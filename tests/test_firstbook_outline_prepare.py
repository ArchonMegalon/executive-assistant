from __future__ import annotations

import copy
import json
import re

import pytest

from scripts import firstbook_outline_prepare as outline
from tests.test_firstbook_project_prepare import packet as setup_packet


def packet():
    return {**setup_packet(), "outline_activation_approved": True, "maximum_book_credits": 1}


@pytest.fixture
def surface(tmp_path, monkeypatch):
    data = packet()
    binding = outline.setup._binding(data)
    root = outline.writer._private_root(tmp_path)
    outline.writer._save(root / ("setup-" + binding["book_ref"] + ".json"), {
        "binding": binding, "plan": outline.setup._plan(binding), "state": "framework_dispatched",
        "provider": {"provider_book_id": "existing-book", "book_title": "Nera's private book"}})
    cards = [{"number": n, "expanded": True, "values": [f"old-{n}-{i}" for i in range(8)]} for n in range(1, 9)]
    calls = []
    page = {"origin": "https://app.firstbook.ai", "pageEpoch": 1000, "outlinePage": True,
            "lockText": "Lock & Start Writing 1 Credit", "lockEnabled": True, "cards": cards}
    monkeypatch.setattr(outline, "_inspect", lambda *args: copy.deepcopy(page))
    monkeypatch.setattr(outline.setup, "_observe_existing_framework", lambda *args: calls.append("verify_project"))
    author = {"origin": "https://app.firstbook.ai", "pageEpoch": 1000, "formCount": 1, "fieldCount": 2,
              "anecdotes": "", "sample": "", "submitEnabled": True, "creditCost": "1"}
    monkeypatch.setattr(outline, "_inspect_author", lambda *args: copy.deepcopy(author))
    def browser(session, *args):
        if args[0] == "input":
            author["anecdotes" if args[2] == outline._ANECDOTES else "sample"] = args[4]
    monkeypatch.setattr(outline.capture, "_browser", browser)
    monkeypatch.setattr(outline.capture, "_click", lambda session, selector: calls.append(selector))
    monkeypatch.setattr(outline.capture, "_open_book", lambda *args: calls.append("reopen_paid"))
    monkeypatch.setattr(outline.writer, "_inspect", lambda *args: {"generating": False})
    monkeypatch.setattr(outline.writer, "_require_prepared", lambda *args: None)
    def fill(session, number, chapter):
        assert outline.writer._load(root / ("outline-" + binding["book_ref"] + ".json"))["state"] == "editing"
        calls.append("fill")
        cards[number - 1]["values"] = outline._values(chapter)
    monkeypatch.setattr(outline, "_fill_card", fill)
    return data, root, page, calls


def test_all_future_slots_are_unselected_and_activation_is_fenced_once(tmp_path, surface, monkeypatch):
    data, root, page, calls = surface
    path = root / ("outline-" + data["book_ref"] + ".json")
    def click(session, selector):
        if "Lock & Start" in selector:
            record = outline.writer._load(path)
            assert record["state"] == "outline_lock_dispatched"
            assert [row["values"] for row in page["cards"]] == [outline._values(c) for c in record["plan"]]
        if "Start writing my book" in selector:
            assert outline.writer._load(path)["state"] == "credit_dispatched"
        calls.append(selector)
    monkeypatch.setattr(outline.capture, "_click", click)
    result = outline.prepare_first_chapter(data, tmp_path)
    assert result["state"] == "credit_dispatched" and result["publication_authorized"] is False
    assert path.stat().st_mode & 0o777 == 0o600
    record = outline.writer._load(path)
    assert "Nera is an elf." in json.dumps(record["plan"][0])
    assert "Nera is an elf." not in json.dumps(record["plan"][1:])
    assert all(c["title"].startswith("Noch unentschieden") for c in record["plan"][1:])
    assert outline.prepare_first_chapter(data, tmp_path)["state"] == "first_chapter_prepared"
    assert len([c for c in calls if "Lock & Start" in c]) == 1
    assert len([c for c in calls if "Start writing my book" in c]) == 1
    assert calls.count("fill") == 8


