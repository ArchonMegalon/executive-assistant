from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import firstbook_chapter_capture as capture


@pytest.mark.parametrize("text,expected", [("My Profile\nBook Credits\n25\nCredits per Month\n25", 25),
    ("My Profile\nCREDIT BALANCE\n24\ncredits available\nAppSumo Lifetime Deal\nTier 5\n25\ncredits/mo\nLAST REFILL\n2026-10", 24),
    ("My Profile\nCredits\n0\nLast Refill\n2026-10", 0)])
def test_credit_probe_uses_visible_balance_not_monthly_allowance(monkeypatch, text, expected):
    seen = []
    monkeypatch.setattr(capture, "_account_profile", lambda session, account:
        seen.append((session, account)) or text)
    monkeypatch.setattr(capture, "_click", lambda *args: None)
    assert capture.credit_balance("owned", "a" * 64) == expected
    assert seen == [("owned", "a" * 64)]


@pytest.mark.parametrize("text", ["Login", "My Profile\nCredits per Month\n25", "Credits\n-1",
    "Credits\nunknown", "Credits\n0\nCredits\n25", "Credits\n25/month"])
def test_missing_ambiguous_or_allowance_only_balance_is_not_zero(monkeypatch, text):
    monkeypatch.setattr(capture, "_account_profile", lambda *args: text)
    with pytest.raises(RuntimeError, match="credit_balance_unverified"):
        capture.credit_balance("owned", "a" * 64)


@pytest.mark.parametrize("args", [
    ("eval", "document.title"),
    ("click", "--selector", "button"),
    ("navigate", "https://app.firstbook.ai/"),
    ("wait", "selector", "--selector", "main"),
])
def test_browser_commands_never_automatically_handle_provider_dialogs(monkeypatch, args):
    def execute(command, **options):
        assert command == ["browser-act", "--no-auto-dialog", "--session", "owned", *args]
        assert options == {"capture_output": True, "text": True, "check": True, "timeout": 45}
        return subprocess.CompletedProcess(command, 0, stdout=" observed \n")
    monkeypatch.setattr(capture.subprocess, "run", execute)
    assert capture._browser("owned", *args) == "observed"


def test_dialog_blocked_command_stops_without_acceptance_retry_or_private_output(monkeypatch):
    calls = []
    def execute(command, **options):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command, output="private provider dialog")
    monkeypatch.setattr(capture.subprocess, "run", execute)
    with pytest.raises(RuntimeError, match="^firstbook_capture_browser_unavailable$") as error:
        capture._browser("owned", "eval", "document.title")
    assert len(calls) == 1 and "--no-auto-dialog" in calls[0]
    assert "private" not in str(error.value)


def packet() -> dict:
    return {
        "mode": capture.MODE, "browser_session": "owned-origin-test",
        "request_id": "chapter-request-1", "account_sha256": capture._sha("operator@example.test"),
        "provider_book_id": "private-book-id", "book_title": "Nera's Origin",
        "chapter_title": "The First Choice", "chapter_number": 1,
        "source_packet_sha256": "1" * 64, "narrative_locale": "de-DE",
    }


def observation() -> dict:
    return {
        "origin": "https://app.firstbook.ai", "bookTitles": ["Nera's Origin"],
        "chapterTitle": "The First Choice", "chapterNumber": 1, "chapterCount": 8,
        "surfaceCount": 1, "text": "The First Choice\n\nNera wartet an der Schwelle.",
        "reviewRequired": True, "editing": False, "approveControl": 1,
    }


