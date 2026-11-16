"""M1 采样采信的入口：总览页、采信诊断页、导入接口。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app import config, errors, store, web
from app.modules.m2_timebase import service as timebase_service
from app.modules.m6_batches import history
from app.modules.m6_batches import service as batch_service

from . import service

router = APIRouter(tags=["m1 采样采信"])


class ImportBody(BaseModel):
    sample: str = Field(default="telemetry_raw", max_length=64)
    offsets: str = Field(default="device_offsets", max_length=64)


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    conn = store.session()
    try:
        data = batch_service.overview(conn)
    finally:
        conn.close()
    return web.render(
        request,
        "index.html",
        "index",
        samples=service.sample_choices(),
        offsets=service.offset_choices(),
        **data,
    )


@router.get("/samples", response_class=HTMLResponse)
def samples_page(request: Request):
    conn = store.session()
    try:
        run = history.latest(conn)
        run_id = run["run_id"] if run else None
        intake = service.intake_view(conn, run_id) if run_id else None
        columns = service.intake_columns(intake["header"]) if intake else []
        offsets = timebase_service.offset_view(conn, run_id) if run_id else []
        summary = timebase_service.summary(conn, run_id) if run_id else None
        flags = timebase_service.flag_counts(conn, run_id) if run_id else []
    finally:
        conn.close()
    return web.render(
        request,
        "samples.html",
        "samples",
        intake=intake,
        columns=columns,
        sensors=timebase_service.contract_view(),
        offsets=offsets,
        tb_summary=summary,
        flags=flags,
    )


@router.post("/api/samples/import")
def import_samples(body: ImportBody):
    if body.sample not in config.SAMPLES:
        raise errors.InputError(
            "未知样例",
            code="SAMPLE_UNKNOWN",
            detail={"sample": body.sample, "choices": sorted(config.SAMPLES)},
        )
    if body.offsets not in config.OFFSET_SAMPLES:
        raise errors.InputError(
            "未知偏移表",
            code="OFFSET_TABLE_UNKNOWN",
            detail={"offsets": body.offsets, "choices": sorted(config.OFFSET_SAMPLES)},
        )
    conn = store.session()
    try:
        result = batch_service.execute_run(conn, sample=body.sample, offsets=body.offsets)
    finally:
        conn.close()
    return JSONResponse(result)


@router.get("/api/samples")
def samples_api():
    conn = store.session()
    try:
        run = history.latest(conn)
        if run is None:
            raise errors.NotFoundError("还没有批次", code="NO_RUN")
        intake = service.intake_view(conn, run["run_id"])
    finally:
        conn.close()
    return {"run_id": run["run_id"], "intake": intake}