def test_uncertain_activation_never_spends_twice(tmp_path, surface, monkeypatch):
    data, root, page, calls = surface
    def click(session, selector):
        calls.append(selector)
        if "Start writing my book" in selector:
            raise RuntimeError("lost_response")
    monkeypatch.setattr(outline.capture, "_click", click)
    with pytest.raises(RuntimeError, match="lost_response"):
        outline.prepare_first_chapter(data, tmp_path)
    assert outline.prepare_first_chapter(data, tmp_path)["state"] == "first_chapter_prepared"
    assert sum("Lock & Start" in c for c in calls) == 1
    assert sum("Start writing my book" in c for c in calls) == 1


def test_partial_edit_is_not_a_paid_activation_or_a_blind_replay(tmp_path, surface, monkeypatch):
    data, root, page, calls = surface
    def failed(*args):
        raise RuntimeError("browser_closed")
    monkeypatch.setattr(outline, "_fill_card", failed)
    with pytest.raises(RuntimeError, match="browser_closed"):
        outline.prepare_first_chapter(data, tmp_path)
    before = list(calls)
    assert outline.prepare_first_chapter(data, tmp_path)["state"] == "outline_reconciliation_required"
    assert calls == before and not any("Lock & Start" in c for c in calls)


@pytest.mark.parametrize("patch", [{"outline_activation_approved": False}, {"maximum_book_credits": 2}, {"maximum_book_credits": True}])
def test_initial_framework_consent_is_not_payment_consent(tmp_path, surface, patch):
    data, root, page, calls = surface
    with pytest.raises(ValueError, match="not_admitted"):
        outline.prepare_first_chapter({**data, **patch}, tmp_path)
    assert calls == []


@pytest.mark.parametrize("key,value", [("lockText", "Lock & Start Writing 2 Credits"),
    ("lockEnabled", False), ("outlinePage", False), ("origin", "https://other.test"), ("pageEpoch", None)])
def test_wrong_surface_or_price_is_not_accepted(tmp_path, surface, key, value):
    data, root, page, calls = surface
    page[key] = value
    with pytest.raises(RuntimeError, match="surface_mismatch"):
        outline.prepare_first_chapter(data, tmp_path)
    assert "fill" not in calls and not any("Lock & Start" in c for c in calls)


def test_wrong_source_cannot_reuse_existing_setup(tmp_path, surface):
    data, root, page, calls = surface
    data["approved_source"]["runnerName"] = "Different runner"
    with pytest.raises(RuntimeError, match="setup_not_bound"):
        outline.prepare_first_chapter(data, tmp_path)
    assert not calls


def test_lost_input_or_react_reset_prevents_activation(tmp_path, surface, monkeypatch):
    data, root, page, calls = surface
    monkeypatch.setattr(outline, "_fill_card", lambda *args: None)
    with pytest.raises(RuntimeError, match="input_not_retained"):
        outline.prepare_first_chapter(data, tmp_path)
    assert not any("Lock & Start" in c for c in calls)


def test_private_journal_failure_prevents_all_edits(tmp_path, surface, monkeypatch):
    data, root, page, calls = surface
    monkeypatch.setattr(outline.writer, "_save", lambda *args: (_ for _ in ()).throw(OSError("disk_full")))
    with pytest.raises(OSError, match="disk_full"):
        outline.prepare_first_chapter(data, tmp_path)
    assert "fill" not in calls and not any("Lock & Start" in c for c in calls)


@pytest.mark.parametrize("locale,first,pending", [("de-DE", "Ein Anfang", "Noch unentschieden"),
    ("en-US", "A Beginning", "Still Undecided"), ("es-ES", "Un comienzo", "Aún sin decidir")])
def test_plan_is_localized_and_does_not_leak_private_identity(locale, first, pending):
    data = packet()
    data["approved_source"]["locale"] = locale
    plan = outline._plan(outline.setup._binding(data), 8)
    assert plan[0]["title"].endswith(first) and plan[1]["title"].startswith(pending)
    text = json.dumps(plan)
    for excluded in ("private-workspace-id", "chapter-id", "decision-id", "fact-id", "chummer.run", "4" * 64):
        assert excluded not in text


