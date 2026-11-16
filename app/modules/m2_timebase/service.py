"""时基编排：加载偏移表、把采样归一到 UTC 分钟桶、暴露契约视图。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app import config, manifest, store

from . import coerce, contract, offsets

from app.modules.m1_intake import decode, service as intake_service


@dataclass
class OffsetTable:
    key: str
    file_name: str
    sha256: str
    size: int
    entries: list[offsets.OffsetEntry] = field(default_factory=list)


@dataclass(frozen=True)
class NormRow:
    source_row: int
    sensor_id: str
    spec: contract.SensorSpec
    instant: datetime
    bucket: datetime
    offset: int
    value_text: str
    unit_text: str
    quality: str
    ingest_seq: int
    flags: tuple[str, ...]


@dataclass(frozen=True)
class NormReject:
    source_row: int
    sensor_id: str
    column_name: str
    raw_value: str
    code: str
    detail: str


@dataclass
class NormResult:
    rows: list[NormRow] = field(default_factory=list)
    rejects: list[NormReject] = field(default_factory=list)
    tz_written: int = 0


def load_offsets(key: str) -> OffsetTable:
    from app.errors import InputError, NotFoundError

    if key not in config.OFFSET_SAMPLES:
        raise InputError("未知偏移表", code="OFFSET_TABLE_UNKNOWN", detail={"offsets": key})
    path = config.offset_file(key)
    if not path.exists():
        raise NotFoundError("偏移表不存在", code="OFFSET_TABLE_MISSING", detail={"path": str(path)})

    raw = path.read_bytes()
    table = OffsetTable(
        key=key,
        file_name=path.name,
        sha256=manifest.sha256_bytes(raw),
        size=len(raw),
    )
    decoded = decode.decode_bytes(raw)
    table.entries = offsets.parse_rows(decoded.text)
    return table


def normalize(sample, table: OffsetTable) -> NormResult:
    result = NormResult()
    for row in sample.rows:
        sensor_id = (row.cells.get("sensor_id") or "").strip()
        spec = contract.spec(sensor_id)
        if spec is None:
            result.rejects.append(
                NormReject(
                    source_row=row.source_row,
                    sensor_id=sensor_id,
                    column_name="sensor_id",
                    raw_value=sensor_id,
                    code="UNKNOWN_SENSOR",
                    detail="契约表无此传感器",
                )
            )
            continue

        raw_time = row.cells.get("sampled_at", "")
        try:
            instant = coerce.to_utc(raw_time)
        except coerce.CoerceError:
            result.rejects.append(
                NormReject(
                    source_row=row.source_row,
                    sensor_id=sensor_id,
                    column_name="sampled_at",
                    raw_value=raw_time,
                    code="TIMESTAMP_INVALID",
                    detail="时间无法解析",
                )
            )
            continue

        resolution = offsets.resolve(table.entries, sensor_id, instant)
        if resolution.ambiguous:
            result.rejects.append(
                NormReject(
                    source_row=row.source_row,
                    sensor_id=sensor_id,
                    column_name="offset_seconds",
                    raw_value="/".join(str(item) for item in resolution.candidates),
                    code="OFFSET_AMBIGUOUS",
                    detail="偏移表区间重叠",
                )
            )
            continue

        reported = coerce.parse_seconds(row.cells.get("offset_seconds", ""))
        flags: list[str] = []
        if resolution.code == "OFFSET_ASSUMED":
            offset = reported if reported is not None else 0
            flags.append("OFFSET_ASSUMED")
        else:
            offset = resolution.seconds
            if reported is not None and reported != offset:
                flags.append("OFFSET_CONFLICT")

        utc = instant - timedelta(seconds=offset)
        bucket = coerce.floor_minute(utc)
        if coerce.has_explicit_offset(raw_time) and not raw_time.strip().endswith(("Z", "z")):
            result.tz_written += 1

        ingest = coerce.parse_seconds(row.cells.get("ingest_seq", ""))
        result.rows.append(
            NormRow(
                source_row=row.source_row,
                sensor_id=sensor_id,
                spec=spec,
                instant=instant,
                bucket=bucket,
                offset=offset,
                value_text=row.cells.get("value", ""),
                unit_text=row.cells.get("unit", ""),
                quality=(row.cells.get("quality") or "").strip().lower() or config.DEFAULT_QUALITY,
                ingest_seq=ingest if ingest is not None else row.source_row,
                flags=tuple(flags),
            )
        )
    return result


def offset_view(conn, run_id: str) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT * FROM offsets WHERE run_id = ? ORDER BY sensor_id, start_utc",
        (run_id,),
    )
    return [
        {
            "sensor_id": row["sensor_id"],
            "start": row["start_utc"],
            "end": row["end_utc"],
            "seconds": row["seconds"],
        }
        for row in rows
    ]


def summary(conn, run_id: str) -> dict:
    offset_rows = store.rows(conn, "SELECT * FROM offsets WHERE run_id = ?", (run_id,))
    samples = store.rows(conn, "SELECT late, flags FROM samples WHERE run_id = ?", (run_id,))
    assumed = sum(1 for row in samples if "OFFSET_ASSUMED" in (row["flags"] or ""))
    conflict = sum(1 for row in samples if "OFFSET_CONFLICT" in (row["flags"] or ""))
    late = sum(1 for row in samples if row["late"])
    return {
        "sensors": len(contract.SENSORS),
        "offset_entries": len(offset_rows),
        "accepted": len(samples),
        "late": late,
        "assumed": assumed,
        "conflict": conflict,
        "rates": sorted({item.rate_minutes for item in contract.SENSORS.values()}),
    }


def flag_counts(conn, run_id: str) -> list[dict]:
    samples = store.rows(conn, "SELECT flags FROM samples WHERE run_id = ?", (run_id,))
    counter: dict[str, int] = {}
    for row in samples:
        for flag in (row["flags"] or "").split(","):
            name = flag.strip()
            if not name:
                continue
            counter[name] = counter.get(name, 0) + 1
    from app import reasons

    return [
        {"code": code, "label": reasons.label(code), "count": counter.get(code, 0)}
        for code in ("OFFSET_ASSUMED", "OFFSET_CONFLICT", "LATE_ARRIVAL")
    ]


def contract_view() -> list[dict]:
    return contract.contract_view()


def store_offsets(conn, run_id: str, entries: list[offsets.OffsetEntry]) -> None:
    payload = [
        (run_id, item.sensor_id, coerce.minute_text(item.start), coerce.minute_text(item.end), item.seconds)
        for item in entries
    ]
    store.insert_many(
        conn,
        "INSERT INTO offsets(run_id, sensor_id, start_utc, end_utc, seconds) VALUES (?,?,?,?,?)",
        payload,
    )


def params_view() -> dict:
    return json.dumps(
        {
            "grid_minutes": config.GRID_MINUTES,
            "window_minutes": config.WINDOW_MINUTES,
            "max_fill_buckets": config.MAX_FILL_BUCKETS,
            "late_window_minutes": config.LATE_WINDOW_MINUTES,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
