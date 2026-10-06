"""Standing credit approval uses the real pool/intake and simulated provider."""
import copy
import hashlib

import pytest

from scripts import origin_book_pool as pool
from tests.test_origin_book_pool import Books, BalanceBrowser, ledger, rotating_configuration, run, start
from tests.test_origin_chapter_intake import executor
from tests.test_origin_chapter_watch import Clock


def configuration():
    config = rotating_configuration()
    config.update(schema="firstbook.local-book-service/v1", approval_id="existing-credit-snapshot",
                  expires_at=None)
    for account, budget in zip(config["accounts"], (1, 2)):
        account["maximum_new_books"] = budget
    return config


def test_standing_service_admits_later_user_book_after_seven_days_and_cold_restart(tmp_path, executor):
    config, hub, clock = start(tmp_path, configuration()), Books(), Clock()
    browser = BalanceBrowser({"a" * 64: 50, "b" * 64: 50})
    hub.add("1")
    run(config, hub, tmp_path, browser)
    clock.elapsed = 8 * 86400
    hub.add("2")
    result = pool.serve(lambda: config, hub, tmp_path, browser=browser,
        now=clock.wall, monotonic=clock.monotonic, sleep=clock.sleep,
        stop_requested=lambda: len(executor) == 2)
    assert result["state"] == "service_stopped" and len(executor) == 2
    assert [p["setup"]["account_sha256"] for p in executor] == ["a" * 64, "b" * 64]
    assert all(b["admission"]["expires_at"] is None for b in ledger(tmp_path)["books"])
    pool.run_once(lambda: config, hub, tmp_path, browser=browser, now=clock.wall)
    assert len(executor) == 2  # Completed work is not regenerated on restart.
    assert all(w["job"].get("readerAcceptedTextDigest") is None for w in hub.jobs.values())


def test_credit_snapshot_does_not_refill_when_provider_balance_increases(tmp_path, executor):
    config, hub = start(tmp_path, configuration()), Books()
    browser = BalanceBrowser({"a" * 64: 99, "b" * 64: 99})
    for digit in "1234":
        hub.add(digit)
        run(config, hub, tmp_path, browser)
    assert len(executor) == 3 and len(ledger(tmp_path)["books"]) == 3
    assert browser.probes == ["a" * 64, "b" * 64, "b" * 64]
    assert hub.jobs["4" * 64 + "." + "a" * 64]["executionAdmission"] is None
    assert run(config, hub, tmp_path, browser)["remaining_books"] == 0
    assert len(executor) == 3


def test_exhausted_new_book_accounts_do_not_stop_existing_chapters(tmp_path, executor):
    config, hub, clock = start(tmp_path, configuration()), Books(), Clock()
    browser = BalanceBrowser({"a" * 64: 1, "b" * 64: 0})
    first = hub.add("1")
    run(config, hub, tmp_path, browser)
    hub.next()  # Reader accepts the existing chapter and requests its successor.
    second = hub.add("2")
    observations = []
    result = pool.watch(lambda: config, hub, tmp_path, browser=browser,
        now=clock.wall, monotonic=clock.monotonic, sleep=clock.sleep,
        duration=31, poll_interval=15, observe=observations.append)
    assert result["state"] == "watch_finished" and clock.elapsed == 31
    assert len(executor) == 2 and "maximum_book_credits" not in executor[-1]["setup"]
    assert second["executionAdmission"] is None
    assert ledger(tmp_path)["new_book_admission_exhausted"] is True
    assert browser.probes == ["a" * 64, "b" * 64]
    assert all(r["state"] == "accounts_exhausted" for r in observations)
    browser.balances = {}  # Cold restart cannot silently admit refilled credits.
    run(config, hub, tmp_path, browser)
    assert len(executor) == 2 and first["executionAdmission"] is not None


@pytest.mark.parametrize("change", ["revoked", "budget", "account", "approval"])
def test_standing_approval_change_stops_before_any_new_admission(tmp_path, executor, change):
    config, hub, clock = start(tmp_path, configuration()), Books(), Clock()
    browser = BalanceBrowser({"a" * 64: 99, "b" * 64: 99})
    def changed():
        hub.add("1")
        if change == "revoked": config["approved"] = False
        if change == "budget":
            config["maximum_new_books"] += 1
            config["accounts"][0]["maximum_new_books"] += 1
        if change == "account": config["accounts"][0]["account_sha256"] = "c" * 64
        if change == "approval": config["approval_id"] = "another-approval"
    clock.after_sleep = changed
    with pytest.raises((ValueError, RuntimeError)):
        pool.serve(lambda: copy.deepcopy(config), hub, tmp_path, browser=browser,
            now=clock.wall, monotonic=clock.monotonic, sleep=clock.sleep)
    assert not executor and not browser.calls and not ledger(tmp_path)["books"]


