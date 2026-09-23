from __future__ import annotations

import copy
import json

import pytest

from scripts import firstbook_project_prepare as prepare
from scripts import firstbook_chapter_write as writer


def packet():
    return {"work_id": "1" * 64 + "." + "2" * 64, "book_ref": "3" * 64,
            "account_sha256": "4" * 64, "source_packet_sha256": "5" * 64,
            "framework_generation_approved": True, "browser_session": "owned-project-setup",
            "approved_source": {"workspaceId": "private-workspace-id", "chapterId": "chapter-id",
                "chapterDigest": "6" * 64, "acceptedDecisionId": "decision-id", "locale": "de-DE",
                "runnerName": "Nera", "facts": [
                    {"factId": "fact-id", "decisionId": "decision-id", "text": "Nera is an elf."}]}}


class Form:
    def __init__(self):
        self.step = 0
        self.values = {key: "" for key in prepare._FIELDS}
        self.selects = ["Thought Leadership & Authority", "English"]
        self.clicks = []
        self.account_checks = []
        self.page_epoch = 1000
        self.submitted = False

    def inspect(self, session):
        active = ("title", "premise", "audience") if self.step == 1 else ("background", "beliefs", "tone", "references")
        return {"origin": "https://app.firstbook.ai", "formCount": 0 if self.step == 0 else 1,
                "ideaCount": 1 if self.step == 0 else 0,
                "fields": {key: {"count": 1 if key in active else 0,
                                 "value": self.values[key] if key in active else None} for key in self.values},
                "selects": self.selects if self.step == 1 else [],
                "nextCount": 1 if self.step == 1 else 0, "nextEnabled": self.step == 1,
                "generateCount": 1 if self.step == 2 else 0, "generateEnabled": self.step == 2,
                "pageEpoch": self.page_epoch, "frameworkVisible": self.submitted}

    def click(self, session, selector):
        self.clicks.append(selector)
        if "I have an idea" in selector:
            self.step = 1
        elif "'Next'" in selector:
            self.step = 2
        elif "Generate Book Framework" in selector:
            self.submitted = True

    def browser(self, session, *args):
        assert args[0] == "select"
        self.selects[0 if "Primary Goal" in args[2] else 1] = args[4]


@pytest.fixture
def form(monkeypatch):
    browser = Form()
    monkeypatch.setattr(prepare, "_inspect", browser.inspect)
    monkeypatch.setattr(prepare, "_fill", lambda session, key, value: browser.values.update({key: value}))
    monkeypatch.setattr(prepare.capture, "_click", browser.click)
    monkeypatch.setattr(prepare.capture, "_browser", browser.browser)
    monkeypatch.setattr(prepare.capture, "_open_dashboard", lambda *args: browser.account_checks.append(args))
    monkeypatch.setattr(writer, "_inspect", lambda *args: {"generating": False})
    return browser


def test_two_step_form_uses_exact_source_and_never_pays_or_writes(tmp_path, form):
    result = prepare.prepare_framework(packet(), tmp_path)
    assert result["state"] == "framework_dispatched"
    assert result["chapter_writing_ready"] is False and result["publication_authorized"] is False
    assert form.values == {key: prepare._plan(prepare._binding(packet()))[key] for key in prepare._FIELDS}
    assert form.selects == ["Legacy & Personal Story", "German"]
    assert len(form.account_checks) == 1
    assert len(form.clicks) == 4
    assert not any(any(word in click for word in ("Lock", "Pay", "Buy", "Write Chapter", "Approve")) for click in form.clicks)
    path = tmp_path / "firstbook-private-writes" / ("setup-" + packet()["book_ref"] + ".json")
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["state"] == "framework_dispatched"
    before = list(form.clicks)
    assert prepare.prepare_framework(packet(), tmp_path)["state"] == "framework_observed_needs_project_binding"
    assert form.clicks == before


@pytest.mark.parametrize("lost_at", ["Start a New Book", "'Next'", "Generate Book Framework"])
def test_lost_response_leaves_fence_and_cannot_create_or_submit_twice(tmp_path, form, monkeypatch, lost_at):
    def click(session, selector):
        retained = next((tmp_path / "firstbook-private-writes").glob("setup-*.json"))
        state = json.loads(retained.read_text())["state"]
        if lost_at in selector:
            assert state == {"Start a New Book": "intake_started", "'Next'": "concept_continue_dispatched",
                             "Generate Book Framework": "framework_dispatched"}[lost_at]
            form.clicks.append(selector)
            raise RuntimeError("lost_response")
        form.click(session, selector)
    monkeypatch.setattr(prepare.capture, "_click", click)
    with pytest.raises(RuntimeError, match="lost_response"):
        prepare.prepare_framework(packet(), tmp_path)
    before = list(form.clicks)
    assert prepare.prepare_framework(packet(), tmp_path)["state"] == "reconciliation_required"
    assert form.clicks == before and len(form.account_checks) == 1


