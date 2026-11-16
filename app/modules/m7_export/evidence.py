"""证据行：把网格上的一个点追回原始行、原值与原因码。

页面上每个点都能点开看这三件事，导出里的 source_row 与 reason 与之一致。
"""

from __future__ import annotations

from app import reasons, store


def cell(conn, run_id: str, sensor_id: str, bucket_utc: str) -> dict | None:
    grid = store.one(
        conn,
        "SELECT * FROM grid WHERE run_id = ? AND sensor_id = ? AND bucket_utc = ?",
        (run_id, sensor_id, bucket_utc),
    )
    if grid is None:
        return None

    sample = store.one(
        conn,
        "SELECT * FROM samples WHERE run_id = ? AND sensor_id = ? AND bucket_utc = ?",
        (run_id, sensor_id, bucket_utc),
    )
    source_row = grid["source_row"] or (sample["source_row"] if sample else None)
    quarantined = []
    if source_row is not None:
        quarantined = [
            dict(row)
            for row in store.rows(
                conn,
                "SELECT * FROM quarantine WHERE run_id = ? AND source_row = ?",
                (run_id, source_row),
            )
        ]
    duplicates = [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT * FROM duplicates WHERE run_id = ? AND sensor_id = ? AND bucket_utc = ?",
            (run_id, sensor_id, bucket_utc),
        )
    ]
    return {
        "run_id": run_id,
        "sensor_id": grid["sensor_id"],
        "bucket_utc": grid["bucket_utc"],
        "state": grid["state"],
        "value": grid["value"],
        "unit": grid["unit"],
        "reason": grid["reason"],
        "reason_label": reasons.label(grid["reason"]) if grid["reason"] else "",
        "fill_policy": grid["fill_policy"],
        "source_row": source_row,
        "quality": sample["quality"] if sample else None,
        "ingest_seq": sample["ingest_seq"] if sample else None,
        "offset_seconds": sample["offset_seconds"] if sample else None,
        "flags": (sample["flags"] if sample else "") or "",
        "quarantine": quarantined,
        "duplicates": duplicates,
    }


def trailing(conn, run_id: str, limit: int = 20) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT sensor_id, bucket_utc, state, value, reason, source_row FROM grid"
        " WHERE run_id = ? AND state != 'OBSERVED' ORDER BY sensor_id, bucket_utc LIMIT ?",
        (run_id, limit),
    )
    return [
        {
            "sensor_id": row["sensor_id"],
            "bucket_utc": row["bucket_utc"],
            "state": row["state"],
            "value": row["value"],
            "reason": reasons.label(row["reason"]) if row["reason"] else "",
            "source_row": row["source_row"],
        }
        for row in rows
    ]


def count(conn, run_id: str) -> dict:
    states = {
        row["state"]: row["n"]
        for row in store.rows(
            conn,
            "SELECT state, COUNT(*) AS n FROM grid WHERE run_id = ? GROUP BY state",
            (run_id,),
        )
    }
    return {
        "observed": states.get("OBSERVED", 0),
        "filled": states.get("FILLED", 0),
        "gaps": states.get("GAP", 0),
    }
