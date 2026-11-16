"""质量编排：逐行判定、迟到标记、隔离结论。

有序单遍：按文件到达顺序推进水位（已见最大桶），因此「迟到」是到达顺序的性质，
而不是数据自身的性质；重跑同一文件得到同一批迟到标记。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app import config, store

from . import metrics, quarantine, rules


@dataclass(frozen=True)
class Judged:
    source_row: int
    sensor_id: str
    spec: object
    bucket: datetime
    value: Decimal
    unit: str
    quality: str
    quality_rank: int
    ingest_seq: int
    offset: int
    late: bool
    flags: tuple[str, ...]


@dataclass
class JudgeResult:
    judged: list[Judged] = field(default_factory=list)
    rejects: list[dict] = field(default_factory=list)

    @property
    def late_count(self) -> int:
        return sum(1 for row in self.judged if row.late)


def judge_all(rows) -> JudgeResult:
    result = JudgeResult()
    max_bucket: datetime | None = None
    for row in rows:
        watermark = rules.watermark_for(max_bucket)
        verdict = rules.judge(row, watermark)
        max_bucket = row.bucket if max_bucket is None else max(max_bucket, row.bucket)
        if verdict.ok:
            flags = list(row.flags)
            if verdict.lateness:
                flags.append("LATE_ARRIVAL")
            result.judged.append(
                Judged(
                    source_row=row.source_row,
                    sensor_id=row.sensor_id,
                    spec=row.spec,
                    bucket=row.bucket,
                    value=verdict.value,
                    unit=row.unit_text,
                    quality=row.quality,
                    quality_rank=rules.quality_rank(row.quality),
                    ingest_seq=row.ingest_seq,
                    offset=row.offset,
                    late=verdict.lateness,
                    flags=tuple(flags),
                )
            )
        else:
            result.rejects.append(
                {
                    "source_row": row.source_row,
                    "sensor_id": row.sensor_id,
                    "column_name": "value" if verdict.code in {"SENTINEL_VALUE", "NOT_DECIMAL", "OUT_OF_RANGE"} else "unit",
                    "raw_value": row.value_text,
                    "code": verdict.code,
                    "detail": verdict.detail,
                }
            )
    return result


def quality_view(conn, run_id: str) -> dict:
    return {
        "summary": metrics.summary(conn, run_id),
        "rows": quarantine.rows_of(conn, run_id, limit=400),
        "distribution": quarantine.distribution(conn, run_id),
        "by_sensor": quarantine.by_sensor(conn, run_id),
        "quality": metrics.quality_breakdown(conn, run_id),
    }


def persist_samples(conn, run_id: str, judged: list[Judged]) -> int:
    payload = [
        (
            run_id,
            row.source_row,
            row.sensor_id,
            row.bucket.strftime("%Y-%m-%dT%H:%M:%SZ"),
            str(row.value),
            row.unit,
            row.quality,
            row.quality_rank,
            row.ingest_seq,
            row.offset,
            1 if row.late else 0,
            ",".join(row.flags),
        )
        for row in judged
    ]
    return store.insert_many(
        conn,
        "INSERT INTO samples(run_id, source_row, sensor_id, bucket_utc, value, unit, quality,"
        " quality_rank, ingest_seq, offset_seconds, late, flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        payload,
    )


def load_samples(conn, run_id: str) -> list[dict]:
    rows = store.rows(
        conn,
        "SELECT * FROM samples WHERE run_id = ? ORDER BY sensor_id, bucket_utc",
        (run_id,),
    )
    return [dict(row) for row in rows]


def load_judged(conn, run_id: str) -> list[Judged]:
    """从落库样本还原采纳行，供网格/缺口重新推导使用（结果必须与首次一致）。"""
    from app.modules.m2_timebase import coerce, contract

    rows = store.rows(
        conn,
        "SELECT * FROM samples WHERE run_id = ? ORDER BY sensor_id, bucket_utc",
        (run_id,),
    )
    restored: list[Judged] = []
    for row in rows:
        spec = contract.spec(row["sensor_id"])
        if spec is None:  # pragma: no cover - 采纳阶段已按契约过滤
            continue
        flags = tuple(part for part in (row["flags"] or "").split(",") if part)
        restored.append(
            Judged(
                source_row=row["source_row"],
                sensor_id=row["sensor_id"],
                spec=spec,
                bucket=coerce.to_utc(row["bucket_utc"]),
                value=Decimal(row["value"]),
                unit=row["unit"],
                quality=row["quality"],
                quality_rank=row["quality_rank"],
                ingest_seq=row["ingest_seq"],
                offset=row["offset_seconds"],
                late=bool(row["late"]),
                flags=flags,
            )
        )
    return restored


def accepted_count(conn, run_id: str) -> int:
    return int(store.value(conn, "SELECT COUNT(*) FROM samples WHERE run_id = ?", (run_id,), 0))
