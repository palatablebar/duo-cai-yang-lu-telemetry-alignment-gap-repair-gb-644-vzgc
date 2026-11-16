"""缺口识别与补齐计算。

缺口 = 应有桶里连续缺席的一段。长度 ≤ 上限才补：hold 取前一个实有值，
linear 在前一实有值与后一实有值之间按桶距等分；任一锚点缺失记 EDGE_NO_ANCHOR，
超长缺口记 GAP_TOO_LONG 且不插值。补出来的值按最小刻度四舍五入，锚点值原样保留。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app import config

from . import policy


@dataclass(frozen=True)
class GapRun:
    start_index: int
    length: int

    @property
    def end_index(self) -> int:
        return self.start_index + self.length


@dataclass(frozen=True)
class GapPlan:
    run: GapRun
    policy: str
    outcome: str
    reason: str
    prev_index: int | None
    next_index: int | None
    prev_value: Decimal | None
    next_value: Decimal | None


@dataclass
class FillPlan:
    filled: dict[datetime, Decimal] = field(default_factory=dict)
    gaps: dict[datetime, str] = field(default_factory=dict)
    plans: list[GapPlan] = field(default_factory=list)


def gap_runs(expected: list[datetime], observed: set[datetime]) -> list[GapRun]:
    runs: list[GapRun] = []
    start: int | None = None
    for index, moment in enumerate(expected):
        if moment in observed:
            if start is not None:
                runs.append(GapRun(start_index=start, length=index - start))
                start = None
        elif start is None:
            start = index
    if start is not None:
        runs.append(GapRun(start_index=start, length=len(expected) - start))
    return runs


def interpolate(prev_value: Decimal, next_value: Decimal, prev_index: int, next_index: int, index: int) -> Decimal:
    span = Decimal(next_index - prev_index)
    step = (next_value - prev_value) / span
    value = prev_value + step * Decimal(index - prev_index)
    return value.quantize(Decimal(1).scaleb(-config.VALUE_PLACES), rounding=ROUND_HALF_UP)


def plan(
    expected: list[datetime],
    observed_values: dict[datetime, Decimal],
    sensor_policy: str,
    max_fill: int | None = None,
) -> FillPlan:
    limit = policy.max_fill() if max_fill is None else max_fill
    result = FillPlan()
    observed_set = set(observed_values)
    for run in gap_runs(expected, observed_set):
        prev_index = run.start_index - 1 if run.start_index > 0 else None
        next_index = run.end_index if run.end_index < len(expected) else None
        prev_value = observed_values[expected[prev_index]] if prev_index is not None else None
        next_value = observed_values[expected[next_index]] if next_index is not None else None

        outcome = "FILLED"
        reason = policy.reason_for(sensor_policy)
        if run.length > limit:
            outcome, reason = "GAP", "GAP_TOO_LONG"
        elif prev_index is None:
            outcome, reason = "GAP", "EDGE_NO_ANCHOR"
        elif policy.needs_next_anchor(sensor_policy) and next_index is None:
            outcome, reason = "GAP", "EDGE_NO_ANCHOR"

        result.plans.append(
            GapPlan(
                run=run,
                policy=sensor_policy,
                outcome=outcome,
                reason=reason,
                prev_index=prev_index,
                next_index=next_index,
                prev_value=prev_value,
                next_value=next_value,
            )
        )

        for offset in range(run.length):
            index = run.start_index + offset
            moment = expected[index]
            if outcome == "GAP":
                result.gaps[moment] = reason
                continue
            if sensor_policy == policy.POLICY_LINEAR:
                value = interpolate(prev_value, next_value, prev_index, next_index, index)
            else:
                value = prev_value
            result.filled[moment] = value
    return result
