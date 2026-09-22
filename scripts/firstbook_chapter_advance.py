"""Advance one exact reader-accepted First Book chapter, at most once.

Trusted local connector only. Hub must supply the reader's acceptance of the
exact retained draft; generation completion alone never authorizes this action.
No book creation, spending, rewriting, next-chapter generation or publication.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat

from scripts import firstbook_chapter_write as writer


def advance_accepted_chapter(packet: dict, output_root: Path, text_digest: str, receipt_digest: str) -> dict:
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
           for value in (text_digest, receipt_digest)):
        raise ValueError("firstbook_reader_acceptance_missing")
    binding = writer._binding(packet)
    session = writer.capture._text(packet, "browser_session", 128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        raise ValueError("firstbook_invalid_browser_session")
    root = writer._private_root(output_root)
    path = writer._record_path(root, binding)
    fence = path.with_suffix(".accept.json")
    lock_fd = os.open(root / ".writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("firstbook_chapter_worker_busy") from None
        record = writer._load(path)
        if record is None:
            raise RuntimeError("firstbook_reader_draft_not_retained")
        writer._validate_retained(binding, record)
        if record["state"] != "chapter_review_required" or record["result"]["text_sha256"] != text_digest:
            raise RuntimeError("firstbook_reader_acceptance_mismatch")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RuntimeError("firstbook_reader_record_not_private")
            raw = stream.read(writer._MAX_RECORD_BYTES + 1)
        if len(raw) > writer._MAX_RECORD_BYTES or hashlib.sha256(raw).hexdigest() != receipt_digest:
            raise RuntimeError("firstbook_reader_receipt_mismatch")
        expected = {"binding": binding, "text_digest": text_digest, "receipt_digest": receipt_digest}
        retained = writer._load(fence)
        if retained is not None and (set(retained) != {"accepted", "state"} or retained["accepted"] != expected
            or retained["state"] not in ("advance_dispatched", "next_chapter_observed")):
            raise RuntimeError("firstbook_reader_fence_mismatch")

        def status(value: str) -> dict:
            return {"render_status": value, "request_id": binding["request_id"],
                    "publication_authorized": False, "next_chapter_generation_attempted": False,
                    "retry_approval_allowed": False}

        if retained is not None and retained["state"] == "next_chapter_observed":
            return status("next_chapter_observed")
        if writer._inspect(session).get("generating") is True:
            return status("provider_busy")
        writer.capture._open_book(session, binding)
        observed = writer._inspect(session)
        if retained is not None:
            if (observed.get("origin") == writer.capture._ORIGIN.rstrip("/")
                and observed.get("chapterNumber") == binding["chapter_number"] + 1
                and observed.get("chapterCount") == record["result"]["chapter_count_observed"]
                and observed.get("hasDraft") is False and observed.get("writeCount") == 1
                and observed.get("writeEnabled") is True and observed.get("includedInPlan") is True):
                writer._save(fence, {"accepted": expected, "state": "next_chapter_observed"})
                return status("next_chapter_observed")
            return status("reconciliation_required")
        current = writer._result(binding, writer.capture._read_draft(session))
        if current != record["result"]:
            raise RuntimeError("firstbook_reader_provider_draft_changed")
        if binding["chapter_number"] >= current["chapter_count_observed"]:
            # Final-book approval/export may use a different provider flow.
            # Never treat it as permission to publish or finish that workflow.
            return status("final_chapter_retained")
        writer._save(fence, {"accepted": expected, "state": "advance_dispatched"})
        writer.capture._click(session, "xpath=//button[normalize-space(.)='Approve & Next']")
        return status("advance_dispatched")
