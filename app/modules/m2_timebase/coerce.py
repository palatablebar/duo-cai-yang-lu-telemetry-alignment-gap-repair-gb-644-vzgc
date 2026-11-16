"""数值与时间的归一化。

三件事在这里收口：千分位/全角数字 → Decimal；带偏移时间 → UTC；分钟桶取整。
空值哨兵不做数值化，交给调用方判三态。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from app import config

FULLWIDTH = str.maketrans(
    "０１２３４５６７８９．－＋，％",
    "0123456789.-+,%",
)
THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
SPACE_CHARS = ("\u00a0", "\u2009", "\u202f", "\u3000", " ")


class CoerceError(ValueError):
    """归一化失败；调用方映射成原因码。"""


def squash(text: str) -> str:
    value = (text or "").translate(FULLWIDTH)
    for space in SPACE_CHARS:
        value = value.replace(space, "")
    return value.strip()


def is_sentinel(text: str) -> bool:
    value = (text or "").strip().translate(FULLWIDTH).lower()
    return value in config.SENTINELS


def parse_decimal(text: str) -> Decimal:
    if is_sentinel(text):
        raise CoerceError("sentinel")
    raw = squash(text)
    if not raw:
        raise CoerceError("blank")
    if raw.endswith("%"):
        raw = raw[:-1]
    if "," in raw:
        if not THOUSANDS_RE.match(raw):
            raise CoerceError("comma")
        raw = raw.replace(",", "")
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise CoerceError("not_decimal") from exc
    if not number.is_finite():
        raise CoerceError("not_finite")
    return number


def parse_seconds(text: str) -> int | None:
    if is_sentinel(text):
        return None
    try:
        value = parse_decimal(text)
    except CoerceError:
        return None
    return int(value)


def to_utc(text: str) -> datetime:
    """ISO8601 → UTC；`Z`、`+08:00`、纯日期时间都收。"""
    raw = (text or "").strip()
    if not raw:
        raise CoerceError("blank")
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CoerceError("timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def has_explicit_offset(text: str) -> bool:
    """判断原始写法是否自带时区标记，用于统计跨时区写法。"""
    raw = (text or "").strip()
    if raw.endswith("Z") or raw.endswith("z"):
        return True
    return bool(re.search(r"[+-]\d{2}:?\d{2}$", raw))


def floor_minute(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(second=0, microsecond=0)


def minute_text(moment: datetime) -> str:
    return floor_minute(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_minute(text: str) -> datetime:
    return to_utc(text)


def add_minutes(moment: datetime, count: int) -> datetime:
    return moment + timedelta(minutes=count)
