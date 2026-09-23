import copy
import fcntl

import pytest

from scripts import origin_chapter_cycle as cycle
from scripts import origin_chapter_worker as worker
from tests.test_origin_chapter_worker import Hub, setup_packet, retained_setup, prepared_browser
from tests.test_firstbook_next_chapter_prepare import continuation


def approved(data):
    data = copy.deepcopy(data)
    data["automatic_execution_approved"] = True
    data["setup"]["chapter_generation_approved"] = True
    return data


@pytest.mark.parametrize("field", ["automatic_execution_approved", "chapter_generation_approved"])
def test_cycle_needs_explicit_bounded_execution_before_http(tmp_path, field):
    hub = Hub()
    data = approved(setup_packet(hub))
    if field == "automatic_execution_approved": data[field] = False
    else: data["setup"][field] = False
    with pytest.raises(ValueError, match="execution_not_admitted"):
        cycle.run_once(data, hub, tmp_path)
    assert not hub.calls


def test_cycle_derives_prepared_mapping_and_completes_one_write(tmp_path, monkeypatch):
    hub = Hub()
    data, _ = retained_setup(tmp_path, hub)
    observed, calls = prepared_browser(data, monkeypatch)
    data = approved(data)
    # An operator no longer copies provider IDs/outlines between phases.
    del data["prepared"]
    assert cycle.run_once(data, hub, tmp_path)["state"] == "generation_dispatched"
    observed["generating"] = True
    assert cycle.run_once(data, hub, tmp_path)["state"] == "provider_busy"
    before = list(calls)
    observed.update(generating=False, hasDraft=True)
    assert cycle.run_once(data, hub, tmp_path)["state"] == "review_required"
    assert sum("Write Chapter" in c for c in calls) == 1
    assert not any("Approve" in c for c in calls)
    assert hub.work["job"].get("readerAcceptedTextDigest") is None
    assert len(calls) > len(before)
    calls.clear()
    assert cycle.run_once(data, hub, tmp_path)["state"] == "review_required"
    assert calls == []


def test_cycle_ignores_injected_prepared_mapping_and_stops_at_uncertain_write(tmp_path, monkeypatch):
    hub = Hub()
    data, _ = retained_setup(tmp_path, hub)
    _, calls = prepared_browser(data, monkeypatch)
    data = approved(data)
    data["prepared"]["provider_book_id"] = "wrong-book"
    assert cycle.run_once(data, hub, tmp_path)["state"] == "generation_dispatched"
    assert cycle.run_bounded(data, hub, tmp_path, cycles=10,
        sleep=lambda _: pytest.fail("uncertain write must stop"))["state"] == "reconciliation_required"
    assert sum("Write Chapter" in c for c in calls) == 1


def test_cycle_rejects_source_drift_before_preparation(tmp_path, monkeypatch):
    hub = Hub()
    data = approved(setup_packet(hub))
    hub.work["job"]["sourceDigest"] = "d" * 64
    monkeypatch.setattr(worker, "prepare_once", lambda *a: pytest.fail("no preparation"))
    with pytest.raises(ValueError, match="binding_mismatch"):
        cycle.run_once(data, hub, tmp_path)
    assert hub.calls == [("", None)]


def test_cycle_moves_directly_from_completed_preparation_to_fenced_writer(tmp_path, monkeypatch):
    hub = Hub()
    data = approved(setup_packet(hub))
    actions = []
    def prepare(packet, client, output):
        retained, _ = retained_setup(output, client)
        prepared_browser(retained, monkeypatch)
        actions.append("prepared")
        return {"state": "first_chapter_prepared"}
    monkeypatch.setattr(worker, "prepare_once", prepare)
    assert cycle.run_once(data, hub, tmp_path)["state"] == "generation_dispatched"
    assert actions == ["prepared"]


def test_cycle_refuses_preparation_success_without_matching_durable_handoff(tmp_path, monkeypatch):
    hub = Hub()
    data = approved(setup_packet(hub))
    monkeypatch.setattr(worker, "prepare_once", lambda *a: {"state": "first_chapter_prepared"})
    monkeypatch.setattr(worker, "run_once", lambda *a: pytest.fail("no write"))
    with pytest.raises(RuntimeError, match="preparation_not_retained"):
        cycle.run_once(data, hub, tmp_path)


