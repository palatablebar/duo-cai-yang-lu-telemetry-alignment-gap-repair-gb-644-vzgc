"""隔离区落盘、原因分布与 CSV 导出。

隔离行永远带 source_row（原始行号）、列名与原值，导出后能直接回原文核对。
"""

from __future__ import annotations

import csv
import io
import json

from app import reasons, store

CSV_COLUMNS = (
    "row_no",
    "source_row",
    "sensor_id",
    "column_name",
    "raw_value",
    "code",
    "label",
    "detail",
)

INSERT_SQL = (
    "INSERT INTO quarantine(run_id, source_row, sensor_id, column_name, raw_value, code, label, detail)"
    " VALUES (?,?,?,?,?,?,?,?)"
)


def write(conn, run_id: str, entries: list[dict]) -> int:
    payload = [
        (
            run_id,
            item.get("source_row", 0),
            item.get("sensor_id", ""),
            item.get("column_name", ""),
            (item.get("raw_value") or "")[:400],
            item["code"],
            reasons.label(item["code"]),
            (item.get("detail") or "")[:300],
        )
        for item in entries
    ]
    return store.insert_many(conn, INSERT_SQL, payload)


def rows_of(conn, run_id: str, limit: int | None = None) -> list[dict]:
    sql = "SELECT * FROM quarantine WHERE run_id = ? ORDER BY source_row, code"
    params: list = [run_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [
        {
            "source_row": row["source_row"],
            "sensor_id": row["sensor_id"],
            "column_name": row["column_name"],
            "raw_value": row["raw_value"],
            "code": row["code"],
            "label": row["label"],
            "detail": row["detail"],
        }
        for row in store.rows(conn, sql, tuple(params))
    ]


def distribution(conn, run_id: str) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT code, COUNT(*) AS n FROM quarantine WHERE run_id = ? GROUP BY code ORDER BY n DESC, code",
        (run_id,),
    )
    return [
        {"code": row["code"], "label": reasons.label(row["code"]), "count": row["n"]}
        for row in rows
    ]


def by_sensor(conn, run_id: str) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT sensor_id, COUNT(*) AS n FROM quarantine WHERE run_id = ?"
        " GROUP BY sensor_id ORDER BY n DESC, sensor_id",
        (run_id,),
    )
    return [{"sensor_id": row["sensor_id"] or "—", "count": row["n"]} for row in rows]


def count(conn, run_id: str) -> int:
    return int(store.value(conn, "SELECT COUNT(*) FROM quarantine WHERE run_id = ?", (run_id,), 0))


def to_csv(entries: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for index, item in enumerate(entries, 1):
        writer.writerow(
            [
                index,
                item.get("source_row", ""),
                item.get("sensor_id", ""),
                item.get("column_name", ""),
                item.get("raw_value", ""),
                item.get("code", ""),
                reasons.label(item.get("code", "")),
                item.get("detail", ""),
            ]
        )
    return buffer.getvalue()


def detail_json(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True)
