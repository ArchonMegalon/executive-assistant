from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest

from scripts import origin_chapter_worker as worker
from scripts import firstbook_chapter_write as writer
from scripts import firstbook_project_prepare as prepare
from scripts import firstbook_outline_prepare as outline


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
            if "editorial" in body:
                self.work["job"]["editorial"] = copy.deepcopy(body["editorial"])
        return copy.deepcopy(self.work)


def setup_packet(hub):
    source = {"workspaceId": "workspace", "chapterId": "chapter", "chapterDigest": "f" * 64,
              "acceptedDecisionId": "choice", "locale": "de-DE", "runnerName": "Nera",
              "facts": [{"factId": "fact", "decisionId": "choice", "text": "Nera is an elf."}]}
    hub.work["job"]["source"] = source
    return {"work_id": packet()["work_id"], "execution_admission": packet()["execution_admission"],
            "approved_source": source, "setup": {"browser_session": "owned-setup", "account_sha256": "a" * 64,
                "source_packet_sha256": "b" * 64, "framework_generation_approved": True}}


def test_setup_receives_hub_book_identity_only_after_execution_admission(tmp_path, monkeypatch):
    hub = Hub()
    data = setup_packet(hub)
    calls = []
    def setup(value, root, *, allow_new_dispatch):
        assert value["book_ref"] == hub.work["bookRef"]
        assert value["approved_source"] == hub.work["job"]["source"]
        assert hub.work["executionAdmission"] == data["execution_admission"]
        calls.append(allow_new_dispatch)
        return {"state": "framework_dispatched" if allow_new_dispatch else "reconciliation_required"}
    monkeypatch.setattr(prepare, "prepare_framework", setup)
    assert worker.prepare_once(data, hub, tmp_path)["state"] == "framework_dispatched"
    assert worker.prepare_once(data, hub, tmp_path)["state"] == "reconciliation_required"
    assert calls == [True, False]
    assert not any(action == "/complete" for action, _ in hub.calls)


def test_setup_with_changed_source_never_dispatches(tmp_path, monkeypatch):
    hub = Hub()
    data = setup_packet(hub)
    data["approved_source"] = {**data["approved_source"], "runnerName": "Someone else"}
    monkeypatch.setattr(prepare, "prepare_framework", lambda *a, **k: pytest.fail("wrong source"))
    with pytest.raises(ValueError, match="binding_mismatch"):
        worker.prepare_once(data, hub, tmp_path)
    assert len(hub.calls) == 1


@pytest.mark.parametrize("approved,state,expected", [
    (False, "framework_bound_needs_outline_review", False),
    (True, "framework_dispatched", False),
    (True, "framework_bound_needs_outline_review", True),
])
def test_outline_activation_needs_separate_local_approval_and_bound_project(tmp_path, monkeypatch, approved, state, expected):
    hub = Hub()
    data = setup_packet(hub)
    data["setup"].update(outline_activation_approved=approved, maximum_book_credits=1)
    monkeypatch.setattr(prepare, "prepare_framework", lambda *a, **k: {"state": state})
    activations = []
    def activate(value, root):
        assert hub.work["executionAdmission"] == data["execution_admission"]
        assert value["book_ref"] == hub.work["bookRef"]
        assert value["approved_source"] == hub.work["job"]["source"]
        assert value["maximum_book_credits"] == 1
        activations.append(value)
        return {"state": "activation_dispatched"}
    monkeypatch.setattr(worker.outline_preparation, "prepare_first_chapter", activate)
    result = worker.prepare_once(data, hub, tmp_path)
    assert bool(activations) is expected
    assert result["state"] == ("activation_dispatched" if expected else state)
    assert not any(action == "/complete" for action, _ in hub.calls)


def test_setup_lost_admission_does_not_create_provider_book(tmp_path, monkeypatch):
    hub = Hub()
    data = setup_packet(hub)
    call = hub.call
    def lost(*args, **kwargs):
        value = call(*args, **kwargs)
        if args[1:] and args[1] == "/admit":
            raise RuntimeError("lost_admission")
        return value
    hub.call = lost
    monkeypatch.setattr(prepare, "prepare_framework", lambda *a, **k: pytest.fail("unknown admission"))
    with pytest.raises(RuntimeError, match="lost_admission"):
        worker.prepare_once(data, hub, tmp_path)


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


