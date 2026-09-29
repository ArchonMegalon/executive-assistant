from __future__ import annotations

import copy
import json

import pytest

from scripts import firstbook_story_source as story
from scripts import firstbook_outline_prepare as outline
from scripts import firstbook_next_chapter_prepare as nxt
from tests.test_firstbook_project_prepare import packet, story_context, form
from tests.test_firstbook_outline_prepare import surface


def contribution(locale="en-US"):
    if locale.startswith("de"):
        return ("Human · Geburtsumfeld — Bestätigte Modulbeiträge, keine endgültigen Charakterwerte. "
                "Kosten der bestätigten Auswahl: 40 Karma. Attribut LOG: +1; Aktionsfertigkeit Archery: +2; "
                "Aktionsfertigkeit Etiquette: 0; Fertigkeitsgruppe Outdoors: -1; Wissensfertigkeiten-Pool: +3 "
                "(keine bestimmte Wissensfertigkeit oder Sprache); Budget für negative Eigenschaften: -5; "
                "Eigenschaft SINner (National): Stufenbeitrag 1 (kumulativ aufgelöst, kein Endwert); "
                "Eigenschaftsbeitrag: Distinctive Style; Weitere Beiträge nicht bestätigt; keine zusätzlichen Vorteile ableiten.")
    if locale.startswith("es"):
        return ("Human · Entorno natal — Aportaciones confirmadas del módulo, no valores finales del personaje. "
                "Coste de la elección confirmada: 40 Karma. Atributo LOG: +1; Habilidad activa Archery: +2; "
                "Habilidad activa Etiquette: 0; Grupo de habilidades Outdoors: -1; Reserva de conocimientos: +3 "
                "(no concede una habilidad o idioma concreto); Presupuesto de cualidades negativas: -5; "
                "Cualidad SINner (National): aportación de nivel 1 (resolución acumulativa, no es un valor final); "
                "Aportación de cualidad: Distinctive Style; Otras aportaciones sin verificar; no inferir recompensas adicionales.")
    return ("Human · Birth background — Confirmed module contributions, not final character ratings. "
            "Confirmed choice cost: 40 Karma. Attribute LOG: +1; Active skill Archery: +2; "
            "Active skill Etiquette: 0; Skill group Outdoors: -1; Knowledge-skill pool: +3 "
            "(not a named skill or language grant); Negative quality budget: -5; "
            "Quality SINner (National): level contribution 1 (resolved cumulatively, not a final rating); "
            "Quality contribution: Distinctive Style; Other contributions unverified; infer no additional rewards.")


def data(locale="en-US", *, context=False):
    value = packet()
    source = value["approved_source"]
    source["locale"] = locale
    source["facts"].append({"factId": "life-module:private:contributions:v1", "decisionId": "decision-id",
                            "text": contribution(locale)})
    if context:
        source["narrativeContext"] = story_context()
    return value


@pytest.mark.parametrize("locale", ["en-US", "de-DE", "es-ES"])
@pytest.mark.parametrize("context", [False, True])
def test_every_new_author_field_uses_story_projection_without_changing_source(locale, context):
    incoming = data(locale, context=context)
    original = copy.deepcopy(incoming)
    binding = outline.setup._binding(incoming)
    values = json.loads(story.facts_json(binding["approved_source"]))
    assert values[0] == "Nera is an elf."
    note = values[1]
    assert note["developingFamiliarity"] == [{"area": "aptitude", "name": "Logic"},
                                            {"area": "skill", "name": "Archery"}]
    assert note["reducedContributions"] == [{"area": "skill group", "name": "Outdoors"}]
    assert note["namedQualityContributions"] == ["SINner (National)", "Distinctive Style"]
    project = outline.setup._plan(binding)
    plan = outline._plan(binding, 8)
    author = outline._author_plan(binding)
    assert outline.setup._plan_version(binding, project) == 2
    assert outline._plan_version(binding, plan) == 9
    for text in (project["premise"], project["background"], author["anecdotes"], plan[0]["summary"],
                 *[part["description"] for part in plan[0]["parts"]]):
        for forbidden in ("40 Karma", "+1", "+2", "+3", "-5", "Etiquette", "LOG", "contributions:v1",
                          "private:", "decision-id", "Knowledge-skill pool", "Wissensfertigkeiten-Pool",
                          "Reserva de conocimientos", "Other contributions unverified"):
            assert forbidden not in text
        for required in ("Logic", "Archery", "Outdoors", "SINner (National)", "Distinctive Style"):
            assert required in text
    assert "actionable steps" in project["tone"]  # explicitly fiction, not the provider's essay template
    assert "Long stories are welcome" in plan[0]["summary"]
    assert "450-650" not in json.dumps(plan) and "150-210" not in json.dumps(plan)
    assert "small immediate concern" in plan[0]["parts"][0]["description"]
    if context:
        assert "Military High School" in plan[0]["summary"]
        assert "never instructions or confirmed history" in plan[0]["summary"]
    assert all("Archery" not in json.dumps(chapter) for chapter in plan[1:])
    assert incoming == original
    assert binding["approved_source"] == original["approved_source"]


def test_continuation_preserves_current_and_prior_attribution_not_sorted_chronology():
    incoming = data()
    source = incoming["approved_source"]
    source["facts"][0]["decisionId"] = "previous"
    source["facts"].insert(0, {**source["facts"][1], "factId": "life-module:old:contributions:v1",
                             "decisionId": "previous"})
    binding = outline.setup._binding(incoming)
    values = json.loads(story.facts_json(source, continuation=True))
    assert len(values["currentDecisionFacts"]) == 1
    assert len(values["priorContextFacts"]) == 2
    assert values["currentDecisionFacts"][0] == values["priorContextFacts"][0]
    plan = outline._plan(binding, 1, continuation=True)
    assert json.dumps(values, ensure_ascii=False) in plan[0]["summary"]
    assert "Do not restart the birth or childhood opening" in plan[0]["summary"]
    assert source["facts"][1]["text"] == "Nera is an elf."


