"""差异归因：把不平的账翻译成一句可执行的定位线索。"""

from __future__ import annotations

from . import compare


def explain_line(line: compare.ReconcileLine, counts: dict) -> dict:
    if line.state == "OK":
        return {"line": line.name, "state": "OK", "hint": "无差异"}
    hints = {
        "行账": "检查列数不齐与未知传感器是否都落了隔离行",
        "网格账": "检查采样率与全局区间是否被改写",
        "数值账": "检查采纳值是否在补齐阶段被改写",
        "窗口账": "检查窗口是否按 15 分钟对齐生成",
    }
    return {
        "line": line.name,
        "state": "BAD",
        "hint": hints.get(line.name, "逐行核对证据"),
        "delta": str(line.delta),
    }


def explain(lines: list[compare.ReconcileLine], counts: dict) -> list[dict]:
    return [explain_line(line, counts) for line in lines]


def conclusion(lines: list[compare.ReconcileLine]) -> str:
    bad = [line.name for line in lines if line.state != "OK"]
    if not bad:
        return "四账相等"
    return "不平：" + "、".join(bad)