@pytest.mark.parametrize("change", ["sum", "negative", "boolean", "expiry", "missing-ceiling"])
def test_invalid_standing_budget_does_not_initialize(tmp_path, change):
    config = configuration()
    if change == "sum": config["maximum_new_books"] += 1
    if change == "negative": config["accounts"][0]["maximum_new_books"] = -1
    if change == "boolean": config["accounts"][0]["maximum_new_books"] = True
    if change == "expiry": config["expires_at"] = 1100
    if change == "missing-ceiling": del config["accounts"][0]["maximum_new_books"]
    with pytest.raises(ValueError): start(tmp_path, config)
    assert not (tmp_path / "firstbook-private-writes/book-pool.json").exists()


def test_finite_configuration_cannot_be_silently_promoted(tmp_path):
    old = rotating_configuration()
    start(tmp_path, old)
    hub = Books()
    with pytest.raises(RuntimeError, match="custody_mismatch"):
        run(configuration(), hub, tmp_path)
    assert not hub.calls and ledger(tmp_path)["configuration"] == old


def test_runtime_still_requires_short_lived_explicit_admission(tmp_path, monkeypatch):
    config, hub = start(tmp_path, configuration()), Books()
    hub.add("1")
    browser = BalanceBrowser({"a" * 64: 1})
    with pytest.raises(ValueError, match="not_admitted"):
        pool.runtime._configuration(pool._book_configuration(config, next(iter(hub.jobs.values()))),
                                    "validation-only", 1000)
    def execute(book, *args, before_tick, **kwargs):
        assert book["admission"]["expires_at"] == 4600
        assert ledger(tmp_path)["in_flight"] == "1" * 64
        config["approved"] = False
        before_tick()
        pytest.fail("Revoked parent must stop execution")
    monkeypatch.setattr(pool.runtime, "run_bounded", execute)
    with pytest.raises(ValueError): run(config, hub, tmp_path, browser)
    assert ledger(tmp_path)["in_flight"] == "1" * 64
    with pytest.raises(RuntimeError, match="requires_reconciliation"):
        run(configuration(), hub, tmp_path, browser)


def test_standing_custody_rejects_per_account_overdraw(tmp_path):
    config, hub = start(tmp_path, configuration()), Books()
    books = [hub.add(digit) for digit in "12"]
    state = ledger(tmp_path)
    state["books"] = [pool._book_configuration(config, w, config["accounts"][0]) for w in books]
    pool.worker.writer._save(tmp_path / "firstbook-private-writes/book-pool.json", state)
    with pytest.raises(RuntimeError, match="custody_mismatch"):
        run(config, hub, tmp_path)
    assert not hub.calls


def transition(config, target, root, **kwargs):
    path = root / "firstbook-private-writes/book-pool.json"
    return pool.approve_standing_service(lambda: config, target, root,
        expected_pool_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), now=lambda: 1000, **kwargs)


def test_explicit_transition_preserves_all_reserved_books_and_journal_bytes(tmp_path, executor):
    old, hub = start(tmp_path, rotating_configuration()), Books()
    browser = BalanceBrowser({"a" * 64: 1, "b" * 64: 2})
    hub.add("1")
    run(old, hub, tmp_path, browser)
    root = tmp_path / "firstbook-private-writes"
    before = {p: p.read_bytes() for p in root.iterdir() if p.name != "book-pool.json"}
    hub.calls.clear()
    browser.calls.clear()
    target = configuration()
    result = transition(old, target, tmp_path)
    assert result["reserved_books"] == 1 and result["remaining_books"] == 2
    assert result["pool_after_sha256"] == hashlib.sha256((root / "book-pool.json").read_bytes()).hexdigest()
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not hub.calls and not browser.calls and len(executor) == 1
    hub.next()
    run(target, hub, tmp_path, browser)
    assert len(executor) == 2 and "maximum_book_credits" not in executor[-1]["setup"]
    assert len(ledger(tmp_path)["books"]) == 1
    with pytest.raises(RuntimeError, match="custody_mismatch"):
        run(old, hub, tmp_path, browser)


@pytest.mark.parametrize("change", ["in-flight", "probe", "session", "unfinished", "account",
                                  "budget", "excluded", "chapter-limit", "same-approval"])
