from __future__ import annotations

import copy
import json

import pytest

from scripts import firstbook_book_binding as books
from scripts import origin_chapter_worker as worker
from scripts import firstbook_chapter_write as writer
from tests.test_origin_chapter_worker import Hub, packet


def prepared():
    return {**packet()["prepared"], "request_id": packet()["work_id"]}


def test_two_chapters_retain_same_book_across_cold_calls(tmp_path):
    first = prepared()
    books.bind_prepared("c" * 64, "childhood", first, tmp_path)
    path = tmp_path / "firstbook-private-writes/books" / ("c" * 64 + ".json")
    original = path.read_bytes()
    books.bind_prepared("c" * 64, "childhood", copy.deepcopy(first), tmp_path)
    assert path.read_bytes() == original
    second = {**first, "request_id": "1" * 64 + "." + "3" * 64,
              "chapter_number": 2, "chapter_title": "School", "source_packet_sha256": "d" * 64}
    books.bind_prepared("c" * 64, "school", second, tmp_path)
    stored = json.loads(path.read_text())
    books._check(stored, "c" * 64)
    assert len(stored["mapping"]["chapters"]) == 2
    assert stored["mapping"]["provider"]["provider_book_id"] == first["provider_book_id"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    final = path.read_bytes()
    books.bind_prepared("c" * 64, "childhood", first, tmp_path)
    assert path.read_bytes() == final


@pytest.mark.parametrize("key,value", [("provider_book_id", "new-paid-book"),
    ("account_sha256", "f" * 64), ("book_title", "Other title"), ("narrative_locale", "es")])
def test_next_chapter_cannot_silently_allocate_another_book_or_account(tmp_path, key, value):
    books.bind_prepared("c" * 64, "childhood", prepared(), tmp_path)
    second = {**prepared(), "request_id": "1" * 64 + "." + "3" * 64, "chapter_number": 2, key: value}
    with pytest.raises(RuntimeError, match="mapping_changed"):
        books.bind_prepared("c" * 64, "school", second, tmp_path)


def test_other_runner_cannot_reuse_same_provider_project_or_job(tmp_path):
    books.bind_prepared("c" * 64, "childhood", prepared(), tmp_path)
    other = {**prepared(), "request_id": "4" * 64 + "." + "2" * 64}
    with pytest.raises(RuntimeError, match="provider_book_already_bound"):
        books.bind_prepared("d" * 64, "childhood", other, tmp_path)
    with pytest.raises(RuntimeError, match="work_already_bound"):
        books.bind_prepared("d" * 64, "childhood", {**prepared(), "provider_book_id": "book-2"}, tmp_path)


@pytest.mark.parametrize("chapter,changes", [
    ("childhood", {"source_packet_sha256": "d" * 64}),
    ("school", {"request_id": "1" * 64 + "." + "3" * 64}),
    ("school", {"chapter_number": 2}),
    ("childhood", {"request_id": "1" * 64 + "." + "3" * 64, "chapter_number": 2})])
def test_chapter_slot_source_and_work_are_immutable(tmp_path, chapter, changes):
    books.bind_prepared("c" * 64, "childhood", prepared(), tmp_path)
    with pytest.raises(RuntimeError, match="slot_already_bound"):
        books.bind_prepared("c" * 64, chapter, {**prepared(), **changes}, tmp_path)


def test_owner_cannot_change_within_book(tmp_path):
    books.bind_prepared("c" * 64, "childhood", prepared(), tmp_path)
    second = {**prepared(), "request_id": "4" * 64 + "." + "3" * 64, "chapter_number": 2}
    with pytest.raises(RuntimeError, match="mapping_invalid"):
        books.bind_prepared("c" * 64, "school", second, tmp_path)


def test_corrupt_or_linked_book_mapping_cannot_be_replaced(tmp_path):
    books.bind_prepared("c" * 64, "childhood", prepared(), tmp_path)
    path = tmp_path / "firstbook-private-writes/books" / ("c" * 64 + ".json")
    path.write_text(path.read_text().replace('"book-1"', '"book-2"'))
    with pytest.raises(RuntimeError, match="mapping_invalid"):
        books.bind_prepared("c" * 64, "childhood", prepared(), tmp_path)
    link = tmp_path / "linked"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="linked_storage"):
        books.bind_prepared("c" * 64, "childhood", prepared(), link)


def test_connector_rejects_project_switch_before_hub_admission_or_browser(tmp_path, monkeypatch):
    hub = Hub()
    books.bind_prepared(hub.work["bookRef"], "chapter", prepared(), tmp_path)
    changed = packet()
    changed["prepared"]["provider_book_id"] = "other-paid-project"
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("must not write"))
    with pytest.raises(RuntimeError, match="mapping_changed"):
        worker.run_once(changed, hub, tmp_path)
    assert len(hub.calls) == 1
    assert hub.work["executionAdmission"] is None


def test_connector_requires_consistent_hub_book_identity(tmp_path, monkeypatch):
    hub = Hub()
    original = hub.call
    def changed_on_admission(work_id, action="", body=None):
        result = original(work_id, action, body)
        if action == "/admit":
            result["work"]["bookRef"] = "d" * 64
        return result
    hub.call = changed_on_admission
    monkeypatch.setattr(writer, "write_prepared_chapter", lambda *a, **k: pytest.fail("must not write"))
    with pytest.raises(ValueError, match="admission_response_invalid"):
        worker.run_once(packet(), hub, tmp_path)
