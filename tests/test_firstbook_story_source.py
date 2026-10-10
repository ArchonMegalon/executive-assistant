from __future__ import annotations

import copy
import hashlib
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
@pytest.mark.parametrize("contributions", [False, True])
def test_runner_name_missing_from_fact_list_reaches_every_new_authoring_surface(locale, contributions):
    incoming = data(locale) if contributions else packet()
    source = incoming["approved_source"]
    source["locale"] = locale
    source["runnerName"] = 'Runner "Nord"'
    source["facts"][0]["text"] = "Human, childhood in a repair shop."
    original = copy.deepcopy(incoming)
    binding = outline.setup._binding(incoming)
    project = outline.setup._plan(binding)
    chapter = outline._plan(binding, 8)[0]
    author = outline._author_plan(binding)
    identity = json.dumps({"runnerName": source["runnerName"]}, ensure_ascii=False)
    for value in (project["premise"], project["background"], project["tone"], author["anecdotes"],
                  chapter["summary"], *[part["description"] for part in chapter["parts"]]):
        assert identity in value
        assert "Use this exact runnerName" in value
        assert "generic name is intentional" in value
        assert "Never invent a protagonist name/alias" in value
        assert "private-workspace-id" not in value and "chapter-id" not in value
    assert incoming == original


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
    assert outline.setup._plan_version(binding, project) == 4
    assert outline._plan_version(binding, plan) == 13
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
    source, plan = nxt._plan(incoming, previous, version=9)
    record = {"source": source, "previous": nxt.writer._binding(previous), "state": "prepared", "plan": plan}
    assert nxt._retained_plan(incoming, previous, source, record) == plan
    assert "40 Karma" not in json.dumps(plan)
    changed = copy.deepcopy(record)
    changed["plan"]["chapter"]["summary"] += " changed"
    with pytest.raises(RuntimeError, match="retained_mismatch"):
        nxt._retained_plan(incoming, previous, source, changed)


@pytest.mark.parametrize("locale,spoken", [("en-US", "Hold the door"),
                                          ("de-DE", "Halt die Tür"),
                                          ("es-ES", "Sujeta la puerta")])
@pytest.mark.parametrize("context", [False, True])
def test_new_recipe_models_action_dialogue_and_local_resolution_without_a_biography(locale, spoken, context):
    incoming = data(locale, context=context)
    before = copy.deepcopy(incoming)
    binding = outline.setup._binding(incoming)
    author = outline._author_plan(binding, version=10)
    assert spoken in author["sample"]
    assert "not biography or events" in author["anecdotes"]
    for continuation in (False, True):
        plan = outline._plan(binding, 8, version=10, continuation=continuation)
        for text in (author["anecdotes"], plan[0]["summary"],
                     *[part["description"] for part in plan[0]["parts"]]):
            assert "A small local problem may be resolved" in text
            assert "incidental dialogue" in text
            assert "not new family, trusted contacts, possessions" in text
            assert "Do not borrow the style sample's" in text
        assert "dialogue" in plan[0]["parts"][1]["description"]
        assert "local problem" in plan[0]["parts"][2]["description"]
        assert "Hold the door" not in json.dumps(plan)  # sample is not an outline event
        assert all("local problem" not in json.dumps(slot) for slot in plan[1:])
    assert incoming == before


