from __future__ import annotations

import copy
import hashlib
import json

import pytest

from scripts import firstbook_chapter_review as review
from scripts import firstbook_chapter_advance as advance
from scripts import firstbook_chapter_write as writer
from scripts import origin_chapter_worker as worker
from tests.test_firstbook_chapter_write import packet, draft, prepared
from tests.test_origin_chapter_worker import Hub, packet as hub_packet


EDITED = "Childhood\nNera wartet am Fenster. Die Wahl bleibt offen."


def save_original(data, root):
    binding = writer._binding(data)
    path = writer._record_path(writer._private_root(root), binding)
    result = writer._result(binding, draft())
    writer._save(path, {"binding": binding, "state": "chapter_review_required", "result": result})
    return path


@pytest.fixture
def surface(tmp_path, monkeypatch):
    path = save_original(packet(), tmp_path)
    observed = {**draft(), "text": EDITED}
    calls = []
    monkeypatch.setattr(writer, "_inspect", lambda *args: {**prepared(), "hasDraft": True})
    monkeypatch.setattr(writer.capture, "_observe", lambda *args: calls.append("capture") or dict(observed))
    monkeypatch.setattr(writer.capture, "_open_book", lambda *args: calls.append("open"))
    monkeypatch.setattr(writer.capture, "_read_draft", lambda *args: dict(observed))
    monkeypatch.setattr(writer.capture, "_click", lambda session, selector: calls.append(selector))
    return path, path.read_bytes(), observed, calls


def test_edited_capture_is_separate_private_and_read_only_with_cold_reuse(tmp_path, surface, monkeypatch):
    path, original, _, calls = surface
    digest = writer.capture._sha(EDITED)
    result = review.capture_reviewed_chapter(packet(), tmp_path, digest)
    assert result["text"] == EDITED and result["text_sha256"] == digest
    assert result["canon_approved"] is False and result["publication_authorized"] is False
    assert result["provider_generation_attempted"] is False
    assert result["binding"]["request_id"].startswith("review-")
    assert path.read_bytes() == original and calls == ["capture"]
    selected = review.retained(writer._binding(packet()), tmp_path, digest)
    assert selected[1].stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(writer, "_inspect", lambda *args: pytest.fail("immutable retry needs no browser"))
    assert review.capture_reviewed_chapter(packet(), tmp_path, digest)["reused_capture"] is True
    assert calls == ["capture"] and path.read_bytes() == original


def test_wrong_live_text_is_retained_as_observation_but_never_selected_or_recaptured(tmp_path, surface):
    path, original, _, calls = surface
    for _ in range(2):
        with pytest.raises(RuntimeError, match="draft_mismatch"):
            review.capture_reviewed_chapter(packet(), tmp_path, "f" * 64)
    assert calls == ["capture"] and path.read_bytes() == original


@pytest.mark.parametrize("change", ["source", "owner", "project", "pending", "advancing"])
def test_wrong_identity_or_unfinished_or_advancing_chapter_cannot_be_reselected(tmp_path, surface, change):
    path, original, _, calls = surface
    data = packet()
    if change in ("source", "owner", "project"):
        key = {"source": "source_packet_sha256", "owner": "account_sha256", "project": "provider_book_id"}[change]
        data[key] = "f" * 64 if change != "project" else "different-book"
    elif change == "pending":
        writer._save(path, {"binding": writer._binding(data), "state": "write_dispatched", "result": None})
    else:
        writer._save(path.with_suffix(".accept.json"), {"state": "advance_dispatched"})
    with pytest.raises(RuntimeError):
        review.capture_reviewed_chapter(data, tmp_path, writer.capture._sha(EDITED))
    assert not calls


def test_capture_while_generation_is_active_never_navigates(tmp_path, surface, monkeypatch):
    monkeypatch.setattr(writer, "_inspect", lambda *args: {"generating": True, "hasDraft": True})
    assert review.capture_reviewed_chapter(packet(), tmp_path, writer.capture._sha(EDITED))["render_status"] == "provider_busy"
    assert not surface[3]


