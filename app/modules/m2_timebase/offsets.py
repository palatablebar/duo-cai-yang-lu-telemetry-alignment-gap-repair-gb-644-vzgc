"""设备偏移表：按 `[effective_from, effective_to)` 解析，重叠即歧义。

偏移表是权威来源；文件里自带的偏移列只作对照，两者不一致时记冲突标记但不改判。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from . import coerce

OFFSET_COLUMNS = ("sensor_id", "effective_from", "effective_to", "offset_seconds")

ALIASES = {
    "sensor": "sensor_id",
    "传感器": "sensor_id",
    "生效起": "effective_from",
    "生效自": "effective_from",
    "生效止": "effective_to",
    "生效至": "effective_to",
    "偏移秒": "offset_seconds",
    "偏移": "offset_seconds",
}


@dataclass(frozen=True)
class OffsetEntry:
    sensor_id: str
    start: datetime
    end: datetime
    seconds: int


@dataclass(frozen=True)
class Resolution:
    seconds: int
    code: str | None
    candidates: tuple[int, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return self.code == "OFFSET_AMBIGUOUS"


def _canonical(name: str) -> str:
    key = (name or "").replace("\ufeff", "").strip()
    if key in OFFSET_COLUMNS:
        return key
    return ALIASES.get(key, ALIASES.get(key.lower(), key))


def parse_rows(text: str) -> list[OffsetEntry]:
    reader = csv.reader(io.StringIO(text, newline=""))
    header: list[str] | None = None
    entries: list[OffsetEntry] = []
    for record in reader:
        if not any((cell or "").strip() for cell in record):
            continue
        if header is None:
            header = [_canonical(cell) for cell in record]
            missing = [name for name in OFFSET_COLUMNS if name not in header]
            if missing:
                raise ValueError("offset header missing: " + ",".join(missing))
            continue
        cells = {header[index]: (record[index] or "").strip() for index in range(min(len(header), len(record)))}
        sensor_id = cells.get("sensor_id", "")
        if not sensor_id:
            continue
        start = coerce.to_utc(cells.get("effective_from", ""))
        end = coerce.to_utc(cells.get("effective_to", ""))
        if end <= start:
            raise ValueError(f"offset window inverted: {sensor_id}")
        entries.append(
            OffsetEntry(
                sensor_id=sensor_id,
                start=start,
                end=end,
                seconds=coerce.parse_seconds(cells.get("offset_seconds", "")) or 0,
            )
        )
    return entries


def filter_sensor(entries: list[OffsetEntry], sensor_id: str) -> list[OffsetEntry]:
    return [item for item in entries if item.sensor_id == sensor_id]


def resolve(entries: list[OffsetEntry], sensor_id: str, instant: datetime) -> Resolution:
    hits = [
        item
        for item in entries
        if item.sensor_id == sensor_id and item.start <= instant < item.end
    ]
    if len(hits) > 1:
        return Resolution(
            seconds=0,
            code="OFFSET_AMBIGUOUS",
            candidates=tuple(sorted({item.seconds for item in hits})),
        )
    if len(hits) == 1:
        return Resolution(seconds=hits[0].seconds, code=None)
    return Resolution(seconds=0, code="OFFSET_ASSUMED")


def default_window() -> tuple[datetime, datetime]:
    return (
        coerce.to_utc("2026-02-01T00:00:00Z"),
        coerce.to_utc("2026-04-01T00:00:00Z"),
    )


def describe(entry: OffsetEntry) -> dict:
    return {
        "sensor_id": entry.sensor_id,
        "start": coerce.minute_text(entry.start),
        "end": coerce.minute_text(entry.end),
        "seconds": entry.seconds,
        "window": "[start, end)",
    }
