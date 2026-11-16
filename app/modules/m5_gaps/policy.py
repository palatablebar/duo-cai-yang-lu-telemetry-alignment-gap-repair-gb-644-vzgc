"""补齐策略：每个传感器在契约里声明 hold 或 linear，阈值集中在这里。"""

from __future__ import annotations

from app import config

from app.modules.m2_timebase import contract

POLICY_HOLD = "hold"
POLICY_LINEAR = "linear"

REASON_BY_POLICY = {
    POLICY_HOLD: "FILLED_HOLD",
    POLICY_LINEAR: "FILLED_LINEAR",
}


def resolve(spec) -> str:
    policy = (getattr(spec, "fill_policy", "") or "").strip().lower()
    return policy if policy in contract.FILL_POLICIES else POLICY_HOLD


def reason_for(policy: str) -> str:
    return REASON_BY_POLICY.get(policy, "FILLED_HOLD")


def max_fill() -> int:
    return config.MAX_FILL_BUCKETS


def fillable(length: int) -> bool:
    return 0 < length <= max_fill()


def needs_next_anchor(policy: str) -> bool:
    return policy == POLICY_LINEAR


def describe(policy: str) -> str:
    return "保持" if policy == POLICY_HOLD else "线性"
