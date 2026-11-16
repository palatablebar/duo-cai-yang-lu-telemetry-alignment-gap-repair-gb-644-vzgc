"""批次编排：一次导入跑完采信 → 时基 → 质量 → 网格 → 缺口，落库并核四账。

幂等由 run_key 唯一约束保证；落库整体在一个事务里，异常回滚不留半张表。
"""

from __future__ import annotations

import json
import time
from decimal import Decimal, ROUND_HALF_UP

from app import config, errors, manifest, store

from app.modules.m1_intake import service as intake_service
from app.modules.m2_timebase import service as timebase_service
from app.modules.m3_quality import quarantine as quarantine_store
from app.modules.m3_quality import service as quality_service
from app.modules.m4_grid import service as grid_service
from app.modules.m5_gaps import service as gaps_service

from . import compare, diff, history

RECONCILE_INSERT = (
    "INSERT INTO reconcile(run_id, line_no, name, expected, actual, delta, state, note)"
    " VALUES (?,?,?,?,?,?,?,?)"
)


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal(1).scaleb(-config.VALUE_PLACES), rounding=ROUND_HALF_UP)


def _params() -> dict:
    return {
        "grid_minutes": config.GRID_MINUTES,
        "window_minutes": config.WINDOW_MINUTES,
        "max_fill_buckets": config.MAX_FILL_BUCKETS,
        "late_window_minutes": config.LATE_WINDOW_MINUTES,
    }


def _lines_of(conn, run_id: str) -> list[compare.ReconcileLine]:
    rows = store.rows(
        conn, "SELECT * FROM reconcile WHERE run_id = ? ORDER BY line_no", (run_id,)
    )
    return [
        compare.ReconcileLine(
            line_no=row["line_no"],
            name=row["name"],
            expected=Decimal(row["expected"]),
            actual=Decimal(row["actual"]),
            note=row["note"],
        )
        for row in rows
    ]


def _result(conn, run: dict, *, reused: bool, lines: list[compare.ReconcileLine]) -> dict:
    detail = history.manifest_of(conn, run["run_id"]) or {}
    return {
        "run_id": run["run_id"],
        "run_key": run["run_key"],
        "created_at": run["created_at"],
        "sample": run["sample_name"],
        "offsets": run["offset_name"],
        "reused": reused,
        "counts": run["counts"],
        "totals": run["totals"],
        "balanced": run["counts"].get("balanced", False),
        "empty_code": run["counts"].get("empty_code"),
        "reconcile": [compare.as_dict(line) for line in lines],
        "conclusion": diff.conclusion(lines),
        "elapsed_ms": run["elapsed_ms"],
        "inputs": detail.get("inputs", []),
        "rule_version": run["rule_version"],
    }


