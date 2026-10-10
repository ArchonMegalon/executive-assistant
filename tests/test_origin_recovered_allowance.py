"""Real recovery/approval/worker with retained synthetic prose; no live provider."""
import copy
import hashlib
import json

import pytest

from scripts import origin_recovered_allowance as allowance
from tests.test_origin_custody_recovery import fixture, restore
from tests.test_origin_chapter_intake import executor
from tests.test_origin_book_pool import Books, BalanceBrowser

pool, writer = allowance.pool, allowance.writer


def setup(tmp_path):
    hub, history, _ = fixture()
    restore(tmp_path, hub, history)
    hub.pending_books = lambda: []
    root = tmp_path / "recovered"
    custody = root / "firstbook-private-writes"
    target = copy.deepcopy(history["configuration"])
    target.update(approval_id="new-explicit-standing-credit-approval", maximum_new_books=4)
    target["accounts"][0]["maximum_new_books"] = 4
    plan = {"schema": allowance._SCHEMA, "configuration": target,
        "expected_pool_sha256": digest(custody / "book-pool.json"),
        "expected_recovery_sha256": digest(custody / "completed-custody-recovery.json"),
        "observed_at": 1010, "stopped_executor_id": "d" * 64,
        "executor_stopped": True, "browsers_closed": True,
        "accounts": [{"profile_id": "chrome_local_12345", "account_sha256": "a" * 64,
            "remaining_credits": 3, "observed_at": 1009, "capture_sha256": "e" * 64,
            "session": "owned-balance-probe", "closed": True}]}
    return hub, history, plan, root, custody


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approve(hub, history, plan, root, **kwargs):
    return allowance.approve(lambda: history["configuration"], lambda: history,
        lambda: plan, hub, root, now=lambda: 1011, **kwargs)


def snapshot(custody):
    return {p: p.read_bytes() for p in custody.iterdir() if p.is_file() and p.suffix == ".json"}


def test_explicit_allowance_preserves_books_and_every_journal_then_cold_idle(tmp_path, monkeypatch):
    hub, history, plan, root, custody = setup(tmp_path)
    monkeypatch.setattr(writer.capture, "_browser", lambda *a: pytest.fail("Approval must never open a browser"))
    before = snapshot(custody)
    result = approve(hub, history, plan, root)
    assert result["reserved_books"] == 1 and result["remaining_books"] == 3
    assert not result["provider_dispatch"] and not result["historical_ledger_restored"]
    assert all(p.read_bytes() == data for p, data in before.items() if p.name != "book-pool.json")
    state = writer._load(custody / "book-pool.json")
    old = json.loads(before[custody / "book-pool.json"])
    assert state["books"] == old["books"] and state["in_flight"] is None
    assert state["new_book_admission_exhausted"] is False
    assert digest(custody / "book-pool.json") == result["pool_after_sha256"]
    with pytest.raises(RuntimeError, match="mismatch"):
        pool.run_once(lambda: history["configuration"], hub, root, now=lambda: 1012)
    observed = pool.run_once(lambda: plan["configuration"], hub, root, now=lambda: 1012)
    assert observed["book_states"] == ["idle"] and observed["remaining_books"] == 3
    assert all(action in ("", "pending") for action, _ in hub.calls)
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        approve(hub, history, plan, root)  # Cannot refill or replay an applied transition.


@pytest.mark.parametrize("change", ["running", "browser-open", "stale", "future", "unknown-credit",
    "negative-credit", "stale-credit", "credit-mismatch", "account", "profile", "exclusion",
    "chapter-budget", "same-approval", "pool-digest", "recovery-digest", "in-flight", "probe-open",
    "session-open", "session-closed", "intake", "writer", "receipt", "pending", "full-page",
    "pending-successor", "unaccepted"])
