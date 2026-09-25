import copy
import hashlib

import pytest

from scripts import origin_book_pool as pool
from tests.test_origin_book_pool import Books, start, run, ledger
from tests.test_origin_chapter_intake import executor
from tests.test_origin_chapter_runtime import Browser


def failed_open(tmp_path):
    config, hub, browser = start(tmp_path), Books(), Browser()
    work = hub.add("1")

    def failure(profile, session):
        browser.calls.append(("open", profile, session))
        raise RuntimeError("WebSocket connection closed")

    browser.open = failure
    with pytest.raises(RuntimeError, match="WebSocket"):
        run(config, hub, tmp_path, browser)
    root = tmp_path / "firstbook-private-writes"
    paths = {key: root / name for key, name in {
        "pool": "book-pool.json", "session": "owned-session-" + work["bookRef"] + ".json",
        "intake": "intake-" + work["bookRef"] + ".json"}.items()}
    reviewed = {key: path.read_bytes() for key, path in paths.items()}
    args = dict(expected_pool_sha256=hashlib.sha256(reviewed["pool"]).hexdigest(),
        expected_session_sha256=hashlib.sha256(reviewed["session"]).hexdigest(),
        stopped_session=browser.calls[0][2], book_ref=work["bookRef"])
    hub.calls.clear()
    return config, hub, root, paths, reviewed, args


def recover(config, hub, root, args):
    return pool.reconcile_unstarted(lambda: copy.deepcopy(config), hub, root.parent,
        now=lambda: 1000, **args)


def test_failed_open_explicit_recovery_keeps_job_reservation_and_session_history(tmp_path, executor):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    with pytest.raises(RuntimeError, match="requires_reconciliation"):
        run(config, hub, tmp_path)
    result = recover(config, hub, root, args)
    assert result["state"] == "reconciled_unstarted"
    assert result["reserved_books"] == 1 and result["remaining_books"] == 2
    assert result["publication_authorized"] is False
    assert ledger(tmp_path)["in_flight"] is None
    assert paths["session"].read_bytes() == before["session"]
    assert paths["intake"].read_bytes() == before["intake"]
    assert not executor and not any(action.startswith("/") for action, _ in hub.calls)
    old_packet = pool.worker.writer._load(paths["intake"])["jobs"][0]["packet"]
    assert run(config, hub, tmp_path)["reserved_books"] == 1
    assert len(executor) == 1
    assert executor[0]["work_id"] == old_packet["work_id"]
    assert executor[0]["execution_admission"] == old_packet["execution_admission"]
    assert executor[0]["setup"]["browser_session"] != args["stopped_session"]
    assert ledger(tmp_path)["configuration"] == config


@pytest.mark.parametrize("change", ["admitted", "reconciliation", "wrong_source", "wrong_book",
    "successor", "prepared", "setup", "outline", "session_hash", "pool_hash", "session_name", "revoked"])
def test_uncertain_or_changed_work_cannot_be_released(tmp_path, change):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    work = next(iter(hub.jobs.values()))
    if change == "admitted": work["executionAdmission"] = "already-dispatched"
    if change == "reconciliation": work["job"]["state"] = "reconciliation_required"
    if change == "wrong_source": work["job"]["source"]["runnerName"] = "Changed"
    if change == "wrong_book": work["bookRef"] = "2" * 64
    if change == "successor":
        other = copy.deepcopy(work)
        other["workId"] = "1" * 64 + "." + "b" * 64
        hub.jobs[other["workId"]] = other
    if change == "prepared":
        value = pool.worker.writer._load(paths["intake"])
        value["jobs"][0]["prepared"] = {"unexpected": True}
        pool.worker.writer._save(paths["intake"], value)
    if change in ("setup", "outline"):
        pool.worker.writer._save(root / (change + "-" + args["book_ref"] + ".json"), {})
    if change == "session_hash": args["expected_session_sha256"] = "0" * 64
    if change == "pool_hash": args["expected_pool_sha256"] = "0" * 64
    if change == "session_name": args["stopped_session"] = "another-window"
    if change == "revoked": config["approved"] = False
    with pytest.raises((ValueError, RuntimeError)):
        recover(config, hub, root, args)
    assert paths["pool"].read_bytes() == before["pool"]
    assert paths["session"].read_bytes() == before["session"]
    assert not any(action.startswith("/") for action, _ in hub.calls)


def test_changed_intake_after_recovery_does_not_authorize_a_browser(tmp_path, executor):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    recover(config, hub, root, args)
    value = pool.worker.writer._load(paths["intake"])
    value["jobs"][0]["packet"]["execution_admission"] = "changed-after-recovery"
    pool.worker.writer._save(paths["intake"], value)
    browser = Browser()
    with pytest.raises(RuntimeError, match="previous_session_requires_reconciliation"):
        run(config, hub, tmp_path, browser)
    assert not browser.calls and not executor


def test_recovery_does_not_authorize_a_second_failed_open(tmp_path):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    recover(config, hub, root, args)
    browser = Browser()
    browser.open = lambda *a: (_ for _ in ()).throw(RuntimeError("another failed open"))
    with pytest.raises(RuntimeError, match="another failed open"):
        run(config, hub, tmp_path, browser)
    with pytest.raises(RuntimeError, match="requires_reconciliation"):
        run(config, hub, tmp_path)
    assert len(ledger(tmp_path)["books"]) == 1


@pytest.mark.parametrize("lease", [pool._lease, pool.runtime.intake.cycle._lease])
def test_recovery_never_races_a_live_executor(tmp_path, lease):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    with lease(tmp_path):
        with pytest.raises(RuntimeError, match="busy"):
            recover(config, hub, root, args)
    assert paths["pool"].read_bytes() == before["pool"]


def test_changed_hub_snapshot_during_reconciliation_keeps_fence(tmp_path):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    original = hub.call
    count = 0
    def read(work_id):
        nonlocal count
        count += 1
        work = original(work_id)
        if count > 1: work["executionAdmission"] = "raced-admission"
        return work
    hub.call = read
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        recover(config, hub, root, args)
    assert paths["pool"].read_bytes() == before["pool"]


def test_failure_after_receipt_keeps_fence_and_exact_recovery_is_repeatable(tmp_path, monkeypatch):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    original = pool.worker.writer._save
    def fail_pool(path, value):
        if path == paths["pool"]:
            raise OSError("disk unavailable")
        original(path, value)
    with monkeypatch.context() as m:
        m.setattr(pool.worker.writer, "_save", fail_pool)
        with pytest.raises(OSError, match="disk unavailable"):
            recover(config, hub, root, args)
    assert paths["pool"].read_bytes() == before["pool"]
    with pytest.raises(RuntimeError, match="requires_reconciliation"):
        run(config, hub, tmp_path)
    assert recover(config, hub, root, args)["state"] == "reconciled_unstarted"


def test_recovery_rechecks_live_approval_after_observations(tmp_path):
    config, hub, root, paths, before, args = failed_open(tmp_path)
    original = hub.call
    def read(work_id):
        value = original(work_id)
        config["approved"] = False
        return value
    hub.call = read
    with pytest.raises(ValueError, match="not_admitted"):
        recover(config, hub, root, args)
    assert paths["pool"].read_bytes() == before["pool"]
