#!/usr/bin/env python3
"""Exchange a fragment-only review URL for a private session-cookie file."""

from __future__ import annotations

import argparse
import json
import sys
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from scripts.manfred_voice_review_client_auth import (
        REVIEW_ALLOWED_PUBLIC_ORIGINS,
        REVIEW_COOKIE_NAME,
        REVIEW_SLUG,
        ReviewSessionError,
        normalized_https_origin,
        parse_review_session_token,
        write_private_review_session_token,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from manfred_voice_review_client_auth import (  # type: ignore[no-redef]
        REVIEW_ALLOWED_PUBLIC_ORIGINS,
        REVIEW_COOKIE_NAME,
        REVIEW_SLUG,
        ReviewSessionError,
        normalized_https_origin,
        parse_review_session_token,
        write_private_review_session_token,
    )


MAX_REVIEW_URL_BYTES = 8192
EXCHANGE_PATH = "/admin/memorials/manfred/voice-review"
REVIEW_EXCHANGE_USER_AGENT = "EA-Memorial-Review-Client/1.0"


def _origin_from_url(value: object) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError as exc:
        raise ReviewSessionError("review_session_origin_invalid") from exc
    return normalized_https_origin(
        urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                "/",
                "",
                "",
            )
        )
    )


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, expected_origin: str) -> None:
        super().__init__()
        self._expected_origin = expected_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirect_url = urljoin(req.full_url, str(newurl or ""))
        if _origin_from_url(redirect_url) != self._expected_origin:
            raise URLError("review_session_cross_origin_redirect")
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            redirect_url,
        )


def _read_review_url_from_stdin() -> str:
    raw = sys.stdin.buffer.read(MAX_REVIEW_URL_BYTES + 1)
    if not raw or len(raw) > MAX_REVIEW_URL_BYTES:
        raise ReviewSessionError("review_session_bootstrap_input_invalid")
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ReviewSessionError("review_session_bootstrap_input_invalid") from exc
    if "\n" in value or "\r" in value:
        raise ReviewSessionError("review_session_bootstrap_input_invalid")
    return value


def _bootstrap_from_review_url(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        origin = _origin_from_url(value)
        fragment = parse_qs(
            parsed.fragment,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except (ValueError, ReviewSessionError) as exc:
        raise ReviewSessionError("review_session_bootstrap_input_invalid") from exc
    tokens = fragment.get("token")
    if (
        origin not in REVIEW_ALLOWED_PUBLIC_ORIGINS
        or parsed.path != EXCHANGE_PATH
        or parsed.query
        or set(fragment) != {"token"}
        or not isinstance(tokens, list)
        or len(tokens) != 1
        or not tokens[0]
    ):
        raise ReviewSessionError("review_session_bootstrap_input_invalid")
    return origin, str(tokens[0])


def exchange_review_url(
    review_url: str,
    *,
    output: Path,
) -> dict[str, object]:
    origin, bootstrap_token = _bootstrap_from_review_url(review_url)
    endpoint = f"{origin}{EXCHANGE_PATH}"
    body = json.dumps(
        {"token": bootstrap_token},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": origin,
            "User-Agent": REVIEW_EXCHANGE_USER_AGENT,
        },
    )
    try:
        opener = build_opener(_SameOriginRedirectHandler(origin))
        with opener.open(request, timeout=20.0) as response:
            if _origin_from_url(str(response.geturl() or "")) != origin:
                raise ReviewSessionError("review_session_exchange_origin_changed")
            response_body = response.read(4097)
            if len(response_body) > 4096:
                raise ReviewSessionError("review_session_exchange_response_invalid")
            payload = json.loads(response_body.decode("utf-8"))
            set_cookie_headers = response.headers.get_all("Set-Cookie") or []
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise ReviewSessionError("review_session_exchange_failed") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewSessionError("review_session_exchange_response_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "accepted"
        or payload.get("redirect") != f"/memorials/{REVIEW_SLUG}"
    ):
        raise ReviewSessionError("review_session_exchange_response_invalid")
    selected = None
    for header in set_cookie_headers:
        parsed_cookie = SimpleCookie()
        try:
            parsed_cookie.load(header)
        except Exception:
            continue
        if REVIEW_COOKIE_NAME in parsed_cookie:
            selected = parsed_cookie[REVIEW_COOKIE_NAME]
            break
    if selected is None:
        raise ReviewSessionError("review_session_exchange_cookie_missing")
    token = str(selected.value or "")
    try:
        max_age = int(str(selected["max-age"] or "0"))
    except ValueError as exc:
        raise ReviewSessionError("review_session_exchange_cookie_invalid") from exc
    if (
        selected["path"] != f"/memorials/{REVIEW_SLUG}"
        or not selected["secure"]
        or not selected["httponly"]
        or str(selected["samesite"] or "").lower() != "strict"
        or max_age < 180
        or max_age > 1800
    ):
        raise ReviewSessionError("review_session_exchange_cookie_invalid")
    auth = parse_review_session_token(
        token,
        public_origin=origin,
        slug=REVIEW_SLUG,
    )
    write_private_review_session_token(output, token)
    return {
        "status": "pass",
        "output": str(output),
        "public_origin": origin,
        "slug": REVIEW_SLUG,
        "source_revision": auth.source_revision,
        "image_id": auth.image_id,
        "voice_identity_sha256": auth.voice_identity_sha256,
        "bearer_material_exposed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read a fragment-only Manfred review URL from stdin, exchange it "
            "same-origin, and write only the HttpOnly session value to a new "
            "0600 file."
        )
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = exchange_review_url(
            _read_review_url_from_stdin(),
            output=Path(args.output),
        )
    except ReviewSessionError as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
