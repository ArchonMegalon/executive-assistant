from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import firstbook_chapter_capture as capture
from scripts import firstbook_chapter_write as writer


def packet():
    return {"browser_session": "owned-chapter", "request_id": "job-1",
            "account_sha256": "1" * 64, "provider_book_id": "book-1",
            "book_title": "Nera", "chapter_title": "Childhood", "chapter_number": 1,
            "source_packet_sha256": "2" * 64, "narrative_locale": "de-DE",
            "generation_approved": True,
            "expected_outline": [{"title": str(i), "description": "An accepted fact."} for i in range(3)]}


def prepared():
    return {"origin": "https://app.firstbook.ai", "chapterTitle": "Childhood",
            "chapterNumber": 1, "chapterCount": 8, "outlineCount": 1,
            "outline": packet()["expected_outline"], "writeCount": 1, "writeEnabled": True,
            "includedInPlan": True, "briefCount": 1, "briefSelected": True, "hasDraft": False}


def draft():
    return {"origin": "https://app.firstbook.ai", "bookTitles": ["Nera"],
            "chapterTitle": "Childhood", "chapterNumber": 1, "chapterCount": 8,
            "surfaceCount": 1, "text": "Childhood\nNera wartet.", "reviewRequired": True,
            "editing": False, "approveControl": 1}


@pytest.fixture
def browser(monkeypatch):
    actions = []
    monkeypatch.setattr(capture, "_open_book", lambda *a: actions.append("open"))
    monkeypatch.setattr(capture, "_click", lambda session, selector: actions.append(selector))
    monkeypatch.setattr(capture, "_read_draft", lambda *a: draft())
    monkeypatch.setattr(writer, "_inspect", lambda *a: prepared())
    return actions


def test_dispatch_fence_precedes_write_and_retry_cannot_repeat(tmp_path, browser, monkeypatch):
    def click(session, selector):
        browser.append(selector)
        if "Write Chapter" in selector:
            saved = next((tmp_path / "firstbook-private-writes").glob("*.json"))
            assert json.loads(saved.read_text())["state"] == "write_dispatched"
            assert saved.stat().st_mode & 0o777 == 0o600
            raise RuntimeError("lost_browser_response")
    monkeypatch.setattr(capture, "_click", click)
    with pytest.raises(RuntimeError, match="lost_browser_response"):
        writer.write_prepared_chapter(packet(), tmp_path)
    again = writer.write_prepared_chapter(packet(), tmp_path)
    assert again["render_status"] == "reconciliation_required"
    assert again["retry_generation_allowed"] is False
    assert sum("Write Chapter" in action for action in browser) == 1


def test_real_draft_capture_and_cold_retry_do_not_navigate_or_admit_canon(tmp_path, browser, monkeypatch):
    writer.write_prepared_chapter(packet(), tmp_path)
    monkeypatch.setattr(writer, "_inspect", lambda *a: {"hasDraft": True})
    result = writer.write_prepared_chapter(packet(), tmp_path)
    assert result["render_status"] == "chapter_review_required"
    assert result["provider_generation_attempted"] is True
    assert result["canon_approved"] is False
    assert result["publication_authorized"] is False
    assert result["generation_causally_attested"] is False
    assert result["text"] == draft()["text"]
    monkeypatch.setattr(capture, "_open_book", lambda *a: pytest.fail("cold retained result"))
    assert writer.write_prepared_chapter(packet(), tmp_path)["reused_capture"] is True


@pytest.mark.parametrize("key,value", [("request_id", "job-2"), ("source_packet_sha256", "3" * 64),
                                       ("book_title", "Other"), ("narrative_locale", "es-ES"),
                                       ("expected_outline", [{"title": "changed", "description": "x"}] * 3)])
def test_new_request_cannot_rewrite_same_provider_chapter(tmp_path, browser, monkeypatch, key, value):
    writer.write_prepared_chapter(packet(), tmp_path)
    monkeypatch.setattr(capture, "_open_book", lambda *a: pytest.fail("binding changed"))
    with pytest.raises(RuntimeError, match="binding_mismatch"):
        writer.write_prepared_chapter({**packet(), key: value}, tmp_path)


@pytest.mark.parametrize("key,value", [("chapterTitle", "wrong"), ("chapterNumber", 2),
                                       ("writeCount", 2), ("writeEnabled", False),
                                       ("includedInPlan", False), ("briefCount", 2),
                                       ("outline", []), ("hasDraft", True)])
def test_unprepared_or_existing_chapter_cannot_generate(tmp_path, browser, monkeypatch, key, value):
    monkeypatch.setattr(writer, "_inspect", lambda *a: {**prepared(), key: value})
    with pytest.raises(RuntimeError, match="prepared_source_mismatch"):
        writer.write_prepared_chapter(packet(), tmp_path)
    assert browser == ["open"]
    assert not list(tmp_path.rglob("*.json"))


