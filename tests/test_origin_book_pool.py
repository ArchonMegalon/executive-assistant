import copy
import hashlib
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


def test_selected_book_preserves_prior_books_and_only_executes_exact_selection(tmp_path, monkeypatch):
    config, hub = start(tmp_path), Books()
    for digit in "123": hub.add(digit)
    observed = []
    def execute(book, *args, **kwargs):
        observed.append(book["admission"]["book_ref"])
        assert ledger(tmp_path)["in_flight"] == observed[-1]
        return {"state": "review_required", "browser_retained": False}
    monkeypatch.setattr(pool.runtime, "run_bounded", execute)
    def selected(ref):
        return pool.run_once(lambda: config, hub, tmp_path, now=lambda: 1000, selected_book_ref=ref)
    selected("1" * 64)
    previous = copy.deepcopy(ledger(tmp_path)["books"])
    selected("3" * 64)
    assert observed == ["1" * 64, "3" * 64]
    assert ledger(tmp_path)["books"][:1] == previous
    assert len(ledger(tmp_path)["books"]) == 2
    selected("3" * 64)
    assert observed[-1] == "3" * 64 and len(ledger(tmp_path)["books"]) == 2
    assert hub.jobs["2" * 64 + "." + "a" * 64]["executionAdmission"] is None


@pytest.mark.parametrize("ref", ["missing", "", True, "F" * 64])
def test_selected_invalid_identity_does_not_query_hub(tmp_path, ref):
    config, hub = start(tmp_path), Books()
    with pytest.raises(ValueError, match="selection_invalid"):
        pool.run_once(lambda: config, hub, tmp_path, now=lambda: 1000, selected_book_ref=ref)
    assert not hub.calls


def test_selected_missing_book_cannot_fall_back_to_another(tmp_path, executor):
    config, hub = start(tmp_path), Books()
    hub.add("1")
    with pytest.raises(RuntimeError, match="selected_book_not_admitted"):
        pool.run_once(lambda: config, hub, tmp_path, now=lambda: 1000, selected_book_ref="2" * 64)
    assert not executor and not ledger(tmp_path)["books"]


def test_selected_book_does_not_bypass_capacity_or_uncertain_fence(tmp_path, monkeypatch):
    config = configuration()
    config["maximum_new_books"] = 1
    start(tmp_path, config)
    hub = Books()
    for digit in "12": hub.add(digit)
    monkeypatch.setattr(pool.runtime, "run_bounded", lambda *a, **k:
        {"state": "idle", "browser_retained": False})
    run(config, hub, tmp_path)
    before = ledger(tmp_path)
    with pytest.raises(RuntimeError, match="selected_book_not_admitted"):
        pool.run_once(lambda: config, hub, tmp_path, now=lambda: 1000, selected_book_ref="2" * 64)
    assert ledger(tmp_path) == before
    before["in_flight"] = "1" * 64
    pool.worker.writer._save(tmp_path / "firstbook-private-writes/book-pool.json", before)
    with pytest.raises(RuntimeError, match="requires_reconciliation"):
        pool.run_once(lambda: config, hub, tmp_path, now=lambda: 1000, selected_book_ref="2" * 64)


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


def completed_fence(tmp_path, executor):
    config, hub = start(tmp_path), Books()
    hub.add("1")
    run(config, hub, tmp_path)
    root = tmp_path / "firstbook-private-writes"
    path = root / "book-pool.json"
    state = ledger(tmp_path)
    state["in_flight"] = "1" * 64  # deadline/crash before clearing an idle sweep
    pool.worker.writer._save(path, state)
    hub.calls.clear()
    executor.clear()
    return config, hub, root, path


def reconcile(config, hub, root, path, **kwargs):
    return pool.reconcile_completed(lambda: copy.deepcopy(config), hub, root.parent,
        expected_pool_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        book_ref="1" * 64, now=lambda: 1000, **kwargs)


