"""Recovery uses exact historical writer bytes, real intake/pool, fake Hub."""
import copy
import hashlib
import json

import pytest

from scripts import origin_custody_recovery as recovery
from tests.test_origin_chapter_intake import Queue, executor

pool, writer, worker = recovery.pool, recovery.writer, recovery.worker


def fixture(chapters=2):
    hub = Queue()
    prior, originals = None, []
    for number in range(1, chapters + 1):
        work = hub.first if number == 1 else hub.next(suffix=str(number + 1))
        source = worker.preparation._binding({"work_id": work["workId"], "book_ref": work["bookRef"],
            "account_sha256": "a" * 64, "source_packet_sha256": work["job"]["sourceDigest"],
            "approved_source": work["job"]["source"], "framework_generation_approved": True})
        if prior is None:
            prepared = worker.outline_preparation._prepared(source,
                {"provider_book_id": "existing-project", "book_title": "An existing book"},
                worker.outline_preparation._plan(source, 8, version=7))
            prepared["generation_approved"] = True
        else:
            prepared = worker.next_preparation._plan(source, prior, version=7)[1]["prepared"]
        binding = writer._binding(prepared)
        prose = f"Chapter {number}: retained full synthetic prose."
        result = writer._result(binding, {"origin": "https://app.firstbook.ai", "bookTitles": [binding["book_title"]],
            "chapterTitle": binding["chapter_title"], "chapterNumber": number, "chapterCount": 8,
            "surfaceCount": 1, "text": prose, "reviewRequired": True, "editing": False, "approveControl": 1})
        record = {"binding": binding, "state": "chapter_review_required", "result": result}
        raw = json.dumps(record, ensure_ascii=False).encode()
        originals.append(raw)
        work["executionAdmission"] = f"original-admission-{number}"
        work["job"].update(state="review_required", draftText=prose,
            providerReceiptDigest=hashlib.sha256(raw).hexdigest(), readerAcceptedTextDigest=writer.capture._sha(prose))
        prior = prepared
    config = {"schema": pool._SERVICE_SCHEMA, "approval_id": "existing-books-recovery", "approved": True,
        "maximum_new_books": 1, "maximum_chapters_per_book": 100, "source_scope": "consented_origin",
        "expires_at": None, "excluded_book_refs": ["f" * 64], "accounts": [{"profile_id": "chrome_local_12345",
            "profile_use_approved": True, "account_sha256": "a" * 64, "maximum_new_books": 1}]}
    book = {"book_ref": work["bookRef"], "head_work_id": work["workId"], "profile_id": "chrome_local_12345",
        "account_sha256": "a" * 64, "provider_book_id": "existing-project", "book_title": "An existing book",
        "chapter_number": chapters, "chapter_count": 8, "text_sha256": work["job"]["readerAcceptedTextDigest"],
        "receipt_sha256": work["job"]["providerReceiptDigest"], "capture_sha256": "b" * 64,
        "review_required": True, "generating": False, "editing": False}
    plan = {"schema": recovery._SCHEMA, "configuration": config, "observed_at": 1000,
        "stopped_executor_id": "c" * 64, "executor_stopped": True, "browsers_closed": True, "books": [book]}
    return hub, plan, originals


def restore(tmp_path, hub, plan):
    return recovery.recover_completed(lambda: copy.deepcopy(plan), hub, tmp_path / "recovered", now=lambda: 1001)


def test_exact_receipts_and_original_admissions_survive_cold_idle(tmp_path, monkeypatch):
    hub, plan, originals = fixture()
    monkeypatch.setattr(writer.capture, "_browser", lambda *a: pytest.fail("Recovery never calls a browser"))
    result = restore(tmp_path, hub, plan)
    root = tmp_path / "recovered/firstbook-private-writes"
    state = writer._load(root / ("intake-" + plan["books"][0]["book_ref"] + ".json"))
    for entry, expected, work in zip(state["jobs"], originals, hub.jobs.values()):
        assert writer._record_path(root, writer._binding(entry["prepared"])).read_bytes() == expected
        assert entry["packet"]["execution_admission"] == work["executionAdmission"]
        assert "outline_activation_approved" not in entry["packet"]["setup"]
    assert not list(root.glob("owned-session-*")) and not list(root.glob("*.accept.json"))
    assert result["exact_completed_receipts"] == 2 and not result["provider_dispatch"]
    before = copy.deepcopy(hub.jobs)
    for _ in range(2):
        observed = pool.run_once(lambda: plan["configuration"], hub, tmp_path / "recovered", now=lambda: 1001)
        assert observed["book_states"] == ["idle"] and observed["remaining_books"] == 0
    assert hub.jobs == before and all(action in ("", "pending") for action, _ in hub.calls)
    assert writer._load(root / "book-pool.json")["new_book_admission_exhausted"] is True
    assert all(p.stat().st_mode & 0o077 == 0 for p in root.rglob("*.json"))


