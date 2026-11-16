"""四账核对：行账、网格账、数值账、窗口账。

每账给出「应有」与「实得」，差额非零即不平；Decimal 比较，不设容差。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ReconcileLine:
    line_no: int
    name: str
    expected: Decimal
    actual: Decimal
    note: str

    @property
    def delta(self) -> Decimal:
        return self.actual - self.expected

    @property
    def state(self) -> str:
        return "OK" if self.delta == 0 else "BAD"


def _dec(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def reconcile_lines(counts: dict, totals: dict) -> list[ReconcileLine]:
    accepted = _dec(counts.get("accepted")) + _dec(counts.get("duplicates")) + _dec(
        counts.get("quarantined")
    )
    observed = _dec(counts.get("observed")) + _dec(counts.get("filled")) + _dec(counts.get("gaps"))
    lines = [
        ReconcileLine(
            line_no=1,
            name="行账",
            expected=_dec(counts.get("raw_records")),
            actual=accepted,
            note="原始 = 采纳 + 重复 + 隔离",
        ),
        ReconcileLine(
            line_no=2,
            name="网格账",
            expected=_dec(counts.get("expected_buckets")),
            actual=observed,
            note="应有 = 实有 + 补齐 + 缺口",
        ),
        ReconcileLine(
            line_no=3,
            name="数值账",
            expected=_dec(totals.get("accepted_sum")),
            actual=_dec(totals.get("observed_sum")),
            note="采纳合计 = 实有合计",
        ),
        ReconcileLine(
            line_no=4,
            name="窗口账",
            expected=_dec(counts.get("windows")),
            actual=_dec(counts.get("windows_stored")),
            note="应有窗口 = 落库窗口",
        ),
    ]
    return lines


def is_balanced(lines: list[ReconcileLine]) -> bool:
    return all(line.state == "OK" for line in lines)


def as_dict(line: ReconcileLine) -> dict:
    return {
        "line_no": line.line_no,
        "name": line.name,
        "expected": str(line.expected),
        "actual": str(line.actual),
        "delta": str(line.delta),
        "state": line.state,
        "note": line.note,
    }
