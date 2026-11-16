"""保留证据：跨班窗口内原始采样的独立快照。

证据不引用源批次表，而是把跨班窗口覆盖到的每一条采纳采样连同输入文件 sha256、
原始行号、原值逐行复制进 handover_evidence，并对快照整体再算一个 sha256。
这样即使在线数据腾出空间、源批次被清理，下一班补算仍能凭快照追回原始采样并自证未被篡改。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from app import manifest, store

from . import shift_windows


@dataclass(frozen=True)
class EvidenceRow:
    sensor_id: str
    bucket_utc: str
    source_row: int
    value: str | None
    unit: str
    quality: str
    raw_value: str | None
    sample_sha256: str
    window_start: str
    cross_shift: int


def _input_sha256(conn, run_id: str) -> str:
    """取采样输入（非偏移表）的 sha256；run_key 输入按名称排序，采样文件即 telemetry 类。"""
    raw = store.one(conn, "SELECT input_json FROM runs WHERE run_id = ?", (run_id,))
    if raw is None:
        return ""
    inputs = json.loads(raw["input_json"])
    # 偏移表固定名 device_offsets.csv，其余即采样输入
    for item in inputs:
        if "offset" not in item["name"]:
            return item["sha256"]
    return inputs[0]["sha256"] if inputs else ""


def build(conn, run_id: str, windows: list[shift_windows.ShiftWindow]) -> list[EvidenceRow]:
    """为跨班窗口覆盖到的采纳采样逐条建快照。"""
    cross = [w for w in windows if w.cross_shift]
    if not cross:
        return []

    # 每个传感器的跨班窗口并集区间（窗口相邻时合并），用于一次性圈定桶
    by_sensor: dict[str, list[shift_windows.ShiftWindow]] = {}
    for window in cross:
        by_sensor.setdefault(window.sensor_id, []).append(window)

    sample_sha = _input_sha256(conn, run_id)
    rows: list[EvidenceRow] = []
    for sensor_id in sorted(by_sensor):
        spans = sorted(by_sensor[sensor_id], key=lambda w: w.start)
        samples = store.rows(
            conn,
            "SELECT sensor_id, bucket_utc, value, unit, quality, source_row"
            " FROM samples WHERE run_id = ? AND sensor_id = ?"
            " ORDER BY bucket_utc",
            (run_id, sensor_id),
        )
        by_bucket = {row["bucket_utc"]: row for row in samples}
        for window in spans:
            start_text = window.start.strftime("%Y-%m-%dT%H:%M:%SZ")
            for bucket in _buckets_in_window(window):
                bucket_text = bucket.strftime("%Y-%m-%dT%H:%M:%SZ")
                sample = by_bucket.get(bucket_text)
                if sample is None:
                    continue  # 缺口/补齐桶没有原始采样，不属于「原始采样证据」
                rows.append(
                    EvidenceRow(
                        sensor_id=sensor_id,
                        bucket_utc=bucket_text,
                        source_row=sample["source_row"],
                        value=sample["value"],
                        unit=sample["unit"],
                        quality=sample["quality"],
                        raw_value=sample["value"],
                        sample_sha256=sample_sha,
                        window_start=start_text,
                        cross_shift=1,
                    )
                )
    rows.sort(key=lambda item: (item.sensor_id, item.bucket_utc))
    return rows


def _buckets_in_window(window: shift_windows.ShiftWindow) -> list[datetime]:
    from app.modules.m2_timebase import contract

    return contract.expected_minutes(1, window.start, window.end)


def snapshot_digest(rows: list[EvidenceRow]) -> str:
    """对快照内容做确定性 sha256：任一行被改动都会改变摘要。"""
    material = [
        {
            "sensor_id": r.sensor_id,
            "bucket_utc": r.bucket_utc,
            "source_row": r.source_row,
            "value": r.value,
            "unit": r.unit,
            "quality": r.quality,
            "sample_sha256": r.sample_sha256,
            "window_start": r.window_start,
        }
        for r in rows
    ]
    return manifest.sha256_bytes(
        manifest.canonical_json(material).encode("utf-8")
    )


def cross_window_sample_count(rows: list[EvidenceRow]) -> dict[tuple[str, str], int]:
    """按 (传感器, 窗口起点) 统计保留的原始采样数，供与窗口 observed 交叉复核。"""
    counter: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.sensor_id, row.window_start)
        counter[key] = counter.get(key, 0) + 1
    return counter
