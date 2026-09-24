import copy
import hashlib
import json

import pytest

from scripts import origin_chapter_intake as intake
from tests.test_origin_chapter_worker import Hub, setup_packet
from tests.test_origin_chapter_worker import retained_setup, prepared_browser


class Queue:
    def __init__(self):
        first = Hub()
        setup_packet(first)
        first.work["job"]["requestId"] = "first-request"
        self.first = copy.deepcopy(first.work)
        self.jobs = {self.first["workId"]: self.first}
        self.calls = []

    def pending(self, book_ref):
        self.calls.append(("pending", book_ref))
        return copy.deepcopy([w for w in self.jobs.values() if w["bookRef"] == book_ref
                              and w["job"]["state"] != "review_required"])

    def call(self, work_id, action="", body=None):
        self.calls.append((action, work_id))
        work = self.jobs[work_id]
        if action == "/admit":
            first = work["executionAdmission"] is None
            assert first or work["executionAdmission"] == body["executionAdmission"]
            work["executionAdmission"] = body["executionAdmission"]
            work["job"]["state"] = "reconciliation_required"
            return {"work": copy.deepcopy(work), "mayStartGeneration": first}
        if action == "/complete":
            work["job"].update(state="review_required", draftText="A fictional chapter.", providerReceiptDigest="e" * 64)
        return copy.deepcopy(work)

    def next(self, *, accepted=True, suffix="3"):
        old = list(self.jobs.values())[-1]
        text_digest = hashlib.sha256(old["job"]["draftText"].encode()).hexdigest()
        old["job"]["readerAcceptedTextDigest"] = text_digest if accepted else None
        new = copy.deepcopy(old)
        new.update(workId=old["workId"][:65] + suffix * 64, executionAdmission=None, previousWorkId=old["workId"])
        new["job"].update(requestId="request-" + suffix, sourceDigest=suffix * 64, state="awaiting_authoring",
            draftText=None, providerReceiptDigest=None, readerAcceptedTextDigest=None,
            previous={"requestId": old["job"]["requestId"], "sourceDigest": old["job"]["sourceDigest"],
                "providerReceiptDigest": old["job"]["providerReceiptDigest"], "textDigest": text_digest})
        new["job"]["source"].update(chapterId="chapter-" + suffix, acceptedDecisionId="decision-" + suffix)
        new["job"]["source"]["facts"].append({"factId": "fact-" + suffix, "decisionId": "decision-" + suffix,
            "text": "Chose the next confirmed stage."})
        self.jobs[new["workId"]] = new
        return new


def admission(hub, limit=3):
    return {"schema": intake._SCHEMA, "approved": True, "book_ref": hub.first["bookRef"],
        "first_work_id": hub.first["workId"], "account_sha256": "a" * 64, "workspace_id": "workspace",
        "locale": "de-DE", "browser_session": "owned-browser", "expires_at": 1100,
        "maximum_chapters": limit, "maximum_book_credits": 1}


def run(data, hub, root):
    return intake.run_once(data, hub, root, now=lambda: 1000)


@pytest.fixture
def executor(monkeypatch):
    packets = []
    def step(packet, hub, root):
        work = hub.call(packet["work_id"])
        intake.worker._validate_work(work, packet, preparing=True)
        if work["job"]["state"] != "review_required":
            path = intake.worker.writer._private_root(root) / ("intake-" + work["bookRef"] + ".json")
            saved = intake.worker.writer._load(path)
            assert saved["jobs"][-1]["packet"]["execution_admission"] == packet["execution_admission"]
            hub.call(packet["work_id"], "/admit", {"executionAdmission": packet["execution_admission"]})
            hub.call(packet["work_id"], "/complete", {})
        packets.append(copy.deepcopy(packet))
        return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}
    def retained(packet, book_ref, root):
        return {"request_id": packet["work_id"], "account_sha256": packet["setup"]["account_sha256"],
            "provider_book_id": "book-1", "book_title": "Nera", "chapter_title": packet["approved_source"]["chapterId"],
            "chapter_number": packet.get("previous", {}).get("prepared", {}).get("chapter_number", 0) + 1,
            "source_packet_sha256": packet["setup"]["source_packet_sha256"], "narrative_locale": "de-DE",
            "expected_outline": [{"title": str(i), "description": "Confirmed facts"} for i in range(3)]}
    monkeypatch.setattr(intake.cycle, "_step", step)
    monkeypatch.setattr(intake.cycle, "retained_preparation", retained)
    return packets


