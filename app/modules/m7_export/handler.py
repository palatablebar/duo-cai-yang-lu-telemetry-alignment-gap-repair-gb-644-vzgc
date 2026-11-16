"""M7 导出的入口：网格 CSV、采纳 CSV、隔离 CSV、运行清单 JSON、单元格证据。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from app import store

from . import evidence, service

router = APIRouter(tags=["m7 导出"])

CSV_MEDIA = "text/csv; charset=utf-8"


def _download(body: str, filename: str) -> Response:
    return Response(
        content=body.encode("utf-8"),
        media_type=CSV_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/export/grid.csv")
def export_grid(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        target = service.resolve(conn, run_id)
        body = service.grid_csv(conn, target)
    finally:
        conn.close()
    return _download(body, f"grid-{target}.csv")


@router.get("/api/export/accepted.csv")
def export_accepted(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        target = service.resolve(conn, run_id)
        body = service.accepted_csv(conn, target)
    finally:
        conn.close()
    return _download(body, f"accepted-{target}.csv")


@router.get("/api/export/quarantine.csv")
def export_quarantine(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        target = service.resolve(conn, run_id)
        body = service.quarantine_csv(conn, target)
    finally:
        conn.close()
    return _download(body, f"quarantine-{target}.csv")


@router.get("/api/export/manifest.json")
def export_manifest(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        target = service.resolve(conn, run_id)
        body = service.manifest_text(conn, target)
    finally:
        conn.close()
    return Response(
        content=body.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="manifest-{target}.json"'},
    )


@router.get("/api/export/summary")
def export_summary(run_id: str | None = Query(default=None, max_length=64)):
    conn = store.session()
    try:
        target = service.resolve(conn, run_id)
        return service.summary(conn, target)
    finally:
        conn.close()


@router.get("/api/export/evidence")
def export_evidence(
    sensor_id: str = Query(min_length=1, max_length=32),
    bucket: str = Query(min_length=10, max_length=32),
    run_id: str | None = Query(default=None, max_length=64),
):
    conn = store.session()
    try:
        target = service.resolve(conn, run_id)
        payload = evidence.cell(conn, target, sensor_id, bucket)
    finally:
        conn.close()
    if payload is None:
        return JSONResponse(
            status_code=404,
            content={"error": "CELL_NOT_FOUND", "message": "该网格点不存在", "detail": {"sensor_id": sensor_id, "bucket": bucket}},
        )
    return payload
