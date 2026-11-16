"""M6 批次与对账：四账、幂等重跑、清单摘要与重新推导比对。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app import store
from app.errors import NotFoundError
from app.modules.m6_batches import compare, history, service

from expected import MAIN


def test_reconcile_balanced_on_main_sample(conn, run_main):
    """四账相等：行账、网格账、数值账、窗口账差额都是 0。"""
    view = service.reconcile_view(conn, run_main["run_id"])
    assert view["balanced"] is True
    assert view["conclusion"] == "四账相等"
    assert len(view["lines"]) == 4
    for line in view["lines"]:
        assert line["state"] == "OK"
        assert Decimal(line["delta"]) == 0


def test_reconcile_detects_drift():
    """任何一个数被改动，对应那一账立刻不平，并给出归因。"""
    counts = {
        "raw_records": 92,
        "accepted": 84,
        "duplicates": 2,
        "quarantined": 7,
        "expected_buckets": 110,
        "observed": 83,
        "filled": 8,
        "gaps": 19,
        "windows": 14,
        "windows_stored": 14,
    }
    totals = {"accepted_sum": "5482.000", "observed_sum": "5482.000"}
    lines = compare.reconcile_lines(counts, totals)
    assert [line.state for line in lines] == ["BAD", "OK", "OK", "OK"]
    from app.modules.m6_batches import diff

    hints = diff.explain(lines, counts)
    assert hints[0]["state"] == "BAD"
    assert hints[0]["delta"] == "1"


def test_rerun_reuses_run_and_keeps_counts(conn, run_main):
    """同输入同参数重跑命中同一批次键，不新增行也不改计数。"""
    again = service.execute_run(conn, sample="telemetry_raw", offsets="device_offsets")
    assert again["reused"] is True
    assert again["run_id"] == run_main["run_id"]
    assert again["counts"] == run_main["counts"]
    assert store.value(conn, "SELECT COUNT(*) FROM runs", (), 0) == 1
    assert store.value(conn, "SELECT COUNT(*) FROM grid", (), 0) == MAIN["grid_points"]


def test_manifest_has_input_sha256(conn, run_main):
    """运行清单带 run_id、规则版本与两个输入的 sha256。"""
    manifest = history.manifest_of(conn, run_main["run_id"])
    assert manifest["run_id"] == run_main["run_id"]
    assert manifest["rule_version"] == "gridlab-1.0.0"
    names = [item["name"] for item in manifest["inputs"]]
    assert names == ["device_offsets.csv", "telemetry_raw.csv"]
    for item in manifest["inputs"]:
        assert len(item["sha256"]) == 64
        assert item["bytes"] > 0
    assert manifest["window_minutes"] == 15
    assert manifest["window_rule"] == "[start, end)"


def test_history_lists_runs(conn, run_main):
    """批次清单按生成时间倒序，首条即最新批次。"""
    view = service.runs_view(conn)
    assert len(view["runs"]) == 1
    assert view["latest"]["run_id"] == run_main["run_id"]
    assert view["runs"][0]["grid_points"] == MAIN["grid_points"]
    assert view["runs"][0]["balanced"] is True


def test_unknown_run_raises_404(conn):
    """不存在的批次号给 404，而不是空对象。"""
    with pytest.raises(NotFoundError) as error:
        service.run_detail(conn, "GL-NOT-EXIST")
    assert error.value.status == 404
    assert error.value.code == "RUN_NOT_FOUND"


def test_verify_grid_matches_stored(conn, run_main):
    """从采纳行重新推导网格，逐点与落库结果一致。"""
    result = service.verify_grid(conn, run_main["run_id"])
    assert result["verified"] is True
    assert result["derived_points"] == MAIN["grid_points"]
    assert result["stored_points"] == MAIN["grid_points"]
    assert result["mismatches"] == []
    assert result["counts"]["filled"] == MAIN["filled"]


def test_verify_gaps_matches_stored(conn, run_main):
    """补齐与窗口同样可重新推导，数量与落库一致。"""
    result = service.verify_gaps(conn, run_main["run_id"])
    assert result["verified"] is True
    assert result["derived"]["filled"] == MAIN["filled"]
    assert result["derived"]["gaps"] == MAIN["gaps"]
    assert result["derived"]["windows"] == MAIN["windows"]


def test_overview_stages_cover_counts(conn, run_main):
    """总览的阶段数字直接来自批次计数，不另算一套。"""
    overview = service.overview(conn)
    stages = {item["name"]: item["value"] for item in overview["stages"]}
    assert stages["原始行"] == MAIN["raw_records"]
    assert stages["采纳"] == MAIN["accepted"]
    assert stages["补齐"] == MAIN["filled"]
    assert stages["缺口"] == MAIN["gaps"]
    assert overview["run"]["run_id"] == run_main["run_id"]
    assert overview["balanced"] is True
