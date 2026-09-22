"""Private execution mapping for one Hub-owned runner/language book.

No book creation, spending, chapter ordering or reader-approval authority. The
Hub supplies BookRef; a trusted preparation step supplies exact provider slots.
Mappings are append-only. Retries cannot silently select another paid project.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re

from scripts import firstbook_chapter_write as writer


def _digest(value: dict) -> str:
    return writer.capture._sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _check(stored: dict, book_ref: str) -> None:
    try:
        body = stored["mapping"]
        provider = body["provider"]
        chapters = body["chapters"]
        valid = (set(stored) == {"mapping", "digest"} and stored["digest"] == _digest(body)
            and set(body) == {"schema", "book_ref", "provider", "chapters"}
            and body["schema"] == "firstbook.private-book-binding/v1" and body["book_ref"] == book_ref
            and set(provider) == {"account_sha256", "provider_book_id", "book_title", "narrative_locale"}
            and isinstance(chapters, list) and 1 <= len(chapters) <= 100)
        for item in chapters:
            valid = valid and (set(item) == {"work_id", "chapter_id", "source_packet_sha256", "chapter_number"}
                and re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", item["work_id"]) is not None)
            writer.capture._binding({**provider, "request_id": item["work_id"],
                "chapter_title": item["chapter_id"], "chapter_number": item["chapter_number"],
                "source_packet_sha256": item["source_packet_sha256"]})
        for key in ("work_id", "chapter_id", "chapter_number"):
            valid = valid and len({item[key] for item in chapters}) == len(chapters)
        valid = valid and len({item["work_id"].split(".")[0] for item in chapters}) == 1
    except (KeyError, ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise RuntimeError("firstbook_book_mapping_invalid")


def bind_prepared(book_ref: str, chapter_id: str, prepared: dict, output_root: Path) -> None:
    """Bind the exact prepared project/slot before Hub admission or browser use."""
    if not isinstance(book_ref, str) or not re.fullmatch(r"[0-9a-f]{64}", book_ref):
        raise ValueError("firstbook_book_reference_invalid")
    writer.capture._text({"chapter_id": chapter_id}, "chapter_id")
    binding = writer._binding(prepared)
    if not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", binding["request_id"]):
        raise ValueError("firstbook_book_work_identity_invalid")
    provider = {key: binding[key] for key in ("account_sha256", "provider_book_id", "book_title", "narrative_locale")}
    chapter = {"work_id": binding["request_id"], "chapter_id": chapter_id,
               "source_packet_sha256": binding["source_packet_sha256"], "chapter_number": binding["chapter_number"]}
    root = writer._private_root(output_root) / "books"
    if root.is_symlink():
        raise RuntimeError("firstbook_book_mapping_not_private")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError("firstbook_book_mapping_not_private")
    lock_fd = os.open(root / ".writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("firstbook_book_mapping_busy") from None
        # Serializing both lookups prevents two runners claiming the same paid
        # provider book concurrently. This is execution custody, not Hub truth.
        records = {}
        for path in root.glob("*.json"):
            if len(records) >= 512 or not re.fullmatch(r"[0-9a-f]{64}", path.stem):
                raise RuntimeError("firstbook_book_mapping_inventory_invalid")
            record = writer._load(path)
            _check(record, path.stem)
            records[path.stem] = record["mapping"]
        for other_ref, other in records.items():
            other_provider = other["provider"]
            if other_ref != book_ref and any(item["work_id"] == chapter["work_id"] for item in other["chapters"]):
                raise RuntimeError("firstbook_work_already_bound")
            if (other_ref != book_ref and other_provider["account_sha256"] == provider["account_sha256"]
                and other_provider["provider_book_id"] == provider["provider_book_id"]):
                raise RuntimeError("firstbook_provider_book_already_bound")
        previous = records.get(book_ref)
        if previous:
            if previous["provider"] != provider:
                raise RuntimeError("firstbook_runner_book_mapping_changed")
            for item in previous["chapters"]:
                if item == chapter:
                    return
                if any(item[key] == chapter[key] for key in ("work_id", "chapter_id", "chapter_number")):
                    raise RuntimeError("firstbook_chapter_slot_already_bound")
        elif len(records) >= 512:
            raise RuntimeError("firstbook_book_mapping_inventory_full")
        chapters = [*(previous["chapters"] if previous else []), chapter]
        body = {"schema": "firstbook.private-book-binding/v1", "book_ref": book_ref,
                "provider": provider, "chapters": chapters}
        stored = {"mapping": body, "digest": _digest(body)}
        _check(stored, book_ref)
        writer._save(root / (book_ref + ".json"), stored)
