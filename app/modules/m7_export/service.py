"""导出编排：把落库结果拼成 CSV / JSON，并给出导出摘要。"""

from __future__ import annotations

from app import config, store
from app.errors import NotFoundError
from app.modules.m3_quality import quarantine as quarantine_store
from app.modules.m6_batches import history

from . import csv_out, evidence, manifest_out


def resolve(conn, run_id: str | None) -> str:
    if run_id:
        if history.get(conn, run_id) is None:
            raise NotFoundError("批次不存在", code="RUN_NOT_FOUND", detail={"run_id": run_id})
        return run_id
    latest = history.latest(conn)
    if latest is None:
        raise NotFoundError("还没有批次", code="NO_RUN")
    return latest["run_id"]


def grid_csv(conn, run_id: str) -> str:
    columns, rows = csv_out.grid_export(conn, run_id)
    return "\ufeff" + csv_out.write_csv(columns, rows)


def accepted_csv(conn, run_id: str) -> str:
    columns, rows = csv_out.accepted_export(conn, run_id)
    return "\ufeff" + csv_out.write_csv(columns, rows)


def quarantine_csv(conn, run_id: str) -> str:
    return "\ufeff" + quarantine_store.to_csv(quarantine_store.rows_of(conn, run_id))


def manifest_text(conn, run_id: str) -> str:
    return manifest_out.to_text(manifest_out.build(conn, run_id))


def summary(conn, run_id: str) -> dict:
    run = history.get(conn, run_id)
    if run is None:
        raise NotFoundError("批次不存在", code="RUN_NOT_FOUND", detail={"run_id": run_id})
    manifest = manifest_out.build(conn, run_id)
    return {
        "run_id": run_id,
        "run_key": run["run_key"],
        "rule_version": run["rule_version"],
        "created_at": run["created_at"],
        "inputs": manifest.get("inputs", []),
        "counts": run["counts"],
        "totals": run["totals"],
        "files": [
            {"name": "网格 CSV", "path": "/api/export/grid.csv", "rows": run["counts"].get("grid_points", 0)},
            {"name": "采纳 CSV", "path": "/api/export/accepted.csv", "rows": run["counts"].get("accepted", 0)},
            {
                "name": "隔离 CSV",
                "path": "/api/export/quarantine.csv",
                "rows": run["counts"].get("quarantined", 0),
            },
            {"name": "运行清单", "path": "/api/export/manifest.json", "rows": len(manifest.get("inputs", []))},
        ],
        "evidence": evidence.trailing(conn, run_id, limit=12),
        "stamp": store.value(
            conn, "SELECT COUNT(*) FROM grid WHERE run_id = ?", (run_id,), 0
        ),
        "tz": "+08:00",
        "grid_minutes": config.GRID_MINUTES,
    }