def test_queue_to_three_chapters_retains_constant_size_predecessor_and_stops_at_budget(tmp_path, executor):
    hub = Queue()
    data = admission(hub)
    assert run(data, hub, tmp_path)["state"] == "review_required"
    assert hub.first["job"].get("readerAcceptedTextDigest") is None
    assert run(data, hub, tmp_path)["state"] == "idle"
    hub.next()
    assert run(data, hub, tmp_path)["state"] == "review_required"
    hub.next(suffix="4")
    assert run(data, hub, tmp_path)["state"] == "review_required"
    assert run(data, hub, tmp_path)["state"] == "chapter_limit_reached"
    assert len(executor) == 3
    assert "maximum_book_credits" not in executor[1]["setup"]
    assert "previous" not in executor[2]["previous"]
    assert executor[2]["previous"]["prepared"]["chapter_number"] == 2
    assert sum(action == "/admit" for action, _ in hub.calls) == 3


@pytest.mark.parametrize("key,value", [("approved", False), ("expires_at", 1000), ("expires_at", 900000),
    ("maximum_book_credits", 2), ("maximum_book_credits", True), ("maximum_chapters", 0),
    ("maximum_chapters", 101), ("account_sha256", "bad"), ("browser_session", "../bad"), ("locale", "xx")])
def test_invalid_admission_does_not_read_hub_or_spend(tmp_path, executor, key, value):
    hub = Queue()
    data = admission(hub)
    data[key] = value
    with pytest.raises(ValueError): run(data, hub, tmp_path)
    assert hub.calls == executor == []


def test_exact_reader_acceptance_is_required_before_retaining_next_dispatch(tmp_path, executor):
    hub = Queue()
    data = admission(hub)
    run(data, hub, tmp_path)
    hub.next(accepted=False)
    with pytest.raises(ValueError, match="predecessor_binding_mismatch"):
        run(data, hub, tmp_path)
    assert len(executor) == 1
    assert sum(action == "/admit" for action, _ in hub.calls) == 1


def test_ambiguous_successors_are_not_selected_by_sort_order(tmp_path, executor):
    hub = Queue()
    data = admission(hub)
    run(data, hub, tmp_path)
    new = hub.next()
    competing = copy.deepcopy(new)
    competing["workId"] = new["workId"][:65] + "4" * 64
    hub.jobs[competing["workId"]] = competing
    with pytest.raises(RuntimeError, match="ambiguous_successor"): run(data, hub, tmp_path)
    assert len(executor) == 1


@pytest.mark.parametrize("key,value", [("account_sha256", "d" * 64), ("maximum_chapters", 4)])
def test_cold_resume_cannot_change_account_or_expand_budget(tmp_path, executor, key, value):
    hub = Queue()
    data = admission(hub)
    run(data, hub, tmp_path)
    data[key] = value
    hub.calls.clear()
    with pytest.raises(RuntimeError, match="retained_admission_mismatch"): run(data, hub, tmp_path)
    assert hub.calls == []


def test_lost_completion_resumes_exact_work_without_needing_pending_queue(tmp_path, executor, monkeypatch):
    hub = Queue()
    data = admission(hub)
    step = intake.cycle._step
    def lost(*args):
        step(*args)
        raise RuntimeError("lost response")
    monkeypatch.setattr(intake.cycle, "_step", lost)
    with pytest.raises(RuntimeError, match="lost response"): run(data, hub, tmp_path)
    exact = executor[0]["execution_admission"]
    monkeypatch.setattr(intake.cycle, "_step", step)
    monkeypatch.setattr(hub, "pending", lambda *a: pytest.fail("resume exact work, not queue"))
    data["browser_session"] = "new-owned-session"
    assert run(data, hub, tmp_path)["state"] == "review_required"
    assert executor[-1]["execution_admission"] == exact
    assert executor[-1]["setup"]["browser_session"] == "new-owned-session"
    assert sum(action == "/admit" for action, _ in hub.calls) == 1


