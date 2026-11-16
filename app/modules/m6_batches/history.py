"""批次历史：运行清单的读写与查询。

run_key 唯一约束是幂等的物理保证：同一输入同参数第二次导入必然撞键，
事务不会插入半张表。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app import manifest, store

RUN_COLUMNS = (
    "run_id, run_key, created_at, rule_version, sample_name, offset_name,"
    " counts_json, totals_json, elapsed_ms"
)


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    counts = json.loads(row["counts_json"])
    totals = json.loads(row["totals_json"])
    return {
        "run_id": row["run_id"],
        "run_key": row["run_key"],
        "created_at": row["created_at"],
        "rule_version": row["rule_version"],
        "sample_name": row["sample_name"],
        "offset_name": row["offset_name"],
        "counts": counts,
        "totals": totals,
        "elapsed_ms": row["elapsed_ms"],
        "empty_code": counts.get("empty_code"),
        "raw_records": counts.get("raw_records", 0),
        "accepted": counts.get("accepted", 0),
        "duplicates": counts.get("duplicates", 0),
        "quarantined": counts.get("quarantined", 0),
        "grid_points": counts.get("grid_points", 0),
        "filled": counts.get("filled", 0),
        "gaps": counts.get("gaps", 0),
        "balanced": counts.get("balanced", False),
    }


def get(conn, run_id: str) -> dict | None:
    return _row_to_dict(store.one(conn, f"SELECT {RUN_COLUMNS} FROM runs WHERE run_id = ?", (run_id,)))


def find_by_key(conn, run_key: str) -> dict | None:
    return _row_to_dict(
        store.one(conn, f"SELECT {RUN_COLUMNS} FROM runs WHERE run_key = ?", (run_key,))
    )


def latest(conn) -> dict | None:
    return _row_to_dict(
        store.one(conn, f"SELECT {RUN_COLUMNS} FROM runs ORDER BY created_at DESC, run_id LIMIT 1")
    )


def list_runs(conn, limit: int = 40) -> list[dict]:
    rows = store.rows(
        conn,
        f"SELECT {RUN_COLUMNS} FROM runs ORDER BY created_at DESC, run_id LIMIT ?",
        (limit,),
    )
    return [_row_to_dict(row) for row in rows]


def save(conn, payload: dict) -> None:
    store.insert_many(
        conn,
        "INSERT INTO runs(run_id, run_key, created_at, rule_version, sample_name,"
        " offset_name, params_json, input_json, counts_json, totals_json, elapsed_ms)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                payload["run_id"],
                payload["run_key"],
                payload["created_at"],
                payload["rule_version"],
                payload["sample_name"],
                payload["offset_name"],
                manifest.canonical_json(payload["params"]),
                manifest.canonical_json(payload["inputs"]),
                manifest.canonical_json(payload["counts"]),
                manifest.canonical_json(payload["totals"]),
                payload["elapsed_ms"],
            )
        ],
    )


def save_intake(conn, run_id: str, intake: dict) -> None:
    store.insert_many(
        conn,
        "INSERT INTO intake(run_id, encoding, bom, delimiter, header_json, segments,"
        " blank_lines, truncated, byte_size, sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                run_id,
                intake["encoding"],
                1 if intake["bom"] else 0,
                intake["delimiter"],
                json.dumps(intake["header"], ensure_ascii=False),
                intake["segments"],
                intake["blank_lines"],
                1 if intake["truncated"] else 0,
                intake["byte_size"],
                intake["sha256"],
            )
        ],
    )


def manifest_of(conn, run_id: str) -> dict | None:
    row = store.one(conn, "SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if row is None:
        return None
    return manifest.build_manifest(
        run_id=row["run_id"],
        key=row["run_key"],
        created_at=row["created_at"],
        rule_version=row["rule_version"],
        sample_name=row["sample_name"],
        offset_name=row["offset_name"],
        inputs=json.loads(row["input_json"]),
        params=json.loads(row["params_json"]),
        counts=json.loads(row["counts_json"]),
        totals=json.loads(row["totals_json"]),
        elapsed_ms=row["elapsed_ms"],
    )


def now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
