"""M8 班次交接：交接包范围、跨班窗口、保留证据、腾空间判定、幂等与回滚。"""

from __future__ import annotations

import pytest

from app import errors, store
from app.modules.m8_handover import crosscheck, evidence as evidence_mod, service, shift_windows

SHIFT_START = "2026-03-01T00:00:00Z"
SHIFT_END = "2026-03-01T00:15:00Z"


def _prepare(conn, **over):
    params = {"shift_date": SHIFT_START, "shift_end": SHIFT_END}
    params.update(over)
    return service.prepare_handover(conn, run_id=None, **params)


# ---------------------------------------------------------------- 范围与跨班窗口

def test_handover_scope_counts_windows_and_sensors(conn, run_main):
    """交接包清点窗口总数、跨班窗口与班内采样，范围数字来自落库而非另算。"""
    pkg = _prepare(conn)
    assert pkg["state"] == service.STATE_DRAFT
    assert pkg["scope"]["windows_total"] == run_main["counts"]["windows"]
    # 起点恰在班末 00:15、末端 00:30 越过班末的 7 个窗口判跨班
    assert pkg["scope"]["cross_windows"] == 7
    assert pkg["scope"]["samples_in_shift"] == 47
    starts = {w["window_start"] for w in pkg["windows"] if w["cross_shift"]}
    assert starts == {"2026-03-01T00:15:00Z"}


def test_window_half_open_boundary_is_not_double_counted(conn, run_main):
    """窗口右端开：末端恰等班末的 00:00 窗口不判跨班，00:15 起的窗口才跨班。"""
    pkg = _prepare(conn)
    in_shift = [w for w in pkg["windows"] if w["window_start"] == "2026-03-01T00:00:00Z"]
    cross = [w for w in pkg["windows"] if w["cross_shift"]]
    assert all(not w["cross_shift"] for w in in_shift)
    assert all(w["window_start"] == "2026-03-01T00:15:00Z" for w in cross)


def test_shift_bounds_default_is_one_natural_day(conn):
    """只给日期时班次为自然日 [00:00, 次日 00:00)。"""
    start, end = shift_windows.shift_bounds("2026-03-01")
    assert start.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-03-01T00:00:00Z"
    assert end.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-03-02T00:00:00Z"


def test_invalid_boundary_raises_input_error(conn, run_main):
    """班次日界无法解析给 400 类错误，而不是 500。"""
    with pytest.raises(errors.InputError) as exc:
        service.prepare_handover(conn, run_id=None, shift_date="not-a-time")
    assert exc.value.code == "SHIFT_BOUND_INVALID"


def test_empty_shift_window_rejected(conn, run_main):
    """范围内没有任何 15 分钟窗口时拒绝起草，不生成空交接包。"""
    with pytest.raises(errors.InputError) as exc:
        service.prepare_handover(
            conn, run_id=None,
            shift_date="2026-03-02T00:00:00Z", shift_end="2026-03-02T00:15:00Z",
        )
    assert exc.value.code == "SHIFT_WINDOW_EMPTY"


# ---------------------------------------------------------------- 保留证据与交叉复核

def test_evidence_snapshots_cross_shift_raw_samples(conn, run_main):
    """跨班窗口内每条原始采样独立快照，带输入 sha256、原始行号与所属窗口。"""
    pkg = _prepare(conn)
    assert pkg["scope"]["retained_samples"] == 36
    by_window = {}
    for ev in pkg["evidence"]:
        assert len(ev["sample_sha256"]) == 64
        assert ev["source_row"] > 0
        assert ev["cross_shift"] == 1
        by_window.setdefault((ev["sensor_id"], ev["window_start"]), 0)
        by_window[(ev["sensor_id"], ev["window_start"])] += 1
    # TH-01 跨班窗口 observed=13，证据也应是 13 条
    assert by_window[("TH-01", "2026-03-01T00:15:00Z")] == 13


def test_cross_check_matches_window_observed_to_retained(conn, run_main):
    """窗口登记的实有桶数与保留证据数逐窗相等，复核通过。"""
    pkg = _prepare(conn)
    assert pkg["checks"]["passed"] == True
    names = {line["name"]: line for line in pkg["checks"]["lines"]}
    assert names["窗口-采样对账"]["state"] == "OK"
    for w in pkg["windows"]:
        if w["cross_shift"] and w["observed"] > 0:
            assert w["retained"] == w["observed"]


def test_empty_cross_window_allows_zero_evidence(conn, run_main):
    """observed=0 的跨班窗口本就无采样，允许零证据，不阻塞复核。"""
    pkg = _prepare(conn)
    empty_cross = [w for w in pkg["windows"] if w["cross_shift"] and w["observed"] == 0]
    assert {w["sensor_id"] for w in empty_cross} >= {"GH-07", "NO-04"}
    assert pkg["checks"]["passed"] == True