def test_cycle_root_lock_prevents_parallel_browser_work(tmp_path):
    hub = Hub()
    data = approved(setup_packet(hub))
    root = worker.writer._private_root(tmp_path)
    with (root / ".cycle.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match="cycle_busy"):
            cycle.run_once(data, hub, tmp_path)
    assert not hub.calls


@pytest.mark.parametrize("state", ["awaiting_reader_acceptance", "reconciliation_required",
    "outline_reconciliation_required", "framework_observed_needs_project_binding", "review_required", "unexpected"])
def test_polling_stops_on_terminal_unapproved_or_unknown_state(tmp_path, monkeypatch, state):
    calls = []
    data = approved(setup_packet(Hub()))
    monkeypatch.setattr(cycle, "_step", lambda *a: calls.append(1) or {"state": state})
    assert cycle.run_bounded(data, None, tmp_path, cycles=3, sleep=lambda _: pytest.fail("must stop")) == {"state": state}
    assert calls == [1]


def test_polling_observes_only_known_transitions_with_finite_budget(tmp_path, monkeypatch):
    data = approved(setup_packet(Hub()))
    states = iter(["framework_dispatched", "credit_dispatched", "advance_dispatched", "provider_busy", "generation_dispatched", "review_required"])
    sleeps = []
    monkeypatch.setattr(cycle, "_step", lambda *a: {"state": next(states)})
    assert cycle.run_bounded(data, None, tmp_path, cycles=10, interval=2, sleep=sleeps.append)["state"] == "review_required"
    assert sleeps == [2] * 5
    monkeypatch.setattr(cycle, "_step", lambda *a: {"state": "provider_busy"})
    sleeps.clear()
    assert cycle.run_bounded(data, None, tmp_path, cycles=3, sleep=sleeps.append)["state"] == "provider_busy"
    assert sleeps == [10, 10]


def test_polling_does_not_retry_transport_failure(tmp_path, monkeypatch):
    def unavailable(*args): raise RuntimeError("origin_worker_hub_unavailable_reconcile_same_job")
    monkeypatch.setattr(cycle, "_step", unavailable)
    with pytest.raises(RuntimeError, match="unavailable"):
        cycle.run_bounded(approved(setup_packet(Hub())), None, tmp_path, cycles=3, sleep=lambda _: pytest.fail("no retry"))


@pytest.mark.parametrize("cycles,interval", [(0, 10), (121, 10), (True, 10), (1, 1), (1, 61)])
def test_invalid_poll_budget_never_starts(tmp_path, monkeypatch, cycles, interval):
    monkeypatch.setattr(cycle, "_step", lambda *a: pytest.fail("invalid budget"))
    with pytest.raises(ValueError, match="invalid_budget"):
        cycle.run_bounded({}, None, tmp_path, cycles=cycles, interval=interval)


def test_bounded_cycle_keeps_lease_while_browser_is_busy(tmp_path, monkeypatch):
    data = approved(setup_packet(Hub()))
    monkeypatch.setattr(cycle, "_step", lambda *a: {"state": "provider_busy"})
    waits = []
    def sleep(seconds):
        waits.append(seconds)
        with pytest.raises(RuntimeError, match="cycle_busy"):
            cycle.run_once(data, None, tmp_path)
    assert cycle.run_bounded(data, None, tmp_path, cycles=2, sleep=sleep)["state"] == "provider_busy"
    assert waits == [10]
    assert cycle.run_once(data, None, tmp_path)["state"] == "provider_busy"


def jobs_for(s):
    old = copy.deepcopy(s["hub"].work)
    old["executionAdmission"] = s["old"]["execution_admission"]
    old["job"].update(state="review_required", draftText=worker.writer._load(s["path"])["result"]["text"],
        providerReceiptDigest=s["receipt"], readerAcceptedTextDigest=s["text"])
    new = copy.deepcopy(s["hub"].work)
    new["workId"] = s["new"]["work_id"]
    new["job"].update(source=s["new"]["approved_source"], sourceDigest="d" * 64)
    class Jobs:
        def call(self, work_id, action="", body=None):
            if work_id == old["workId"]:
                assert not action
                return copy.deepcopy(old)
            assert work_id == new["workId"]
            if action == "/admit":
                first = new["executionAdmission"] is None
                new["executionAdmission"] = body["executionAdmission"]
                new["job"]["state"] = "reconciliation_required"
                return {"work": copy.deepcopy(new), "mayStartGeneration": first}
            if action == "/complete":
                new["job"].update(state="review_required", draftText=body["draftText"], providerReceiptDigest=body["providerReceiptDigest"])
            return copy.deepcopy(new)
    return Jobs(), old, new


def test_next_cycle_advances_and_edits_once_then_uses_retained_plan(tmp_path, continuation, monkeypatch):
    s = continuation
    data = approved(s["new"])
    hub, old, new = jobs_for(s)
    advances = []
    monkeypatch.setattr(worker.advancement, "advance_accepted_chapter",
        lambda *a: advances.append(1) or {"render_status": "next_chapter_observed"})
    assert cycle.run_once(data, hub, tmp_path)["state"] == "outline_save_dispatched"
    assert cycle.run_once(data, hub, tmp_path)["state"] == "generation_dispatched"
    assert len(advances) == 2  # real advancement adapter reconciles its one-click fence
    assert cycle.run_once(data, hub, tmp_path)["state"] == "reconciliation_required"
    assert len(advances) == 2  # does not navigate back to predecessor after handoff
    assert sum("Lock & Start Writing" in a for a in s["actions"]) == 1
    assert sum("Write Chapter" in a for a in s["actions"]) == 1
    assert s["values"][:1] == s["before"][:1] and s["values"][2:] == s["before"][2:]
    old["job"]["readerAcceptedTextDigest"] = None
    before = list(s["actions"])
    assert cycle.run_once(data, hub, tmp_path)["state"] == "awaiting_reader_acceptance"
    assert s["actions"] == before


def test_next_cycle_waits_for_reader_and_rejects_other_book(tmp_path, continuation, monkeypatch):
    s = continuation
    data = approved(s["new"])
    hub, old, new = jobs_for(s)
    monkeypatch.setattr(worker, "prepare_next_once", lambda *a: pytest.fail("no advancement"))
    old["job"]["readerAcceptedTextDigest"] = None
    assert cycle.run_once(data, hub, tmp_path)["state"] == "awaiting_reader_acceptance"
    old["bookRef"] = "0" * 64
    with pytest.raises(ValueError, match="source_mismatch"):
        cycle.run_once(data, hub, tmp_path)
    assert not s["actions"] and new["executionAdmission"] is None


def bind_hub_edge(s):
    hub, old, new = jobs_for(s)
    old["job"]["requestId"] = "accepted-previous-request"
    new["job"]["requestId"] = "next-request"
    new["previousWorkId"] = old["workId"]
    new["job"]["previous"] = {"requestId": old["job"]["requestId"],
        "sourceDigest": old["job"]["sourceDigest"], "providerReceiptDigest": old["job"]["providerReceiptDigest"],
        "textDigest": old["job"]["readerAcceptedTextDigest"]}
    return hub, old, new


@pytest.mark.parametrize("change", ["work", "request", "source", "receipt", "text", "acceptance", "history", "missing-packet"])
def test_hub_declared_predecessor_cannot_be_replaced_before_provider(tmp_path, continuation, monkeypatch, change):
    s = continuation
    data = approved(s["new"])
    hub, old, new = bind_hub_edge(s)
    if change == "work": new["previousWorkId"] = "1" * 64 + "." + "7" * 64
    elif change == "request": new["job"]["previous"]["requestId"] = "another-request"
    elif change in ("source", "receipt", "text"):
        new["job"]["previous"][{"source": "sourceDigest", "receipt": "providerReceiptDigest", "text": "textDigest"}[change]] = "0" * 64
    elif change == "acceptance": old["job"]["readerAcceptedTextDigest"] = None
    elif change == "history":
        new["job"]["source"]["facts"] = new["job"]["source"]["facts"][1:]
        data["approved_source"] = copy.deepcopy(new["job"]["source"])
    else: del data["previous"]
    monkeypatch.setattr(worker, "prepare_next_once", lambda *a: pytest.fail("no advancement or input"))
    monkeypatch.setattr(worker, "prepare_once", lambda *a: pytest.fail("no replacement book"))
    with pytest.raises(ValueError, match="predecessor_binding_mismatch|previous_chapter_required"):
        cycle.run_once(data, hub, tmp_path)
    assert not s["actions"] and new["executionAdmission"] is None


def test_exact_hub_edge_works_without_recursively_copying_all_earlier_packets(tmp_path, continuation, monkeypatch):
    s = continuation
    data = approved(s["new"])
    hub, old, new = bind_hub_edge(s)
    # The predecessor itself may have an earlier immutable Hub edge. The
    # caller supplies only the immediately preceding prepared execution packet.
    old["previousWorkId"] = "1" * 64 + "." + "8" * 64
    old["job"]["previous"] = {"requestId": "earlier-request", "sourceDigest": "8" * 64,
        "providerReceiptDigest": "9" * 64, "textDigest": "a" * 64}
    monkeypatch.setattr(worker.advancement, "advance_accepted_chapter",
        lambda *a: {"render_status": "next_chapter_observed"})
    assert cycle.run_once(data, hub, tmp_path)["state"] == "outline_save_dispatched"
    assert sum("Lock & Start Writing" in a for a in s["actions"]) == 1
