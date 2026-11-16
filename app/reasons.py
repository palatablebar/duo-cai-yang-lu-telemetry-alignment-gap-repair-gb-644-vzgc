"""原因码唯一来源。

blocking=True 的码会把行挡在隔离区，blocking=False 的码只是标记，不影响采纳。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    code: str
    label: str
    blocking: bool


_REASONS = (
    # —— 采信层（M1） ——
    Reason("EMPTY_FILE", "空文件", True),
    Reason("ALL_BLANK", "全空行", True),
    Reason("HEADER_ONLY", "仅表头", True),
    Reason("COLUMN_COUNT", "列数不符", True),
    Reason("TRUNCATED_TAIL", "尾行截断", True),
    Reason("HEADER_MISSING", "缺必需列", True),
    # —— 时基层（M2） ——
    Reason("TIMESTAMP_INVALID", "时间无法解析", True),
    Reason("UNKNOWN_SENSOR", "未知传感器", True),
    Reason("OFFSET_AMBIGUOUS", "偏移重叠", True),
    Reason("OFFSET_ASSUMED", "默认偏移", False),
    Reason("OFFSET_CONFLICT", "偏移与表不符", False),
    Reason("TZ_FOREIGN", "异地时区", False),
    # —— 质量层（M3） ——
    Reason("SENTINEL_VALUE", "空值哨兵", True),
    Reason("NOT_DECIMAL", "数值无法解析", True),
    Reason("OUT_OF_RANGE", "越界", True),
    Reason("UNIT_MISMATCH", "单位不符", True),
    Reason("QUALITY_UNKNOWN", "质量位未知", True),
    Reason("OFF_RATE", "偏离采样率", True),
    Reason("LATE_ARRIVAL", "迟到", False),
    # —— 网格层（M4） ——
    Reason("DUPLICATE_MINUTE", "同分钟重复", False),
    # —— 缺口层（M5） ——
    Reason("FILLED_HOLD", "补齐·保持", False),
    Reason("FILLED_LINEAR", "补齐·线性", False),
    Reason("GAP_TOO_LONG", "缺口超限", False),
    Reason("EDGE_NO_ANCHOR", "边缘无锚点", False),
    Reason("PARTIAL_COVERAGE", "覆盖不足", False),
)

REASONS = {item.code: item for item in _REASONS}


def get(code: str) -> Reason:
    return REASONS.get(code, Reason(code, code, True))


def label(code: str) -> str:
    return get(code).label


def blocking(code: str) -> bool:
    return get(code).blocking


def all_codes() -> tuple[str, ...]:
    return tuple(REASONS)


def blocking_codes() -> tuple[str, ...]:
    return tuple(code for code, item in REASONS.items() if item.blocking)


def label_map() -> dict[str, str]:
    return {code: item.label for code, item in REASONS.items()}