def test_missing_original_and_invalid_selection_never_touch_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(writer.capture, "_observe", lambda *args: pytest.fail("no original admission"))
    with pytest.raises(ValueError, match="exact_text_digest"):
        review.capture_reviewed_chapter(packet(), tmp_path, "not-a-digest")
    with pytest.raises(RuntimeError, match="original_not_retained"):
        review.capture_reviewed_chapter(packet(), tmp_path, "f" * 64)


def test_capture_root_cannot_be_symlinked_to_another_store(tmp_path, surface):
    elsewhere = tmp_path / "other"
    elsewhere.mkdir(mode=0o700)
    (tmp_path / "firstbook-private-captures").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError, match="not_private"):
        review.capture_reviewed_chapter(packet(), tmp_path, writer.capture._sha(EDITED))
    assert not surface[3]


def test_edited_result_still_requires_exact_hub_text_receipt_and_live_provider_match(tmp_path, surface):
    path, original, observed, calls = surface
    digest = writer.capture._sha(EDITED)
    review.capture_reviewed_chapter(packet(), tmp_path, digest)
    _, selected_path = review.retained(writer._binding(packet()), tmp_path, digest)
    receipt = hashlib.sha256(selected_path.read_bytes()).hexdigest()
    calls.clear()
    with pytest.raises(RuntimeError, match="receipt_mismatch|acceptance_mismatch"):
        advance.advance_accepted_chapter(packet(), tmp_path, digest, hashlib.sha256(original).hexdigest())
    assert not calls
    observed["text"] = EDITED + " Changed later."
    with pytest.raises(RuntimeError, match="draft_changed"):
        advance.advance_accepted_chapter(packet(), tmp_path, digest, receipt)
    assert calls == ["open"]
    observed["text"] = EDITED
    assert advance.advance_accepted_chapter(packet(), tmp_path, digest, receipt)["render_status"] == "advance_dispatched"
    assert advance.advance_accepted_chapter(packet(), tmp_path, digest, receipt)["render_status"] == "reconciliation_required"
    assert sum("Approve & Next" in action for action in calls) == 1
    assert path.read_bytes() == original


def test_corrupt_capture_never_becomes_acceptance_or_new_capture(tmp_path, surface):
    digest = writer.capture._sha(EDITED)
    review.capture_reviewed_chapter(packet(), tmp_path, digest)
    captured, path = review.retained(writer._binding(packet()), tmp_path, digest)
    writer._save(path, {**captured, "canon_approved": True})
    with pytest.raises(RuntimeError, match="retained_binding_mismatch"):
        advance.advance_accepted_chapter(packet(), tmp_path, digest, hashlib.sha256(path.read_bytes()).hexdigest())
    assert surface[3] == ["capture"]


def prepare_hub_review(tmp_path):
    data = hub_packet()
    prepared_packet = {**data["prepared"], "request_id": data["work_id"]}
    original = save_original(prepared_packet, tmp_path)
    hub = Hub()
    hub.work["executionAdmission"] = data["execution_admission"]
    hub.work["job"]["state"] = "reconciliation_required"
    return data, hub, original


def test_connector_delivers_edited_text_without_writing_or_replacing_original_and_recovers_lost_reply(tmp_path, surface, monkeypatch):
    data, hub, original = prepare_hub_review(tmp_path)
    old_bytes = original.read_bytes()
    digest = writer.capture._sha(EDITED)
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("review cannot generate"))
    call = hub.call
    def lost(*args, **kwargs):
        result = call(*args, **kwargs)
        if len(args) > 1 and args[1] == "/complete":
            raise RuntimeError("lost_completion_reply")
        return result
    hub.call = lost
    with pytest.raises(RuntimeError, match="lost_completion_reply"):
        worker.run_once(data, hub, tmp_path, reviewed_draft_digest=digest)
    assert hub.work["job"]["draftText"] == EDITED
    selected = review.retained(writer._binding({**data["prepared"], "request_id": data["work_id"]}), tmp_path, digest)
    assert hub.work["job"]["providerReceiptDigest"] == hashlib.sha256(selected[1].read_bytes()).hexdigest()
    assert worker.run_once(data, hub, tmp_path, reviewed_draft_digest=digest)["state"] == "review_required"
    assert original.read_bytes() == old_bytes and surface[3] == ["capture"]
    assert sum(action == "/complete" for action, _ in hub.calls) == 1
    assert "readerAcceptedTextDigest" not in hub.work["job"]


