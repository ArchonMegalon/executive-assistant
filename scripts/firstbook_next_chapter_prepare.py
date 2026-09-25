"""Replace one unwritten placeholder after an exact accepted predecessor.

Hub supplies both sources/consents. This private helper edits only the next slot
of the existing paid book; it cannot approve a reader draft, buy or generate.
An uncertain save is observed, never replayed. Past/future outline fields stay
byte-for-byte unchanged.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re

from scripts import firstbook_outline_prepare as outline

writer = outline.writer
capture = writer.capture
_LOCK = "Lock & Start Writing"


def _plan(packet: dict, previous: dict, *, version: int = 3) -> tuple[dict, dict]:
    source = outline.setup._binding({**packet, "framework_generation_approved": True})
    prior = writer._binding(previous)
    if (source["account_sha256"] != prior["account_sha256"]
        or source["approved_source"]["locale"] != prior["narrative_locale"]
        or source["work_id"].split(".")[0] != prior["request_id"].split(".")[0]
        or source["work_id"] == prior["request_id"] or prior["chapter_number"] >= 100):
        raise ValueError("firstbook_next_source_mismatch")
    number = prior["chapter_number"] + 1
    chapter = outline._plan(source, 1, version=version)[0]
    label = {"de": "Der nächste Schritt", "en": "The Next Step", "es": "El siguiente paso"}[
        prior["narrative_locale"].split("-")[0]]
    chapter["title"] = f'{source["approved_source"]["runnerName"]} — {label} {number}'
    prepared = {key: prior[key] for key in ("account_sha256", "provider_book_id", "book_title", "narrative_locale")}
    prepared.update(request_id=source["work_id"], source_packet_sha256=source["source_packet_sha256"],
                    chapter_number=number, chapter_title=chapter["title"], expected_outline=chapter["parts"],
                    generation_approved=True)
    writer._binding(prepared)
    return source, {"prepared": prepared, "chapter": chapter}


def _path(root: Path, work_id: str) -> Path:
    return root / ("next-outline-" + capture._sha(work_id) + ".json")


def _retained_plan(packet: dict, previous: dict, source: dict, planned: dict, record: dict) -> dict:
    if (record.get("source") != source or record.get("previous") != writer._binding(previous)
        or record.get("state") not in ("editing", "save_dispatched", "prepared")):
        raise RuntimeError("firstbook_next_retained_mismatch")
    if record.get("plan") == planned:
        return planned
    try:
        _, old_plan = _plan(packet, previous, version=2)
        if record.get("plan") == old_plan:
            return old_plan
    except ValueError:
        pass
    raise RuntimeError("firstbook_next_retained_mismatch")


def retained_next_chapter(packet: dict, previous: dict, output_root: Path) -> dict | None:
    source, planned = _plan(packet, previous)
    record = writer._load(_path(writer._private_root(output_root), source["work_id"]))
    if record is None:
        return None
    planned = _retained_plan(packet, previous, source, planned, record)
    return planned["prepared"] if record["state"] == "prepared" else None


def prepare_next_chapter(packet: dict, previous: dict, output_root: Path,
                         text_digest: str, receipt_digest: str, *, allow_new_dispatch: bool = True) -> dict:
    if packet.get("outline_update_approved") is not True:
        raise ValueError("firstbook_next_outline_not_admitted")
    source, planned = _plan(packet, previous)
    prior = writer._binding(previous)
    session = capture._text(packet, "browser_session", 128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        raise ValueError("firstbook_invalid_browser_session")
    root = writer._private_root(output_root)
    path = _path(root, source["work_id"])
    lock_fd = os.open(root / ".writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("firstbook_chapter_worker_busy") from None
        predecessor = writer._record_path(root, prior)
        acceptance = writer._load(predecessor.with_suffix(".accept.json"))
        if (acceptance is None or acceptance.get("state") != "next_chapter_observed"
            or acceptance.get("accepted") != {"binding": prior, "text_digest": text_digest,
                                              "receipt_digest": receipt_digest}):
            raise RuntimeError("firstbook_next_predecessor_not_accepted")
        retained = writer._load(predecessor)
        if retained is None:
            raise RuntimeError("firstbook_next_predecessor_missing")
        writer._validate_retained(prior, retained)
        count = retained["result"]["chapter_count_observed"]
        number = planned["prepared"]["chapter_number"]
        if number > count:
            raise RuntimeError("firstbook_next_no_remaining_slot")
        # Validate an existing journal before any navigation or input.
        record = writer._load(path)
        if record is not None:
            planned = _retained_plan(packet, previous, source, planned, record)
            if record["state"] == "prepared":
                return {"state": "next_chapter_prepared", "prepared": planned["prepared"]}
        if record is None and not allow_new_dispatch:
            return {"state": "outline_reconciliation_required"}
        if writer._inspect(session).get("generating") is True:
            return {"state": "provider_busy"}
        capture._open_book(session, planned["prepared"])
        observed = writer._inspect(session)
        if record is not None and record["state"] == "save_dispatched":
            # A save with a lost acknowledgement cannot be sent a second time.
            writer._require_prepared(writer._binding(planned["prepared"]), observed)
            record["state"] = "prepared"
            writer._save(path, record)
            return {"state": "next_chapter_prepared", "prepared": planned["prepared"]}
        placeholder = outline._plan(source, count)[number - 1]
        empty = {**planned["prepared"], "chapter_title": placeholder["title"], "expected_outline": placeholder["parts"]}
        writer._require_prepared(writer._binding(empty), observed)
        capture._click(session, "xpath=//button[normalize-space(.)='Book Overview']")
        capture._click(session, "xpath=//button[normalize-space(.)='Edit Outline']")
        rows = outline._require_page(outline._inspect(session), count, lock_text=_LOCK)
        before = [outline._card(session, i, count, lock_text=_LOCK)["values"] for i in range(1, len(rows) + 1)]
        if record is not None and before != record["before"]:
            # Reopening discards provider-local, unsaved form edits. Only the
            # exact original server outline permits resuming idempotent input;
            # another persisted/partial edit must not be overwritten.
            return {"state": "outline_reconciliation_required"}
        if before[number - 1] != outline._values(placeholder):
            raise RuntimeError("firstbook_next_placeholder_changed")
        record = {"source": source, "previous": prior, "plan": planned, "before": before, "state": "editing"}
        writer._save(path, record)
        # The outline is an accordion: inspecting the last card collapsed the
        # target. Reopen and recheck it before sending any field input.
        if outline._card(session, number, count, lock_text=_LOCK)["values"] != before[number - 1]:
            raise RuntimeError("firstbook_next_placeholder_changed")
        outline._fill_card(session, number, planned["chapter"])
        after = [outline._card(session, i, count, lock_text=_LOCK)["values"] for i in range(1, count + 1)]
        expected = [*before]
        expected[number - 1] = outline._values(planned["chapter"])
        if after != expected:
            raise RuntimeError("firstbook_next_outline_readback_mismatch")
        record["state"] = "save_dispatched"
        writer._save(path, record)
        capture._click(session, "xpath=//button[normalize-space(.)='Lock & Start Writing']")
        return {"state": "outline_save_dispatched"}
