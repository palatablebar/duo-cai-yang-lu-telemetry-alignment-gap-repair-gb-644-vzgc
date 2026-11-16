"""不变量：行账守恒、网格守恒、幂等重跑、补齐不回流、交接证据可追回。"""

from __future__ import annotations

from decimal import Decimal

from app import store
from app.modules.m6_batches import service
from app.modules.m8_handover import service as handover_service

from expected import EDGE, GAP, MAIN

SHIFT_START = "2026-03-01T00:00:00Z"
SHIFT_END = "2026-03-01T00:15:00Z"


def test_row_account_conserved(conn):
    """行账守恒：原始行 = 采纳 + 重复 + 隔离，换样例也成立。"""
    for sample, expected in (("telemetry_raw", MAIN), ("gap_series", GAP), ("midnight_edge", EDGE)):
        result = service.execute_run(conn, sample=sample, offsets="device_offsets")
        counts = result["counts"]
        assert counts["raw_records"] == (
            counts["accepted"] + counts["duplicates"] + counts["quarantined"]
        ), sample
        assert counts["raw_records"] == expected["raw_records"]
        assert result["balanced"] is True


def test_grid_account_conserved(conn, run_main):
    """网格守恒：应有桶 = 实有 + 补齐 + 缺口，且等于逐传感器应有之和。"""
    counts = run_main["counts"]
    assert counts["expected_buckets"] == (
        counts["observed"] + counts["filled"] + counts["gaps"]
    )
    per_sensor = store.rows(
        conn,
        "SELECT sensor_id, COUNT(*) AS n FROM grid WHERE run_id = ? GROUP BY sensor_id",
        (run_main["run_id"],),
    )
    assert sum(row["n"] for row in per_sensor) == counts["expected_buckets"]
    assert counts["grid_points"] == counts["expected_buckets"]


def test_rerun_is_idempotent(conn, run_main):
    """幂等重跑：行数、合计、导出摘要都不变。"""
    before_runs = store.value(conn, "SELECT COUNT(*) FROM runs", (), 0)
    before_grid = store.value(conn, "SELECT COUNT(*) FROM grid", (), 0)
    before_sum = Decimal(run_main["totals"]["grid_sum"])

    again = service.execute_run(conn, sample="telemetry_raw", offsets="device_offsets")
    assert again["reused"] is True
    assert store.value(conn, "SELECT COUNT(*) FROM runs", (), 0) == before_runs
    assert store.value(conn, "SELECT COUNT(*) FROM grid", (), 0) == before_grid
    assert Decimal(again["totals"]["grid_sum"]) == before_sum
    assert again["counts"]["accepted"] == MAIN["accepted"]

    fresh = service.execute_run(conn, sample="telemetry_raw", offsets="device_offsets")
    assert fresh["counts"] == again["counts"]
    assert fresh["totals"] == again["totals"]


def test_filled_values_do_not_leak_into_accepted(conn, run_main):
    """补齐值不回流采纳合计：数值账两边都只算实有。"""
    totals = run_main["totals"]
    assert Decimal(totals["accepted_sum"]) == Decimal(totals["observed_sum"])
    assert Decimal(totals["grid_sum"]) == Decimal(totals["accepted_sum"]) + Decimal(
        totals["filled_sum"]
    )
    accepted_rows = store.value(
        conn, "SELECT COUNT(*) FROM samples WHERE run_id = ?", (run_main["run_id"],), 0
    )
    assert accepted_rows == MAIN["accepted"]
    filled_rows = store.value(
        conn,
        "SELECT COUNT(*) FROM grid WHERE run_id = ? AND state = 'FILLED'",
        (run_main["run_id"],),
        0,
    )
    assert filled_rows == MAIN["filled"]


def test_watermark_monotonic_across_replay(conn, run_main):
    """迟到只由到达顺序决定：同一文件重放得到同一批迟到标记。"""
    late_before = [
        dict(row)
        for row in store.rows(
            conn, "SELECT sensor_id, bucket_utc FROM samples WHERE run_id = ? AND late = 1",
            (run_main["run_id"],),
        )
    ]
    second = service.execute_run(conn, sample="telemetry_raw", offsets="device_offsets")
    late_after = [
        dict(row)
        for row in store.rows(
            conn, "SELECT sensor_id, bucket_utc FROM samples WHERE run_id = ? AND late = 1",
            (second["run_id"],),
        )
    ]
    assert late_before == late_after
    assert len(late_before) == MAIN["late"]


def test_handover_is_idempotent_invariant(conn, run_main):
    """交接不变量一：同班次重复交接不新增交接包、窗口与证据。"""
    first = handover_service.prepare_handover(
        conn, run_id=None, shift_date=SHIFT_START, shift_end=SHIFT_END
    )
    handover_service.prepare_handover(
        conn, run_id=None, shift_date=SHIFT_START, shift_end=SHIFT_END
    )
    assert store.value(conn, "SELECT COUNT(*) FROM handovers", (), 0) == 1
    assert store.value(
        conn, "SELECT COUNT(*) FROM handover_windows WHERE handover_id=?",
        (first["handover_id"],), 0,
    ) == len(first["windows"])
    assert store.value(
        conn, "SELECT COUNT(*) FROM handover_evidence WHERE handover_id=?",
        (first["handover_id"],), 0,
    ) == first["scope"]["retained_samples"]


def test_handover_evidence_survives_reclaim_and_restores(conn, run_main):
    """交接不变量二：腾空间后证据仍在，回滚把每条被删原始采样追回。"""
    pkg = handover_service.prepare_handover(
        conn, run_id=None, shift_date=SHIFT_START, shift_end=SHIFT_END
    )
    hid = pkg["handover_id"]
    rid = run_main["run_id"]
    handover_service.confirm_handover(conn, hid)
    handover_service.reclaim_space(conn, hid)

    # 在线采样已腾出，证据快照原样保留
    assert store.value(
        conn, "SELECT COUNT(*) FROM samples WHERE run_id=? AND bucket_utc >= ?",
        (rid, SHIFT_END), 0,
    ) == 0
    assert store.value(
        conn, "SELECT COUNT(*) FROM handover_evidence WHERE handover_id=?", (hid,), 0
    ) == pkg["scope"]["retained_samples"]

    handover_service.rollback_handover(conn, hid)
    restored = store.value(
        conn,
        "SELECT COUNT(*) FROM samples WHERE run_id=? AND flags='RESTORED_FROM_HANDOVER'",
        (rid,), 0,
    )
    assert restored == pkg["scope"]["retained_samples"]


def test_handover_window_observed_matches_retained_invariant(conn, run_main):
    """交接不变量三：每个有数据的跨班窗口，登记实有桶数 = 保留证据数。"""
    pkg = handover_service.prepare_handover(
        conn, run_id=None, shift_date=SHIFT_START, shift_end=SHIFT_END
    )
    retained: dict[tuple, int] = {}
    for ev in handover_service.evidence_of(conn, pkg["handover_id"]):
        key = (ev["sensor_id"], ev["window_start"])
        retained[key] = retained.get(key, 0) + 1
    for window in handover_service.windows_of(conn, pkg["handover_id"]):
        if window["cross_shift"] and window["observed"] > 0:
            assert retained[(window["sensor_id"], window["window_start"])] == window["observed"]
    assert pkg["checks"]["passed"] is True
