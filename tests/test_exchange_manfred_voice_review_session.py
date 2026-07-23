from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest

from scripts import exchange_manfred_voice_review_session as exchange
from scripts import manfred_voice_review_client_auth as review_auth


ORIGIN = "https://myexternalbrain.com"
REVISION = "a" * 40
IMAGE_ID = f"sha256:{'b' * 64}"
VOICE_IDENTITY = "c" * 64


def _session_token() -> str:
    now = int(time.time())
    claims = {
        "contract_name": review_auth.REVIEW_CONTRACT,
        "purpose": review_auth.REVIEW_PURPOSE,
        "kind": "session",
        "slug": review_auth.REVIEW_SLUG,
        "jti": "d" * 48,
        "source_revision": REVISION,
        "public_origin": ORIGIN,
        "image_id": IMAGE_ID,
        "voice_identity_sha256": VOICE_IDENTITY,
        "issued_at": now,
        "accepted_at": now,
        "expires_at": now + 1200,
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


class _Headers:
    def __init__(self, set_cookie: str) -> None:
        self._set_cookie = set_cookie

    def get_all(self, name: str) -> list[str]:
        return [self._set_cookie] if name.lower() == "set-cookie" else []


class _Response:
    def __init__(self, *, set_cookie: str) -> None:
        self.headers = _Headers(set_cookie)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return f"{ORIGIN}{exchange.EXCHANGE_PATH}"

    def read(self, _size: int) -> bytes:
        return json.dumps(
            {
                "status": "accepted",
                "redirect": "/memorials/manfred",
            }
        ).encode("utf-8")


def _install_exchange_response(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_token: str,
    attributes: str = (
        "Path=/memorials/manfred; Secure; HttpOnly; "
        "SameSite=Strict; Max-Age=1200"
    ),
) -> list[object]:
    requests: list[object] = []

    class _Opener:
        def open(self, request: object, *, timeout: float) -> _Response:
            assert timeout == 20.0
            requests.append(request)
            return _Response(
                set_cookie=(
                    f"{review_auth.REVIEW_COOKIE_NAME}={session_token}; "
                    f"{attributes}"
                )
            )

    monkeypatch.setattr(
        exchange,
        "build_opener",
        lambda _handler: _Opener(),
    )
    return requests


def test_exchange_writes_only_private_session_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_token = _session_token()
    requests = _install_exchange_response(
        monkeypatch,
        session_token=session_token,
    )
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "review-session"
    bootstrap = "bootstrap-value"

    result = exchange.exchange_review_url(
        f"{ORIGIN}{exchange.EXCHANGE_PATH}#token={bootstrap}",
        output=output,
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == f"{ORIGIN}{exchange.EXCHANGE_PATH}"
    assert "#" not in request.full_url
    assert request.get_header("Origin") == ORIGIN
    assert json.loads(request.data.decode("ascii")) == {"token": bootstrap}
    assert output.read_text(encoding="ascii") == f"{session_token}\n"
    assert output.stat().st_mode & 0o777 == 0o600
    rendered = json.dumps(result, sort_keys=True)
    assert session_token not in rendered
    assert bootstrap not in rendered
    assert result["bearer_material_exposed"] is False


@pytest.mark.parametrize(
    "review_url",
    [
        "https://attacker.example/admin/memorials/manfred/voice-review#token=x",
        f"{ORIGIN}/wrong#token=x",
        f"{ORIGIN}{exchange.EXCHANGE_PATH}?token=x#token=y",
        f"{ORIGIN}{exchange.EXCHANGE_PATH}#other=x",
    ],
)
def test_exchange_rejects_unbound_bootstrap_url(
    review_url: str,
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "review-session"

    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_bootstrap_input_invalid",
    ):
        exchange.exchange_review_url(review_url, output=output)

    assert not output.exists()


def test_exchange_rejects_insecure_cookie_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_exchange_response(
        monkeypatch,
        session_token=_session_token(),
        attributes=(
            "Path=/memorials/manfred; HttpOnly; "
            "SameSite=Strict; Max-Age=1200"
        ),
    )
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "review-session"

    with pytest.raises(
        review_auth.ReviewSessionError,
        match="review_session_exchange_cookie_invalid",
    ):
        exchange.exchange_review_url(
            f"{ORIGIN}{exchange.EXCHANGE_PATH}#token=bootstrap",
            output=output,
        )

    assert not output.exists()