def test_connector_cannot_overwrite_already_delivered_text_or_start_new_admission(tmp_path, surface):
    data, hub, _ = prepare_hub_review(tmp_path)
    digest = writer.capture._sha(EDITED)
    hub.work["job"].update(state="review_required", draftText="Old result", providerReceiptDigest="d" * 64)
    with pytest.raises(ValueError, match="immutable"):
        worker.run_once(data, hub, tmp_path, reviewed_draft_digest=digest)
    hub.work["job"].update(state="awaiting_authoring", draftText=None, providerReceiptDigest=None)
    hub.work["executionAdmission"] = None
    with pytest.raises(ValueError, match="existing_admission"):
        worker.run_once(data, hub, tmp_path, reviewed_draft_digest=digest)
    assert not surface[3] and all(action == "" for action, _ in hub.calls)


def test_capture_does_not_accept_provider_chapter_inventory_change(tmp_path, surface):
    surface[2]["chapterCount"] = 9
    with pytest.raises(RuntimeError, match="draft_mismatch"):
        review.capture_reviewed_chapter(packet(), tmp_path, writer.capture._sha(EDITED))


def test_connector_bounds_edited_text_before_hub_completion(tmp_path, surface):
    data, hub, _ = prepare_hub_review(tmp_path)
    surface[2]["text"] = "x" * 65537
    with pytest.raises(ValueError, match="result_oversized"):
        worker.run_once(data, hub, tmp_path, reviewed_draft_digest=writer.capture._sha(surface[2]["text"]))
    assert not any(action == "/complete" for action, _ in hub.calls)


@pytest.mark.parametrize("revision", [False, True])
def test_editorial_scaffold_cannot_be_delivered_by_exact_digest_selection(tmp_path, surface, monkeypatch, revision):
    text = ("A COUNTER–ARGUMENT emerged in the silence.\n\n"
            "The process required internal, actionable steps. First, observe; second, classify.")
    if revision:
        data, hub, original, digests = delivered_revision(tmp_path)
    else:
        data, hub, original = prepare_hub_review(tmp_path)
    original_bytes = original.read_bytes()
    before = copy.deepcopy(hub.work)
    surface[2]["text"] = text
    digest = writer.capture._sha(text)
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("no generation"))
    for _ in range(2):
        with pytest.raises(ValueError, match="^origin_worker_draft_needs_editorial_review$"):
            if revision:
                worker.revise_unaccepted_once(data, hub, tmp_path, **{**digests, "text_digest": digest})
            else:
                worker.run_once(data, hub, tmp_path, reviewed_draft_digest=digest)
    assert hub.work == before and original.read_bytes() == original_bytes
    assert all(action in ("", "/admit") for action, _ in hub.calls)
    assert surface[3] == ["capture"]
    binding = writer._binding({**data["prepared"], "request_id": data["work_id"]})
    assert review.retained(binding, tmp_path, digest)[0]["text"] == text


def delivered_revision(tmp_path):
    data, hub, original = prepare_hub_review(tmp_path)
    old_bytes = original.read_bytes()
    text = json.loads(old_bytes)["result"]["text"]
    digests = {"text_digest": writer.capture._sha(EDITED),
               "expected_receipt_digest": hashlib.sha256(old_bytes).hexdigest(),
               "expected_text_digest": writer.capture._sha(text)}
    hub.work["job"].update(state="review_required", draftText=text,
                           providerReceiptDigest=digests["expected_receipt_digest"])
    call = hub.call

    def revision(work_id, action="", body=None):
        if action == "/revise-unaccepted":
            assert body["sourceDigest"] == hub.work["job"]["sourceDigest"]
            assert body["executionAdmission"] == hub.work["executionAdmission"]
            assert hub.work["job"].get("readerAcceptedTextDigest") is None
            assert body["expectedProviderReceiptDigest"] == digests["expected_receipt_digest"]
            assert body["expectedTextDigest"] == digests["expected_text_digest"]
            hub.work["job"].update(draftText=body["draftText"], providerReceiptDigest=body["providerReceiptDigest"])
        return call(work_id, action, body)

    hub.call = revision
    return data, hub, original, digests