def test_missing_local_custody_never_adopts_an_existing_hub_admission(tmp_path, executor):
    hub = Queue()
    hub.first["executionAdmission"] = "old-consumed-work"
    hub.first["job"]["state"] = "reconciliation_required"
    with pytest.raises(RuntimeError, match="existing_admission_requires_recovery"):
        run(admission(hub), hub, tmp_path)
    assert not executor


def test_shared_cycle_lock_blocks_intake_before_hub(tmp_path, executor):
    hub = Queue()
    with intake.cycle._lease(tmp_path):
        with pytest.raises(RuntimeError, match="cycle_busy"): run(admission(hub), hub, tmp_path)
    assert hub.calls == []


def test_pending_request_uses_only_scoped_loopback_get_and_bounds_response(tmp_path):
    token = tmp_path / "token"
    token.write_text("synthetic-worker-token-" * 3)
    token.chmod(0o600)
    client = intake.worker.LocalHub("http://127.0.0.1:15099", token, host="chummer.run")
    class Response:
        status = 200
        headers = {}
        raw = b"[]"
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, maximum): return self.raw[:maximum]
    class Http:
        def open(self, request, timeout):
            assert request.full_url == "http://127.0.0.1:15099/api/internal/origin/chapters/pending?limit=20&bookRef=" + "c" * 64
            assert request.get_method() == "GET"
            return Response()
    client._http = Http()
    assert client.pending("c" * 64) == []
    Response.raw = json.dumps([{"bookRef": "d" * 64}]).encode()
    with pytest.raises(ValueError, match="response_invalid"): client.pending("c" * 64)
    Response.raw = b" " * 512001
    with pytest.raises(RuntimeError, match="response_oversized"): client.pending("c" * 64)


def test_intake_drives_real_cycle_writer_and_result_adapter_without_replaying(tmp_path, monkeypatch):
    hub = Queue()
    data = admission(hub)
    browser = {}
    def prepare(packet, client, output):
        # Only the remote framework/outline UI is simulated here. Actual
        # cycle, retained handoff, writer fence and result validation run below.
        fixture = Hub()
        setup_packet(fixture)
        retained, _ = retained_setup(output, fixture)
        client.call(packet["work_id"], "/admit", {"executionAdmission": packet["execution_admission"]})
        observed, actions = prepared_browser(retained, monkeypatch)
        browser.update(observed=observed, actions=actions)
        return {"state": "first_chapter_prepared"}
    monkeypatch.setattr(intake.worker, "prepare_once", prepare)
    # The genuine complete adapter must receive exactly what the writer read.
    original = hub.call
    def call(work_id, action="", body=None):
        result = original(work_id, action, body)
        if action == "/complete":
            hub.jobs[work_id]["job"].update(draftText=body["draftText"], providerReceiptDigest=body["providerReceiptDigest"])
            return copy.deepcopy(hub.jobs[work_id])
        return result
    monkeypatch.setattr(hub, "call", call)
    assert run(data, hub, tmp_path)["state"] == "generation_dispatched"
    browser["observed"].update(generating=True)
    assert run(data, hub, tmp_path)["state"] == "provider_busy"
    browser["observed"].update(generating=False, hasDraft=True)
    assert run(data, hub, tmp_path)["state"] == "review_required"
    assert run(data, hub, tmp_path)["state"] == "idle"
    assert sum("Write Chapter" in action for action in browser["actions"]) == 1
    assert not any("Approve" in action for action in browser["actions"])
    assert hub.first["job"].get("readerAcceptedTextDigest") is None
