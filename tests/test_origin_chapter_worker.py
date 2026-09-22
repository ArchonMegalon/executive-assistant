from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest

from scripts import origin_chapter_worker as worker
from scripts import firstbook_chapter_write as writer


def packet():
    return {"work_id": "1" * 64 + "." + "2" * 64, "execution_admission": "approved-job-1",
            "approved_source": {"workspaceId": "workspace", "chapterId": "chapter", "locale": "de-DE"},
            "prepared": {"browser_session": "owned-worker", "account_sha256": "a" * 64,
                         "provider_book_id": "book-1", "book_title": "Nera", "chapter_title": "Childhood",
                         "chapter_number": 1, "source_packet_sha256": "b" * 64,
                         "narrative_locale": "de-DE", "generation_approved": True,
                         "expected_outline": [{"title": str(i), "description": "Accepted facts"} for i in range(3)]}}


class Hub:
    def __init__(self):
        self.calls = []
        self.work = {"workId": packet()["work_id"], "bookRef": "c" * 64, "executionAdmission": None,
                     "job": {"sourceDigest": "b" * 64, "source": packet()["approved_source"],
                             "provider": "first_book_ai", "state": "awaiting_authoring", "requiresReaderReview": True,
                             "affectsMechanics": False, "publicationAuthorized": False,
                             "draftText": None, "providerReceiptDigest": None}}

    def call(self, work_id, action="", body=None):
        assert work_id == packet()["work_id"]
        self.calls.append((action, body))
        if action == "/admit":
            first = self.work["executionAdmission"] is None
            self.work["executionAdmission"] = body["executionAdmission"]
            self.work["job"]["state"] = "reconciliation_required"
            return {"work": copy.deepcopy(self.work), "mayStartGeneration": first}
        if action == "/complete":
            self.work["job"].update(state="review_required", draftText=body["draftText"],
                                    providerReceiptDigest=body["providerReceiptDigest"])
        return copy.deepcopy(self.work)


def test_pending_worker_reuses_upstream_admission_without_new_permission(tmp_path, monkeypatch):
    hub = Hub()
    allowed = []
    def pending(prepared, root, *, allow_new_dispatch):
        assert prepared["request_id"] == packet()["work_id"]
        allowed.append(allow_new_dispatch)
        return {"render_status": "reconciliation_required"}
    monkeypatch.setattr(writer, "write_prepared_chapter", pending)
    assert worker.run_once(packet(), hub, tmp_path)["state"] == "reconciliation_required"
    assert worker.run_once(packet(), hub, tmp_path)["state"] == "reconciliation_required"
    assert allowed == [True, False]


def test_retained_provider_draft_returns_to_hub_and_completed_retry_skips_browser(tmp_path, monkeypatch):
    hub = Hub()
    binding = writer._binding({**packet()["prepared"], "request_id": packet()["work_id"]})
    result = writer._result(binding, {
        "origin": "https://app.firstbook.ai", "bookTitles": ["Nera"], "chapterTitle": "Childhood",
        "chapterNumber": 1, "chapterCount": 8, "surfaceCount": 1, "reviewRequired": True,
        "editing": False, "approveControl": 1, "text": "Nera waits."})
    path = tmp_path / "result.json"
    writer._save(path, {"binding": binding, "state": "chapter_review_required", "result": result})
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: {**result, "asset_path": str(path)})
    assert worker.run_once(packet(), hub, tmp_path)["state"] == "review_required"
    assert hub.work["job"]["draftText"] == "Nera waits."
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("no paid replay"))
    before = len(hub.calls)
    assert worker.run_once(packet(), hub, tmp_path)["state"] == "review_required"
    assert len(hub.calls) == before + 1


@pytest.mark.parametrize("key,value", [("sourceDigest", "c" * 64), ("source", {}),
                                       ("requiresReaderReview", False), ("affectsMechanics", True),
                                       ("publicationAuthorized", True), ("provider", "other")])
def test_hub_source_or_safety_drift_never_reaches_provider(tmp_path, monkeypatch, key, value):
    hub = Hub()
    hub.work["job"][key] = value
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("wrong source"))
    with pytest.raises(ValueError, match="binding_mismatch"):
        worker.run_once(packet(), hub, tmp_path)
    assert len(hub.calls) == 1


def test_unknown_admission_outcome_stops_before_provider(tmp_path, monkeypatch):
    hub = Hub()
    call = hub.call
    def fail_after_admit(*args, **kwargs):
        result = call(*args, **kwargs)
        if args[1:] and args[1] == "/admit":
            raise RuntimeError("lost_response")
        return result
    hub.call = fail_after_admit
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("no authority response"))
    with pytest.raises(RuntimeError, match="lost_response"):
        worker.run_once(packet(), hub, tmp_path)


@pytest.mark.parametrize("origin", ["https://external.example", "http://localhost:5089", "http://127.0.0.1:5089/x",
                                   "http://user:pass@127.0.0.1:5089", "http://127.0.0.1:5089/?token=x"])
def test_only_literal_local_listener_is_allowed_before_loading_token(tmp_path, origin):
    with pytest.raises(ValueError, match="loopback_listener"):
        worker.LocalHub(origin, tmp_path / "not-read")


def test_response_size_duplicate_json_and_redirects_are_rejected(tmp_path):
    key = tmp_path / "service-token"
    key.write_text("synthetic-worker-token-with-no-production-power")
    key.chmod(0o600)
    hub = worker.LocalHub("http://127.0.0.1:5089", key)
    class Response(io.BytesIO):
        status = 200
        headers = {}
    class Transport:
        def open(self, request, timeout):
            assert request.get_header("Authorization").startswith("Bearer ")
            return Response(b"x" * 512001)
    hub._http = Transport()
    with pytest.raises(RuntimeError, match="oversized"):
        hub.call(packet()["work_id"])
    with pytest.raises(ValueError, match="invalid_json"):
        worker._json(b'{"source":1,"source":2}')
    with pytest.raises(RuntimeError, match="redirect_rejected"):
        worker._NoRedirects().redirect_request(None, None, 302, "", {}, "https://outside.test")


def test_story_language_must_match_approved_source_before_hub_dispatch(tmp_path, monkeypatch):
    hub = Hub()
    changed = packet()
    changed["prepared"]["narrative_locale"] = "es-ES"
    with pytest.raises(ValueError, match="story_language_mismatch"):
        worker.run_once(changed, hub, tmp_path)
    assert not hub.calls


def test_reader_acceptance_must_bind_the_retained_draft_and_never_approve_from_worker(tmp_path, monkeypatch):
    hub = Hub()
    hub.work["executionAdmission"] = packet()["execution_admission"]
    hub.work["job"].update(state="review_required", draftText="Nera waits.", providerReceiptDigest="d" * 64,
                           readerAcceptedTextDigest="f" * 64)
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("reader acceptance does not dispatch"))
    with pytest.raises(ValueError, match="reader_acceptance_invalid"):
        worker.run_once(packet(), hub, tmp_path)
    hub.work["job"]["readerAcceptedTextDigest"] = worker.hashlib.sha256(b"Nera waits.").hexdigest()
    assert worker.run_once(packet(), hub, tmp_path)["state"] == "review_required"
    assert all(action == "" for action, _ in hub.calls)