def test_only_a_new_unadmitted_successor_can_progress(tmp_path, executor):
    hub, plan, _ = fixture()
    restore(tmp_path, hub, plan)
    successor = hub.next(suffix="4")
    # Provider execution is simulated by the existing fixture; real pool/intake
    # must retain the old project's exact predecessor and reserve no new credit.
    from tests.test_origin_chapter_runtime import Browser
    pool.run_once(lambda: plan["configuration"], hub, tmp_path / "recovered", browser=Browser(), now=lambda: 1001)
    assert len(executor) == 1 and executor[0]["work_id"] == successor["workId"]
    assert executor[0]["previous"]["prepared"]["provider_book_id"] == "existing-project"
    assert "maximum_book_credits" not in executor[0]["setup"]


@pytest.mark.parametrize("change", ["receipt", "text", "source", "account", "project", "title", "count",
    "unaccepted", "uncertain", "missing-admission", "wrong-owner", "chain", "pending"])
def test_mismatch_and_uncertainty_never_create_runnable_custody(tmp_path, change):
    hub, plan, _ = fixture()
    head = list(hub.jobs.values())[-1]
    book = plan["books"][0]
    if change == "receipt": head["job"]["providerReceiptDigest"] = "0" * 64
    if change == "text": head["job"]["draftText"] += "changed"
    if change == "source": head["job"]["source"]["facts"][0]["text"] = "changed"
    if change == "account": book["account_sha256"] = "1" * 64
    if change == "project": book["provider_book_id"] = "another-project"
    if change == "title": book["book_title"] = "Changed"
    if change == "count": book["chapter_count"] = 9
    if change == "unaccepted": head["job"]["readerAcceptedTextDigest"] = None
    if change == "uncertain": head["job"]["state"] = "reconciliation_required"
    if change == "missing-admission": head["executionAdmission"] = None
    if change == "wrong-owner": head["workId"] = "0" * 64 + head["workId"][64:]
    if change == "chain": head["previousWorkId"] = head["workId"]
    if change == "pending": hub.next(suffix="4")
    with pytest.raises((RuntimeError, ValueError)):
        restore(tmp_path, hub, plan)
    assert not (tmp_path / "recovered").exists()
    assert all(action in ("", "pending") for action, _ in hub.calls)


@pytest.mark.parametrize("change", ["running", "browser", "stale", "future", "extra-credit", "duplicate"])
def test_unverified_operator_observation_and_new_allowance_rejected(tmp_path, change):
    hub, plan, _ = fixture()
    if change == "running": plan["executor_stopped"] = False
    if change == "browser": plan["browsers_closed"] = False
    if change == "stale": plan["observed_at"] = -7000
    if change == "future": plan["observed_at"] = 1002
    if change == "extra-credit":
        plan["configuration"]["maximum_new_books"] = 2
        plan["configuration"]["accounts"][0]["maximum_new_books"] = 2
    if change == "duplicate":
        plan["books"].append(copy.deepcopy(plan["books"][0]))
        plan["configuration"]["maximum_new_books"] = 2
        plan["configuration"]["accounts"][0]["maximum_new_books"] = 2
    with pytest.raises(ValueError): restore(tmp_path, hub, plan)
    assert not hub.calls and not (tmp_path / "recovered").exists()


def test_existing_destination_and_unknown_fences_are_never_replaced(tmp_path):
    hub, plan, _ = fixture()
    target = tmp_path / "recovered"
    target.mkdir()
    unknown = target / "unknown-write.json"
    unknown.write_text("uncertain")
    with pytest.raises(FileExistsError): restore(tmp_path, hub, plan)
    assert unknown.read_text() == "uncertain" and list(target.iterdir()) == [unknown]


def test_hub_change_during_final_commit_leaves_no_runnable_pool(tmp_path):
    hub, plan, _ = fixture()
    original = hub.call
    def changed(work_id, *args):
        value = original(work_id, *args)
        if (tmp_path / "recovered").exists(): value["executionAdmission"] = "changed"
        return value
    hub.call = changed
    with pytest.raises(RuntimeError, match="snapshot_changed"): restore(tmp_path, hub, plan)
    assert not (tmp_path / "recovered/firstbook-private-writes/book-pool.json").exists()


def test_interrupted_local_write_leaves_no_pool_and_cannot_retry_in_place(tmp_path, monkeypatch):
    hub, plan, _ = fixture()
    original = writer._save
    def fail(path, value, **kwargs):
        if path.name.startswith("intake-"): raise OSError("disk_write_failed")
        original(path, value, **kwargs)
    monkeypatch.setattr(writer, "_save", fail)
    with pytest.raises(OSError, match="disk_write_failed"): restore(tmp_path, hub, plan)
    assert not (tmp_path / "recovered/firstbook-private-writes/book-pool.json").exists()
    with pytest.raises(FileExistsError): restore(tmp_path, hub, plan)