def retained_setup(tmp_path, hub, *, legacy=False):
    data = setup_packet(hub)
    binding = prepare._binding({**data["setup"], "work_id": data["work_id"],
        "book_ref": hub.work["bookRef"], "approved_source": data["approved_source"]})
    provider = {"provider_book_id": "book-1", "book_title": "Nera"}
    root = writer._private_root(tmp_path)
    writer._save(root / ("setup-" + binding["book_ref"] + ".json"), {
        "binding": binding, "plan": prepare._plan(binding), "state": "framework_dispatched", "provider": provider})
    plan = outline._plan(binding, 8, legacy=legacy)
    path = root / ("outline-" + binding["book_ref"] + ".json")
    writer._save(path, {"binding": binding, "provider": provider, "plan": plan,
        "before": [], "state": "first_chapter_prepared", "browser_session": "owned-setup", "page_epoch": 1000})
    # Framework/credit preparation already consumed the one Hub admission.
    hub.call(data["work_id"], "/admit", {
        "sourceDigest": hub.work["job"]["sourceDigest"], "executionAdmission": data["execution_admission"]})
    data["prepared"] = {**outline._prepared(binding, provider, plan),
        "generation_approved": True, "browser_session": "owned-first-chapter"}
    return data, path


def prepared_browser(data, monkeypatch):
    observed = {"origin": "https://app.firstbook.ai", "chapterTitle": data["prepared"]["chapter_title"],
        "chapterNumber": 1, "chapterCount": 8, "outlineCount": 1, "outline": data["prepared"]["expected_outline"],
        "writeCount": 1, "writeEnabled": True, "includedInPlan": True,
        "briefCount": 1, "briefSelected": True, "hasDraft": False, "generating": False}
    calls = []
    monkeypatch.setattr(writer, "_inspect", lambda *args: dict(observed))
    monkeypatch.setattr(writer.capture, "_open_book", lambda *args: calls.append("open"))
    monkeypatch.setattr(writer.capture, "_click", lambda session, selector: calls.append(selector))
    monkeypatch.setattr(writer.capture, "_read_draft", lambda *args: {
        **observed, "bookTitles": ["Nera"], "surfaceCount": 1, "reviewRequired": True,
        "editing": False, "approveControl": 1, "text": "Nera wartet. Die nächste Wahl bleibt offen."})
    return observed, calls


@pytest.mark.parametrize("legacy", [False, True])
def test_completed_setup_can_start_first_chapter_once_under_same_hub_admission(tmp_path, monkeypatch, legacy):
    hub = Hub()
    data, _ = retained_setup(tmp_path, hub, legacy=legacy)
    observed, calls = prepared_browser(data, monkeypatch)
    assert worker.run_once(data, hub, tmp_path)["state"] == "generation_dispatched"
    assert worker.run_once(data, hub, tmp_path)["state"] == "reconciliation_required"
    observed["hasDraft"] = True
    assert worker.run_once(data, hub, tmp_path)["state"] == "review_required"
    previous = list(calls)
    assert worker.run_once(data, hub, tmp_path)["state"] == "review_required"
    assert calls == previous
    assert sum("Write Chapter" in action for action in calls) == 1
    assert not any("Start writing my book" in action or "Approve" in action for action in calls)
    assert hub.work["executionAdmission"] == data["execution_admission"]


def test_first_chapter_handoff_never_replays_an_uncertain_write(tmp_path, monkeypatch):
    hub = Hub()
    data, _ = retained_setup(tmp_path, hub)
    _, calls = prepared_browser(data, monkeypatch)
    def uncertain(session, selector):
        calls.append(selector)
        if "Write Chapter" in selector:
            raise RuntimeError("lost_provider_response")
    monkeypatch.setattr(writer.capture, "_click", uncertain)
    with pytest.raises(RuntimeError, match="lost_provider_response"):
        worker.run_once(data, hub, tmp_path)
    assert worker.run_once(data, hub, tmp_path)["state"] == "reconciliation_required"
    assert sum("Write Chapter" in action for action in calls) == 1


