"""跨班窗口判定。

窗口仍沿用 15 分钟左闭右开 `[start, end)`。一个窗口起点落在本班、末端越过班次日界，
即判为跨班窗口：整窗（含越界部分）原样带进交接包，下一班补算时按同一右端开区间复核，
不会在边界时刻重复计入。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import config
from app.modules.m2_timebase import coerce, contract

UTC = timezone.utc


@dataclass(frozen=True)
class ShiftWindow:
    sensor_id: str
    start: datetime
    end: datetime
    observed: int
    expected: int
    coverage: str
    state: str
    cross_shift: bool

    @property
    def key(self) -> tuple[str, str]:
        return self.sensor_id, self.start.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_bound(text: str) -> datetime:
    """解析班次日界（UTC，秒级）。允许纯日期，按当日 00:00 起算。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty boundary")
    if len(raw) == 10:
        raw = raw + "T00:00:00Z"
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0)


def shift_bounds(shift_date: str, shift_end: str | None = None) -> tuple[datetime, datetime]:
    """班次日界：[起点, 终点)。

    只传日期/起点时终点默认起点 +1 天（一个自然班）；
    显式给 shift_end 时按实际交接窗口算，便于表达小时级跨班窗口。
    """
    start = parse_bound(shift_date)
    if shift_end:
        end = parse_bound(shift_end)
        if end <= start:
            raise ValueError("shift end must be later than start")
    else:
        end = start + timedelta(days=1)
    return start, end


def is_cross_shift(start: datetime, end: datetime, shift_end: datetime) -> bool:
    """跨班窗口：末端越过班末，且窗口起点不晚于班末。

    分两种位置：
    - 起点严格在班内（`start < shift_end`）而末端越过班末：常规跨班窗口；
    - 起点恰在班末（`start == shift_end`）、末端伸入下一班：边界跨班窗口，
      左端点由本班数据支撑，仍整窗交出。
    右端开：末端恰好等于班末不算越界（如 00:00–00:15 窗口在班末 00:15 处不跨班）。
    """
    return start <= shift_end < end


def from_stored_row(row, shift_end: datetime) -> ShiftWindow:
    start = coerce.to_utc(row["window_start"])
    end = start + timedelta(minutes=config.WINDOW_MINUTES)
    return ShiftWindow(
        sensor_id=row["sensor_id"],
        start=start,
        end=end,
        observed=row["observed"],
        expected=row["expected"],
        coverage=row["coverage"],
        state=row["state"],
        cross_shift=is_cross_shift(start, end, shift_end),
    )


def collect(rows, shift_start: datetime, shift_end: datetime) -> list[ShiftWindow]:
    """挑出与本班相关的窗口并标注跨班。

    纳入条件：窗口起点落在 `[shift_start, shift_end]`。起点恰在班末的窗口，其左端点
    由本班数据支撑、末端伸入下一班，是必须整窗交出的跨班窗口，故上界取闭区间；
    起点早于班界的窗口属于上一班，不纳入。是否跨班再由末端是否越过班末判定。
    """
    out: list[ShiftWindow] = []
    for row in rows:
        window = from_stored_row(row, shift_end)
        if window.start < shift_start or window.start > shift_end:
            continue
        out.append(window)
    out.sort(key=lambda item: (item.sensor_id, item.start))
    return out


def cross_keys(windows: list[ShiftWindow]) -> set[tuple[str, str]]:
    return {item.key for item in windows if item.cross_shift}


def window_of_bucket(bucket: datetime) -> datetime:
    """桶所属 15 分钟窗口的起点。"""
    return contract.align_window(coerce.floor_minute(bucket), config.WINDOW_MINUTES)
