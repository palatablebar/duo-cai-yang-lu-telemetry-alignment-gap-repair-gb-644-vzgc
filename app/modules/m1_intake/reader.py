"""流式读行：保留原始行号、剔除重复表头、列数严格校验。

用 csv 模块按逻辑记录解析，因此单元格内换行不会被切成两条记录；
空行、重复表头、列数不齐各自走不同分支，绝不静默补位。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from app.errors import InputError

from . import sniff


@dataclass(frozen=True)
class RowIssue:
    source_row: int
    code: str
    detail: str
    raw: str = ""


@dataclass(frozen=True)
class RawRow:
    source_row: int
    cells: dict[str, str]
    raw: tuple[str, ...]


@dataclass
class ReadResult:
    delimiter: str = ","
    header: tuple[str, ...] = ()
    canonical: tuple[str, ...] = ()
    rows: list[RawRow] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)
    blank_lines: int = 0
    segments: int = 0
    truncated: bool = False
    data_rows: int = 0
    empty_code: str | None = None


def _blank(record: list[str]) -> bool:
    return not any((cell or "").strip() for cell in record)


def read_records(text: str) -> ReadResult:
    if text is None or text.strip() == "":
        return ReadResult(empty_code="ALL_BLANK")

    delimiter = sniff.detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)

    header: list[str] | None = None
    blank_lines = 0
    for record in reader:
        if _blank(record):
            blank_lines += 1
            continue
        header = [sniff.normalize_cell(cell) for cell in record]
        break

    if header is None:
        return ReadResult(delimiter=delimiter, blank_lines=blank_lines, empty_code="ALL_BLANK")

    canonical = sniff.canonical_header(header)
    missing = [name for name in sniff.REQUIRED_COLUMNS if name not in canonical]
    if missing:
        raise InputError(
            "表头缺少必需列",
            code="HEADER_MISSING",
            detail={"missing": missing, "header": header},
        )

    result = ReadResult(
        delimiter=delimiter,
        header=tuple(header),
        canonical=canonical,
        blank_lines=blank_lines,
    )
    tail_unterminated = not text.endswith("\n")

    def consume(record: list[str], is_last: bool) -> None:
        if _blank(record):
            result.blank_lines += 1
            return
        if sniff.is_repeated_header(record, canonical):
            result.segments += 1
            return
        result.data_rows += 1
        row_no = result.data_rows
        if len(record) != len(canonical):
            truncated = is_last and tail_unterminated
            if truncated:
                result.truncated = True
            result.issues.append(
                RowIssue(
                    source_row=row_no,
                    code="TRUNCATED_TAIL" if truncated else "COLUMN_COUNT",
                    detail=f"{len(record)}/{len(canonical)}",
                    raw=delimiter.join(record),
                )
            )
            return
        cells = {}
        for index, name in enumerate(canonical):
            cells[name] = (record[index] or "").strip()
        result.rows.append(RawRow(source_row=row_no, cells=cells, raw=tuple(record)))

    pending: list[str] | None = None
    for record in reader:
        if pending is not None:
            consume(pending, False)
        pending = record
    if pending is not None:
        consume(pending, True)

    if result.data_rows == 0:
        result.empty_code = "HEADER_ONLY"
    return result
