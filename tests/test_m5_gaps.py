"""M5 缺口修复：线性 / 保持补齐、超长缺口、边缘无锚与窗口覆盖。"""

from __future__ import annotations

from decimal import Decimal

from app import store
from app.modules.m2_timebase import coerce
from app.modules.m5_gaps import fill, policy, repair, service

from expected import GAP, MAIN, MAIN_FILLS


def utc(text: str):
    return coerce.to_utc(text)


def grid_row(conn, run_id, sensor_id, bucket_text):
    row = store.one(
        conn,
        "SELECT * FROM grid WHERE run_id = ? AND sensor_id = ? AND bucket_utc = ?",
        (run_id, sensor_id, bucket_text),
    )
    return dict(row) if row else None


def test_linear_fill_exact_values(conn, run_gap):
    """线性补齐按桶距等分：41 → 44 中间两桶是 42.000 与 43.000。"""
    for item in GAP["threshold_sums"]:
        row = grid_row(conn, run_gap["run_id"], item["sensor_id"], item["bucket"])
        assert row is not None
        assert row["state"] == "FILLED"
        assert row["reason"] == "FILLED_LINEAR"
        assert row["value"] == item["value"]


def test_hold_fill_uses_previous(conn, run_main):
    """保持策略取前一个实有值，锚点值原样保留。"""
    for sensor_id, bucket_text, value, reason in MAIN_FILLS:
        row = grid_row(conn, run_main["run_id"], sensor_id, bucket_text)
        assert row is not None, (sensor_id, bucket_text)
        assert row["state"] == "FILLED"
        assert row["reason"] == reason
        assert row["value"] == value


def test_gap_too_long_not_interpolated(conn, run_gap):
    """超过 3 桶的缺口不插值，逐桶标 GAP 并给 GAP_TOO_LONG。"""
    rows = [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT * FROM grid WHERE run_id = ? AND sensor_id = 'WS-05' ORDER BY bucket_utc",
            (run_gap["run_id"],),
        )
    ]
    gaps = [row for row in rows if row["state"] == "GAP"]
    assert len(gaps) == 8
    assert {row["reason"] for row in gaps} == {"GAP_TOO_LONG"}
    assert all(row["value"] is None for row in gaps)


def test_edge_no_anchor_for_linear_tail(conn, run_gap):
    """线性策略在后继锚点缺失时不能补，记边缘无锚点。"""
    rows = [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT * FROM grid WHERE run_id = ? AND sensor_id = 'TH-02'"
            " AND bucket_utc >= '2026-03-01T00:07:00Z' ORDER BY bucket_utc",
            (run_gap["run_id"],),
        )
    ]
    assert [row["state"] for row in rows] == ["GAP", "GAP"]
    assert {row["reason"] for row in rows} == {"EDGE_NO_ANCHOR"}


def test_naive_fill_all_gaps_would_invent_values(conn, run_gap):
    """反例：把超过上限的缺口也插值，会凭空造出 10 个采样值。"""
    counts = run_gap["counts"]
    assert counts["gaps"] == GAP["gaps"]
    assert counts["filled"] == GAP["filled"]
    naive_total = counts["observed"] + counts["filled"] + counts["gaps"]
    filled_values = store.rows(
        conn,
        "SELECT COUNT(*) AS n FROM grid WHERE run_id = ? AND state = 'FILLED'",
        (run_gap["run_id"],),
    )[0]["n"]
    assert naive_total == GAP["expected_buckets"]
    assert filled_values == 3  # 只补 2 + 1，不是 13


def test_gap_run_grouping():
    """缺口段按连续缺席聚合，长度与起点都对得上。"""
    buckets = [
        utc("2026-03-01T00:00:00Z"),
        utc("2026-03-01T00:01:00Z"),
        utc("2026-03-01T00:02:00Z"),
        utc("2026-03-01T00:03:00Z"),
        utc("2026-03-01T00:04:00Z"),
        utc("2026-03-01T00:05:00Z"),
    ]
    observed = {buckets[0], buckets[3]}
    runs = fill.gap_runs(buckets, observed)
    assert [(run.start_index, run.length) for run in runs] == [(1, 2), (4, 2)]


def test_window_coverage_counts(conn, run_gap):
    """覆盖度 = 实有 / 应有，缺口样例两个窗口都不达标。"""
    rows = [
        dict(row)
        for row in store.rows(
            conn,
            "SELECT * FROM windows WHERE run_id = ? ORDER BY sensor_id",
            (run_gap["run_id"],),
        )
    ]
    assert len(rows) == GAP["windows"]
    th02 = [row for row in rows if row["sensor_id"] == "TH-02"][0]
    ws05 = [row for row in rows if row["sensor_id"] == "WS-05"][0]
    assert (th02["observed"], th02["expected"], th02["coverage"]) == (4, 9, "0.444")
    assert (ws05["observed"], ws05["expected"], ws05["coverage"]) == (1, 9, "0.111")
    assert {row["state"] for row in rows} == {"PARTIAL"}


def test_fill_quantization_three_places():
    """补齐值按 0.001 四舍五入，不引入 float 尾差。"""
    value = fill.interpolate(Decimal("1.000"), Decimal("2.000"), 0, 3, 1)
    assert value == Decimal("1.333")
    another = fill.interpolate(Decimal("0.000"), Decimal("1.000"), 0, 3, 2)
    assert another == Decimal("0.667")
    assert fill.policy.max_fill() == 3
    assert policy.fillable(3) is True
    assert policy.fillable(4) is False


def test_repair_reports_states_for_every_bucket(conn, run_main):
    """每个应有桶恰好一个状态，三态之和等于应有桶数。"""
    rows = store.rows(
        conn,
        "SELECT state, COUNT(*) AS n FROM grid WHERE run_id = ? GROUP BY state",
        (run_main["run_id"],),
    )
    counts = {row["state"]: row["n"] for row in rows}
    total = sum(counts.values())
    assert total == MAIN["expected_buckets"]
    assert counts["FILLED"] == MAIN["filled"]
    assert counts["GAP"] == MAIN["gaps"]
    assert service.summary(conn, run_main["run_id"])["total"] == total
