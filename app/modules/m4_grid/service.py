"""网格编排：去重、全局区间、应有桶与窗口覆盖。

全局区间起点按 15 分钟对齐，终点取「最大桶 + 1 分钟」，右端开；
每个传感器的应有桶由采样率决定，因此 5 分钟传感器的覆盖度不会被 1 分钟传感器拉低。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app import store

from app.modules.m2_timebase import contract

from . import align, bucket, windows


@dataclass
class Analysis:
    start: datetime
    end: datetime
    expected: dict[str, list[datetime]] = field(default_factory=dict)
    observed: dict[str, set] = field(default_factory=dict)
    windows: list = field(default_factory=list)


def align_rows(judged) -> align.AlignResult:
    return align.align(judged)


def analyse(kept) -> Analysis | None:
    if not kept:
        return None
    start, end = bucket.range_of([row.bucket for row in kept])
    per_sensor: dict[str, set] = {}
    for row in kept:
        per_sensor.setdefault(row.sensor_id, set()).add(row.bucket)

    bounds = bucket.windows(start, end)
    analysis = Analysis(start=start, end=end)
    for sensor_id in sorted(per_sensor):
        spec = contract.spec(sensor_id)
        if spec is None:  # pragma: no cover - 采纳前已过滤未知传感器
            continue
        expected = contract.expected_minutes(spec.rate_minutes, start, end)
        analysis.expected[sensor_id] = expected
        analysis.observed[sensor_id] = per_sensor[sensor_id]
        analysis.windows.extend(
            windows.for_sensor(sensor_id, expected, per_sensor[sensor_id], bounds, end)
        )
    return analysis


def persist_duplicates(conn, run_id: str, duplicates) -> int:
    payload = [
        (
            run_id,
            item.sensor_id,
            item.bucket.strftime("%Y-%m-%dT%H:%M:%SZ"),
            item.kept_row,
            item.dropped_row,
            item.kept_value,
            item.dropped_value,
            item.kept_quality,
            item.dropped_quality,
            item.code,
        )
        for item in duplicates
    ]
    return store.insert_many(
        conn,
        "INSERT INTO duplicates(run_id, sensor_id, bucket_utc, kept_row, dropped_row,"
        " kept_value, dropped_value, kept_quality, dropped_quality, code)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        payload,
    )


def duplicate_rows(conn, run_id: str) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT * FROM duplicates WHERE run_id = ? ORDER BY sensor_id, bucket_utc",
        (run_id,),
    )
    return [dict(row) for row in rows]


def grid_view(conn, run_id: str) -> dict:
    rows = store.rows(
        conn,
        "SELECT * FROM grid WHERE run_id = ? ORDER BY sensor_id, bucket_utc",
        (run_id,),
    )
    states: dict[str, int] = {}
    points = []
    for row in rows:
        states[row["state"]] = states.get(row["state"], 0) + 1
        item = dict(row)
        spec = contract.spec(row["sensor_id"])
        item["places"] = spec.places if spec else 3
        points.append(item)
    letters = "ABCDEFGH"
    return {
        "total": len(rows),
        "points": points[:400],
        "states": states,
        "sensors": sorted({row["sensor_id"] for row in rows}),
        "letters": list(letters[:8]),
    }


def bucket_bounds(conn, run_id: str) -> tuple[str, str] | None:
    row = store.one(
        conn,
        "SELECT MIN(bucket_utc) AS lo, MAX(bucket_utc) AS hi FROM grid WHERE run_id = ?",
        (run_id,),
    )
    if row is None or row["lo"] is None:
        return None
    return row["lo"], row["hi"]
