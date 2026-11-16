"""班次交接编排：交接包、跨班窗口、保留证据、确认/回滚与腾空间判定。

状态机：DRAFT（起草，证据已快照但未确认）→ CONFIRMED（已确认，可腾空间）
        → ROLLED_BACK（交接失败回滚，恢复上一版结果与原始记录）。

幂等：shift_key 由「源批次 + 班次日界」确定性派生并加唯一约束，
同一班次重复交接必然撞键，复用既有交接包，不重复生成窗口与证据。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app import config, errors, manifest, store
from app.modules.m6_batches import history

from . import crosscheck, evidence as evidence_mod, shift_windows

STATE_DRAFT = "DRAFT"
STATE_CONFIRMED = "CONFIRMED"
STATE_ROLLED_BACK = "ROLLED_BACK"

WINDOW_INSERT = (
    "INSERT INTO handover_windows(handover_id, sensor_id, window_start, window_end,"
    " observed, expected, coverage, state, cross_shift, retained)"
    " VALUES (?,?,?,?,?,?,?,?,?,?)"
)
EVIDENCE_INSERT = (
    "INSERT INTO handover_evidence(handover_id, sensor_id, bucket_utc, source_row, value,"
    " unit, quality, raw_value, sample_sha256, window_start, cross_shift)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
)
EVENT_INSERT = (
    "INSERT INTO handover_events(handover_id, seq, event, actor, detail_json, created_at)"
    " VALUES (?,?,?,?,?,?)"
)


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _shift_key(run_id: str, shift_start: str, shift_end: str) -> str:
    material = manifest.canonical_json(
        {"run_id": run_id, "shift_start": shift_start, "shift_end": shift_end}
    )
    return manifest.sha256_bytes(material.encode("utf-8"))


def _handover_id(shift_key: str) -> str:
    return "HO-" + shift_key[:10].upper()


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return {
        "handover_id": row["handover_id"],
        "shift_key": row["shift_key"],
        "run_id": row["run_id"],
        "shift_date": row["shift_date"],
        "shift_start": row["shift_start"],
        "shift_end": row["shift_end"],
        "state": row["state"],
        "previous_id": row["previous_id"],
        "scope": json.loads(row["scope_json"]),
        "checks": json.loads(row["checks_json"]),
        "created_at": row["created_at"],
        "confirmed_at": row["confirmed_at"],
        "rolled_back_at": row["rolled_back_at"],
    }


# ---------------------------------------------------------------- 起草交接包

def prepare_handover(
    conn,
    *,
    run_id: str | None,
    shift_date: str,
    shift_end: str | None = None,
    actor: str = "值班员",
) -> dict:
    target = _resolve_run(conn, run_id)
    try:
        shift_start_dt, shift_end_dt = shift_windows.shift_bounds(shift_date, shift_end)
    except (ValueError, TypeError) as exc:
        raise errors.InputError(
            "班次日界无法解析",
            code="SHIFT_BOUND_INVALID",
            detail={"shift_date": shift_date, "shift_end": shift_end},
        ) from exc

    shift_start = _utc_text(shift_start_dt)
    shift_end = _utc_text(shift_end_dt)
    key = _shift_key(target, shift_start, shift_end)

    existing = store.one(conn, "SELECT * FROM handovers WHERE shift_key = ?", (key,))
    if existing is not None:
        payload = _row_to_dict(existing)
        payload["reused"] = True
        payload["windows"] = windows_of(conn, existing["handover_id"])
        payload["evidence"] = evidence_of(conn, existing["handover_id"])
        payload["events"] = events_of(conn, existing["handover_id"])
        return payload

    stored_windows = store.rows(
        conn,
        "SELECT * FROM windows WHERE run_id = ? ORDER BY sensor_id, window_start",
        (target,),
    )
    windows = shift_windows.collect(stored_windows, shift_start_dt, shift_end_dt)
    if not windows:
        raise errors.InputError(
            "该班次范围内没有任何 15 分钟窗口，无法形成交接包",
            code="SHIFT_WINDOW_EMPTY",
            detail={"shift_start": shift_start, "shift_end": shift_end},
        )

    evidence_rows = evidence_mod.build(conn, target, windows)
    report = crosscheck.cross_check(windows, evidence_rows)
    digest = evidence_mod.snapshot_digest(evidence_rows)

    run = history.get(conn, target)
    scope = _scope(conn, target, run, windows, evidence_rows, digest, shift_start, shift_end)
    checks = {
        "passed": report.passed,
        "lines": [line.as_dict() for line in report.lines],
        "window_mismatches": report.window_mismatches,
        "cross_empty": report.cross_empty,
        "evidence_digest": digest,
    }

    handover_id = _handover_id(key)
    retained_map = evidence_mod.cross_window_sample_count(evidence_rows)
    created_at = now_text()
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO handovers(handover_id, shift_key, run_id, shift_date, shift_start,"
            " shift_end, state, previous_id, scope_json, checks_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                handover_id, key, target, shift_date, shift_start, shift_end,
                STATE_DRAFT, None,
                manifest.canonical_json(scope), manifest.canonical_json(checks), created_at,
            ),
        )
        store.insert_many(
            conn,
            WINDOW_INSERT,
            [
                (
                    handover_id, w.sensor_id,
                    w.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    w.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    w.observed, w.expected, str(w.coverage), w.state,
                    1 if w.cross_shift else 0,
                    retained_map.get(w.key, 0),
                )
                for w in windows
            ],
        )
        store.insert_many(
            conn,
            EVIDENCE_INSERT,
            [
                (
                    handover_id, r.sensor_id, r.bucket_utc, r.source_row, r.value,
                    r.unit, r.quality, r.raw_value, r.sample_sha256, r.window_start, r.cross_shift,
                )
                for r in evidence_rows
            ],
        )
        _add_event(conn, handover_id, "PREPARED", actor, {
            "run_id": target, "windows": len(windows),
            "cross_windows": sum(1 for w in windows if w.cross_shift),
            "evidence": len(evidence_rows), "checks_passed": report.passed,
        })

    return get_handover(conn, handover_id)


def _scope(conn, run_id, run, windows, evidence_rows, digest, shift_start, shift_end) -> dict:
    cross = [w for w in windows if w.cross_shift]
    raw_in_shift = store.value(
        conn,
        "SELECT COUNT(*) FROM samples WHERE run_id = ?"
        " AND bucket_utc >= ? AND bucket_utc < ?",
        (run_id, shift_start, shift_end),
        0,
    )
    return {
        "run_id": run_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "windows_total": len(windows),
        "cross_windows": len(cross),
        "retained_samples": len(evidence_rows),
        "samples_in_shift": int(raw_in_shift),
        "accepted": run["accepted"] if run else 0,
        "quarantined": run["quarantined"] if run else 0,
        "grid_points": run["grid_points"] if run else 0,
        "balanced": run["balanced"] if run else False,
        "evidence_digest": digest,
    }


# ---------------------------------------------------------------- 确认 / 腾空间

def confirm_handover(conn, handover_id: str, *, actor: str = "值班员") -> dict:
    row = _require(conn, handover_id)
    if row["state"] == STATE_CONFIRMED:
        return get_handover(conn, handover_id)  # 幂等：重复确认不报错也不重复生成
    if row["state"] == STATE_ROLLED_BACK:
        raise errors.StateError(
            "交接包已回滚，不能确认；请重新起草",
            code="HANDOVER_ROLLED_BACK",
            detail={"handover_id": handover_id},
        )

    checks = json.loads(row["checks_json"])
    if not checks.get("passed"):
        raise errors.StateError(
            "交叉复核未通过，不能确认交接",
            code="HANDOVER_CHECK_FAILED",
            detail={"handover_id": handover_id, "failures": checks.get("cross_empty", [])},
        )

    # 记录被取代的上一版已确认交接包，供回滚恢复
    previous = store.one(
        conn,
        "SELECT handover_id FROM handovers WHERE state = ? AND handover_id != ?"
        " ORDER BY confirmed_at DESC LIMIT 1",
        (STATE_CONFIRMED, handover_id),
    )
    with store.transaction(conn):
        conn.execute(
            "UPDATE handovers SET state = ?, confirmed_at = ?, previous_id = ?"
            " WHERE handover_id = ?",
            (STATE_CONFIRMED, now_text(), previous["handover_id"] if previous else None, handover_id),
        )
        _add_event(conn, handover_id, "CONFIRMED", actor, {
            "previous_id": previous["handover_id"] if previous else None,
        })
    return get_handover(conn, handover_id)


def reclaim_decision(conn, handover_id: str) -> dict:
    """先腾空间还是等证据齐备：只看交接包状态、证据与复核结果，不替值班员动手。"""
    row = _require(conn, handover_id)
    scope = json.loads(row["scope_json"])
    checks = json.loads(row["checks_json"])
    blockers: list[str] = []

    if row["state"] != STATE_CONFIRMED:
        blockers.append("交接包尚未确认（状态 %s）" % row["state"])
    if not checks.get("passed"):
        blockers.append("窗口与采样交叉复核未通过")
    if scope.get("cross_windows", 0) > 0 and checks.get("evidence_digest") in (None, ""):
        blockers.append("跨班窗口缺少证据快照摘要")
    if not scope.get("balanced"):
        blockers.append("源批次四账不平，已发布结果缺依据")

    reclaimable = not blockers
    return {
        "handover_id": handover_id,
        "state": row["state"],
        "reclaimable": reclaimable,
        "decision": "RECLAIM_NOW" if reclaimable else "WAIT_EVIDENCE",
        "blockers": blockers,
        "cross_windows": scope.get("cross_windows", 0),
        "retained_samples": scope.get("retained_samples", 0),
        "evidence_digest": checks.get("evidence_digest", ""),
        "note": "可腾空间：仅清理交接范围之外的在线数据，跨班窗口与证据保留至下一班补算完成"
        if reclaimable else "证据未齐备，禁止清理，等待复核通过并确认",
    }


def reclaim_space(conn, handover_id: str, *, actor: str = "值班员") -> dict:
    """执行腾空间。

    只清理「班末之外」且「已被证据快照覆盖」的在线数据：跨班窗口的原始采样先有独立
    快照才允许删除在线副本，因此每一条被删采样都能在回滚时从快照追回；班内数据与
    交接包、证据快照原样保留。网格点与窗口登记同步清到班末。
    """
    decision = reclaim_decision(conn, handover_id)
    if not decision["reclaimable"]:
        raise errors.StateError(
            "腾空间被阻塞：" + "；".join(decision["blockers"]),
            code="RECLAIM_BLOCKED",
            detail={"handover_id": handover_id, "blockers": decision["blockers"]},
        )
    row = _require(conn, handover_id)
    run_id = row["run_id"]
    shift_end = row["shift_end"]
    retained = scope_retained = json.loads(row["scope_json"]).get("retained_samples", 0)
    with store.transaction(conn):
        # 仅删除证据快照里有对应记录的在线采样，保证可逐条恢复
        cur = conn.execute(
            "DELETE FROM samples WHERE run_id = ? AND bucket_utc >= ?"
            " AND EXISTS ("
            "  SELECT 1 FROM handover_evidence he WHERE he.handover_id = ?"
            "  AND he.sensor_id = samples.sensor_id AND he.bucket_utc = samples.bucket_utc"
            ")",
            (run_id, shift_end, handover_id),
        )
        removed_samples = cur.rowcount
        cur = conn.execute(
            "DELETE FROM grid WHERE run_id = ? AND bucket_utc >= ?",
            (run_id, shift_end),
        )
        removed_grid = cur.rowcount
        cur = conn.execute(
            "DELETE FROM windows WHERE run_id = ? AND window_start >= ?",
            (run_id, shift_end),
        )
        removed_windows = cur.rowcount
        _add_event(conn, handover_id, "RECLAIMED", actor, {
            "removed_samples": removed_samples,
            "removed_grid": removed_grid,
            "removed_windows": removed_windows,
            "kept_evidence": scope_retained,
        })
    return {
        "handover_id": handover_id,
        "removed_samples": removed_samples,
        "removed_grid": removed_grid,
        "removed_windows": removed_windows,
        "kept_evidence": retained,
        "decision": decision,
    }


# ---------------------------------------------------------------- 回滚

def rollback_handover(conn, handover_id: str, *, actor: str = "值班员") -> dict:
    """交接失败：回滚到上一版已确认结果；原始记录从证据快照恢复。"""
    row = _require(conn, handover_id)
    if row["state"] == STATE_ROLLED_BACK:
        return get_handover(conn, handover_id)  # 幂等
    previous_id = row["previous_id"]

    restored_samples = 0
    with store.transaction(conn):
        if previous_id:
            prev = store.one(
                conn, "SELECT * FROM handovers WHERE handover_id = ?", (previous_id,)
            )
            if prev is not None and prev["state"] != STATE_ROLLED_BACK:
                conn.execute(
                    "UPDATE handovers SET state = ? WHERE handover_id = ?",
                    (STATE_CONFIRMED, previous_id),
                )
        # 从证据快照恢复原始记录：若在线采样已被清理，按快照重新落回 samples
        run_id = row["run_id"]
        for ev in store.rows(
            conn, "SELECT * FROM handover_evidence WHERE handover_id = ?", (handover_id,)
        ):
            exists = store.one(
                conn,
                "SELECT 1 FROM samples WHERE run_id = ? AND sensor_id = ? AND bucket_utc = ?",
                (run_id, ev["sensor_id"], ev["bucket_utc"]),
            )
            if exists is None:
                conn.execute(
                    "INSERT INTO samples(run_id, source_row, sensor_id, bucket_utc, value,"
                    " unit, quality, quality_rank, ingest_seq, offset_seconds, late, flags)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, ev["source_row"], ev["sensor_id"], ev["bucket_utc"], ev["value"],
                        ev["unit"], ev["quality"], config.QUALITY_RANK.get(ev["quality"], 0),
                        ev["source_row"], 0, 0, "RESTORED_FROM_HANDOVER",
                    ),
                )
                restored_samples += 1
        conn.execute(
            "UPDATE handovers SET state = ?, rolled_back_at = ? WHERE handover_id = ?",
            (STATE_ROLLED_BACK, now_text(), handover_id),
        )
        _add_event(conn, handover_id, "ROLLED_BACK", actor, {
            "previous_id": previous_id, "restored_samples": restored_samples,
        })
    payload = get_handover(conn, handover_id)
    payload["restored_previous_id"] = previous_id
    payload["restored_samples"] = restored_samples
    return payload


# ---------------------------------------------------------------- 查询

def _resolve_run(conn, run_id: str | None) -> str:
    if run_id:
        if history.get(conn, run_id) is None:
            raise errors.NotFoundError("批次不存在", code="RUN_NOT_FOUND", detail={"run_id": run_id})
        return run_id
    latest = history.latest(conn)
    if latest is None:
        raise errors.NotFoundError("还没有批次，无法交接", code="NO_RUN")
    return latest["run_id"]


def _require(conn, handover_id: str):
    row = store.one(conn, "SELECT * FROM handovers WHERE handover_id = ?", (handover_id,))
    if row is None:
        raise errors.NotFoundError(
            "交接包不存在", code="HANDOVER_NOT_FOUND", detail={"handover_id": handover_id}
        )
    return row


def get_handover(conn, handover_id: str) -> dict:
    row = _require(conn, handover_id)
    payload = _row_to_dict(row)
    payload["reused"] = False
    payload["windows"] = windows_of(conn, handover_id)
    payload["evidence"] = evidence_of(conn, handover_id)
    payload["events"] = events_of(conn, handover_id)
    return payload


def list_handovers(conn) -> dict:
    rows = store.rows(
        conn,
        "SELECT handover_id, run_id, shift_date, shift_start, shift_end, state, previous_id,"
        " scope_json, checks_json, created_at, confirmed_at, rolled_back_at, shift_key"
        " FROM handovers ORDER BY created_at DESC, handover_id",
    )
    items = []
    for row in rows:
        item = _row_to_dict(row)
        item["reused"] = False
        items.append(item)
    return {
        "handovers": items,
        "count": len(items),
        "latest": items[0] if items else None,
    }


def windows_of(conn, handover_id: str) -> list[dict]:
    return [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT sensor_id, window_start, window_end, observed, expected, coverage,"
            " state, cross_shift, retained FROM handover_windows"
            " WHERE handover_id = ? ORDER BY sensor_id, window_start",
            (handover_id,),
        )
    ]


def evidence_of(conn, handover_id: str, limit: int | None = None) -> list[dict]:
    sql = (
        "SELECT sensor_id, bucket_utc, source_row, value, unit, quality, raw_value,"
        " sample_sha256, window_start, cross_shift FROM handover_evidence WHERE handover_id = ?"
        " ORDER BY sensor_id, bucket_utc"
    )
    params: tuple = (handover_id,)
    if limit is not None:
        sql += " LIMIT ?"
        params = (handover_id, limit)
    return [dict(row) for row in store.rows(conn, sql, params)]


def events_of(conn, handover_id: str) -> list[dict]:
    return [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT seq, event, actor, detail_json, created_at FROM handover_events"
            " WHERE handover_id = ? ORDER BY seq",
            (handover_id,),
        )
    ]


def _add_event(conn, handover_id: str, event: str, actor: str, detail: dict) -> None:
    seq = int(store.value(
        conn,
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM handover_events WHERE handover_id = ?",
        (handover_id,), 1,
    ))
    conn.execute(
        EVENT_INSERT,
        (handover_id, seq, event, actor, manifest.canonical_json(detail), now_text()),
    )
