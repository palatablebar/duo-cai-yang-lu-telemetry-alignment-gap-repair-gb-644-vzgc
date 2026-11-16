"""质量指标：采纳率、质量位分布、隔离原因占比。

指标只做聚合，不改变任何判定；页面上的每个数字都能追到隔离行或采纳行。
"""

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP

from app import store


def quality_breakdown(conn, run_id: str) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT quality, COUNT(*) AS n FROM samples WHERE run_id = ?"
        " GROUP BY quality ORDER BY n DESC, quality",
        (run_id,),
    )
    return [{"quality": row["quality"], "count": row["n"]} for row in rows]


def sensor_breakdown(conn, run_id: str) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT sensor_id, COUNT(*) AS n FROM samples WHERE run_id = ?"
        " GROUP BY sensor_id ORDER BY sensor_id",
        (run_id,),
    )
    return [{"sensor_id": row["sensor_id"], "count": row["n"]} for row in rows]


def pass_rate(accepted: int, raw: int) -> Decimal:
    if raw <= 0:
        return Decimal("0.000")
    return (Decimal(accepted) / Decimal(raw)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def summary(conn, run_id: str) -> dict:
    row = store.one(conn, "SELECT counts_json FROM runs WHERE run_id = ?", (run_id,))
    counts = json.loads(row["counts_json"]) if row else {}
    accepted = counts.get("accepted", 0)
    quarantined = counts.get("quarantined", 0)
    duplicates = counts.get("duplicates", 0)
    raw = counts.get("raw_records", 0)
    quality = quality_breakdown(conn, run_id)
    return {
        "accepted": accepted,
        "quarantined": quarantined,
        "duplicates": duplicates,
        "raw": raw,
        "pass_rate": str(pass_rate(accepted, raw)),
        "quality": quality,
        "suspect": sum(item["count"] for item in quality if item["quality"] != "good"),
        "sensors": len(sensor_breakdown(conn, run_id)),
    }
