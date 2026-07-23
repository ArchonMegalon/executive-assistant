from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from scripts import manfred_voice_review_client_auth as review_auth


NOW = 1_800_000_000
REVISION = "a" * 40
IMAGE_ID = f"sha256:{'b' * 64}"
VOICE_IDENTITY = "c" * 64
ORIGIN = "https://myexternalbrain.com"
NOW_NS = NOW * 1_000_000_000


def _token(*, origin: str = ORIGIN, expires_at: int = NOW + 1800) -> str:
    claims = {
        "contract_name": review_auth.REVIEW_CONTRACT,
        "purpose": review_auth.REVIEW_PURPOSE,
        "kind": "session",
        "slug": review_auth.REVIEW_SLUG,
        "jti": "d" * 48,
        "source_revision": REVISION,
        "public_origin": origin,
        "image_id": IMAGE_ID,
        "voice_identity_sha256": VOICE_IDENTITY,
        "issued_at": NOW,
        "accepted_at": NOW,
        "expires_at": expires_at,
        "scopes": sorted(review_auth.REVIEW_REQUIRED_SCOPES),
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(
            claims,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = base64.urlsafe_b64encode(b"s" * 32).decode("ascii").rstrip("=")
    return f"{payload}.{signature}"


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_auth.time, "time", lambda: NOW)
    monkeypatch.setattr(review_auth.time, "time_ns", lambda: NOW_NS)


def _private_bytes(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    path.write_bytes(payload)
    path.chmod(0o600)
    os.utime(path, ns=(NOW_NS, NOW_NS))
    return path


def _private_file(path: Path, token: str | None = None) -> Path:
    return _private_bytes(path, ((token or _token()) + "\n").encode("ascii"))


def test_private_review_session_loads_without_bearer_disclosure(
    tmp_path: Path,
) -> None:
    token = _token()
    path = _private_file(tmp_path / "private" / "session")

    auth = review_auth.load_review_session_auth(
        path,
        public_origin=ORIGIN,
        slug="manfred",
        expected_source_revision=REVISION,
    )

    assert auth.request_headers() == {
        "Cookie": f"{review_auth.REVIEW_COOKIE_NAME}={token}",
        "Origin": ORIGIN,
    }
    assert auth.playwright_cookie()["domain"] == "myexternalbrain.com"
    assert auth.playwright_cookie()["path"] == "/memorials/manfred"
    assert token not in repr(auth)
    assert token not in json.dumps(auth.public_binding(), sort_keys=True)
    assert auth.public_binding()["bearer_material_exposed"] is False


def test_private_review_playwright_cookie_is_host_only_and_slug_scoped() -> None:
    auth = review_auth.parse_review_session_token(
        _token(),
        public_origin=ORIGIN,
        slug="manfred",
        expected_source_revision=REVISION,
        now=NOW,
    )

    cookie = auth.playwright_cookie()

    assert cookie == {
        "name": review_auth.REVIEW_COOKIE_NAME,
        "value": _token(),
        "domain": "myexternalbrain.com",
        "path": "/memorials/manfred",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Strict",
    }
    assert not str(cookie["domain"]).startswith(".")
    assert "url" not in cookie


@pytest.mark.parametrize(
    "mutation",
    ["mode", "hardlink", "symlink", "symlink_parent"],
)
def test_private_review_session_rejects_unsafe_files(
    tmp_path: Path,
    mutation: str,
) -> None:
    real = _private_file(tmp_path / "private" / "session")
    target = real
    if mutation == "mode":
        real.chmod(0o640)
    elif mutation == "hardlink":
        os.link(real, real.parent / "other")
    elif mutation == "symlink":
        link = real.parent / "link"
        link.symlink_to(real)
        target = link
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(real.parent, target_is_directory=True)
        target = alias / real.name

    with pytest.raises(review_auth.ReviewSessionError):
        review_auth.load_review_session_auth(
            target,
            public_origin=ORIGIN,
            slug="manfred",
            expected_source_revision=REVISION,
        )


@pytest.mark.parametrize(
    ("mtime_offset_seconds", "allowed"),
    [
        (0, True),
        (-review_auth.MAX_COOKIE_FILE_AGE_SECONDS, True),
        (-review_auth.MAX_COOKIE_FILE_AGE_SECONDS - 1, False),
        (review_auth.MAX_COOKIE_FILE_FUTURE_SKEW_SECONDS, True),
        (review_auth.MAX_COOKIE_FILE_FUTURE_SKEW_SECONDS + 1, False),
    ],
)
def test_private_review_session_enforces_file_timestamp_bounds(
    tmp_path: Path,
    mtime_offset_seconds: int,
    allowed: bool,
) -> None:
    path = _private_file(tmp_path / "private" / "session")
    mtime_ns = (NOW + mtime_offset_seconds) * 1_000_000_000
    os.utime(path, ns=(mtime_ns, mtime_ns))

    if allowed:
        auth = review_auth.load_review_session_auth(
            path,
            public_origin=ORIGIN,
            slug="manfred",
            expected_source_revision=REVISION,
        )
        assert auth.source_revision == REVISION
    else:
        with pytest.raises(
            review_auth.ReviewSessionError,
            match="review_session_cookie_file_stale",
        ):
            review_auth.load_review_session_auth(
                path,
                public_origin=ORIGIN,
                slug="manfred",
                expected_source_revision=REVISION,
            )


def test_private_review_session_rejects_oversize_file(
    tmp_path: Path,
) -> None:
    payload = b"a" * (review_auth.MAX_TOKEN_BYTES + 2)
    path = _private_bytes(tmp_path / "private" / "session", payload)

    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_cookie_file_unsafe",
    ):
        review_auth.load_review_session_auth(
            path,
            public_origin=ORIGIN,
            slug="manfred",
            expected_source_revision=REVISION,
        )


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (b"not-a-token\n", "review_session_cookie_token_invalid"),
        (b"ab.cd\n", "review_session_cookie_token_invalid"),
        (b"\xff\n", "review_session_cookie_token_invalid"),
        (
            (
                base64.urlsafe_b64encode(b"not json").rstrip(b"=")
                + b"."
                + base64.urlsafe_b64encode(b"signature").rstrip(b"=")
                + b"\n"
            ),
            "review_session_cookie_claims_invalid",
        ),
        (
            (_token() + "\n\n").encode("ascii"),
            "review_session_cookie_token_invalid",
        ),
    ],
)
def test_private_review_session_rejects_malformed_file_content(
    tmp_path: Path,
    payload: bytes,
    error_code: str,
) -> None:
    path = _private_bytes(tmp_path / "private" / "session", payload)

    with pytest.raises(review_auth.ReviewSessionError, match=error_code) as exc:
        review_auth.load_review_session_auth(
            path,
            public_origin=ORIGIN,
            slug="manfred",
            expected_source_revision=REVISION,
        )

    printable_payload = payload.decode("ascii", errors="ignore").strip()
    if printable_payload:
        assert printable_payload not in str(exc.value)


