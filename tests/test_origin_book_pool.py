import copy
import json

import pytest

from scripts import origin_book_pool as pool
from tests.test_origin_chapter_intake import Queue, executor
from tests.test_origin_chapter_runtime import Browser
from tests.test_origin_chapter_watch import Clock


def configuration():
    return {"schema": pool._SCHEMA, "approval_id": "three-new-books", "approved": True,
        "maximum_new_books": 3, "maximum_chapters_per_book": 100,
        "profile_id": "chrome_local_12345", "profile_use_approved": True,
        "source_scope": "consented_origin", "account_sha256": "a" * 64,
        "expires_at": 1100, "excluded_book_refs": []}


class Books(Queue):
    def __init__(self):
        super().__init__()
        self.jobs.clear()

    def add(self, digit):
        work = copy.deepcopy(self.first)
        work.update(bookRef=digit * 64, workId=digit * 64 + "." + "a" * 64)
        self.jobs[work["workId"]] = work
        return work

    def pending_books(self):
        self.calls.append(("pending_books", None))
        return copy.deepcopy([w for w in self.jobs.values() if w["job"]["state"] != "review_required"])


def start(tmp_path, config=None):
    config = configuration() if config is None else config
    pool.initialize(config, tmp_path, now=lambda: 1000)
    return config


def run(config, hub, root, browser=None):
    return pool.run_once(lambda: copy.deepcopy(config), hub, root, now=lambda: 1000,
        browser=browser or Browser(), sleep=lambda _: None)


def ledger(root):
    return pool.worker.writer._load(root / "firstbook-private-writes/book-pool.json")


def test_three_books_total_fourth_never_dispatched_and_restart_never_refills(tmp_path, executor):
    config, hub, browser = start(tmp_path), Books(), Browser()
    for digit in "1234": hub.add(digit)
    for count in range(1, 4):
        result = run(config, hub, tmp_path, browser)
        assert result["reserved_books"] == count and result["remaining_books"] == 3 - count
    assert len(executor) == 3
    assert sum(p["setup"].get("maximum_book_credits", 0) for p in executor) == 3
    for _ in range(2):
        # A new controller invocation reloads the same persisted reservations.
        assert run(config, hub, tmp_path, browser)["remaining_books"] == 0
    assert len(executor) == 3
    assert hub.jobs["4" * 64 + "." + "a" * 64]["executionAdmission"] is None
    assert len(ledger(tmp_path)["books"]) == 3
    assert all(w["job"].get("readerAcceptedTextDigest") is None for w in hub.jobs.values())
    assert [x[0] for x in browser.calls] == ["open", "account", "close"] * 3


def test_reservation_and_inflight_fence_are_persisted_before_runtime(tmp_path, monkeypatch):
    config, hub = start(tmp_path), Books()
    hub.add("1")
    def crash(*args, **kwargs):
        state = ledger(tmp_path)
        assert len(state["books"]) == 1 and state["in_flight"] == "1" * 64
        raise RuntimeError("uncertain_provider_result")
    monkeypatch.setattr(pool.runtime, "run_bounded", crash)
    with pytest.raises(RuntimeError, match="uncertain_provider_result"): run(config, hub, tmp_path)
    hub.add("2")
    with pytest.raises(RuntimeError, match="requires_reconciliation"): run(config, hub, tmp_path)
    assert len(ledger(tmp_path)["books"]) == 1


def test_reader_requested_continuation_reuses_book_without_another_slot_or_credit(tmp_path, executor):
    config, hub = start(tmp_path), Books()
    hub.add("1")
    run(config, hub, tmp_path)
    hub.next()
    result = run(config, hub, tmp_path)
    assert result["reserved_books"] == 1 and result["remaining_books"] == 2
    assert len(executor) == 2
    assert sum(p["setup"].get("maximum_book_credits", 0) for p in executor) == 1
    assert list(hub.jobs.values())[-1]["job"].get("readerAcceptedTextDigest") is None


def test_retained_browser_stops_pool_and_is_not_retried(tmp_path, monkeypatch):
    config, hub = start(tmp_path), Books()
    hub.add("1")
    monkeypatch.setattr(pool.runtime, "run_bounded", lambda *a, **k:
        {"state": "provider_busy", "browser_retained": True})
    assert run(config, hub, tmp_path)["state"] == "reconciliation_required"
    with pytest.raises(RuntimeError, match="requires_reconciliation"): run(config, hub, tmp_path)


@pytest.mark.parametrize("key,value", [("maximum_new_books", 4), ("expires_at", 1150),
    ("account_sha256", "b" * 64), ("profile_id", "chrome_local_999"), ("approval_id", "reset"),
    ("maximum_chapters_per_book", 99)])
def test_editing_configuration_cannot_expand_reset_or_move_retained_allowance(tmp_path, key, value):
    config, hub = start(tmp_path), Books()
    config[key] = value
    with pytest.raises(RuntimeError, match="custody_mismatch"): run(config, hub, tmp_path)
    assert not hub.calls


@pytest.mark.parametrize("key,value", [("approved", False), ("profile_use_approved", False),
    ("source_scope", "synthetic_only"), ("expires_at", 1000), ("maximum_new_books", True),
    ("maximum_new_books", 0), ("maximum_new_books", 21), ("maximum_chapters_per_book", 0)])