def test_capture_and_retry_preserve_exact_unapproved_draft_without_browser_replay(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(capture, "_observe", lambda *args: calls.append(args) or observation())
    first = capture.capture_existing_chapter(packet(), tmp_path)
    second = capture.capture_existing_chapter(packet(), tmp_path)
    assert len(calls) == 1
    assert first["reused_capture"] is False and second["reused_capture"] is True
    assert first["text"] == second["text"] == observation()["text"]
    assert first["private_only"] is True
    for claim in ("full_manuscript_ready", "canon_approved", "language_verified",
                  "provider_generation_attempted", "publication_authorized"):
        assert first[claim] is False
    saved = Path(first["asset_path"])
    assert saved.stat().st_mode & 0o777 == 0o600
    assert saved.parent.stat().st_mode & 0o777 == 0o700
    assert "operator@example.test" not in saved.read_text()


@pytest.mark.parametrize("number", [1, 2, 8])
def test_numbered_provider_heading_preserves_exact_title_text_and_binding(monkeypatch, tmp_path, number):
    request = {**packet(), "chapter_number": number}
    heading = f"Chapter {number}: The First Choice"
    observed = {**observation(), "chapterNumber": number, "chapterTitle": heading,
                "text": heading + "\n\nNera wartet an der Schwelle."}
    monkeypatch.setattr(capture, "_observe", lambda *args: observed)
    first = capture.capture_existing_chapter(request, tmp_path)
    monkeypatch.setattr(capture, "_observe", lambda *args: pytest.fail("must reuse exact capture"))
    assert capture.capture_existing_chapter(request, tmp_path)["text"] == observed["text"]
    assert first["binding"] == capture._binding(request)
    assert first["text_sha256"] == capture._sha(observed["text"])
    assert first["canon_approved"] is False


@pytest.mark.parametrize("heading,number", [
    ("Chapter 1: The First Choice", 2), ("Chapter 3: The First Choice", 2),
    ("Chapter 02: The First Choice", 2), ("Chapter 2: Other", 2),
    ("Chapter 2: The First Choice extra", 2), ("The First Choice extra", 2),
    ("Chapter 2: Chapter 2: The First Choice", 2), ("chapter 2: The First Choice", 2),
    ("Chapter 2: The First Choice", 1),
])
def test_numbered_heading_cannot_relax_title_or_chapter_identity(monkeypatch, tmp_path, heading, number):
    monkeypatch.setattr(capture, "_observe", lambda *args:
        {**observation(), "chapterTitle": heading, "chapterNumber": number})
    with pytest.raises(RuntimeError, match="draft_not_verified"):
        capture.capture_existing_chapter({**packet(), "chapter_number": 2}, tmp_path)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("key,value", [
    ("source_packet_sha256", "2" * 64), ("account_sha256", "3" * 64),
    ("provider_book_id", "other-book"), ("book_title", "Another book"),
    ("chapter_number", 2), ("narrative_locale", "es-ES"),
])
def test_reused_request_cannot_change_source_owner_chapter_or_language(monkeypatch, tmp_path, key, value):
    monkeypatch.setattr(capture, "_observe", lambda *args: observation())
    capture.capture_existing_chapter(packet(), tmp_path)
    monkeypatch.setattr(capture, "_observe", lambda *args: pytest.fail("must not retry browser"))
    with pytest.raises(RuntimeError, match="retained_binding_mismatch"):
        capture.capture_existing_chapter({**packet(), key: value}, tmp_path)


@pytest.mark.parametrize("key,value", [
    ("origin", "https://not-firstbook.example.test"), ("bookTitles", ["Other"]),
    ("chapterTitle", "Other"), ("chapterNumber", 2), ("chapterCount", 0),
    ("surfaceCount", 2), ("reviewRequired", False), ("editing", True),
    ("approveControl", 0), ("text", ""), ("text", "é" * 100001),
])
def test_wrong_or_incomplete_surface_cannot_be_saved(tmp_path, monkeypatch, key, value):
    monkeypatch.setattr(capture, "_observe", lambda *args: {**observation(), key: value})
    with pytest.raises(RuntimeError, match="draft_not_verified"):
        capture.capture_existing_chapter(packet(), tmp_path)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("patch", [{"canon_approved": True}, {"publication_authorized": True},
                                  {"full_manuscript_ready": True}, {"text_sha256": "0" * 64}])
def test_corrupt_retained_capture_is_not_promoted_or_regenerated(tmp_path, monkeypatch, patch):
    monkeypatch.setattr(capture, "_observe", lambda *args: observation())
    first = capture.capture_existing_chapter(packet(), tmp_path)
    path = Path(first["asset_path"])
    path.write_text(json.dumps({**json.loads(path.read_text()), **patch}))
    monkeypatch.setattr(capture, "_observe", lambda *args: pytest.fail("must not retry browser"))
    with pytest.raises(RuntimeError, match="retained_binding_mismatch"):
        capture.capture_existing_chapter(packet(), tmp_path)


def test_readonly_observer_never_invokes_generation_or_approval(monkeypatch):
    commands = []
    answers = iter([
        {"origin": "https://app.firstbook.ai", "count": 1},
        {"origin": "https://app.firstbook.ai", "text": "My Profile\noperator@example.test"},
        {"origin": "https://app.firstbook.ai", "count": 1},
        {"origin": "https://app.firstbook.ai", "count": 1},
        {"origin": "https://app.firstbook.ai", "overviewControls": 0},
        {"origin": "https://app.firstbook.ai", "leaves": ["private-book-id"]},
        {"origin": "https://app.firstbook.ai", "count": 1},
        observation(),
    ])
    def browser(session, *args):
        commands.append(args)
        return json.dumps(next(answers)) if args[0] == "eval" else "ok"
    monkeypatch.setattr(capture, "_browser", browser)
    assert capture._observe("owned-origin-test", capture._binding(packet())) == observation()
    clicks = [cmd[-1] for cmd in commands if cmd[0] == "click"]
    assert clicks == [
        'button[title="Your Profile"]', "xpath=//button[normalize-space(.)='Back to Dashboard']",
        'xpath=//h3[normalize-space(.)="Nera\'s Origin"]',
        "xpath=//button[normalize-space(.)='Resume Writing']",
    ]


def test_account_mismatch_stops_before_book_navigation(monkeypatch):
    clicks = []
    monkeypatch.setattr(capture, "_browser", lambda *args: "ok")
    monkeypatch.setattr(capture, "_click", lambda session, selector: clicks.append(selector))
    monkeypatch.setattr(capture, "_eval", lambda *args: {"text": "wrong@example.test"})
    with pytest.raises(RuntimeError, match="account_mismatch"):
        capture._observe("owned-origin-test", capture._binding(packet()))
    assert clicks == ['button[title="Your Profile"]']


def duplicate_overviews(monkeypatch, identities, *, counts=(2, 2, 2)):
    clicks, visits = [], []
    counts = iter(counts)
    identities = iter(identities)
    def click(session, selector):
        if selector.startswith("xpath=//h3["):
            raise RuntimeError("firstbook_capture_control_not_unique")
        clicks.append(selector)
    def observe(session, expression):
        return {"ids": next(identities)} if "ids:" in expression else {"count": next(counts)}
    monkeypatch.setattr(capture, "_open_dashboard", lambda *a: visits.append("dashboard"))
    monkeypatch.setattr(capture, "_overview_route", lambda *a: visits.append("overview"))
    monkeypatch.setattr(capture, "_click", click)
    monkeypatch.setattr(capture, "_eval", observe)
    monkeypatch.setattr(capture, "_browser", lambda *a: pytest.fail("no other browser operation"))
    return clicks, visits


def test_duplicate_book_titles_require_the_exact_retained_provider_identity(monkeypatch):
    clicks, visits = duplicate_overviews(monkeypatch, [["other-book"], ["private-book-id"]])
    capture._open_overview("owned", "1" * 64, "Runner: Before the First Run", "private-book-id")
    assert clicks == ["xpath=(//h3[normalize-space(.)='Runner: Before the First Run'])[1]",
                      "xpath=(//h3[normalize-space(.)='Runner: Before the First Run'])[2]"]
    assert visits == ["dashboard", "overview", "dashboard", "overview"]


def test_duplicate_title_without_retained_project_still_fails_closed(monkeypatch):
    clicks, visits = duplicate_overviews(monkeypatch, [])
    with pytest.raises(RuntimeError, match="control_not_unique"):
        capture._open_overview("owned", "1" * 64, "Runner")
    assert clicks == [] and visits == ["dashboard"]


@pytest.mark.parametrize("identities,reason", [
    ([["other-book"], ["second-other"]], "book_mismatch"),
    ([[]], "project_identity_ambiguous"),
    ([["private-book-id", "other"]], "project_identity_ambiguous"),
    ([["other-book"], ["other-book"]], "project_identity_ambiguous"),
])
def test_duplicate_title_mismatch_cannot_admit_another_book(monkeypatch, identities, reason):
    duplicate_overviews(monkeypatch, identities)
    with pytest.raises(RuntimeError, match=reason):
        capture._open_overview("owned", "1" * 64, "Runner", "private-book-id")


@pytest.mark.parametrize("counts,reason", [
    ((21,), "duplicate_titles_invalid"), ((0,), "duplicate_titles_invalid"),
    ((True,), "duplicate_titles_invalid"), ((2, 3), "dashboard_changed"),
])
def test_duplicate_title_scan_is_bounded_and_checks_inventory(monkeypatch, counts, reason):
    clicks, _ = duplicate_overviews(monkeypatch, [], counts=counts)
    with pytest.raises(RuntimeError, match=reason):
        capture._open_overview("owned", "1" * 64, "Runner", "private-book-id")
    assert clicks == []


def test_book_route_is_awaited_before_reading_transient_dashboard_dom(monkeypatch):
    calls = []
    monkeypatch.setattr(capture, "_open_dashboard", lambda *args: None)
    monkeypatch.setattr(capture, "_click", lambda session, selector: calls.append(("click", selector)))
    monkeypatch.setattr(capture, "_browser", lambda session, *args: calls.append(args))
    def observe(*args):
        assert calls[-1][0] == "wait"
        assert "Book Overview" in calls[-1][3] and "Nera's Origin" in calls[-1][3]
        return {"overviewControls": 1}
    monkeypatch.setattr(capture, "_eval", observe)
    capture._open_overview("owned-test", "1" * 64, "Nera's Origin")
    assert calls[-2] == ("click", "xpath=//button[normalize-space(.)='Book Overview']")
    assert calls[-1][0] == "wait" and calls[-1][3].startswith("xpath=//h1[")


@pytest.mark.parametrize("overview_controls", [1, 2])
def test_new_paid_book_normalizes_only_unambiguous_readonly_overview(monkeypatch, overview_controls):
    clicks = []
    answers = iter([
        {"text": "operator@example.test"},
        {"overviewControls": overview_controls},
        {"leaves": ["private-book-id"]},
    ])
    monkeypatch.setattr(capture, "_browser", lambda *a: "ok")
    monkeypatch.setattr(capture, "_click", lambda session, selector: clicks.append(selector))
    monkeypatch.setattr(capture, "_eval", lambda *a: next(answers))
    if overview_controls == 2:
        with pytest.raises(RuntimeError, match="overview_ambiguous"):
            capture._open_book("owned-test", capture._binding(packet()))
        assert len(clicks) == 3
    else:
        capture._open_book("owned-test", capture._binding(packet()))
        assert clicks[-2:] == ["xpath=//button[normalize-space(.)='Book Overview']",
                               "xpath=//button[normalize-space(.)='Resume Writing']"]
    assert not any("Lock" in click or "Write Chapter" in click for click in clicks)


def test_private_capture_cannot_enter_automatic_public_proxy(monkeypatch):
    from app.services.browseract_ui_service_catalog import browseract_ui_service_by_service_key
    from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
    service = browseract_ui_service_by_service_key("booka_book")
    monkeypatch.setattr(BrowserActToolAdapter, "_ui_service_login_email", lambda *a, **k: pytest.fail("no credential lookup"))
    monkeypatch.setattr(BrowserActToolAdapter, "_ui_service_login_password", lambda *a, **k: pytest.fail("no credential lookup"))
    def worker(*a, **kwargs):
        assert "login_password" not in kwargs["packet"] and "login_email" not in kwargs["packet"]
        return {"text": "private draft"}
    monkeypatch.setattr(BrowserActToolAdapter, "_run_ui_service_worker", worker)
    monkeypatch.setattr(BrowserActToolAdapter, "_publish_ui_service_result", lambda *a, **k: pytest.fail("must remain private"))
    result = BrowserActToolAdapter._execute_ui_service_worker_direct(
        service_key="booka_book", request_payload={"proxy_result": True, "login_password": "unused-test-secret"},
        requested_inputs={"mode": capture.MODE}, binding_metadata={},
        service=service, workflow_id="", run_url="",
    )
    assert "public_url" not in result


def test_unknown_or_hostile_input_fails_before_browser(monkeypatch, tmp_path):
    monkeypatch.setattr(capture, "_observe", lambda *args: pytest.fail("invalid input"))
    for change in ({"browser_session": "--other-session" + "/"}, {"chapter_number": True},
                   {"source_packet_sha256": ""}, {"narrative_locale": "bad"}):
        with pytest.raises(ValueError):
            capture.capture_existing_chapter({**packet(), **change}, tmp_path)


def test_capture_urls_are_not_inferred_to_be_published_book_downloads():
    from app.services.browseract_ui_service_catalog import browseract_ui_service_by_service_key
    from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
    response = capture._capture(capture._binding(packet()), {
        **observation(), "text": "Nera reads https://example.test/unapproved.epub on a wall.",
    })
    normalized = BrowserActToolAdapter._normalize_browseract_ui_service_payload(
        service=browseract_ui_service_by_service_key("booka_book"), response=response,
        workflow_id="", requested_url="", requested_inputs={}, result_title="",
    )
    assert normalized["asset_urls"] == []
    for field in ("public_url", "download_url", "asset_url", "editor_url"):
        assert normalized[field] is None
    assert normalized["structured_output_json"]["text"] == response["text"]
    assert normalized["structured_output_json"]["canon_approved"] is False


def test_capture_cannot_fall_through_to_remote_generation():
    from app.services.browseract_ui_service_catalog import browseract_ui_service_by_service_key
    from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
    from app.services.tool_execution_common import ToolExecutionError
    with pytest.raises(ToolExecutionError, match="requires_owned_local_session"):
        BrowserActToolAdapter._execute_ui_service_worker_direct(
            service_key="booka_book", request_payload={"mode": capture.MODE, "force_browseract": True},
            requested_inputs={}, binding_metadata={}, service=browseract_ui_service_by_service_key("booka_book"),
            workflow_id="remote-workflow", run_url="",
        )


def test_bad_mode_never_falls_through_to_create(monkeypatch):
    from scripts import booka_book_worker as worker
    from types import SimpleNamespace
    monkeypatch.setattr(worker, "parse_args", lambda: SimpleNamespace(packet_path=""))
    monkeypatch.setattr(worker, "_load_packet", lambda *_: {"mode": "capture_typo"})
    monkeypatch.setattr(worker, "_run_browser", lambda *a, **k: pytest.fail("no new generation"))
    with pytest.raises(ValueError, match="unknown_worker_mode"):
        worker.main()


def test_capture_entry_does_not_invoke_old_framework_worker(monkeypatch, capsys):
    from scripts import booka_book_worker as worker
    from types import SimpleNamespace
    monkeypatch.setattr(worker, "parse_args", lambda: SimpleNamespace(packet_path=""))
    monkeypatch.setattr(worker, "_load_packet", lambda *_: packet())
    monkeypatch.setattr(worker, "_run_browser", lambda *a, **k: pytest.fail("no framework creation"))
    monkeypatch.setattr(capture, "capture_existing_chapter", lambda *_: {"mode": capture.MODE, "private_only": True})
    assert worker.main() == 0
    assert json.loads(capsys.readouterr().out)["private_only"] is True


def test_world_readable_capture_root_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "firstbook-private-captures"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    monkeypatch.setattr(capture, "_observe", lambda *args: pytest.fail("unsafe storage"))
    with pytest.raises(RuntimeError, match="store_not_private"):
        capture.capture_existing_chapter(packet(), tmp_path)
