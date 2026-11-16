"""M8 班次交接的入口：交接页、起草/确认/腾空间/回滚、窗口与证据查询。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app import store, web

from . import service

router = APIRouter(tags=["m8 班次交接"])


class PrepareBody(BaseModel):
    shift_date: str = Field(min_length=8, max_length=32)
    shift_end: str | None = Field(default=None, max_length=32)
    run_id: str | None = Field(default=None, max_length=64)
    actor: str = Field(default="值班员", max_length=32)


class ActorBody(BaseModel):
    actor: str = Field(default="值班员", max_length=32)


@router.get("/handovers", response_class=HTMLResponse)
def handovers_page(request: Request):
    conn = store.session()
    try:
        view = service.list_handovers(conn)
        detail = None
        decision = None
        if view["handovers"]:
            hid = view["latest"]["handover_id"]
            detail = service.get_handover(conn, hid)
            decision = service.reclaim_decision(conn, hid)
    finally:
        conn.close()
    return web.render(
        request, "handovers.html", "handovers", view=view, detail=detail, decision=decision
    )


@router.get("/api/handovers")
def handovers_api():
    conn = store.session()
    try:
        return service.list_handovers(conn)
    finally:
        conn.close()


@router.post("/api/handovers")
def prepare_api(body: PrepareBody):
    conn = store.session()
    try:
        return service.prepare_handover(
            conn,
            run_id=body.run_id,
            shift_date=body.shift_date,
            shift_end=body.shift_end,
            actor=body.actor,
        )
    finally:
        conn.close()


@router.get("/api/handovers/{handover_id}")
def handover_api(handover_id: str):
    conn = store.session()
    try:
        return service.get_handover(conn, handover_id)
    finally:
        conn.close()


@router.post("/api/handovers/{handover_id}/confirm")
def confirm_api(handover_id: str, body: ActorBody):
    conn = store.session()
    try:
        return service.confirm_handover(conn, handover_id, actor=body.actor)
    finally:
        conn.close()


@router.get("/api/handovers/{handover_id}/reclaim")
def reclaim_decision_api(handover_id: str):
    conn = store.session()
    try:
        return service.reclaim_decision(conn, handover_id)
    finally:
        conn.close()


@router.post("/api/handovers/{handover_id}/reclaim")
def reclaim_api(handover_id: str, body: ActorBody):
    conn = store.session()
    try:
        return service.reclaim_space(conn, handover_id, actor=body.actor)
    finally:
        conn.close()


@router.post("/api/handovers/{handover_id}/rollback")
def rollback_api(handover_id: str, body: ActorBody):
    conn = store.session()
    try:
        return service.rollback_handover(conn, handover_id, actor=body.actor)
    finally:
        conn.close()


@router.get("/api/handovers/{handover_id}/windows")
def windows_api(handover_id: str):
    conn = store.session()
    try:
        service._require(conn, handover_id)
        return {"handover_id": handover_id, "windows": service.windows_of(conn, handover_id)}
    finally:
        conn.close()


@router.get("/api/handovers/{handover_id}/evidence")
def evidence_api(handover_id: str, limit: int | None = Query(default=None, ge=1, le=2000)):
    conn = store.session()
    try:
        service._require(conn, handover_id)
        return {
            "handover_id": handover_id,
            "evidence": service.evidence_of(conn, handover_id, limit=limit),
        }
    finally:
        conn.close()