def test_revoked_or_invalid_grant_never_queries_hub(tmp_path, key, value):
    config, hub = start(tmp_path), Books()
    config[key] = value
    with pytest.raises(ValueError): run(config, hub, tmp_path)
    assert not hub.calls


def test_missing_ledger_is_not_recreated_and_initialization_does_not_overwrite(tmp_path):
    config, hub = configuration(), Books()
    with pytest.raises(RuntimeError, match="custody_missing"): run(config, hub, tmp_path)
    start(tmp_path, config)
    with pytest.raises(RuntimeError, match="empty_custody"): pool.initialize(config, tmp_path, now=lambda: 1000)
    (tmp_path / "firstbook-private-writes/book-pool.json").unlink()
    with pytest.raises(RuntimeError, match="custody_missing"): run(config, hub, tmp_path)


def test_existing_books_consumed_jobs_and_continuations_do_not_get_new_credit(tmp_path, executor):
    config = configuration()
    config["excluded_book_refs"] = ["1" * 64]
    start(tmp_path, config)
    hub = Books()
    hub.add("1")
    hub.add("2")["executionAdmission"] = "old-admission"
    hub.add("3")["job"]["previous"] = {"old": "chapter"}
    hub.add("4")["previousWorkId"] = "other-work"
    hub.add("5")["job"]["state"] = "reconciliation_required"
    assert run(config, hub, tmp_path)["remaining_books"] == 3
    assert not executor


def test_ambiguous_first_chapter_fails_before_reservation(tmp_path, executor):
    config, hub = start(tmp_path), Books()
    first = hub.add("1")
    second = copy.deepcopy(first)
    second["workId"] = "1" * 64 + "." + "b" * 64
    hub.jobs[second["workId"]] = second
    with pytest.raises(RuntimeError, match="ambiguous_first_chapter"): run(config, hub, tmp_path)
    assert not ledger(tmp_path)["books"] and not executor


def test_hub_source_changed_after_enumeration_is_rejected(tmp_path, executor):
    config, hub = start(tmp_path), Books()
    hub.add("1")
    original = hub.call
    def read(work_id):
        changed = original(work_id)
        changed["job"]["source"]["runnerName"] = "Another runner"
        return changed
    hub.call = read
    with pytest.raises(RuntimeError, match="source_changed"): run(config, hub, tmp_path)
    assert not ledger(tmp_path)["books"] and not executor


@pytest.mark.parametrize("key,value", [("publicationAuthorized", True), ("affectsMechanics", True),
    ("requiresReaderReview", False), ("provider", "another_provider")])
def test_untrusted_job_posture_does_not_enroll(tmp_path, executor, key, value):
    config, hub = start(tmp_path), Books()
    hub.add("1")["job"][key] = value
    with pytest.raises(ValueError, match="binding_mismatch"): run(config, hub, tmp_path)
    assert not ledger(tmp_path)["books"] and not executor


def test_global_lease_serializes_competing_pool_controllers(tmp_path):
    config, hub = start(tmp_path), Books()
    with pool._lease(tmp_path):
        with pytest.raises(RuntimeError, match="pool_busy"): run(config, hub, tmp_path)
    assert not hub.calls


def test_idle_watch_is_bounded_and_opens_no_browser(tmp_path, executor):
    config, hub, browser, clock = start(tmp_path), Books(), Browser(), Clock()
    result = pool.watch(lambda: copy.deepcopy(config), hub, tmp_path, browser=browser,
        now=clock.wall, monotonic=clock.monotonic, sleep=clock.sleep, duration=31, poll_interval=15)
    assert result["state"] == "watch_finished" and clock.elapsed == 31
    assert result["remaining_books"] == 3 and not browser.calls and not executor


def test_mid_dispatch_revocation_stops_before_provider_cycle(tmp_path, executor):
    config, hub, browser = start(tmp_path), Books(), Browser()
    hub.add("1")
    original = pool.runtime.run_bounded
    def invoke(*args, **kwargs):
        config["approved"] = False
        return original(*args, **kwargs)
    from unittest.mock import patch
    with patch.object(pool.runtime, "run_bounded", invoke):
        with pytest.raises(ValueError): run(config, hub, tmp_path, browser)
    assert not executor and not browser.calls
    assert ledger(tmp_path)["in_flight"] == "1" * 64


def test_full_pending_page_is_not_misrepresented_as_complete(tmp_path):
    config, hub = start(tmp_path), Books()
    work = hub.add("1")
    hub.pending_books = lambda: [copy.deepcopy(work)] * 20
    with pytest.raises(RuntimeError, match="pending_incomplete"): run(config, hub, tmp_path)
    assert not ledger(tmp_path)["books"]


def test_duplicate_json_member_in_custody_is_rejected(tmp_path):
    config, hub = start(tmp_path), Books()
    path = tmp_path / "firstbook-private-writes/book-pool.json"
    path.write_text('{"books": [], ' + json.dumps(ledger(tmp_path))[1:])
    with pytest.raises(ValueError, match="invalid_json"): run(config, hub, tmp_path)
    assert not hub.calls
