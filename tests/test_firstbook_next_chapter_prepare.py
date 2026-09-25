import copy
import hashlib

import pytest

from scripts import firstbook_next_chapter_prepare as nxt
from scripts import origin_chapter_worker as worker
from tests.test_origin_chapter_worker import Hub, setup_packet, packet as worker_packet, prepared_browser


@pytest.fixture
def continuation(tmp_path, monkeypatch):
    hub = Hub()
    old = setup_packet(hub)
    old["prepared"] = worker_packet()["prepared"]
    old["prepared"]["request_id"] = old["work_id"]
    old["approved_source"] = copy.deepcopy(hub.work["job"]["source"])
    next_source = copy.deepcopy(old["approved_source"])
    next_source.update(chapterId="education", acceptedDecisionId="school", chapterDigest="e" * 64)
    next_source["facts"].append({"factId": "school", "decisionId": "school", "text": "Nera chose corporate schooling."})
    new = {"work_id": "1" * 64 + "." + "3" * 64, "execution_admission": "approved-job-2",
           "previous": old, "approved_source": next_source,
           "setup": {"browser_session": "owned-next", "account_sha256": "a" * 64,
                     "source_packet_sha256": "d" * 64, "outline_update_approved": True}}
    setup = {**new["setup"], "work_id": new["work_id"], "book_ref": hub.work["bookRef"], "approved_source": next_source}
    source, plan = nxt._plan(setup, old["prepared"])
    binding = nxt.writer._binding(old["prepared"])
    observed, actions = prepared_browser(old, monkeypatch)
    draft = nxt.capture._read_draft("owned-next")
    result = nxt.writer._result(binding, draft)
    root = nxt.writer._private_root(tmp_path)
    prior_path = nxt.writer._record_path(root, binding)
    nxt.writer._save(prior_path, {"binding": binding, "state": "chapter_review_required", "result": result})
    receipt = hashlib.sha256(prior_path.read_bytes()).hexdigest()
    text = result["text_sha256"]
    acceptance = {"binding": binding, "text_digest": text, "receipt_digest": receipt}
    nxt.writer._save(prior_path.with_suffix(".accept.json"), {"accepted": acceptance, "state": "next_chapter_observed"})
    initial = nxt.outline._plan(source, 8)
    before = [nxt.outline._values(row) for row in initial]
    values = copy.deepcopy(before)
    observed.update(chapterNumber=2, chapterTitle=initial[1]["title"], outline=initial[1]["parts"])
    page = {"origin": "https://app.firstbook.ai", "pageEpoch": 1000, "outlinePage": True,
            "lockText": "Lock & Start Writing", "lockEnabled": True,
            "cards": [{"number": i} for i in range(1, 9)]}
    monkeypatch.setattr(nxt.outline, "_inspect", lambda *a: copy.deepcopy(page))
    monkeypatch.setattr(nxt.outline, "_card", lambda s, n, c, **k: {"values": copy.deepcopy(values[n - 1])})
    def fill(s, n, chapter):
        assert nxt.writer._load(nxt._path(root, new["work_id"]))["state"] == "editing"
        values[n - 1] = nxt.outline._values(chapter)
    monkeypatch.setattr(nxt.outline, "_fill_card", fill)
    def click(s, target):
        actions.append(target)
        if "Lock & Start Writing" in target:
            assert nxt.writer._load(nxt._path(root, new["work_id"]))["state"] == "save_dispatched"
            observed.update(chapterTitle=plan["prepared"]["chapter_title"], outline=plan["prepared"]["expected_outline"])
    monkeypatch.setattr(nxt.capture, "_click", click)
    return dict(hub=hub, old=old, new=new, setup=setup, root=root, path=prior_path,
                receipt=receipt, text=text, before=before, values=values, observed=observed,
                actions=actions, plan=plan, page=page)


def prepare(state, tmp_path, **kw):
    return nxt.prepare_next_chapter(state["setup"], state["old"]["prepared"], tmp_path,
                                    state["text"], state["receipt"], **kw)


