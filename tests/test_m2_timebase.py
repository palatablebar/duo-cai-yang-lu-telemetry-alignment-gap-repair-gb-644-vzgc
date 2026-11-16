"""M2 时基契约：数值归一、时区归一、偏移区间与采样率派生。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.modules.m1_intake import service as intake_service
from app.modules.m2_timebase import coerce, contract, offsets, service

UTC = timezone.utc


def utc(text: str) -> datetime:
    return coerce.to_utc(text)


def test_trap_06_thousands_and_fullwidth():
    """TRAP-06：千分位与全角数字都要归一成 Decimal。"""
    assert coerce.parse_decimal("1,234.5") == Decimal("1234.5")
    assert coerce.parse_decimal("４.２") == Decimal("4.2")
    assert coerce.parse_decimal("１２３４.５") == Decimal("1234.5")
    assert coerce.parse_decimal("-12.5") == Decimal("-12.5")
    with pytest.raises(coerce.CoerceError):
        coerce.parse_decimal("12,3")


def test_trap_11_timezone_offsets_same_bucket():
    """TRAP-11：`Z` 与 `+08:00` 写同一个时刻必须落进同一个分钟桶。"""
    zulu = coerce.floor_minute(coerce.to_utc("2026-03-01T00:01:12Z"))
    shifted = coerce.floor_minute(coerce.to_utc("2026-03-01T08:01:12+08:00"))
    assert zulu == shifted
    assert coerce.minute_text(zulu) == "2026-03-01T00:01:00Z"


def test_trap_12_offset_overlap_is_ambiguous():
    """TRAP-12：两段区间同时覆盖同一时刻即歧义，不允许取「先读到的那段」。"""
    loaded = service.load_offsets("device_offsets")
    resolution = offsets.resolve(loaded.entries, "AM-06", utc("2026-03-01T00:05:30Z"))
    assert resolution.code == "OFFSET_AMBIGUOUS"
    assert resolution.candidates == (30, 31)


def test_offset_window_is_half_open():
    """偏移区间左闭右开：结束时刻属于下一段，区间外视为无表。"""
    entries = [
        offsets.OffsetEntry("S-1", utc("2026-02-01T00:00:00Z"), utc("2026-03-01T00:00:00Z"), 10),
        offsets.OffsetEntry("S-1", utc("2026-03-01T00:00:00Z"), utc("2026-04-01T00:00:00Z"), 20),
    ]
    assert offsets.resolve(entries, "S-1", utc("2026-02-28T23:59:59Z")).seconds == 10
    assert offsets.resolve(entries, "S-1", utc("2026-03-01T00:00:00Z")).seconds == 20
    assert offsets.resolve(entries, "S-1", utc("2026-04-01T00:00:00Z")).code == "OFFSET_ASSUMED"


def test_offset_assumed_and_conflict_flags():
    """无偏移条目的传感器用行内偏移并标默认，与表不符只标冲突不改判。"""
    loaded = intake_service.load_sample("telemetry_raw")
    table = service.load_offsets("device_offsets")
    normalized = service.normalize(loaded, table)
    assumed = [row for row in normalized.rows if "OFFSET_ASSUMED" in row.flags]
    conflict = [row for row in normalized.rows if "OFFSET_CONFLICT" in row.flags]
    assert {row.sensor_id for row in assumed} == {"GH-07"}
    assert {row.sensor_id for row in conflict} == {"NO-04"}
    no04 = [row for row in normalized.rows if row.sensor_id == "NO-04"][0]
    assert no04.offset == 0
    assert no04.bucket.strftime("%H:%M") == "00:00"


def test_expected_minutes_follow_rate():
    """应有桶按采样率派生，而不是一律按分钟。"""
    start = utc("2026-03-01T00:00:00Z")
    end = utc("2026-03-01T00:30:00Z")
    assert len(contract.expected_minutes(1, start, end)) == 30
    assert len(contract.expected_minutes(5, start, end)) == 6
    assert len(contract.expected_minutes(15, start, end)) == 2
    assert contract.expected_minutes(15, start, end) == [
        utc("2026-03-01T00:00:00Z"),
        utc("2026-03-01T00:15:00Z"),
    ]


def test_window_bounds_align_to_quarter():
    """窗口从 15 分钟整点开始，最后一段按分析区间右端截断。"""
    bounds = contract.window_bounds(utc("2026-03-01T00:07:00Z"), utc("2026-03-01T00:20:00Z"))
    assert bounds[0] == (utc("2026-03-01T00:00:00Z"), utc("2026-03-01T00:15:00Z"))
    assert bounds[1] == (utc("2026-03-01T00:15:00Z"), utc("2026-03-01T00:30:00Z"))


def test_naive_local_bucket_differs():
    """反例：不校正偏移直接取本地分钟，90 秒漂移会让整条序列错位一分钟。"""
    raw = coerce.to_utc("2026-03-01T00:06:30Z")
    naive = coerce.floor_minute(raw)
    corrected = coerce.floor_minute(raw - timedelta(seconds=90))
    assert naive.strftime("%H:%M") == "00:06"
    assert corrected.strftime("%H:%M") == "00:05"


def test_unit_alias_matches():
    """单位写法归一：大小写与空格差异不算不符，量纲不同才算。"""
    assert contract.unit_matches("RH", "%RH")
    assert contract.unit_matches("%RH ", "%RH")
    assert contract.unit_matches("M/S", "m/s")
    assert not contract.unit_matches("km/h", "m/s")
    assert not contract.unit_matches("ppb", "ppm")
