"""M2 时基契约的入口：契约、偏移表与当下批次的时间基线。"""

from __future__ import annotations

from fastapi import APIRouter

from app import errors, store
from app.modules.m6_batches import history

from . import service

router = APIRouter(tags=["m2 时基契约"])


@router.get("/api/timebase")
def timebase():
    conn = store.session()
    try:
        run = history.latest(conn)
        run_id = run["run_id"] if run else None
        return {
            "sensors": service.contract_view(),
            "offsets": service.offset_view(conn, run_id) if run_id else [],
            "summary": service.summary(conn, run_id) if run_id else None,
            "params": service.params_view(),
            "window_rule": "[start, end)",
        }
    finally:
        conn.close()


@router.get("/api/timebase/{run_id}")
def timebase_of_run(run_id: str):
    conn = store.session()
    try:
        run = history.get(conn, run_id)
        if run is None:
            raise errors.NotFoundError("批次不存在", code="RUN_NOT_FOUND", detail={"run_id": run_id})
        return {
            "run_id": run_id,
            "offsets": service.offset_view(conn, run_id),
            "summary": service.summary(conn, run_id),
        }
    finally:
        conn.close()