def test_transition_does_not_clear_uncertainty_or_rebind_existing_work(tmp_path, executor, change):
    old, hub = start(tmp_path, rotating_configuration()), Books()
    browser = BalanceBrowser({"a" * 64: 1})
    hub.add("1")
    run(old, hub, tmp_path, browser)
    target, state = configuration(), ledger(tmp_path)
    root = tmp_path / "firstbook-private-writes"
    if change == "in-flight":
        state["in_flight"] = "1" * 64
        pool.worker.writer._save(root / "book-pool.json", state)
    if change == "probe":
        pool.worker.writer._save(root / "account-probe.json", {"state": "opening"})
    if change in ("session", "unfinished"):
        path = root / (("owned-session-" if change == "session" else "intake-") + "1" * 64 + ".json")
        record = pool.worker.writer._load(path)
        if change == "session": record["state"] = "retained_for_reconciliation"
        else: record["jobs"][-1]["state"] = "working"
        pool.worker.writer._save(path, record)
    if change == "account": target["accounts"][0]["account_sha256"] = "c" * 64
    if change == "budget":
        target["accounts"][0]["maximum_new_books"] = 0
        target["maximum_new_books"] = 2
    if change == "excluded": target["excluded_book_refs"] = ["1" * 64]
    if change == "chapter-limit": target["maximum_chapters_per_book"] = 99
    if change == "same-approval": target["approval_id"] = old["approval_id"]
    before = {p: p.read_bytes() for p in root.iterdir()}
    with pytest.raises((ValueError, RuntimeError)):
        transition(old, target, tmp_path)
    assert all(p.read_bytes() == data for p, data in before.items())
    assert len(executor) == 1


def test_transition_requires_exact_snapshot_and_preserves_historical_exclusions(tmp_path):
    old = rotating_configuration()
    old["excluded_book_refs"] = ["f" * 64]
    start(tmp_path, old)
    with pytest.raises(ValueError, match="scope_changed"):
        transition(old, configuration(), tmp_path)
    target = configuration()
    target["excluded_book_refs"] = ["f" * 64]
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        pool.approve_standing_service(lambda: old, target, tmp_path,
            expected_pool_sha256="0" * 64, now=lambda: 1000)
    assert ledger(tmp_path)["configuration"] == old


def test_interrupted_transition_keeps_old_authority_until_atomic_commit(tmp_path, executor, monkeypatch):
    old, hub = start(tmp_path, rotating_configuration()), Books()
    hub.add("1")
    run(old, hub, tmp_path, BalanceBrowser({"a" * 64: 1}))
    path = tmp_path / "firstbook-private-writes/book-pool.json"
    before = path.read_bytes()
    save = pool.worker.writer._save
    def interrupted(target, value, **kwargs):
        if target == path: raise OSError("disk unavailable")
        save(target, value, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(pool.worker.writer, "_save", interrupted)
        with pytest.raises(OSError): transition(old, configuration(), tmp_path)
    assert path.read_bytes() == before
    assert transition(old, configuration(), tmp_path)["reserved_books"] == 1
    assert len(executor) == 1


def test_standing_completed_reconciliation_keeps_exact_grant_and_never_dispatches(tmp_path, executor):
    config, hub = start(tmp_path, configuration()), Books()
    hub.add("1")
    run(config, hub, tmp_path, BalanceBrowser({"a" * 64: 1}))
    state = ledger(tmp_path)
    state["in_flight"] = "1" * 64
    path = tmp_path / "firstbook-private-writes/book-pool.json"
    pool._save_pool(path, state)
    result = pool.reconcile_completed(lambda: config, hub, tmp_path,
        expected_pool_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), book_ref="1" * 64,
        now=lambda: 8 * 86400)
    assert result["state"] == "reconciled_completed" and len(executor) == 1
    assert ledger(tmp_path) == {**state, "in_flight": None}


def test_large_service_pool_round_trip_does_not_expand_chapter_record_limit(tmp_path):
    config = configuration()
    config["maximum_new_books"] = 1000
    config["accounts"][0]["maximum_new_books"] = 998
    start(tmp_path, config)
    hub = Books()
    work = hub.add("1")
    state = ledger(tmp_path)
    for index in range(1000):
        ref = f"{index:064x}"
        item = {**work, "bookRef": ref, "workId": ref + "." + "a" * 64}
        state["books"].append(pool._book_configuration(config, item, config["accounts"][index >= 998]))
    path = tmp_path / "firstbook-private-writes/book-pool.json"
    pool._save_pool(path, state)
    assert path.stat().st_size > pool.worker.writer._MAX_RECORD_BYTES
    assert pool._read_ledger(path, config, 1000) == state
    with pytest.raises(RuntimeError, match="record_invalid"):
        pool.worker.writer._load(path)  # Existing single-chapter readers stay bounded.
    with pytest.raises(RuntimeError, match="oversized"):
        pool.worker.writer._save(path.parent / "ordinary-chapter.json", state)


@pytest.mark.parametrize("maximum", [True, -1, 0, 2_000_001, None])
def test_private_record_limits_remain_bounded(tmp_path, maximum):
    path = tmp_path / "not-created.json"
    with pytest.raises(ValueError, match="record_limit_invalid"):
        pool.worker.writer._save(path, {}, maximum=maximum)
    with pytest.raises(ValueError, match="record_limit_invalid"):
        pool.worker.writer._load(path, maximum=maximum)
    assert not path.exists()
