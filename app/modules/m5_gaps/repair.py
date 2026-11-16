"""缺口修复：把实有、补齐、缺口合成一张网格。

每个应有桶恰好落进三种状态之一：OBSERVED（实有）、FILLED（补齐）、GAP（缺口），
所以「应有桶数 = 实有 + 补齐 + 缺口」不是巧合，而是构造出来的等式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from . import fill, policy


@dataclass(frozen=True)
class GridPoint:
    sensor_id: str
    bucket: datetime
    value: Decimal | None
    unit: str
    state: str
    reason: str
    fill_policy: str
    source_row: int | None


@dataclass
class RepairResult:
    points: list[GridPoint] = field(default_factory=list)
    plans: list[dict] = field(default_factory=list)
    observed: int = 0
    filled: int = 0
    gaps: int = 0

    @property
    def total(self) -> int:
        return self.observed + self.filled + self.gaps

    def counts(self) -> dict:
        return {
            "grid_points": self.total,
            "observed": self.observed,
            "filled": self.filled,
            "gaps": self.gaps,
        }


def repair(kept_rows, expected: dict[str, list[datetime]]) -> RepairResult:
    by_sensor: dict[str, list] = {}
    for row in kept_rows:
        by_sensor.setdefault(row.sensor_id, []).append(row)

    result = RepairResult()
    for sensor_id in sorted(by_sensor):
        rows = sorted(by_sensor[sensor_id], key=lambda item: item.bucket)
        spec = rows[0].spec
        sensor_policy = policy.resolve(spec)
        buckets = expected.get(sensor_id, [])
        if not buckets:
            continue
        observed_rows = {row.bucket: row for row in rows}
        observed_values = {row.bucket: row.value for row in rows}
        plan = fill.plan(buckets, observed_values, sensor_policy)

        filled_reason: dict[datetime, str] = {}
        for item in plan.plans:
            run = item.run
            result.plans.append(
                {
                    "sensor_id": sensor_id,
                    "start": buckets[run.start_index],
                    "length": run.length,
                    "policy": sensor_policy,
                    "outcome": item.outcome,
                    "reason": item.reason,
                    "prev_value": item.prev_value,
                    "next_value": item.next_value,
                }
            )
            if item.outcome != "FILLED":
                continue
            for offset in range(run.length):
                filled_reason[buckets[run.start_index + offset]] = item.reason

        for moment in buckets:
            if moment in observed_rows:
                row = observed_rows[moment]
                result.points.append(
                    GridPoint(
                        sensor_id=sensor_id,
                        bucket=moment,
                        value=row.value,
                        unit=row.unit,
                        state="OBSERVED",
                        reason="",
                        fill_policy=sensor_policy,
                        source_row=row.source_row,
                    )
                )
                result.observed += 1
            elif moment in plan.filled:
                result.points.append(
                    GridPoint(
                        sensor_id=sensor_id,
                        bucket=moment,
                        value=plan.filled[moment],
                        unit=spec.unit,
                        state="FILLED",
                        reason=filled_reason.get(moment, policy.reason_for(sensor_policy)),
                        fill_policy=sensor_policy,
                        source_row=None,
                    )
                )
                result.filled += 1
            elif moment in plan.gaps:
                result.points.append(
                    GridPoint(
                        sensor_id=sensor_id,
                        bucket=moment,
                        value=None,
                        unit=spec.unit,
                        state="GAP",
                        reason=plan.gaps[moment],
                        fill_policy=sensor_policy,
                        source_row=None,
                    )
                )
                result.gaps += 1
    return result
