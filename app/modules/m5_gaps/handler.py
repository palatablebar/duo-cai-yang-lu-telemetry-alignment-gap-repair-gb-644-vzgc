"""M5 缺口修复的入口：缺口页、缺口段与窗口覆盖、重新推导校验。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import errors, store, web
from app.modules.m6_batches import history
from app.modules.m6_batches import service as batch_service

from . import service

router = APIRouter(tags=["m5 缺口修复"])


@router.get("/gaps", response_class=HTMLResponse)
def gaps_page(request: Request):
    conn = store.session()
    try:
        run = history.latest(conn)
        view = service.gaps_view(conn, run["run_id"]) if run else None
    finally:
        conn.close()
    return web.render(request, "gaps.html", "gaps", view=view)


@router.get("/api/gaps")
def gaps_api():
    conn = store.session()
    try:
        run = history.latest(conn)
        if run is None:
            raise errors.NotFoundError("还没有批次", code="NO_RUN")
        return service.gaps_view(conn, run["run_id"])
    finally:
        conn.close()


@router.post("/api/gaps/repair")
def gaps_repair():
    """从已采纳样本重新推导缺口，并与落库网格逐行比对。"""
    conn = store.session()
    try:
        run = history.latest(conn)
        if run is None:
            raise errors.NotFoundError("还没有批次", code="NO_RUN")
        return batch_service.verify_gaps(conn, run["run_id"])
    finally:
        conn.close()
