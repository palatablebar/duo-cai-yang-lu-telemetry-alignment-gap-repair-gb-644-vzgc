"""网格桶运算：1 分钟桶、15 分钟窗口、按采样率派生的应有桶集合。

所有区间左闭右开：桶是 `[t, t+1min)`，窗口是 `[w, w+15min)`，
因此相邻窗口不会重复计入边界那一刻的采样。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app import config

from app.modules.m2_timebase import coerce, contract


def minute_bucket(moment: datetime) -> datetime:
    return coerce.floor_minute(moment)


def bucket_text(moment: datetime) -> str:
    return coerce.minute_text(moment)


def window_start(moment: datetime, minutes: int = config.WINDOW_MINUTES) -> datetime:
    return contract.align_window(coerce.floor_minute(moment), minutes)


def windows(start: datetime, end: datetime, minutes: int = config.WINDOW_MINUTES):
    return contract.window_bounds(start, end, minutes)


def buckets_for(rate_minutes: int, start: datetime, end: datetime) -> list[datetime]:
    return contract.expected_minutes(rate_minutes, start, end)


def range_of(buckets: list[datetime]) -> tuple[datetime, datetime]:
    """全局分析区间：起点按窗口对齐，终点 = 最大桶 + 1 分钟（右端开）。"""
    if not buckets:
        raise ValueError("empty")
    start = contract.align_window(min(buckets))
    end = max(buckets) + timedelta(minutes=config.GRID_MINUTES)
    return start, end


def offset_buckets(start: datetime, count: int, step_minutes: int = 1) -> list[datetime]:
    return [start + timedelta(minutes=index * step_minutes) for index in range(count)]


def label(moment: datetime) -> str:
    return moment.strftime("%H:%M")
