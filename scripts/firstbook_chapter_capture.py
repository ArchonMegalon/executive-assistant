"""Read an existing First Book draft; never create, rewrite, approve or publish.

The caller owns the BrowserAct session and supplies the exact approved account,
book and source-packet binding. This is a provider observation, not a canon audit
or a completed book. A retry returns the immutable local capture for that request.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


MODE = "capture_existing_chapter"
_ORIGIN = "https://app.firstbook.ai/"
_MAX_BYTES = 200_000


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(packet: dict, key: str, limit: int = 256) -> str:
    value = packet.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or value != value.strip():
        raise ValueError(f"firstbook_invalid_{key}")
    return value


def _binding(packet: dict) -> dict:
    binding = {key: _text(packet, key) for key in (
        "request_id", "account_sha256", "provider_book_id", "book_title",
        "chapter_title", "source_packet_sha256", "narrative_locale",
    )}
    for key in ("account_sha256", "source_packet_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", binding[key]):
            raise ValueError(f"firstbook_invalid_{key}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", binding["provider_book_id"]):
        raise ValueError("firstbook_invalid_provider_book_id")
    if not re.fullmatch(r"(?:de|en|es)(?:-[A-Za-z]{2})?", binding["narrative_locale"]):
        raise ValueError("firstbook_invalid_narrative_locale")
    number = packet.get("chapter_number")
    if type(number) is not int or not 1 <= number <= 100:
        raise ValueError("firstbook_invalid_chapter_number")
    binding["chapter_number"] = number
    return binding


def _xpath(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ',"\'",'.join(f"'{part}'" for part in value.split("'")) + ")"


def _browser(session: str, *args: str) -> str:
    try:
        run = subprocess.run(
            ["browser-act", "--session", session, *args], capture_output=True,
            text=True, check=True, timeout=45,
        )
    except (subprocess.SubprocessError, OSError):
        # Browser output may contain account or page data; do not echo it in errors.
        raise RuntimeError("firstbook_capture_browser_unavailable") from None
    return run.stdout.strip()


def _eval(session: str, expression: str) -> dict:
    raw = _browser(session, "eval", "JSON.stringify(" + expression + ")")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise RuntimeError("firstbook_capture_observation_invalid") from None
    if not isinstance(value, dict) or value.get("origin") != _ORIGIN.rstrip("/"):
        raise RuntimeError("firstbook_capture_wrong_origin")
    return value


def _click(session: str, selector: str) -> None:
    _browser(session, "wait", "selector", "--selector", selector, "--timeout", "15000")
    # Count in the DOM first: a duplicate title must not select an arbitrary book.
    if selector.startswith("xpath="):
        expression = "document.evaluate(" + json.dumps(selector[6:]) + ",document,null,XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null).snapshotLength"
    else:
        expression = "document.querySelectorAll(" + json.dumps(selector) + ").length"
    observed = _eval(session, "({origin:location.origin,count:" + expression + "})")
    if observed.get("count") != 1:
        raise RuntimeError("firstbook_capture_control_not_unique")
    _browser(session, "click", "--selector", selector)


def _open_dashboard(session: str, account_sha256: str) -> None:
    """Read-only navigation through the visible account identity."""
    _browser(session, "navigate", _ORIGIN)
    _click(session, 'button[title="Your Profile"]')
    _browser(session, "wait", "selector", "--selector", "xpath=//*[normalize-space(.)='My Profile']", "--timeout", "15000")
    profile = _eval(session, "({origin:location.origin,text:document.body.innerText})")
    emails = re.findall(r"[^\s@]+@[^\s@]+\.[^\s@]+", profile.get("text", ""))
    if len(emails) != 1 or _sha(emails[0].casefold()) != account_sha256:
        raise RuntimeError("firstbook_capture_account_mismatch")
    _click(session, "xpath=//button[normalize-space(.)='Back to Dashboard']")


def _open_book(session: str, binding: dict) -> None:
    # Navigation only. None of these controls generate or approve text.
    _open_dashboard(session, binding["account_sha256"])
    _click(session, "xpath=//h3[normalize-space(.)=" + _xpath(binding["book_title"]) + "]")
    # A new paid book may open its retained outline rather than the overview.
    # Normalize by a read-only navigation control, never by Lock/Start/Write.
    route = _eval(session, "({origin:location.origin,overviewControls:Array.from(document.querySelectorAll('button')).filter(e=>e.innerText.trim()==='Book Overview').length})")
    if route.get("overviewControls") == 1:
        _click(session, "xpath=//button[normalize-space(.)='Book Overview']")
    elif route.get("overviewControls") != 0:
        raise RuntimeError("firstbook_capture_overview_ambiguous")
    _browser(session, "wait", "selector", "--selector", "xpath=//button[normalize-space(.)='Resume Writing']", "--timeout", "15000")
    overview = _eval(session, "({origin:location.origin,leaves:Array.from(document.querySelectorAll('body *')).filter(e=>e.childElementCount===0).map(e=>e.textContent.trim())})")
    if overview.get("leaves", []).count(binding["provider_book_id"]) != 1:
        raise RuntimeError("firstbook_capture_book_mismatch")
    _click(session, "xpath=//button[normalize-space(.)='Resume Writing']")


def _observe(session: str, binding: dict) -> dict:
    _open_book(session, binding)
    _browser(session, "wait", "selector", "--selector", ".prose h1", "--timeout", "15000")
    return _read_draft(session)


def _read_draft(session: str) -> dict:
    return _eval(session, """(() => {
        const surfaces = Array.from(document.querySelectorAll('.prose'));
        const indicator = document.body.innerText.match(/Chapter\\s+(\\d+)\\s+of\\s+(\\d+)/);
        return {origin:location.origin,
            bookTitles:Array.from(document.querySelectorAll('h3')).map(e=>e.innerText),
            chapterTitle:document.querySelector('.prose h1')?.innerText,
            chapterNumber:indicator ? Number(indicator[1]) : null,
            chapterCount:indicator ? Number(indicator[2]) : null,
            surfaceCount:surfaces.length,
            text:surfaces.length===1 ? surfaces[0].innerText : '',
            reviewRequired:document.body.innerText.includes('Review Mode: Changes must be approved before proceeding.'),
            editing:document.querySelector('[contenteditable=true]')!==null,
            approveControl:Array.from(document.querySelectorAll('button')).filter(e=>e.innerText.trim()==='Approve & Next').length};
    })()""")


def _capture(binding: dict, observed: dict) -> dict:
    text = observed.get("text")
    if (observed.get("origin") != _ORIGIN.rstrip("/")
        or observed.get("bookTitles") != [binding["book_title"]]
        or observed.get("chapterTitle") != binding["chapter_title"]
        or observed.get("chapterNumber") != binding["chapter_number"]
        or type(observed.get("chapterCount")) is not int
        or not binding["chapter_number"] <= observed["chapterCount"] <= 100
        or observed.get("surfaceCount") != 1
        or observed.get("reviewRequired") is not True
        or observed.get("editing") is not False
        or observed.get("approveControl") != 1
        or not isinstance(text, str) or not text.strip()
        or len(text.encode("utf-8")) > _MAX_BYTES):
        raise RuntimeError("firstbook_capture_draft_not_verified")
    return {
        "service_key": "booka_book", "mode": MODE, "binding": binding,
        "result_title": binding["book_title"] + " — " + binding["chapter_title"],
        "render_status": "chapter_review_required",
        "generation_stage": "existing_chapter_review", "deliverable_kind": "chapter_draft_capture",
        "provider": "First Book AI", "provider_origin": _ORIGIN,
        "chapter_count_observed": observed["chapterCount"], "text": text,
        "text_sha256": _sha(text), "private_only": True,
        "full_manuscript_ready": False, "canon_approved": False,
        "language_verified": False, "provider_generation_attempted": False,
        "publication_authorized": False,
        "blocker": "chapter_requires_length_language_and_canon_review",
        "next_safe_action": "Review this exact retained draft against its approved source packet; do not resubmit generation on capture retry.",
    }


def capture_existing_chapter(packet: dict, output_root: Path) -> dict:
    binding = _binding(packet)
    session = _text(packet, "browser_session", 128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        raise ValueError("firstbook_invalid_browser_session")
    root = output_root / "firstbook-private-captures"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError("firstbook_capture_store_not_private")
    path = root / (_sha(binding["request_id"]) + ".json")
    # Session ownership is provided by the caller; serialize this adapter's users.
    lock_fd = os.open(root / (_sha(session) + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("firstbook_capture_session_busy") from None
        if path.is_symlink():
            raise RuntimeError("firstbook_capture_store_invalid")
        if path.exists():
            if path.stat().st_size > _MAX_BYTES * 2 or path.stat().st_mode & 0o077:
                raise RuntimeError("firstbook_capture_store_invalid")
            try:
                retained = json.loads(path.read_text(encoding="utf-8"))
                expected = _capture(binding, {
                    "origin": _ORIGIN.rstrip("/"), "bookTitles": [binding["book_title"]],
                    "chapterTitle": binding["chapter_title"], "chapterNumber": binding["chapter_number"],
                    "chapterCount": retained["chapter_count_observed"], "surfaceCount": 1,
                    "reviewRequired": True, "editing": False, "approveControl": 1, "text": retained["text"],
                })
                valid = retained == expected
            except (KeyError, ValueError, TypeError, RuntimeError):
                valid = False
            if not valid:
                raise RuntimeError("firstbook_capture_retained_binding_mismatch")
            return {**retained, "asset_path": str(path), "mime_type": "application/json", "reused_capture": True}
        captured = _capture(binding, _observe(session, binding))
        # One atomic private file is the recovery boundary. No browser call follows it.
        fd, temporary = tempfile.mkstemp(prefix=".capture-", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(captured, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            # Atomic no-clobber publication also protects different sessions racing
            # with the same request ID. A differing result is never overwritten.
            os.link(temporary, path)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.unlink(temporary)
        return {**captured, "asset_path": str(path), "mime_type": "application/json", "reused_capture": False}
