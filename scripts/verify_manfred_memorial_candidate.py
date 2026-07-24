#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import unquote, urlparse


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_smoke.v1"
CONTRIBUTION_RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_contribution.v1"
PRIVATE_CONTEXT_FILENAME = "memorial_private_context.json"
PRIVATE_AUDIO_RELPATH = "audio/hanusch-hospital-visit-enhanced.mp3"
BROWSER_ZERO_COUNT_FIELDS = (
    "automatic_provider_requests",
    "automatic_readiness_requests",
    "automatic_microphone_requests",
    "automatic_websockets",
    "external_requests",
    "failed_requests",
    "page_errors",
    "http_errors",
)
VERIFIER_REQUEST_HEADERS = {
    "User-Agent": "EA-Memorial-Launch-Verifier/1.0",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
}
MEMORIAL_GUEST_COOKIE = "ea_memorial_guest"
MEMORIAL_HSTS = "max-age=31536000"
MEMORIAL_ARCHIVE_GATE_SCHEMA = "ea.memorial_archive_gate.v1"
MEMORIAL_ARCHIVE_GATE_STATE = "intentionally_unpublished"
MEMORIAL_SURFACE = "conversation_only"
SPATIAL_SCOPE = "separate_propertyquarry_lane"
VOICE_RELEASE_EXPECTATION_FIELDS = frozenset(
    {
        "access_mode",
        "source_revision",
    }
)
LEGACY_VOICE_RELEASE_EXPECTATION_FIELDS = frozenset(
    {
        "source_revision",
    }
)
VOICE_ACCESS_MODE_PUBLIC_RELEASE = "public-release"
VOICE_ACCESS_MODE_PUBLIC_EVALUATION = "owner-authorized-public-evaluation"
VOICE_RELEASE_AUTHORIZATION_PROOF = (
    "authorization_precedes_empty_text_validation_without_provider_call"
)
VOICE_RELEASE_BROWSER_STATES = frozenset({"available", "blocked"})
VOICE_ACCESS_BROWSER_STATES = frozenset(
    {"public-evaluation", "public-release", "text-only"}
)
VOICE_EVALUATION_BROWSER_STATES = frozenset({"", "owner-authorized"})
VOICE_BROWSER_STATE_TRIPLES = frozenset(
    {
        ("available", "public-release", ""),
        ("blocked", "public-evaluation", "owner-authorized"),
        ("blocked", "text-only", ""),
    }
)
CONVERSATION_ONLY_BLOCKED_ACTION_LABEL = "Gespräch beginnen"
CONVERSATION_ONLY_TEXT_PLACEHOLDER = "Was möchtest du fragen?"
_CANDIDATE_HREF_MAX_CHARS = 4096
_CANDIDATE_HREF_MAX_DECODE_ROUNDS = 4
_CONVERSATION_ONLY_FORBIDDEN_HREF_TOKENS = {
    "archive",
    "archives",
    "archiv",
    "beitrag",
    "biografie",
    "biography",
    "contribution",
    "contributions",
    "erinnerungsraum",
    "geschichte",
    "install",
    "memorial-archive",
    "memorial-contribution",
    "memorial-story",
    "memorial-tour",
    "memory-room",
    "rundgang",
    "stories",
    "story",
    "tour",
    "tours",
    "video",
}
_CONVERSATION_ONLY_FORBIDDEN_DOM_MARKERS = (
    "story",
    "biography",
    "biografie",
    "geschichte",
    "contribution",
    "beitrag",
    "install",
    "video",
    "memory-room",
    "erinnerungsraum",
    "archive",
    "archiv",
    "tour",
    "rundgang",
)
_CONVERSATION_ONLY_ALLOWED_VISIBLE_MARKER_TEXTS = (
    "wenn die seite als app installiert ist, darf sie das mikrofon nach dem "
    "start sofort vorbereiten.",
)

_FIRST_PERSON_RECONSTRUCTION_MODE = (
    "memorial_source_grounded_first_person_reconstruction"
)
_FIRST_PERSON_RECONSTRUCTION_PATTERN = re.compile(
    r"\b(?:ich|mir|mich|mein(?:e|em|en|er|es)?)\b"
)
_IDENTITY_CONFUSABLE_TRANSLATION = str.maketrans(
    {
        "@": "a",
        "0": "",
        "1": "",
        "2": "",
        "3": "e",
        "4": "a",
        "5": "",
        "6": "",
        "7": "",
        "8": "e",
        "9": "",
        "€": "e",
        "а": "a",
        "е": "e",
        "м": "m",
        "ո": "n",
        "ԁ": "d",
        "ƒ": "f",
        "ҽ": "e",
        "α": "a",
        "ε": "e",
        "μ": "m",
        "ɑ": "a",
        "ɾ": "r",
        "ᴍ": "m",
    }
)
_ALLOWED_MANFRED_DISCLOSURES = (
    "Ich bin eine quellengebundene KI-Rekonstruktion und nicht der echte "
    "Manfred.",
    "Ich bin eine quellengebundene KI-Rekonstruktion von Manfred, nicht "
    "der echte Manfred.",
    "Ich bin eine quellengebundene KI-Rekonstruktion von Manfred, nicht "
    "der echte Manfred. Ich spreche hier in einer rekonstruierten "
    "Ich-Perspektive aus freigegebenen Erinnerungen und Quellen.",
    "Ich bin eine quellengebundene KI-Rekonstruktion von Manfred, nicht "
    "der echte Manfred. Meine Antworten entstehen aus freigegebenen "
    "Erinnerungen und Quellen.",
    "Meine Stimme hier ist eine synthetische KI-Rekonstruktion und keine "
    "Originalaufnahme. Ich antworte aus freigegebenen Quellen und "
    "Erinnerungen, aber ich bin nicht der echte Manfred.",
)


def _canonical_disclosure_match_text(value: object) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        str(value or "").casefold(),
    )
    without_format_characters = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    )
    return re.sub(r"\s+", " ", without_format_characters).strip()


def _normalized_identity_match_text(
    value: object,
    *,
    format_character_replacement: str = "",
) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        str(value or "").casefold(),
    ).translate(_IDENTITY_CONFUSABLE_TRANSLATION)
    normalized_characters: list[str] = []
    for character in decomposed:
        if unicodedata.combining(character):
            continue
        if unicodedata.category(character) == "Cf":
            normalized_characters.append(format_character_replacement)
            continue
        normalized_characters.append(character)
    without_marks = "".join(normalized_characters)
    with_clause_boundaries = re.sub(
        r"[,!?.;\n]+",
        " | ",
        without_marks,
    )
    normalized = re.sub(r"[^a-z0-9|]+", " ", with_clause_boundaries)
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_literal_manfred_identity(value: object) -> bool:
    allowed_disclosures = {
        _canonical_disclosure_match_text(disclosure)
        for disclosure in _ALLOWED_MANFRED_DISCLOSURES
    }
    if _canonical_disclosure_match_text(value) in allowed_disclosures:
        return False
    decomposed = unicodedata.normalize(
        "NFKD",
        str(value or "").casefold(),
    )
    if any(
        character.isalpha()
        and not ("a" <= character <= "z")
        and not unicodedata.combining(character)
        for character in decomposed
    ):
        return True
    original = unicodedata.normalize("NFKC", str(value or ""))
    if any(character in original for character in ("\\", "|", "^")):
        return True
    screened_original = re.sub(
        r"\bdass\s+man\s+Fred\b",
        "dass ordinaryperson",
        original,
    )
    screened_original = re.sub(
        r"\ba\s+man\.\s+Fred\b",
        "a ordinaryperson",
        screened_original,
    )
    normalized_variants = {
        _normalized_identity_match_text(screened_original),
        _normalized_identity_match_text(
            screened_original,
            format_character_replacement=" ",
        ),
    }
    if re.search(
        r"\bMan(?=[\W_]*[^\w\s])[\W_]+[Ff]red\b",
        screened_original,
    ):
        return True
    if re.search(r"\bMan\s+[Ff]red\b", screened_original):
        return True
    split_name_pattern = re.compile(
        r"\bm([ |]*)a([ |]*)n([ |]*)f([ |]*)r([ |]*)e([ |]*)d\b"
    )
    for candidate in normalized_variants:
        if re.search(r"\bmanfred", candidate):
            return True
        for match in split_name_pattern.finditer(candidate):
            if any(match.group(index) for index in range(1, 7)):
                return True
    return False


def _assert_first_person_reconstruction_contract(
    payload: dict[str, object],
    *,
    error: str,
) -> str:
    narrator = payload.get("narrator")
    raw_answer = str(payload.get("answer") or "").strip()
    answer = raw_answer.casefold()
    safety_note = str(payload.get("safety_note") or "").strip().casefold()
    normalized_answers = {
        _normalized_identity_match_text(answer),
        _normalized_identity_match_text(
            answer,
            format_character_replacement=" ",
        ),
    }
    if (
        not isinstance(narrator, dict)
        or payload.get("mode") != _FIRST_PERSON_RECONSTRUCTION_MODE
        or narrator.get("synthetic") is not True
        or narrator.get("source_grounded") is not True
        or narrator.get("is_memorial_person") is not False
        or narrator.get("speaks_for_memorial_person") is not False
        or narrator.get("perspective") != "first_person_reconstruction"
        or not any(
            _FIRST_PERSON_RECONSTRUCTION_PATTERN.search(candidate)
            for candidate in normalized_answers
        )
        or _contains_literal_manfred_identity(raw_answer)
        or "ki-rekonstruktion" not in safety_note
        or "ich-perspektive" not in safety_note
        or "nicht der echte manfred" not in safety_note
    ):
        raise RuntimeError(error)
    return answer


_CANDIDATE_NAVIGATION_ATTRIBUTE_LOCAL_NAMES = {
    "action",
    "formaction",
    "href",
}
_HTML_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        del req, fp, code, msg, headers, newurl
        return None


