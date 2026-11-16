"""质量规则：哨兵三态、数值、量程、单位、采样率、迟到标记。

多条规则同时命中时按固定优先级判定（质量位 → 哨兵 → 数值 → 量程 → 单位 → 采样率），
结果与书写顺序无关，先命中的原因码即最终原因；迟到只标记，不影响采纳。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app import config

from app.modules.m2_timebase import coerce, contract

RULE_ORDER = (
    "QUALITY_UNKNOWN",
    "SENTINEL_VALUE",
    "NOT_DECIMAL",
    "OUT_OF_RANGE",
    "UNIT_MISMATCH",
    "OFF_RATE",
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    code: str | None
    detail: str
    value: Decimal | None
    lateness: bool


def _fail(code: str, detail: str) -> Verdict:
    return Verdict(ok=False, code=code, detail=detail, value=None, lateness=False)


def judge(row, watermark: datetime | None) -> Verdict:
    """row 是 m2 归一后的采样行；watermark = 已见最大桶 − 迟到窗口。"""
    quality = (row.quality or "").strip().lower()
    if quality not in config.QUALITY_RANK:
        return _fail("QUALITY_UNKNOWN", quality or "空")

    if coerce.is_sentinel(row.value_text):
        return _fail("SENTINEL_VALUE", row.value_text or "空串")

    try:
        value = coerce.parse_decimal(row.value_text)
    except coerce.CoerceError as exc:
        return _fail("NOT_DECIMAL", f"{row.value_text}（{exc}）")

    low, high = row.spec.low, row.spec.high
    if value < low or value > high:
        return _fail("OUT_OF_RANGE", f"{value} 越出 [{low}, {high}]")

    if not contract.unit_matches(row.unit_text, row.spec.unit):
        return _fail("UNIT_MISMATCH", f"{row.unit_text} ≠ {row.spec.unit}")

    if row.bucket.minute % max(1, row.spec.rate_minutes) != 0:
        return _fail(
            "OFF_RATE",
            f"第 {row.bucket.minute} 分不在 {row.spec.rate_minutes} 分钟采样点",
        )

    late = False
    if watermark is not None and row.bucket < watermark:
        late = True

    return Verdict(ok=True, code=None, detail="采纳", value=value, lateness=late)


def watermark_for(max_bucket: datetime | None) -> datetime | None:
    if max_bucket is None:
        return None
    return max_bucket - timedelta(minutes=config.LATE_WINDOW_MINUTES)


def priority_index(code: str) -> int:
    try:
        return RULE_ORDER.index(code)
    except ValueError:
        return len(RULE_ORDER)


def quality_rank(quality: str) -> int:
    return config.QUALITY_RANK.get((quality or "").strip().lower(), -1)
