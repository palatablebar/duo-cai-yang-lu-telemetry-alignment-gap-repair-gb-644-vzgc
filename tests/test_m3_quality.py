"""M3 质量隔离：哨兵、越界、单位、采样率、迟到与原因码导出。"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from app import reasons
from app.modules.m2_timebase import coerce, contract
from app.modules.m3_quality import rules, service

from expected import MAIN, MAIN_QUARANTINE


def judged_of(conn, run_id):
    return service.load_judged(conn, run_id)


def test_trap_07_sentinel_not_zero(conn, run_main):
    """TRAP-07：哨兵不是 0，哨兵行不能进合计。"""
    rows = service.quarantine.rows_of(conn, run_main["run_id"])
    sentinels = [row for row in rows if row["code"] == "SENTINEL_VALUE"]
    assert len(sentinels) == 2
    assert {row["raw_value"] for row in sentinels} == {"-"}
    values = [row["value"] for row in service.load_samples(conn, run_main["run_id"])]
    assert "0" not in values
    assert Decimal(run_main["totals"]["accepted_sum"]) == Decimal(MAIN["accepted_sum"])


def test_trap_13_late_still_applied(conn, run_main):
    """TRAP-13：迟到 24 分钟的读数仍然采纳，只标迟到。"""
    late = [
        row
        for row in service.load_samples(conn, run_main["run_id"])
        if row["late"]
    ]
    assert len(late) == 1
    assert late[0]["sensor_id"] == "PM-02"
    assert late[0]["bucket_utc"] == "2026-03-01T00:05:00Z"
    assert "LATE_ARRIVAL" in late[0]["flags"]


def test_out_of_range_quarantined(conn, run_main):
    """越界值进隔离区，原因码与量程一起给出。"""
    rows = service.quarantine.rows_of(conn, run_main["run_id"])
    out = [row for row in rows if row["code"] == "OUT_OF_RANGE"]
    assert len(out) == 1
    assert out[0]["raw_value"] == "131.0"
    assert "100" in out[0]["detail"]


def test_unknown_sensor_quarantined(conn, run_main):
    """契约外传感器不参与任何计算。"""
    rows = service.quarantine.rows_of(conn, run_main["run_id"])
    unknown = [row for row in rows if row["code"] == "UNKNOWN_SENSOR"]
    assert len(unknown) == 1
    assert unknown[0]["sensor_id"] == "XX-99"


def test_off_rate_quarantined(conn, run_main):
    """偏离采样率：5 分钟传感器出现在第 3 分即隔离。"""
    rows = service.quarantine.rows_of(conn, run_main["run_id"])
    off = [row for row in rows if row["code"] == "OFF_RATE"]
    assert len(off) == 1
    assert off[0]["sensor_id"] == "PM-02"
    assert "第 3 分" in off[0]["detail"]


def test_unit_mismatch_quarantined(conn, run_main):
    """单位不符只隔离该行，不影响同传感器其他分钟。"""
    rows = service.quarantine.rows_of(conn, run_main["run_id"])
    unit = [row for row in rows if row["code"] == "UNIT_MISMATCH"]
    assert len(unit) == 1
    assert unit[0]["sensor_id"] == "WS-05"
    assert "km/h" in unit[0]["detail"]


def test_rule_priority_sentinel_before_unit():
    """多规则命中时按固定优先级，结果不随书写顺序变化。"""

    class Row:
        sensor_id = "NO-04"
        spec = contract.spec("NO-04")
        bucket = coerce.to_utc("2026-03-01T00:15:00Z")
        value_text = "-"
        unit_text = "km/h"
        quality = "good"

    verdict = rules.judge(Row(), None)
    assert verdict.code == "SENTINEL_VALUE"
    assert rules.priority_index("SENTINEL_VALUE") < rules.priority_index("UNIT_MISMATCH")


def test_quarantine_csv_columns(conn, run_main):
    """隔离 CSV 带行号、列名、原值与原因码，可直接回原文核对。"""
    from app.modules.m3_quality import quarantine

    rows = quarantine.rows_of(conn, run_main["run_id"])
    text = quarantine.to_csv(rows)
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert len(parsed) == MAIN["quarantined"]
    assert parsed[0]["code"]
    assert parsed[0]["source_row"].isdigit()
    assert list(csv.DictReader(io.StringIO(text))).__len__() == len(MAIN_QUARANTINE)
    codes = [row["code"] for row in parsed]
    for code in ("SENTINEL_VALUE", "OUT_OF_RANGE", "UNIT_MISMATCH", "OFF_RATE",
                 "NOT_DECIMAL", "UNKNOWN_SENSOR"):
        assert code in codes


def test_metrics_summary_matches_reconcile(conn, run_main):
    """采纳率与原始行数自洽，摘要不引入第四条账。"""
    summary = service.metrics.summary(conn, run_main["run_id"])
    assert summary["raw"] == MAIN["raw_records"]
    assert summary["accepted"] == MAIN["accepted"]
    assert summary["quarantined"] == MAIN["quarantined"]
    assert summary["duplicates"] == MAIN["duplicates"]
    assert summary["pass_rate"] == "0.902"


def test_quarantine_codes_are_registered():
    """原因码只能来自集中定义，隔离行不会出现裸码。"""
    for code in ("SENTINEL_VALUE", "NOT_DECIMAL", "OUT_OF_RANGE", "UNIT_MISMATCH",
                 "OFF_RATE", "UNKNOWN_SENSOR", "OFFSET_AMBIGUOUS", "TRUNCATED_TAIL"):
        assert code in reasons.all_codes()
        assert reasons.label(code) != code
