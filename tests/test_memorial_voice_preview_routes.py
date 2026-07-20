from __future__ import annotations

import json
import time
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.memorial_voice_preview_authority import (
    MemorialVoicePreviewReleaseContext,
)


PUBLIC_ORIGIN = "https://myexternalbrain.com"
SOURCE_REVISION = "c" * 40
DEPLOYMENT_ID = f"ea-manfred-prod-{SOURCE_REVISION[:12]}"
WRITE_TOKEN = "manfred-operator-write-token-20260720"
ROTATED_WRITE_TOKEN = "manfred-operator-write-token-rotated-20260720"
SIGNING_SECRET = "preview-route-test-signing-secret-20260720"


def _write_public_memorial(
    root: Path,
    *,
    write_token: str = WRITE_TOKEN,
) -> None:
    bundle = root / "manfred"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "person_name": "Manfred Hoza",
                "title": "Erinnerungen an Manfred",
                "write_token": write_token,
                "audio_clips": [],
                "memory_cards": [],
                "suggested_prompts": ["Worüber möchtest du sprechen?"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_private_voice(root: Path) -> None:
    profile = root / "manfred"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "tts_voice.json").write_text(
        json.dumps(
            {
                "tts_plugin": "unmixr_voice_clone",
                "tts_plugin_voice_id": "manfred-preview-test",
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "authorized_by": "preview-route-test",
                    "authorized_at": "2026-07-20T12:00:00Z",
                    "source_assets_reviewed": True,
                    "revoked": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def preview_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[TestClient, Path]:
    from app.api.routes import public_memorials
    from app.api.app import create_app

    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    _write_public_memorial(public_root)
    _write_private_voice(private_root)

    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    monkeypatch.setenv("EA_MEMORIAL_VOICE_PREVIEW_ENABLED", "1")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", PUBLIC_ORIGIN)
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    monkeypatch.delenv("EA_PUBLIC_MEMORIAL_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(
        public_memorials,
        "_PUBLIC_MEMORIAL_RATE_DB",
        tmp_path / "memorial-rate.sqlite3",
    )
    monkeypatch.setattr(
        public_memorials,
        "_PUBLIC_MEMORIAL_RATE_BACKEND_CACHE",
        None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda slug: {
            "allowed": False,
            "status": "blocked",
            "reason": "memorial_voice_release_not_verified",
            "receipt_status": "blocked",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_preview_release_context",
        lambda: MemorialVoicePreviewReleaseContext(
            source_revision=SOURCE_REVISION,
            deployment_id=DEPLOYMENT_ID,
            public_origin=PUBLIC_ORIGIN,
        ),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_preview_signing_secret",
        lambda: SIGNING_SECRET,
    )
    client = TestClient(create_app(), base_url=PUBLIC_ORIGIN)
    return client, public_root


def _issue_preview(client: TestClient) -> tuple[str, object]:
    response = client.post(
        "/memorials/manfred/voice-preview/session",
        headers={
            "origin": PUBLIC_ORIGIN,
            "x-memorial-write-token": WRITE_TOKEN,
        },
    )
    assert response.status_code == 200, response.text
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    value = cookie["ea_manfred_voice_preview"].value
    assert value
    return value, response


def test_preview_session_is_disabled_by_default_and_manually_flagged(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = preview_runtime
    monkeypatch.delenv("EA_MEMORIAL_VOICE_PREVIEW_ENABLED", raising=False)

    response = client.post(
        "/memorials/manfred/voice-preview/session",
        headers={
            "origin": PUBLIC_ORIGIN,
            "x-memorial-write-token": WRITE_TOKEN,
        },
    )

    assert response.status_code == 404
    assert "set-cookie" not in response.headers


def test_preview_session_is_production_only_and_never_masks_a_public_release(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    client, _ = preview_runtime
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: False,
    )
    development = client.post(
        "/memorials/manfred/voice-preview/session",
        headers={
            "origin": PUBLIC_ORIGIN,
            "x-memorial-write-token": WRITE_TOKEN,
        },
    )
    assert development.status_code == 404
    assert "set-cookie" not in development.headers

    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda slug: {"allowed": True, "status": "pass", "reason": ""},
    )
    released = client.post(
        "/memorials/manfred/voice-preview/session",
        headers={
            "origin": PUBLIC_ORIGIN,
            "x-memorial-write-token": WRITE_TOKEN,
        },
    )

    assert released.status_code == 409
    assert released.json()["detail"] == "memorial_voice_preview_not_required"
    assert "set-cookie" not in released.headers


def test_public_release_voice_access_never_depends_on_preview_authority(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    client, _ = preview_runtime
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda slug: {"allowed": True, "status": "pass", "reason": ""},
    )

    def preview_authority_must_not_be_loaded():
        raise AssertionError("public release coupled to preview authority")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_preview_release_context",
        preview_authority_must_not_be_loaded,
    )
    monkeypatch.setattr(public_memorials, "_gemini_live_available", lambda: True)

    accepted = client.post(
        "/memorials/manfred/realtime/webrtc",
        headers={"origin": PUBLIC_ORIGIN},
    )
    page = client.get("/memorials/manfred")

    assert accepted.status_code == 410
    assert accepted.json()["detail"] == "gemini_live_uses_websocket_pcm"
    assert page.status_code == 200
    assert 'data-voice-access="public-release"' in page.text
    assert 'data-operator-voice-preview="allowed"' not in page.text


def test_preview_session_uses_only_a_short_lived_hardened_cookie(
    preview_runtime: tuple[TestClient, Path],
) -> None:
    client, _ = preview_runtime

    token, response = _issue_preview(client)
    payload = response.json()
    rendered_payload = json.dumps(payload, sort_keys=True)
    set_cookie = response.headers["set-cookie"]

    assert payload == {
        "status": "operator_preview",
        "memorial_slug": "manfred",
        "expires_at": payload["expires_at"],
        "public_release_allowed": False,
    }
    assert token not in rendered_payload
    assert "token" not in payload
    assert "cookie" not in payload
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=Strict" in set_cookie
    assert "Path=/memorials/manfred" in set_cookie
    assert "Max-Age=600" in set_cookie
    assert "Domain=" not in set_cookie
    assert response.headers["cache-control"] == "no-store"
    assert 60 <= int(payload["expires_at"]) - int(time.time()) <= 600


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({"origin": PUBLIC_ORIGIN}, 403),
        (
            {
                "origin": PUBLIC_ORIGIN,
                "x-memorial-write-token": "wrong-operator-write-token-20260720",
            },
            403,
        ),
        (
            {
                "origin": "https://propertyquarry.com",
                "x-memorial-write-token": WRITE_TOKEN,
            },
            403,
        ),
        (
            {
                "host": "propertyquarry.com",
                "origin": PUBLIC_ORIGIN,
                "x-memorial-write-token": WRITE_TOKEN,
            },
            404,
        ),
    ],
)
def test_preview_session_requires_exact_origin_host_and_current_operator_token(
    preview_runtime: tuple[TestClient, Path],
    headers: dict[str, str],
    expected_status: int,
) -> None:
    client, _ = preview_runtime

    response = client.post(
        "/memorials/manfred/voice-preview/session",
        headers=headers,
    )

    assert response.status_code == expected_status
    assert "set-cookie" not in response.headers


def test_preview_session_rejects_multiple_operator_credentials(
    preview_runtime: tuple[TestClient, Path],
) -> None:
    client, _ = preview_runtime

    response = client.post(
        "/memorials/manfred/voice-preview/session",
        headers=[
            ("origin", PUBLIC_ORIGIN),
            ("x-memorial-write-token", WRITE_TOKEN),
            ("x-memorial-admin-token", WRITE_TOKEN),
        ],
    )

    assert response.status_code == 403
    assert "set-cookie" not in response.headers

    duplicate_origin = client.post(
        "/memorials/manfred/voice-preview/session",
        headers=[
            ("origin", PUBLIC_ORIGIN),
            ("origin", PUBLIC_ORIGIN),
            ("x-memorial-write-token", WRITE_TOKEN),
        ],
    )
    assert duplicate_origin.status_code == 403
    assert "set-cookie" not in duplicate_origin.headers


def test_http_voice_provider_is_never_resolved_before_preview_auth(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    client, _ = preview_runtime
    provider_calls = 0

    def available() -> bool:
        nonlocal provider_calls
        provider_calls += 1
        return True

    monkeypatch.setattr(public_memorials, "_gemini_live_available", available)

    blocked = client.post(
        "/memorials/manfred/realtime/webrtc",
        headers={"origin": PUBLIC_ORIGIN},
    )
    wrong_origin = client.post(
        "/memorials/manfred/realtime/webrtc",
        headers={"origin": "https://propertyquarry.com"},
    )

    assert blocked.status_code == 409
    assert wrong_origin.status_code == 403
    assert provider_calls == 0

    _issue_preview(client)
    accepted = client.post(
        "/memorials/manfred/realtime/webrtc",
        headers={"origin": PUBLIC_ORIGIN},
    )

    assert accepted.status_code == 410
    assert provider_calls == 1


def test_all_http_voice_entrypoints_stop_before_runtime_or_provider_work(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorial_turn_support
    from app.api.routes import public_memorials

    client, _ = preview_runtime
    runtime_calls = 0
    render_calls = 0
    warmup_calls = 0

    def runtime_from_shared(shared):
        nonlocal runtime_calls
        runtime_calls += 1
        raise AssertionError("runtime resolved before preview authorization")

    def render_audio(**kwargs):
        nonlocal render_calls
        render_calls += 1
        raise AssertionError("tts provider called before preview authorization")

    def schedule_warmup(slug: str):
        nonlocal warmup_calls
        warmup_calls += 1
        raise AssertionError("warmup scheduled before preview authorization")

    monkeypatch.setattr(
        public_memorial_turn_support,
        "runtime_from_shared",
        runtime_from_shared,
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        render_audio,
    )
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        schedule_warmup,
    )
    headers = {"origin": PUBLIC_ORIGIN}

    responses = [
        client.post(
            "/memorials/manfred/speech-transcribe",
            headers={**headers, "content-type": "audio/wav"},
            content=b"not-provider-bound-without-auth",
        ),
        client.post(
            "/memorials/manfred/speech-synthesize",
            headers=headers,
            json={"text": "Hallo Manfred"},
        ),
        client.post(
            "/memorials/manfred/conversation-turn",
            headers={**headers, "content-type": "audio/wav"},
            content=b"not-provider-bound-without-auth",
        ),
        client.post(
            "/memorials/manfred/warmup",
            headers=headers,
        ),
    ]

    assert [response.status_code for response in responses] == [409, 409, 409, 409]
    assert runtime_calls == 0
    assert render_calls == 0
    assert warmup_calls == 0


@pytest.mark.parametrize(
    "path",
    [
        "/memorials/manfred/readiness",
        "/memorials/manfred/warmup-status",
    ],
)
def test_readiness_routes_stop_before_rate_limit_and_provider_without_voice_access(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    from app.api.routes import public_memorials

    client, _ = preview_runtime
    rate_limit_calls = 0
    provider_calls = 0

    def enforce_rate_limit(*args, **kwargs) -> None:
        nonlocal rate_limit_calls
        rate_limit_calls += 1

    def connect_target():
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider capability resolved before voice access")

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        enforce_rate_limit,
    )
    monkeypatch.setattr(
        public_memorials,
        "_gemini_live_connect_target_with_status",
        connect_target,
    )
    public_memorials._memorial_runtime_readiness_cache_invalidate("manfred")

    response = client.get(path)

    assert response.status_code == 409
    assert rate_limit_calls == 0
    assert provider_calls == 0


@pytest.mark.parametrize(
    "path",
    [
        "/memorials/manfred/readiness",
        "/memorials/manfred/warmup-status",
    ],
)
def test_readiness_routes_resolve_provider_only_after_exact_preview_access(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    from app.api.routes import public_memorials

    client, _ = preview_runtime
    _issue_preview(client)
    provider_calls = 0

    def connect_target():
        nonlocal provider_calls
        provider_calls += 1
        return (
            "wss://generativelanguage.googleapis.com/provider-test",
            {},
            "oauth",
            {"state": "ready", "reason": "", "mode": "oauth"},
        )

    monkeypatch.setattr(
        public_memorials,
        "_gemini_live_connect_target_with_status",
        connect_target,
    )
    public_memorials._memorial_runtime_readiness_cache_invalidate("manfred")

    response = client.get(path)

    assert response.status_code in {200, 503}
    assert response.json().get("detail") != "memorial_voice_release_not_verified"
    assert provider_calls == 1


@pytest.mark.parametrize("rotation", ["token", "source", "deployment"])
def test_preview_cookie_is_reverified_against_current_bindings_on_every_use(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
    rotation: str,
) -> None:
    from app.api.routes import public_memorials

    client, public_root = preview_runtime
    token, _ = _issue_preview(client)
    assert token
    if rotation == "token":
        _write_public_memorial(public_root, write_token=ROTATED_WRITE_TOKEN)
    elif rotation == "source":
        monkeypatch.setattr(
            public_memorials,
            "_memorial_voice_preview_release_context",
            lambda: MemorialVoicePreviewReleaseContext(
                source_revision="d" * 40,
                deployment_id=DEPLOYMENT_ID,
                public_origin=PUBLIC_ORIGIN,
            ),
        )
    else:
        monkeypatch.setattr(
            public_memorials,
            "_memorial_voice_preview_release_context",
            lambda: MemorialVoicePreviewReleaseContext(
                source_revision=SOURCE_REVISION,
                deployment_id="ea-manfred-prod-rotated-20260720",
                public_origin=PUBLIC_ORIGIN,
            ),
        )

    response = client.post(
        "/memorials/manfred/realtime/webrtc",
        headers={"origin": PUBLIC_ORIGIN},
    )

    assert response.status_code == 409
    assert response.json()["detail"] != "gemini_live_uses_websocket_pcm"


def test_tampered_cookie_is_rejected_and_authenticated_delete_revokes_browser_access(
    preview_runtime: tuple[TestClient, Path],
) -> None:
    client, _ = preview_runtime
    token, _ = _issue_preview(client)
    client.cookies.clear()
    client.cookies.set(
        "ea_manfred_voice_preview",
        token[:-1] + ("a" if token[-1] != "a" else "b"),
        path="/memorials/manfred",
    )

    tampered = client.post(
        "/memorials/manfred/realtime/webrtc",
        headers={"origin": PUBLIC_ORIGIN},
    )
    assert tampered.status_code == 409

    client.cookies.clear()
    _issue_preview(client)
    deleted = client.delete(
        "/memorials/manfred/voice-preview/session",
        headers={
            "origin": PUBLIC_ORIGIN,
            "x-memorial-admin-token": WRITE_TOKEN,
        },
    )

    assert deleted.status_code == 200
    assert deleted.json()["public_release_allowed"] is False
    set_cookie = deleted.headers["set-cookie"]
    assert "Max-Age=0" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=Strict" in set_cookie
    assert "Path=/memorials/manfred" in set_cookie
    assert "Domain=" not in set_cookie
    assert client.post(
        "/memorials/manfred/realtime/webrtc",
        headers={"origin": PUBLIC_ORIGIN},
    ).status_code == 409


def test_websocket_rejects_before_accept_and_valid_preview_reaches_ready(
    preview_runtime: tuple[TestClient, Path],
) -> None:
    client, _ = preview_runtime

    with pytest.raises(WebSocketDisconnect) as blocked:
        with client.websocket_connect(
            "wss://myexternalbrain.com/memorials/manfred/realtime",
            headers={"origin": PUBLIC_ORIGIN},
        ):
            pass
    assert blocked.value.code == 4403

    _issue_preview(client)
    with client.websocket_connect(
        "wss://myexternalbrain.com/memorials/manfred/realtime",
        headers={"origin": PUBLIC_ORIGIN},
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        assert ready["mode"] == "memorial_realtime_voice"
        websocket.close()


def test_preview_page_is_conversation_only_while_public_release_stays_blocked(
    preview_runtime: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    client, _ = preview_runtime
    token, _ = _issue_preview(client)

    page = client.get("/memorials/manfred")
    server_decision = public_memorials._memorial_voice_access_decision(
        "manfred",
        request=None,
        websocket=None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_gemini_live_connect_target_with_status",
        lambda: (
            "",
            {},
            "",
            {"state": "disabled", "reason": "oauth_disabled"},
        ),
    )
    public_memorials._memorial_runtime_readiness_cache_invalidate("manfred")
    readiness = public_memorials._memorial_runtime_readiness("manfred")

    assert page.status_code == 200
    assert 'data-public-memorial-surface="conversation-only"' in page.text
    assert page.text.count('id="memorial-conversation-region"') == 1
    assert page.text.count('id="memorial-conversation"') == 1
    assert 'id="memorial-text-turn-form"' in page.text
    assert 'id="memorial-retry-button"' in page.text
    assert 'id="memorial-speech-transcript"' in page.text
    for forbidden in (
        'href="/memorials/manfred/memory-room"',
        'id="memorial-story"',
        'id="memorial-contribution"',
        'id="memorial-install-hint"',
        '<details class="conversation-settings">',
        "3D-Erinnerungsraum",
        "Erinnerungen ansehen",
        "Eine private Erinnerung beitragen",
        "/voice-ab-admin/",
        "/voice-profile/build",
    ):
        assert forbidden not in page.text
    assert 'data-operator-voice-preview="allowed"' in page.text
    assert 'data-voice-release="blocked"' in page.text
    assert 'data-voice-access="operator-preview"' in page.text
    assert "Die öffentliche Sprachfreigabe bleibt blockiert" in page.text
    assert "const memorialPublicVoiceReleaseAllowed = false;" in page.text
    assert "const memorialOperatorPreviewAllowed = true;" in page.text
    assert token not in page.text
    assert "ea_manfred_voice_preview" not in page.text
    assert server_decision["access_allowed"] is False
    assert server_decision["public_release_allowed"] is False
    assert server_decision["reason"] == "memorial_voice_release_not_verified"
    assert readiness["ready"] is False
    assert readiness["status"] == "blocked_release"
    assert readiness["release"]["allowed"] is False
    assert "memorial_voice_release_not_verified" in readiness["degraded_reasons"]
