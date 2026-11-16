"""时基契约：传感器规格、采样率、量程、补齐策略。

单位、量程、采样率只在这里定义；网格应有桶数由采样率派生，不写死分钟数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class SensorSpec:
    sensor_id: str
    label: str
    unit: str
    rate_minutes: int
    low: Decimal
    high: Decimal
    fill_policy: str
    places: int = 1


SENSORS: dict[str, SensorSpec] = {
    item.sensor_id: item
    for item in (
        SensorSpec("TH-01", "温湿度 01", "%RH", 1, D("0"), D("100"), "hold", 1),
        SensorSpec("TH-02", "温湿度 02", "%RH", 1, D("0"), D("100"), "linear", 1),
        SensorSpec("PM-02", "颗粒物 02", "µg/m³", 5, D("0"), D("500"), "hold", 1),
        SensorSpec("CO-03", "一氧化碳 03", "ppm", 5, D("0"), D("50"), "linear", 2),
        SensorSpec("NO-04", "氮氧化物 04", "ppb", 15, D("0"), D("2000"), "hold", 1),
        SensorSpec("WS-05", "风速 05", "m/s", 1, D("0"), D("40"), "linear", 2),
        SensorSpec("AM-06", "氨气 06", "ppm", 5, D("0"), D("50"), "hold", 2),
        SensorSpec("GH-07", "气压 07", "hPa", 5, D("300"), D("1100"), "hold", 1),
    )
}

UNIT_KEYS = {
    "%rh": "%RH",
    "rh": "%RH",
    "ug/m3": "µg/m³",
    "µg/m³": "µg/m³",
    "μg/m³": "µg/m³",
    "ppm": "ppm",
    "ppb": "ppb",
    "m/s": "m/s",
    "mps": "m/s",
    "m/s²": "m/s²",
    "hpa": "hPa",
}

FILL_POLICIES = ("hold", "linear")


def spec(sensor_id: str) -> SensorSpec | None:
    return SENSORS.get((sensor_id or "").strip())


def unit_key(text: str) -> str:
    key = (text or "").strip().replace("\n", "").replace(" ", "").lower()
    return UNIT_KEYS.get(key, key)


def unit_matches(text: str, expected: str) -> bool:
    return unit_key(text) == unit_key(expected)


def align_window(moment: datetime, minutes: int = 15) -> datetime:
    remainder = moment.minute % minutes
    return moment.replace(minute=moment.minute - remainder, second=0, microsecond=0)


def window_bounds(start: datetime, end: datetime, minutes: int = 15) -> list[tuple[datetime, datetime]]:
    cursor = align_window(start, minutes)
    windows: list[tuple[datetime, datetime]] = []
    step = timedelta(minutes=minutes)
    while cursor < end:
        windows.append((cursor, cursor + step))
        cursor += step
    return windows


def expected_minutes(rate_minutes: int, start: datetime, end: datetime) -> list[datetime]:
    """按采样率派生的应有桶；rate=1 就是每分钟一个。"""
    rate = max(1, int(rate_minutes))
    step = timedelta(minutes=rate)
    cursor = start.replace(second=0, microsecond=0)
    while cursor.minute % rate != 0:
        cursor += timedelta(minutes=1)
    buckets: list[datetime] = []
    while cursor < end:
        buckets.append(cursor)
        cursor += step
    return buckets


def expected_in_window(rate_minutes: int, window_start: datetime, window_end: datetime) -> int:
    return len(expected_minutes(rate_minutes, window_start, window_end))


def contract_view() -> list[dict]:
    letters = "ABCDEFGH"
    items = []
    for index, item in enumerate(sorted(SENSORS.values(), key=lambda spec_: spec_.sensor_id)):
        items.append(
            {
                "letter": letters[index % len(letters)],
                "sensor_id": item.sensor_id,
                "label": item.label,
                "unit": item.unit,
                "rate": item.rate_minutes,
                "low": str(item.low),
                "high": str(item.high),
                "policy": item.fill_policy,
            }
        )
    return items