@pytest.mark.parametrize("change", ["missing", "credit_dispatched", "editing", "source", "provider", "work", "outline", "chapter"])
def test_first_chapter_handoff_requires_exact_completed_preparation(tmp_path, monkeypatch, change):
    hub = Hub()
    data, path = retained_setup(tmp_path, hub)
    _, calls = prepared_browser(data, monkeypatch)
    record = writer._load(path)
    if change == "missing":
        path.unlink()
    elif change in ("credit_dispatched", "editing"):
        writer._save(path, {**record, "state": change})
    elif change == "source":
        record["binding"]["approved_source"]["runnerName"] = "Other runner"
        writer._save(path, record)
    elif change == "provider":
        data["prepared"]["provider_book_id"] = "other-book"
    elif change == "work":
        record["binding"]["work_id"] = "e" * 64 + "." + "f" * 64
        writer._save(path, record)
    elif change == "outline":
        data["prepared"]["expected_outline"][0]["description"] = "Invented new future."
    else:
        data["prepared"]["chapter_number"] = 2
    if change == "chapter":
        with pytest.raises(ValueError, match="previous_chapter_required"):
            worker.run_once(data, hub, tmp_path)
    elif change in ("missing", "credit_dispatched", "editing"):
        assert worker.run_once(data, hub, tmp_path)["state"] == "reconciliation_required"
    else:
        with pytest.raises(RuntimeError, match="binding_mismatch|handoff_mismatch"):
            worker.run_once(data, hub, tmp_path)
        assert not (path.parent / "books" / (hub.work["bookRef"] + ".json")).exists()
    assert not calls


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


def test_analytical_provider_draft_stays_private_without_replaying_generation(tmp_path, monkeypatch):
    hub = Hub()
    data, _ = retained_setup(tmp_path, hub)
    observed, calls = prepared_browser(data, monkeypatch)
    text = ("An opposing counter-argument emerged during the observation.\n\n"
            "Readiness required actionable, methodical steps. First, isolate the detail; "
            "second, assess the baseline; third, categorize the result.")
    read_draft = writer.capture._read_draft
    monkeypatch.setattr(writer.capture, "_read_draft", lambda *args: {**read_draft(*args), "text": text})
    assert worker.run_once(data, hub, tmp_path)["state"] == "generation_dispatched"
    observed["hasDraft"] = True
    for _ in range(2):
        with pytest.raises(ValueError, match="^origin_worker_draft_needs_editorial_review$"):
            worker.run_once(data, hub, tmp_path)
    binding = writer._binding({**data["prepared"], "request_id": data["work_id"]})
    retained = writer._load(writer._record_path(writer._private_root(tmp_path), binding))
    assert retained["result"]["text"] == text
    assert retained["state"] == "chapter_review_required"
    assert hub.work["job"]["draftText"] is None
    assert hub.work["job"]["state"] == "reconciliation_required"
    assert not any(action == "/complete" for action, _ in hub.calls)
    assert sum("Write Chapter" in action for action in calls) == 1
    assert not any("Approve" in action or "Rewrite" in action for action in calls)


@pytest.mark.parametrize("text", [
    "Nera waited by the window. The next choice was hers.",
    "Nera whispered a counter-argument, then stepped away from the window.",
    "Nera wrote actionable steps in her notebook, then shut it and left.",
    "Nera hörte die Schritte im Hof. Sie ließ das Fenster offen.",
])
def test_editorial_screen_does_not_treat_isolated_words_as_nonfiction(text):
    assert worker._require_story_draft(text) is None


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


@pytest.mark.parametrize("hostname", ["", "https://chummer.run", "chummer.run:5089", "chummer.run/path",
    "chummer.run\r\nAuthorization: stolen", "user@chummer.run", "-chummer.run", "chummer..run",
    "chummer.run ", "x" * 64 + ".run", "a." * 127 + "a"])
def test_virtual_host_is_a_bounded_hostname_before_loading_token(tmp_path, hostname):
    with pytest.raises(ValueError, match="invalid_host"):
        worker.LocalHub("http://127.0.0.1:5089", tmp_path / "not-read", host=hostname)


def test_virtual_host_does_not_allow_remote_connection(tmp_path):
    with pytest.raises(ValueError, match="loopback_listener"):
        worker.LocalHub("http://chummer.run:5089", tmp_path / "not-read", host="chummer.run")


def test_private_loopback_listener_accepts_explicit_host_without_changing_connection(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    token = "synthetic-private-worker-token-not-production"
    key = tmp_path / "service-token"
    key.write_text(token)
    key.chmod(0o600)
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append((self.headers.get("Host"), self.headers.get("Authorization"), self.path))
            valid = self.headers.get("Host") == "chummer.run" and self.headers.get("Authorization") == "Bearer " + token
            body = b'{"ok":true}' if valid else b'{"error":"Invalid Hostname"}'
            self.send_response(200 if valid else 400)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with pytest.raises(RuntimeError, match="hub_http_400"):
                worker.LocalHub(origin, key).call(packet()["work_id"])
            assert worker.LocalHub(origin, key, host="chummer.run").call(packet()["work_id"]) == {"ok": True}
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert len(observed) == 2
    assert observed[-1] == ("chummer.run", "Bearer " + token, worker._PREFIX + packet()["work_id"])


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
