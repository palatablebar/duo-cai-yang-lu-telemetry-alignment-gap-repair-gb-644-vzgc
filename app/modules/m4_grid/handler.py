"""M4 网格对齐的入口：网格页、网格读取、重新推导校验。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import errors, store, web
from app.modules.m6_batches import history
from app.modules.m6_batches import service as batch_service

from . import service

router = APIRouter(tags=["m4 网格对齐"])


@router.get("/grid", response_class=HTMLResponse)
def grid_page(request: Request):
    conn = store.session()
    try:
        run = history.latest(conn)
        view = service.grid_view(conn, run["run_id"]) if run else None
        bounds = service.bucket_bounds(conn, run["run_id"]) if run else None
    finally:
        conn.close()
    return web.render(request, "grid.html", "grid", view=view, bounds=bounds)


@router.get("/api/grid")
def grid_api():
    conn = store.session()
    try:
        run = history.latest(conn)
        if run is None:
            raise errors.NotFoundError("还没有批次", code="NO_RUN")
        return {
            "run_id": run["run_id"],
            "summary": service.grid_view(conn, run["run_id"])["states"],
            "points": service.grid_view(conn, run["run_id"])["points"],
        }
    finally:
        conn.close()


@router.post("/api/grid")
def grid_rebuild():
    """从已采纳样本重新推导网格，并与落库结果逐点比对。"""
    conn = store.session()
    try:
        run = history.latest(conn)
        if run is None:
            raise errors.NotFoundError("还没有批次", code="NO_RUN")
        return batch_service.verify_grid(conn, run["run_id"])
    finally:
        conn.close()
