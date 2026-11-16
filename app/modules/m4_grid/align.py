"""同分钟去重：先质量位，再到达顺序。

同一 (传感器, 分钟桶) 有多条时，按 good > suspect > bad 取一；质量位相同则取 ingest
较晚的一条；仍相同则取原始行号较大的一条。排序键全序且与输入顺序无关，因此打乱输入
不会改变保留结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Duplicate:
    sensor_id: str
    bucket: object
    kept_row: int
    dropped_row: int
    kept_value: str
    dropped_value: str
    kept_quality: str
    dropped_quality: str
    code: str = "DUPLICATE_MINUTE"


@dataclass
class AlignResult:
    kept: list = field(default_factory=list)
    duplicates: list[Duplicate] = field(default_factory=list)


def order_key(row):
    """全序：传感器 → 桶 → 质量位（高优先） → 到达序（晚优先） → 行号（大优先）。"""
    return (
        row.sensor_id,
        row.bucket,
        -row.quality_rank,
        -row.ingest_seq,
        -row.source_row,
    )


def align(rows) -> AlignResult:
    result = AlignResult()
    ordered = sorted(rows, key=order_key)
    for row in ordered:
        if result.kept:
            head = result.kept[-1]
            if (head.sensor_id, head.bucket) == (row.sensor_id, row.bucket):
                result.duplicates.append(
                    Duplicate(
                        sensor_id=row.sensor_id,
                        bucket=row.bucket,
                        kept_row=head.source_row,
                        dropped_row=row.source_row,
                        kept_value=str(head.value),
                        dropped_value=str(row.value),
                        kept_quality=head.quality,
                        dropped_quality=row.quality,
                    )
                )
                continue
        result.kept.append(row)
    return result


def unique_buckets(kept) -> dict:
    """(sensor, bucket) -> 值；供缺口修复与窗口覆盖使用。"""
    table: dict[tuple[str, object], object] = {}
    for row in kept:
        table[(row.sensor_id, row.bucket)] = row.value
    return table