def test_invalid_or_uncertain_state_cannot_enable_new_books(tmp_path, change):
    hub, history, plan, root, custody = setup(tmp_path)
    config = plan["configuration"]
    if change == "running": plan["executor_stopped"] = False
    if change == "browser-open": plan["accounts"][0]["closed"] = False
    if change == "stale": plan["observed_at"] = -1000
    if change == "future": plan["observed_at"] = 1012
    if change == "unknown-credit": plan["accounts"][0]["remaining_credits"] = None
    if change == "negative-credit": plan["accounts"][0]["remaining_credits"] = -1
    if change == "stale-credit": plan["accounts"][0]["observed_at"] = -1000
    if change == "credit-mismatch": plan["accounts"][0]["remaining_credits"] = 2
    if change == "account": plan["accounts"][0]["account_sha256"] = "b" * 64
    if change == "profile": config["accounts"][0]["profile_id"] = "chrome_local_67890"
    if change == "exclusion": config["excluded_book_refs"] = []
    if change == "chapter-budget": config["maximum_chapters_per_book"] = 99
    if change == "same-approval": config["approval_id"] = history["configuration"]["approval_id"]
    if change == "pool-digest": plan["expected_pool_sha256"] = "0" * 64
    if change == "recovery-digest": plan["expected_recovery_sha256"] = "0" * 64
    if change == "in-flight":
        state = writer._load(custody / "book-pool.json")
        state["in_flight"] = history["books"][0]["book_ref"]
        pool._save_pool(custody / "book-pool.json", state)
        plan["expected_pool_sha256"] = digest(custody / "book-pool.json")
    if change == "probe-open": writer._save(custody / "account-probe.json", {"state": "opening"})
    if change.startswith("session-"):
        writer._save(custody / ("owned-session-" + history["books"][0]["book_ref"] + ".json"),
            {"state": change.removeprefix("session-")})
    if change == "intake":
        p = custody / ("intake-" + history["books"][0]["book_ref"] + ".json")
        state = writer._load(p)
        state["jobs"][0]["state"] = "working"
        writer._save(p, state)
    if change == "writer":
        intake = writer._load(custody / ("intake-" + history["books"][0]["book_ref"] + ".json"))
        p = writer._record_path(custody, writer._binding(intake["jobs"][0]["prepared"]))
        p.write_text('{}')
    if change == "receipt":
        p = custody / "completed-custody-recovery.json"
        value = writer._load(p)
        value["books"] = []
        writer._save(p, value)
        plan["expected_recovery_sha256"] = digest(p)
    if change == "pending": hub.pending_books = lambda: [{"bookRef": "0" * 64}]
    if change == "full-page": hub.pending_books = lambda: [{"bookRef": "f" * 64}] * 20
    if change == "pending-successor": hub.next(suffix="4")
    if change == "unaccepted": list(hub.jobs.values())[-1]["job"]["readerAcceptedTextDigest"] = None
    before = snapshot(custody)
    with pytest.raises((ValueError, RuntimeError)):
        approve(hub, history, plan, root)
    assert snapshot(custody) == before


def test_all_historical_exclusions_survive_without_replaying_their_pending_work(tmp_path):
    hub, history, plan, root, custody = setup(tmp_path)
    hub.pending_books = lambda: [{"bookRef": "f" * 64, "state": "uncertain"}]
    approve(hub, history, plan, root)
    assert writer._load(custody / "book-pool.json")["configuration"]["excluded_book_refs"] == ["f" * 64]


def test_future_request_is_admitted_once_and_reservation_survives_restart(tmp_path, executor):
    hub, history, plan, root, custody = setup(tmp_path)
    approve(hub, history, plan, root)
    work = Books().add("d")
    hub.jobs[work["workId"]] = work
    hub.pending_books = lambda: copy.deepcopy([
        w for w in hub.jobs.values() if w["job"]["state"] != "review_required"])
    browser = BalanceBrowser({"a" * 64: 3})
    run = lambda: pool.run_once(lambda: copy.deepcopy(plan["configuration"]), hub, root,
        now=lambda: 1012, browser=browser, sleep=lambda _: None)
    first = run()
    assert first["reserved_books"] == 2 and first["remaining_books"] == 2
    assert len(executor) == 1 and browser.probes == ["a" * 64]
    before = (custody / "book-pool.json").read_bytes()
    assert run()["reserved_books"] == 2
    assert len(executor) == 1 and browser.probes == ["a" * 64]
    assert (custody / "book-pool.json").read_bytes() == before


@pytest.mark.parametrize("lease", [pool._lease, pool.runtime.intake.cycle._lease])
def test_cannot_overlap_live_executor(tmp_path, lease):
    hub, history, plan, root, custody = setup(tmp_path)
    before = snapshot(custody)
    with lease(root), pytest.raises(RuntimeError):
        approve(hub, history, plan, root)
    assert snapshot(custody) == before


def test_changed_completed_admission_during_final_read_is_rejected(tmp_path):
    hub, history, plan, root, custody = setup(tmp_path)
    original = hub.call
    count = 0
    def changed(work_id):
        nonlocal count
        count += 1
        if count == 3:
            hub.jobs[work_id]["executionAdmission"] = "changed-admission"
        return original(work_id)
    hub.call = changed
    before = snapshot(custody)
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        approve(hub, history, plan, root)
    assert snapshot(custody) == before


def test_interrupted_atomic_commit_keeps_old_grant_and_resumes_exact_transition(tmp_path, monkeypatch):
    hub, history, plan, root, custody = setup(tmp_path)
    before = (custody / "book-pool.json").read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(pool, "_save_pool", lambda *a: (_ for _ in ()).throw(OSError("write failed")))
        with pytest.raises(OSError): approve(hub, history, plan, root)
    assert (custody / "book-pool.json").read_bytes() == before
    assert approve(hub, history, plan, root)["remaining_books"] == 3