@pytest.mark.parametrize("locale,context,expected", [
    ("en-US", False, "26d7f2452c30f56d0e0d458fe8aba388a6bca21e591c990f49e6bbfeb103b716"),
    ("en-US", True, "796843657041bd917cd29c0bd3fc256b61fb061421e274bf6dfce77c56ecc317"),
    ("de-DE", False, "292eef32ec1dab3172159e5199e658c790a7c74158aa13a16c4b7aeabeefa77b"),
    ("de-DE", True, "457340211f60e8314aa03a13f64cc26f828c8235258c84e2ad754cd5af45bb5a"),
    ("es-ES", False, "f7d9f71b612d72ea4d4b28b4c48104c9a1163bdd7048a948d77894bc0db4f586"),
    ("es-ES", True, "31d774acc4f0cec1f8ebf14c5b16b90a927acb3d6dc03f3bf3f896023f8fe6d3"),
])
def test_paid_version_nine_outline_and_author_style_keep_exact_historical_bytes(locale, context, expected):
    binding = outline.setup._binding(data(locale, context=context))
    plan = outline._plan(binding, 8, version=9)
    old = {"outline": plan, "author": outline._author_plan(binding, version=9)}
    assert hashlib.sha256(json.dumps(old, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == expected
    assert outline._plan_version(binding, plan) == 9


def test_next_chapter_recognizes_retained_scene_recipe_without_adding_context():
    incoming = data()
    binding = outline.setup._binding(incoming)
    previous = {**outline._prepared(binding, {"provider_book_id": "book", "book_title": "Book"},
                                  outline._plan(binding, 8, version=9)), "generation_approved": True}
    incoming["work_id"] = "1" * 64 + "." + "9" * 64
    source, plan = nxt._plan(incoming, previous, version=12)
    assert "A small local problem may be resolved" in plan["chapter"]["summary"]
    record = {"source": source, "previous": nxt.writer._binding(previous), "state": "prepared", "plan": plan}
    assert nxt._retained_plan(incoming, previous, source, record) == plan


@pytest.mark.parametrize("locale", ["en-US", "de-DE", "es-ES"])
@pytest.mark.parametrize("context", [False, True])
def test_grounded_scene_keeps_childhood_and_skill_scale_explicit_in_every_section(locale, context):
    incoming = data(locale, context=context)
    before = copy.deepcopy(incoming)
    binding = outline.setup._binding(incoming)
    plan = outline._plan(binding, 8)
    for text in (outline._author_plan(binding)["anecdotes"], plan[0]["summary"],
                 *[part["description"] for part in plan[0]["parts"]]):
        assert "Archery does not supply a bow" in text
        assert "Survival does not supply a kit" in text
        assert "interest in trains is not mechanical training" in text
        assert "ask qualified staff" in text
        assert "not a guessed past journey" in text
    for part in plan[0]["parts"]:
        text = part["description"]
        assert "inside childhood" in text
        assert "birth background" in text
        assert "not an independent adult" in text
        assert "Do not assign an exact age" in text
        assert len(text) <= outline.writer.MAX_DESCRIPTION_CHARS
    later = outline._plan(binding, 1, continuation=True)
    for part in later[0]["parts"]:
        text = part["description"]
        assert "currentDecisionFacts are this chapter's confirmed stage" in text
        assert "inside childhood" not in text
        assert "Archery does not supply a bow" in text
    assert all("inside childhood" not in json.dumps(slot) for slot in plan[1:])
    assert incoming == before


@pytest.mark.parametrize("locale,context,expected", [
    ("en-US", False, "bca83e8bcc7278a85fe4ad86368dcc1e1e0e7ff28fdbe55e76a73981d4bf9e46"),
    ("en-US", True, "2c6ac1b684f179475362b9392a7a7dabdd5c57abd97946465250e66734fd1c7a"),
    ("de-DE", False, "2de6db5b04c58321c42b85959b6578a616b5bbfa42be38dd964c7580fabd6219"),
    ("de-DE", True, "2627ade5376243d6e2e0cbbed6c867bf7b89c17cef76b5012a7ddfb4cb179c9e"),
    ("es-ES", False, "e0731e548295a489d49a65652fd61a76f4f94ce4457fe58977ac1f115424a1ad"),
    ("es-ES", True, "697d67cc12450ed26bfd909885cf3daacd12fe533849f9655cd2cdb1d4c8011b"),
])
def test_admitted_recipe_ten_keeps_outline_author_and_continuation_bytes(locale, context, expected):
    binding = outline.setup._binding(data(locale, context=context))
    plan = outline._plan(binding, 8, version=10)
    value = {"outline": plan, "author": outline._author_plan(binding, version=10),
             "continuation": outline._plan(binding, 1, version=10, continuation=True)}
    assert hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == expected
    assert outline._plan_version(binding, plan) == 10


def test_next_chapter_retains_ten_but_new_request_uses_grounding_without_restarting_childhood():
    incoming = data()
    binding = outline.setup._binding(incoming)
    previous = {**outline._prepared(binding, {"provider_book_id": "book", "book_title": "Book"},
                                  outline._plan(binding, 8, version=10)), "generation_approved": True}
    incoming["work_id"] = "1" * 64 + "." + "9" * 64
    source, admitted = nxt._plan(incoming, previous, version=10)
    record = {"source": source, "previous": nxt.writer._binding(previous), "state": "prepared", "plan": admitted}
    assert nxt._retained_plan(incoming, previous, source, record) == admitted
    _, new = nxt._plan(incoming, previous)
    assert new != admitted
    assert "Archery does not supply a bow" in new["chapter"]["summary"]
    assert "inside childhood" not in new["chapter"]["summary"]


@pytest.mark.parametrize("locale,reflection,dialogue", [
    ("en-US", "Robin wondered", "Robin said"),
    ("de-DE", "Robin fragte sich", "sagte Robin"),
    ("es-ES", "Robin se preguntó", "dijo Robin"),
])
@pytest.mark.parametrize("context", [False, True])
def test_natural_voice_reaches_actual_style_field_sample_and_each_section(locale, reflection, dialogue, context):
    incoming = data(locale, context=context)
    original = copy.deepcopy(incoming)
    binding = outline.setup._binding(incoming)
    framework = outline.setup._plan(binding)
    author = outline._author_plan(binding)
    assert reflection in author["sample"] and dialogue in author["sample"]
    assert author["sample"] != story.SCENE_SAMPLES[locale[:2]]
    # The provider uses only the first 2,000 characters of its sample.
    assert 600 < len(author["sample"]) <= 2000
    for continuation in (False, True):
        plan = outline._plan(binding, 8, continuation=continuation)
        for text in (framework["tone"], author["anecdotes"], plan[0]["summary"],
                     *[part["description"] for part in plan[0]["parts"]]):
            assert "varied sentence lengths" in text
            assert "adjectives and adverbs" in text
            assert "inner thoughts" in text
            assert "clearly attributed dialogue" in text
            assert "not disembodied hands" in text
            assert "not a biography" in text
        assert "singular they" in framework["tone"]
        for part in plan[0]["parts"]:
            assert len(part["description"]) <= outline.writer.MAX_DESCRIPTION_CHARS
            if not continuation:
                assert part["description"].index("inside childhood") < part["description"].index("Quoted character reference")
        assert all("inner thoughts" not in json.dumps(slot) for slot in plan[1:])
    assert incoming == original


@pytest.mark.parametrize("locale,context,expected", [
    ("en-US", False, "f053bd5e59dc7d2ac90f3e7887590e8c37113d93a767cafc533fe39df9598e4a"),
    ("en-US", True, "70fe41136ffc1958959badf2a725dedd7eee4c4d37e89a2925d6e2583d49130b"),
    ("de-DE", False, "519601574810c3cc4850ef9c7ac9214a85996c1483270630689c08b2518bd8be"),
    ("de-DE", True, "8ade60a8df94c37a18f9edc7fc9a8ee1cf0ec8db301fe6e1ef7c56901caddf8f"),
    ("es-ES", False, "47284aa14c4eb3a43ff8d770c2ca8137b5d7e91959ec0ab195983230e207fcac"),
    ("es-ES", True, "2f3478cb97abecbcff21e055eeb1fea030004574c2061561e6320b81a8e2f56a"),
])
def test_admitted_recipe_eleven_and_framework_two_keep_exact_bytes(locale, context, expected):
    binding = outline.setup._binding(data(locale, context=context))
    plan = outline._plan(binding, 8, version=11)
    value = {"framework": outline.setup._plan(binding, version=2), "outline": plan,
             "author": outline._author_plan(binding, version=11),
             "continuation": outline._plan(binding, 1, version=11, continuation=True)}
    assert hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == expected
    assert outline._plan_version(binding, plan) == 11
    assert outline.setup._plan_version(binding, value["framework"]) == 2


def test_old_style_framework_without_outline_is_not_paid_but_admitted_eleven_can_resume(tmp_path, surface):
    _, root, _, calls = surface
    incoming = {**data(), "outline_activation_approved": True, "maximum_book_credits": 1}
    binding = outline.setup._binding(incoming)
    provider = {"provider_book_id": "existing-book", "book_title": "Nera's private book"}
    setup_path = root / ("setup-" + binding["book_ref"] + ".json")
    outline_path = root / ("outline-" + binding["book_ref"] + ".json")
    outline.writer._save(setup_path, {"binding": binding, "plan": outline.setup._plan(binding, version=2),
        "state": "framework_dispatched", "provider": provider, "browser_session": incoming["browser_session"], "page_epoch": 1000})
    before = setup_path.read_bytes()
    assert outline.prepare_first_chapter(incoming, tmp_path)["state"] == "outline_reconciliation_required"
    assert not calls and setup_path.read_bytes() == before and not outline_path.exists()
    old_plan = outline._plan(binding, 8, version=11)
    outline.writer._save(outline_path, {"binding": binding, "provider": provider, "plan": old_plan,
        "before": [], "state": "first_chapter_prepared", "browser_session": incoming["browser_session"], "page_epoch": 1000})
    old_bytes = outline_path.read_bytes()
    assert outline.retained_first_chapter(incoming, tmp_path)["expected_outline"] == old_plan[0]["parts"]
    assert outline.prepare_first_chapter(incoming, tmp_path)["state"] == "first_chapter_prepared"
    assert calls == ["reopen_paid"]  # no outline/style edits or credit dispatch
    assert setup_path.read_bytes() == before and outline_path.read_bytes() == old_bytes


def test_next_chapter_recognizes_new_twelve_and_retained_eleven_without_style_rewrite():
    incoming = data()
    binding = outline.setup._binding(incoming)
    previous = {**outline._prepared(binding, {"provider_book_id": "book", "book_title": "Book"},
                                  outline._plan(binding, 8, version=11)), "generation_approved": True}
    incoming["work_id"] = "1" * 64 + "." + "9" * 64
    for version in (11, 12):
        source, plan = nxt._plan(incoming, previous, version=version)
        record = {"source": source, "previous": nxt.writer._binding(previous), "state": "prepared", "plan": plan}
        assert nxt._retained_plan(incoming, previous, source, record) == plan
    _, new = nxt._plan(incoming, previous)
    assert "inner thoughts" in new["chapter"]["summary"]
    assert "inside childhood" not in new["chapter"]["summary"]
