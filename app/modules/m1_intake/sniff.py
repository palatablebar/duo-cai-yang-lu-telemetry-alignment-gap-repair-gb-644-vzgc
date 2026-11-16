"""分隔符、表头与分段探测。

真实导出件里表头可能带 BOM、带空格、用中文列名，也可能在分段导出时重复出现；
这些都在这里收口，reader 只按规范化列名取值。
"""

from __future__ import annotations

from dataclasses import dataclass

REQUIRED_COLUMNS = (
    "sensor_id",
    "sampled_at",
    "offset_seconds",
    "value",
    "unit",
    "quality",
    "ingest_seq",
)

HEADER_ALIASES = {
    # 英文常见写法
    "sensor": "sensor_id",
    "sensorid": "sensor_id",
    "sensor_id": "sensor_id",
    "id": "sensor_id",
    "ts": "sampled_at",
    "time": "sampled_at",
    "timestamp": "sampled_at",
    "sampled_at": "sampled_at",
    "sampledat": "sampled_at",
    "offset": "offset_seconds",
    "offset_seconds": "offset_seconds",
    "offsetsec": "offset_seconds",
    "value": "value",
    "val": "value",
    "unit": "unit",
    "quality": "quality",
    "qual": "quality",
    "ingest": "ingest_seq",
    "ingest_seq": "ingest_seq",
    "seq": "ingest_seq",
    # 中文导出件
    "传感器": "sensor_id",
    "传感器编号": "sensor_id",
    "采样时间": "sampled_at",
    "时间": "sampled_at",
    "偏移秒": "offset_seconds",
    "时钟偏移": "offset_seconds",
    "偏移": "offset_seconds",
    "数值": "value",
    "值": "value",
    "单位": "unit",
    "质量": "quality",
    "质量位": "quality",
    "入库序号": "ingest_seq",
    "序号": "ingest_seq",
}

DELIMITERS = (",", ";", "\t", "|")


@dataclass(frozen=True)
class Sniffed:
    delimiter: str
    header: tuple[str, ...]
    canonical: tuple[str, ...]
    missing: tuple[str, ...]


def normalize_cell(value: str) -> str:
    return (value or "").replace("\ufeff", "").strip()


def canonical_name(raw: str) -> str:
    key = normalize_cell(raw)
    if key in HEADER_ALIASES:
        return HEADER_ALIASES[key]
    return HEADER_ALIASES.get(key.lower(), key)


def canonical_header(cells: list[str]) -> tuple[str, ...]:
    return tuple(canonical_name(cell) for cell in cells)


def detect_delimiter(text: str) -> str:
    counts = {item: 0 for item in DELIMITERS}
    for line in text.splitlines()[:5]:
        if not line.strip():
            continue
        for item in DELIMITERS:
            counts[item] += line.count(item)
    best = max(DELIMITERS, key=lambda item: (counts[item], item == ","))
    return best if counts[best] > 0 else ","


def sniff(text: str) -> Sniffed:
    import csv
    import io

    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    header: list[str] = []
    for record in reader:
        if any(cell.strip() for cell in record):
            header = [normalize_cell(cell) for cell in record]
            break
    canonical = canonical_header(header)
    missing = tuple(name for name in REQUIRED_COLUMNS if name not in canonical)
    return Sniffed(
        delimiter=delimiter,
        header=tuple(header),
        canonical=canonical,
        missing=missing,
    )


def is_repeated_header(cells: list[str], canonical: tuple[str, ...]) -> bool:
    if len(cells) != len(canonical):
        return False
    return canonical_header(cells) == canonical
