"""M6 批次与对账的入口：批次页、批次清单、四账核对。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app import store, web
from app.modules.m7_export import service as export_service

from . import service

router = APIRouter(tags=["m6 批次对账"])


@router.get("/batches", response_class=HTMLResponse)
def batches_page(request: Request):
    conn = store.session()
    try:
        view = service.runs_view(conn)
        reconcile = None
        exports = None
        if view["runs"]:
            run_id = view["latest"]["run_id"]
            reconcile = service.reconcile_view(conn, run_id)
            exports = export_service.summary(conn, run_id)
    finally:
        conn.close()
    return web.render(
        request, "batches.html", "batches", view=view, rec=reconcile, exports=exports
    )


@router.get("/api/batches")
def batches_api():
    conn = store.session()
    try:
        view = service.runs_view(conn)
        return {
            "runs": view["runs"],
            "latest": view["latest"],
            "count": len(view["runs"]),
        }
    finally:
        conn.close()


@router.get("/api/batches/{run_id}")
def batch_api(run_id: str):
    conn = store.session()
    try:
        return service.run_detail(conn, run_id)
    finally:
        conn.close()


@router.get("/api/reconcile")
def reconcile_api(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        return service.reconcile_view(conn, run_id)
    finally:
        conn.close()