def test_selection_drift_is_rechecked_before_fence(tmp_path, browser, monkeypatch):
    snapshots = iter([prepared(), prepared(), {**prepared(), "briefSelected": False}])
    monkeypatch.setattr(writer, "_inspect", lambda *a: next(snapshots))
    with pytest.raises(RuntimeError, match="prepared_source_mismatch"):
        writer.write_prepared_chapter(packet(), tmp_path)
    assert not list(tmp_path.rglob("*.json"))
    assert not any("Write Chapter" in action for action in browser)


def test_poll_does_not_navigate_away_from_inflight_browser_generation(tmp_path, browser, monkeypatch):
    writer.write_prepared_chapter(packet(), tmp_path)
    before = list(browser)
    monkeypatch.setattr(writer, "_inspect", lambda *a: {"generating": True})
    assert writer.write_prepared_chapter(packet(), tmp_path)["render_status"] == "provider_busy"
    assert browser == before


@pytest.mark.parametrize("labels,busy", [
    (['Writing Subchapter 1 of 3: "Der Augenblick"...'], True),
    (['Writing Subchapter 3 of 3: "Vor der Entscheidung"...'], True),
    (['Review Mode: Changes must be approved before proceeding.'], False),
    ([], False), (None, False), ([None], False),
])
def test_live_subchapter_rewrite_is_not_mistaken_for_a_completed_draft(monkeypatch, labels, busy):
    monkeypatch.setattr(capture, "_eval", lambda *args: {
        "generating": False, "generationLabels": labels, "hasDraft": True})
    observed = writer._inspect("owned-chapter")
    assert observed["generating"] is busy and observed["hasDraft"] is True


def test_live_rewrite_prevents_navigation_even_with_old_draft_visible(tmp_path, monkeypatch):
    binding = writer._binding(packet())
    root = writer._private_root(tmp_path)
    writer._save(writer._record_path(root, binding), {
        "binding": binding, "state": "write_dispatched", "result": None})
    monkeypatch.setattr(capture, "_eval", lambda *args: {
        "generating": False, "generationLabels": ['Writing Subchapter 2 of 3: "Moment"...'], "hasDraft": True})
    monkeypatch.setattr(capture, "_open_book", lambda *args: pytest.fail("must not interrupt live rewriting"))
    assert writer.write_prepared_chapter(packet(), tmp_path)["render_status"] == "provider_busy"


def test_lost_upstream_admission_without_local_fence_cannot_start_generation(tmp_path, browser):
    result = writer.write_prepared_chapter(packet(), tmp_path, allow_new_dispatch=False)
    assert result["render_status"] == "reconciliation_required"
    assert browser == []
    assert not list(tmp_path.rglob("*.json"))


def test_missing_admission_cannot_touch_browser_or_storage(tmp_path, browser):
    with pytest.raises(ValueError, match="not_admitted"):
        writer.write_prepared_chapter({**packet(), "generation_approved": False}, tmp_path)
    assert browser == [] and list(tmp_path.iterdir()) == []


def test_wrong_draft_does_not_complete_or_trigger_rewrite(tmp_path, browser, monkeypatch):
    writer.write_prepared_chapter(packet(), tmp_path)
    monkeypatch.setattr(writer, "_inspect", lambda *a: {"hasDraft": True})
    monkeypatch.setattr(capture, "_read_draft", lambda *a: {**draft(), "chapterNumber": 2})
    with pytest.raises(RuntimeError, match="draft_not_verified"):
        writer.write_prepared_chapter(packet(), tmp_path)
    assert sum("Write Chapter" in action for action in browser) == 1
    assert json.loads(next(tmp_path.rglob("*.json")).read_text())["state"] == "write_dispatched"


def test_corrupt_retained_result_does_not_recover_or_regenerate(tmp_path, browser, monkeypatch):
    writer.write_prepared_chapter(packet(), tmp_path)
    monkeypatch.setattr(writer, "_inspect", lambda *a: {"hasDraft": True})
    result = writer.write_prepared_chapter(packet(), tmp_path)
    path = Path(result["asset_path"])
    saved = json.loads(path.read_text())
    saved["result"]["canon_approved"] = True
    path.write_text(json.dumps(saved))
    monkeypatch.setattr(capture, "_open_book", lambda *a: pytest.fail("corrupt result"))
    with pytest.raises(RuntimeError, match="record_invalid"):
        writer.write_prepared_chapter(packet(), tmp_path)


def test_unsafe_or_linked_storage_never_dispatches(tmp_path, browser):
    root = tmp_path / "firstbook-private-writes"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(RuntimeError, match="not_private"):
        writer.write_prepared_chapter(packet(), tmp_path)
    assert browser == []
    link = tmp_path / "linked"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="linked_storage"):
        writer.write_prepared_chapter(packet(), link)


def test_durable_write_failure_prevents_provider_write(tmp_path, browser, monkeypatch):
    def disk_full(*a):
        raise OSError("disk_full")
    monkeypatch.setattr(writer, "_save", disk_full)
    with pytest.raises(OSError, match="disk_full"):
        writer.write_prepared_chapter(packet(), tmp_path)
    assert not any("Write Chapter" in action for action in browser)