def test_next_choice_changes_only_one_slot_and_cold_read_completes_once(tmp_path, continuation):
    s = continuation
    original = s["path"].read_bytes()
    assert prepare(s, tmp_path)["state"] == "outline_save_dispatched"
    assert s["values"][:1] == s["before"][:1] and s["values"][2:] == s["before"][2:]
    assert "corporate schooling" in s["values"][1][1]
    assert prepare(s, tmp_path, allow_new_dispatch=False)["state"] == "next_chapter_prepared"
    actions = list(s["actions"])
    assert prepare(s, tmp_path)["prepared"] == s["plan"]["prepared"]
    assert s["actions"] == actions and s["path"].read_bytes() == original
    assert sum("Lock & Start Writing" in a for a in actions) == 1
    assert not any(x in a for a in actions for x in ("1 Credit", "Write Chapter", "Approve", "Regenerate"))


@pytest.mark.parametrize("change", ["acceptance", "receipt", "pending", "wrong_slot", "draft", "paid_lock", "missing_admission"])
def test_invalid_or_unready_continuation_never_edits(tmp_path, continuation, monkeypatch, change):
    s = continuation
    if change == "acceptance": s["text"] = "0" * 64
    elif change == "receipt": s["receipt"] = "0" * 64
    elif change == "pending":
        path = s["path"].with_suffix(".accept.json")
        record = nxt.writer._load(path); record["state"] = "advance_dispatched"; nxt.writer._save(path, record)
    elif change == "wrong_slot": s["observed"]["chapterNumber"] = 3
    elif change == "draft": s["observed"]["hasDraft"] = True
    elif change == "paid_lock": s["page"]["lockText"] = "Lock & Start Writing 1 Credit"
    elif change == "missing_admission":
        assert prepare(s, tmp_path, allow_new_dispatch=False)["state"] == "outline_reconciliation_required"
        assert not s["actions"]
        return
    monkeypatch.setattr(nxt.outline, "_fill_card", lambda *a: pytest.fail("must not edit"))
    with pytest.raises(RuntimeError): prepare(s, tmp_path)
    assert not any("Lock" in a for a in s["actions"])


def test_lost_save_does_not_replay_and_cross_slot_edits_prevent_save(tmp_path, continuation, monkeypatch):
    s = continuation
    click = nxt.capture._click
    def lost(session, target):
        click(session, target)
        if "Lock & Start Writing" in target: raise RuntimeError("lost_save")
    monkeypatch.setattr(nxt.capture, "_click", lost)
    with pytest.raises(RuntimeError, match="lost_save"): prepare(s, tmp_path)
    assert prepare(s, tmp_path)["state"] == "next_chapter_prepared"
    assert sum("Lock & Start Writing" in a for a in s["actions"]) == 1


def test_accordion_target_reopens_and_unsaved_input_failure_can_resume(tmp_path, continuation, monkeypatch):
    s = continuation
    expanded = 1
    original_card, original_fill = nxt.outline._card, nxt.outline._fill_card
    def card(session, number, count, **kw):
        nonlocal expanded
        expanded = number
        return original_card(session, number, count, **kw)
    failed = False
    def fill(session, number, chapter):
        nonlocal failed
        assert expanded == number, "last inventory card must not remain expanded"
        if not failed:
            failed = True
            raise RuntimeError("input_unavailable")
        original_fill(session, number, chapter)
    monkeypatch.setattr(nxt.outline, "_card", card)
    monkeypatch.setattr(nxt.outline, "_fill_card", fill)
    with pytest.raises(RuntimeError, match="input_unavailable"): prepare(s, tmp_path)
    assert not any("Lock" in a for a in s["actions"])
    assert prepare(s, tmp_path, allow_new_dispatch=False)["state"] == "outline_save_dispatched"
    assert prepare(s, tmp_path)["state"] == "next_chapter_prepared"


def test_other_chapter_changes_and_partial_edits_remain_blocked(tmp_path, continuation, monkeypatch):
    s = continuation
    fill = nxt.outline._fill_card
    def wrong(session, number, chapter):
        fill(session, number, chapter)
        s["values"][0][0] = "Changed previous chapter"
    monkeypatch.setattr(nxt.outline, "_fill_card", wrong)
    with pytest.raises(RuntimeError, match="readback_mismatch"): prepare(s, tmp_path)
    assert prepare(s, tmp_path)["state"] == "outline_reconciliation_required"
    assert not any("Lock" in a for a in s["actions"])