def test_historical_local_limit_is_not_silently_reinterpreted():
    data = packet()
    data["approved_source"]["facts"][0]["text"] = "a" * 2048
    with pytest.raises(ValueError, match="description"):
        outline._plan(outline.setup._binding(data), 8, version=2)
    plan = outline._plan(outline.setup._binding(data), 8)
    assert all("a" * 2048 in part["description"] for part in plan[0]["parts"])


@pytest.mark.parametrize("patch", [{"creditCost": "2"}, {"pageEpoch": 2000}, {"anecdotes": "Some other person's story"},
                                   {"formCount": 2}, {"submitEnabled": False}])
def test_author_form_drift_stops_before_credit_use(tmp_path, surface, monkeypatch, patch):
    data, root, page, calls = surface
    original = outline._inspect_author
    monkeypatch.setattr(outline, "_inspect_author", lambda *args: {**original(*args), **patch})
    with pytest.raises(RuntimeError, match="author_form_mismatch"):
        outline.prepare_first_chapter(data, tmp_path)
    assert not any("Start writing my book" in c for c in calls)


def test_author_style_is_synthetic_and_facts_are_not_invented():
    binding = outline.setup._binding(packet())
    plan = outline._author_plan(binding)
    assert "not the player's personal experiences" in plan["anecdotes"]
    assert "Nera is an elf." in plan["anecdotes"]
    assert "Nera" not in plan["sample"] and "vertraute Umgebung" in plan["sample"]
    assert "Regen" in outline._author_plan(binding, version=3)["sample"]


@pytest.mark.parametrize("locale", ["de-DE", "en-US", "es-ES"])
def test_new_prose_preserves_unspecified_identity_and_distinguishes_scene_from_biography(locale):
    data = packet()
    data["approved_source"]["locale"] = locale
    binding = outline.setup._binding(data)
    plan = outline._plan(binding, 8)
    assert outline._plan_version(binding, plan) == 6
    for part in plan[0]["parts"]:
        text = part["description"]
        assert "pronouns only when explicitly confirmed" in text
        assert "otherwise use the runner's name" in text
        assert "Survival does not establish childhood forest treks" in text
        assert "Leadership does not mean peers already trust or follow" in text
        assert "Small present-moment sensory details" in text
        assert "not possessions, relationships, remembered events or successful outcomes" in text
    endings = [part["description"].removeprefix(plan[0]["summary"]) for part in plan[0]["parts"]]
    assert "one confirmed contribution" in endings[0]
    assert "different confirmed contribution" in endings[1]
    assert "Do not recap the training or bonuses" in endings[2]
    assert "Establish the confirmed metatype, birth background and childhood" in plan[0]["summary"]
    assert "currentDecisionFacts" not in plan[0]["summary"]
    sample = outline._author_plan(binding)["sample"]
    assert not re.search(r"\b(sie|ihr|ihre|er|sein|she|her|he|his|ella|él)\b", sample, re.IGNORECASE)


@pytest.mark.parametrize("locale", ["de-DE", "en-US", "es-ES"])
def test_prose_instructions_address_observed_inventory_and_rule_leakage(locale):
    data = packet()
    data["approved_source"]["locale"] = locale
    binding = outline.setup._binding(data)
    facts = json.dumps([f["text"] for f in binding["approved_source"]["facts"]], ensure_ascii=False)
    plan = outline._plan(binding, 8)
    assert outline._plan_version(binding, plan) == 6
    for part in plan[0]["parts"]:
        text = part["description"]
        assert facts in text  # Do not achieve better prose by dropping approved facts.
        assert "Karma costs, negative-quality budgets, zero entries, unassigned pools" in text
        assert "have no biographical meaning" in text
        assert "A skill grant does not grant its equipment" in text
        assert "Missing augmentation data does not mean an unmodified body" in text
        assert "developing habits" in text and "never mastery" in text
        assert "2-4 varied sentences" in text and "150-210 words" in text
        assert "do not reuse its weather, room, objects or events" in text
    assert all(facts not in json.dumps(future) for future in plan[1:])


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_resumed_author_form_preserves_admitted_style(tmp_path, surface, monkeypatch, version):
    data, root, page, calls = surface
    binding = outline.setup._binding(data)
    path = root / ("outline-" + data["book_ref"] + ".json")
    record = {"binding": binding,
        "provider": {"provider_book_id": "existing-book", "book_title": "Nera's private book"},
        "plan": outline._plan(binding, 8, version=version), "before": [],
        "state": "outline_lock_dispatched", "browser_session": data["browser_session"], "page_epoch": 1000}
    outline.writer._save(path, record)
    author_plan = outline._author_plan
    selected = []
    def retained_style(binding, *, version):
        selected.append(version)
        return author_plan(binding, version=version)
    monkeypatch.setattr(outline, "_author_plan", retained_style)
    assert outline.prepare_first_chapter(data, tmp_path)["state"] == "credit_dispatched"
    assert selected == [version]
    assert outline.writer._load(path)["plan"] == record["plan"]
    assert not any("Lock & Start" in call for call in calls)
    assert sum("Start writing my book" in call for call in calls) == 1


