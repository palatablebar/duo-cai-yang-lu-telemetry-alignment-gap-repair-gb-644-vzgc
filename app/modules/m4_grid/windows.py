"""15 分钟窗口覆盖度。

覆盖度 = 实有桶数 / 应有桶数，应有桶数按传感器采样率派生；
低于阈值记 PARTIAL，但窗口本身照常输出，不做任何插入或删除。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app import config


@dataclass(frozen=True)
class WindowRow:
    sensor_id: str
    start: datetime
    end: datetime
    observed: int
    expected: int
    coverage: Decimal
    state: str


def ratio(observed: int, expected: int) -> Decimal:
    if expected <= 0:
        return Decimal("0.000")
    return (Decimal(observed) / Decimal(expected)).quantize(
        Decimal(1).scaleb(-config.COVERAGE_PLACES), rounding=ROUND_HALF_UP
    )


def state_of(coverage: Decimal) -> str:
    return "PARTIAL" if coverage < Decimal(config.PARTIAL_COVERAGE) else "OK"


def for_sensor(
    sensor_id: str,
    expected: list[datetime],
    observed: set[datetime],
    window_bounds: list[tuple[datetime, datetime]],
    end: datetime,
) -> list[WindowRow]:
    rows: list[WindowRow] = []
    expected_set = set(expected)
    for start, stop in window_bounds:
        limit = min(stop, end)
        exp = sum(1 for bucket in expected_set if start <= bucket < limit)
        obs = sum(1 for bucket in observed if start <= bucket < limit)
        coverage = ratio(obs, exp)
        rows.append(
            WindowRow(
                sensor_id=sensor_id,
                start=start,
                end=limit,
                observed=obs,
                expected=exp,
                coverage=coverage,
                state=state_of(coverage),
            )
        )
    return rows


def summarize(rows: list[WindowRow]) -> dict:
    total = len(rows)
    partial = sum(1 for row in rows if row.state == "PARTIAL")
    observed = sum(row.observed for row in rows)
    expected = sum(row.expected for row in rows)
    return {
        "windows": total,
        "partial": partial,
        "ok": total - partial,
        "observed": observed,
        "expected": expected,
        "coverage": ratio(observed, expected),
    }