def test_private_review_session_is_pinned_to_production_origin() -> None:
    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_cookie_binding_invalid",
    ):
        review_auth.parse_review_session_token(
            _token(origin="https://attacker.example"),
            public_origin="https://attacker.example",
            slug="manfred",
            expected_source_revision=REVISION,
            now=NOW,
        )


def test_private_review_session_requires_safe_remaining_lifetime() -> None:
    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_cookie_binding_invalid",
    ):
        review_auth.parse_review_session_token(
            _token(expires_at=NOW + 179),
            public_origin=ORIGIN,
            slug="manfred",
            expected_source_revision=REVISION,
            now=NOW,
        )


def test_private_review_session_rejects_overlong_lifetime() -> None:
    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_cookie_binding_invalid",
    ):
        review_auth.parse_review_session_token(
            _token(
                expires_at=(
                    NOW
                    + review_auth.MAX_REMAINING_LIFETIME_SECONDS
                    + 1
                )
            ),
            public_origin=ORIGIN,
            slug="manfred",
            expected_source_revision=REVISION,
            now=NOW,
        )


def test_private_token_writer_is_owner_only_and_non_overwriting(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "session"

    review_auth.write_private_review_session_token(output, _token())

    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_cookie_output_exists",
    ):
        review_auth.write_private_review_session_token(output, _token())


def test_private_token_writer_rejects_malformed_value_before_creation(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "session"

    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_cookie_token_invalid",
    ):
        review_auth.write_private_review_session_token(output, "not-a-token")

    assert not output.exists()


def test_private_review_receipt_writer_is_atomic_owner_only_and_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "evidence.json"
    fsynced_modes: list[int] = []
    real_fsync = os.fsync

    def record_fsync(descriptor: int) -> None:
        fsynced_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(review_auth.os, "fsync", record_fsync)
    review_auth.write_private_review_receipt_text(
        output,
        '{"status":"pass","bearer_material_exposed":false}',
    )

    assert output.read_text(encoding="utf-8").endswith("\n")
    assert output.stat().st_mode & 0o777 == 0o600
    assert any(mode & 0o170000 == 0o100000 for mode in fsynced_modes)
    assert any(mode & 0o170000 == 0o040000 for mode in fsynced_modes)
    assert [path.name for path in private.iterdir()] == ["evidence.json"]