@pytest.mark.parametrize("locale", ["de-DE", "en-US", "es-ES"])
def test_new_plan_bounds_whole_scene_and_does_not_infer_abilities(locale):
    data = packet()
    data["approved_source"]["locale"] = locale
    plan = outline._plan(outline.setup._binding(data), 8)
    for part in plan[0]["parts"]:
        assert "450-650 words TOTAL" in part["description"]
        assert "150-210 words in this section" in part["description"]
        assert "enhanced senses, powers or skills" in part["description"]
        assert "ordinary sensations only" in part["description"]


def test_prior_exact_outline_recovers_without_rewriting_or_repaying(tmp_path, surface):
    data, root, page, calls = surface
    outline.prepare_first_chapter(data, tmp_path)
    path = root / ("outline-" + data["book_ref"] + ".json")
    record = outline.writer._load(path)
    old_plan = outline._plan(record["binding"], 8, legacy=True)
    record["plan"] = old_plan
    outline.writer._save(path, record)
    calls.clear()
    assert outline.prepare_first_chapter(data, tmp_path)["state"] == "first_chapter_prepared"
    assert calls == ["reopen_paid"]
    assert outline.writer._load(path)["plan"] == old_plan


def test_legacy_recovery_does_not_apply_new_prompt_size_to_retained_plan(tmp_path, surface):
    data, root, page, calls = surface
    data["approved_source"]["facts"][0]["text"] = "x" * 1400
    binding = outline.setup._binding(data)
    provider = {"provider_book_id": "existing-book", "book_title": "Nera's private book"}
    old_plan = outline._plan(binding, 8, legacy=True)
    with pytest.raises(ValueError, match="description"):
        outline._plan(binding, 8, version=2)
    outline.writer._save(root / ("setup-" + binding["book_ref"] + ".json"), {
        "binding": binding, "plan": outline.setup._plan(binding), "state": "framework_dispatched",
        "provider": provider})
    path = root / ("outline-" + binding["book_ref"] + ".json")
    outline.writer._save(path, {"binding": binding, "provider": provider, "plan": old_plan,
        "before": [], "state": "credit_dispatched", "browser_session": "old-session", "page_epoch": 1000})
    assert outline.prepare_first_chapter(data, tmp_path)["state"] == "first_chapter_prepared"
    assert calls == ["reopen_paid"]
    assert outline.writer._load(path)["plan"] == old_plan


