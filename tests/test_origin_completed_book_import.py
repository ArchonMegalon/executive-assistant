import hashlib

import pytest

from scripts import origin_completed_book_import as migration
from scripts import firstbook_book_binding as mapping
from tests.test_origin_book_pool import Books, start, configuration, rotating_configuration, run, ledger
from tests.test_origin_chapter_intake import executor
from tests.test_origin_chapter_runtime import Browser

pool = migration.pool


@pytest.fixture
def completed(tmp_path, executor):
    source, destination = tmp_path / "old", tmp_path / "new"
    source.mkdir(mode=0o700)
    destination.mkdir(mode=0o700)
    config = configuration() | {"maximum_new_books": 1, "maximum_chapters_per_book": 1}
    start(source, config)
    hub = Books()
    work = hub.add("1")
    run(config, hub, source)
    root = source / "firstbook-private-writes"
    intake = pool.worker.writer._load(root / ("intake-" + "1" * 64 + ".json"))
    prepared = intake["jobs"][0]["prepared"]
    binding = pool.worker.writer._binding(prepared)
    observed = {"origin": "https://app.firstbook.ai", "bookTitles": [binding["book_title"]],
        "chapterTitle": binding["chapter_title"], "chapterNumber": 1, "chapterCount": 8,
        "surfaceCount": 1, "text": work["job"]["draftText"], "reviewRequired": True,
        "editing": False, "approveControl": 1}
    record = {"binding": binding, "state": "chapter_review_required",
        "result": pool.worker.writer._result(binding, observed)}
    path = pool.worker.writer._record_path(root, binding)
    pool.worker.writer._save(path, record)
    (root / ".writer.lock").touch(mode=0o600)
    work["job"]["providerReceiptDigest"] = hashlib.sha256(path.read_bytes()).hexdigest()
    mapping.bind_prepared(work["bookRef"], work["job"]["source"]["chapterId"], prepared, source)
    for prefix in ("setup-", "outline-"):
        pool.worker.writer._save(root / (prefix + "1" * 64 + ".json"), {"fixture": "completed preparation"})
    target = rotating_configuration() | {"approval_id": "approved-continuation", "expires_at": 1200}
    return source, destination, target, hub


def transfer(data, **kwargs):
    source, destination, target, hub = data
    return migration.import_completed_book(source, destination, target, hub,
        expected_source_sha256=hashlib.sha256((source / "firstbook-private-writes/book-pool.json").read_bytes()).hexdigest(),
        now=lambda: 1000, **kwargs)


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")}


def test_completed_import_keeps_original_bytes_and_next_chapter_never_buys_a_book(completed, executor):
    source, destination, target, hub = completed
    before = snapshot(source)
    hub.calls.clear()
    result = transfer(completed)
    assert result["reserved_books"] == 1 and result["remaining_books"] == 2
    assert result["provider_dispatch"] is False
    assert snapshot(source) == before
    assert all(action in ("", "pending") for action, _ in hub.calls)
    assert hub.jobs["1" * 64 + "." + "a" * 64]["job"].get("readerAcceptedTextDigest") is None
    # No work means no browser and no additional provider action.
    browser = Browser()
    assert run(target, hub, destination, browser)["state"] == "idle"
    assert not browser.calls and len(executor) == 1
    hub.next(accepted=True)
    run(target, hub, destination, browser)
    assert len(executor) == 2 and "maximum_book_credits" not in executor[-1]["setup"]
    assert executor[-1]["previous"]["work_id"] == executor[0]["work_id"]
    assert ledger(destination)["books"][0]["profile_id"] == "chrome_local_12345"
    assert snapshot(source) == before
    # Provider receipt is copied byte for byte, not regenerated JSON.
    for relative, raw in before.items():
        if relative.name not in ("book-pool.json", "intake-" + "1" * 64 + ".json", "owned-session-" + "1" * 64 + ".json"):
            if relative.parent.name != "books":
                assert (destination / relative).read_bytes() == raw


def test_continuation_still_requires_exact_reader_acceptance(completed, executor):
    transfer(completed)
    source, destination, target, hub = completed
    hub.next(accepted=False)
    assert run(target, hub, destination)["state"] == "reconciliation_required"
    assert len(executor) == 1


@pytest.mark.parametrize("change", ["in_flight", "open_session", "pending", "wrong_account", "receipt", "unknown_file", "destination", "excluded"])
def test_unsafe_import_does_not_reset_or_replay(completed, executor, change):
    source, destination, target, hub = completed
    root = source / "firstbook-private-writes"
    if change == "in_flight":
        value = ledger(source)
        value["in_flight"] = "1" * 64
        pool.worker.writer._save(root / "book-pool.json", value)
    elif change == "open_session":
        path = root / ("owned-session-" + "1" * 64 + ".json")
        pool.worker.writer._save(path, pool.worker.writer._load(path) | {"state": "open"})
    elif change == "pending":
        hub.next()
    elif change == "wrong_account":
        target["accounts"][0]["account_sha256"] = "c" * 64
    elif change == "receipt":
        next(iter(hub.jobs.values()))["job"]["providerReceiptDigest"] = "0" * 64
    elif change == "unknown_file":
        pool.worker.writer._save(root / "uncertain-dispatch.json", {"state": "write_dispatched"})
    elif change == "destination":
        start(destination, target)
    else:
        target["excluded_book_refs"] = ["1" * 64]
    before = snapshot(source)
    with pytest.raises((RuntimeError, ValueError)):
        transfer(completed)
    assert snapshot(source) == before and len(executor) == 1
    if change != "destination":
        assert not (destination / "firstbook-private-writes/book-pool.json").exists()


def test_partial_copy_stays_unusable_and_preserves_original(completed, monkeypatch):
    source, destination, target, hub = completed
    before = snapshot(source)
    save = pool.worker.writer._save
    def fail(path, value):
        if destination in path.parents and path.name.startswith("owned-session-"):
            raise OSError("disk-full")
        return save(path, value)
    monkeypatch.setattr(pool.worker.writer, "_save", fail)
    with pytest.raises(OSError, match="disk-full"):
        transfer(completed)
    assert snapshot(source) == before
    with pytest.raises(RuntimeError, match="custody_missing"):
        run(target, hub, destination)
    with pytest.raises(RuntimeError, match="destination_not_empty"):
        transfer(completed)


def test_snapshot_drift_is_rejected_before_copy(completed, monkeypatch):
    source, destination, target, hub = completed
    call = hub.call
    count = 0
    def drift(*args, **kwargs):
        nonlocal count
        count += 1
        value = call(*args, **kwargs)
        if count == 2:
            value["job"]["sourceDigest"] = "0" * 64
        return value
    monkeypatch.setattr(hub, "call", drift)
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        transfer(completed)
    assert not (destination / "firstbook-private-writes/book-pool.json").exists()


def test_source_cycle_lock_blocks_import(completed):
    with pool.runtime.intake.cycle._lease(completed[0]):
        with pytest.raises(RuntimeError, match="cycle_busy"):
            transfer(completed)


@pytest.mark.parametrize("relative", ["", "books"])
def test_source_writer_locks_block_import(completed, relative):
    root = completed[0] / "firstbook-private-writes"
    before = snapshot(completed[0])
    with migration._writer_lease(root / relative):
        with pytest.raises(RuntimeError, match="writer_busy"):
            transfer(completed)
    assert snapshot(completed[0]) == before
    assert not (completed[1] / "firstbook-private-writes/book-pool.json").exists()
