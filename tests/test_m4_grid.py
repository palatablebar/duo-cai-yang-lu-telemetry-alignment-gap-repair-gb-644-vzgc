"""M4 网格对齐：同分钟去重、分钟桶、窗口右端开与覆盖度。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pytest

from app import store
from app.modules.m2_timebase import coerce, contract
from app.modules.m4_grid import align, bucket, service, windows

from expected import MAIN, MAIN_DUPLICATES


def utc(text: str):
    return coerce.to_utc(text)


@dataclass
class Row:
    source_row: int
    sensor_id: str
    bucket: object
    value: Decimal
    quality: str
    quality_rank: int
    ingest_seq: int


def test_trap_14_duplicate_keeps_better_quality(conn, run_main):
    """TRAP-14：同分钟重复先按质量位择一，bad 那条不能覆盖 good。"""
    rows = service.duplicate_rows(conn, run_main["run_id"])
    th01 = [row for row in rows if row["sensor_id"] == "TH-01"][0]
    expected = MAIN_DUPLICATES[0]
    assert th01["kept_row"] == expected["kept_row"]
    assert th01["dropped_row"] == expected["dropped_row"]
    assert th01["kept_value"] == expected["kept_value"]
    assert th01["dropped_quality"] == "bad"


def test_trap_14_tie_breaks_on_later_arrival(conn, run_main):
    """TRAP-14：质量位并列时取到达较晚的一条，不是文件里先出现的那条。"""
    rows = service.duplicate_rows(conn, run_main["run_id"])
    pm = [row for row in rows if row["sensor_id"] == "PM-02"][0]
    expected = MAIN_DUPLICATES[1]
    assert pm["kept_row"] == expected["kept_row"]
    assert pm["dropped_row"] == expected["dropped_row"]
    assert pm["kept_value"] == expected["kept_value"]
    assert pm["dropped_value"] == expected["dropped_value"]


def test_trap_23_window_is_half_open(conn, run_edge):
    """TRAP-23：端点 00:15:00 归右窗口，左窗口不计入。"""
    stored = [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT * FROM windows WHERE run_id = ? ORDER BY sensor_id, window_start",
            (run_edge["run_id"],),
        )
    ]
    th01 = [row for row in stored if row["sensor_id"] == "TH-01"]
    assert [row["window_start"] for row in th01] == [
        "2026-02-28T23:45:00Z",
        "2026-03-01T00:00:00Z",
        "2026-03-01T00:15:00Z",
    ]
    assert th01[2]["observed"] == 1
    assert th01[1]["observed"] == 1
    assert bucket.window_start(utc("2026-03-01T00:15:00Z")) == utc("2026-03-01T00:15:00Z")
    assert bucket.window_start(utc("2026-03-01T00:14:59Z")) == utc("2026-03-01T00:00:00Z")


def test_minute_bucket_floors_seconds():
    """分钟桶向下取整：59 秒仍属当前分钟。"""
    assert bucket.minute_bucket(utc("2026-03-01T00:07:59Z")) == utc("2026-03-01T00:07:00Z")
    assert bucket.bucket_text(utc("2026-02-28T23:59:30Z")) == "2026-02-28T23:59:00Z"


def test_align_order_independent():
    """打乱输入顺序，保留结果与重复归属不变。"""
    base = utc("2026-03-01T00:00:00Z")
    rows = [
        Row(1, "TH-01", base, Decimal("45.0"), "good", 2, 1),
        Row(2, "TH-01", base, Decimal("45.9"), "bad", 0, 5),
        Row(3, "TH-01", base, Decimal("45.4"), "good", 2, 3),
    ]
    first = align.align(rows)
    second = align.align(list(reversed(rows)))
    assert [row.source_row for row in first.kept] == [row.source_row for row in second.kept]
    assert first.kept[0].source_row == 3
    assert {dup.dropped_row for dup in first.duplicates} == {1, 2}
    assert {dup.dropped_row for dup in second.duplicates} == {1, 2}


def test_coverage_partial_threshold():
    """覆盖度低于 0.8 记 PARTIAL，等于 0.8 仍记 OK（左边界）。"""
    assert windows.state_of(Decimal("0.799")) == "PARTIAL"
    assert windows.state_of(Decimal("0.800")) == "OK"
    assert windows.ratio(4, 5) == Decimal("0.800")
    assert windows.ratio(0, 0) == Decimal("0.000")


def test_windows_per_sensor_uses_rate(conn, run_main):
    """窗口应有桶按各自采样率派生：1 分钟 15 个，5 分钟 3 个，15 分钟 1 个。"""
    rows = [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT * FROM windows WHERE run_id = ? ORDER BY sensor_id, window_start",
            (run_main["run_id"],),
        )
    ]
    assert len(rows) == MAIN["windows"]
    th01 = [row for row in rows if row["sensor_id"] == "TH-01"]
    ws05 = [row for row in rows if row["sensor_id"] == "WS-05"]
    pm02 = [row for row in rows if row["sensor_id"] == "PM-02"]
    no04 = [row for row in rows if row["sensor_id"] == "NO-04"]
    assert {row["expected"] for row in th01} == {15}
    assert {row["expected"] for row in ws05} == {15}
    assert [row["expected"] for row in pm02] == [3, 3]
    assert [row["expected"] for row in no04] == [1, 1]
    partial = [row for row in rows if row["state"] == "PARTIAL"]
    assert len(partial) == MAIN["partial_windows"]


def test_bucket_range_opens_right(conn, run_gap):
    """全局区间终点是最大桶 + 1 分钟，右端开，不含下一分钟。"""
    observed = [row for row in service.grid_view(conn, run_gap["run_id"])["points"]
                if row["state"] == "OBSERVED"]
    last = max(row["bucket_utc"] for row in observed)
    assert last == "2026-03-01T00:08:00Z"
    analysis_points = service.grid_view(conn, run_gap["run_id"])["total"]
    assert analysis_points == 18
    assert contract.expected_minutes(1, utc("2026-03-01T00:00:00Z"), utc("2026-03-01T00:09:00Z"))[-1] == utc(
        "2026-03-01T00:08:00Z"
    )


def test_grid_states_add_up(conn, run_main):
    """网格账在数据层也成立：实有 + 补齐 + 缺口 = 应有。"""
    states = service.grid_view(conn, run_main["run_id"])["states"]
    assert states["OBSERVED"] == MAIN["observed"]
    assert states["FILLED"] == MAIN["filled"]
    assert states["GAP"] == MAIN["gaps"]
    assert sum(states.values()) == MAIN["expected_buckets"]
    assert states["GAP"] + states["FILLED"] == MAIN["expected_buckets"] - MAIN["observed"]