@pytest.mark.parametrize("locale", ["de-DE", "en-US", "es-ES"])
def test_opening_setup_and_contributions_fit_without_losing_any_fact(locale):
    data = packet()
    data["approved_source"]["locale"] = locale
    texts = ["Metatype: elf. " + "m" * 50,
             "Birth background and confirmed contributions: " + "b" * 1073,
             "Childhood and confirmed contributions: " + "c" * 1083]
    data["approved_source"]["facts"] = [
        {"factId": f"private-fact-{i}", "decisionId": f"private-decision-{i}", "text": value}
        for i, value in enumerate(texts)]
    binding = outline.setup._binding(data)
    facts = json.dumps(texts, ensure_ascii=False)
    plan = outline._plan(binding, 8)
    assert facts in plan[0]["summary"]
    assert facts in outline.setup._plan(binding)["background"]
    assert facts in outline._author_plan(binding)["anecdotes"]
    for part in plan[0]["parts"]:
        assert facts in part["description"]
        assert "metatype, birth background and childhood" in part["description"]
        assert "confirmed module contributions and trade-offs" in part["description"]
        assert "contributions are not final ratings" in part["description"]
        assert "without inventing extra biographical events or rewards" in part["description"]
    assert "private-fact" not in json.dumps(plan) and "private-decision" not in json.dumps(plan)
    assert all(text not in json.dumps(plan[1:]) for text in texts)
    prepared = outline._prepared(binding, {"provider_book_id": "existing-book", "book_title": "Nera"}, plan)
    accepted = outline.writer._binding({**prepared, "generation_approved": True})
    assert accepted["expected_outline"] == plan[0]["parts"]


@pytest.mark.parametrize("text", ["a" * 2048, "境" * 680])
def test_near_source_byte_bound_fits_writer_and_durable_record(tmp_path, text):
    data = packet()
    data["approved_source"]["facts"] = [
        {"factId": f"f-{i}", "decisionId": f"d-{i}", "text": f"{i}:" + text[3:]}
        for i in range(15)]
    binding = outline.setup._binding(data)
    assert len(json.dumps(binding["approved_source"], ensure_ascii=False).encode("utf-8")) > 30_000
    plan = outline._plan(binding, 100)
    assert outline._matches_plan(binding, plan)
    prepared = outline._prepared(binding, {"provider_book_id": "existing-book", "book_title": "Nera"}, plan)
    outline.writer._binding({**prepared, "generation_approved": True})
    root = outline.writer._private_root(tmp_path)
    path = root / "bounded-outline.json"
    record = {"binding": binding, "plan": plan, "before": [outline._values(chapter) for chapter in plan]}
    outline.writer._save(path, record)
    assert outline.writer._load(path) == record
    data["approved_source"]["facts"].append({"factId": "overflow", "decisionId": "d", "text": text})
    with pytest.raises(ValueError, match="source_oversized"):
        outline.setup._binding(data)


@pytest.mark.parametrize("version", [2, 3, 4])
def test_current_pre_upgrade_outline_is_recovered_byte_for_byte(tmp_path, surface, version):
    data, root, page, calls = surface
    outline.prepare_first_chapter(data, tmp_path)
    path = root / ("outline-" + data["book_ref"] + ".json")
    record = outline.writer._load(path)
    record["plan"] = outline._plan(record["binding"], 8, version=version)
    outline.writer._save(path, record)
    old_plan = copy.deepcopy(record["plan"])
    calls.clear()
    assert outline.prepare_first_chapter(data, tmp_path)["state"] == "first_chapter_prepared"
    assert calls == ["reopen_paid"]
    assert outline.writer._load(path)["plan"] == old_plan
    assert outline.retained_first_chapter(data, tmp_path)["expected_outline"] == old_plan[0]["parts"]


@pytest.mark.parametrize("fits", [[True] * 8, [True] * 7 + [False], None, [True] * 7])
def test_live_field_capacity_is_checked_before_any_input(monkeypatch, fits):
    data = packet()
    data["approved_source"]["facts"][0]["text"] = "Nera: 🌧"
    chapter = outline._plan(outline.setup._binding(data), 1)[0]
    calls = []
    def inspect(session, expression):
        lengths = json.loads(re.search(r"lengths=(\[[^\]]+\])", expression)[1])
        assert lengths == [len(value.encode("utf-16-le")) // 2 for value in outline._values(chapter)]
        assert lengths[1] > len(chapter["summary"])
        return {"origin": "https://app.firstbook.ai", "fits": fits}
    monkeypatch.setattr(outline.capture, "_eval", inspect)
    monkeypatch.setattr(outline.capture, "_browser", lambda s, *args: calls.append(args))
    if fits == [True] * 8:
        outline._fill_card("owned", 1, chapter)
        assert [call[4] for call in calls] == outline._values(chapter)
    else:
        with pytest.raises(RuntimeError, match="field_capacity_mismatch"):
            outline._fill_card("owned", 1, chapter)
        assert not calls
