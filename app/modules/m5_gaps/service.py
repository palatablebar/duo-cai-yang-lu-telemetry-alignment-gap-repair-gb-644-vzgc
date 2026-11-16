"""缺口编排：修复、落库、缺口段与窗口覆盖视图。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app import store
from app.modules.m2_timebase import contract

from . import repair


def repair_all(kept, analysis) -> repair.RepairResult:
    if analysis is None:
        return repair.RepairResult()
    return repair.repair(kept, analysis.expected)


def persist_grid(conn, run_id: str, points) -> int:
    payload = [
        (
            run_id,
            item.sensor_id,
            item.bucket.strftime("%Y-%m-%dT%H:%M:%SZ"),
            None if item.value is None else str(item.value),
            item.unit,
            item.state,
            item.reason,
            item.fill_policy,
            item.source_row,
        )
        for item in points
    ]
    return store.insert_many(
        conn,
        "INSERT INTO grid(run_id, sensor_id, bucket_utc, value, unit, state, reason,"
        " fill_policy, source_row) VALUES (?,?,?,?,?,?,?,?,?)",
        payload,
    )


def persist_windows(conn, run_id: str, rows) -> int:
    payload = [
        (
            run_id,
            item.sensor_id,
            item.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            item.observed,
            item.expected,
            str(item.coverage),
            item.state,
        )
        for item in rows
    ]
    return store.insert_many(
        conn,
        "INSERT INTO windows(run_id, sensor_id, window_start, observed, expected, coverage, state)"
        " VALUES (?,?,?,?,?,?,?)",
        payload,
    )


def group_runs(points: list[dict]) -> list[dict]:
    """把逐桶的 FILLED/GAP 行按传感器聚成连续段，供缺口表展示。"""
    grouped: list[dict] = []
    current: dict | None = None
    for row in points:
        key = (row["sensor_id"], row["state"], row["reason"])
        if current is not None and current["key"] == key and current["next_index"] == row["index"]:
            current["length"] += 1
            current["next_index"] += 1
            current["end"] = row["bucket_utc"]
            continue
        if current is not None:
            grouped.append(current)
        current = {
            "key": key,
            "sensor_id": row["sensor_id"],
            "state": row["state"],
            "reason": row["reason"],
            "start": row["bucket_utc"],
            "end": row["bucket_utc"],
            "length": 1,
            "start_index": row["index"],
            "next_index": row["index"] + 1,
            "fill_policy": row["fill_policy"],
        }
    if current is not None:
        grouped.append(current)
    return [
        {key: value for key, value in item.items() if key not in {"key", "start_index", "next_index"}}
        for item in grouped
    ]


def gaps_view(conn, run_id: str) -> dict:
    rows = store.rows(
        conn,
        "SELECT * FROM grid WHERE run_id = ? ORDER BY sensor_id, bucket_utc",
        (run_id,),
    )
    indexed = []
    counters: dict[str, int] = {}
    for index, row in enumerate(rows):
        counters[row["sensor_id"]] = counters.get(row["sensor_id"], 0) + 1
        if row["state"] == "OBSERVED":
            continue
        spec = contract.spec(row["sensor_id"])
        indexed.append(
            {
                "index": index,
                "places": spec.places if spec else 3,
                "sensor_id": row["sensor_id"],
                "bucket_utc": row["bucket_utc"],
                "state": row["state"],
                "reason": row["reason"],
                "fill_policy": row["fill_policy"],
                "value": row["value"],
            }
        )

    windows = [
        {
            "sensor_id": row["sensor_id"],
            "start": row["window_start"],
            "observed": row["observed"],
            "expected": row["expected"],
            "coverage": row["coverage"],
            "state": row["state"],
        }
        for row in store.rows(
            conn,
            "SELECT * FROM windows WHERE run_id = ? ORDER BY sensor_id, window_start",
            (run_id,),
        )
    ]
    filled = sum(1 for row in indexed if row["state"] == "FILLED")
    gaps = sum(1 for row in indexed if row["state"] == "GAP")
    partial = sum(1 for row in windows if row["state"] == "PARTIAL")
    return {
        "runs": group_runs(indexed),
        "filled": [row for row in indexed if row["state"] == "FILLED"],
        "windows": windows,
        "summary": {
            "filled": filled,
            "gaps": gaps,
            "windows": len(windows),
            "partial": partial,
            "ok": len(windows) - partial,
            "sensors": len(counters),
        },
    }


def summary(conn, run_id: str) -> dict:
    rows = store.rows(
        conn,
        "SELECT state, COUNT(*) AS n FROM grid WHERE run_id = ? GROUP BY state",
        (run_id,),
    )
    counts = {row["state"]: row["n"] for row in rows}
    return {
        "observed": counts.get("OBSERVED", 0),
        "filled": counts.get("FILLED", 0),
        "gaps": counts.get("GAP", 0),
        "total": sum(counts.values()),
    }
