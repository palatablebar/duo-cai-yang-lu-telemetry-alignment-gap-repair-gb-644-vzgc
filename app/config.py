"""运行参数与常量。

所有阈值、编码链、质量位序、补齐上限集中在这里，模块只引用不重复定义。
"""

from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
SAMPLE_DIR = BASE_DIR / "sample_data"
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

RULE_VERSION = "gridlab-1.0.0"

# 网格与窗口
GRID_MINUTES = 1
WINDOW_MINUTES = 15
MAX_FILL_BUCKETS = 3
PARTIAL_COVERAGE = "0.8"
LATE_WINDOW_MINUTES = 15

# 精度
VALUE_PLACES = 3
COVERAGE_PLACES = 3

# 质量位序：good > suspect > bad
QUALITY_RANK = {"good": 2, "suspect": 1, "bad": 0}
DEFAULT_QUALITY = "good"

# 空值哨兵：只在这里定义一次
SENTINELS = (
    "", "-", "--", "---", "—", "/", "na", "n/a", "null", "none", "nil", "nan",
    "?", "待定", "未知", "空", "无",
)

# 编码回退链：按顺序尝试严格解码
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5")

CN_TZ = timezone(timedelta(hours=8), "UTC+08:00")

# 载体分辨率 -> 表格列字母
COLUMN_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 自带样例：key -> (文件名, 中文标题)
SAMPLES = {
    "telemetry_raw": ("telemetry_raw.csv", "主样例（脏）"),
    "gap_series": ("gap_series.csv", "缺口样例"),
    "midnight_edge": ("midnight_edge.csv", "跨日边界"),
    "offset_overlap": ("offset_overlap.csv", "偏移重叠"),
    "column_count": ("column_count.csv", "列数不齐"),
    "truncated_tail": ("truncated_tail.csv", "尾行截断"),
    "header_only": ("header_only.csv", "仅表头"),
    "blank_rows": ("blank_rows.csv", "全空行"),
    "crlf_quoted": ("crlf_quoted.csv", "换行混用"),
    "gb18030": ("telemetry_gb18030.csv", "中文表头"),
    "empty": ("empty_sample.csv", "空文件"),
}

OFFSET_SAMPLES = {
    "device_offsets": ("device_offsets.csv", "设备偏移表"),
}


def db_path() -> Path:
    raw = os.environ.get("GRIDLAB_DB")
    if raw:
        return Path(raw)
    return BASE_DIR / "data" / "gridlab.db"


def sample_file(key: str) -> Path:
    if key not in SAMPLES:
        raise KeyError(key)
    return SAMPLE_DIR / SAMPLES[key][0]


def offset_file(key: str) -> Path:
    if key not in OFFSET_SAMPLES:
        raise KeyError(key)
    return SAMPLE_DIR / OFFSET_SAMPLES[key][0]
