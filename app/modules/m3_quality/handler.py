"""M3 质量隔离的入口：隔离页、原因分布、隔离 CSV。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from app import errors, store, web
from app.modules.m6_batches import history

from . import quarantine, service

router = APIRouter(tags=["m3 质量隔离"])


def _run_id(conn, run_id: str | None) -> str:
    if run_id:
        if history.get(conn, run_id) is None:
            raise errors.NotFoundError("批次不存在", code="RUN_NOT_FOUND", detail={"run_id": run_id})
        return run_id
    latest = history.latest(conn)
    if latest is None:
        raise errors.NotFoundError("还没有批次", code="NO_RUN")
    return latest["run_id"]


@router.get("/quality", response_class=HTMLResponse)
def quality_page(request: Request):
    conn = store.session()
    try:
        run = history.latest(conn)
        view = service.quality_view(conn, run["run_id"]) if run else None
    finally:
        conn.close()
    return web.render(request, "quality.html", "quality", view=view)


@router.get("/api/quarantine")
def quarantine_api(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        target = _run_id(conn, run_id)
        return {
            "run_id": target,
            "rows": quarantine.rows_of(conn, target, limit=500),
            "distribution": quarantine.distribution(conn, target),
            "by_sensor": quarantine.by_sensor(conn, target),
        }
    finally:
        conn.close()


@router.get("/api/quarantine.csv")
def quarantine_csv(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        target = _run_id(conn, run_id)
        entries = quarantine.rows_of(conn, target)
    finally:
        conn.close()
    body = "\ufeff" + quarantine.to_csv(entries)
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="quarantine-{target}.csv"'},
    )
