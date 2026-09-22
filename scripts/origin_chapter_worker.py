"""Private local adapter between Hub admission and a prepared First Book chapter.

No polling daemon, credential lookup, book creation, new spending authorization
or public tool registration. A trusted operator supplies the exact prepared book
mapping and approved source. Hub remains consent/job/result authority.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import urllib.error
import urllib.parse
import urllib.request

from scripts import firstbook_chapter_write as writer
from scripts import firstbook_book_binding as books
from scripts import firstbook_chapter_advance as advancement

_PREFIX = "/api/internal/origin/chapters/"
_MAX_BYTES = 512_000


def _read_private(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("origin_worker_input_not_private")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("origin_worker_input_oversized")
    return data


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("origin_worker_duplicate_json_member")
        result[key] = value
    return result


def _json(raw: bytes):
    try:
        return json.loads(raw, object_pairs_hook=_object)
    except (ValueError, UnicodeError):
        raise ValueError("origin_worker_invalid_json") from None


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("origin_worker_redirect_rejected")


class LocalHub:
    def __init__(self, origin: str, token_file: Path):
        parsed = urllib.parse.urlsplit(origin)
        try:
            local = ipaddress.ip_address(parsed.hostname or "").is_loopback
            valid_port = parsed.port is not None and 1024 <= parsed.port <= 65535
        except ValueError:
            local = valid_port = False
        if (parsed.scheme != "http" or not local or not valid_port or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("origin_worker_requires_explicit_loopback_listener")
        self.origin = origin.rstrip("/")
        self._token = _read_private(token_file, 256).decode("ascii").strip()
        if len(self._token) < 32 or any(ord(char) <= 32 or ord(char) >= 127 for char in self._token):
            raise ValueError("origin_worker_invalid_service_token")
        self._http = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects())

    def call(self, work_id: str, action: str = "", body: dict | None = None) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", work_id) or action not in ("", "/admit", "/complete"):
            raise ValueError("origin_worker_invalid_route")
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        if data is not None and len(data) > 128 * 1024:
            raise ValueError("origin_worker_request_oversized")
        request = urllib.request.Request(self.origin + _PREFIX + work_id + action, data=data,
            headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self._http.open(request, timeout=20) as response:
                if response.status != 200:
                    raise RuntimeError("origin_worker_hub_response_rejected")
                size = response.headers.get("Content-Length")
                if size is not None and (not size.isdigit() or int(size) > _MAX_BYTES):
                    raise RuntimeError("origin_worker_hub_response_oversized")
                raw = response.read(_MAX_BYTES + 1)
        except urllib.error.HTTPError as error:
            # No response bodies, request headers or credentials in logs/errors.
            raise RuntimeError(f"origin_worker_hub_http_{error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("origin_worker_hub_unavailable_reconcile_same_job") from None
        if len(raw) > _MAX_BYTES:
            raise RuntimeError("origin_worker_hub_response_oversized")
        result = _json(raw)
        if not isinstance(result, dict):
            raise ValueError("origin_worker_hub_response_invalid")
        return result


def _validate_work(work: dict, packet: dict) -> dict:
    job = work.get("job")
    if (work.get("workId") != packet["work_id"] or not isinstance(job, dict)
        or not isinstance(work.get("bookRef"), str) or not re.fullmatch(r"[0-9a-f]{64}", work["bookRef"])
        or job.get("sourceDigest") != packet["prepared"]["source_packet_sha256"]
        or job.get("source") != packet["approved_source"]
        or job.get("provider") != "first_book_ai" or job.get("requiresReaderReview") is not True
        or job.get("affectsMechanics") is not False or job.get("publicationAuthorized") is not False
        or job.get("state") not in ("awaiting_authoring", "reconciliation_required", "review_required")
        or work.get("executionAdmission") not in (None, packet["execution_admission"])):
        raise ValueError("origin_worker_hub_binding_mismatch")
    if job["state"] == "review_required":
        if (work.get("executionAdmission") != packet["execution_admission"]
            or not isinstance(job.get("draftText"), str) or not job["draftText"].strip()
            or len(job["draftText"].encode("utf-8")) > 65536
            or not re.fullmatch(r"[0-9a-f]{64}", job.get("providerReceiptDigest") or "")):
            raise ValueError("origin_worker_completed_result_invalid")
    elif job.get("draftText") is not None or job.get("providerReceiptDigest") is not None:
        raise ValueError("origin_worker_pending_result_invalid")
    if job.get("readerAcceptedTextDigest") is not None and (job["state"] != "review_required"
        or job["readerAcceptedTextDigest"] != hashlib.sha256(job["draftText"].encode("utf-8")).hexdigest()):
        raise ValueError("origin_worker_reader_acceptance_invalid")
    return job


def run_once(packet: dict, hub: LocalHub, output_root: Path, *, advance_accepted: bool = False) -> dict:
    if (not isinstance(packet.get("work_id"), str)
        or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", packet["work_id"])
        or not isinstance(packet.get("execution_admission"), str)
        or not 1 <= len(packet["execution_admission"]) <= 256
        or any(ord(c) < 33 for c in packet["execution_admission"])
        or not isinstance(packet.get("prepared"), dict) or not isinstance(packet.get("approved_source"), dict)):
        raise ValueError("origin_worker_admitted_packet_invalid")
    prepared = {**packet["prepared"], "request_id": packet["work_id"]}
    writer._binding(prepared)  # Validate consent/execution assertion before HTTP.
    if prepared["narrative_locale"] != packet["approved_source"].get("locale"):
        raise ValueError("origin_worker_story_language_mismatch")
    observed = hub.call(packet["work_id"])
    job = _validate_work(observed, packet)
    book_ref = observed["bookRef"]
    books.bind_prepared(book_ref, job["source"].get("chapterId"), prepared, output_root)
    if advance_accepted:
        if job.get("readerAcceptedTextDigest") is None:
            return {"state": "awaiting_reader_acceptance", "work_id": packet["work_id"], "publication_authorized": False}
        advanced = advancement.advance_accepted_chapter(prepared, output_root,
            job["readerAcceptedTextDigest"], job["providerReceiptDigest"])
        return {"state": advanced["render_status"], "work_id": packet["work_id"], "publication_authorized": False}
    if job["state"] == "review_required":
        return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}
    admitted = hub.call(packet["work_id"], "/admit", {
        "sourceDigest": job["sourceDigest"], "executionAdmission": packet["execution_admission"]})
    if not isinstance(admitted.get("work"), dict) or type(admitted.get("mayStartGeneration")) is not bool:
        raise ValueError("origin_worker_admission_response_invalid")
    fenced = _validate_work(admitted["work"], packet)
    if (admitted["work"].get("bookRef") != book_ref
        or admitted["work"].get("executionAdmission") != packet["execution_admission"]
        or fenced["state"] != "reconciliation_required"):
        raise ValueError("origin_worker_admission_response_invalid")
    result = writer.write_prepared_chapter(prepared, output_root,
        allow_new_dispatch=admitted["mayStartGeneration"])
    if result.get("render_status") != "chapter_review_required":
        return {"state": result["render_status"], "work_id": packet["work_id"], "publication_authorized": False}
    # Receipt bytes come from the adapter's private retained result, not text or
    # a digest supplied by the public app. Same result => same receipt on retry.
    retained = _read_private(Path(result["asset_path"]), _MAX_BYTES)
    receipt = hashlib.sha256(retained).hexdigest()
    saved = _json(retained)
    writer._validate_retained(writer._binding(prepared), saved)
    if saved["result"].get("text") != result.get("text"):
        raise ValueError("origin_worker_result_changed")
    completed = hub.call(packet["work_id"], "/complete", {
        "sourceDigest": job["sourceDigest"], "executionAdmission": packet["execution_admission"],
        "draftText": result["text"], "providerReceiptDigest": receipt})
    completed_job = _validate_work(completed, packet)
    if (completed.get("bookRef") != book_ref or completed_job.get("draftText") != result["text"]
        or completed_job.get("providerReceiptDigest") != receipt):
        raise ValueError("origin_worker_completion_readback_mismatch")
    return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-path", type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--advance-accepted", action="store_true",
        help="Advance only after Hub confirms exact reader acceptance; never generate the next chapter.")
    args = parser.parse_args()
    packet = _json(_read_private(args.packet_path, 64_000))
    if not isinstance(packet, dict):
        raise ValueError("origin_worker_invalid_packet")
    print(json.dumps(run_once(packet, LocalHub(args.hub_origin, args.token_file), args.output_root,
        advance_accepted=args.advance_accepted)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
