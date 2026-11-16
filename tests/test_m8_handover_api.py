"""M8 班次交接的 HTTP 入口与页面渲染。"""

from __future__ import annotations

PAYLOAD = {
    "shift_date": "2026-03-01T00:00:00Z",
    "shift_end": "2026-03-01T00:15:00Z",
}


def _import(api):
    return api.post(
        "/api/samples/import",
        json={"sample": "telemetry_raw", "offsets": "device_offsets"},
    ).json()


def test_prepare_handover_api_creates_package(api):
    """起草交接包返回 200，含范围、跨班窗口与证据。"""
    _import(api)
    response = api.post("/api/handovers", json=PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["handover_id"].startswith("HO-")
    assert body["state"] == "DRAFT"
    assert body["scope"]["cross_windows"] == 7
    assert body["scope"]["retained_samples"] == 36
    assert body["checks"]["passed"] is True


def test_repeat_prepare_is_idempotent_over_http(api):
    """同班次重复 POST 命中同一交接包，reused=True 且库内只有一行。"""
    _import(api)
    first = api.post("/api/handovers", json=PAYLOAD).json()
    second = api.post("/api/handovers", json=PAYLOAD).json()
    assert second["reused"] is True
    assert second["handover_id"] == first["handover_id"]
    listing = api.get("/api/handovers").json()
    assert listing["count"] == 1


def test_confirm_reclaim_rollback_flow_over_http(api):
    """确认 → 腾空间判定放行 → 回滚 的完整 HTTP 流程。"""
    _import(api)
    hid = api.post("/api/handovers", json=PAYLOAD).json()["handover_id"]

    # DRAFT 腾空间被拒
    blocked = api.post(f"/api/handovers/{hid}/reclaim", json={})
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "RECLAIM_BLOCKED"

    assert api.post(f"/api/handovers/{hid}/confirm", json={}).status_code == 200
    decision = api.get(f"/api/handovers/{hid}/reclaim").json()
    assert decision["decision"] == "RECLAIM_NOW"

    reclaimed = api.post(f"/api/handovers/{hid}/reclaim", json={}).json()
    assert reclaimed["removed_grid"] > 0
    assert reclaimed["removed_samples"] == 36
    assert reclaimed["kept_evidence"] == 36

    rolled = api.post(f"/api/handovers/{hid}/rollback", json={}).json()
    assert rolled["state"] == "ROLLED_BACK"
    assert rolled["restored_samples"] == 36


def test_windows_and_evidence_endpoints(api):
    """窗口与证据可单独查询，证据带输入 sha256。"""
    _import(api)
    hid = api.post("/api/handovers", json=PAYLOAD).json()["handover_id"]
    windows = api.get(f"/api/handovers/{hid}/windows").json()["windows"]
    assert len(windows) == 14
    evidence = api.get(f"/api/handovers/{hid}/evidence").json()["evidence"]
    assert len(evidence) == 36
    assert all(len(row["sample_sha256"]) == 64 for row in evidence)


def test_unknown_handover_returns_404(api):
    """不存在的交接号统一 404。"""
    _import(api)
    response = api.get("/api/handovers/HO-MISSING")
    assert response.status_code == 404
    assert response.json()["error"] == "HANDOVER_NOT_FOUND"


def test_prepare_without_run_returns_404(api):
    """没有批次时起草交接给 NO_RUN。"""
    response = api.post("/api/handovers", json=PAYLOAD)
    assert response.status_code == 404
    assert response.json()["error"] == "NO_RUN"


def test_invalid_boundary_returns_400(api):
    """非法班次日界给 400，不产生 500。"""
    _import(api)
    response = api.post("/api/handovers", json={"shift_date": "not-a-time"})
    assert response.status_code == 400
    assert response.json()["error"] == "SHIFT_BOUND_INVALID"


def test_handovers_page_renders(api):
    """交接页 200，空态与有数据态都能渲染关键字段。"""
    empty = api.get("/handovers")
    assert empty.status_code == 200
    assert "班次交接包" in empty.text

    _import(api)
    api.post("/api/handovers", json=PAYLOAD)
    page = api.get("/handovers").text
    assert "HO-" in page
    assert "跨班" in page
    assert "腾空间判定" in page
    assert "保留证据" in page
