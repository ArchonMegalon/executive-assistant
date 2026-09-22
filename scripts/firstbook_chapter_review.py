"""Read a deliberately selected edited draft before initial Hub delivery.

This never edits, generates, approves, or replaces the original writer journal.
The separate immutable capture can later satisfy an exact Hub reader acceptance.
It is editorial selection by a trusted local caller, not semantic/canon approval.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re

from scripts import firstbook_chapter_write as writer

capture = writer.capture


def _binding(binding: dict, text_digest: str) -> dict:
    if not isinstance(text_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", text_digest):
        raise ValueError("firstbook_review_requires_exact_text_digest")
    identity = json.dumps([binding["request_id"], binding["source_packet_sha256"], text_digest], separators=(",", ":"))
    return {**capture._binding(binding), "request_id": "review-" + capture._sha(identity)}


def _original(binding: dict, output_root: Path) -> tuple[dict, Path]:
    root = writer._private_root(output_root)
    path = writer._record_path(root, binding)
    record = writer._load(path)
    if record is None:
        raise RuntimeError("firstbook_review_original_not_retained")
    writer._validate_retained(binding, record)
    if record["state"] != "chapter_review_required":
        raise RuntimeError("firstbook_review_original_not_complete")
    return record, path


def _path(output_root: Path, binding: dict) -> Path:
    root = writer._private_root(output_root).parent / "firstbook-private-captures"
    if root.is_symlink() or (root.exists() and
        (not root.is_dir() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077)):
        raise RuntimeError("firstbook_review_capture_store_not_private")
    return root / (capture._sha(binding["request_id"]) + ".json")


def retained(binding: dict, output_root: Path, text_digest: str) -> tuple[dict, Path] | None:
    original, _ = _original(binding, output_root)
    expected = _binding(binding, text_digest)
    path = _path(output_root, expected)
    result = writer._load(path)
    if result is None:
        return None
    capture._validate_retained(expected, result)
    if (result["text_sha256"] != text_digest or result["chapter_count_observed"] !=
        original["result"]["chapter_count_observed"]):
        raise RuntimeError("firstbook_review_draft_mismatch")
    return result, path


def capture_reviewed_chapter(packet: dict, output_root: Path, text_digest: str) -> dict:
    binding = writer._binding(packet)
    expected = _binding(binding, text_digest)
    session = capture._text(packet, "browser_session", 128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        raise ValueError("firstbook_invalid_browser_session")
    root = writer._private_root(output_root)
    lock_fd = os.open(root / ".writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("firstbook_chapter_worker_busy") from None
        _, original_path = _original(binding, output_root)
        fence = original_path.with_suffix(".accept.json")
        if fence.exists() or fence.is_symlink():
            raise RuntimeError("firstbook_review_chapter_already_advancing")
        selected = retained(binding, output_root, text_digest)
        if selected is not None:
            result, path = selected
            return {**result, "asset_path": str(path), "reused_capture": True}
        if writer._inspect(session).get("generating") is True:
            return {"render_status": "provider_busy", "publication_authorized": False}
        # Capture only: no Write, Rewrite, Save, payment or approval control.
        capture.capture_existing_chapter({**expected, "browser_session": session}, output_root)
        selected = retained(binding, output_root, text_digest)
        if selected is None:
            raise RuntimeError("firstbook_review_capture_not_retained")
        result, path = selected
        return {**result, "asset_path": str(path), "reused_capture": False}
