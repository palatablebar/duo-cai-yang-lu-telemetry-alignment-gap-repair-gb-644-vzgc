"""采信编排：读字节 → 解码 → 嗅探 → 逐行诊断 → 采信结论。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app import config, manifest, store
from app.errors import InputError, NotFoundError

from . import decode, reader


@dataclass
class LoadedSample:
    key: str
    file_name: str
    path: Path
    sha256: str
    size: int
    encoding: str = "utf-8"
    bom: bool = False
    delimiter: str = ","
    header: tuple[str, ...] = ()
    rows: list[reader.RawRow] = field(default_factory=list)
    issues: list[reader.RowIssue] = field(default_factory=list)
    blank_lines: int = 0
    segments: int = 0
    truncated: bool = False
    data_rows: int = 0
    empty_code: str | None = None


def sample_choices() -> list[dict]:
    return [
        {"key": key, "label": label, "file": file_name}
        for key, (file_name, label) in config.SAMPLES.items()
    ]


def offset_choices() -> list[dict]:
    return [
        {"key": key, "label": label, "file": file_name}
        for key, (file_name, label) in config.OFFSET_SAMPLES.items()
    ]


def load_sample(key: str) -> LoadedSample:
    if key not in config.SAMPLES:
        raise InputError("未知样例", code="SAMPLE_UNKNOWN", detail={"sample": key})
    path = config.sample_file(key)
    if not path.exists():
        raise NotFoundError("样例文件不存在", code="SAMPLE_MISSING", detail={"path": str(path)})

    raw = path.read_bytes()
    loaded = LoadedSample(
        key=key,
        file_name=path.name,
        path=path,
        sha256=manifest.sha256_bytes(raw),
        size=len(raw),
    )
    if len(raw) == 0:
        loaded.empty_code = "EMPTY_FILE"
        return loaded
    if raw.strip() == b"":
        loaded.empty_code = "ALL_BLANK"
        return loaded

    try:
        decoded = decode.decode_bytes(raw)
    except ValueError as exc:  # pragma: no cover - 编码链兜底
        raise InputError("编码无法识别", code="ENCODING_FAILED", detail={"file": path.name}) from exc

    loaded.encoding = decoded.encoding
    loaded.bom = decoded.bom
    parsed = reader.read_records(decoded.text)
    loaded.delimiter = parsed.delimiter
    loaded.header = parsed.header
    loaded.rows = parsed.rows
    loaded.issues = parsed.issues
    loaded.blank_lines = parsed.blank_lines
    loaded.segments = parsed.segments
    loaded.truncated = parsed.truncated
    loaded.data_rows = parsed.data_rows
    loaded.empty_code = parsed.empty_code
    return loaded


def intake_view(conn, run_id: str) -> dict | None:
    row = store.one(conn, "SELECT * FROM intake WHERE run_id = ?", (run_id,))
    if row is None:
        return None
    return {
        "encoding": row["encoding"],
        "bom": bool(row["bom"]),
        "delimiter": row["delimiter"],
        "header": json.loads(row["header_json"]),
        "segments": row["segments"],
        "blank_lines": row["blank_lines"],
        "truncated": bool(row["truncated"]),
        "byte_size": row["byte_size"],
        "sha256": row["sha256"],
    }


def intake_columns(header: list[str]) -> list[dict]:
    from . import sniff

    letters = config.COLUMN_LETTERS
    items = []
    for index, raw_name in enumerate(header):
        items.append(
            {
                "letter": letters[index % 26],
                "raw": raw_name,
                "canonical": sniff.canonical_name(raw_name),
            }
        )
    return items