def test_private_review_receipt_writer_replaces_symlink_not_target(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    victim = tmp_path / "victim.json"
    victim.write_text("preserve\n", encoding="utf-8")
    output = private / "evidence.json"
    output.symlink_to(victim)

    review_auth.write_private_review_receipt_text(
        output,
        '{"status":"pass"}',
    )

    assert victim.read_text(encoding="utf-8") == "preserve\n"
    assert output.is_file()
    assert not output.is_symlink()
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("case", ["relative", "unsafe-parent"])
def test_private_review_receipt_writer_rejects_unsafe_output_path(
    tmp_path: Path,
    case: str,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = Path("relative.json") if case == "relative" else private / "receipt.json"
    if case == "unsafe-parent":
        private.chmod(0o755)

    with pytest.raises(review_auth.ReviewSessionError):
        review_auth.write_private_review_receipt_text(
            output,
            '{"status":"pass"}',
        )


@pytest.mark.parametrize(
    "redirect_url",
    [
        "https://attacker.example/collect",
        "http://myexternalbrain.com/memorials/manfred",
        "//attacker.example/collect",
        "https://myexternalbrain.com:444/memorials/manfred",
        "https://myexternalbrain.com./memorials/manfred",
        "https://myexternalbrain.com@attacker.example/collect",
    ],
)
def test_review_request_rejects_cross_origin_redirect_without_bearer_leak(
    monkeypatch: pytest.MonkeyPatch,
    redirect_url: str,
) -> None:
    token = _token()

    class RedirectingOpener:
        def __init__(self, handler: object) -> None:
            self.handler = handler

        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            assert timeout == 3.0
            return self.handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                redirect_url,
            )

    def fake_build_opener(handler):  # type: ignore[no-untyped-def]
        return RedirectingOpener(handler)

    monkeypatch.setattr(review_auth, "build_opener", fake_build_opener)
    request = review_auth.Request(
        f"{ORIGIN}/memorials/manfred/voice?mode=review",
        headers={
            "Cookie": f"{review_auth.REVIEW_COOKIE_NAME}={token}",
            "Origin": ORIGIN,
        },
    )

    with pytest.raises(review_auth.URLError) as exc:
        review_auth.open_review_request(
            request,
            expected_origin=ORIGIN,
            timeout=3.0,
        )

    assert "review_session_cross_origin_redirect" in str(exc.value)
    assert token not in str(exc.value)


def test_review_request_allows_same_origin_endpoint_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _token()
    redirected_requests: list[object] = []

    class Response:
        def __init__(self, url: str) -> None:
            self.url = url
            self.closed = False

        def geturl(self) -> str:
            return self.url

        def close(self) -> None:
            self.closed = True

    class RedirectingOpener:
        def __init__(self, handler: object) -> None:
            self.handler = handler

        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            assert timeout == 2.0
            assert request.get_header("User-agent") == (
                review_auth.REVIEW_HTTP_USER_AGENT
            )
            redirected = self.handler.redirect_request(
                request,
                None,
                307,
                "Temporary Redirect",
                {},
                "/memorials/manfred/voice?mode=review",
            )
            redirected_requests.append(redirected)
            return Response(redirected.full_url)

    def fake_build_opener(handler):  # type: ignore[no-untyped-def]
        return RedirectingOpener(handler)

    monkeypatch.setattr(review_auth, "build_opener", fake_build_opener)
    request = review_auth.Request(
        f"{ORIGIN}/memorials/manfred?review=1",
        headers={
            "Cookie": f"{review_auth.REVIEW_COOKIE_NAME}={token}",
            "Origin": ORIGIN,
            "User-Agent": "blocked-client",
        },
    )

    response = review_auth.open_review_request(
        request,
        expected_origin=ORIGIN,
        timeout=2.0,
    )

    assert response.geturl() == (
        f"{ORIGIN}/memorials/manfred/voice?mode=review"
    )
    assert len(redirected_requests) == 1
    assert redirected_requests[0].get_header("Cookie") == (
        f"{review_auth.REVIEW_COOKIE_NAME}={token}"
    )
    assert redirected_requests[0].get_header("User-agent") == (
        review_auth.REVIEW_HTTP_USER_AGENT
    )
    response.close()
    assert response.closed is True


def test_review_request_closes_cross_origin_final_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _token()

    class Response:
        closed = False

        def geturl(self) -> str:
            return "https://attacker.example/collect"

        def close(self) -> None:
            self.closed = True

    response = Response()

    class Opener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            del request, timeout
            return response

    monkeypatch.setattr(
        review_auth,
        "build_opener",
        lambda _handler: Opener(),
    )
    request = review_auth.Request(
        f"{ORIGIN}/memorials/manfred/voice?mode=review",
        headers={
            "Cookie": f"{review_auth.REVIEW_COOKIE_NAME}={token}",
            "Origin": ORIGIN,
        },
    )

    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_response_origin_invalid",
    ) as exc:
        review_auth.open_review_request(
            request,
            expected_origin=ORIGIN,
            timeout=2.0,
        )

    assert response.closed is True
    assert token not in str(exc.value)