def execute_run(conn, *, sample: str, offsets: str) -> dict:
    started = time.monotonic()
    loaded = intake_service.load_sample(sample)
    table = timebase_service.load_offsets(offsets)

    inputs = [
        {"name": loaded.file_name, "sha256": loaded.sha256, "bytes": loaded.size},
        {"name": table.file_name, "sha256": table.sha256, "bytes": table.size},
    ]
    params = _params()
    key = manifest.run_key(inputs, config.RULE_VERSION, params)

    existing = history.find_by_key(conn, key)
    if existing is not None:
        return _result(conn, existing, reused=True, lines=_lines_of(conn, existing["run_id"]))

    run_id = manifest.run_id_for(key)

    normalized = timebase_service.normalize(loaded, table)
    judged = quality_service.judge_all(normalized.rows)

    rejects: list[dict] = []
    for issue in loaded.issues:
        rejects.append(
            {
                "source_row": issue.source_row,
                "sensor_id": "",
                "column_name": "*",
                "raw_value": issue.raw[:200],
                "code": issue.code,
                "detail": issue.detail,
            }
        )
    for reject in normalized.rejects:
        rejects.append(
            {
                "source_row": reject.source_row,
                "sensor_id": reject.sensor_id,
                "column_name": reject.column_name,
                "raw_value": reject.raw_value,
                "code": reject.code,
                "detail": reject.detail,
            }
        )
    rejects.extend(judged.rejects)

    aligned = grid_service.align_rows(judged.judged)
    analysis = grid_service.analyse(aligned.kept)
    repaired = gaps_service.repair_all(aligned.kept, analysis)

    accepted_sum = sum((row.value for row in aligned.kept), Decimal("0"))
    observed_sum = sum(
        (point.value for point in repaired.points if point.state == "OBSERVED"), Decimal("0")
    )
    filled_sum = sum(
        (point.value for point in repaired.points if point.state == "FILLED"), Decimal("0")
    )

    counts = {
        "raw_records": loaded.data_rows,
        "accepted": len(aligned.kept),
        "duplicates": len(aligned.duplicates),
        "quarantined": len(rejects),
        "expected_buckets": sum(len(item) for item in analysis.expected.values()) if analysis else 0,
        "observed": repaired.observed,
        "filled": repaired.filled,
        "gaps": repaired.gaps,
        "grid_points": repaired.total,
        "windows": len(analysis.windows) if analysis else 0,
        "windows_stored": 0,
        "blank_lines": loaded.blank_lines,
        "segments": loaded.segments,
        "truncated": 1 if loaded.truncated else 0,
        "late": sum(1 for row in aligned.kept if row.late),
        "empty_code": loaded.empty_code,
        "balanced": False,
    }
    totals = {
        "accepted_sum": str(_q(accepted_sum)),
        "observed_sum": str(_q(observed_sum)),
        "filled_sum": str(_q(filled_sum)),
        "grid_sum": str(_q(observed_sum + filled_sum)),
    }

    created_at = history.now_text()
    lines: list[compare.ReconcileLine] = []
    with store.transaction(conn):
        timebase_service.store_offsets(conn, run_id, table.entries)
        quality_service.persist_samples(conn, run_id, aligned.kept)
        grid_service.persist_duplicates(conn, run_id, aligned.duplicates)
        gaps_service.persist_grid(conn, run_id, repaired.points)
        gaps_service.persist_windows(conn, run_id, analysis.windows if analysis else [])
        quarantine_store.write(conn, run_id, rejects)

        counts["windows_stored"] = int(
            store.value(conn, "SELECT COUNT(*) FROM windows WHERE run_id = ?", (run_id,), 0)
        )
        lines = compare.reconcile_lines(counts, totals)
        counts["balanced"] = compare.is_balanced(lines)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        history.save(
            conn,
            {
                "run_id": run_id,
                "run_key": key,
                "created_at": created_at,
                "rule_version": config.RULE_VERSION,
                "sample_name": loaded.file_name,
                "offset_name": table.file_name,
                "params": params,
                "inputs": inputs,
                "counts": counts,
                "totals": totals,
                "elapsed_ms": elapsed_ms,
            },
        )
        history.save_intake(
            conn,
            run_id,
            {
                "encoding": loaded.encoding,
                "bom": loaded.bom,
                "delimiter": loaded.delimiter,
                "header": list(loaded.header),
                "segments": loaded.segments,
                "blank_lines": loaded.blank_lines,
                "truncated": loaded.truncated,
                "byte_size": loaded.size,
                "sha256": loaded.sha256,
            },
        )
        store.insert_many(
            conn,
            RECONCILE_INSERT,
            [
                (
                    run_id,
                    line.line_no,
                    line.name,
                    str(line.expected),
                    str(line.actual),
                    str(line.delta),
                    line.state,
                    line.note,
                )
                for line in lines
            ],
        )

    run = history.get(conn, run_id)
    return _result(conn, run, reused=False, lines=lines)


def _stages(counts: dict) -> list[dict]:
    return [
        {"name": "原始行", "value": counts.get("raw_records", 0), "unit": "行"},
        {"name": "采纳", "value": counts.get("accepted", 0), "unit": "行"},
        {"name": "重复", "value": counts.get("duplicates", 0), "unit": "行"},
        {"name": "隔离", "value": counts.get("quarantined", 0), "unit": "行"},
        {"name": "网格点", "value": counts.get("grid_points", 0), "unit": "个"},
        {"name": "补齐", "value": counts.get("filled", 0), "unit": "个"},
        {"name": "缺口", "value": counts.get("gaps", 0), "unit": "个"},
        {"name": "窗口", "value": counts.get("windows", 0), "unit": "个"},
    ]