@pytest.mark.parametrize("key,value", [("work_id", "a" * 64 + "." + "b" * 64),
    ("source_packet_sha256", "f" * 64), ("account_sha256", "e" * 64),
    ("approved_source", {**packet()["approved_source"], "locale": "es-ES"})])
def test_existing_runner_setup_cannot_change_binding(tmp_path, form, key, value):
    prepare.prepare_framework(packet(), tmp_path)
    before = list(form.clicks)
    with pytest.raises(RuntimeError, match="retained_binding_mismatch"):
        prepare.prepare_framework({**packet(), key: value}, tmp_path)
    assert form.clicks == before


def test_missing_upstream_admission_never_touches_browser(tmp_path, form):
    assert prepare.prepare_framework(packet(), tmp_path, allow_new_dispatch=False)["state"] == "reconciliation_required"
    assert not form.clicks and not form.account_checks
    assert not list(tmp_path.rglob("*.json"))


def test_active_generation_never_navigates(tmp_path, form, monkeypatch):
    monkeypatch.setattr(writer, "_inspect", lambda *args: {"generating": True})
    assert prepare.prepare_framework(packet(), tmp_path)["state"] == "provider_busy"
    assert not form.clicks and not form.account_checks


def test_filled_new_form_cannot_overwrite_another_source(tmp_path, form):
    form.values["title"] = "Another book"
    with pytest.raises(RuntimeError, match="form_mismatch"):
        prepare.prepare_framework(packet(), tmp_path)
    assert not any("'Next'" in click or "Generate Book Framework" in click for click in form.clicks)


def test_direct_blank_concept_entry_does_not_wait_for_absent_idea_control(tmp_path, form):
    form.step = 1
    assert prepare.prepare_framework(packet(), tmp_path)["state"] == "framework_dispatched"
    assert not any("I have an idea" in action for action in form.clicks)


def test_resumed_author_form_is_not_treated_as_a_new_blank_book(tmp_path, form):
    form.step = 2
    with pytest.raises(RuntimeError, match="form_mismatch"):
        prepare.prepare_framework(packet(), tmp_path)
    assert len(form.clicks) == 1
    assert form.values == {key: "" for key in prepare._FIELDS}


def test_input_uses_real_events_for_provider_controlled_react_form(monkeypatch):
    calls = []
    monkeypatch.setattr(prepare.capture, "_browser", lambda *args: calls.append(args))
    prepare._fill("owned-setup", "title", "Ivo — Vor dem ersten Run")
    assert calls == [("owned-setup", "input", "--selector", prepare._FIELDS["title"],
                      "--text", "Ivo — Vor dem ersten Run", "--type-interval", "0")]
    assert "--mode" not in calls[0]  # DOM-only fill did not persist through React rerenders.


def test_failed_private_write_never_enters_new_book(tmp_path, form, monkeypatch):
    def full(*args):
        raise OSError("disk_full")
    monkeypatch.setattr(writer, "_save", full)
    with pytest.raises(OSError, match="disk_full"):
        prepare.prepare_framework(packet(), tmp_path)
    assert not form.clicks


def test_bound_book_is_reused_not_silently_replaced(tmp_path, form):
    root = writer._private_root(tmp_path) / "books"
    root.mkdir(mode=0o700)
    writer._save(root / (packet()["book_ref"] + ".json"), {"existing": True})
    with pytest.raises(RuntimeError, match="already_bound"):
        prepare.prepare_framework(packet(), tmp_path)
    assert not form.clicks and not form.account_checks


def test_framework_observation_requires_same_live_page_and_session(tmp_path, form):
    prepare.prepare_framework(packet(), tmp_path)
    assert prepare.prepare_framework({**packet(), "browser_session": "different-session"}, tmp_path)["state"] == "reconciliation_required"
    form.page_epoch += 1
    assert prepare.prepare_framework(packet(), tmp_path)["state"] == "reconciliation_required"
    assert len(form.clicks) == 4