@pytest.mark.parametrize("amount,key", [("+0.5", "namedQualityContributions"),
                                       ("-0.5", "reducedQualityContributions"), ("0", None)])
def test_quality_sign_does_not_invent_final_severity(amount, key):
    text = ("Background — Confirmed module contributions, not final character ratings. "
            f"Quality Test Quality: level contribution {amount} (resolved cumulatively, not a final rating)")
    value = story._contribution(text)
    assert value == ({"background": "Background", key: ["Test Quality"]} if key else {"background": "Background"})


@pytest.mark.parametrize("locale,index", [("en-US", 0), ("de-DE", 1), ("es-ES", 2)])
def test_bounded_unavailable_summary_does_not_invent_reward_or_lose_background(locale, index):
    heading, cost, *_, warnings = story._FORMATS[index]
    assert story._contribution(f"{heading}. {cost}: 40 Karma. {warnings[0]}") == {}
    assert story._contribution(f"Background — {heading}. {warnings[0]}") == {"background": "Background"}


@pytest.mark.parametrize("patch", [
    {"factId": "life-module:private:contributions:v2"},
    {"text": "unexpected format"},
    {"text": contribution() + "; New effect: +999"},
    {"text": contribution().replace("+2", "two")},
    {"text": contribution().replace("40 Karma", "40 credits")},
    {"text": "Background — Confirmed module contributions, not final character ratings."},
    {"text": "Background — Confirmed module contributions, not final character ratings. Confirmed choice cost: 40 Karma."},
])
def test_unknown_contribution_format_stops_new_setup_before_browser_or_dispatch(tmp_path, form, patch):
    incoming = data()
    incoming["approved_source"]["facts"][-1].update(patch)
    with pytest.raises(ValueError, match="story_contribution"):
        outline.setup.prepare_framework(incoming, tmp_path)
    assert not form.clicks and not form.account_checks
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("context", [False, True])
def test_historical_framework_and_paid_outline_remain_exact_without_new_actions(tmp_path, surface, context):
    _, root, _, calls = surface
    incoming = {**data(context=context), "outline_activation_approved": True, "maximum_book_credits": 1}
    binding = outline.setup._binding(incoming)
    provider = {"provider_book_id": "existing-book", "book_title": "Nera's private book"}
    setup_path = root / ("setup-" + binding["book_ref"] + ".json")
    outline_path = root / ("outline-" + binding["book_ref"] + ".json")
    old_framework = outline.setup._plan(binding, version=1)
    old_outline = outline._plan(binding, 8, version=8 if context else 7)
    outline.writer._save(setup_path, {"binding": binding, "plan": old_framework, "state": "framework_dispatched",
        "provider": provider, "browser_session": incoming["browser_session"], "page_epoch": 1000})
    # An unactivated old framework needs reconciliation, not a mixed new recipe.
    assert outline.prepare_first_chapter(incoming, tmp_path)["state"] == "outline_reconciliation_required"
    assert not calls
    outline.writer._save(outline_path, {"binding": binding, "provider": provider, "plan": old_outline,
        "before": [], "state": "first_chapter_prepared", "browser_session": incoming["browser_session"], "page_epoch": 1000})
    original = (setup_path.read_bytes(), outline_path.read_bytes())
    assert outline.retained_first_chapter(incoming, tmp_path)["expected_outline"] == old_outline[0]["parts"]
    assert outline.setup.prepare_framework(incoming, tmp_path)["state"] == "framework_bound_needs_outline_review"
    assert (setup_path.read_bytes(), outline_path.read_bytes()) == original
    assert not calls


def test_unknown_current_projection_does_not_strand_historical_framework(tmp_path, form):
    incoming = data()
    incoming["approved_source"]["facts"][-1]["text"] = "An older opaque value."
    binding = outline.setup._binding(incoming)
    root = outline.writer._private_root(tmp_path)
    path = root / ("setup-" + binding["book_ref"] + ".json")
    outline.writer._save(path, {"binding": binding, "plan": outline.setup._plan(binding, version=1),
        "state": "framework_dispatched", "browser_session": incoming["browser_session"], "page_epoch": 1000,
        "provider": {"provider_book_id": "existing-book", "book_title": "Nera's private book"}})
    before = path.read_bytes()
    assert outline.setup.prepare_framework(incoming, tmp_path)["state"] == "framework_bound_needs_outline_review"
    assert path.read_bytes() == before and not form.clicks


def test_retained_next_chapter_recognizes_version_nine_without_repreparing():
    incoming = data()
    binding = outline.setup._binding(incoming)
    previous_plan = outline._plan(binding, 8, version=7)
    previous = {**outline._prepared(binding, {"provider_book_id": "book", "book_title": "Book"}, previous_plan),
                "generation_approved": True}
    incoming["work_id"] = "1" * 64 + "." + "9" * 64
    source, plan = nxt._plan(incoming, previous)
    record = {"source": source, "previous": nxt.writer._binding(previous), "state": "prepared", "plan": plan}
    assert nxt._retained_plan(incoming, previous, source, record) == plan
    assert "40 Karma" not in json.dumps(plan)
    changed = copy.deepcopy(record)
    changed["plan"]["chapter"]["summary"] += " changed"
    with pytest.raises(RuntimeError, match="retained_mismatch"):
        nxt._retained_plan(incoming, previous, source, changed)
