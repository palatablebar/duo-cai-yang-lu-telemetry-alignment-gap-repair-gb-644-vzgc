"""端到端：脏样例 → 采信 → 隔离 → 网格 → 缺口 → 四账 → 导出。"""

from __future__ import annotations

import json

from expected import MAIN

PAGES = ("/", "/samples", "/quality", "/grid", "/gaps", "/batches")


def test_full_pipeline_to_export(api):
    """一次导入跑通全链路，四账相等且导出有数据。"""
    health = api.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["max_fill_buckets"] == 3

    response = api.post(
        "/api/samples/import", json={"sample": "telemetry_raw", "offsets": "device_offsets"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["reused"] is False
    assert payload["counts"]["accepted"] == MAIN["accepted"]
    assert payload["counts"]["quarantined"] == MAIN["quarantined"]
    assert payload["balanced"] is True
    assert payload["conclusion"] == "四账相等"
    assert payload["inputs"][0]["sha256"]

    reconcile = api.get("/api/reconcile").json()
    assert reconcile["balanced"] is True
    assert len(reconcile["lines"]) == 4

    grid_csv = api.get("/api/export/grid.csv")
    assert grid_csv.status_code == 200
    assert grid_csv.headers["content-type"].startswith("text/csv")
    body = grid_csv.content.decode("utf-8-sig")
    assert len(body.strip().splitlines()) == MAIN["grid_points"] + 1

    manifest = json.loads(api.get("/api/export/manifest.json").content.decode("utf-8"))
    assert manifest["run_id"] == payload["run_id"]
    assert manifest["counts"]["filled"] == MAIN["filled"]


def test_all_pages_render(api):
    """6 个页面全部 200，且关键数字出现在页面上。"""
    api.post("/api/samples/import", json={"sample": "telemetry_raw", "offsets": "device_offsets"})
    for page in PAGES:
        response = api.get(page)
        assert response.status_code == 200, page
        body = response.text
        assert "<html" in body
        assert "遥测网格" in body
    home = api.get("/").text
    assert str(MAIN["accepted"]) in home
    grid_page = api.get("/grid").text
    assert "OBSERVED" in grid_page
    quality_page = api.get("/quality").text
    assert "SENTINEL_VALUE" in quality_page


def test_import_rejects_unknown_sample(api):
    """未知样例给 400，返回可读错误而不是 500。"""
    response = api.post("/api/samples/import", json={"sample": "nope", "offsets": "device_offsets"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "SAMPLE_UNKNOWN"
    assert "nope" in body["detail"]["sample"]


def test_no_run_endpoints_return_404(api):
    """还没有批次时，依赖批次的接口给 404 而不是空表。"""
    for path in ("/api/reconcile", "/api/quarantine", "/api/gaps", "/api/export/grid.csv"):
        response = api.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"] == "NO_RUN"


def test_second_sample_creates_new_run(api):
    """换样例得到新批次，旧批次仍在清单里。"""
    first = api.post("/api/samples/import", json={"sample": "gap_series"}).json()
    second = api.post("/api/samples/import", json={"sample": "midnight_edge"}).json()
    assert first["run_id"] != second["run_id"]
    runs = api.get("/api/batches").json()
    assert runs["count"] == 2
    reconcile = api.get(f"/api/reconcile?run_id={first['run_id']}").json()
    assert reconcile["run"]["run_id"] == first["run_id"]
