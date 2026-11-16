"""运行清单：输入摘要、批次键、清单结构。

批次键由「输入文件 sha256 + 规则版本 + 参数」确定性派生，同输入同参数必然同键，
因此重复导入只会复用已有批次，不新增行。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def input_digest(inputs: list[dict]) -> list[dict]:
    """按名称排序，保证同一批输入无论传参顺序如何都得到同一摘要。"""
    ordered = sorted(inputs, key=lambda item: item["name"])
    return [{"name": item["name"], "sha256": item["sha256"], "bytes": item["bytes"]} for item in ordered]


def run_key(inputs: list[dict], rule_version: str, params: dict) -> str:
    material = canonical_json(
        {
            "inputs": input_digest(inputs),
            "rule_version": rule_version,
            "params": params,
        }
    )
    return sha256_bytes(material.encode("utf-8"))


def run_id_for(key: str) -> str:
    return "GL-" + key[:10].upper()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def build_manifest(
    *,
    run_id: str,
    key: str,
    created_at: str,
    rule_version: str,
    sample_name: str,
    offset_name: str,
    inputs: list[dict],
    params: dict,
    counts: dict,
    totals: dict,
    elapsed_ms: int,
) -> dict:
    return {
        "run_id": run_id,
        "run_key": key,
        "created_at": created_at,
        "rule_version": rule_version,
        "grid_resolution": "PT1M",
        "window_minutes": params.get("window_minutes"),
        "sample": sample_name,
        "offsets": offset_name,
        "inputs": input_digest(inputs),
        "params": params,
        "counts": counts,
        "totals": totals,
        "elapsed_ms": elapsed_ms,
        "window_rule": "[start, end)",
    }