def project_packet():
    return {**packet(), "browser_session": "cold-owned-session",
            "framework_project_binding_approved": True,
            "framework_project": {"provider_book_id": "existing-provider-book", "book_title": "Nera's beginning"}}


def overview(data):
    plan = prepare._plan(prepare._binding(data))
    return {"origin": "https://app.firstbook.ai", "titles": [data["framework_project"]["book_title"]],
            "ids": [data["framework_project"]["provider_book_id"]], "reviewOutlineCount": 1,
            "context": {label: {"count": 1, "value": plan[key]}
                        for label, key in (("Premise", "premise"), ("Goal", "goal"), ("Audience", "audience"))}}


def mock_overview(monkeypatch, observed):
    monkeypatch.setattr(prepare.capture, "_eval", lambda session, expression:
        {"overviewControls": 1} if "overviewControls" in expression else observed)
    def wait(session, *args):
        assert args[:3] == ("wait", "selector", "--selector")
        assert "//h1[normalize-space(.)=" in args[3]
        assert args[4:] == ("--timeout", "15000")
    monkeypatch.setattr(prepare.capture, "_browser", wait)


def test_cold_reconciliation_binds_exact_existing_project_without_generating(tmp_path, form, monkeypatch):
    prepare.prepare_framework(packet(), tmp_path)
    data = project_packet()
    mock_overview(monkeypatch, overview(data))
    before = len(form.clicks)
    result = prepare.prepare_framework(data, tmp_path, allow_new_dispatch=False)
    assert result["state"] == "framework_bound_needs_outline_review"
    assert result["chapter_writing_ready"] is False and result["publication_authorized"] is False
    assert form.clicks[before:] == ["xpath=//h3[normalize-space(.)=\"Nera's beginning\"]",
                                   "xpath=//button[normalize-space(.)='Book Overview']"]
    assert form.account_checks[-1] == (data["browser_session"], data["account_sha256"])
    stored = json.loads((tmp_path / "firstbook-private-writes" / ("setup-" + data["book_ref"] + ".json")).read_text())
    assert stored["provider"] == data["framework_project"]
    before = list(form.clicks)
    assert prepare.prepare_framework(data, tmp_path)["state"] == "framework_bound_needs_outline_review"
    assert form.clicks == before
    data["framework_project"]["provider_book_id"] = "different-book"
    with pytest.raises(RuntimeError, match="retained_project_mismatch"):
        prepare.prepare_framework(data, tmp_path)
    assert form.clicks == before


@pytest.mark.parametrize("field", ["title", "id", "duplicate_id", "premise", "goal", "audience", "already_paid"])
def test_reconciliation_rejects_mismatched_project_and_never_regenerates(tmp_path, form, monkeypatch, field):
    prepare.prepare_framework(packet(), tmp_path)
    data = project_packet()
    observed = overview(data)
    if field == "title":
        observed["titles"] = ["Different book"]
    elif field == "id":
        observed["ids"] = ["different-id"]
    elif field == "duplicate_id":
        observed["ids"] *= 2
    elif field == "already_paid":
        observed["reviewOutlineCount"] = 0
    else:
        observed["context"][field.capitalize()]["value"] = "Other source"
    mock_overview(monkeypatch, observed)
    before = len(form.clicks)
    with pytest.raises(RuntimeError, match="existing_project_mismatch"):
        prepare.prepare_framework(data, tmp_path)
    assert not any("Generate" in action or "Start a New" in action for action in form.clicks[before:])
    stored = json.loads((tmp_path / "firstbook-private-writes" / ("setup-" + data["book_ref"] + ".json")).read_text())
    assert "provider" not in stored


def test_project_reconciliation_requires_existing_dispatch_and_explicit_mapping_admission(tmp_path, form):
    data = project_packet()
    assert prepare.prepare_framework(data, tmp_path)["state"] == "reconciliation_required"
    assert not form.clicks and not form.account_checks
    data["framework_project_binding_approved"] = False
    with pytest.raises(ValueError, match="binding_not_admitted"):
        prepare.prepare_framework(data, tmp_path)
    assert not form.clicks and not form.account_checks


def test_reconciliation_does_not_navigate_away_from_active_generation(tmp_path, form, monkeypatch):
    prepare.prepare_framework(packet(), tmp_path)
    before = list(form.clicks)
    monkeypatch.setattr(writer, "_inspect", lambda *args: {"generating": True})
    assert prepare.prepare_framework(project_packet(), tmp_path)["state"] == "provider_busy"
    assert form.clicks == before


