"""CSV 导出：网格、采纳行。

导出列固定，行号连续；时间同时给 UTC 与 +08:00 两列，值按落库字面量输出，
不再二次格式化，避免导出与页面不一致。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from app import config, store

GRID_COLUMNS = (
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
)

ACCEPTED_COLUMNS = (
    "row_no",
    "source_row",
    "sensor_id",
    "bucket_utc",
    "value",
    "unit",
    "quality",
    "ingest_seq",
    "offset_seconds",
    "flags",
)


def local_text(utc_text: str) -> str:
    if not utc_text:
        return ""
    raw = utc_text[:-1] + "+00:00" if utc_text.endswith("Z") else utc_text
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return utc_text
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(config.CN_TZ).strftime("%Y-%m-%d %H:%M")


def grid_export(conn, run_id: str) -> tuple[tuple[str, ...], list[list]]:
    rows = store.rows(
        conn,
        "SELECT g.sensor_id, g.bucket_utc, g.value, g.unit, g.state, g.reason, g.source_row,"
        " s.flags AS flags FROM grid g LEFT JOIN samples s"
        " ON s.run_id = g.run_id AND s.sensor_id = g.sensor_id AND s.bucket_utc = g.bucket_utc"
        " WHERE g.run_id = ? ORDER BY g.sensor_id, g.bucket_utc",
        (run_id,),
    )
    payload = []
    for index, row in enumerate(rows, 1):
        payload.append(
            [
                index,
                row["sensor_id"],
                row["bucket_utc"],
                local_text(row["bucket_utc"]),
                "" if row["value"] is None else row["value"],
                row["unit"],
                row["state"],
                row["reason"] or "",
                "" if row["source_row"] is None else row["source_row"],
                row["flags"] or "",
            ]
        )
    return GRID_COLUMNS, payload


def accepted_export(conn, run_id: str) -> tuple[tuple[str, ...], list[list]]:
    rows = store.rows(
        conn,
        "SELECT * FROM samples WHERE run_id = ? ORDER BY sensor_id, bucket_utc",
        (run_id,),
    )
    payload = []
    for index, row in enumerate(rows, 1):
        payload.append(
            [
                index,
                row["source_row"],
                row["sensor_id"],
                row["bucket_utc"],
                row["value"],
                row["unit"],
                row["quality"],
                row["ingest_seq"],
                row["offset_seconds"],
                row["flags"] or "",
            ]
        )
    return ACCEPTED_COLUMNS, payload


def write_csv(columns: tuple[str, ...], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()