def overview(conn) -> dict:
    run = history.latest(conn)
    payload = {
        "run": run,
        "counts": {},
        "totals": {},
        "lines": [],
        "stages": [],
        "balanced": False,
        "conclusion": "",
    }
    if run is None:
        return payload
    lines = _lines_of(conn, run["run_id"])
    payload.update(
        {
            "counts": run["counts"],
            "totals": run["totals"],
            "lines": [compare.as_dict(line) for line in lines],
            "stages": _stages(run["counts"]),
            "balanced": run["counts"].get("balanced", False),
            "conclusion": diff.conclusion(lines),
        }
    )
    return payload


def reconcile_view(conn, run_id: str | None = None) -> dict:
    run = history.get(conn, run_id) if run_id else history.latest(conn)
    if run is None:
        raise errors.NotFoundError("还没有批次", code="NO_RUN")
    lines = _lines_of(conn, run["run_id"])
    return {
        "run": run,
        "lines": [compare.as_dict(line) for line in lines],
        "hints": diff.explain(lines, run["counts"]),
        "conclusion": diff.conclusion(lines),
        "counts": run["counts"],
        "totals": run["totals"],
        "balanced": compare.is_balanced(lines),
    }


def runs_view(conn) -> dict:
    runs = history.list_runs(conn)
    return {"runs": runs, "latest": runs[0] if runs else None}


def _rebuild(conn, run_id: str):
    judged = quality_service.load_judged(conn, run_id)
    analysis = grid_service.analyse(judged)
    repaired = gaps_service.repair_all(judged, analysis)
    return analysis, repaired


def verify_grid(conn, run_id: str) -> dict:
    _, repaired = _rebuild(conn, run_id)
    stored = store.rows(
        conn,
        "SELECT sensor_id, bucket_utc, value, state, reason FROM grid"
        " WHERE run_id = ? ORDER BY sensor_id, bucket_utc",
        (run_id,),
    )
    derived = [
        {
            "sensor_id": point.sensor_id,
            "bucket_utc": point.bucket.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value": None if point.value is None else str(point.value),
            "state": point.state,
            "reason": point.reason,
        }
        for point in repaired.points
    ]
    mismatches = []
    for index, item in enumerate(derived):
        counterpart = dict(stored[index]) if index < len(stored) else None
        if counterpart != item:
            mismatches.append({"index": index, "derived": item, "stored": counterpart})
            if len(mismatches) >= 20:
                break
    return {
        "run_id": run_id,
        "verified": not mismatches and len(derived) == len(stored),
        "derived_points": len(derived),
        "stored_points": len(stored),
        "counts": repaired.counts(),
        "mismatches": mismatches,
    }


def verify_gaps(conn, run_id: str) -> dict:
    analysis, repaired = _rebuild(conn, run_id)
    derived_windows = len(analysis.windows) if analysis else 0
    stored_windows = int(
        store.value(conn, "SELECT COUNT(*) FROM windows WHERE run_id = ?", (run_id,), 0)
    )
    stored_filled = int(
        store.value(conn, "SELECT COUNT(*) FROM grid WHERE run_id = ? AND state = 'FILLED'", (run_id,), 0)
    )
    stored_gaps = int(
        store.value(conn, "SELECT COUNT(*) FROM grid WHERE run_id = ? AND state = 'GAP'", (run_id,), 0)
    )
    verified = (
        derived_windows == stored_windows
        and repaired.filled == stored_filled
        and repaired.gaps == stored_gaps
    )
    return {
        "run_id": run_id,
        "verified": verified,
        "derived": {"filled": repaired.filled, "gaps": repaired.gaps, "windows": derived_windows},
        "stored": {"filled": stored_filled, "gaps": stored_gaps, "windows": stored_windows},
        "runs": {"plans": len(repaired.plans)},
    }


def run_detail(conn, run_id: str) -> dict:
    run = history.get(conn, run_id)
    if run is None:
        raise errors.NotFoundError("批次不存在", code="RUN_NOT_FOUND", detail={"run_id": run_id})
    detail = history.manifest_of(conn, run_id) or {}
    return {"run": run, "manifest": detail, "lines": [compare.as_dict(line) for line in _lines_of(conn, run_id)]}


def counts_json(conn, run_id: str) -> str:
    run = history.get(conn, run_id)
    return json.dumps(run["counts"] if run else {}, ensure_ascii=False, sort_keys=True)