def test_evidence_digest_changes_when_snapshot_tampered(conn, run_main):
    """证据快照摘要对内容敏感：改一条值，sha256 即变。"""
    pkg = _prepare(conn)
    original = pkg["scope"]["evidence_digest"]
    rows = evidence_mod.build(
        conn, run_main["run_id"],
        [shift_windows.ShiftWindow(
            sensor_id=w["sensor_id"],
            start=shift_windows.parse_bound(w["window_start"]),
            end=shift_windows.parse_bound(w["window_end"]),
            observed=w["observed"], expected=w["expected"], coverage=w["coverage"],
            state=w["state"], cross_shift=bool(w["cross_shift"]),
        ) for w in pkg["windows"]],
    )
    tampered = [evidence_mod.EvidenceRow(**{**r.__dict__, "value": "999.000"}) for r in rows]
    assert evidence_mod.snapshot_digest(tampered) != original


def test_cross_check_detects_mismatch():
    """登记 observed 与保留数对不上时，复核判 BAD。"""
    windows = [
        shift_windows.ShiftWindow(
            sensor_id="TH-01",
            start=shift_windows.parse_bound("2026-03-01T00:15:00Z"),
            end=shift_windows.parse_bound("2026-03-01T00:30:00Z"),
            observed=13, expected=15, coverage="0.867", state="OK", cross_shift=True,
        )
    ]
    rows = [
        evidence_mod.EvidenceRow(
            sensor_id="TH-01", bucket_utc="2026-03-01T00:15:00Z", source_row=i + 1,
            value="1.0", unit="%RH", quality="good", raw_value="1.0", sample_sha256="x" * 64,
            window_start="2026-03-01T00:15:00Z", cross_shift=1,
        )
        for i in range(12)  # 少一条
    ]
    report = crosscheck.cross_check(windows, rows)
    assert report.passed == False
    assert report.window_mismatches and report.window_mismatches[0]["observed"] == 13


# ---------------------------------------------------------------- 幂等

def test_repeat_handover_is_idempotent(conn, run_main):
    """同班次同窗口重复交接撞 shift_key，复用既有包，不重复生成窗口与证据。"""
    first = _prepare(conn)
    second = _prepare(conn)
    assert second["reused"] == True
    assert second["handover_id"] == first["handover_id"]
    assert store.value(conn, "SELECT COUNT(*) FROM handovers", (), 0) == 1
    assert store.value(conn, "SELECT COUNT(*) FROM handover_windows", (), 0) == len(first["windows"])
    assert store.value(conn, "SELECT COUNT(*) FROM handover_evidence", (), 0) == 36


def test_different_shift_boundary_creates_new_package(conn, run_main):
    """不同班次日界得到不同交接包，旧包仍在清单里。"""
    one = _prepare(conn)
    two = service.prepare_handover(
        conn, run_id=None, shift_date=SHIFT_START, shift_end="2026-03-01T00:30:00Z"
    )
    assert one["handover_id"] != two["handover_id"]
    assert service.list_handovers(conn)["count"] == 2


# ---------------------------------------------------------------- 腾空间判定

def test_draft_blocks_reclaim_until_confirmed(conn, run_main):
    """DRAFT 阶段证据未确认，判定 WAIT_EVIDENCE 并给阻塞原因，禁止腾空间。"""
    pkg = _prepare(conn)
    decision = service.reclaim_decision(conn, pkg["handover_id"])
    assert decision["reclaimable"] == False
    assert decision["decision"] == "WAIT_EVIDENCE"
    assert any("尚未确认" in b for b in decision["blockers"])
    with pytest.raises(errors.StateError) as exc:
        service.reclaim_space(conn, pkg["handover_id"])
    assert exc.value.code == "RECLAIM_BLOCKED"


def test_confirmed_handover_allows_reclaim_and_keeps_evidence(conn, run_main):
    """确认且复核通过后允许腾空间；只清范围外在线数据，证据与交接包原样保留。"""
    pkg = _prepare(conn)
    service.confirm_handover(conn, pkg["handover_id"])
    decision = service.reclaim_decision(conn, pkg["handover_id"])
    assert decision["reclaimable"] == True
    assert decision["decision"] == "RECLAIM_NOW"

    grid_before = store.value(conn, "SELECT COUNT(*) FROM grid", (), 0)
    result = service.reclaim_space(conn, pkg["handover_id"])
    assert result["removed_grid"] > 0
    assert result["removed_samples"] == 36
    assert store.value(conn, "SELECT COUNT(*) FROM grid", (), 0) < grid_before
    # 被腾掉的在线采样恰为被证据覆盖的那些，在线表已无班末之外采样
    assert store.value(
        conn, "SELECT COUNT(*) FROM samples WHERE run_id=? AND bucket_utc >= ?",
        (run_main["run_id"], SHIFT_END), 0,
    ) == 0
    # 证据、窗口快照、交接包都还在
    assert store.value(
        conn, "SELECT COUNT(*) FROM handover_evidence WHERE handover_id=?",
        (pkg["handover_id"],), 0,
    ) == 36
    assert store.value(
        conn, "SELECT COUNT(*) FROM handover_windows WHERE handover_id=?",
        (pkg["handover_id"],), 0,
    ) == len(pkg["windows"])


