"""M1 采样采信：编码、分段、列数、尾行、空态。"""

from __future__ import annotations

import pytest

from app.errors import InputError
from app.modules.m1_intake import decode, reader, service


def test_trap_03_crlf_and_quoted_newline():
    """TRAP-03：CRLF 与引号内换行不能被切成两条记录。"""
    loaded = service.load_sample("crlf_quoted")
    assert loaded.data_rows == 4
    assert len(loaded.rows) == 4
    assert loaded.issues == []
    assert loaded.rows[1].cells["unit"] == "%RH"


def test_naive_splitlines_would_break_records(sample_dir):
    """反例：按裸换行切分会多切一条，逻辑记录数会变成 5。"""
    raw = (sample_dir / "crlf_quoted.csv").read_text(encoding="utf-8")
    naive = [line for line in raw.splitlines() if line.strip()]
    loaded = service.load_sample("crlf_quoted")
    assert len(naive) == 7  # 表头 2 行 + 数据 4 行，引号内换行被多切
    assert loaded.data_rows == 4


def test_trap_05_column_count_mismatch():
    """TRAP-05：少列与多列都进隔离，且带原始行号与两边列数。"""
    loaded = service.load_sample("column_count")
    codes = [(issue.source_row, issue.code) for issue in loaded.issues]
    assert codes == [(2, "COLUMN_COUNT"), (3, "COLUMN_COUNT")]
    assert loaded.issues[0].detail == "6/7"
    assert loaded.issues[1].detail == "8/7"
    assert loaded.data_rows == 4
    assert len(loaded.rows) == 2


def test_trap_16_truncated_tail_rejected():
    """TRAP-16：无结尾换行且列数不足即尾行截断，整行拒绝。"""
    loaded = service.load_sample("truncated_tail")
    assert loaded.truncated is True
    assert [issue.code for issue in loaded.issues] == ["TRUNCATED_TAIL"]
    assert loaded.data_rows == 3
    assert len(loaded.rows) == 2


def test_trap_18_three_empty_states():
    """TRAP-18：0 字节 / 全空行 / 仅表头 是三种结论，不是同一句「导入 0 行」。"""
    assert service.load_sample("empty").empty_code == "EMPTY_FILE"
    assert service.load_sample("blank_rows").empty_code == "ALL_BLANK"
    header_only = service.load_sample("header_only")
    assert header_only.empty_code == "HEADER_ONLY"
    assert header_only.data_rows == 0
    assert len({service.load_sample("empty").empty_code,
                service.load_sample("blank_rows").empty_code,
                header_only.empty_code}) == 3


def test_bom_stripped_and_header_canonical():
    """首列名不能带 BOM，必须是契约列名。"""
    loaded = service.load_sample("telemetry_raw")
    assert loaded.bom is True
    assert loaded.header[0] == "sensor_id"
    assert not loaded.header[0].startswith("\ufeff")
    assert loaded.delimiter == ","


def test_gb18030_chinese_header_decoded():
    """编码回退链：GB18030 中文表头要能读出来并映射成规范列名。"""
    loaded = service.load_sample("gb18030")
    assert loaded.encoding == "gb18030"
    assert loaded.header[0] == "传感器"
    parsed = reader.read_records(decode.decode_bytes(loaded.path.read_bytes()).text)
    assert parsed.canonical[:4] == ("sensor_id", "sampled_at", "offset_seconds", "value")
    assert len(parsed.rows) == 3


def test_original_row_numbers_preserved():
    """原始行号从 1 开始，跨过空行不跳号，隔离行也带行号。"""
    loaded = service.load_sample("telemetry_raw")
    numbers = [row.source_row for row in loaded.rows]
    assert numbers[0] == 1
    assert numbers == list(range(1, len(numbers) + 1))
    assert "XX-99" in {row.cells["sensor_id"] for row in loaded.rows}


def test_repeated_header_segment_counted():
    """分段导出的重复表头要被剔除并计分段，不能当数据。"""
    loaded = service.load_sample("crlf_quoted")
    assert loaded.segments == 1
    assert loaded.data_rows == 4


def test_missing_required_column_raises():
    """缺必需列是输入错误，直接 400，不进隔离区。"""
    with pytest.raises(InputError) as error:
        reader.read_records("a,b,c\n1,2,3\n")
    assert error.value.code == "HEADER_MISSING"
    assert error.value.status == 400