def test_unaccepted_revision_retains_both_versions_and_retries_without_generation(tmp_path, surface, monkeypatch):
    data, hub, original, digests = delivered_revision(tmp_path)
    old_bytes = original.read_bytes()
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("revision cannot generate"))
    call = hub.call

    def lost(work_id, action="", body=None):
        result = call(work_id, action, body)
        if action == "/revise-unaccepted":
            raise RuntimeError("lost_revision_reply")
        return result

    hub.call = lost
    with pytest.raises(RuntimeError, match="lost_revision_reply"):
        worker.revise_unaccepted_once(data, hub, tmp_path, **digests)
    hub.call = call
    assert worker.revise_unaccepted_once(data, hub, tmp_path, **digests)["state"] == "review_required"
    assert original.read_bytes() == old_bytes and surface[3] == ["capture"]
    assert hub.work["job"]["draftText"] == EDITED
    assert hub.work["job"].get("readerAcceptedTextDigest") is None
    assert all(action in ("", "/revise-unaccepted") for action, _ in hub.calls)
    selected = review.retained(writer._binding({**data["prepared"], "request_id": data["work_id"]}),
                               tmp_path, digests["text_digest"])
    assert hub.work["job"]["providerReceiptDigest"] == hashlib.sha256(selected[1].read_bytes()).hexdigest()
    # The normal polling path still cannot replace a delivered revision.
    with pytest.raises(ValueError, match="immutable"):
        worker.run_once(data, hub, tmp_path, reviewed_draft_digest=digests["expected_text_digest"])


@pytest.mark.parametrize("change", ["source", "owner", "admission", "receipt", "text", "accepted", "pending", "changed"])
def test_revision_rejects_stale_unowned_or_accepted_work_before_browser_capture(tmp_path, surface, change):
    data, hub, original, digests = delivered_revision(tmp_path)
    old_bytes = original.read_bytes()
    if change == "source":
        hub.work["job"]["sourceDigest"] = "f" * 64
    elif change == "owner":
        hub.work["workId"] = "f" * 64 + "." + "2" * 64
    elif change == "admission":
        hub.work["executionAdmission"] = "other"
    elif change == "receipt":
        digests["expected_receipt_digest"] = "f" * 64
    elif change == "text":
        digests["expected_text_digest"] = "f" * 64
    elif change == "accepted":
        hub.work["job"]["readerAcceptedTextDigest"] = digests["expected_text_digest"]
    elif change == "pending":
        hub.work["job"].update(state="reconciliation_required", draftText=None, providerReceiptDigest=None)
    else:
        hub.work["job"].update(draftText="Newer result", providerReceiptDigest="f" * 64)
    with pytest.raises(ValueError, match="binding_mismatch|revision_"):
        worker.revise_unaccepted_once(data, hub, tmp_path, **digests)
    assert not surface[3] and original.read_bytes() == old_bytes
    assert all(action == "" for action, _ in hub.calls)


def test_revision_cannot_deliver_oversized_text_or_capture_while_provider_busy(tmp_path, surface, monkeypatch):
    data, hub, original, digests = delivered_revision(tmp_path)
    monkeypatch.setattr(writer, "_inspect", lambda *a: {"generating": True})
    assert worker.revise_unaccepted_once(data, hub, tmp_path, **digests)["state"] == "provider_busy"
    assert not surface[3] and all(action == "" for action, _ in hub.calls)
    monkeypatch.setattr(writer, "_inspect", lambda *a: {**prepared(), "hasDraft": True})
    surface[2]["text"] = "x" * 65537
    digests["text_digest"] = writer.capture._sha(surface[2]["text"])
    with pytest.raises(ValueError, match="capture_changed"):
        worker.revise_unaccepted_once(data, hub, tmp_path, **digests)
    assert all(action == "" for action, _ in hub.calls)
