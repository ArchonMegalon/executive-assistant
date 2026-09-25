"""Private local adapter for Hub-admitted First Book setup and chapter work.

No polling daemon, credential lookup, new spending authorization or public tool
registration. A trusted operator supplies approved source and an owned browser
session. Setup stops at the unapproved framework
unless separate local approval allows one existing credit for a confirmed-fact
outline. Writing still requires an exact prepared book mapping. Hub remains consent,
job and result authority.

The optional origin_chapter_cycle module composes these bounded phases for one
explicitly approved packet; it does not add queue admission or spending policy.
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
from scripts import firstbook_project_prepare as preparation
from scripts import firstbook_outline_prepare as outline_preparation
from scripts import firstbook_next_chapter_prepare as next_preparation
from scripts import firstbook_chapter_review as review

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
    def __init__(self, origin: str, token_file: Path, *, host: str | None = None):
        parsed = urllib.parse.urlsplit(origin)
        try:
            local = ipaddress.ip_address(parsed.hostname or "").is_loopback
            valid_port = parsed.port is not None and 1024 <= parsed.port <= 65535
        except ValueError:
            local = valid_port = False
        if (parsed.scheme != "http" or not local or not valid_port or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("origin_worker_requires_explicit_loopback_listener")
        if host is not None and (not isinstance(host, str) or len(host) > 253 or not re.fullmatch(
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host)):
            raise ValueError("origin_worker_invalid_host")
        self.origin = origin.rstrip("/")
        # Production HostFiltering still applies on the private listener. Only
        # the HTTP virtual host changes; the socket remains literal loopback.
        self._host = host
        self._token = _read_private(token_file, 256).decode("ascii").strip()
        if len(self._token) < 32 or any(ord(char) <= 32 or ord(char) >= 127 for char in self._token):
            raise ValueError("origin_worker_invalid_service_token")
        self._http = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects())

    def call(self, work_id: str, action: str = "", body: dict | None = None) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", work_id) or action not in ("", "/admit", "/complete", "/revise-unaccepted"):
            raise ValueError("origin_worker_invalid_route")
        result = self._request(work_id + action, body)
        if not isinstance(result, dict):
            raise ValueError("origin_worker_hub_response_invalid")
        return result

    def pending(self, book_ref: str, limit: int = 20) -> list[dict]:
        if (not isinstance(book_ref, str) or not re.fullmatch(r"[0-9a-f]{64}", book_ref)
            or type(limit) is not int or not 1 <= limit <= 20):
            raise ValueError("origin_worker_invalid_route")
        result = self._request(f"pending?limit={limit}&bookRef={book_ref}", None)
        if (not isinstance(result, list) or len(result) > limit
            or any(not isinstance(work, dict) or work.get("bookRef") != book_ref for work in result)):
            raise ValueError("origin_worker_hub_response_invalid")
        return result

    def pending_books(self) -> list[dict]:
        """Private bounded discovery; only the separately approved pool uses it."""
        result = self._request("pending?limit=20", None)
        if not isinstance(result, list) or len(result) > 20 or any(not isinstance(work, dict) for work in result):
            raise ValueError("origin_worker_hub_response_invalid")
        return result

    def _request(self, route: str, body: dict | None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        if data is not None and len(data) > 128 * 1024:
            raise ValueError("origin_worker_request_oversized")
        headers = {"Authorization": "Bearer " + self._token, "Content-Type": "application/json", "Accept": "application/json"}
        if self._host is not None:
            headers["Host"] = self._host
        request = urllib.request.Request(self.origin + _PREFIX + route, data=data, headers=headers)
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
        return _json(raw)


def _validate_work(work: dict, packet: dict, *, preparing: bool = False) -> dict:
    job = work.get("job")
    if (work.get("workId") != packet["work_id"] or not isinstance(job, dict)
        or not isinstance(work.get("bookRef"), str) or not re.fullmatch(r"[0-9a-f]{64}", work["bookRef"])
        or job.get("sourceDigest") != packet["setup" if preparing else "prepared"]["source_packet_sha256"]
        or job.get("source") != packet["approved_source"]
        or job.get("provider") != "first_book_ai" or job.get("requiresReaderReview") is not True
        or job.get("affectsMechanics") is not False or job.get("publicationAuthorized") is not False
        or job.get("state") not in ("awaiting_authoring", "reconciliation_required", "review_required")
        or work.get("executionAdmission") not in (None, packet["execution_admission"])):
        raise ValueError("origin_worker_hub_binding_mismatch")
    previous = job.get("previous")
    if previous is not None or work.get("previousWorkId") is not None:
        parent_packet = packet.get("previous")
        if (not isinstance(previous, dict)
            or set(previous) != {"requestId", "sourceDigest", "providerReceiptDigest", "textDigest"}
            or not isinstance(previous.get("requestId"), str) or not previous["requestId"].strip()
            or len(previous["requestId"]) > 256
            or any(not isinstance(previous[key], str) or not re.fullmatch(r"[0-9a-f]{64}", previous[key])
                for key in ("sourceDigest", "providerReceiptDigest", "textDigest"))
            or parent_packet is not None and (not isinstance(parent_packet, dict)
                or work.get("previousWorkId") != parent_packet.get("work_id"))
            or not isinstance(work.get("previousWorkId"), str)
            or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", work["previousWorkId"])
            or work["previousWorkId"][:64] != work["workId"][:64]
            or work["previousWorkId"] == work["workId"]):
            raise ValueError("origin_worker_predecessor_binding_mismatch")
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


def _validate_previous(work: dict, old: dict, packet: dict) -> dict:
    old_job = _validate_work(old, packet)
    source, old_source = work["job"]["source"], old_job["source"]
    if (old["bookRef"] != work["bookRef"]
        or any(source.get(key) != old_source.get(key) for key in ("workspaceId", "locale", "runnerName"))
        or source.get("chapterId") == old_source.get("chapterId")
        or source.get("acceptedDecisionId") == old_source.get("acceptedDecisionId")):
        raise ValueError("origin_worker_next_chapter_source_mismatch")
    if work["job"].get("previous") is not None:
        expected = {"requestId": old_job.get("requestId"), "sourceDigest": old_job["sourceDigest"],
            "providerReceiptDigest": old_job.get("providerReceiptDigest"),
            "textDigest": old_job.get("readerAcceptedTextDigest")}
        if (work.get("previousWorkId") != old["workId"] or work["job"]["previous"] != expected
            or old_job.get("readerAcceptedTextDigest") is None
            or any(fact not in source.get("facts", []) for fact in old_source.get("facts", []))):
            raise ValueError("origin_worker_predecessor_binding_mismatch")
    return old_job


def prepare_once(packet: dict, hub: LocalHub, output_root: Path) -> dict:
    """Admit initial framework setup without requiring a manually created book.

    Framework consent alone stops before payment/writing. Explicit local