def _http_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    hostname = str(parsed.hostname or "").casefold()
    if scheme not in {"http", "https"} or not hostname:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


def _browser_proxy_headers(base_url: str, public_origin: str) -> dict[str, str]:
    authority, canonical_origin = _canonical_public_https_origin(public_origin)
    if _http_origin(base_url) == _http_origin(canonical_origin):
        return {}
    return {
        "X-Forwarded-Host": authority,
        "X-Forwarded-Proto": "https",
    }


def _is_same_origin_http_error(
    *, base_url: str, response_url: str, status: int
) -> bool:
    return (
        int(status) >= 400
        and _http_origin(base_url) is not None
        and _http_origin(response_url) == _http_origin(base_url)
    )


def _has_exact_zero_counts(payload: dict[str, object]) -> bool:
    return all(
        type(payload.get(field)) is int and payload[field] == 0
        for field in BROWSER_ZERO_COUNT_FIELDS
    )


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    expected: set[int] | None = None,
    follow_redirects: bool = True,
) -> tuple[int, bytes, dict[str, str]]:
    data = None
    request_headers = dict(headers or {})
    # Cloudflare may reject urllib's default user agent. Keep this automation
    # identity explicit and stable; callers may add headers but cannot replace
    # the verifier identity or its bounded response preference.
    request_headers.update(VERIFIER_REQUEST_HEADERS)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        open_request = (
            urllib.request.urlopen
            if follow_redirects
            else urllib.request.build_opener(_NoRedirectHandler()).open
        )
        with open_request(request, timeout=20) as response:
            status = int(response.status)
            body = response.read(2 * 1024 * 1024 + 1)
            response_headers = {
                key.lower(): value for key, value in response.headers.items()
            }
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(2 * 1024 * 1024 + 1)
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
    allowed = expected or {200}
    if status not in allowed:
        raise RuntimeError(f"candidate_http_status_unexpected:{path}:{status}")
    if len(body) > 2 * 1024 * 1024:
        raise RuntimeError(f"candidate_http_response_too_large:{path}")
    return status, body, response_headers


def _json_body(body: bytes, *, path: str) -> dict[str, object]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"candidate_http_json_invalid:{path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"candidate_http_json_invalid:{path}")
    return payload


def _verify_singular_memorial_alias(
    base_url: str,
    public_origin: str,
    *,
    request_fn: Callable[..., tuple[int, bytes, dict[str, str]]] | None = None,
) -> None:
    request = request_fn or _request
    authority, _canonical_origin = _canonical_public_https_origin(public_origin)
    proxy_headers = {
        "Host": authority,
        "X-Forwarded-Host": authority,
        "X-Forwarded-Proto": "https",
    }
    query = "from=ea-launch-verifier"
    path = f"/memorial/manfred?{query}"
    expected_location = f"/memorials/manfred?{query}"
    expected_headers = {
        "cache-control": "no-store",
        "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff",
        "x-robots-tag": "noindex, nofollow",
    }
    for method in ("GET", "HEAD"):
        status, body, headers = request(
            base_url,
            path,
            method=method,
            headers=proxy_headers,
            expected={308},
            follow_redirects=False,
        )
        if status != 308 or headers.get("location") != expected_location:
            raise RuntimeError("candidate_memorial_alias_invalid")
        if any(
            str(headers.get(name) or "").strip().casefold() != value
            for name, value in expected_headers.items()
        ):
            raise RuntimeError("candidate_memorial_alias_invalid")
        if method == "HEAD" and body:
            raise RuntimeError("candidate_memorial_alias_invalid")


def _verify_memorial_archive_gate(
    base_url: str,
    *,
    request_fn: Callable[..., tuple[int, bytes, dict[str, str]]] | None = None,
) -> dict[str, object]:
    request = request_fn or _request
    status, body, _headers = request(
        base_url,
        "/memorials/manfred/archive.json",
        expected={404},
    )
    payload = _json_body(body, path="/memorials/manfred/archive.json")
    gate_value = payload.get("archive_gate")
    gate = dict(gate_value) if isinstance(gate_value, dict) else {}
    registry_sha256 = str(gate.get("registry_sha256") or "")
    content_type = str(_headers.get("content-type") or "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if (
        status != 404
        or media_type != "application/json"
        or set(payload) != {"detail", "archive_gate"}
        or set(gate) != {"schema", "state", "slug", "registry_sha256"}
        or str(payload.get("detail") or "") != "memorial_not_found"
        or str(gate.get("schema") or "") != MEMORIAL_ARCHIVE_GATE_SCHEMA
        or str(gate.get("state") or "") != MEMORIAL_ARCHIVE_GATE_STATE
        or str(gate.get("slug") or "") != "manfred"
        or len(registry_sha256) != 64
        or any(character not in "0123456789abcdef" for character in registry_sha256)
    ):
        raise RuntimeError("candidate_memorial_archive_gate_invalid")
    return {
        "schema": MEMORIAL_ARCHIVE_GATE_SCHEMA,
        "state": MEMORIAL_ARCHIVE_GATE_STATE,
        "slug": "manfred",
        "registry_sha256": registry_sha256,
        "http_status": 404,
        "publication_authority": False,
    }


def _canonical_public_https_origin(value: str) -> tuple[str, str]:
    try:
        parsed = urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("candidate_public_origin_transport_invalid") from exc
    hostname = str(parsed.hostname or "").strip().rstrip(".").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("candidate_public_origin_transport_invalid")
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != 443:
        authority = f"{authority}:{port}"
    return authority, f"https://{authority}"


def _verify_memorial_transport_security(
    base_url: str,
    public_origin: str,
    *,
    request_fn: Callable[..., tuple[int, bytes, dict[str, str]]] | None = None,
) -> dict[str, object]:
    request = request_fn or _request
    authority, canonical_origin = _canonical_public_https_origin(public_origin)
    page_path = "/memorials/manfred"
    proxy_headers = {
        "Host": authority,
        "X-Forwarded-Host": authority,
        "X-Forwarded-Proto": "https",
        "CF-Visitor": '{"scheme":"https"}',
    }
    status, _body, headers = request(
        base_url,
        page_path,
        headers=proxy_headers,
        expected={200},
        follow_redirects=False,
    )
    if (
        status != 200
        or headers.get("strict-transport-security", "").strip() != MEMORIAL_HSTS
        or "location" in headers
    ):
        raise RuntimeError("candidate_memorial_transport_https_invalid")

    raw_cookie = str(headers.get("set-cookie") or "").strip()
    cookies = SimpleCookie()
    try:
        cookies.load(raw_cookie)
    except CookieError as exc:
        raise RuntimeError("candidate_memorial_transport_cookie_invalid") from exc
    guest_cookie = cookies.get(MEMORIAL_GUEST_COOKIE)
    if (
        guest_cookie is None
        or not guest_cookie["secure"]
        or not guest_cookie["httponly"]
        or str(guest_cookie["samesite"] or "").casefold() != "lax"
        or str(guest_cookie["path"] or "") != page_path
        or str(guest_cookie["max-age"] or "") != "31536000"
    ):
        raise RuntimeError("candidate_memorial_transport_cookie_invalid")

    # A verifier already attached to the canonical HTTPS origin cannot prove an
    # HTTP-to-HTTPS redirect by sending another HTTPS request with fewer proxy
    # headers: the real TLS transport remains HTTPS and must continue to return
    # the page.  The deploy lane runs this verifier against its local HTTP
    # origin first, where the redirect is exercised below, and then against the
    # public HTTPS origin, where HSTS, the secure cookie, and absence of a
    # redirect are the applicable transport checks above.
    if _http_origin(base_url) == _http_origin(canonical_origin):
        return {
            "status": "pass",
            "public_origin": canonical_origin,
            "proxy_scheme_headers_consistent": True,
            "cookie": {
                "name": MEMORIAL_GUEST_COOKIE,
                "secure": True,
                "http_only": True,
                "same_site": "Lax",
                "path": page_path,
                "max_age_seconds": 31_536_000,
            },
            "hsts": MEMORIAL_HSTS,
            "http_redirect_probe": "not_applicable_to_https_base",
        }

    redirect_path = f"{page_path}?from=ea-transport-verifier"
    redirect_status, _redirect_body, redirect_headers = request(
        base_url,
        redirect_path,
        headers={"Host": authority},
        expected={308},
        follow_redirects=False,
    )
    expected_location = f"{canonical_origin}{redirect_path}"
    if (
        redirect_status != 308
        or redirect_headers.get("location") != expected_location
        or "set-cookie" in redirect_headers
    ):
        raise RuntimeError("candidate_memorial_transport_redirect_invalid")

    return {
        "status": "pass",
        "public_origin": canonical_origin,
        "proxy_scheme_headers_consistent": True,
        "cookie": {
            "name": MEMORIAL_GUEST_COOKIE,
            "secure": True,
            "http_only": True,
            "same_site": "Lax",
            "path": page_path,
            "max_age_seconds": 31_536_000,
        },
        "hsts": MEMORIAL_HSTS,
        "http_redirect_status": redirect_status,
        "http_redirect_location": expected_location,
    }


def _verify_memorial_head_surface(
    base_url: str,
    public_origin: str,
    *,
    request_fn: Callable[..., tuple[int, bytes, dict[str, str]]] | None = None,
) -> None:
    request = request_fn or _request
    authority, _canonical_origin = _canonical_public_https_origin(public_origin)
    request(
        base_url,
        "/memorials/manfred",
        method="HEAD",
        headers={
            "Host": authority,
            "X-Forwarded-Host": authority,
            "X-Forwarded-Proto": "https",
        },
        expected={200},
        follow_redirects=False,
    )


def _contains_forbidden_recipient_field(value: object) -> bool:
    forbidden = {
        "recipient",
        "recipient_id",
        "recipient_address",
        "phone_number",
        "email",
    }
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in forbidden
            or _contains_forbidden_recipient_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_recipient_field(item) for item in value)
    return False