def test_explicit_completed_reconciliation_preserves_budget_and_never_dispatches(tmp_path, executor):
    config, hub, root, path = completed_fence(tmp_path, executor)
    before = path.read_bytes()
    journals = {p.name: p.read_bytes() for p in root.iterdir() if p.suffix == ".json" and p != path}
    result = reconcile(config, hub, root, path)
    assert result["state"] == "reconciled_completed"
    assert result["reserved_books"] == 1 and result["remaining_books"] == 2
    expected = json.loads(before)
    expected["in_flight"] = None
    assert ledger(tmp_path) == expected
    assert all((root / name).read_bytes() == raw for name, raw in journals.items())
    assert not executor and all(action in ("", "pending") for action, _ in hub.calls)
    assert hub.jobs["1" * 64 + "." + "a" * 64]["job"].get("readerAcceptedTextDigest") is None
    receipt = pool.worker.writer._load(root / ("pool-reconciliation-" + hashlib.sha256(before).hexdigest() + ".json"))
    assert receipt == result
    assert receipt["pool_after_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert run(config, hub, tmp_path)["state"] == "idle"


@pytest.mark.parametrize("retained_state", ["open", "retained_for_reconciliation"])
def test_operator_verified_stopped_completed_session_preserves_original_journal(tmp_path, executor, retained_state):
    config, hub, root, path = completed_fence(tmp_path, executor)
    session_path = root / ("owned-session-" + "1" * 64 + ".json")
    session = pool.worker.writer._load(session_path)
    session["state"] = retained_state
    pool.worker.writer._save(session_path, session)
    original = session_path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    with pytest.raises(RuntimeError, match="session_not_closed"):
        reconcile(config, hub, root, path)
    result = reconcile(config, hub, root, path,
        stopped_session=session["session"], expected_session_sha256=digest)
    assert result["state"] == "reconciled_completed"
    assert result["stopped_session"] == session["session"]
    assert result["session_sha256"] == digest
    assert result["retained_session_state"] == retained_state
    assert session_path.read_bytes() == original
    assert ledger(tmp_path)["in_flight"] is None
    assert len(ledger(tmp_path)["books"]) == 1
    assert not executor and all(action in ("", "pending") for action, _ in hub.calls)


@pytest.mark.parametrize("change", ["digest", "session", "half_identity", "opening", "unfinished"])
def test_stopped_completion_rejects_uncertain_or_mismatched_state(tmp_path, executor, change):
    config, hub, root, path = completed_fence(tmp_path, executor)
    session_path = root / ("owned-session-" + "1" * 64 + ".json")
    session = pool.worker.writer._load(session_path)
    session["state"] = "opening" if change == "opening" else "open"
    pool.worker.writer._save(session_path, session)
    kwargs = {"stopped_session": session["session"],
        "expected_session_sha256": hashlib.sha256(session_path.read_bytes()).hexdigest()}
    if change == "digest": kwargs["expected_session_sha256"] = "f" * 64
    if change == "session": kwargs["stopped_session"] = "origin-book-" + "f" * 32
    if change == "half_identity": kwargs.pop("expected_session_sha256")
    if change == "unfinished":
        next(iter(hub.jobs.values()))["job"].update(state="reconciliation_required", draftText=None,
            providerReceiptDigest=None)
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.suffix == ".json"}
    with pytest.raises((RuntimeError, ValueError)):
        reconcile(config, hub, root, path, **kwargs)
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.suffix == ".json"} == before
    assert not executor and all(action in ("", "pending") for action, _ in hub.calls)


@pytest.mark.parametrize("change", ["open_session", "wrong_session_binding", "missing_session",
    "missing_intake", "local_pending", "hub_pending", "wrong_source", "wrong_admission",
    "invalid_receipt", "bad_acceptance", "pending_successor", "revoked", "expanded_budget"])