outline activation can use one existing credit but never write a chapter.
    Source and stable BookRef come from Hub, not the provider framework.
    """
    if (not isinstance(packet.get("work_id"), str)
        or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", packet["work_id"])
        or not isinstance(packet.get("execution_admission"), str)
        or not 1 <= len(packet["execution_admission"]) <= 256
        or any(ord(c) < 33 for c in packet["execution_admission"])
        or not isinstance(packet.get("approved_source"), dict)
        or not isinstance(packet.get("setup"), dict)
        or packet["setup"].get("framework_generation_approved") is not True):
        raise ValueError("origin_worker_setup_packet_invalid")
    observed = hub.call(packet["work_id"])
    job = _validate_work(observed, packet, preparing=True)
    if job["state"] == "review_required":
        return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}
    if job.get("previous") is not None:
        raise ValueError("origin_worker_previous_chapter_required")
    setup = {**packet["setup"], "work_id": packet["work_id"], "book_ref": observed["bookRef"],
             "approved_source": job["source"]}
    preparation._binding(setup)
    admitted = hub.call(packet["work_id"], "/admit", {
        "sourceDigest": job["sourceDigest"], "executionAdmission": packet["execution_admission"]})
    if not isinstance(admitted.get("work"), dict) or type(admitted.get("mayStartGeneration")) is not bool:
        raise ValueError("origin_worker_admission_response_invalid")
    fenced = _validate_work(admitted["work"], packet, preparing=True)
    if (admitted["work"].get("bookRef") != observed["bookRef"]
        or admitted["work"].get("executionAdmission") != packet["execution_admission"]
        or fenced["state"] != "reconciliation_required"):
        raise ValueError("origin_worker_admission_response_invalid")
    result = preparation.prepare_framework(setup, output_root, allow_new_dispatch=admitted["mayStartGeneration"])
    if setup.get("outline_activation_approved") is True and result["state"] == "framework_bound_needs_outline_review":
        # Separate trusted local approval for spending one existing book credit.
        # Framework admission alone never authorizes payment or chapter writing.
        result = outline_preparation.prepare_first_chapter(setup, output_root)
    return {"state": result["state"], "work_id": packet["work_id"], "publication_authorized": False}


def prepare_next_once(packet: dict, hub: LocalHub, output_root: Path) -> dict:
    """Prepare only the next requested stage, in the same accepted private book."""
    if (not isinstance(packet.get("work_id"), str)
        or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", packet["work_id"])
        or not isinstance(packet.get("execution_admission"), str)
        or not 1 <= len(packet["execution_admission"]) <= 256
        or any(ord(c) < 33 for c in packet["execution_admission"])
        or not isinstance(packet.get("setup"), dict) or not isinstance(packet.get("approved_source"), dict)):
        raise ValueError("origin_worker_admitted_packet_invalid")
    previous = packet.get("previous")
    if not isinstance(previous, dict) or not isinstance(previous.get("prepared"), dict):
        raise ValueError("origin_worker_previous_chapter_required")
    prior = {**previous["prepared"], "request_id": previous["work_id"]}
    writer._binding(prior)
    observed = hub.call(packet["work_id"])
    job = _validate_work(observed, packet, preparing=True)
    old = hub.call(previous["work_id"])
    old_job = _validate_previous(observed, old, previous)
    source, old_source = job["source"], old_job["source"]
    setup = {**packet["setup"], "work_id": packet["work_id"], "book_ref": observed["bookRef"],
             "approved_source": source}
    next_preparation._plan(setup, prior)
    if setup.get("outline_update_approved") is not True:
        raise ValueError("firstbook_next_outline_not_admitted")
    if job["state"] == "review_required":
        return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}
    if old_job.get("readerAcceptedTextDigest") is None:
        return {"state": "awaiting_reader_acceptance", "work_id": packet["work_id"], "publication_authorized": False}
    books.bind_prepared(old["bookRef"], old_source["chapterId"], prior, output_root)
    advanced = advancement.advance_accepted_chapter({**prior, "browser_session": setup["browser_session"]}, output_root,
        old_job["readerAcceptedTextDigest"], old_job["providerReceiptDigest"])
    if advanced["render_status"] != "next_chapter_observed":
        return {"state": advanced["render_status"], "work_id": packet["work_id"], "publication_authorized": False}
    admitted = hub.call(packet["work_id"], "/admit", {
        "sourceDigest": job["sourceDigest"], "executionAdmission": packet["execution_admission"]})
    if not isinstance(admitted.get("work"), dict) or type(admitted.get("mayStartGeneration")) is not bool:
        raise ValueError("origin_worker_admission_response_invalid")
    fenced = _validate_work(admitted["work"], packet, preparing=True)
    if (admitted["work"].get("bookRef") != observed["bookRef"]
        or admitted["work"].get("executionAdmission") != packet["execution_admission"]
        or fenced["state"] != "reconciliation_required"):
        raise ValueError("origin_worker_admission_response_invalid")
    result = next_preparation.prepare_next_chapter(setup, prior, output_root,
        old_job["readerAcceptedTextDigest"], old_job["providerReceiptDigest"],
        allow_new_dispatch=admitted["mayStartGeneration"])
    return {"state": result["state"], "work_id": packet["work_id"], "publication_authorized": False}


def run_once(packet: dict, hub: LocalHub, output_root: Path, *, advance_accepted: bool = False,
             reviewed_draft_digest: str | None = None) -> dict:
    if (not isinstance(packet.get("work_id"), str)
        or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", packet["work_id"])
        or not isinstance(packet.get("execution_admission"), str)
        or not 1 <= len(packet["execution_admission"]) <= 256
        or any(ord(c) < 33 for c in packet["execution_admission"])
        or not isinstance(packet.get("prepared"), dict) or not isinstance(packet.get("approved_source"), dict)):
        raise ValueError("origin_worker_admitted_packet_invalid")
    prepared = {**packet["prepared"], "request_id": packet["work_id"]}
    binding = writer._binding(prepared)  # Validate consent/execution assertion before HTTP.
    if reviewed_draft_digest is not None:
        if advance_accepted:
            raise ValueError("origin_worker_review_cannot_approve")
        review._binding(binding, reviewed_draft_digest)
    if prepared["narrative_locale"] != packet["approved_source"].get("locale"):
        raise ValueError("origin_worker_story_language_mismatch")
    observed = hub.call(packet["work_id"])
    job = _validate_work(observed, packet)
    if job.get("previous") is not None and job["state"] != "review_required":
        previous = packet.get("previous")
        if not isinstance(previous, dict) or not isinstance(previous.get("prepared"), dict):
            raise ValueError("origin_worker_previous_chapter_required")
        _validate_previous(observed, hub.call(previous["work_id"]), previous)
    book_ref = observed["bookRef"]
    first_handoff = False
    if (not advance_accepted and reviewed_draft_digest is None
        and job["state"] != "review_required" and binding["chapter_number"] == 1):
        # Validate before reserving the immutable provider mapping as well as
        # before dispatch. A stale/wrong prepared packet must not poison it.
        first = outline_preparation.retained_first_chapter({
            "work_id": packet["work_id"], "book_ref": book_ref,
            "account_sha256": binding["account_sha256"],
            "source_packet_sha256": binding["source_packet_sha256"],
            "approved_source": job["source"], "framework_generation_approved": True,
        }, output_root)
        if first is not None:
            if writer._binding({**first, "generation_approved": True}) != binding:
                raise RuntimeError("origin_worker_first_chapter_handoff_mismatch")
            first_handoff = True
    next_handoff = False
    if (not advance_accepted and reviewed_draft_digest is None
        and job["state"] != "review_required" and binding["chapter_number"] > 1):
        previous = packet.get("previous")
        if not isinstance(previous, dict) or not isinstance(previous.get("prepared"), dict):
            raise ValueError("origin_worker_previous_chapter_required")
        next_ready = next_preparation.retained_next_chapter({
            "work_id": packet["work_id"], "book_ref": book_ref,
            "account_sha256": binding["account_sha256"], "source_packet_sha256": binding["source_packet_sha256"],
            "approved_source": job["source"],
        }, {**previous["prepared"], "request_id": previous["work_id"]}, output_root)
        if next_ready is None or writer._binding(next_ready) != binding:
            raise RuntimeError("origin_worker_next_chapter_handoff_mismatch")
        next_handoff = True
    books.bind_prepared(book_ref, job["source"].get("chapterId"), prepared, output_root)
    if advance_accepted:
        if job.get("readerAcceptedTextDigest") is None:
            return {"state": "awaiting_reader_acceptance", "work_id": packet["work_id"], "publication_authorized": False}
        advanced = advancement.advance_accepted_chapter(prepared, output_root,
            job["readerAcceptedTextDigest"], job["providerReceiptDigest"])
        return {"state": advanced["render_status"], "work_id": packet["work_id"], "publication_authorized": False}
    if job["state"] == "review_required":
        if reviewed_draft_digest is not None and writer.capture._sha(job["draftText"]) != reviewed_draft_digest:
            raise ValueError("origin_worker_delivered_draft_is_immutable")
        return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}
    if reviewed_draft_digest is not None:
        if (job["state"] != "reconciliation_required"
            or observed.get("executionAdmission") != packet["execution_admission"]):
            raise ValueError("origin_worker_review_requires_existing_admission")
        review._original(binding, output_root)
    admitted = hub.call(packet["work_id"], "/admit", {
        "sourceDigest": job["sourceDigest"], "executionAdmission": packet["execution_admission"]})
    if not isinstance(admitted.get("work"), dict) or type(admitted.get("mayStartGeneration")) is not bool:
        raise ValueError("origin_worker_admission_response_invalid")
    fenced = _validate_work(admitted["work"], packet)
    if (admitted["work"].get("bookRef") != book_ref
        or admitted["work"].get("executionAdmission") != packet["execution_admission"]
        or fenced["state"] != "reconciliation_required"):
        raise ValueError("origin_worker_admission_response_invalid")
    if reviewed_draft_digest is not None:
        if admitted["mayStartGeneration"]:
            raise ValueError("origin_worker_review_cannot_generate")
        result = review.capture_reviewed_chapter(prepared, output_root, reviewed_draft_digest)
    else:
        # Outline preparation already consumed the Hub admission. Only its
        # completed, exact handoff permits a separately fenced write afterwards.
        result = writer.write_prepared_chapter(prepared, output_root,
            allow_new_dispatch=admitted["mayStartGeneration"] or first_handoff or next_handoff)
    if result.get("render_status") != "chapter_review_required":
        return {"state": result["render_status"], "work_id": packet["work_id"], "publication_authorized": False}
    # Receipt bytes come from the adapter's private retained result, not text or
    # a digest supplied by the public app. Same result => same receipt on retry.
    retained = _read_private(Path(result["asset_path"]), _MAX_BYTES)
    receipt = hashlib.sha256(retained).hexdigest()
    saved = _json(retained)
    if reviewed_draft_digest is None:
        writer._validate_retained(binding, saved)
        selected = saved["result"]
    else:
        writer.capture._validate_retained(review._binding(binding, reviewed_draft_digest), saved)
        if saved["text_sha256"] != reviewed_draft_digest:
            raise ValueError("origin_worker_review_text_changed")
        selected = saved
    if selected.get("text") != result.get("text"):
        raise ValueError("origin_worker_result_changed")
    if len(selected["text"].encode("utf-8")) > 65536:
        raise ValueError("origin_worker_result_oversized")
    completed = hub.call(packet["work_id"], "/complete", {
        "sourceDigest": job["sourceDigest"], "executionAdmission": packet["execution_admission"],
        "draftText": result["text"], "providerReceiptDigest": receipt})
    completed_job = _validate_work(completed, packet)
    if (completed.get("bookRef") != book_ref or completed_job.get("draftText") != result["text"]
        or completed_job.get("providerReceiptDigest") != receipt):
        raise ValueError("origin_worker_completion_readback_mismatch")
    return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}


def revise_unaccepted_once(packet: dict, hub: LocalHub, output_root: Path, *,
                           text_digest: str, expected_receipt_digest: str, expected_text_digest: str) -> dict:
    """Explicit read-only capture and CAS handoff, never a provider rewrite.

    The operator has already edited the retained provider draft. Both versions
    must exist in private custody. Normal polling/completion cannot enter here.
    Hub refuses an accepted reading and retains every superseded draft.
    """
    if (not isinstance(packet, dict) or not isinstance(packet.get("work_id"), str)
        or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", packet["work_id"])
        or not isinstance(packet.get("execution_admission"), str)
        or not 1 <= len(packet["execution_admission"]) <= 256
        or any(ord(c) < 33 for c in packet["execution_admission"])
        or not isinstance(packet.get("prepared"), dict) or not isinstance(packet.get("approved_source"), dict)
        or any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
               for digest in (text_digest, expected_receipt_digest, expected_text_digest))
        or text_digest == expected_text_digest):
        raise ValueError("origin_worker_revision_binding_invalid")
    prepared = {**packet["prepared"], "request_id": packet["work_id"]}
    binding = writer._binding(prepared)
    if prepared["narrative_locale"] != packet["approved_source"].get("locale"):
        raise ValueError("origin_worker_story_language_mismatch")
    original, original_path = review._original(binding, output_root)
    prior = original["result"]
    prior_receipt = hashlib.sha256(_read_private(original_path, _MAX_BYTES)).hexdigest()
    if prior_receipt != expected_receipt_digest:
        retained = review.retained(binding, output_root, expected_text_digest)
        if retained is None:
            raise ValueError("origin_worker_revision_previous_not_retained")
        prior, prior_path = retained
        prior_receipt = hashlib.sha256(_read_private(prior_path, _MAX_BYTES)).hexdigest()
    if prior_receipt != expected_receipt_digest or writer.capture._sha(prior["text"]) != expected_text_digest:
        raise ValueError("origin_worker_revision_previous_mismatch")
    observed = hub.call(packet["work_id"])
    job = _validate_work(observed, packet)
    if job["state"] != "review_required" or job.get("readerAcceptedTextDigest") is not None:
        raise ValueError("origin_worker_revision_requires_unaccepted_draft")
    current_text_digest = writer.capture._sha(job["draftText"])
    if not (job["providerReceiptDigest"] == expected_receipt_digest and current_text_digest == expected_text_digest
            or current_text_digest == text_digest):
        raise ValueError("origin_worker_revision_previous_changed")
    books.bind_prepared(observed["bookRef"], job["source"].get("chapterId"), prepared, output_root)
    result = review.capture_reviewed_chapter(prepared, output_root, text_digest)
    if result.get("render_status") != "chapter_review_required":
        return {"state": result["render_status"], "work_id": packet["work_id"], "publication_authorized": False}
    raw = _read_private(Path(result["asset_path"]), _MAX_BYTES)
    selected = _json(raw)
    writer.capture._validate_retained(review._binding(binding, text_digest), selected)
    if (selected["text_sha256"] != text_digest or selected["text"] != result.get("text")
        or len(selected["text"].encode("utf-8")) > 65536):
        raise ValueError("origin_worker_revision_capture_changed")
    receipt = hashlib.sha256(raw).hexdigest()
    completed = hub.call(packet["work_id"], "/revise-unaccepted", {
        "sourceDigest": job["sourceDigest"], "executionAdmission": packet["execution_admission"],
        "expectedProviderReceiptDigest": expected_receipt_digest, "expectedTextDigest": expected_text_digest,
        "draftText": selected["text"], "providerReceiptDigest": receipt})
    completed_job = _validate_work(completed, packet)
    if (completed.get("bookRef") != observed["bookRef"] or completed_job.get("draftText") != selected["text"]
        or completed_job.get("providerReceiptDigest") != receipt or completed_job.get("readerAcceptedTextDigest") is not None):
        raise ValueError("origin_worker_revision_readback_mismatch")
    return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-path", type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host", help="Explicit hostname allowed by local Hub HostFiltering; connection stays loopback.")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--advance-accepted", action="store_true",
        help="Advance only after Hub confirms exact reader acceptance; never generate the next chapter.")
    modes.add_argument("--prepare-book-framework", action="store_true",
        help="Prepare the first private framework. One-credit outline activation requires separate packet approval; never write chapters.")
    modes.add_argument("--prepare-next-chapter", action="store_true",
        help="Replace only the next placeholder from a new Hub source after exact predecessor acceptance; never generate.")
    modes.add_argument("--capture-reviewed-draft", metavar="TEXT_SHA256",
        help="Before first delivery, capture this exact edited draft; never generate or replace a delivered result.")
    modes.add_argument("--revise-unaccepted-draft", metavar="TEXT_SHA256",
        help="Capture an already edited provider draft and supersede only the exact unaccepted Hub result; no generation.")
    parser.add_argument("--expected-receipt-digest")
    parser.add_argument("--expected-text-digest")
    args = parser.parse_args()
    if bool(args.revise_unaccepted_draft) != bool(args.expected_receipt_digest and args.expected_text_digest) or (
        not args.revise_unaccepted_draft and (args.expected_receipt_digest or args.expected_text_digest)):
        parser.error("Revision requires both exact previous digests; other modes cannot accept them.")
    packet = _json(_read_private(args.packet_path, 64_000))
    if not isinstance(packet, dict):
        raise ValueError("origin_worker_invalid_packet")
    hub = LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    result = (revise_unaccepted_once(packet, hub, args.output_root, text_digest=args.revise_unaccepted_draft,
        expected_receipt_digest=args.expected_receipt_digest, expected_text_digest=args.expected_text_digest)
        if args.revise_unaccepted_draft else
        prepare_next_once(packet, hub, args.output_root) if args.prepare_next_chapter else
        prepare_once(packet, hub, args.output_root) if args.prepare_book_framework else
        run_once(packet, hub, args.output_root, advance_accepted=args.advance_accepted,
                 reviewed_draft_digest=args.capture_reviewed_draft))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
