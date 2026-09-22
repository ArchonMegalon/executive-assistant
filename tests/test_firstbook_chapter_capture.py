from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import firstbook_chapter_capture as capture


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