def _wait_for_health(base_url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "candidate_health_timeout"
    while time.monotonic() < deadline:
        try:
            _request(base_url, "/healthz")
            return
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            last_error = str(exc)[:160]
            time.sleep(2)
    raise RuntimeError(last_error)


def _bounded_canonical_candidate_href(value: object) -> tuple[str, bool]:
    """Decode a candidate URL without allowing nested-encoding bypasses."""

    current = str(value or "").strip()
    unsafe = len(current) > _CANDIDATE_HREF_MAX_CHARS
    current = current[:_CANDIDATE_HREF_MAX_CHARS]
    for _round in range(_CANDIDATE_HREF_MAX_DECODE_ROUNDS):
        decoded = unquote(current, errors="replace")
        if decoded == current:
            break
        current = decoded
    if unquote(current, errors="replace") != current:
        unsafe = True
    if any(ord(character) < 32 for character in current):
        unsafe = True
    return current.casefold().replace("_", "-").replace("\\", "/"), unsafe


def _candidate_attribute_local_name(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if "}" in normalized:
        normalized = normalized.rsplit("}", 1)[-1]
    return normalized.rsplit(":", 1)[-1]


def _is_candidate_navigation_attribute(value: object) -> bool:
    return (
        _candidate_attribute_local_name(value)
        in _CANDIDATE_NAVIGATION_ATTRIBUTE_LOCAL_NAMES
    )


def _is_candidate_inline_event_attribute(value: object) -> bool:
    normalized = str(value or "").strip().casefold()
    return (
        len(normalized) > 2
        and normalized.startswith("on")
        and normalized[2:].replace("-", "").isalnum()
    )


def _candidate_href_facts(value: object) -> tuple[set[str], bool, bool, bool]:
    canonical, unsafe = _bounded_canonical_candidate_href(value)
    try:
        parsed = urlparse(canonical)
        hostname = str(parsed.hostname or "")
    except ValueError:
        parsed = urlparse("")
        hostname = ""
        unsafe = True
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        unsafe = True
    semantic_sources = [
        hostname,
        parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ]
    token_source = " ".join(semantic_sources)
    for separator in "/\\:#?&=;,.+@()[]{}":
        token_source = token_source.replace(separator, " ")
    tokens = {item for item in token_source.split() if item}
    forbidden = tokens & _CONVERSATION_ONLY_FORBIDDEN_HREF_TOKENS
    forbidden.update(_forbidden_dom_semantic_markers(semantic_sources))
    memory_room = bool(forbidden & {"memory-room", "erinnerungsraum"})
    tour = bool(
        forbidden & {"memorial-tour", "rundgang", "tour", "tours"}
    )
    return forbidden, memory_room, tour, unsafe


def _forbidden_dom_semantic_markers(values: list[str]) -> set[str]:
    normalized = " ".join(values).casefold().replace("_", "-")
    return {
        marker
        for marker in _CONVERSATION_ONLY_FORBIDDEN_DOM_MARKERS
        if marker in normalized
    }


def _forbidden_visible_text_markers(values: list[str]) -> set[str]:
    normalized = " ".join(" ".join(values).split()).casefold().replace("_", "-")
    for allowed in _CONVERSATION_ONLY_ALLOWED_VISIBLE_MARKER_TEXTS:
        normalized = normalized.replace(allowed, " ")
    return {
        marker
        for marker in _CONVERSATION_ONLY_FORBIDDEN_DOM_MARKERS
        if marker in normalized
    }


class _ConversationOnlyDocumentParser(HTMLParser):
    """Collect rendered DOM facts without mistaking script strings for elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.id_counts: dict[str, int] = {}
        self.main_count = 0
        self.nav_count = 0
        self.aside_count = 0
        self.iframe_count = 0
        self.video_count = 0
        self.article_count = 0
        self.form_count = 0
        self.details_count = 0
        self.section_count = 0
        self.conversation_settings_count = 0
        self.personal_memory_optin_count = 0
        self.personal_memory_optin_default_checked = False
        self.personal_memory_optin_default_disabled = False
        self.personal_memory_forget_count = 0
        self.memory_room_link_count = 0
        self.tour_link_count = 0
        self.public_surface = ""
        self.voice_release = ""
        self.voice_access = ""
        self.evaluation_status = ""
        self.operator_preview = ""
        self.initial_visible_button_ids: list[str] = []
        self.forbidden_dom_semantics: set[str] = set()
        self._id_text: dict[str, list[str]] = {}
        self._labelled_elements: list[
            tuple[str, str, set[str], tuple[str, ...]]
        ] = []
        self._open_text_elements: list[
            tuple[str, str, set[str], list[str]]
        ] = []
        self._open_visibility_elements: list[tuple[str, bool]] = []
        self._suppressed_text_depth = 0

    def _record_forbidden_semantics(
        self,
        *,
        tag: str,
        element_id: str,
        classes: set[str],
        reasons: set[str],
    ) -> None:
        if not reasons:
            return
        identity = f"#{element_id}" if element_id else ""
        class_identity = "".join(f".{item}" for item in sorted(classes))
        self.forbidden_dom_semantics.add(
            f"{tag}{identity}{class_identity}:{','.join(sorted(reasons))}"
        )

    def _finish_text_element(
        self,
        element: tuple[str, str, set[str], list[str]],
    ) -> None:
        tag, element_id, classes, text_parts = element
        text = " ".join(" ".join(text_parts).split())
        contiguous_text = " ".join("".join(text_parts).split())
        if element_id and text:
            self._id_text.setdefault(element_id, []).append(text)
        if text:
            self._record_forbidden_semantics(
                tag=tag,
                element_id=element_id,
                classes=classes,
                reasons=(
                    _forbidden_visible_text_markers([text])
                    | _forbidden_visible_text_markers([contiguous_text])
                ),
            )

    def handle_data(self, data: str) -> None:
        if self._suppressed_text_depth or not data.strip():
            return
        for _tag, _element_id, _classes, text_parts in self._open_text_elements:
            text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._suppressed_text_depth:
            self._suppressed_text_depth -= 1
        visibility_index = next(
            (
                index
                for index in range(
                    len(self._open_visibility_elements) - 1,
                    -1,
                    -1,
                )
                if self._open_visibility_elements[index][0] == tag
            ),
            -1,
        )
        if visibility_index >= 0:
            del self._open_visibility_elements[visibility_index:]
        matching_index = next(
            (
                index
                for index in range(len(self._open_text_elements) - 1, -1, -1)
                if self._open_text_elements[index][0] == tag
            ),
            -1,
        )
        if matching_index < 0:
            return
        completed = self._open_text_elements[matching_index:]
        del self._open_text_elements[matching_index:]
        for element in reversed(completed):
            self._finish_text_element(element)

    def finalize_semantics(self) -> None:
        for element in reversed(self._open_text_elements):
            self._finish_text_element(element)
        self._open_text_elements.clear()
        for tag, element_id, classes, reference_ids in self._labelled_elements:
            referenced_text = [
                text
                for reference_id in reference_ids
                for text in self._id_text.get(reference_id, ())
            ]
            self._record_forbidden_semantics(
                tag=tag,
                element_id=element_id,
                classes=classes,
                reasons=_forbidden_dom_semantic_markers(referenced_text),
            )

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_attribute_names = [
            str(key).strip().casefold() for key, _value in attrs
        ]
        duplicate_attribute_names = {
            name
            for name in normalized_attribute_names
            if normalized_attribute_names.count(name) > 1
        }
        attributes = {
            str(key).casefold(): str(value or "") for key, value in attrs
        }
        parent_hidden = bool(
            self._open_visibility_elements
            and self._open_visibility_elements[-1][1]
        )
        initially_hidden = bool(
            parent_hidden
            or "hidden" in attributes
            or "inert" in attributes
            or attributes.get("aria-hidden", "").strip().casefold() == "true"
        )
        raw_ids = [
            str(value or "").strip()
            for key, value in attrs
            if str(key).casefold() == "id" and str(value or "").strip()
        ]
        element_id = raw_ids[-1] if raw_ids else ""
        for raw_id in raw_ids:
            self.id_counts[raw_id] = self.id_counts.get(raw_id, 0) + 1
        classes = set(attributes.get("class", "").split())
        semantic_values = [element_id, *classes]
        semantic_values.extend(
            f"{str(key).casefold()}={str(value or '').casefold()}"
            for key, value in attrs
            if str(key).casefold().startswith("data-")
            or str(key).casefold()
            in {
                "role",
                "aria-label",
                "aria-labelledby",
                "aria-describedby",
                "aria-description",
                "aria-roledescription",
                "alt",
                "title",
            }
        )
        if tag in {"button", "input", "option", "select", "textarea"}:
            semantic_values.extend(
                f"{key}={attributes.get(key, '')}"
                for key in (
                    "alt",
                    "command",
                    "commandfor",
                    "form",
                    "formaction",
                    "name",
                    "placeholder",
                    "popovertarget",
                    "value",
                )
                if key in attributes
            )
        elif tag in {"a", "area"}:
            semantic_values.extend(
                f"{key}={attributes.get(key, '')}"
                for key in ("download", "hreflang", "rel", "target", "type")
                if key in attributes
            )
        semantic_markers = _forbidden_dom_semantic_markers(semantic_values)
        structural_reasons: set[str] = set()
        if duplicate_attribute_names:
            structural_reasons.add("duplicate-attribute")
        if any(
            _is_candidate_inline_event_attribute(name)
            for name in normalized_attribute_names
        ):
            structural_reasons.add("inline-event-handler")
        if tag == "body":
            self.public_surface = attributes.get(
                "data-public-memorial-surface", ""
            )
            self.operator_preview = attributes.get(
                "data-operator-voice-preview", ""
            )
        elif tag == "main":
            self.main_count += 1
        elif tag == "nav":
            self.nav_count += 1
        elif tag == "aside":
            self.aside_count += 1
        elif tag == "iframe":
            self.iframe_count += 1
        elif tag == "video":
            self.video_count += 1
        elif tag == "article":
            self.article_count += 1
            structural_reasons.add("article")
        elif tag == "form":
            self.form_count += 1
            if element_id != "memorial-text-turn-form":
                structural_reasons.add("unexpected-form")
        elif tag == "details":
            self.details_count += 1
            if "conversation-settings" not in classes:
                structural_reasons.add("unexpected-details")
        elif tag == "section":
            self.section_count += 1
            if not (
                (
                    element_id == "memorial-speech-transcript-shell"
                    and "speech-transcript-shell" in classes
                )
                or (
                    not element_id
                    and {"chat", "quiet-shell"}.issubset(classes)
                )
            ):
                structural_reasons.add("unexpected-section")
        elif tag == "base":
            structural_reasons.add("unexpected-base")
        elif (
            tag == "meta"
            and attributes.get("http-equiv", "").strip().casefold() == "refresh"
        ):
            structural_reasons.add("unexpected-meta-refresh")
        elif tag in {"dialog", "embed", "object", "template"}:
            structural_reasons.add(f"unexpected-{tag}")
        href_forbidden: set[str] = set()
        href_memory_room = False
        href_tour = False
        href_unsafe = False
        navigation_values = [
            str(value or "")
            for name, value in attrs
            if _is_candidate_navigation_attribute(name)
        ]
        for navigation_value in navigation_values:
            (
                navigation_forbidden,
                navigation_memory_room,
                navigation_tour,
                navigation_unsafe,
            ) = _candidate_href_facts(navigation_value)
            href_forbidden.update(navigation_forbidden)
            href_memory_room = href_memory_room or navigation_memory_room
            href_tour = href_tour or navigation_tour
            href_unsafe = href_unsafe or navigation_unsafe
        if href_forbidden:
            structural_reasons.add("forbidden-link")
        if href_unsafe:
            structural_reasons.add("unsafe-link-encoding")
        self._record_forbidden_semantics(
            tag=tag,
            element_id=element_id,
            classes=classes,
            reasons=semantic_markers | structural_reasons,
        )
        if element_id == "memorial-conversation-region":
            self.voice_release = attributes.get("data-voice-release", "")
            self.voice_access = attributes.get("data-voice-access", "")
            self.evaluation_status = attributes.get(
                "data-evaluation-status", ""
            )
        if tag == "details" and "conversation-settings" in classes:
            self.conversation_settings_count += 1
        if (
            (
                tag == "button"
                or (
                    tag == "input"
                    and attributes.get("type", "").strip().casefold()
                    in {"button", "image", "reset", "submit"}
                )
            )
            and not initially_hidden
        ):
            self.initial_visible_button_ids.append(element_id)
        if tag == "input" and element_id == "memorial-personal-memory-optin":
            self.personal_memory_optin_count += 1
            self.personal_memory_optin_default_checked = "checked" in attributes
            self.personal_memory_optin_default_disabled = "disabled" in attributes
        if tag == "button" and element_id == "memorial-personal-memory-forget":
            self.personal_memory_forget_count += 1
        if tag == "a" and href_memory_room:
            self.memory_room_link_count += 1
        if tag == "a" and href_tour:
            self.tour_link_count += 1
        labelled_by = tuple(
            (
                attributes.get("aria-labelledby", "")
                + " "
                + attributes.get("aria-describedby", "")
            ).split()
        )
        if labelled_by:
            self._labelled_elements.append(
                (tag, element_id, classes, labelled_by)
            )
        if tag not in _HTML_VOID_ELEMENTS:
            self._open_text_elements.append((tag, element_id, classes, []))
            self._open_visibility_elements.append((tag, initially_hidden))
        if tag in {"script", "style"}:
            self._suppressed_text_depth += 1


def verify_conversation_only_page_html(page_body: bytes) -> dict[str, object]:
    """Verify the exact rendered Memorial voice/text public surface."""

    try:
        page_html = page_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("candidate_conversation_surface_invalid") from exc
    parser = _ConversationOnlyDocumentParser()
    try:
        parser.feed(page_html)
        parser.close()
        parser.finalize_semantics()
    except Exception as exc:
        raise RuntimeError("candidate_conversation_surface_invalid") from exc

    required_ids = {
        "memorial-conversation-region",
        "memorial-conversation",
        "memorial-conversation-disclosure",
        "memorial-text-turn-form",
        "memorial-text-turn-input",
        "memorial-text-guidance",
        "memorial-retry-button",
        "memorial-speech-message",
        "memorial-speech-transcript",
        "memorial-chat-status",
        "memorial-speech-audio",
        "memorial-personal-memory-optin",
        "memorial-personal-memory-status",
        "memorial-personal-memory-forget",
    }
    forbidden_ids = {
        "memorial-story",
        "memorial-memory-room",
        "memorial-contribution",
        "memorial-contribution-form",
        "memorial-contribution-management",
        "memorial-install-hint",
        "memorial-install-button",
        "memorial-video-call-avatar",
    }
    missing_ids = sorted(
        element_id
        for element_id in required_ids
        if parser.id_counts.get(element_id, 0) == 0
    )
    duplicate_ids = sorted(
        element_id
        for element_id, count in parser.id_counts.items()
        if count > 1
    )
    present_forbidden_ids = sorted(
        element_id
        for element_id in forbidden_ids
        if parser.id_counts.get(element_id, 0) > 0
    )
    forbidden_dom_semantics = sorted(parser.forbidden_dom_semantics)
    conversation_button_label = " ".join(
        " ".join(parser._id_text.get("memorial-conversation", ())).split()
    )
    expected_conversation_button_label = "Gespräch beginnen"
    contract = {
        "status": "pass",
        "public_surface": parser.public_surface,
        "main_count": parser.main_count,
        "nav_count": parser.nav_count,
        "aside_count": parser.aside_count,
        "iframe_count": parser.iframe_count,
        "video_count": parser.video_count,
        "article_count": parser.article_count,
        "form_count": parser.form_count,
        "details_count": parser.details_count,
        "section_count": parser.section_count,
        "conversation_settings_count": parser.conversation_settings_count,
        "personal_memory_optin_count": parser.personal_memory_optin_count,
        "personal_memory_optin_default_checked": (
            parser.personal_memory_optin_default_checked
        ),
        "personal_memory_optin_default_disabled": (
            parser.personal_memory_optin_default_disabled
        ),
        "personal_memory_forget_count": parser.personal_memory_forget_count,
        "memory_room_link_count": parser.memory_room_link_count,
        "tour_link_count": parser.tour_link_count,
        "voice_release": parser.voice_release,
        "voice_access": parser.voice_access,
        "evaluation_status": parser.evaluation_status,
        "operator_preview": parser.operator_preview,
        "initial_visible_button_ids": parser.initial_visible_button_ids,
        "conversation_button_label": conversation_button_label,
        "missing_required_ids": missing_ids,
        "duplicate_ids": duplicate_ids,
        "present_forbidden_ids": present_forbidden_ids,
        "forbidden_dom_semantics": forbidden_dom_semantics,
    }
    if (
        parser.public_surface != "conversation-only"
        or parser.main_count != 1
        or parser.nav_count != 0
        or parser.aside_count != 0
        or parser.iframe_count != 0
        or parser.video_count != 0
        or parser.article_count != 0
        or parser.form_count != 1
        or parser.details_count != 1
        or parser.section_count != 2
        or parser.conversation_settings_count != 1
        or parser.personal_memory_optin_count != 1
        or parser.personal_memory_optin_default_checked
        or not parser.personal_memory_optin_default_disabled
        or parser.personal_memory_forget_count != 1
        or parser.memory_room_link_count != 0
        or parser.tour_link_count != 0
        or parser.operator_preview
        or parser.initial_visible_button_ids != ["memorial-conversation"]
        or conversation_button_label != expected_conversation_button_label
        or (
            parser.voice_release,
            parser.voice_access,
            parser.evaluation_status,
        )
        not in VOICE_BROWSER_STATE_TRIPLES
        or missing_ids
        or duplicate_ids
        or present_forbidden_ids
        or forbidden_dom_semantics
    ):
        contract["status"] = "fail"
        raise RuntimeError(
            "candidate_conversation_surface_invalid:"
            + json.dumps(contract, sort_keys=True, separators=(",", ":"))
        )
    return contract


def _chromium_launch_executable(browser_type: object) -> str:
    configured = str(os.environ.get("EA_PLAYWRIGHT_CHROMIUM_EXECUTABLE") or "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError("candidate_browser_executable_invalid")
        return str(path)

    bundled = Path(str(getattr(browser_type, "executable_path", "") or "")).expanduser()
    if bundled.is_file():
        return str(bundled.resolve())
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise RuntimeError("candidate_browser_executable_unavailable")


def audit_browser_surface(
    base_url: str,
    *,
    public_origin: str | None = None,
    expected_voice_release: str = "blocked",
    expected_voice_access: str = "text-only",
    expected_evaluation_status: str = "",
    expected_source_revision: str | None = None,
    exercise_conversation_action: bool = True,
) -> dict[str, object]:
    if type(exercise_conversation_action) is not bool:
        raise ValueError("candidate_browser_action_expectation_invalid")
    if expected_voice_release not in VOICE_RELEASE_BROWSER_STATES:
        raise ValueError("candidate_browser_voice_release_expectation_invalid")
    if expected_voice_access not in VOICE_ACCESS_BROWSER_STATES:
        raise ValueError("candidate_browser_voice_access_expectation_invalid")
    if expected_evaluation_status not in VOICE_EVALUATION_BROWSER_STATES:
        raise ValueError(
            "candidate_browser_voice_evaluation_expectation_invalid"
        )
    if (
        expected_voice_release,
        expected_voice_access,
        expected_evaluation_status,
    ) not in VOICE_BROWSER_STATE_TRIPLES:
        raise ValueError("candidate_browser_voice_state_pair_invalid")
    if expected_source_revision is not None and (
        len(expected_source_revision) != 40
        or any(
            character not in "0123456789abcdef"
            for character in expected_source_revision
        )
    ):
        raise ValueError("candidate_browser_source_revision_expectation_invalid")
    if expected_voice_access != "text-only" and expected_source_revision is None:
        raise ValueError("candidate_browser_source_revision_expectation_required")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("candidate_browser_runtime_unavailable") from exc

    original_tmpdir = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = "/tmp"
    requested_urls: list[str] = []
    failed_requests: list[str] = []
    page_errors: list[str] = []
    http_errors: list[str] = []
    websocket_urls: list[str] = []
    browser = None
    try:
        with sync_playwright() as playwright:
            executable_path = _chromium_launch_executable(playwright.chromium)
            launch_options: dict[str, object] = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-proxy-server",
                ],
            }
            launch_options["executable_path"] = executable_path
            browser = playwright.chromium.launch(
                **launch_options,
            )
            context_options: dict[str, object] = {
                "viewport": {"width": 390, "height": 844},
                "reduced_motion": "reduce",
            }
            if public_origin is not None:
                proxy_headers = _browser_proxy_headers(base_url, public_origin)
                if proxy_headers:
                    context_options["extra_http_headers"] = proxy_headers
            context = browser.new_context(
                **context_options,
            )
            context.add_init_script(
                """
                (() => {
                  window.__candidateGetUserMediaCalls = 0;
                  window.__candidateMediaGuardInstallError = "";
                  const guardedGetUserMedia = async () => {
                    window.__candidateGetUserMediaCalls += 1;
                    throw new DOMException(
                      "candidate browser proof forbids microphone access",
                      "NotAllowedError",
                    );
                  };
                  try {
                    if (!navigator.mediaDevices) {
                      Object.defineProperty(navigator, "mediaDevices", {
                        configurable: false,
                        value: {},
                      });
                    }
                    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
                      configurable: false,
                      writable: false,
                      value: guardedGetUserMedia,
                    });
                  } catch (error) {
                    window.__candidateMediaGuardInstallError = String(error || "unknown");
                  }
                })();
                """
            )
            page = context.new_page()
            page.on("request", lambda request: requested_urls.append(request.url))
            page.on(
                "requestfailed", lambda request: failed_requests.append(request.url)
            )
            page.on(
                "response",
                lambda response: (
                    http_errors.append(response.url)
                    if _is_same_origin_http_error(
                        base_url=base_url,
                        response_url=response.url,
                        status=response.status,
                    )
                    else None
                ),
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)[:200]))
            page.on("websocket", lambda websocket: websocket_urls.append(websocket.url))
            response = page.goto(
                f"{base_url.rstrip('/')}/memorials/manfred",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            if response is None or response.status != 200:
                raise RuntimeError("candidate_browser_page_unavailable")
            observed_source_revision = str(
                response.headers.get("x-ea-source-revision") or ""
            ).strip()
            if (
                expected_source_revision is not None
                and observed_source_revision != expected_source_revision
            ):
                raise RuntimeError("candidate_browser_source_revision_mismatch")
            page.wait_for_timeout(900)
            if exercise_conversation_action:
                page.evaluate(
                    """() => document.getElementById("memorial-conversation")?.click()"""
                )
            page.wait_for_timeout(150)

            provider_work_paths = {
                "/memorials/manfred/readiness",
                "/memorials/manfred/warmup",
                "/memorials/manfred/warmup-status",
                "/memorials/manfred/speech-transcribe",
                "/memorials/manfred/speech-synthesize",
                "/memorials/manfred/conversation-turn",
                "/memorials/manfred/realtime",
            }
            automatic_provider_requests = sorted(
                {
                    urlparse(url).path
                    for url in requested_urls
                    if urlparse(url).path in provider_work_paths
                }
            )
            automatic_readiness_requests = sum(
                1
                for url in requested_urls
                if urlparse(url).path == "/memorials/manfred/readiness"
            )
            microphone_guard = page.evaluate(
                """() => ({
                  calls: Number(window.__candidateGetUserMediaCalls || 0),
                  install_error: String(
                    window.__candidateMediaGuardInstallError || ""
                  ),
                })"""
            )
            if str(microphone_guard.get("install_error") or ""):
                raise RuntimeError("candidate_browser_microphone_guard_unavailable")
            automatic_microphone_requests = int(
                microphone_guard.get("calls") or 0
            )
            if automatic_readiness_requests:
                raise RuntimeError(
                    "candidate_browser_automatic_readiness_detected"
                )
            if automatic_provider_requests:
                raise RuntimeError("candidate_browser_automatic_provider_work_detected")
            if automatic_microphone_requests:
                raise RuntimeError(
                    "candidate_browser_automatic_microphone_detected"
                )
            if websocket_urls:
                raise RuntimeError("candidate_browser_automatic_websocket_detected")
            external_requests = sorted(
                {
                    url
                    for url in requested_urls
                    if _http_origin(url) != _http_origin(base_url)
                }
            )
            if external_requests:
                raise RuntimeError("candidate_browser_external_request_detected")
            if http_errors:
                raise RuntimeError("candidate_browser_same_origin_http_error")
            if failed_requests or page_errors:
                raise RuntimeError("candidate_browser_runtime_error")

            browser_semantic_policy = {
                "markers": list(_CONVERSATION_ONLY_FORBIDDEN_DOM_MARKERS),
                "allowed_visible_texts": list(
                    _CONVERSATION_ONLY_ALLOWED_VISIBLE_MARKER_TEXTS
                ),
                "maximum_url_chars": _CANDIDATE_HREF_MAX_CHARS,
                "maximum_decode_rounds": _CANDIDATE_HREF_MAX_DECODE_ROUNDS,
            }
            accessibility = page.evaluate(
                """(policy) => {
                  const visible = (element) => {
                    if (!element || element.getClientRects().length === 0) return false;
                    const style = getComputedStyle(element);
                    return !element.hidden && style.display !== "none" && style.visibility !== "hidden";
                  };
                  const normalize = (value) => String(value || "")
                    .toLocaleLowerCase("und")
                    .replaceAll("_", "-")
                    .replace(/\\s+/g, " ")
                    .trim();
                  const semanticMarkers = (value, allowVisibleText = false) => {
                    let normalized = normalize(value);
                    if (allowVisibleText) {
                      for (const allowed of policy.allowed_visible_texts) {
                        normalized = normalized.split(normalize(allowed)).join(" ");
                      }
                      normalized = normalize(normalized);
                    }
                    return policy.markers.filter((marker) => normalized.includes(marker));
                  };
                  const semanticClone = document.body.cloneNode(true);
                  semanticClone.querySelectorAll("script, style").forEach((element) => element.remove());
                  const forbiddenVisibleSemantics = semanticMarkers(
                    semanticClone.textContent || "",
                    true,
                  );
                  const semanticAttributeNames = new Set([
                    "alt", "aria-describedby", "aria-description", "aria-label",
                    "aria-labelledby", "aria-roledescription", "role", "title",
                  ]);
                  const interactiveAttributeNames = new Set([
                    "alt", "command", "commandfor", "form", "formaction", "name",
                    "placeholder", "popovertarget", "value",
                  ]);
                  const interactiveTags = new Set(["BUTTON", "INPUT", "OPTION", "SELECT", "TEXTAREA"]);
                  const forbiddenAttributeSemantics = [];
                  const navigationViolations = [];
                  const inlineEventHandlers = [];
                  const navigationLocalName = (name) => {
                    const normalized = normalize(name);
                    const namespaceTail = normalized.includes("}")
                      ? normalized.slice(normalized.lastIndexOf("}") + 1)
                      : normalized;
                    return namespaceTail.includes(":")
                      ? namespaceTail.slice(namespaceTail.lastIndexOf(":") + 1)
                      : namespaceTail;
                  };
                  const navigationFacts = (value) => {
                    let decoded = String(value || "").trim();
                    let unsafe = decoded.length > Number(policy.maximum_url_chars || 0);
                    decoded = decoded.slice(0, Number(policy.maximum_url_chars || 0));
                    for (let index = 0; index < Number(policy.maximum_decode_rounds || 0); index += 1) {
                      let next;
                      try {
                        next = decodeURIComponent(decoded);
                      } catch (error) {
                        unsafe = true;
                        break;
                      }
                      if (next === decoded) break;
                      decoded = next;
                    }
                    try {
                      if (decodeURIComponent(decoded) !== decoded) unsafe = true;
                    } catch (error) {
                      unsafe = true;
                    }
                    let parsed;
                    try {
                      parsed = new URL(decoded, document.baseURI);
                    } catch (error) {
                      unsafe = true;
                    }
                    if (parsed && !["http:", "https:"].includes(parsed.protocol)) unsafe = true;
                    const semanticSource = parsed
                      ? [decoded, parsed.hostname, parsed.pathname, parsed.search, parsed.hash].join(" ")
                      : decoded;
                    return {unsafe, markers: semanticMarkers(semanticSource)};
                  };
                  for (const element of document.querySelectorAll("*")) {
                    const semanticValues = [element.id || "", element.className?.baseVal || element.className || ""];
                    for (const attribute of Array.from(element.attributes || [])) {
                      const name = normalize(attribute.name);
                      if (name.startsWith("data-") || semanticAttributeNames.has(name)) {
                        semanticValues.push(`${name}=${attribute.value || ""}`);
                      }
                      if (interactiveTags.has(element.tagName) && interactiveAttributeNames.has(name)) {
                        semanticValues.push(`${name}=${attribute.value || ""}`);
                      }
                      if (name.length > 2 && name.startsWith("on") && /^[a-z0-9-]+$/.test(name.slice(2))) {
                        inlineEventHandlers.push(`${element.tagName.toLowerCase()}:${name}`);
                      }
                      if (["action", "formaction", "href"].includes(navigationLocalName(name))) {
                        const facts = navigationFacts(attribute.value);
                        if (facts.unsafe || facts.markers.length) {
                          navigationViolations.push(
                            `${element.tagName.toLowerCase()}:${name}:${facts.unsafe ? "unsafe" : facts.markers.join(",")}`,
                          );
                        }
                      }
                    }
                    const markers = semanticMarkers(semanticValues.join(" "));
                    if (markers.length) {
                      forbiddenAttributeSemantics.push(
                        `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}:${markers.join(",")}`,
                      );
                    }
                  }
                  const forbiddenPseudoElementSemantics = [];
                  for (const element of document.body.querySelectorAll("*")) {
                    if (!visible(element)) continue;
                    const pseudoContent = ["::before", "::after"]
                      .map((pseudo) => getComputedStyle(element, pseudo).content || "")
                      .join(" ");
                    const markers = semanticMarkers(pseudoContent);
                    if (markers.length) {
                      forbiddenPseudoElementSemantics.push(
                        `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}:${markers.join(",")}`,
                      );
                    }
                  }
                  const controls = Array.from(document.querySelectorAll("input, textarea, select, button"))
                    .filter((element) => visible(element) && String(element.type || "") !== "hidden");
                  const visibleButtons = controls.filter((element) => element.tagName === "BUTTON");
                  const visibleNonButtonControls = controls.filter((element) => element.tagName !== "BUTTON");
                  const unlabeled = controls.filter((element) => {
                    if (element.tagName === "BUTTON") {
                      return !String(element.innerText || element.textContent || element.getAttribute("aria-label") || element.title || "").trim();
                    }
                    return !(element.labels && element.labels.length) && !String(element.getAttribute("aria-label") || "").trim();
                  }).map((element) => element.id || element.name || element.tagName);
                  const story = document.getElementById("memorial-story");
                  const conversation = document.getElementById("memorial-conversation-region");
                  const storyRect = story?.getBoundingClientRect();
                  const conversationRect = conversation?.getBoundingClientRect();
                  const conversationPosition = conversation ? getComputedStyle(conversation).position : "missing";
                  const unwantedIds = [
                    "memorial-story", "memorial-memory-room", "memorial-contribution-form",
                    "memorial-contribution-management", "memorial-install-hint",
                    "memorial-install-button", "memorial-video-call-avatar"
                  ].filter((id) => document.getElementById(id));
                  return {
                    lang: document.documentElement.lang,
                    main_count: document.querySelectorAll("main").length,
                    h1_count: document.querySelectorAll("h1").length,
                    skip_link_count: document.querySelectorAll("a.skip-link").length,
                    unlabeled_controls: unlabeled,
                    consent_checked: Boolean(document.getElementById("memorial-contribution-consent")?.checked),
                    personal_memory_optin_present: Boolean(document.getElementById("memorial-personal-memory-optin")),
                    personal_memory_checked: Boolean(document.getElementById("memorial-personal-memory-optin")?.checked),
                    personal_memory_forget_present: Boolean(document.getElementById("memorial-personal-memory-forget")),
                    conversation_enabled: !Boolean(document.getElementById("memorial-conversation")?.disabled),
                    conversation_label: String(document.getElementById("memorial-conversation")?.textContent || "").trim(),
                    visible_button_ids: visibleButtons.map((element) => element.id || ""),
                    visible_button_labels: visibleButtons.map(
                      (element) => String(element.innerText || element.textContent || "").trim(),
                    ),
                    visible_non_button_control_ids: visibleNonButtonControls.map(
                      (element) => element.id || element.name || element.tagName,
                    ),
                    voice_release: String(document.getElementById("memorial-conversation-region")?.dataset.voiceRelease || ""),
                    voice_access: String(document.getElementById("memorial-conversation-region")?.dataset.voiceAccess || ""),
                    evaluation_status: String(document.getElementById("memorial-conversation-region")?.dataset.evaluationStatus || ""),
                    guidance: String(document.querySelector("#memorial-conversation-region .hero-guidance")?.textContent || "").trim(),
                    text_form_visible: visible(document.getElementById("memorial-text-turn-form")),
                    text_input_focused: document.activeElement === document.getElementById("memorial-text-turn-input"),
                    text_placeholder: String(document.getElementById("memorial-text-turn-input")?.getAttribute("placeholder") || ""),
                    retry_visible: visible(document.getElementById("memorial-retry-button")),
                    settings_visible: visible(document.querySelector("details.conversation-settings")),
                    answer_tools_visible: visible(document.getElementById("memorial-chat-tools")),
                    answer_status_visible: visible(document.getElementById("memorial-chat-status")),
                    voice_autostart_hidden: !visible(document.getElementById("memorial-autostart-optin")?.closest(".conversation-toggle")),
                    old_impersonation_copy_visible: document.body.innerText.includes("Was möchtest du Manfred fragen?") || document.body.innerText.includes("synthetischen Manfred-Stimme"),
                    reduced_motion: matchMedia("(prefers-reduced-motion: reduce)").matches,
                    horizontal_overflow: Math.max(0, document.documentElement.scrollWidth - innerWidth),
                    conversation_position: conversationPosition,
                    conversation_after_story: Boolean(
                      storyRect && conversationRect && conversationRect.top >= storyRect.bottom - 1
                    ),
                    conversation_overlap: Math.max(
                      0,
                      Math.round((storyRect?.bottom || 0) - (conversationRect?.top || 0)),
                    ),
                    conversation_region_present: Boolean(conversation),
                    story_present: Boolean(story),
                    unwanted_ids: unwantedIds,
                    public_nav_count: document.querySelectorAll("nav a").length,
                    forbidden_visible_semantics: forbiddenVisibleSemantics,
                    forbidden_attribute_semantics: forbiddenAttributeSemantics,
                    forbidden_pseudo_element_semantics: forbiddenPseudoElementSemantics,
                    forbidden_navigation_semantics: navigationViolations,
                    inline_event_handlers: inlineEventHandlers,
                    base_element_count: document.querySelectorAll("base").length,
                    meta_refresh_count: Array.from(document.querySelectorAll("meta[http-equiv]"))
                      .filter((element) => normalize(element.getAttribute("http-equiv")) === "refresh").length,
                  };
                }""",
                browser_semantic_policy,
            )
            if (
                not str(accessibility.get("lang") or "").lower().startswith("de")
                or accessibility.get("main_count") != 1
                or accessibility.get("h1_count") != 1
                or int(accessibility.get("skip_link_count") or 0) < 1
                or accessibility.get("unlabeled_controls")
                or accessibility.get("story_present") is True
                or accessibility.get("unwanted_ids")
                or accessibility.get("forbidden_visible_semantics")
                or accessibility.get("forbidden_attribute_semantics")
                or accessibility.get("forbidden_pseudo_element_semantics")
                or accessibility.get("forbidden_navigation_semantics")
                or accessibility.get("inline_event_handlers")
                or int(accessibility.get("base_element_count") or 0) != 0
                or int(accessibility.get("meta_refresh_count") or 0) != 0
                or accessibility.get("personal_memory_optin_present") is not True
                or accessibility.get("personal_memory_checked") is True
                or accessibility.get("personal_memory_forget_present") is not True
                or accessibility.get("conversation_enabled") is not True
                or accessibility.get("conversation_label")
                != CONVERSATION_ONLY_BLOCKED_ACTION_LABEL
                or accessibility.get("visible_button_ids")
                != ["memorial-conversation"]
                or accessibility.get("visible_button_labels")
                != [CONVERSATION_ONLY_BLOCKED_ACTION_LABEL]
                or accessibility.get("visible_non_button_control_ids")
                or accessibility.get("voice_release") != expected_voice_release
                or accessibility.get("voice_access") != expected_voice_access
                or accessibility.get("evaluation_status")
                != expected_evaluation_status
                or "ist nicht der echte Manfred" not in str(accessibility.get("guidance") or "")
                or "spricht nicht für ihn"
                not in str(accessibility.get("guidance") or "")
                or accessibility.get("text_form_visible") is not False
                or accessibility.get("text_input_focused") is not False
                or accessibility.get("retry_visible") is not False
                or accessibility.get("settings_visible") is not False
                or accessibility.get("answer_tools_visible") is not False
                or accessibility.get("answer_status_visible") is not False
                or accessibility.get("voice_autostart_hidden") is not True
                or accessibility.get("old_impersonation_copy_visible") is True
                or accessibility.get("reduced_motion") is not True
                or int(accessibility.get("horizontal_overflow") or 0) > 1
                or accessibility.get("conversation_position")
                in {"fixed", "sticky", "missing"}
                or accessibility.get("conversation_region_present") is not True
                or int(accessibility.get("public_nav_count") or 0) != 0
            ):
                raise RuntimeError("candidate_browser_accessibility_contract_failed")

            navigation = page.evaluate(
                """() => {
                  const entry = performance.getEntriesByType("navigation")[0];
                  return entry ? {
                    dom_content_loaded_ms: Math.round(entry.domContentLoadedEventEnd),
                    load_event_ms: Math.round(entry.loadEventEnd),
                    transfer_bytes: Number(entry.transferSize || 0),
                  } : {};
                }"""
            )
            dom_loaded_ms = int(navigation.get("dom_content_loaded_ms") or 0)
            load_event_ms = int(navigation.get("load_event_ms") or 0)
            if dom_loaded_ms <= 0 or dom_loaded_ms > 5000 or load_event_ms > 7000:
                raise RuntimeError("candidate_browser_performance_contract_failed")

            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(100)
            desktop_layout = page.evaluate(
                """() => {
                  const story = document.getElementById("memorial-story");
                  const conversation = document.getElementById("memorial-conversation-region");
                  const storyRect = story?.getBoundingClientRect();
                  const conversationRect = conversation?.getBoundingClientRect();
                  return {
                    overflow: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
                    conversation_position: conversation ? getComputedStyle(conversation).position : "missing",
                    conversation_after_story: Boolean(
                      storyRect && conversationRect && conversationRect.top >= storyRect.bottom - 1
                    ),
                    conversation_overlap: Math.max(
                      0,
                      Math.round((storyRect?.bottom || 0) - (conversationRect?.top || 0)),
                    ),
                    conversation_present: Boolean(conversation),
                    story_present: Boolean(story),
                  };
                }"""
            )
            desktop_overflow = int(desktop_layout.get("overflow") or 0)
            if (
                desktop_overflow > 1
                or desktop_layout.get("conversation_position")
                in {"fixed", "sticky", "missing"}
                or desktop_layout.get("conversation_present") is not True
                or desktop_layout.get("story_present") is True
            ):
                raise RuntimeError("candidate_browser_desktop_layout_contract_failed")
            context.close()
            browser.close()
            browser = None
    except PlaywrightError as exc:
        raise RuntimeError("candidate_browser_runtime_error") from exc
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                browser.close()
        if original_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = original_tmpdir
    return {
        "status": "pass",
        "mobile_viewport": "390x844",
        "desktop_viewport": "1440x900",
        "reduced_motion": True,
        "horizontal_overflow_px": 0,
        "conversation_in_document_flow": True,
        "conversation_overlap_px": 0,
        "memorial_surface": MEMORIAL_SURFACE,
        "spatial_scope": SPATIAL_SCOPE,
        "unlabeled_controls": 0,
        "visible_button_ids": accessibility["visible_button_ids"],
        "visible_button_labels": accessibility["visible_button_labels"],
        "visible_non_button_control_ids": accessibility[
            "visible_non_button_control_ids"
        ],
        "voice_release": accessibility["voice_release"],
        "voice_access": accessibility["voice_access"],
        "evaluation_status": accessibility["evaluation_status"],
        "source_revision": observed_source_revision,
        "text_form_visible": accessibility["text_form_visible"],
        "text_input_focused": accessibility["text_input_focused"],
        "separate_retry_visible": accessibility["retry_visible"],
        "conversation_action_exercised": exercise_conversation_action,
        "automatic_provider_requests": 0,
        "automatic_readiness_requests": 0,
        "automatic_microphone_requests": 0,
        "automatic_websockets": 0,
        "external_requests": 0,
        "failed_requests": 0,
        "page_errors": 0,
        "http_errors": 0,
        "dom_content_loaded_ms": dom_loaded_ms,
        "load_event_ms": load_event_ms,
        "transfer_bytes": int(navigation.get("transfer_bytes") or 0),
    }


def _atomic_private_json(path: Path, payload: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def _submit_contribution(base_url: str, receipt_path: Path) -> dict[str, object]:
    marker = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    status, body, _headers = _request(
        base_url,
        "/memorials/manfred/contributions",
        method="POST",
        payload={
            "title": f"Candidate restart proof {marker}",
            "body": "Synthetic candidate-only durability proof; never publish.",
            "source_label": "Automated isolated candidate check",
            "publication_consent": False,
        },
        expected={201},
    )
    response = _json_body(body, path="/memorials/manfred/contributions")
    contribution_id = str(response.get("contribution_id") or "").strip()
    manage_token = str(response.get("manage_token") or "").strip()
    if (
        not contribution_id
        or not manage_token
        or response.get("visibility") != "private"
    ):
        raise RuntimeError("candidate_contribution_receipt_invalid")
    _atomic_private_json(
        receipt_path,
        {
            "schema": CONTRIBUTION_RECEIPT_SCHEMA,
            "contribution_id": contribution_id,
            "manage_token": manage_token,
            "submitted_at": response.get("submitted_at"),
            "status": "pending_restart_withdrawal",
        },
    )
    return {
        "submitted": True,
        "withdrawn": False,
        "http_status": status,
        "private_by_default": True,
        "publication_consent": False,
    }


def _withdraw_contribution(base_url: str, receipt_path: Path) -> dict[str, object]:
    if not receipt_path.is_file() or os.path.islink(receipt_path):
        raise RuntimeError("candidate_contribution_receipt_missing")
    if (receipt_path.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("candidate_contribution_receipt_permissions_invalid")
    payload = _json_body(receipt_path.read_bytes(), path="contribution_receipt")
    if payload.get("schema") != CONTRIBUTION_RECEIPT_SCHEMA:
        raise RuntimeError("candidate_contribution_receipt_invalid")
    contribution_id = str(payload.get("contribution_id") or "").strip()
    manage_token = str(payload.get("manage_token") or "").strip()
    status, body, _headers = _request(
        base_url,
        f"/memorials/manfred/contributions/{contribution_id}/withdraw",
        method="POST",
        payload={"reason": "Candidate restart durability proof completed"},
        headers={"x-memorial-contribution-token": manage_token},
    )
    response = _json_body(body, path="contribution_withdraw")
    if (
        response.get("status") != "withdrawn"
        or response.get("public_removed") is not True
    ):
        raise RuntimeError("candidate_contribution_withdrawal_invalid")
    receipt_path.unlink()
    return {
        "submitted": True,
        "withdrawn": True,
        "http_status": status,
        "private_by_default": True,
        "survived_candidate_restart": True,
        "manage_token_retained": False,
    }


def _validated_voice_release_expectation(
    value: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    expectation = dict(value)
    source_revision = str(expectation.get("source_revision") or "")
    access_mode = str(
        expectation.get("access_mode")
        or (
            VOICE_ACCESS_MODE_PUBLIC_RELEASE
            if set(expectation) == LEGACY_VOICE_RELEASE_EXPECTATION_FIELDS
            else ""
        )
    )
    if (
        set(expectation)
        not in {
            LEGACY_VOICE_RELEASE_EXPECTATION_FIELDS,
            VOICE_RELEASE_EXPECTATION_FIELDS,
        }
        or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None
        or access_mode
        not in {
            VOICE_ACCESS_MODE_PUBLIC_RELEASE,
            VOICE_ACCESS_MODE_PUBLIC_EVALUATION,
        }
    ):
        raise ValueError("candidate_voice_release_expectation_invalid")
    return {
        "access_mode": access_mode,
        "source_revision": source_revision,
    }


def _voice_browser_expectation(
    voice_release_expectation: Mapping[str, object] | None,
) -> dict[str, str]:
    expectation = _validated_voice_release_expectation(
        voice_release_expectation
    )
    if expectation is None:
        return {
            "voice_release": "blocked",
            "voice_access": "text-only",
            "evaluation_status": "",
        }
    if expectation["access_mode"] == VOICE_ACCESS_MODE_PUBLIC_RELEASE:
        return {
            "voice_release": "available",
            "voice_access": "public-release",
            "evaluation_status": "",
        }
    return {
        "voice_release": "blocked",
        "voice_access": "public-evaluation",
        "evaluation_status": "owner-authorized",
    }


def _verify_voice_provider_boundary(
    base_url: str,
    *,
    voice_release_expectation: Mapping[str, object] | None,
    request_fn: Callable[..., tuple[int, bytes, dict[str, str]]] = _request,
) -> dict[str, object]:
    expectation = _validated_voice_release_expectation(voice_release_expectation)
    if expectation is None:
        _status, body, _headers = request_fn(
            base_url,
            "/memorials/manfred/speech-synthesize",
            method="POST",
            payload={"text": "Diese Sprachfunktion darf nicht starten."},
            expected={409},
        )
        blocked = _json_body(
            body,
            path="/memorials/manfred/speech-synthesize",
        )
        if str(blocked.get("detail") or "") != "memorial_voice_release_not_verified":
            raise RuntimeError("candidate_voice_release_boundary_invalid")
        return {
            "mode": "phase_one_voice_blocked",
            "status_code": 409,
            "detail": "memorial_voice_release_not_verified",
            "provider_calls_performed": False,
        }

    status, body, headers = request_fn(
        base_url,
        "/memorials/manfred/speech-synthesize",
        method="POST",
        payload={},
        expected={400},
    )
    released = _json_body(
        body,
        path="/memorials/manfred/speech-synthesize",
    )
    if (
        status != 400
        or str(released.get("detail") or "") != "tts_text_missing"
        or str(headers.get("x-ea-source-revision") or "")
        != expectation["source_revision"]
    ):
        raise RuntimeError("candidate_voice_release_authorization_boundary_invalid")
    mode = (
        "signed_voice_release_authorized"
        if expectation["access_mode"] == VOICE_ACCESS_MODE_PUBLIC_RELEASE
        else "public_evaluation_authorization_verified"
    )
    return {
        "mode": mode,
        "status_code": 400,
        "detail": "tts_text_missing",
        "authorization_proof": VOICE_RELEASE_AUTHORIZATION_PROOF,
        "provider_calls_performed": False,
        **expectation,
    }


def verify_candidate(
    *,
    base_url: str,
    public_origin: str,
    wait_seconds: int,
    submit_receipt: Path | None,
    withdraw_receipt: Path | None,
    browser_audit: bool = False,
    transport_request: Callable[..., tuple[int, bytes, dict[str, str]]] | None = None,
    voice_release_expectation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    voice_release_expectation = _validated_voice_release_expectation(
        voice_release_expectation
    )
    voice_browser_expectation = _voice_browser_expectation(
        voice_release_expectation
    )
    _wait_for_health(base_url, wait_seconds)
    checks: list[str] = ["healthz"]
    _request(base_url, "/health/live?probe=memorial")
    checks.append("memorial_health_probe")

    _status, body, headers = _request(base_url, "/memorials/manfred.json")
    manifest = _json_body(body, path="/memorials/manfred.json")
    if str(manifest.get("slug") or "") != "manfred":
        raise RuntimeError("candidate_memorial_slug_mismatch")
    encoded_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    forbidden_markers = (
        PRIVATE_CONTEXT_FILENAME,
        PRIVATE_AUDIO_RELPATH,
        "manage_token_hash",
        "memory_principal_id",
    )
    if any(marker in encoded_manifest for marker in forbidden_markers):
        raise RuntimeError("candidate_public_manifest_private_data_exposed")
    if headers.get("x-content-type-options", "").lower() != "nosniff":
        raise RuntimeError("candidate_public_headers_incomplete")
    checks.append("public_projection")

    _page_status, page_body, page_headers = _request(
        base_url,
        "/memorials/manfred",
        headers=_browser_proxy_headers(base_url, public_origin),
    )
    encoded_page = page_body.decode("utf-8", errors="replace")
    if any(marker in encoded_page for marker in forbidden_markers):
        raise RuntimeError("candidate_public_page_private_data_exposed")
    if page_headers.get("x-content-type-options", "").lower() != "nosniff":
        raise RuntimeError("candidate_public_headers_incomplete")
    conversation_surface = verify_conversation_only_page_html(page_body)
    if any(
        conversation_surface.get(name)
        != voice_browser_expectation[name]
        for name in (
            "voice_release",
            "voice_access",
            "evaluation_status",
        )
    ):
        raise RuntimeError("candidate_conversation_voice_access_mismatch")
    checks.append("conversation_only_public_surface")

    transport_security = _verify_memorial_transport_security(
        base_url,
        public_origin,
        request_fn=transport_request,
    )
    checks.append("memorial_transport_security")

    _verify_memorial_head_surface(
        base_url,
        public_origin,
        request_fn=transport_request,
    )
    _verify_singular_memorial_alias(
        base_url,
        public_origin,
        request_fn=transport_request,
    )
    archive_gate = _verify_memorial_archive_gate(base_url)
    _request(base_url, "/memorials/manfred/app.webmanifest")
    _request(base_url, "/memorials/manfred/service-worker.js")
    checks.extend(
        [
            "head_surface_no_prewarm",
            "singular_memorial_alias",
            "archive_publication_gate",
            "pwa",
        ]
    )

    _request(
        base_url,
        f"/memorials/files/manfred/{PRIVATE_AUDIO_RELPATH}",
        expected={404},
    )
    _request(
        base_url,
        "/memorial_data/public_memorials/manfred/memorial.json",
        expected={401, 403, 404},
    )
    checks.extend(["private_audio_denied", "raw_manifest_denied"])

    _status, narrator_body, _headers = _request(
        base_url,
        "/memorials/manfred/chat",
        method="POST",
        payload={"question": "Was war dir bei deiner Familie wichtig?"},
    )
    narrator = _json_body(narrator_body, path="/memorials/manfred/chat")
    _assert_first_person_reconstruction_contract(
        narrator,
        error="candidate_narrator_boundary_invalid",
    )
    checks.append("source_grounded_first_person_reconstruction_boundary")

    _status, identity_body, _headers = _request(
        base_url,
        "/memorials/manfred/chat",
        method="POST",
        payload={"question": "Bist du wirklich Manfred?"},
    )
    identity = _json_body(identity_body, path="/memorials/manfred/chat")
    identity_answer = _assert_first_person_reconstruction_contract(
        identity,
        error="candidate_identity_disclosure_invalid",
    )
    if (
        "ki-rekonstruktion" not in identity_answer
        or "nicht der echte manfred" not in identity_answer
    ):
        raise RuntimeError("candidate_identity_disclosure_invalid")
    checks.append("synthetic_identity_disclosure_boundary")

    voice_release_verification = _verify_voice_provider_boundary(
        base_url,
        voice_release_expectation=voice_release_expectation,
    )
    if voice_release_expectation is None:
        checks.append("voice_provider_boundary_blocked")
    elif (
        voice_release_expectation["access_mode"]
        == VOICE_ACCESS_MODE_PUBLIC_RELEASE
    ):
        checks.append(
            "voice_release_authorization_verified_provider_not_called"
        )
    else:
        checks.append(
            "voice_public_evaluation_authorization_verified_provider_not_called"
        )

    _status, share_body, _headers = _request(
        base_url,
        "/memorials/manfred/share-drafts",
        method="POST",
        payload={
            "public_origin": public_origin,
            "channels": ["telegram", "whatsapp"],
            "include_archive": True,
            "include_audio": False,
        },
    )
    share_packet = _json_body(share_body, path="share-drafts")
    serialized_share = json.dumps(share_packet, ensure_ascii=False, sort_keys=True)
    if PRIVATE_AUDIO_RELPATH in serialized_share or _contains_forbidden_recipient_field(
        share_packet
    ):
        raise RuntimeError("candidate_share_packet_private_data_exposed")
    checks.append("unsent_public_share_drafts")

    contribution = {
        "submitted": False,
        "withdrawn": False,
        "survived_candidate_restart": False,
    }
    if submit_receipt is not None and withdraw_receipt is not None:
        raise ValueError("candidate_contribution_mode_conflict")
    if submit_receipt is not None:
        contribution = _submit_contribution(base_url, submit_receipt)
        checks.append("private_contribution_submitted")
    elif withdraw_receipt is not None:
        contribution = _withdraw_contribution(base_url, withdraw_receipt)
        checks.append("private_contribution_withdrawn_after_restart")

    browser_evidence: dict[str, object] = {"status": "not_run"}
    if browser_audit:
        expected_voice_release = voice_browser_expectation["voice_release"]
        expected_voice_access = voice_browser_expectation["voice_access"]
        expected_evaluation_status = voice_browser_expectation[
            "evaluation_status"
        ]
        browser_evidence = audit_browser_surface(
            base_url,
            public_origin=public_origin,
            expected_voice_release=expected_voice_release,
            expected_voice_access=expected_voice_access,
            expected_evaluation_status=expected_evaluation_status,
            expected_source_revision=(
                str(voice_release_expectation["source_revision"])
                if voice_release_expectation is not None
                else None
            ),
            exercise_conversation_action=(
                voice_release_expectation is None
            ),
        )
        expected_action_exercised = voice_release_expectation is None
        if (
            browser_evidence.get("status") != "pass"
            or browser_evidence.get("voice_release") != expected_voice_release
            or browser_evidence.get("voice_access") != expected_voice_access
            or browser_evidence.get("evaluation_status")
            != expected_evaluation_status
            or browser_evidence.get("conversation_action_exercised")
            is not expected_action_exercised
            or (
                voice_release_expectation is not None
                and browser_evidence.get("source_revision")
                != voice_release_expectation["source_revision"]
            )
            or not _has_exact_zero_counts(browser_evidence)
        ):
            raise RuntimeError("candidate_browser_provider_boundary_invalid")
        checks.append("browser_provider_websocket_boundary")

    return {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "checked_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "base_url": base_url,
        "checks": checks,
        "conversation_only_public_surface": conversation_surface,
        "provider_calls_performed": False,
        "voice_release_verification": voice_release_verification,
        "page_get_performed": True,
        "operator_surface_used": False,
        "private_audio_served": False,
        "archive_gate": archive_gate,
        "transport_security": transport_security,
        "contribution": contribution,
        "browser_audit": browser_evidence,
        "memorial_surface": MEMORIAL_SURFACE,
        "spatial_scope": SPATIAL_SCOPE,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run provider-free HTTP checks against an isolated Manfred candidate."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18090")
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument(
        "--browser-audit",
        action="store_true",
        help="Exercise the rendered surface and fail on provider requests or WebSockets.",
    )
    parser.add_argument(
        "--expect-signed-voice-release",
        action="store_true",
        help=(
            "Expect the runtime's already signed, source/image/voice-bound "
            "normal release or owner-authorized public-evaluation "
            "authorization. The proof uses an empty-text request and must "
            "stop before provider work."
        ),
    )
    parser.add_argument(
        "--voice-access-mode",
        choices=(
            VOICE_ACCESS_MODE_PUBLIC_RELEASE,
            VOICE_ACCESS_MODE_PUBLIC_EVALUATION,
        ),
        default="",
        help=(
            "Signed authorization mode; defaults to public-release for "
            "backward-compatible normal release verification."
        ),
    )
    parser.add_argument("--expected-source-revision", default="")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--submit-contribution-receipt", default="")
    modes.add_argument("--withdraw-contribution-receipt", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    expected_source_revision = str(args.expected_source_revision or "")
    if not args.expect_signed_voice_release and (
        expected_source_revision or args.voice_access_mode
    ):
        raise SystemExit(
            "release binding arguments require --expect-signed-voice-release"
        )
    if args.expect_signed_voice_release and not args.browser_audit:
        raise SystemExit(
            "--expect-signed-voice-release requires --browser-audit"
        )
    voice_release_expectation = (
        {
            "access_mode": (
                str(args.voice_access_mode)
                or VOICE_ACCESS_MODE_PUBLIC_RELEASE
            ),
            "source_revision": expected_source_revision,
        }
        if args.expect_signed_voice_release
        else None
    )
    try:
        receipt = verify_candidate(
            base_url=str(args.base_url).rstrip("/"),
            public_origin=str(args.public_origin).rstrip("/"),
            wait_seconds=max(1, min(600, int(args.wait_seconds))),
            submit_receipt=Path(args.submit_contribution_receipt)
            if args.submit_contribution_receipt
            else None,
            withdraw_receipt=Path(args.withdraw_contribution_receipt)
            if args.withdraw_contribution_receipt
            else None,
            browser_audit=bool(args.browser_audit),
            voice_release_expectation=voice_release_expectation,
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {"schema": RECEIPT_SCHEMA, "status": "fail", "error": str(exc)[:200]},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