def test_uncertain_reconciliation_keeps_every_byte_and_cannot_dispatch(tmp_path, executor, change):
    config, hub, root, path = completed_fence(tmp_path, executor)
    session = root / ("owned-session-" + "1" * 64 + ".json")
    intake = root / ("intake-" + "1" * 64 + ".json")
    job = next(iter(hub.jobs.values()))
    if change in ("open_session", "wrong_session_binding"):
        value = pool.worker.writer._load(session)
        if change == "open_session": value["state"] = "retained_for_reconciliation"
        else: value["binding"]["profile_id"] = "chrome_local_999"
        pool.worker.writer._save(session, value)
    if change == "missing_session": session.unlink()
    if change == "missing_intake": intake.unlink()
    if change == "local_pending":
        value = pool.worker.writer._load(intake)
        value["jobs"][-1]["state"] = "working"
        pool.worker.writer._save(intake, value)
    if change == "hub_pending": job["job"].update(state="reconciliation_required", draftText=None, providerReceiptDigest=None)
    if change == "wrong_source": job["job"]["source"]["runnerName"] = "Wrong runner"
    if change == "wrong_admission": job["executionAdmission"] = "other"
    if change == "invalid_receipt": job["job"]["providerReceiptDigest"] = None
    if change == "bad_acceptance": job["job"]["readerAcceptedTextDigest"] = "f" * 64
    if change == "pending_successor": hub.next()
    if change == "revoked": config["approved"] = False
    if change == "expanded_budget": config["maximum_new_books"] = 4
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.suffix == ".json"}
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        reconcile(config, hub, root, path)
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.suffix == ".json"} == before
    assert not executor and all(action in ("", "pending") for action, _ in hub.calls)


@pytest.mark.parametrize("lease", [pool._lease, pool.runtime.intake.cycle._lease])
def test_reconciliation_cannot_touch_live_controller_or_cycle(tmp_path, executor, lease):
    config, hub, root, path = completed_fence(tmp_path, executor)
    before = path.read_bytes()
    with lease(tmp_path), pytest.raises(RuntimeError, match="busy"):
        reconcile(config, hub, root, path)
    assert path.read_bytes() == before and not hub.calls and not executor


def test_reconciliation_requires_exact_reviewed_fence_and_stable_inputs(tmp_path, executor):
    config, hub, root, path = completed_fence(tmp_path, executor)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        pool.reconcile_completed(lambda: config, hub, tmp_path, expected_pool_sha256="0" * 64,
            book_ref="1" * 64, now=lambda: 1000)
    assert not hub.calls
    original = hub.pending
    def change_approval(ref):
        config["approved"] = False
        return original(ref)
    hub.pending = change_approval
    with pytest.raises(ValueError): reconcile(config, hub, root, path)
    assert path.read_bytes() == before and not executor


@pytest.mark.parametrize("change", ["pool", "session", "intake", "hub_text", "expired"])
def test_reconciliation_rejects_inputs_changed_during_readback(tmp_path, executor, change):
    config, hub, root, path = completed_fence(tmp_path, executor)
    original = hub.pending
    def mutate(ref):
        if change == "pool":
            value = ledger(tmp_path)
            value["in_flight"] = None
            pool.worker.writer._save(path, value)
        if change in ("session", "intake"):
            target = root / (("owned-session-" if change == "session" else "intake-") + ref + ".json")
            target.write_bytes(target.read_bytes() + b" ")
        if change == "hub_text": next(iter(hub.jobs.values()))["job"]["draftText"] += " Revised."
        if change == "expired": config["expires_at"] = 999
        return original(ref)
    hub.pending = mutate
    with pytest.raises((ValueError, RuntimeError)): reconcile(config, hub, root, path)
    assert not list(root.glob("pool-reconciliation-*")) and not executor


def test_reconciliation_keeps_all_reservations_and_validates_completed_chain(tmp_path, executor):
    config, hub, root, path = completed_fence(tmp_path, executor)
    reconcile(config, hub, root, path)
    hub.next()
    run(config, hub, tmp_path)
    hub.add("2")
    run(config, hub, tmp_path)
    state = ledger(tmp_path)
    state["in_flight"] = "1" * 64
    pool.worker.writer._save(path, state)
    before = path.read_bytes()
    executor.clear()
    result = reconcile(config, hub, root, path)
    assert result["reserved_books"] == 2 and result["remaining_books"] == 1
    assert len(result["completed_jobs"]) == 2
    assert result["completed_jobs"][0]["reader_accepted_text_sha256"] is not None
    assert result["completed_jobs"][1]["reader_accepted_text_sha256"] is None
    assert ledger(tmp_path)["books"] == state["books"] and not executor
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        pool.reconcile_completed(lambda: config, hub, tmp_path,
            expected_pool_sha256=hashlib.sha256(before).hexdigest(), book_ref="1" * 64, now=lambda: 1000)