def test_ready_owned_framework_can_discover_exact_provider_without_operator_copy(tmp_path, form, monkeypatch):
    data = {**packet(), "framework_project_discovery_approved": True}
    prepare.prepare_framework(data, tmp_path)
    expected = {"provider_book_id": "new-provider-book", "book_title": prepare._plan(prepare._binding(data))["title"]}
    mock_overview(monkeypatch, overview({**data, "framework_project": expected}))
    before = len(form.clicks)
    result = prepare.prepare_framework(data, tmp_path, allow_new_dispatch=False)
    assert result["state"] == "framework_bound_needs_outline_review"
    stored = writer._load(tmp_path / "firstbook-private-writes" / ("setup-" + data["book_ref"] + ".json"))
    assert stored["provider"] == expected
    assert not any(x in click for click in form.clicks[before:] for x in ("Generate", "Lock", "Start writing", "Approve"))
    previous = list(form.clicks)
    assert prepare.prepare_framework(data, tmp_path)["state"] == "framework_bound_needs_outline_review"
    assert form.clicks == previous


@pytest.mark.parametrize("change", ["session", "page", "unfinished", "busy"])
def test_discovery_cannot_leave_unready_or_foreign_framework(tmp_path, form, monkeypatch, change):
    data = {**packet(), "framework_project_discovery_approved": True}
    prepare.prepare_framework(data, tmp_path)
    if change == "session": data["browser_session"] = "other-owned-session"
    elif change == "page": form.page_epoch += 1
    elif change == "unfinished": form.submitted = False
    else: monkeypatch.setattr(writer, "_inspect", lambda *a: {"generating": True})
    monkeypatch.setattr(prepare, "_observe_existing_framework", lambda *a: pytest.fail("must not navigate"))
    expected = {"busy": "provider_busy", "unfinished": "framework_observation_pending"}.get(change, "reconciliation_required")
    assert prepare.prepare_framework(data, tmp_path)["state"] == expected


@pytest.mark.parametrize("change", ["title", "ids", "context", "reviewOutlineCount"])
def test_discovery_does_not_bind_ambiguous_or_wrong_source_project(tmp_path, form, monkeypatch, change):
    data = {**packet(), "framework_project_discovery_approved": True}
    prepare.prepare_framework(data, tmp_path)
    expected = {"provider_book_id": "new-provider-book", "book_title": prepare._plan(prepare._binding(data))["title"]}
    value = overview({**data, "framework_project": expected})
    if change == "title": value["titles"] = ["other book"]
    elif change == "ids": value["ids"] *= 2
    elif change == "context": value["context"]["Premise"]["value"] = "other facts"
    else: value["reviewOutlineCount"] = 0
    mock_overview(monkeypatch, value)
    with pytest.raises(RuntimeError, match="existing_project_mismatch"):
        prepare.prepare_framework(data, tmp_path)
    stored = writer._load(tmp_path / "firstbook-private-writes" / ("setup-" + data["book_ref"] + ".json"))
    assert "provider" not in stored


@pytest.mark.parametrize("locale,language", [("de-DE", "German"), ("en", "English"), ("es-ES", "Spanish")])
def test_provider_plan_contains_only_reading_facts_not_private_ids(locale, language):
    data = packet()
    data["approved_source"]["locale"] = locale
    plan = prepare._plan(prepare._binding(data))
    text = json.dumps(plan)
    assert plan["language"] == language
    assert "Nera is an elf." in text
    for excluded in ("private-workspace-id", "chapter-id", "decision-id", "fact-id", "chummer.run", "6" * 64, "3" * 64):
        assert excluded not in text


@pytest.mark.parametrize("change", [
    lambda p: p.update(framework_generation_approved=False),
    lambda p: p["approved_source"].update(locale="fr-FR"),
    lambda p: p["approved_source"].update(characterXml="private"),
    lambda p: p["approved_source"].update(facts=[]),
    lambda p: p["approved_source"]["facts"].append(copy.deepcopy(p["approved_source"]["facts"][0])),
])
def test_invalid_source_or_consent_does_not_touch_browser(tmp_path, form, change):
    data = packet()
    change(data)
    with pytest.raises(ValueError):
        prepare.prepare_framework(data, tmp_path)
    assert not form.clicks and not form.account_checks and list(tmp_path.iterdir()) == []
