import hashlib
import json

import pytest

from scripts import firstbook_chapter_advance as advance
from scripts import firstbook_chapter_write as writer
from scripts import origin_chapter_worker as worker
from tests.test_firstbook_chapter_write import packet, draft, prepared
from tests.test_origin_chapter_worker import Hub, packet as hub_packet


@pytest.fixture
def retained(tmp_path, monkeypatch):
    binding = writer._binding(packet())
    root = writer._private_root(tmp_path)
    result = writer._result(binding, draft())
    path = writer._record_path(root, binding)
    writer._save(path, {"binding": binding, "state": "chapter_review_required", "result": result})
    actions = []
    monkeypatch.setattr(writer.capture, "_open_book", lambda *a: actions.append("open"))
    monkeypatch.setattr(writer.capture, "_read_draft", lambda *a: draft())
    monkeypatch.setattr(writer.capture, "_click", lambda s, target: actions.append(target))
    monkeypatch.setattr(writer, "_inspect", lambda *a: {**prepared(), "hasDraft": True})
    return result["text_sha256"], hashlib.sha256(path.read_bytes()).hexdigest(), actions, path


def test_accepted_chapter_advances_once_and_recovers_after_lost_response(tmp_path, retained, monkeypatch):
    text, receipt, actions, path = retained
    def click(session, selector):
        fence = json.loads(path.with_suffix(".accept.json").read_text())
        assert fence["state"] == "advance_dispatched"
        actions.append(selector)
        raise RuntimeError("lost_reply")
    monkeypatch.setattr(writer.capture, "_click", click)
    with pytest.raises(RuntimeError, match="lost_reply"):
        advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)
    assert advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)["render_status"] == "reconciliation_required"
    monkeypatch.setattr(writer, "_inspect", lambda *a: {**prepared(), "chapterNumber": 2})
    result = advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)
    assert result["render_status"] == "next_chapter_observed"
    assert result["next_chapter_generation_attempted"] is False
    before = list(actions)
    assert advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)["render_status"] == "next_chapter_observed"
    assert actions == before
    assert sum("Approve & Next" in item for item in actions) == 1


def test_missing_or_mismatched_acceptance_receipt_and_changed_live_draft_do_not_click(tmp_path, retained, monkeypatch):
    text, receipt, actions, _ = retained
    with pytest.raises(ValueError, match="missing"):
        advance.advance_accepted_chapter(packet(), tmp_path, "", receipt)
    with pytest.raises(RuntimeError, match="acceptance_mismatch"):
        advance.advance_accepted_chapter(packet(), tmp_path, "f" * 64, receipt)
    with pytest.raises(RuntimeError, match="receipt_mismatch"):
        advance.advance_accepted_chapter(packet(), tmp_path, text, "f" * 64)
    assert not actions
    monkeypatch.setattr(writer.capture, "_read_draft", lambda *a: {**draft(), "text": "Changed after review"})
    with pytest.raises(RuntimeError, match="draft_changed"):
        advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)
    assert actions == ["open"]


def test_fence_failure_prevents_approval_and_pending_generation_is_not_interrupted(tmp_path, retained, monkeypatch):
    text, receipt, actions, _ = retained
    monkeypatch.setattr(writer, "_inspect", lambda *a: {"generating": True})
    assert advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)["render_status"] == "provider_busy"
    assert not actions
    monkeypatch.setattr(writer, "_inspect", lambda *a: prepared())
    def disk_full(*a):
        raise OSError("disk_full")
    monkeypatch.setattr(writer, "_save", disk_full)
    with pytest.raises(OSError, match="disk_full"):
        advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)
    assert actions == ["open"]


def test_last_chapter_never_enters_unverified_finish_or_publication_flow(tmp_path, retained, monkeypatch):
    text, _, actions, path = retained
    result = writer._result(writer._binding(packet()), {**draft(), "chapterCount": 1})
    writer._save(path, {"binding": writer._binding(packet()), "state": "chapter_review_required", "result": result})
    receipt = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(writer.capture, "_read_draft", lambda *a: {**draft(), "chapterCount": 1})
    assert advance.advance_accepted_chapter(packet(), tmp_path, text, receipt)["render_status"] == "final_chapter_retained"
    assert actions == ["open"]


def test_connector_reads_hub_acceptance_never_treats_generation_as_approval(tmp_path, monkeypatch):
    hub = Hub()
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("advance cannot generate"))
    seen = []
    monkeypatch.setattr(advance, "advance_accepted_chapter", lambda *args: seen.append(args) or {"render_status": "advance_dispatched"})
    assert worker.run_once(hub_packet(), hub, tmp_path, advance_accepted=True)["state"] == "awaiting_reader_acceptance"
    hub.work["executionAdmission"] = hub_packet()["execution_admission"]
    hub.work["job"].update(state="review_required", draftText="Nera waits.", providerReceiptDigest="d" * 64)
    assert worker.run_once(hub_packet(), hub, tmp_path, advance_accepted=True)["state"] == "awaiting_reader_acceptance"
    assert not seen
    hub.work["job"]["readerAcceptedTextDigest"] = hashlib.sha256(b"Nera waits.").hexdigest()
    assert worker.run_once(hub_packet(), hub, tmp_path, advance_accepted=True)["state"] == "advance_dispatched"
    assert len(seen) == 1 and all(action == "" for action, _ in hub.calls)
