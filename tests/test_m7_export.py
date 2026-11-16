"""M7 导出：网格 CSV、采纳 CSV、隔离 CSV、运行清单与单元格证据。"""

from __future__ import annotations

import csv
import io
import json

import pytest

from app.errors import NotFoundError
from app.modules.m7_export import evidence, service

from expected import MAIN


def parse(text: str):
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


def test_grid_csv_header_and_rows(conn, run_main):
    """网格 CSV 行数等于网格点数，列名固定。"""
    text = service.grid_csv(conn, run_main["run_id"])
    rows = parse(text)
    assert len(rows) == MAIN["grid_points"]
    assert list(rows[0].keys()) == [
        "row_no",
        "sensor_id",
        "bucket_utc",
        "bucket_local",
        "value",
        "unit",
        "state",
        "reason",
        "source_row",
        "flags",
    ]
    assert rows[0]["row_no"] == "1"
    assert rows[0]["bucket_utc"].endswith("Z")
    assert rows[0]["bucket_local"].startswith("2026-03-01")


def test_grid_csv_gap_rows_have_empty_value(conn, run_gap):
    """缺口行不给值，只给状态与原因码，导出与页面一致。"""
    rows = parse(service.grid_csv(conn, run_gap["run_id"]))
    gaps = [row for row in rows if row["state"] == "GAP"]
    assert len(gaps) == 10
    assert all(row["value"] == "" for row in gaps)
    assert {row["reason"] for row in gaps} == {"GAP_TOO_LONG", "EDGE_NO_ANCHOR"}


def test_accepted_csv_keeps_decimal_literal(conn, run_main):
    """采纳 CSV 的值是落库字面量，不被二次格式化。"""
    rows = parse(service.accepted_csv(conn, run_main["run_id"]))
    assert len(rows) == MAIN["accepted"]
    values = [row["value"] for row in rows]
    assert "45.0" in values
    assert "1234.5" in values
    assert "1,234.5" not in values


def test_manifest_json_fields(conn, run_main):
    """清单是合法 JSON，字段齐全且计数与批次一致。"""
    payload = json.loads(service.manifest_text(conn, run_main["run_id"]))
    assert payload["run_id"] == run_main["run_id"]
    assert payload["counts"]["accepted"] == MAIN["accepted"]
    assert payload["totals"]["grid_sum"] == MAIN["grid_sum"]
    assert payload["grid_resolution"] == "PT1M"
    assert payload["window_rule"] == "[start, end)"
    assert len(payload["inputs"]) == 2


def test_quarantine_csv_has_reason_codes(conn, run_main):
    """隔离 CSV 带原因码与原因说明，可直接交给现场。"""
    rows = parse(service.quarantine_csv(conn, run_main["run_id"]))
    assert len(rows) == MAIN["quarantined"]
    codes = {row["code"] for row in rows}
    assert "SENTINEL_VALUE" in codes
    assert all(row["label"] for row in rows)


def test_evidence_cell_has_source_row(conn, run_main):
    """任一网格点都能追回原始行、质量位与原因。"""
    payload = evidence.cell(conn, run_main["run_id"], "TH-01", "2026-03-01T00:00:00Z")
    assert payload["sensor_id"] == "TH-01"
    assert payload["state"] == "OBSERVED"
    assert payload["source_row"] == 1
    assert payload["quality"] == "good"
    assert payload["offset_seconds"] == 20
    filled = evidence.cell(conn, run_main["run_id"], "TH-01", "2026-03-01T00:04:00Z")
    assert filled["state"] == "FILLED"
    assert filled["reason"] == "FILLED_HOLD"
    assert filled["reason_label"] == "补齐·保持"


def test_export_missing_run_raises(conn):
    """导出不存在的批次给 404，不返回空文件。"""
    with pytest.raises(NotFoundError) as error:
        service.resolve(conn, "GL-NOPE")
    assert error.value.code == "RUN_NOT_FOUND"
    with pytest.raises(NotFoundError):
        service.resolve(conn, None)


def test_csv_bom_prefix(conn, run_main):
    """CSV 带 BOM，表格软件打开中文列名不乱码。"""
    for body in (
        service.grid_csv(conn, run_main["run_id"]),
        service.accepted_csv(conn, run_main["run_id"]),
        service.quarantine_csv(conn, run_main["run_id"]),
    ):
        assert body.startswith("\ufeff")
        assert body.count("\n") >= 8


def test_summary_files_carry_row_counts(conn, run_main):
    """导出摘要给出四个文件与各自行数。"""
    summary = service.summary(conn, run_main["run_id"])
    names = [item["name"] for item in summary["files"]]
    assert names == ["网格 CSV", "采纳 CSV", "隔离 CSV", "运行清单"]
    by_name = {item["name"]: item["rows"] for item in summary["files"]}
    assert by_name["网格 CSV"] == MAIN["grid_points"]
    assert by_name["采纳 CSV"] == MAIN["accepted"]
    assert by_name["隔离 CSV"] == MAIN["quarantined"]
    assert summary["evidence"]