def test_confirm_is_idempotent_and_blocks_rolled_back(conn, run_main):
    """重复确认不报错不重复；已回滚的包不能再确认。"""
    pkg = _prepare(conn)
    service.confirm_handover(conn, pkg["handover_id"])
    again = service.confirm_handover(conn, pkg["handover_id"])
    assert again["state"] == service.STATE_CONFIRMED
    service.rollback_handover(conn, pkg["handover_id"])
    with pytest.raises(errors.StateError) as exc:
        service.confirm_handover(conn, pkg["handover_id"])
    assert exc.value.code == "HANDOVER_ROLLED_BACK"


# ---------------------------------------------------------------- 回滚恢复

def test_rollback_restores_purged_samples_from_snapshot(conn, run_main):
    """在线采样被腾出后，回滚能从证据快照把原始记录逐条追回。"""
    pkg = _prepare(conn)
    hid = pkg["handover_id"]
    rid = run_main["run_id"]
    service.confirm_handover(conn, hid)
    conn.execute(
        "DELETE FROM samples WHERE run_id=? AND bucket_utc >= ?",
        (rid, SHIFT_END),
    )
    assert store.value(
        conn, "SELECT COUNT(*) FROM samples WHERE run_id=? AND bucket_utc >= ?",
        (rid, SHIFT_END), 0,
    ) == 0

    result = service.rollback_handover(conn, hid)
    assert result["state"] == service.STATE_ROLLED_BACK
    assert result["restored_samples"] == 36
    restored = store.rows(
        conn,
        "SELECT * FROM samples WHERE run_id=? AND flags='RESTORED_FROM_HANDOVER'",
        (rid,),
    )
    assert len(restored) == 36
    # 恢复行带单位与正确质量位序，不是空壳
    assert all(row["unit"] for row in restored)
    good = [row for row in restored if row["quality"] == "good"]
    assert all(row["quality_rank"] == 2 for row in good)
    # 恢复值与证据快照一致
    evidence = { (e["sensor_id"], e["bucket_utc"]): e["value"] for e in service.evidence_of(conn, hid) }
    for row in restored:
        assert row["value"] == evidence[(row["sensor_id"], row["bucket_utc"])]


def test_rollback_restores_previous_confirmed_package(conn, run_main):
    """回滚新版交接包后，上一版已确认结果恢复为 CONFIRMED。"""
    p1 = _prepare(conn)
    service.confirm_handover(conn, p1["handover_id"])
    p2 = service.prepare_handover(
        conn, run_id=None, shift_date=SHIFT_START, shift_end="2026-03-01T00:30:00Z"
    )
    service.confirm_handover(conn, p2["handover_id"])
    assert service.get_handover(conn, p2["handover_id"])["previous_id"] == p1["handover_id"]

    service.rollback_handover(conn, p2["handover_id"])
    assert service.get_handover(conn, p2["handover_id"])["state"] == service.STATE_ROLLED_BACK
    assert service.get_handover(conn, p1["handover_id"])["state"] == service.STATE_CONFIRMED


def test_rollback_is_idempotent(conn, run_main):
    """重复回滚不重复恢复、不报错。"""
    pkg = _prepare(conn)
    service.confirm_handover(conn, pkg["handover_id"])
    first = service.rollback_handover(conn, pkg["handover_id"])
    second = service.rollback_handover(conn, pkg["handover_id"])
    assert first["state"] == second["state"] == service.STATE_ROLLED_BACK


def test_handover_events_audit_trail(conn, run_main):
    """起草、确认、回滚都留事件，按 seq 排序可追溯。"""
    pkg = _prepare(conn, actor="张三")
    service.confirm_handover(conn, pkg["handover_id"], actor="张三")
    service.rollback_handover(conn, pkg["handover_id"], actor="张三")
    events = service.events_of(conn, pkg["handover_id"])
    names = [e["event"] for e in events]
    assert names == ["PREPARED", "CONFIRMED", "ROLLED_BACK"]
    assert all(e["actor"] == "张三" for e in events)
    assert [e["seq"] for e in events] == [1, 2, 3]


def test_handover_requires_existing_run(conn):
    """没有批次时起草交接给 404 NO_RUN。"""
    with pytest.raises(errors.NotFoundError) as exc:
        service.prepare_handover(conn, run_id=None, shift_date=SHIFT_START, shift_end=SHIFT_END)
    assert exc.value.code == "NO_RUN"


def test_get_unknown_handover_raises_404(conn, run_main):
    """不存在的交接号给 404，不返回空对象。"""
    with pytest.raises(errors.NotFoundError) as exc:
        service.get_handover(conn, "HO-NOPE")
    assert exc.value.code == "HANDOVER_NOT_FOUND"
