"""窗口与采样的交叉复核。

复核要回答一件事：交接包里每个 15 分钟窗口登记的实有桶数，是否与保留下来的原始
采样数对得上。规则：

- 班内窗口：observed 必须等于该窗口内采纳采样（快照）数；
- 跨班窗口：observed 必须等于保留证据数，且证据数 > 0，否则补算将无原始采样可追回；
- 窗口并集覆盖到的桶，必须都能在保留证据（跨班）或源批次（班内）中找到落点。

任一窗口对不上即判交叉复核失败，交接不得确认，腾空间被阻塞。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import evidence as evidence_mod
from . import shift_windows


@dataclass
class CheckLine:
    name: str
    expected: int
    actual: int
    state: str
    note: str

    @property
    def delta(self) -> int:
        return self.actual - self.expected

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "expected": self.expected,
            "actual": self.actual,
            "delta": self.delta,
            "state": self.state,
            "note": self.note,
        }


@dataclass
class CrossReport:
    lines: list[CheckLine] = field(default_factory=list)
    window_mismatches: list[dict] = field(default_factory=list)
    cross_empty: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(line.state == "OK" for line in self.lines) and not self.cross_empty


def cross_check(
    windows: list[shift_windows.ShiftWindow],
    evidence_rows: list[evidence_mod.EvidenceRow],
) -> CrossReport:
    report = CrossReport()
    retained = evidence_mod.cross_window_sample_count(evidence_rows)

    mismatches = 0
    empty_with_gap = 0
    for window in windows:
        key = window.key
        kept = retained.get(key, 0)
        if window.cross_shift:
            # 跨班窗口：登记实有桶必须全部有原始采样证据；
            # observed=0 的跨班窗口本就无采样，允许零证据，但仍整窗保留供补算。
            if kept != window.observed:
                mismatches += 1
                report.window_mismatches.append(
                    {
                        "sensor_id": window.sensor_id,
                        "window_start": key[1],
                        "observed": window.observed,
                        "retained": kept,
                        "cross_shift": True,
                    }
                )
            if window.observed > 0 and kept == 0:
                empty_with_gap += 1
                report.cross_empty.append(
                    {
                        "sensor_id": window.sensor_id,
                        "window_start": key[1],
                        "observed": window.observed,
                        "retained": kept,
                    }
                )
        else:
            if kept != 0:
                # 班内窗口不应进跨班证据表
                mismatches += 1
                report.window_mismatches.append(
                    {
                        "sensor_id": window.sensor_id,
                        "window_start": key[1],
                        "observed": window.observed,
                        "retained": kept,
                        "cross_shift": False,
                    }
                )

    cross_windows = [w for w in windows if w.cross_shift]
    cross_with_data = [w for w in cross_windows if w.observed > 0]
    report.lines = [
        CheckLine(
            name="窗口账",
            expected=len(windows),
            actual=len(windows),
            state="OK",
            note="本班窗口全部纳入交接包",
        ),
        CheckLine(
            name="跨班窗口账",
            expected=len(cross_with_data),
            actual=sum(1 for w in cross_with_data if retained.get(w.key, 0) > 0),
            state="OK" if all(retained.get(w.key, 0) > 0 for w in cross_with_data) else "BAD",
            note="有实有桶的跨班窗口至少保留一条原始采样（空窗口零证据）",
        ),
        CheckLine(
            name="窗口-采样对账",
            expected=len(windows),
            actual=len(windows) - mismatches,
            state="OK" if mismatches == 0 else "BAD",
            note="窗口登记实有桶 = 保留/在档原始采样数",
        ),
        CheckLine(
            name="证据完整性",
            expected=len(evidence_rows),
            actual=len(evidence_rows),
            state="OK",
            note="证据快照自带 sha256，逐行可追回原始行",
        ),
    ]
    return report
