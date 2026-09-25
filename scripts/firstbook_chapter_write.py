"""One admitted chapter in an already prepared First Book project.

Trusted local caller only; deliberately not registered as an EA/public tool.
No login, new book, credit purchase, outline approval, rewrite or chapter approval.
A durable fence precedes Write Chapter. Subsequent calls only observe that same
project/chapter; an uncertain write is never automatically resubmitted.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from scripts import firstbook_chapter_capture as capture

MODE = "write_prepared_chapter"
_MAX_RECORD_BYTES = 512_000
# Local intake bounds, not a claim about the provider's server limits. The
# observed FirstBook outline textareas have no maxlength; exact live readback
# still has to succeed before Lock/Write. A whole approved source (32 KiB,
# including identities) plus bounded instructions must fit without truncation.
MAX_SOURCE_BYTES = 32_768
MAX_DESCRIPTION_CHARS = MAX_SOURCE_BYTES + 2_048


def _binding(packet: dict) -> dict:
    if packet.get("generation_approved") is not True:
        raise ValueError("firstbook_chapter_execution_not_admitted")
    binding = capture._binding(packet)
    outline = packet.get("expected_outline")
    if not isinstance(outline, list) or len(outline) != 3:
        raise ValueError("firstbook_chapter_outline_invalid")
    retained = []
    for part in outline:
        if not isinstance(part, dict) or set(part) != {"title", "description"}:
            raise ValueError("firstbook_chapter_outline_invalid")
        retained.append({"title": capture._text(part, "title"),
                         "description": capture._text(part, "description", MAX_DESCRIPTION_CHARS)})
    return {**binding, "expected_outline": retained, "depth": "Brief"}


def _inspect(session: str) -> dict:
    observed = capture._eval(session, """(() => {
        const main = document.querySelector('main');
        const outline = Array.from(main?.querySelectorAll('h3') || [])
            .filter(e => e.innerText.trim().toLowerCase() === 'chapter outline');
        const indicator = main?.innerText.match(/chapter\\s+(\\d+)\\s+of\\s+(\\d+)/i);
        const writes = Array.from(main?.querySelectorAll('button') || [])
            .filter(e => e.innerText.trim() === 'Write Chapter');
        const brief = Array.from(main?.querySelectorAll('button') || [])
            .filter(e => Array.from(e.querySelectorAll('div')).some(d => d.innerText === 'Brief'));
        return {origin:location.origin, chapterTitle:main?.querySelector('h2')?.innerText,
            chapterNumber:indicator ? Number(indicator[1]) : null,
            chapterCount:indicator ? Number(indicator[2]) : null,
            outlineCount:outline.length,
            outline:outline.length===1 ? Array.from(outline[0].parentElement.querySelectorAll('li'))
                .map(e=>({title:e.querySelector('strong')?.innerText,
                    description:e.querySelector('strong')?.parentElement.querySelector('span')?.innerText})) : [],
            writeCount:writes.length, writeEnabled:writes.length===1 && !writes[0].disabled,
            includedInPlan:main?.innerText.includes('Included in your book plan') === true,
            briefCount:brief.length,
            briefSelected:brief.length===1 && brief[0].classList.contains('border-brand'),
            generating:main?.innerText.includes('Generating chapter...') === true,
            generationLabels:Array.from(main?.querySelectorAll('.animate-pulse') || [])
                .filter(e=>!e.closest('.prose')).map(e=>e.innerText.trim()),
            hasDraft:document.querySelector('.prose h1')!==null};
    })()""")
    # First Book keeps the previous draft visible while rewriting individual
    # subchapters. That is still live frontend work: navigation interrupts it.
    labels = observed.pop("generationLabels", [])
    observed["generating"] = observed.get("generating") is True or (
        isinstance(labels, list) and any(isinstance(label, str) and
            re.fullmatch(r'Writing Subchapter [1-9][0-9]* of [1-9][0-9]*: [^\n]{1,400}', label)
            for label in labels))
    return observed


def _require_prepared(binding: dict, observed: dict, *, brief: bool = False) -> None:
    if (observed.get("origin") != capture._ORIGIN.rstrip("/")
        or observed.get("chapterTitle") != binding["chapter_title"]
        or observed.get("chapterNumber") != binding["chapter_number"]
        or type(observed.get("chapterCount")) is not int
        or not binding["chapter_number"] <= observed["chapterCount"] <= 100
        or observed.get("outlineCount") != 1
        or observed.get("outline") != binding["expected_outline"]
        or observed.get("writeCount") != 1 or observed.get("writeEnabled") is not True
        or observed.get("includedInPlan") is not True
        or observed.get("briefCount") != 1 or observed.get("hasDraft") is not False
        or (brief and observed.get("briefSelected") is not True)):
        raise RuntimeError("firstbook_chapter_prepared_source_mismatch")


def _private_root(output_root: Path) -> Path:
    root = output_root.absolute() / "firstbook-private-writes"
    for part in (root, *root.parents):
        if part.is_symlink():
            raise RuntimeError("firstbook_chapter_linked_storage")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("firstbook_chapter_storage_not_private")
    return root


def _load(path: Path) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stored:
        info = os.fstat(stored.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > _MAX_RECORD_BYTES):
            raise RuntimeError("firstbook_chapter_record_invalid")
        raw = stored.read(_MAX_RECORD_BYTES + 1)
    if len(raw) > _MAX_RECORD_BYTES:
        raise RuntimeError("firstbook_chapter_record_invalid")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise RuntimeError("firstbook_chapter_record_invalid") from None
    if not isinstance(value, dict):
        raise RuntimeError("firstbook_chapter_record_invalid")
    return value


def _save(path: Path, value: dict) -> None:
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(data) > _MAX_RECORD_BYTES:
        raise RuntimeError("firstbook_chapter_record_oversized")
    fd, temporary = tempfile.mkstemp(prefix=".chapter-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if path.is_symlink():
            raise RuntimeError("firstbook_chapter_linked_storage")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _result(binding: dict, observed: dict) -> dict:
    # Retain a provider observation, not semantic approval or Core provenance.
    base = {key: value for key, value in binding.items() if key not in ("expected_outline", "depth")}
    return {**capture._capture(base, observed), "mode": MODE,
            "provider_generation_attempted": True,
            "generation_stage": "dispatched_chapter_review",
            "generation_causally_attested": False}


def _validate_retained(binding: dict, record: dict) -> None:
    if (set(record) != {"binding", "state", "result"} or record.get("binding") != binding
        or record.get("state") not in ("write_dispatched", "chapter_review_required")):
        raise RuntimeError("firstbook_chapter_retained_binding_mismatch")
    if record["state"] == "write_dispatched":
        if record["result"] is not None:
            raise RuntimeError("firstbook_chapter_record_invalid")
        return
    try:
        result = record["result"]
        expected = _result(binding, {
            "origin": capture._ORIGIN.rstrip("/"), "bookTitles": [binding["book_title"]],
            "chapterTitle": binding["chapter_title"], "chapterNumber": binding["chapter_number"],
            "chapterCount": result["chapter_count_observed"], "surfaceCount": 1,
            "text": result["text"], "reviewRequired": True, "editing": False, "approveControl": 1,
        })
        valid = result == expected
    except (KeyError, TypeError, ValueError, RuntimeError):
        valid = False
    if not valid:
        raise RuntimeError("firstbook_chapter_record_invalid")


def _record_path(root: Path, binding: dict) -> Path:
    identity = [binding[key] for key in ("account_sha256", "provider_book_id", "chapter_number")]
    return root / (capture._sha(json.dumps(identity, separators=(",", ":"))) + ".json")


def write_prepared_chapter(packet: dict, output_root: Path, *, allow_new_dispatch: bool = True) -> dict:
    """Start at most once, otherwise recover/observe. Never waits for generation."""
    binding = _binding(packet)
    session = capture._text(packet, "browser_session", 128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        raise ValueError("firstbook_invalid_browser_session")
    root = _private_root(output_root)
    # A different request ID cannot generate this paid project/chapter again.
    path = _record_path(root, binding)
    lock_fd = os.open(root / ".writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("firstbook_chapter_worker_busy") from None
        record = _load(path)
        if record is not None:
            _validate_retained(binding, record)
            if record["state"] == "chapter_review_required":
                return {**record["result"], "asset_path": str(path), "reused_capture": True}
        elif not allow_new_dispatch:
            # An upstream admission response may have been lost before this
            # adapter persisted its fence. Do not turn recovery into generation.
            return {"mode": MODE, "render_status": "reconciliation_required",
                    "request_id": binding["request_id"], "asset_path": str(path),
                    "publication_authorized": False, "retry_generation_allowed": False}
        # First Book writes through the live page. Do not navigate away from an
        # active generation to perform readback; that can interrupt its requests.
        # This hint never authorizes a result or mutation, even on another page.
        if _inspect(session).get("generating") is True:
            return {"mode": MODE, "render_status": "provider_busy",
                    "request_id": binding["request_id"], "asset_path": str(path),
                    "publication_authorized": False, "retry_generation_allowed": False}
        capture._open_book(session, binding)
        observed = _inspect(session)
        if record is not None:
            if observed.get("hasDraft") is True:
                result = _result(binding, capture._read_draft(session))
                _save(path, {"binding": binding, "state": "chapter_review_required", "result": result})
                return {**result, "asset_path": str(path), "reused_capture": False}
            return {"mode": MODE, "render_status": "reconciliation_required",
                    "request_id": binding["request_id"], "asset_path": str(path),
                    "publication_authorized": False, "retry_generation_allowed": False}
        _require_prepared(binding, observed)
        capture._click(session, "xpath=//button[div[normalize-space(.)='Brief']]")
        _require_prepared(binding, _inspect(session), brief=True)
        _save(path, {"binding": binding, "state": "write_dispatched", "result": None})
        # No exception/cancellation can undo the fsynced dispatch fence.
        capture._click(session, "xpath=//button[normalize-space(.)='Write Chapter']")
        return {"mode": MODE, "render_status": "generation_dispatched",
                "request_id": binding["request_id"], "asset_path": str(path),
                "publication_authorized": False, "retry_generation_allowed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-path", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    with open(args.packet_path, "rb") as source:
        raw = source.read(64_001)
    if len(raw) > 64_000:
        raise ValueError("firstbook_chapter_input_oversized")
    packet = json.loads(raw)
    if not isinstance(packet, dict):
        raise ValueError("firstbook_chapter_input_invalid")
    result = write_prepared_chapter(packet, Path(args.output_root))
    # Do not put the private manuscript or account binding in operator logs.
    print(json.dumps({key: result[key] for key in (
        "render_status", "request_id", "asset_path", "reused_capture", "text_sha256",
        "retry_generation_allowed", "publication_authorized") if key in result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
