"""模板渲染与展示格式。

页面只放标题、字段、状态、数值与单位；格式统一在这里，模板里不再拼字符串。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import config, store

templates = Jinja2Templates(directory=str(config.TEMPLATE_DIR))

NAV = (
    {"key": "index", "href": "/", "label": "总览"},
    {"key": "samples", "href": "/samples", "label": "采样"},
    {"key": "quality", "href": "/quality", "label": "质量"},
    {"key": "grid", "href": "/grid", "label": "网格"},
    {"key": "gaps", "href": "/gaps", "label": "缺口"},
    {"key": "batches", "href": "/batches", "label": "批次"},
)


def _to_dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def f_utc(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    parsed = _to_dt(value)
    if parsed is None:
        return "—"
    return parsed.astimezone(timezone.utc).strftime(fmt)


def f_cn(value, fmt: str = "%m-%d %H:%M") -> str:
    parsed = _to_dt(value)
    if parsed is None:
        return "—"
    return parsed.astimezone(config.CN_TZ).strftime(fmt)


def f_time(value) -> str:
    parsed = _to_dt(value)
    if parsed is None:
        return "—"
    return parsed.astimezone(timezone.utc).strftime("%H:%M")


def f_num(value, places: int = config.VALUE_PLACES) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    quantum = Decimal(1).scaleb(-places)
    return str(number.quantize(quantum, rounding=ROUND_HALF_UP))


def f_pct(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value)) * Decimal(100)
    except (InvalidOperation, ValueError):
        return str(value)
    return str(number.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) + "%"


def f_int(value) -> str:
    if value is None or value == "":
        return "0"
    try:
        return str(int(Decimal(str(value))))
    except (InvalidOperation, ValueError):
        return str(value)


templates.env.filters.update(
    {
        "f_utc": f_utc,
        "f_cn": f_cn,
        "f_time": f_time,
        "f_num": f_num,
        "f_pct": f_pct,
        "f_int": f_int,
    }
)


def page_context(active: str) -> dict:
    """公共页头：6 个导航项 + 最近一次批次。"""
    from app.modules.m6_batches import history

    conn = store.session()
    try:
        run = history.latest(conn)
    finally:
        conn.close()
    return {
        "nav": NAV,
        "active": active,
        "run": run,
        "batch": run,
        "rule_version": config.RULE_VERSION,
        "tz_label": "+08:00",
    }


def render(request: Request, template: str, active: str, **context):
    payload = page_context(active)
    payload.update(context)
    payload["request"] = request
    return templates.TemplateResponse(template, payload)


def render_status(template: str, active: str, **context):
    """无请求对象的内部渲染（错误页兜底用）。"""
    payload = page_context(active)
    payload.update(context)
    payload["request"] = None
    return templates.TemplateResponse(template, payload)