@pytest.mark.parametrize("state", ["editing", "save_dispatched", "prepared"])
def test_existing_next_outline_keeps_original_instructions(tmp_path, continuation, monkeypatch, state):
    s = continuation
    source, old_plan = nxt._plan(s["setup"], s["old"]["prepared"], version=2)
    path = nxt._path(s["root"], source["work_id"])
    nxt.writer._save(path, {"source": source, "previous": nxt.writer._binding(s["old"]["prepared"]),
        "plan": old_plan, "before": s["before"], "state": state})
    if state == "editing":
        fill = nxt.outline._fill_card
        def keep_old(session, number, chapter):
            assert chapter == old_plan["chapter"]
            fill(session, number, chapter)
        monkeypatch.setattr(nxt.outline, "_fill_card", keep_old)
        assert prepare(s, tmp_path)["state"] == "outline_save_dispatched"
    else:
        s["observed"].update(chapterTitle=old_plan["prepared"]["chapter_title"],
                             outline=old_plan["prepared"]["expected_outline"])
        assert prepare(s, tmp_path)["prepared"] == old_plan["prepared"]
        assert not any("Lock" in action for action in s["actions"])
        assert nxt.retained_next_chapter(s["setup"], s["old"]["prepared"], tmp_path) == old_plan["prepared"]
    assert nxt.writer._load(path)["plan"] == old_plan


def test_changed_retained_next_outline_is_rejected_before_navigation(tmp_path, continuation):
    s = continuation
    source, old_plan = nxt._plan(s["setup"], s["old"]["prepared"], version=2)
    old_plan["chapter"]["summary"] += " Changed biography."
    nxt.writer._save(nxt._path(s["root"], source["work_id"]), {
        "source": source, "previous": nxt.writer._binding(s["old"]["prepared"]),
        "plan": old_plan, "before": s["before"], "state": "prepared"})
    with pytest.raises(RuntimeError, match="next_retained_mismatch"):
        prepare(s, tmp_path)
    assert not s["actions"]


def test_worker_binds_both_hub_sources_before_preparing_and_reuses_admission(tmp_path, continuation, monkeypatch):
    s = continuation
    old_work = copy.deepcopy(s["hub"].work)
    old_work["executionAdmission"] = s["old"]["execution_admission"]
    old_work["job"].update(state="review_required", draftText=nxt.writer._load(s["path"])["result"]["text"],
                            providerReceiptDigest=s["receipt"], readerAcceptedTextDigest=s["text"])
    new_work = copy.deepcopy(s["hub"].work)
    new_work.update(workId=s["new"]["work_id"])
    new_work["job"].update(source=s["new"]["approved_source"], sourceDigest="d" * 64)
    class Jobs:
        def call(self, work_id, action="", body=None):
            if work_id == old_work["workId"]:
                assert not action
                return copy.deepcopy(old_work)
            assert work_id == new_work["workId"]
            if action == "/admit":
                first = new_work["executionAdmission"] is None
                new_work["executionAdmission"] = s["new"]["execution_admission"]
                new_work["job"]["state"] = "reconciliation_required"
                return {"work": copy.deepcopy(new_work), "mayStartGeneration": first}
            assert not action
            return copy.deepcopy(new_work)
    monkeypatch.setattr(worker.advancement, "advance_accepted_chapter", lambda *a: {"render_status": "next_chapter_observed"})
    jobs = Jobs()
    assert worker.prepare_next_once(s["new"], jobs, tmp_path)["state"] == "outline_save_dispatched"
    assert worker.prepare_next_once(s["new"], jobs, tmp_path)["state"] == "next_chapter_prepared"
    data = {**s["new"], "prepared": {**s["plan"]["prepared"], "browser_session": "owned-next"}}
    allowed = []
    monkeypatch.setattr(worker.writer, "write_prepared_chapter", lambda *a, **k:
        allowed.append(k["allow_new_dispatch"]) or {"render_status": "reconciliation_required"})
    assert worker.run_once(data, jobs, tmp_path)["state"] == "reconciliation_required"
    assert allowed == [True]
    old_work["job"]["readerAcceptedTextDigest"] = None
    assert worker.prepare_next_once(s["new"], jobs, tmp_path)["state"] == "awaiting_reader_acceptance"
    old_work["bookRef"] = "0" * 64
    with pytest.raises(ValueError, match="source_mismatch"):
        worker.prepare_next_once(s["new"], jobs, tmp_path)
