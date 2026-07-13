from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.services.hedy_meeting_evidence import hedy_webhook_signature


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def _write_public_memorial(root: Path, slug: str, payload: dict[str, object]) -> Path:
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "memorial.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return bundle_dir


def _write_private_voice(root: Path, slug: str, payload: dict[str, object]) -> None:
    profile_dir = root / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "tts_voice.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _patch_memorial_runtime_roots(tmp_path: Path) -> None:
    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry

    artifacts_root = tmp_path / "artifacts"
    public_memorials._PERSONAL_MEMORY_ROOT = artifacts_root / "memorial_user_memory"
    public_memorials._VOICE_AB_ROOT = artifacts_root / "memorial_voice_ab"
    public_memorials._VIDEO_MEETING_RUNTIME_ROOT = artifacts_root / "memorial_video_meeting"
    public_memorials._MEMORIAL_TTS_RENDER_CACHE_ROOT = artifacts_root / "memorial_tts_render_cache"
    public_memorials._MEMORIAL_PRESENT_WORLD_CACHE_ROOT = artifacts_root / "memorial_present_world_cache"
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = tmp_path / "public_registry"
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"


def _error_code(response) -> str:
    body = response.json()
    if isinstance(body.get("error"), dict):
        return str(body["error"].get("code") or "")
    return str(body.get("detail") or "")


def _video_meeting_callback_headers(body: bytes, *, secret: str) -> dict[str, str]:
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    return {
        "content-type": "application/json",
        "x-tavus-timestamp": timestamp,
        "x-tavus-signature": hedy_webhook_signature(body, secret, timestamp=timestamp),
    }


def test_public_memorial_json_is_sanitized_and_raw_manifest_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    bundle_dir = _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "write_token": "must-not-leak",
            "transcript": "TOP_LEVEL_RAW_TRANSCRIPT_SENTINEL",
            "intro": {"private": "STRUCTURED_INTRO_SENTINEL"},
            "character_notes": [{"note": "private-note", "public": False}],
            "audio_clips": [
                {
                    "public": True,
                    "title": "Approved clip",
                    "asset_relpath": "audio/clip.mp3",
                    "transcript": "RAW_TRANSCRIPT_SENTINEL",
                    "public_transcript": "Approved public transcript",
                },
                {
                    "public": True,
                    "title": "Unsafe path",
                    "asset_relpath": "../private/clip.mp3",
                },
                {
                    "visibility": "public",
                    "public": False,
                    "title": "CONFLICTING_AUDIO_SENTINEL",
                    "asset_relpath": "audio/conflicting.mp3",
                },
            ],
            "memory_cards": [
                {
                    "public": True,
                    "title": "Approved memory",
                    "body": {"private": "STRUCTURED_MEMORY_SENTINEL"},
                }
            ],
            "source_grounded_profile": [
                {
                    "public": True,
                    "trait": "Approved trait",
                    "evidence": {"private": "STRUCTURED_EVIDENCE_SENTINEL"},
                }
            ],
            "external_sources": [
                {
                    "public": True,
                    "label": "UNSAFE_SOURCE_SENTINEL",
                    "url": "javascript:alert(1)",
                }
            ],
            "conversation_style": {
                "public": True,
                "reasoning_frame": {"private": "STRUCTURED_STYLE_SENTINEL"},
                "social_tone": "Ruhig",
            },
        },
    )
    (bundle_dir / "audio").mkdir()
    (bundle_dir / "audio" / "clip.mp3").write_bytes(b"clip")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_PWA_INSTALL_ENABLED", "1")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-sanitize")

    response = client.get(f"/memorials/{slug}.json")
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    body = response.json()
    assert "write_token" not in body
    assert body.get("character_notes") == []
    assert "candidate_recordings" not in body
    assert body["audio_clips"] == [
        {
            "title": "Approved clip",
            "asset_relpath": "audio/clip.mp3",
            "public_transcript": "Approved public transcript",
        }
    ]
    assert body["memory_cards"] == [
        {
            "title": "Approved memory",
            "body": "[stark redigiert]",
            "curation_status": "strongly_redacted_preview",
        },
    ]
    assert body["source_grounded_profile"] == [{"trait": "Approved trait"}]
    assert body["external_sources"] == []
    assert body["conversation_style"] == {"social_tone": "Ruhig", "should_avoid": []}
    serialized = json.dumps(body, ensure_ascii=False)
    assert "RAW_TRANSCRIPT_SENTINEL" not in serialized
    assert "TOP_LEVEL_RAW_TRANSCRIPT_SENTINEL" not in serialized
    assert "STRUCTURED_" not in serialized
    assert "CONFLICTING_" not in serialized
    assert "UNSAFE_" not in serialized
    assert "../private" not in serialized

    raw_manifest = client.get(f"/memorials/files/{slug}/memorial.json")
    assert raw_manifest.status_code == 404
    assert raw_manifest.headers.get("Cache-Control") == "no-store"
    assert raw_manifest.headers.get("Referrer-Policy") == "no-referrer"
    assert raw_manifest.headers.get("X-Content-Type-Options") == "nosniff"


def test_memorial_chat_citations_require_public_approval_and_safe_url() -> None:
    from app.api.routes import public_memorials

    labels = public_memorials._memorial_chat_source_labels(
        {
            "external_sources": [
                {
                    "visibility": "public",
                    "label": "Unapproved private-context source",
                    "url": "https://private-context.example/source",
                    "status": "research_only",
                },
                {
                    "visibility": "public",
                    "approved": True,
                    "label": "Unsafe approved source",
                    "url": "javascript:alert(1)",
                    "status": "approved",
                },
                {
                    "visibility": "public",
                    "approved": True,
                    "label": "Approved public source",
                    "url": "https://memorial.example/source",
                    "status": "approved",
                },
            ]
        },
        question="Was war Manfred wichtig?",
    )

    assert labels == ["Approved public source"]


def test_memorial_story_sources_require_public_approval_and_safe_url() -> None:
    from app.api.routes import public_memorials

    story_html = public_memorials._public_memorial_story_html(
        {
            "external_sources": [
                {
                    "visibility": "public",
                    "label": "UNAPPROVED_STORY_SOURCE_SENTINEL",
                    "url": "https://memorial.example/unapproved",
                },
                {
                    "visibility": "public",
                    "approved": True,
                    "label": "UNSAFE_STORY_SOURCE_SENTINEL",
                    "url": "javascript:alert(1)",
                },
                {
                    "visibility": "public",
                    "approved": True,
                    "label": "Approved story source",
                    "url": "https://memorial.example/approved",
                },
            ]
        },
        slug="manfred",
    )

    assert "Approved story source" in story_html
    assert "UNAPPROVED_STORY_SOURCE_SENTINEL" not in story_html
    assert "UNSAFE_STORY_SOURCE_SENTINEL" not in story_html


def test_generic_importance_question_uses_grounded_values_guardrail() -> None:
    from app.api.routes import public_memorials

    answer = public_memorials._memorial_chat_answer(
        {"slug": "manfred", "person_name": "Manfred"},
        "Was war Manfred wichtig?",
        {},
        "ea-coder-fast",
        slug="manfred",
    )

    assert answer["fallback_reason"] == "memorial_values_guardrail"
    assert answer["llm_provider"] == "memorial_guardrail"
    assert answer["sources"] == []
    assert "Tatsachen" in answer["answer"]
    assert "Prinzip" in answer["answer"]
    assert "Fairness" in answer["answer"]


def test_public_memorial_pwa_uses_configured_png_icons_and_install_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    bundle_dir = _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "pwa_app_name": "Mit Manfred sprechen",
            "pwa_short_name": "Manfred",
            "pwa_icon": {
                "src_180": "icons/manfred-180.png",
                "src_192": "icons/manfred-192.png",
                "src_512": "icons/manfred-512.png",
            },
            "audio_clips": [],
        },
    )
    icon_dir = bundle_dir / "icons"
    icon_dir.mkdir()
    for size in (180, 192, 512):
        (icon_dir / f"manfred-{size}.png").write_bytes(b"\x89PNG\r\n\x1a\nicon")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_PWA_INSTALL_ENABLED", "1")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-pwa-icons")

    manifest = client.get(f"/memorials/{slug}/app.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers.get("Cache-Control") == "no-store"
    assert manifest.headers.get("Referrer-Policy") == "no-referrer"
    assert manifest.headers.get("X-Content-Type-Options") == "nosniff"
    assert manifest.headers.get("X-Robots-Tag") == "noindex, nofollow"
    manifest_body = manifest.json()
    assert manifest_body["name"] == "Mit Manfred sprechen"
    assert manifest_body["short_name"] == "Manfred"
    assert manifest_body["scope"] == f"/memorials/{slug}"
    assert manifest_body["start_url"] == f"/memorials/{slug}?source=pwa"
    assert {icon["sizes"]: icon["type"] for icon in manifest_body["icons"]} == {
        "192x192": "image/png",
        "512x512": "image/png",
    }
    assert all("icon.svg" not in icon["src"] for icon in manifest_body["icons"])

    page = client.get(f"/memorials/{slug}")
    assert page.status_code == 200


def test_public_memorial_svg_icon_sends_nosniff_header(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-svg-icon")
    response = client.get(f"/memorials/{slug}/icon.svg")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "public, max-age=3600"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("content-type", "").startswith("image/svg+xml")


def test_public_memorial_png_icon_sends_referrer_privacy_header(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    bundle_dir = _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "pwa_icon": {
                "src_180": "icons/manfred-180.png",
            },
            "audio_clips": [],
        },
    )
    icon_dir = bundle_dir / "icons"
    icon_dir.mkdir()
    (icon_dir / "manfred-180.png").write_bytes(b"\x89PNG\r\n\x1a\nicon")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-png-icon")
    response = client.get(f"/memorials/{slug}/icon-180.png")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "public, max-age=3600"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.headers.get("content-type", "").startswith("image/png")


def test_public_memorial_invalid_png_icon_uses_hardened_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-invalid-png-icon")
    response = client.get(f"/memorials/{slug}/icon-999.png")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["detail"] == "memorial_icon_not_found"


def test_public_memorial_pwa_install_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.delenv("EA_MEMORIAL_PWA_INSTALL_ENABLED", raising=False)
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {"slug": slug, "person_name": "Manfred Hoza", "pwa_app_name": "Mit Manfred sprechen", "audio_clips": []},
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-pwa-disabled")

    manifest = client.get(f"/memorials/{slug}/app.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers.get("Cache-Control") == "no-store"
    assert manifest.headers.get("Referrer-Policy") == "no-referrer"
    assert manifest.headers.get("X-Content-Type-Options") == "nosniff"
    assert manifest.headers.get("X-Robots-Tag") == "noindex, nofollow"
    body = manifest.json()
    assert body["display"] == "browser"
    assert body["start_url"] == f"/memorials/{slug}"
    assert body["install_policy"] == "disabled_until_install_update_offline_behavior_is_tested"

    worker = client.get(f"/memorials/{slug}/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers.get("Cache-Control") == "no-store"
    assert worker.headers.get("Referrer-Policy") == "no-referrer"
    assert worker.headers.get("X-Content-Type-Options") == "nosniff"
    assert worker.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert "caches.delete" in worker.text
    assert "cache.addAll" not in worker.text
    page = client.get(f"/memorials/{slug}")
    assert page.status_code == 200
    assert "Gespräch beginnen" in page.text
    assert 'id="memorial-video-call"' not in page.text
    assert "Am Handy/Desktop installieren" in page.text
    assert "memorialPwaInstallEnabled = false" in page.text
    assert "App installieren" not in page.text
    assert 'id="memorial-hero-actions"' in page.text
    assert 'aria-disabled="true" disabled' in page.text
    assert f'/memorials/{slug}/warmup' in page.text
    assert 'ensureMemorialReady("page_load")' in page.text
    assert 'requestMemorialWarmup("conversation_start")' not in page.text
    assert "primeMemorialLanding()" in page.text
    assert "startVideoCallPreview()" not in page.text
    assert "continueVideoCallWithoutCamera()" not in page.text
    assert 'id="memorial-video-call-preview"' not in page.text
    assert 'id="memorial-video-call-avatar-stage"' not in page.text
    assert 'id="memorial-video-call-avatar-face"' not in page.text
    assert 'id="memorial-video-call-continue-no-camera"' not in page.text
    assert 'id="memorial-video-call-avatar-video"' not in page.text
    assert 'id="memorial-video-call-avatar-fallback"' in page.text
    assert "VidBoard noch nicht live" in page.text
    assert "Gleich kannst du mit mir reden." in page.text
    assert "/memorials/manfred/realtime" in page.text
    assert "/memorials/manfred/realtime/webrtc" not in page.text
    assert "RTCPeerConnection" not in page.text
    assert "gemini_live_websocket_pcm" in page.text
    assert "audio/pcm;rate=16000" in page.text
    assert "openai" not in page.text.lower()
    assert "ensureRealtimeSocket" in page.text
    assert "user_audio_start" in page.text
    assert "user_audio_end" in page.text
    assert "/memorials/manfred/conversation-turn" not in page.text
    assert "ensureMemorialReady(\"page_load\")" in page.text
    assert "requestMemorialWarmup(\"conversation_start\")" not in page.text
    assert "server_stt_cooldown" not in page.text
    assert "utterance.onstart = () => {" not in page.text
    assert 'setSpeechStatus("Ich antworte gleich.", "working", "Meine Stimme wird gestartet")' not in page.text
    assert "<h1>" in page.text
    assert '<a class="skip-link" href="#memorial-story">' in page.text
    assert '<main id="memorial-story" tabindex="-1">' in page.text
    assert '<aside class="conversation-dock"' in page.text
    assert "Tippen, sprechen, kurz warten, einfach weiterreden." not in page.text
    assert "Hosted on myexternalbrain.com" not in page.text


def test_memorial_realtime_safety_identifier_ignores_principal_header() -> None:
    from app.api.routes import public_memorials

    base_scope = {
        "type": "http",
        "method": "GET",
        "path": "/memorials/manfred/realtime",
        "client": ("203.0.113.10", 49152),
    }
    request_a = Request(
        {
            **base_scope,
            "headers": [
                (b"user-agent", b"memorial-browser"),
                (b"accept-language", b"de-AT,de;q=0.8"),
                (b"x-ea-principal-id", b"spoofed-a"),
            ],
        }
    )
    request_b = Request(
        {
            **base_scope,
            "headers": [
                (b"user-agent", b"memorial-browser"),
                (b"accept-language", b"de-AT,de;q=0.8"),
                (b"x-ea-principal-id", b"spoofed-b"),
            ],
        }
    )

    identifier_a = public_memorials._memorial_realtime_safety_identifier(slug="manfred", request=request_a)
    identifier_b = public_memorials._memorial_realtime_safety_identifier(slug="manfred", request=request_b)

    assert identifier_a == identifier_b


def test_memorial_realtime_safety_identifier_changes_with_public_session_fingerprint() -> None:
    from app.api.routes import public_memorials

    request_a = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/memorials/manfred/realtime",
            "client": ("203.0.113.10", 49152),
            "headers": [
                (b"user-agent", b"memorial-browser"),
                (b"accept-language", b"de-AT,de;q=0.8"),
            ],
        }
    )
    request_b = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/memorials/manfred/realtime",
            "client": ("203.0.113.11", 49152),
            "headers": [
                (b"user-agent", b"memorial-browser"),
                (b"accept-language", b"de-AT,de;q=0.8"),
            ],
        }
    )

    identifier_a = public_memorials._memorial_realtime_safety_identifier(slug="manfred", request=request_a)
    identifier_b = public_memorials._memorial_realtime_safety_identifier(slug="manfred", request=request_b)

    assert identifier_a != identifier_b


def test_public_memorial_client_key_ignores_forwarded_ip_without_explicit_trust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR", "0")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/memorials/manfred",
            "client": ("203.0.113.10", 49152),
            "headers": [
                (b"cf-connecting-ip", b"198.51.100.42"),
            ],
        }
    )

    key = public_memorials._public_memorial_client_key(request=request, context={"scope": "public"})

    assert key == "ip:203011310:scope:public"


def test_public_memorial_client_key_uses_forwarded_ip_when_explicitly_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR", "1")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/memorials/manfred",
            "client": ("203.0.113.10", 49152),
            "headers": [
                (b"cf-connecting-ip", b"198.51.100.42"),
            ],
        }
    )

    key = public_memorials._public_memorial_client_key(request=request, context={"scope": "public"})

    assert key == "ip:1985110042:scope:public"


def test_public_memorial_voice_config_only_exposes_selected_voicewave_option(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_label": "Manfred Hoza · VoiceWave-Klon",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    monkeypatch.setenv("VOICEWAVE_LOGIN_EMAIL", "voicewave@example.com")
    monkeypatch.setenv("VOICEWAVE_LOGIN_PASSWORD", "secret")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voicewave-config")
    response = client.get(
        f"/memorials/{slug}/voice-config",
        headers={"x-memorial-write-token": "unit-write-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    body = response.json()
    assert body["tts_plugin"] == "voicewave_clone"
    assert body["tts_mode"] == "voicewave_clone"
    assert body["voice_label"] == "Manfred Hoza · VoiceWave-Klon"
    assert body["tts_plugin_options"] == [
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_label": "VoiceWave Clone",
            "tts_plugin_description": "VoiceWave-Studio-Clone fuer memoriale Sprachausgabe ist verbunden.",
            "tts_plugin_enabled": True,
            "tts_plugin_clone_capable": True,
            "tts_plugin_needs_clone": False,
            "tts_plugin_requires_voice_id": True,
        }
    ]


def test_public_memorial_voice_config_requires_write_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_label": "Manfred Hoza · VoiceWave-Klon",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-config-auth")
    response = client.get(f"/memorials/{slug}/voice-config")

    assert response.status_code == 403
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_write_unauthorized"


def test_public_memorial_voice_config_invalid_json_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-config-invalid-json")
    response = client.post(
        f"/memorials/{slug}/voice-config",
        headers={"x-memorial-write-token": "unit-write-token", "content-type": "application/json"},
        content="{",
    )

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "invalid_json"


def test_public_memorial_voice_profile_requires_write_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-profile-auth")
    response = client.get(f"/memorials/{slug}/voice-profile")

    assert response.status_code == 403
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_write_unauthorized"


def test_public_memorial_speech_synthesize_supports_voicewave_clone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-08T16:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    monkeypatch.setenv("VOICEWAVE_LOGIN_EMAIL", "voicewave@example.com")
    monkeypatch.setenv("VOICEWAVE_LOGIN_PASSWORD", "secret")
    _patch_memorial_runtime_roots(tmp_path)

    from app.api.routes import public_memorials

    seen_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        public_memorials,
        "voicewave_synthesize_request",
        lambda **kwargs: seen_calls.append(dict(kwargs)) or (b"voicewave-audio", "audio/wav"),
    )

    client = _client(principal_id="exec-memorial-voicewave-tts")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ich bin da."})

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content
    assert {"text": "Ich bin da.", "voice_label": "Manfred Hoza Memorial"} in seen_calls


@pytest.mark.parametrize("blocked_plugin", ["openvoice_local", "piper_local_fast"])
def test_public_memorial_speech_synthesize_sanitizes_openvoice_backed_tts_plugins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    blocked_plugin: str,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": blocked_plugin,
            "tts_plugin_voice_id": "blocked-local-voice",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-08T16:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "runtime-unmixr-voice")
    _patch_memorial_runtime_roots(tmp_path)

    from app.api.routes import public_memorials

    seen_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: seen_calls.append(dict(kwargs)) or (b"unmixr-audio", "audio/wav"),
    )

    client = _client(principal_id=f"exec-memorial-blocked-tts-{blocked_plugin}")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ich bin da."})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert seen_calls == [
        {
            "text": "Ich bin da.",
            "voice_id": "runtime-unmixr-voice",
            "lang": "de-AT",
            "speaking_rate": "0.90",
            "speaking_pitch": "",
            "speaking_volume": "",
        }
    ]
    assert blocked_plugin.encode("utf-8") not in response.content


def test_public_memorial_speech_synthesize_without_voice_consent_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_consent": {
                "status": "pending",
                "scope": [],
                "authorized_by": "",
                "authorized_at": "",
                "source_assets_reviewed": False,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-tts-no-consent")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ich bin da."})

    assert response.status_code == 403
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "voice_consent_required"


def test_public_memorial_speech_synthesize_uses_contact_pads_for_direct_opening(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-08T16:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    monkeypatch.setenv("VOICEWAVE_LOGIN_EMAIL", "voicewave@example.com")
    monkeypatch.setenv("VOICEWAVE_LOGIN_PASSWORD", "secret")
    _patch_memorial_runtime_roots(tmp_path)

    from app.api.routes import public_memorials

    seen: dict[str, object] = {}

    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: seen.update(kwargs) or (b"voicewave-audio", "audio/wav"),
    )

    client = _client(principal_id="exec-memorial-voicewave-contact-pads")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ja."})

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.headers["content-type"].startswith("audio/wav")
    assert seen["lead_in_ms"] == public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS
    assert seen["tail_silence_ms"] == public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS


def test_public_memorial_video_call_can_render_real_avatar_video_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    bundle_dir = _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "video_call_avatar": {
                "provider_key": "vidboard",
                "provider_proof_verdict": "VERIFIED_PROVIDER",
                "public_ready": True,
                "asset_relpath": "video/manfred-avatar.mp4",
                "poster_relpath": "video/manfred-avatar-poster.png",
                "provider_label": "VidBoard Avatar bereit",
                "title": "Manfred Hoza als Avatar",
                "detail": "VidBoard-Clip ist für den Video Call eingebunden.",
            },
        },
    )
    video_dir = bundle_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "manfred-avatar.mp4").write_bytes(b"mp4")
    (video_dir / "manfred-avatar-poster.png").write_bytes(b"\x89PNG\r\n\x1a\nposter")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-video-avatar")

    page = client.get(f"/memorials/{slug}")
    assert page.status_code == 200
    assert 'id="memorial-video-call-avatar-video"' not in page.text
    assert f'/memorials/files/{slug}/video/manfred-avatar.mp4' not in page.text
    assert "VidBoard Avatar bereit" not in page.text

    asset = client.get(f"/memorials/files/{slug}/video/manfred-avatar.mp4")
    assert asset.status_code == 200

    payload = client.get(f"/memorials/{slug}.json")
    assert payload.status_code == 200
    assert payload.json()["video_call_avatar"] == {
        "enabled": True,
        "kind": "video",
        "provider_label": "VidBoard Avatar bereit",
        "title": "Manfred Hoza als Avatar",
        "detail": "VidBoard-Clip ist für den Video Call eingebunden.",
        "asset_url": f"/memorials/files/{slug}/video/manfred-avatar.mp4",
        "poster_url": f"/memorials/files/{slug}/video/manfred-avatar-poster.png",
    }


def test_public_memorial_video_call_blocks_unverified_avatar_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    bundle_dir = _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "video_call_avatar": {
                "provider_key": "vidboard",
                "provider_proof_verdict": "READY_VIA_FALLBACK",
                "public_ready": False,
                "asset_relpath": "video/manfred-avatar.mp4",
                "poster_relpath": "video/manfred-avatar-poster.png",
                "provider_label": "VidBoard in Prüfung",
                "title": "Manfred Hoza als Avatar",
                "detail": "Nicht freigegeben.",
            },
        },
    )
    video_dir = bundle_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "manfred-avatar.mp4").write_bytes(b"mp4")
    (video_dir / "manfred-avatar-poster.png").write_bytes(b"\x89PNG\r\n\x1a\nposter")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-video-avatar-blocked")

    page = client.get(f"/memorials/{slug}")
    assert page.status_code == 200
    assert 'id="memorial-video-call-avatar-video"' not in page.text
    assert 'id="memorial-video-call-avatar-fallback"' in page.text
    assert "VidBoard in Prüfung" in page.text
    assert "liegt vor, ist aber noch nicht freigegeben" in page.text
    assert f'/memorials/files/{slug}/video/manfred-avatar.mp4' not in page.text

    asset = client.get(f"/memorials/files/{slug}/video/manfred-avatar.mp4")
    assert asset.status_code == 404
    assert asset.headers.get("Cache-Control") == "no-store"
    assert asset.headers.get("Referrer-Policy") == "no-referrer"
    assert asset.headers.get("X-Content-Type-Options") == "nosniff"

    payload = client.get(f"/memorials/{slug}.json")
    assert payload.status_code == 200
    assert payload.json()["video_call_avatar"] == {
        "enabled": False,
        "kind": "portrait",
        "provider_label": "VidBoard in Prüfung",
        "title": "Manfred Hoza als Avatar",
        "detail": "Der eigentliche VidBoard-Avatar liegt vor, ist aber noch nicht freigegeben. Bis dahin zeigen wir nur die Portraitvorschau.",
        "asset_url": "",
        "poster_url": "",
    }


def test_public_memorial_public_asset_sends_referrer_privacy_header(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    bundle_dir = _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "public_documents": [
                {
                    "public": True,
                    "title": "Rede",
                    "asset_relpath": "docs/rede.pdf",
                },
                {
                    "visibility": "private",
                    "title": "Private",
                    "asset_relpath": "docs/private.pdf",
                },
                {
                    "title": "Implicit",
                    "asset_relpath": "docs/implicit.pdf",
                },
                {
                    "visibility": "public",
                    "public": False,
                    "title": "Conflicting",
                    "asset_relpath": "docs/conflicting.pdf",
                },
                {
                    "public": True,
                    "title": "Unsafe SVG",
                    "asset_relpath": "docs/public.svg",
                },
            ],
        },
    )
    docs_dir = bundle_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "rede.pdf").write_bytes(b"%PDF-1.4 memorial")
    (docs_dir / "private.pdf").write_bytes(b"%PDF-1.4 private")
    (docs_dir / "implicit.pdf").write_bytes(b"%PDF-1.4 implicit")
    (docs_dir / "conflicting.pdf").write_bytes(b"%PDF-1.4 conflicting")
    (docs_dir / "public.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-public-asset")
    response = client.get(f"/memorials/files/{slug}/docs/rede.pdf")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "public, max-age=3600, immutable"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.headers.get("content-type", "").startswith("application/pdf")
    for filename in ("private.pdf", "implicit.pdf", "conflicting.pdf", "public.svg"):
        rejected = client.get(f"/memorials/files/{slug}/docs/{filename}")
        assert rejected.status_code == 404


def test_public_memorial_video_meeting_status_and_session_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.delenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_VIDEO_AVATAR_BETA", raising=False)
    monkeypatch.delenv("TAVUS_API_KEY", raising=False)
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-video-meeting-fallback")

    status = client.get(f"/memorials/{slug}/video-meeting/status")
    assert status.status_code == 200
    assert status.headers.get("Cache-Control") == "no-store"
    assert status.headers.get("Referrer-Policy") == "no-referrer"
    assert status.headers.get("X-Content-Type-Options") == "nosniff"
    assert status.json()["video_meeting"] == {
        "enabled": False,
        "integration_state": "disabled_voice_gold_scope",
        "provider_key": "",
        "provider_label": "",
        "fallback_mode": "voice_only",
        "next_action": "voice_gold_video_beta_disabled",
        "detail": "Video/avatar meeting is disabled for the voice-only memorial release scope.",
    }

    session = client.post(
        f"/memorials/{slug}/video-meeting/session",
        json={"camera_requested": True, "personal_memory_enabled": False},
    )
    assert session.status_code == 404
    assert session.headers.get("Cache-Control") == "no-store"
    assert session.headers.get("Referrer-Policy") == "no-referrer"
    assert session.headers.get("X-Content-Type-Options") == "nosniff"
    body = session.json()
    assert body["integration_state"] == "disabled_voice_gold_scope"
    assert body["fallback_mode"] == "voice_only"
    assert body["next_action"] == "voice_gold_video_beta_disabled"


def test_public_memorial_video_meeting_status_reports_provider_configured_contract_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_AVATAR_BETA", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "tavus")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", "1")
    monkeypatch.setenv("TAVUS_API_KEY", "test-key")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-video-meeting-tavus-contract")

    status = client.get(f"/memorials/{slug}/video-meeting/status")
    assert status.status_code == 200
    assert status.headers.get("Cache-Control") == "no-store"
    assert status.headers.get("Referrer-Policy") == "no-referrer"
    assert status.headers.get("X-Content-Type-Options") == "nosniff"
    video_meeting = status.json()["video_meeting"]
    assert video_meeting["integration_state"] == "provider_configured_contract_only"
    assert video_meeting["provider_key"] == "tavus"
    assert video_meeting["provider_label"] == "Tavus"
    assert video_meeting["next_action"] == "provider_session_runtime_not_implemented"
    assert video_meeting["contract_name"] == "ea.memorial_video_meeting_ltd_integration.v1"
    assert video_meeting["provider_truth_allowed"] is False
    assert video_meeting["gold_claim_allowed"] is False
    assert video_meeting["provider_session_creation_allowed"] is False

    session = client.post(f"/memorials/{slug}/video-meeting/session", json={"camera_requested": False})
    assert session.status_code == 202
    assert session.headers.get("Cache-Control") == "no-store"
    assert session.headers.get("Referrer-Policy") == "no-referrer"
    assert session.headers.get("X-Content-Type-Options") == "nosniff"
    body = session.json()
    assert body["integration_state"] == "provider_configured_contract_only"
    assert body["provider_key"] == "tavus"
    assert body["provider_label"] == "Tavus"
    assert body["next_action"] == "provider_session_runtime_not_implemented"
    assert body["provider_truth_allowed"] is False
    assert body["gold_claim_allowed"] is False


def test_public_memorial_chatlab_status_defaults_to_first_party_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    for name in (
        "EA_MEMORIAL_CHATLAB_ENABLED",
        "EA_MEMORIAL_CHAT_LAB_ENABLED",
        "EA_MEMORIAL_CHATLAB_PROVIDER",
        "EA_MEMORIAL_CHAT_LAB_PROVIDER",
        "EA_MEMORIAL_CHATLAB_API_KEY",
        "EA_MEMORIAL_CHATLAB_API_URL",
        "EA_MEMORIAL_CHATLAB_ALLOW_PROVIDER_RUNTIME",
        "CHATLAB_API_KEY",
        "CHATLAB_API_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-chatlab-first-party")
    response = client.get(f"/memorials/{slug}/chatlab/status")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    chatlab = response.json()["chatlab"]
    assert chatlab["contract_name"] == "ea.memorial_chatlab_ltd_integration.v1"
    assert chatlab["integration_state"] == "fallback_first_party_chat"
    assert chatlab["provider_key"] == ""
    assert chatlab["provider_truth_allowed"] is False
    assert chatlab["provider_persona_truth_allowed"] is False
    assert chatlab["provider_memory_write_allowed"] is False
    assert chatlab["provider_guardrail_override_allowed"] is False
    assert chatlab["raw_private_context_allowed"] is False
    assert chatlab["gold_claim_allowed"] is False
    assert chatlab["first_party_chat_remains_authoritative"] is True
    assert "chatlab_runtime_probe_receipt" in chatlab["required_next_receipts"]


def test_public_memorial_chat_response_exposes_chatlab_transport_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_PROVIDER", "chatlab")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_KEY", "test-chatlab-key")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_URL", "https://chatlab.example.test")
    monkeypatch.delenv("EA_MEMORIAL_CHATLAB_ALLOW_PROVIDER_RUNTIME", raising=False)
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-chatlab-contract")
    response = client.post(f"/memorials/{slug}/chat", json={"question": "Was dachte er ueber Kinder schlagen?"})

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    body = response.json()
    assert body["fallback_reason"] == "difficult_memory_guardrail"
    chatlab = body["chatlab_contract"]
    assert chatlab["integration_state"] == "provider_configured_contract_only"
    assert chatlab["provider_key"] == "chatlab"
    assert chatlab["provider_label"] == "ChatLab"
    assert chatlab["provider_configured"] is True
    assert chatlab["provider_runtime_allowed"] is False
    assert chatlab["provider_truth_allowed"] is False
    assert chatlab["provider_memory_write_allowed"] is False
    assert chatlab["provider_guardrail_override_allowed"] is False
    assert chatlab["first_party_chat_remains_authoritative"] is True
    assert chatlab["difficult_memory_guardrail_owner"] == "ea_first_party_memorial_chat"


def test_public_memorial_chat_invalid_json_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-chat-invalid-json")
    response = client.post(
        f"/memorials/{slug}/chat",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "invalid_json"


def test_public_memorial_chat_help_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-chat-help-missing")
    response = client.get("/memorials/not-found/chat")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_public_memorial_chatlab_status_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-chatlab-missing")
    response = client.get("/memorials/not-found/chatlab/status")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_public_memorial_chat_rate_limit_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(status_code=429, detail="memorial_rate_limited")),
    )

    client = _client(principal_id="exec-memorial-chat-rate-limit")
    response = client.post(f"/memorials/{slug}/chat", json={"question": "Was dachte er ueber Kinder schlagen?"})

    assert response.status_code == 429
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "memorial_rate_limited"


def test_public_memorial_video_meeting_status_reports_tavus_live_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_AVATAR_BETA", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "tavus")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ALLOW_PROVIDER_SESSION", "1")
    monkeypatch.setenv("TAVUS_API_KEY", "test-key")
    monkeypatch.setenv("TAVUS_PERSONA_ID", "persona-123")
    monkeypatch.setenv("TAVUS_REPLICA_ID", "replica-123")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-video-meeting-tavus-live-ready")

    status = client.get(f"/memorials/{slug}/video-meeting/status")
    assert status.status_code == 200
    assert status.headers.get("Cache-Control") == "no-store"
    assert status.headers.get("Referrer-Policy") == "no-referrer"
    assert status.headers.get("X-Content-Type-Options") == "nosniff"
    video_meeting = status.json()["video_meeting"]
    assert video_meeting["integration_state"] == "provider_live_session_ready"
    assert video_meeting["provider_key"] == "tavus"
    assert video_meeting["provider_label"] == "Tavus"
    assert video_meeting["next_action"] == "create_provider_session"
    assert video_meeting["provider_session_creation_allowed"] is True
    assert video_meeting["live_provider_runtime_verified"] is False
    assert video_meeting["gold_claim_allowed"] is False


def test_public_memorial_video_meeting_session_creates_tavus_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_AVATAR_BETA", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "tavus")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ALLOW_PROVIDER_SESSION", "1")
    monkeypatch.setenv("TAVUS_API_KEY", "test-key")
    monkeypatch.setenv("TAVUS_PERSONA_ID", "persona-123")
    monkeypatch.setenv("TAVUS_REPLICA_ID", "replica-123")
    _patch_memorial_runtime_roots(tmp_path)

    from app.services import memorial_video_meeting

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "conversation_id": "conv-123",
                "conversation_url": "https://tavus.daily.co/conv-123",
                "meeting_token": "token-123",
                "status": "active",
                "created_at": "2026-06-08T12:00:00Z",
            }

    seen: dict[str, object] = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["json"] = json
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(memorial_video_meeting.requests, "post", _fake_post)

    client = _client(principal_id="exec-memorial-video-meeting-tavus-live-created")
    session = client.post(
        f"/memorials/{slug}/video-meeting/session",
        json={"camera_requested": True, "personal_memory_enabled": True},
    )
    assert session.status_code == 200
    body = session.json()
    assert body["integration_state"] == "provider_live_session_created"
    assert body["provider_key"] == "tavus"
    assert body["provider_label"] == "Tavus"
    assert body["next_action"] == "join_provider_session"
    assert body["provider_session"]["conversation_url"] == "https://tavus.daily.co/conv-123"
    assert body["provider_session"]["callback_url"].endswith(f"/memorials/{slug}/video-meeting/provider-callback")
    assert body["provider_session_created"] is True
    assert body["live_provider_runtime_verified"] is False
    assert body["gold_claim_allowed"] is False
    assert seen["url"] == "https://tavusapi.com/v2/conversations"
    assert seen["headers"]["x-api-key"] == "test-key"
    assert seen["json"]["persona_id"] == "persona-123"
    assert seen["json"]["replica_id"] == "replica-123"
    assert "personal_memory_enabled" not in seen["json"]


def test_public_memorial_video_meeting_provider_callback_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_AVATAR_BETA", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "tavus")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_WEBHOOK_SECRET", "callback-secret")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-video-meeting-provider-callback")
    body = json.dumps(
        {
            "event_type": "conversation.updated",
            "conversation_id": "conv-123",
            "status": "ended",
            "meeting_token": "must-not-leak",
            "created_at": "2026-06-08T12:00:00Z",
            "updated_at": "2026-06-08T12:03:00Z",
            "ended_at": "2026-06-08T12:04:00Z",
            "persona_id": "persona-123",
            "replica_id": "replica-123",
            "participant_count": 2,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    response = client.post(
        f"/memorials/{slug}/video-meeting/provider-callback",
        content=body,
        headers=_video_meeting_callback_headers(body, secret="callback-secret"),
    )
    assert response.status_code == 202
    assert response.json() == {
        "slug": slug,
        "status": "accepted",
        "provider_key": "tavus",
    }

    callback_path = tmp_path / "artifacts" / "memorial_video_meeting" / slug / "provider_callback.latest.json"
    stored = json.loads(callback_path.read_text(encoding="utf-8"))
    assert stored["slug"] == slug
    assert stored["provider_key"] == "tavus"
    assert stored["event"] == {
        "provider_key": "tavus",
        "event_type": "conversation.updated",
        "conversation_id": "conv-123",
        "status": "ended",
        "created_at": "2026-06-08T12:00:00Z",
        "updated_at": "2026-06-08T12:03:00Z",
        "ended_at": "2026-06-08T12:04:00Z",
        "persona_id": "persona-123",
        "replica_id": "replica-123",
        "participant_count": 2,
    }
    assert "meeting_token" not in stored["event"]


def test_public_memorial_video_meeting_provider_callback_fails_closed_without_valid_signature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_AVATAR_BETA", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "tavus")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_WEBHOOK_SECRET", "callback-secret")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-video-meeting-provider-callback-reject")
    body = b'{"event_type":"conversation.updated","conversation_id":"conv-123"}'

    bad_signature = client.post(
        f"/memorials/{slug}/video-meeting/provider-callback",
        content=body,
        headers={
            "content-type": "application/json",
            "x-tavus-timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "x-tavus-signature": "sha256=bad",
        },
    )
    assert bad_signature.status_code == 401
    assert bad_signature.headers.get("Cache-Control") == "no-store"
    assert bad_signature.headers.get("Referrer-Policy") == "no-referrer"
    assert bad_signature.headers.get("X-Content-Type-Options") == "nosniff"
    assert bad_signature.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert _error_code(bad_signature) == "webhook_signature_mismatch"

    monkeypatch.delenv("EA_MEMORIAL_VIDEO_MEETING_WEBHOOK_SECRET", raising=False)
    missing_secret = client.post(
        f"/memorials/{slug}/video-meeting/provider-callback",
        content=body,
        headers={
            "content-type": "application/json",
            "x-tavus-timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "x-tavus-signature": "sha256=bad",
        },
    )
    assert missing_secret.status_code == 401
    assert missing_secret.headers.get("Cache-Control") == "no-store"
    assert missing_secret.headers.get("Referrer-Policy") == "no-referrer"
    assert missing_secret.headers.get("X-Content-Type-Options") == "nosniff"
    assert missing_secret.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert _error_code(missing_secret) == "webhook_secret_required"

    callback_path = tmp_path / "artifacts" / "memorial_video_meeting" / slug / "provider_callback.latest.json"
    assert not callback_path.exists()


def test_public_memorial_json_includes_public_archive_registry_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    registry_root = tmp_path / "public_registry" / slug
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "archive_registry.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "generated_at": "2026-06-06T03:36:37Z",
                "archive_sections": [
                    {"title": "Oeffentliches Archiv", "audience": "public", "items": ["doc-public"]},
                    {"title": "Familienarchiv", "audience": "family", "items": ["doc-family"]},
                ],
                "fliplink_publications": [
                    {
                        "id": "doc-public",
                        "title": "Public Doc",
                        "audience": "public",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/public",
                        "description": "Visible",
                        "sensitivity": "PUBLIC",
                        "review_status": "approved",
                        "version": "2026-06-06",
                    },
                    {
                        "id": "doc-family",
                        "title": "Family Doc",
                        "audience": "family",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/family",
                        "description": "Hidden",
                        "sensitivity": "FAMILY",
                        "review_status": "approved",
                        "version": "2026-06-06",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    client = _client(principal_id="exec-memorial-archive-json")
    response = client.get(f"/memorials/{slug}.json")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    body = response.json()
    assert body["archive_sections"] == [{"title": "Oeffentliches Archiv", "audience": "public", "items": ["doc-public"]}]
    assert len(body["fliplink_publications"]) == 1
    assert body["fliplink_publications"][0]["id"] == "doc-public"


def test_memorial_fliplink_webhook_stages_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_MEMORIAL_FLIPLINK_WEBHOOK_SECRET", "secret-123")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-fliplink-webhook")
    response = client.post(
        f"/v1/integrations/fliplink/memorials/{slug}/webhook",
        headers={"x-memorial-fliplink-secret": "secret-123"},
        json={
            "publication_slug": "share-a-memory",
            "name": "Test User",
            "email": "test@example.com",
            "relationship": "friend",
            "message": "Ich erinnere mich daran, wie trocken er formuliert hat.",
            "audience": "public",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    body = response.json()
    assert body["status"] == "staged"
    assert body["kind"] == "memorial_contribution_candidate"
    assert body["principal_id"] == "memorial:manfred"
    assert body["slug"] == "manfred"
    assert body["publication_slug"] == "share-a-memory"
    assert body["review_status"] == "pending_owner_review"


def test_memorial_fliplink_webhook_rejects_bad_secret_and_empty_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_MEMORIAL_FLIPLINK_WEBHOOK_SECRET", "secret-123")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-fliplink-webhook-reject")
    unauthorized = client.post(
        f"/v1/integrations/fliplink/memorials/{slug}/webhook",
        headers={"x-memorial-fliplink-secret": "wrong"},
        json={"message": "Should not be accepted."},
    )
    assert unauthorized.status_code == 401
    assert unauthorized.headers.get("Cache-Control") == "no-store"
    assert unauthorized.headers.get("Referrer-Policy") == "no-referrer"
    assert unauthorized.headers.get("X-Content-Type-Options") == "nosniff"
    assert unauthorized.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert _error_code(unauthorized) == "memorial_fliplink_webhook_secret_invalid"

    empty = client.post(
        f"/v1/integrations/fliplink/memorials/{slug}/webhook",
        headers={"x-memorial-fliplink-secret": "secret-123"},
        json={"publication_slug": "share-a-memory"},
    )
    assert empty.status_code == 422
    assert empty.headers.get("Cache-Control") == "no-store"
    assert empty.headers.get("Referrer-Policy") == "no-referrer"
    assert empty.headers.get("X-Content-Type-Options") == "nosniff"
    assert empty.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert _error_code(empty) == "memorial_contribution_signal_required"


def test_memorial_fliplink_webhook_content_length_guard_is_controlled() -> None:
    from app.api.routes.fliplink_integration import _content_length

    request = Request(
        {
            "type": "http",
            "headers": [(b"content-length", b"not-a-number")],
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        _content_length(request, invalid_detail="invalid_memorial_fliplink_webhook_content_length")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid_memorial_fliplink_webhook_content_length"


def test_public_memorial_page_does_not_emit_dead_client_identity_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-html")
    response = client.get(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    assert "x-memorial-visitor-id" not in response.text
    assert "visitor_id:" not in response.text
    assert "memorial_guest_visitor_id_v1" not in response.text


def test_public_memorial_page_keeps_archive_and_voice_feedback_collapsed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    registry_root = tmp_path / "public_registry" / slug
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "archive_registry.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "archive_sections": [
                    {"title": "Oeffentliches Archiv", "audience": "public", "items": ["doc-public"]},
                ],
                "fliplink_publications": [
                    {
                        "id": "doc-public",
                        "title": "Public Doc",
                        "audience": "public",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/public",
                        "description": "Visible",
                        "sensitivity": "PUBLIC",
                        "review_status": "approved",
                        "version": "2026-06-06",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    client = _client(principal_id="exec-memorial-minimal-html")
    response = client.get(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    body = response.text
    assert '<details class="hero-settings minimal-disclosure">' not in body
    assert '<summary class="collapse-summary">Optionen</summary>' not in body
    assert 'id="memorial-voice-ab-wrap"' not in body
    assert "Stimmvergleich und Feedback" not in body
    assert '<div class="voice-ab-choice-grid">' not in body
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" not in body
    assert '<section id="memorial-archive">' not in body
    assert '<summary class="collapse-summary">Archiv lesen</summary>' not in body
    assert "Originalaufnahmen" not in body
    assert "Belegte Erinnerungen" not in body
    assert 'id="memorial-voice-config-form"' not in body
    assert 'id="memorial-chat-answer"' in body
    assert 'id="memorial-speech-transcript-live"' in body
    assert 'id="memorial-speech-transcript"' in body
    assert 'id="memorial-voice-recovery-note"' in body
    assert "Wenn die Stimme stockt, bleibt die Antwort als Text sichtbar." in body
    assert "Du kannst ruhig unterbrechen oder noch einmal sprechen." in body
    assert "Gespräch beginnen" in body
    assert "Am Handy/Desktop installieren" in body
    assert "Tippen, sprechen, kurz warten, einfach weiterreden." not in body
    assert "Bitte noch einmal sprechen" in body


def test_public_memorial_page_exposes_conversation_settings_and_memory_consent_controls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-settings")
    response = client.get(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    body = response.text
    assert "Gesprächseinstellungen" in body
    assert 'id="memorial-autostart-optin"' in body
    assert 'id="memorial-personal-memory-optin"' in body
    assert 'id="memorial-personal-memory-status"' in body
    assert 'id="memorial-personal-memory-forget"' in body
    assert 'id="memorial-personal-memory-forget" disabled aria-disabled="true"' in body
    assert "pseudonym auf unserem Server gespeichert" in body
    assert "Mit diesem Browser verknüpfen" in body
    assert "Gesprächsgedächtnis löschen" in body
    assert "Persönliche Gesprächserinnerungen bleiben nur in diesem Browser" not in body
    assert "Nur dieses Gerät merkt sich etwas" not in body
    assert 'href="/security"' not in body
    assert 'href="/data-deletion"' not in body
    assert 'href="#memorial-contribution-management"' in body
    assert "Private Einreichungen und ihre Rücknahmebelege" in body
    assert "Es gibt noch kein Gesprächsgedächtnis zu löschen" in body
    assert "KI-gestützten, synthetischen Manfred-Stimme" in body
    assert "eingesetzte Sprachdienste verarbeiten das Audio" in body
    assert 'href="#memorial-conversation-region">Zum Gespräch mit Manfred Hoza</a>' in body
    assert "/memorials/manfred/realtime" in body
    assert "/memorials/manfred/realtime/webrtc" not in body
    assert "RTCPeerConnection" not in body
    assert "gemini_live_websocket_pcm" in body
    assert "audio/pcm;rate=16000" in body
    assert "openai" not in body.lower()
    assert "ensureRealtimeSocket" in body
    assert "user_audio_start" in body
    assert "user_audio_end" in body
    assert "personal_memory_enabled: true" not in body
    assert "personal_memory_enabled: personalMemoryEnabled()" in body
    assert 'params.set("personal_memory", personalMemoryEnabled() ? "1" : "0")' in body
    assert 'conversationButton.setAttribute("aria-label", label)' in body
    assert 'conversationButton.setAttribute("title", label)' in body
    assert 'id="memorial-text-turn-form"' in body
    assert 'for="memorial-text-turn-input">Oder ohne Mikrofon schreiben</label>' in body
    assert 'type: "user_text_turn"' in body
    assert "setMicrophoneFailureStatus" in body
    assert "Der Mikrofonzugriff ist blockiert." in body
    assert 'id="memorial-speech-transcript" role="log" aria-label="Gesprächsverlauf"' in body
    assert 'aria-controls="memorial-chat-status" aria-expanded="false"' in body
    assert 'behavior: memorialReducedMotionQuery.matches ? "auto" : "smooth"' in body
    assert 'id="memorial-contribution-form"' in body
    assert "Eine Erinnerung beitragen" in body
    assert "bleibt zunächst privat" in body
    assert 'id="memorial-contribution-consent"' in body
    assert 'id="memorial-contribution-management-jump" hidden' in body
    assert 'id="memorial-contribution-management"' in body
    assert 'data-js-ready="false"' in body
    assert "Rücknahmebeleg sicher aufbewahren" in body
    assert 'id="memorial-contribution-token"' not in body
    assert "/memorials/manfred/conversation-turn" not in body
    assert ".contribution-management-section dd" in body
    assert "overflow-wrap: anywhere;" in body
    assert ".hero-cta:not([disabled]):hover" in body
    assert "min-height: 100dvh;" in body
    assert "position: fixed;" in body
    assert "overflow: hidden;" in body
    assert "<h2>Archiv lesen</h2>" not in body
    assert "<h2>Stimmvergleich</h2>" not in body


def test_public_memorial_personal_memory_status_is_guest_safe_without_cookie(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-memory-guest")
    response = client.get(
        f"/memorials/{slug}/personal-memory",
        headers={"host": "myexternalbrain.com", "x-memorial-personal-memory": "1"},
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json() == {
        "available": False,
        "enabled": False,
        "guest_mode": True,
        "has_login": False,
        "item_count": 0,
        "frozen": False,
        "approved_voice_choice": "",
    }


def test_public_memorial_personal_memory_status_and_forget_work_while_opted_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    from app.api.routes import public_memorials

    visitor_id = "visitor-42"
    scope = public_memorials._memorial_guest_scope(visitor_id)
    public_memorials._save_personal_memory_store(
        slug=slug,
        scope=scope,
        payload={
            "items": [
                {"kind": "preference", "title": "Kurz und direkt", "summary": "Bevorzugt knappe Antworten."},
                {"kind": "voice", "title": "Variante B", "summary": "Die zweite Stimme wirkt vertrauter."},
            ],
            "frozen": True,
            "approved_voice_choice": "b",
        },
    )

    client = _client(principal_id="exec-memorial-memory-reset")
    client.cookies.set(
        public_memorials._MEMORIAL_GUEST_COOKIE,
        public_memorials._sign_memorial_guest_value(visitor_id),
        path=f"/memorials/{slug}",
    )

    status_response = client.get(
        f"/memorials/{slug}/personal-memory",
        headers={"host": "myexternalbrain.com", "x-memorial-personal-memory": "1"},
    )

    assert status_response.status_code == 200
    assert status_response.headers.get("Cache-Control") == "no-store"
    assert status_response.headers.get("Referrer-Policy") == "no-referrer"
    assert status_response.headers.get("X-Content-Type-Options") == "nosniff"
    assert status_response.json() == {
        "available": True,
        "enabled": True,
        "guest_mode": True,
        "has_login": False,
        "item_count": 2,
        "frozen": True,
        "approved_voice_choice": "b",
    }

    forget_response = client.delete(
        f"/memorials/{slug}/personal-memory",
        headers={"host": "myexternalbrain.com", "x-memorial-personal-memory": "0"},
    )

    assert forget_response.status_code == 200
    assert forget_response.headers.get("Cache-Control") == "no-store"
    assert forget_response.headers.get("Referrer-Policy") == "no-referrer"
    assert forget_response.headers.get("X-Content-Type-Options") == "nosniff"
    assert forget_response.json() == {
        "status": "forgotten",
        "available": True,
        "enabled": False,
        "guest_mode": True,
        "has_login": False,
        "item_count": 0,
        "frozen": False,
        "approved_voice_choice": "",
    }


def test_public_memorial_page_issues_and_preserves_signed_guest_cookie(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)
    monkeypatch.setenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR", "0")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    from app.api.routes import public_memorials

    client = _client(principal_id="exec-memorial-cookie")
    response = client.get(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert public_memorials._MEMORIAL_GUEST_COOKIE in set_cookie
    assert f"Path=/memorials/{slug}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert "Max-Age=31536000" in set_cookie
    assert "Secure" not in set_cookie
    assert "Strict-Transport-Security" not in response.headers

    issued = client.cookies.get(public_memorials._MEMORIAL_GUEST_COOKIE)
    assert issued
    issued_visitor = public_memorials._verified_memorial_guest_cookie_value(issued)
    assert issued_visitor
    assert response.headers.get("Cache-Control") == "no-store, max-age=0"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    assert response.headers.get("Permissions-Policy") == "microphone=(self), camera=(), geolocation=(), interest-cohort=()"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"

    second = client.head(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})
    assert second.status_code == 200
    preserved = client.cookies.get(public_memorials._MEMORIAL_GUEST_COOKIE)
    assert preserved
    assert public_memorials._verified_memorial_guest_cookie_value(preserved) == issued_visitor
    assert second.headers.get("Cache-Control") == "no-store, max-age=0"
    assert second.headers.get("Referrer-Policy") == "no-referrer"
    assert second.headers.get("X-Content-Type-Options") == "nosniff"
    assert second.headers.get("X-Frame-Options") == "DENY"
    assert second.headers.get("Content-Security-Policy") == "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    assert second.headers.get("Permissions-Policy") == "microphone=(self), camera=(), geolocation=(), interest-cohort=()"
    assert second.headers.get("X-Robots-Tag") == "noindex, nofollow"


def _configured_transport_memorial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> TestClient:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR", "0")
    public_root = tmp_path / "public"
    _write_public_memorial(
        public_root,
        "manfred",
        {
            "slug": "manfred",
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    return _client(principal_id="exec-memorial-transport")


def test_public_memorial_direct_https_sets_secure_cookie_and_hsts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)

    response = client.get(
        "https://myexternalbrain.com/memorials/manfred",
        headers={"forwarded": 'for=192.0.2.10;proto="not-a-scheme"'},
    )

    assert response.status_code == 200
    assert "Secure" in response.headers.get("set-cookie", "")
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000"


@pytest.mark.parametrize(
    "proxy_headers",
    [
        {"x-forwarded-proto": "https"},
        {"x-forwarded-proto": "https", "x-forwarded-host": "myexternalbrain.com"},
        {"forwarded": "for=192.0.2.10;proto=https"},
        {"forwarded": "for=192.0.2.10;proto=https;host=myexternalbrain.com"},
        {"cf-visitor": '{"scheme":"https"}'},
        {
            "x-forwarded-proto": "https",
            "forwarded": "for=192.0.2.10;proto=https",
            "cf-visitor": '{"scheme":"https"}',
        },
    ],
)
def test_public_memorial_configured_host_accepts_https_proxy_scheme_without_global_trust(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    proxy_headers: dict[str, str],
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)

    response = client.get(
        "/memorials/manfred",
        headers={"host": "myexternalbrain.com", **proxy_headers},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Secure" in response.headers.get("set-cookie", "")
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000"
    assert "location" not in response.headers


@pytest.mark.parametrize(
    "request_host",
    [
        "unrelated.example",
        "myexternalbrain.com.unrelated.example",
        "unrelated.example@myexternalbrain.com",
    ],
)
def test_public_memorial_unrelated_host_fails_closed_before_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request_host: str,
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)

    response = client.get(
        "/memorials/manfred",
        headers={
            "host": request_host,
            "x-forwarded-proto": "https",
            "forwarded": "for=192.0.2.10;proto=https",
            "cf-visitor": '{"scheme":"https"}',
        },
        follow_redirects=False,
    )

    assert response.status_code == 421
    assert "set-cookie" not in response.headers
    assert "Strict-Transport-Security" not in response.headers
    assert "location" not in response.headers


@pytest.mark.parametrize(
    "proxy_headers",
    [
        {"x-forwarded-proto": "https", "x-forwarded-host": "unrelated.example"},
        {"forwarded": "for=192.0.2.10;proto=https;host=unrelated.example"},
    ],
)
def test_public_memorial_forwarded_host_disagreement_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    proxy_headers: dict[str, str],
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)

    response = client.get(
        "/memorials/manfred",
        headers={"host": "myexternalbrain.com", **proxy_headers},
        follow_redirects=False,
    )

    assert response.status_code == 421
    assert "set-cookie" not in response.headers
    assert "Strict-Transport-Security" not in response.headers
    assert "location" not in response.headers


def test_public_memorial_direct_https_rejects_forwarded_host_disagreement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)

    response = client.get(
        "https://myexternalbrain.com/memorials/manfred",
        headers={"x-forwarded-host": "unrelated.example", "x-forwarded-proto": "https"},
        follow_redirects=False,
    )

    assert response.status_code == 421
    assert "set-cookie" not in response.headers
    assert "Strict-Transport-Security" not in response.headers


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/memorials/manfred?next=https%3A%2F%2Funrelated.example"),
        ("HEAD", "/memorials/manfred?surface=head"),
        ("GET", "/memorials/manfred/archive?section=letters"),
        ("GET", "/memorials/manfred/archive/publication-one?view=reader"),
    ],
)
def test_public_memorial_configured_http_routes_redirect_to_exact_https_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    method: str,
    path: str,
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)

    response = client.request(
        method,
        path,
        headers={"host": "myexternalbrain.com"},
        follow_redirects=False,
    )

    assert response.status_code == 308
    assert response.headers["location"] == f"https://myexternalbrain.com{path}"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "malformed_headers",
    [
        {"x-forwarded-proto": "https,http"},
        {"forwarded": 'for=192.0.2.10;proto="https'},
        {"cf-visitor": "not-json"},
        {"x-forwarded-proto": "https", "cf-visitor": '{"scheme":"http"}'},
    ],
)
def test_public_memorial_malformed_proxy_scheme_is_rejected_without_redirect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformed_headers: dict[str, str],
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)

    response = client.get(
        "/memorials/manfred?source=malformed",
        headers={"host": "myexternalbrain.com", **malformed_headers},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "location" not in response.headers
    assert "set-cookie" not in response.headers


def test_public_memorial_isolated_candidate_loopback_is_explicit_and_header_strict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _configured_transport_memorial(monkeypatch, tmp_path)
    monkeypatch.setenv("EA_MANFRED_COMPOSE_PROJECT", "ea-manfred-candidate-security-proof")
    monkeypatch.setenv("EA_MANFRED_HOST_PORT", "18098")

    response = client.get(
        "/memorials/manfred",
        headers={"host": "127.0.0.1:18098"},
        follow_redirects=False,
    )
    malformed = client.get(
        "/memorials/manfred",
        headers={"host": "127.0.0.1:18098", "x-forwarded-proto": "https"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Secure" not in response.headers.get("set-cookie", "")
    assert "Strict-Transport-Security" not in response.headers
    assert malformed.status_code == 400
    assert "set-cookie" not in malformed.headers


def test_public_memorial_page_establishes_guest_scope_without_enabling_personal_memory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-cookie-scope")

    page = client.get(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})
    assert page.status_code == 200

    status_without_opt_in = client.get(
        f"/memorials/{slug}/personal-memory",
        headers={"host": "myexternalbrain.com"},
    )
    assert status_without_opt_in.status_code == 200
    assert status_without_opt_in.json() == {
        "available": True,
        "enabled": False,
        "guest_mode": True,
        "has_login": False,
        "item_count": 0,
        "frozen": False,
        "approved_voice_choice": "",
    }

    status_with_opt_in = client.get(
        f"/memorials/{slug}/personal-memory",
        headers={"host": "myexternalbrain.com", "x-memorial-personal-memory": "1"},
    )
    assert status_with_opt_in.status_code == 200
    assert status_with_opt_in.json() == {
        "available": True,
        "enabled": True,
        "guest_mode": True,
        "has_login": False,
        "item_count": 0,
        "frozen": False,
        "approved_voice_choice": "",
    }


def test_public_memorial_personal_memory_status_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-personal-memory-missing")
    response = client.get("/memorials/not-found/personal-memory")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_public_memorial_personal_memory_forget_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-personal-memory-forget-missing")
    response = client.delete("/memorials/not-found/personal-memory")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_public_memorial_page_marks_guest_cookie_secure_for_trusted_forwarded_https(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-cookie-secure")
    response = client.get(
        f"/memorials/{slug}",
        headers={
            "host": "myexternalbrain.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "Secure" in set_cookie


def test_public_memorial_page_missing_slug_uses_hardened_html_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-page-missing")
    response = client.get("/memorials/not-found")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store, max-age=0"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert '<html lang="de">' in response.text
    assert "Diese Seite ist gerade nicht erreichbar." in response.text
    assert "Erneut versuchen" in response.text
    assert "Zur Startseite" in response.text
    assert "memorial_not_found" not in response.text


def test_public_memorial_manifest_missing_slug_uses_hardened_json_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-manifest-missing")
    response = client.get("/memorials/not-found.json")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["detail"] == "memorial_not_found"


def test_public_memorial_head_missing_slug_uses_hardened_html_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-head-missing")
    response = client.head("/memorials/not-found")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store, max-age=0"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_public_memorial_archive_publication_missing_slug_uses_hardened_html_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-archive-slug-missing")
    response = client.get("/memorials/not-found/archive/anything", follow_redirects=False)

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store, max-age=0"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert "Diese Seite ist gerade nicht erreichbar." in response.text
    assert "memorial_not_found" not in response.text


def test_public_memorial_service_worker_missing_slug_uses_hardened_json_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-worker-missing")
    response = client.get("/memorials/not-found/service-worker.js")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["detail"] == "memorial_not_found"


def test_public_memorial_html_error_response_hides_private_detail_markup() -> None:
    from app.api.routes.public_memorial_surface import _public_surface_html_error_response

    response = _public_surface_html_error_response(404, '<script>alert("x")</script>')
    body = response.body.decode("utf-8")

    assert response.status_code == 404
    assert '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;' not in body
    assert '<script>alert("x")</script>' not in body
    assert "Private oder technische Details werden hier nicht angezeigt." in body


def test_public_memorial_archive_manifest_missing_slug_uses_hardened_json_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-archive-manifest-missing")
    response = client.get("/memorials/not-found/archive.json")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["detail"] == "memorial_not_found"


def test_public_memorial_webmanifest_missing_slug_uses_hardened_json_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-webmanifest-missing")
    response = client.get("/memorials/not-found/app.webmanifest")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["detail"] == "memorial_not_found"


def test_public_memorial_svg_icon_missing_slug_uses_hardened_json_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-svg-missing")
    response = client.get("/memorials/not-found/icon.svg")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["detail"] == "memorial_not_found"


def test_public_memorial_page_does_not_trust_forwarded_https_when_proxy_trust_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.delenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR", raising=False)
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-cookie-untrusted")
    response = client.get(
        f"/memorials/{slug}",
        headers={
            "host": "myexternalbrain.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "Secure" not in set_cookie


def test_public_memorial_archive_route_redirects_to_registry_url_when_local_build_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    publication_slug = "manfred-life-overview"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    registry_root = tmp_path / "public_registry" / slug
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "archive_registry.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "archive_sections": [
                    {"title": "Oeffentliches Archiv", "audience": "public", "items": [publication_slug]},
                ],
                "fliplink_publications": [
                    {
                        "id": publication_slug,
                        "slug": publication_slug,
                        "title": "Manfred: Ueberblick",
                        "audience": "public",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/manfred-life-overview",
                        "description": "Visible",
                        "sensitivity": "PUBLIC",
                        "review_status": "approved",
                        "version": "2026-06-06",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    client = _client(principal_id="exec-memorial-archive-redirect")
    response = client.get(f"/memorials/{slug}/archive/{publication_slug}", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://archive.example/manfred-life-overview"
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.headers.get("X-Frame-Options") is None


def test_public_memorial_archive_index_success_uses_hardened_html_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-archive-index-html")
    response = client.get(f"/memorials/{slug}/archive", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store, max-age=0"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    assert response.headers.get("Permissions-Policy") == "microphone=(self), camera=(), geolocation=(), interest-cohort=()"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_public_memorial_archive_publication_success_uses_hardened_html_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    publication_slug = "manfred-life-overview"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    html_path = tmp_path / "archive" / slug / "public" / publication_slug / "build" / "index.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<!doctype html><title>Archive</title><p>Local publication</p>", encoding="utf-8")

    client = _client(principal_id="exec-memorial-archive-publication-html")
    response = client.get(f"/memorials/{slug}/archive/{publication_slug}", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store, max-age=0"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    assert response.headers.get("Permissions-Policy") == "microphone=(self), camera=(), geolocation=(), interest-cohort=()"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert "Local publication" in response.text


def test_public_memorial_archive_publication_missing_uses_hardened_404_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-archive-missing")
    response = client.get(f"/memorials/{slug}/archive/not-there", follow_redirects=False)

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store, max-age=0"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert "Diese Seite ist gerade nicht erreichbar." in response.text
    assert "Erneut versuchen" in response.text
    assert "memorial_archive_publication_not_found" not in response.text


def test_public_speech_synthesize_rejects_client_voice_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "browser_speech_synthesis",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-05T16:25:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-tts")
    response = client.post(
        f"/memorials/{slug}/speech-synthesize",
        json={"text": "Test", "tts_plugin": "unmixr_clone", "tts_plugin_voice_id": "evil"},
    )

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "unsupported_public_tts_fields"


def test_public_voice_ab_payload_hides_raw_voice_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_MEMORIAL_MANFRED_VOICE_A_ID", "voice-a-private")
    monkeypatch.setenv("EA_MEMORIAL_MANFRED_VOICE_B_ID", "voice-b-private")
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-ab")
    response = client.get(f"/memorials/{slug}/voice-ab")

    assert response.status_code == 200
    body = response.json()
    assert all(set(item.keys()) <= {"id", "label", "description"} for item in body["variants"])
    assert "voice-a-private" not in json.dumps(body)
    assert "voice-b-private" not in json.dumps(body)
    assert [item["id"] for item in body["dimension_spec"]] == [
        "identity",
        "intelligibility",
        "naturalness",
        "warmth",
        "authority",
        "artifact_control",
    ]
    assert set(body["analysis"].keys()) >= {
        "target_profile",
        "target_profile_summary",
        "weak_dimensions",
        "weak_dimension_labels",
        "hypothesis",
        "sample_size",
        "current_round_dimension_average",
        "candidates",
    }
    assert set(body["pool"].keys()) == {
        "needs_new_clone",
        "remaining_challenger_count",
        "current_index",
        "retired_voice_count",
        "pending_external_delete_count",
        "last_clone_error",
        "active",
        "next_challenger",
    }


def test_public_voice_ab_falls_back_to_private_profile_root_when_artifact_root_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)
    profile_dir = private_root / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "voice_ab.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "variants": [
                    {"id": "a", "label": "A", "tts_plugin": "unmixr_clone", "tts_plugin_voice_id": "private-a"},
                    {"id": "b", "label": "B", "tts_plugin": "unmixr_clone", "tts_plugin_voice_id": "private-b"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (profile_dir / "voice_ab_challengers.json").write_text(
        json.dumps(
                {
                    "slug": slug,
                    "champion_voice_id": "private-a",
                    "challengers": [{"voice_id": "private-c", "label": "C"}],
                },
                ensure_ascii=False,
            ),
        encoding="utf-8",
    )

    client = _client(principal_id="exec-memorial-private-voice-ab")
    response = client.get(f"/memorials/{slug}/voice-ab")

    assert response.status_code == 200
    body = response.json()
    assert body["pool"]["remaining_challenger_count"] == 1


def test_public_voice_ab_approval_requires_personal_memory_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-approval")
    response = client.post(f"/memorials/{slug}/voice-ab/rate", json={"choice": "a", "approved_variant": "a"})

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "personal_memory_required_for_voice_approval"


def test_public_voice_ab_totals_are_scope_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-dedupe")
    page = client.get(f"/memorials/{slug}")
    assert page.status_code == 200

    assert client.post(f"/memorials/{slug}/voice-ab/rate", json={"choice": "a"}).status_code == 200
    assert client.post(f"/memorials/{slug}/voice-ab/rate", json={"choice": "b"}).status_code == 200

    body = client.get(f"/memorials/{slug}/voice-ab").json()
    assert body["totals"] == {"a": 0, "b": 1, "equal": 0, "approved": 0}
    assert body["raw_totals"] == {"a": 1, "b": 1, "equal": 0, "approved": 0}
    assert body["round"] == 1


def test_public_voice_ab_rating_persists_dimension_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-dimensions")
    assert client.get(f"/memorials/{slug}").status_code == 200
    response = client.post(
        f"/memorials/{slug}/voice-ab/rate",
        json={
            "choice": "a",
            "dimensions": {
                "identity": 5,
                "intelligibility": 4,
                "naturalness": 3,
                "warmth": 2,
                "authority": 5,
                "artifact_control": 2,
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "analysis" in body

    stored = json.loads(((tmp_path / "artifacts" / "memorial_voice_ab" / slug / "ratings.json").read_text(encoding="utf-8")))
    assert stored["events"][0]["dimensions"]["identity"] == 5
    assert stored["events"][0]["dimensions"]["artifact_control"] == 2


def test_public_voice_ab_rating_persistence_is_minimized_and_pseudonymous(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.delenv("EA_MEMORIAL_VOICE_AB_EVENT_RETENTION_DAYS", raising=False)
    public_memorials._VOICE_AB_ROOT = tmp_path / "voice-ab"
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_ab_config",
        lambda _slug: {
            "variants": [
                {
                    "id": "a",
                    "label": "A",
                    "tts_plugin_voice_id": "PRIVATE_PROVIDER_VOICE_A",
                },
                {
                    "id": "b",
                    "label": "B",
                    "tts_plugin_voice_id": "PRIVATE_PROVIDER_VOICE_B",
                },
            ]
        },
    )

    public_memorials._record_voice_ab_rating(
        slug="manfred",
        context={"scope": "guest:PRIVATE_SCOPE", "guest_mode": True},
        choice="a",
        note="PRIVATE_FREE_TEXT_SENTINEL",
        dedupe_key="ip:203011310:scope:guest:PRIVATE_SCOPE",
        dimensions={"identity": 5, "artifact_control": 2},
    )
    public_memorials._record_voice_ab_rating(
        slug="manfred",
        context={"scope": "guest:PRIVATE_SCOPE", "guest_mode": True},
        choice="b",
        note="SECOND_PRIVATE_FREE_TEXT_SENTINEL",
        dedupe_key="ip:198511007:scope:guest:PRIVATE_SCOPE",
        dimensions={"identity": 4, "artifact_control": 5},
    )

    ratings_path = tmp_path / "voice-ab" / "manfred" / "ratings.json"
    stored = json.loads(ratings_path.read_text(encoding="utf-8"))
    assert len(stored["events"]) == 1
    event = stored["events"][0]
    serialized = json.dumps(stored, ensure_ascii=False)
    assert set(event) == {
        "dedupe_receipt",
        "choice",
        "approved_variant",
        "dimensions",
        "variant_snapshot",
        "created_at",
    }
    assert len(event["dedupe_receipt"]) == 64
    assert event["dedupe_receipt"] == public_memorials._voice_ab_private_receipt(
        "guest:PRIVATE_SCOPE",
        slug="manfred",
        domain="client",
    )
    assert event["choice"] == "b"
    assert event["dimensions"]["identity"] == 4
    assert stored["totals"] == {"a": 1, "b": 1, "equal": 0, "approved": 0}
    assert stored["effective_totals"] == {"a": 0, "b": 1, "equal": 0, "approved": 0}
    assert "dedupe_key" not in event
    assert "scope" not in event
    assert "guest_mode" not in event
    assert "note" not in event
    assert "PRIVATE_FREE_TEXT_SENTINEL" not in serialized
    assert "SECOND_PRIVATE_FREE_TEXT_SENTINEL" not in serialized
    assert "PRIVATE_SCOPE" not in serialized
    assert "203011310" not in serialized
    assert "198511007" not in serialized
    assert "PRIVATE_PROVIDER_VOICE" not in serialized
    assert stored["retention"] == {
        "current_vote_events_days": 30,
        "historical_rounds": "aggregate_receipts_only",
        "free_text_retained": False,
        "client_identity": "hmac_sha256_receipt",
    }


def test_public_voice_ab_load_prunes_expired_events_and_migrates_legacy_rounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.delenv("EA_MEMORIAL_VOICE_AB_EVENT_RETENTION_DAYS", raising=False)
    public_memorials._VOICE_AB_ROOT = tmp_path / "voice-ab"
    ratings_path = tmp_path / "voice-ab" / "manfred" / "ratings.json"
    ratings_path.parent.mkdir(parents=True)
    current_created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    ratings_path.write_text(
        json.dumps(
            {
                "slug": "manfred",
                "totals": {"a": 4, "b": 0, "equal": 0, "approved": 0},
                "events": [
                    {
                        "scope": "EXPIRED_PRIVATE_SCOPE",
                        "dedupe_key": "ip:192021:scope:EXPIRED_PRIVATE_SCOPE",
                        "note": "EXPIRED_PRIVATE_NOTE",
                        "choice": "a",
                        "created_at": "2020-01-01T00:00:00Z",
                    },
                    {
                        "scope": "CURRENT_PRIVATE_SCOPE",
                        "dedupe_key": "ip:203011310:scope:CURRENT_PRIVATE_SCOPE",
                        "guest_mode": True,
                        "note": "CURRENT_PRIVATE_NOTE",
                        "choice": "a",
                        "variant_snapshot": {
                            "a": {"id": "a", "voice_id": "PRIVATE_PROVIDER_VOICE_A"},
                        },
                        "created_at": current_created_at,
                    },
                    {
                        "scope": "MISSING_TIMESTAMP_PRIVATE_SCOPE",
                        "choice": "a",
                    },
                    {
                        "scope": "FUTURE_PRIVATE_SCOPE",
                        "choice": "a",
                        "created_at": "2099-01-01T00:00:00Z",
                    },
                ],
                "round": 2,
                "rounds": [
                    {
                        "round": 1,
                        "winner": "a",
                        "events": [
                            {
                                "scope": "HISTORICAL_PRIVATE_SCOPE",
                                "choice": "a",
                                "created_at": "2026-01-01T00:00:00Z",
                            }
                        ],
                        "analysis": {"voice_id": "PRIVATE_PROVIDER_VOICE_A"},
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = public_memorials._load_voice_ab_ratings("manfred")
    migrated = json.loads(ratings_path.read_text(encoding="utf-8"))
    serialized = json.dumps(migrated, ensure_ascii=False)

    assert len(loaded["events"]) == 1
    assert len(migrated["events"]) == 1
    assert loaded["events"][0]["created_at"] == current_created_at
    assert migrated["schema"] == "ea.memorial_voice_ab_ratings.v2"
    assert "events" not in migrated["rounds"][0]
    assert migrated["rounds"][0]["rating_receipt"]["event_count"] == 1
    assert migrated["rounds"][0]["rating_receipt"]["dimension_average"]["identity"] == 3.0
    assert migrated["rounds"][0]["rating_receipt"]["target_profile"]["identity"] == 3.0
    assert migrated["rounds"][0]["rating_receipt"]["dimension_stats"]["identity"] == {
        "sum": 3.0,
        "count": 1,
    }
    for marker in (
        "EXPIRED_PRIVATE_SCOPE",
        "EXPIRED_PRIVATE_NOTE",
        "CURRENT_PRIVATE_SCOPE",
        "CURRENT_PRIVATE_NOTE",
        "MISSING_TIMESTAMP_PRIVATE_SCOPE",
        "FUTURE_PRIVATE_SCOPE",
        "HISTORICAL_PRIVATE_SCOPE",
        "203011310",
        "PRIVATE_PROVIDER_VOICE_A",
    ):
        assert marker not in serialized


def test_voice_ab_receipts_are_stable_domain_and_slug_separated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._voice_ab_receipt_secret.cache_clear()
    monkeypatch.setattr(public_memorials, "get_settings", lambda: object())
    monkeypatch.setattr(
        public_memorials,
        "resolve_signing_secret",
        lambda _settings, *, purpose: f"stable-test-secret:{purpose}",
    )
    try:
        first = public_memorials._voice_ab_private_receipt(
            "shared-identity",
            slug="manfred",
            domain="client",
        )
        assert len(first) == 64
        assert int(first, 16) >= 0

        public_memorials._voice_ab_receipt_secret.cache_clear()
        restarted = public_memorials._voice_ab_private_receipt(
            "shared-identity",
            slug="manfred",
            domain="client",
        )
        voice_domain = public_memorials._voice_ab_private_receipt(
            "shared-identity",
            slug="manfred",
            domain="voice",
        )
        other_slug = public_memorials._voice_ab_private_receipt(
            "shared-identity",
            slug="another-memorial",
            domain="client",
        )

        assert restarted == first
        assert voice_domain != first
        assert other_slug != first
    finally:
        public_memorials._voice_ab_receipt_secret.cache_clear()


def test_voice_ab_receipt_secret_failure_prevents_rating_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._VOICE_AB_ROOT = tmp_path / "voice-ab"
    public_memorials._voice_ab_receipt_secret.cache_clear()
    monkeypatch.setattr(public_memorials, "get_settings", lambda: object())

    def _fail_secret(_settings, *, purpose: str) -> str:
        raise RuntimeError(f"secret unavailable:{purpose}")

    monkeypatch.setattr(public_memorials, "resolve_signing_secret", _fail_secret)
    monkeypatch.setattr(public_memorials, "_load_voice_ab_config", lambda _slug: {"variants": []})
    try:
        with pytest.raises(RuntimeError, match="secret unavailable"):
            public_memorials._record_voice_ab_rating(
                slug="manfred",
                context={"scope": "guest:stable"},
                choice="a",
            )
        assert not (tmp_path / "voice-ab" / "manfred" / "ratings.json").exists()
    finally:
        public_memorials._voice_ab_receipt_secret.cache_clear()


def test_voice_ab_load_canonically_scrubs_extra_fields_and_invalid_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.delenv("EA_MEMORIAL_VOICE_AB_EVENT_RETENTION_DAYS", raising=False)
    public_memorials._VOICE_AB_ROOT = tmp_path / "voice-ab"
    ratings_path = tmp_path / "voice-ab" / "manfred" / "ratings.json"
    ratings_path.parent.mkdir(parents=True)
    current_created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    ratings_path.write_text(
        json.dumps(
            {
                "schema": "ea.memorial_voice_ab_ratings.v2",
                "slug": "manfred",
                "totals": {"a": 1, "b": 0, "equal": 0, "approved": 0},
                "effective_totals": {"a": 1, "b": 0, "equal": 0, "approved": 0},
                "events": [
                    {
                        "dedupe_receipt": "PLAINTEXT_CLIENT_RECEIPT",
                        "choice": "a",
                        "approved_variant": "",
                        "dimensions": {"identity": 5},
                        "variant_snapshot": {
                            "a": {
                                "id": "a",
                                "voice_receipt": "PLAINTEXT_PROVIDER_RECEIPT",
                                "private_snapshot_extra": "PRIVATE_SNAPSHOT_EXTRA",
                            }
                        },
                        "created_at": current_created_at,
                        "private_event_extra": "PRIVATE_EVENT_EXTRA",
                    }
                ],
                "round": 1,
                "rounds": [
                    {
                        "round": 1,
                        "winner": "a",
                        "private_round_extra": "PRIVATE_ROUND_EXTRA",
                    }
                ],
                "retention": {
                    "current_vote_events_days": 30,
                    "historical_rounds": "aggregate_receipts_only",
                    "free_text_retained": False,
                    "client_identity": "hmac_sha256_receipt",
                },
                "private_top_level_extra": "PRIVATE_TOP_LEVEL_EXTRA",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = public_memorials._load_voice_ab_ratings("manfred")
    first_canonical_bytes = ratings_path.read_bytes()
    canonical = json.loads(first_canonical_bytes)
    public_memorials._load_voice_ab_ratings("manfred")

    assert len(loaded["events"]) == 1
    assert ratings_path.read_bytes() == first_canonical_bytes
    serialized = json.dumps(canonical, ensure_ascii=False)
    assert "PRIVATE_" not in serialized
    event = canonical["events"][0]
    assert public_memorials._voice_ab_receipt_is_valid(event["dedupe_receipt"])
    assert public_memorials._voice_ab_receipt_is_valid(
        event["variant_snapshot"]["a"]["voice_receipt"]
    )
    assert event["dedupe_receipt"] != "PLAINTEXT_CLIENT_RECEIPT"
    assert event["variant_snapshot"]["a"]["voice_receipt"] != "PLAINTEXT_PROVIDER_RECEIPT"


def test_voice_ab_corrupt_ratings_fail_closed_without_overwrite(
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._VOICE_AB_ROOT = tmp_path / "voice-ab"
    ratings_path = tmp_path / "voice-ab" / "manfred" / "ratings.json"
    ratings_path.parent.mkdir(parents=True)
    corrupt = b'{"events": [not-json]}'
    ratings_path.write_bytes(corrupt)

    with pytest.raises(HTTPException) as exc_info:
        public_memorials._load_voice_ab_ratings("manfred")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "memorial_voice_ab_ratings_invalid"
    assert ratings_path.read_bytes() == corrupt


def test_voice_ab_round_aggregates_are_round_local_and_dimension_weighted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_load_voice_ab_config", lambda _slug: {"variants": []})

    def _event(receipt: str, score: int) -> dict[str, object]:
        return {
            "dedupe_receipt": receipt,
            "choice": "a",
            "approved_variant": "",
            "dimensions": {key: score for key in public_memorials._VOICE_AB_DIMENSION_KEYS},
            "variant_snapshot": {},
            "created_at": "2026-07-11T00:00:00Z",
        }

    high = public_memorials._voice_ab_round_receipt_from_events([_event("a" * 64, 5)])
    low = public_memorials._voice_ab_round_receipt_from_events([_event("b" * 64, 1)])
    analysis = public_memorials._voice_ab_analysis(
        "manfred",
        {"events": [], "rounds": [{"rating_receipt": high}, {"rating_receipt": low}]},
    )
    assert analysis["target_profile"]["identity"] == 3.0

    zero_signal = {
        "schema": "ea.memorial_voice_ab_round_receipt.v1",
        "event_count": 9,
        "dimension_average": {key: 0 for key in public_memorials._VOICE_AB_DIMENSION_KEYS},
        "target_profile": {key: 0 for key in public_memorials._VOICE_AB_DIMENSION_KEYS},
        "dimension_stats": {
            key: {"sum": 0, "count": 0}
            for key in public_memorials._VOICE_AB_DIMENSION_KEYS
        },
    }
    undiluted = public_memorials._voice_ab_analysis(
        "manfred",
        {"events": [], "rounds": [{"rating_receipt": high}, {"rating_receipt": zero_signal}]},
    )
    assert undiluted["target_profile"]["identity"] == 5.0

    migrated = public_memorials._voice_ab_minimized_round(
        {
            "round": 1,
            "events": [_event("c" * 64, 3)],
            "created_at": "2026-01-01T00:00:00Z",
        },
        slug="manfred",
        trusted_receipts=True,
    )
    assert migrated["rating_receipt"]["dimension_average"]["identity"] == 3.0
    assert migrated["rating_receipt"]["target_profile"]["identity"] == 3.0


def test_voice_ab_storage_keeps_only_latest_event_per_receipt_before_capping(
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._VOICE_AB_ROOT = tmp_path / "voice-ab"
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    events = [
        {
            "dedupe_receipt": f"{index:064x}",
            "choice": "a",
            "dimensions": {"identity": 1},
            "variant_snapshot": {},
            "created_at": created_at,
        }
        for index in range(40)
    ]
    events.append(
        {
            "dedupe_receipt": f"{20:064x}",
            "choice": "b",
            "dimensions": {"identity": 5},
            "variant_snapshot": {},
            "created_at": created_at,
        }
    )

    public_memorials._save_voice_ab_ratings(
        "manfred",
        {
            "slug": "manfred",
            "totals": {"a": 40, "b": 1, "equal": 0, "approved": 0},
            "events": events,
            "round": 1,
            "rounds": [],
        },
    )
    stored = json.loads(
        (tmp_path / "voice-ab" / "manfred" / "ratings.json").read_text(encoding="utf-8")
    )

    assert len(stored["events"]) == 40
    assert f"{0:064x}" in {event["dedupe_receipt"] for event in stored["events"]}
    updated = next(event for event in stored["events"] if event["dedupe_receipt"] == f"{20:064x}")
    assert updated["choice"] == "b"
    assert updated["dimensions"]["identity"] == 5
    assert stored["effective_totals"] == {"a": 39, "b": 1, "equal": 0, "approved": 0}


def test_public_voice_ab_auto_rotates_challenger_after_effective_margin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_MEMORIAL_MANFRED_VOICE_B_ID", "provider-test-challenger-v2")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    voice_ab_root = tmp_path / "artifacts" / "memorial_voice_ab" / slug
    voice_ab_root.mkdir(parents=True, exist_ok=True)
    (voice_ab_root / "voice_ab.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "variants": [
                    {
                        "id": "a",
                        "label": "Stimme A · klarer",
                        "tts_plugin": "unmixr_clone",
                        "tts_plugin_voice_id": "provider-test-champion-a",
                        "description": "Champion",
                    },
                    {
                        "id": "b",
                        "label": "Stimme B · challenger",
                        "tts_plugin": "unmixr_clone",
                        "tts_plugin_voice_id": "provider-test-challenger-old",
                        "description": "Old challenger",
                    },
                ],
                "sample_text": "Test",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for idx in range(4):
        client = _client(principal_id=f"exec-memorial-voice-rotate-{idx}")
        page = client.get(f"/memorials/{slug}")
        assert page.status_code == 200
        response = client.post(f"/memorials/{slug}/voice-ab/rate", json={"choice": "a"})
        assert response.status_code == 200

    client = _client(principal_id="exec-memorial-voice-rotate-check")
    body = client.get(f"/memorials/{slug}/voice-ab").json()
    assert body["totals"] == {"a": 0, "b": 0, "equal": 0, "approved": 0}
    assert body["round"] == 2

    stored_config = json.loads((voice_ab_root / "voice_ab.json").read_text(encoding="utf-8"))
    variant_b = next(item for item in stored_config["variants"] if item["id"] == "b")
    assert variant_b["tts_plugin_voice_id"] == "provider-test-challenger-v2"

    stored_ratings = json.loads((voice_ab_root / "ratings.json").read_text(encoding="utf-8"))
    assert stored_ratings["round"] == 2
    assert stored_ratings["rounds"][0]["winner"] == "a"
    assert "events" not in stored_ratings["rounds"][0]
    assert stored_ratings["rounds"][0]["rating_receipt"]["schema"] == "ea.memorial_voice_ab_round_receipt.v1"
    assert "dimension_stats" in stored_ratings["rounds"][0]["rating_receipt"]
    assert "retirement" not in stored_ratings["rounds"][0]
    retirement_receipt = stored_ratings["rounds"][0]["retirement_receipt"]
    assert retirement_receipt["schema"] == "ea.memorial_voice_ab_retirement_receipt.v1"
    assert retirement_receipt["provider"] == "unmixr"
    assert retirement_receipt["action"] == "delete_clone_profile"
    assert len(retirement_receipt["voice_receipt"]) == 64
    assert "provider-test-challenger-old" not in json.dumps(stored_ratings)
    assert "provider-test-challenger-v2" not in json.dumps(stored_ratings)


def test_voice_ab_auto_rotation_b_winner_retires_original_a_and_keeps_sanitized_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._VOICE_AB_ROOT = tmp_path / "voice-ab"
    config = {
        "slug": "manfred",
        "variants": [
            {
                "id": "a",
                "label": "A",
                "tts_plugin": "unmixr_clone",
                "tts_plugin_voice_id": "provider-original-a",
            },
            {
                "id": "b",
                "label": "B",
                "tts_plugin": "unmixr_clone",
                "tts_plugin_voice_id": "provider-winning-b",
            },
        ],
    }
    saved_configs: list[dict[str, object]] = []
    retired_voice_ids: list[str] = []
    monkeypatch.setattr(public_memorials, "_load_voice_ab_config", lambda _slug: config)
    monkeypatch.setattr(
        public_memorials,
        "_save_voice_ab_config",
        lambda _slug, payload: saved_configs.append(json.loads(json.dumps(payload))),
    )
    monkeypatch.setattr(
        public_memorials,
        "_voice_ab_next_challenger",
        lambda _slug, *, excluded_voice_ids: {
            "voice_id": "provider-new-challenger",
            "tts_plugin": "unmixr_clone",
            "label": "New challenger",
        },
    )

    def _retire(_slug: str, *, voice_id: str) -> dict[str, object]:
        retired_voice_ids.append(voice_id)
        return {
            "voice_id": voice_id,
            "profile_id": "profile-original-a",
            "retired_at": "2026-07-11T00:05:00Z",
            "delete_status": "deleted",
            "error": "",
        }

    monkeypatch.setattr(public_memorials, "_voice_ab_retire_losing_challenger", _retire)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    ratings = {
        "slug": "manfred",
        "totals": {"a": 0, "b": 4, "equal": 0, "approved": 0},
        "effective_totals": {"a": 0, "b": 4, "equal": 0, "approved": 0},
        "events": [
            {
                "dedupe_receipt": f"{index + 1:064x}",
                "choice": "b",
                "approved_variant": "",
                "dimensions": {"identity": 4},
                "variant_snapshot": {},
                "created_at": created_at,
            }
            for index in range(4)
        ],
        "round": 1,
        "rounds": [],
    }

    rotated = public_memorials._maybe_rotate_voice_ab_challenger("manfred", ratings)

    assert retired_voice_ids == ["provider-original-a"]
    assert rotated["round"] == 2
    assert saved_configs
    saved_variants = {item["id"]: item for item in saved_configs[-1]["variants"]}
    assert saved_variants["a"]["tts_plugin_voice_id"] == "provider-winning-b"
    assert saved_variants["b"]["tts_plugin_voice_id"] == "provider-new-challenger"

    stored = json.loads(
        (tmp_path / "voice-ab" / "manfred" / "ratings.json").read_text(encoding="utf-8")
    )
    round_entry = stored["rounds"][0]
    retirement_receipt = round_entry["retirement_receipt"]
    assert round_entry["winner"] == "b"
    assert retirement_receipt == {
        "schema": "ea.memorial_voice_ab_retirement_receipt.v1",
        "provider": "unmixr",
        "action": "delete_clone_profile",
        "voice_receipt": public_memorials._voice_ab_private_receipt(
            "provider-original-a",
            slug="manfred",
            domain="voice",
        ),
        "profile_receipt": public_memorials._voice_ab_private_receipt(
            "profile-original-a",
            slug="manfred",
            domain="provider-profile",
        ),
        "recorded_at": "2026-07-11T00:05:00Z",
        "status_at_rotation": "deleted",
        "retry_required": False,
        "error_code": "none",
    }
    serialized = json.dumps(stored)
    assert "provider-original-a" not in serialized
    assert "profile-original-a" not in serialized
    assert "provider-winning-b" not in serialized
    assert "provider-new-challenger" not in serialized


def test_voice_ab_manual_finalize_does_not_retire_voice_without_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_load_voice_ab_config",
        lambda _slug: {
            "variants": [
                {"id": "a", "tts_plugin_voice_id": "provider-a"},
                {"id": "b", "tts_plugin_voice_id": "provider-b"},
            ]
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_voice_ab_next_challenger",
        lambda _slug, *, excluded_voice_ids: None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_voice_ab_auto_build_challenger",
        lambda _slug, *, excluded_voice_ids: None,
    )
    retired: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_voice_ab_retire_losing_challenger",
        lambda _slug, *, voice_id: retired.append(voice_id),
    )
    ratings = {
        "totals": {"a": 1, "b": 0, "equal": 0, "approved": 0},
        "effective_totals": {"a": 1, "b": 0, "equal": 0, "approved": 0},
        "events": [],
        "round": 1,
        "rounds": [],
    }

    with pytest.raises(HTTPException) as exc_info:
        public_memorials._voice_ab_finalize_winner("manfred", winner="a", ratings=ratings)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "voice_ab_no_replacement_challenger"
    assert retired == []


def test_public_voice_ab_admin_requires_write_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-admin")
    response = client.get(f"/memorials/{slug}/voice-ab-admin")

    assert response.status_code in {403, 503}


def test_public_memorial_voice_ab_admin_maintain_oversized_payload_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-admin-oversized")
    response = client.post(
        f"/memorials/{slug}/voice-ab-admin/maintain",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={"note": "x" * 100_000},
    )

    assert response.status_code == 413
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "request_payload_too_large"


def test_public_memorial_voice_profile_build_without_sources_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_mode": "browser_speech_synthesis",
            "voice_consent": {
                "status": "approved",
                "scope": ["profile_build", "clone", "synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-05T16:25:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-profile-no-source")
    response = client.post(
        f"/memorials/{slug}/voice-profile/build",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={},
    )

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "voice_profile_no_source"


def test_public_memorial_voice_clone_without_samples_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_mode": "browser_speech_synthesis",
            "voice_consent": {
                "status": "approved",
                "scope": ["profile_build", "clone", "synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-05T16:25:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-clone-no-samples")
    response = client.post(
        f"/memorials/{slug}/voice-clone",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={"voice_label": "Test"},
    )

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "voice_profile_no_samples"


def test_public_memorial_operator_write_routes_are_disabled_without_operator_surface_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.delenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", raising=False)
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    profile_dir = private_root / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "tts_voice.json").write_text(
        json.dumps(
            {
                "tts_mode": "browser_speech_synthesis",
                "voice_consent": {
                    "status": "approved",
                    "scope": ["profile_build", "clone", "synthesize", "conversation_turn", "realtime"],
                    "authorized_by": "test-family",
                    "authorized_at": "2026-06-05T16:25:00Z",
                    "source_assets_reviewed": True,
                    "revoked": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-operator-disabled")
    headers = {"x-memorial-write-token": "unit-write-token"}

    checks = [
        client.post(f"/memorials/{slug}/voice-config", headers=headers, json={"voice_label": "Nope"}),
        client.post(f"/memorials/{slug}/voice-profile/build", headers=headers, json={"youtube_query": "Manfred"}),
        client.post(f"/memorials/{slug}/voice-ab-admin/finalize", headers=headers, json={"winner_variant": "a"}),
        client.get(f"/memorials/{slug}/voice-ab-admin", headers=headers),
        client.post(f"/memorials/{slug}/voice-ab-admin/maintain", headers=headers, json={}),
        client.post(f"/memorials/{slug}/voice-clone", headers=headers, json={"voice_label": "Nope"}),
        client.post(
            f"/memorials/{slug}/contributions/dummy-contribution/reject",
            headers=headers,
            json={"reviewer": "Nope", "reason": "Nope"},
        ),
        client.post(
            f"/memorials/{slug}/contributions/dummy-contribution/unpublish",
            headers=headers,
            json={"reviewer": "Nope", "reason": "Nope"},
        ),
    ]

    assert [response.status_code for response in checks] == [
        404,
        404,
        404,
        404,
        404,
        404,
        404,
        404,
    ]
    assert all("memorial_operator_surface_disabled" in response.text for response in checks)


def test_public_memorial_operator_status_requires_operator_surface_and_write_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-operator-status-auth")
    unauthorized = client.get(f"/memorials/{slug}/operator-status")
    authorized = client.get(
        f"/memorials/{slug}/operator-status",
        headers={"x-memorial-write-token": "unit-write-token"},
    )

    assert unauthorized.status_code == 403
    assert unauthorized.headers.get("Cache-Control") == "no-store"
    assert unauthorized.headers.get("Referrer-Policy") == "no-referrer"
    assert unauthorized.headers.get("X-Content-Type-Options") == "nosniff"
    assert unauthorized.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert unauthorized.json()["error"]["code"] == "memorial_write_unauthorized"
    assert authorized.status_code in {200, 503}


def test_public_memorial_operator_status_route_returns_current_generated_card(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    monkeypatch.delenv("EA_MEMORIAL_VOICE_AB_EVENT_RETENTION_DAYS", raising=False)
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    from app.api.routes import public_memorials

    operator_status = tmp_path / "MEMORIAL_OPERATOR_STATUS.generated.json"
    operator_status.write_text(
        json.dumps(
            {
                "current_label": "Memorial public-origin gold: blocked",
                "status": "blocked",
                "local_release_candidate": "pass",
                "public_voice_receipt": "pass",
                "public_browser_receipt": "pass",
                "room_audio_receipt": "missing_or_blocked",
                "room_audio_receipt_detail": {
                    "status": "fail",
                    "receipt_path": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
                    "failed_codes": [
                        "normal_spoken_turn_confirmed_missing",
                        "interruption_behavior_confirmed_missing",
                    ],
                    "missing_check_ids": [
                        "normal_spoken_turn_confirmed",
                        "interruption_behavior_confirmed",
                    ],
                    "missing_checks": [
                        {
                            "id": "normal_spoken_turn_confirmed",
                            "requirement": "A normal spoken question completed as microphone capture, STT, answer, TTS, and playback.",
                        },
                        {
                            "id": "interruption_behavior_confirmed",
                            "requirement": "Intentional interruption or barge-in behavior was observed and was not harsh or confusing.",
                        },
                    ],
                    "next_action": "collect_real_room_audio_attestation",
                },
                "workflow_backing": {"status": "no"},
                "source_worktree_dirty": True,
                "source_dirty_count": 2,
                "source_dirty_verifier": {
                    "contract_name": "ea.source_dirty_groups_verifier.v1",
                    "status": "pass",
                    "issues": [],
                    "source_dirty_count": 2,
                    "category_count": 2,
                },
                "source_cleanup": {
                    "status": "blocked",
                    "source_worktree_dirty": True,
                    "source_dirty_count": 2,
                    "source_dirty_omitted_count": 0,
                    "source_dirty_status_sha256": "dirty-sha",
                    "summary_status": "dirty",
                    "category_count": 2,
                    "top_categories": [
                        {
                            "category": "api_routes",
                            "visible_count": 1,
                            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
                        },
                        {
                            "category": "services",
                            "visible_count": 1,
                            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category services --limit 20",
                        },
                    ],
                    "category_drilldown_commands": [
                        "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
                        "scripts/inspect_source_dirty_groups.py --category services --limit 20",
                    ],
                    "handoff_commands": [
                        "git status --short",
                        "scripts/inspect_source_dirty_groups.py --list-categories",
                        "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
                        "scripts/inspect_source_dirty_groups.py --category services --limit 20",
                    ],
                    "verifier_status": "pass",
                    "verifier_issues": [],
                    "next_action": "commit_or_stash_source_changes_before_clean_receipts",
                    "next_command": "scripts/inspect_source_dirty_groups.py --list-categories",
                },
                "memorial_public_gold_next_command": "scripts/inspect_source_dirty_groups.py --list-categories",
                "public_voice_receipt_semantics": {"label": "Memorial public voice provenance proof", "transcriber_mode": "provenance_cache"},
                "readiness": {"current_head": "abc123"},
                "evidence_heads": {"whole_project_map": "abc123", "public_voice_receipt": "abc123", "public_browser_receipt": "abc123", "public_meaningful_browser_receipt": "abc123", "room_audio_receipt": "abc123"},
                "operator_notes": [],
            }
        ),
        encoding="utf-8",
    )
    phrase_bank = tmp_path / "MEMORIAL_PHRASE_BANK.manfred.generated.json"
    phrase_bank.write_text(json.dumps({"phrases": []}), encoding="utf-8")

    real_path = Path

    def _fake_path(value: str | Path) -> Path:
        text = str(value)
        if text.endswith("/MEMORIAL_OPERATOR_STATUS.generated.json"):
            return operator_status
        if text.endswith("/MEMORIAL_PHRASE_BANK.manfred.generated.json"):
            return phrase_bank
        return real_path(value)

    monkeypatch.setattr(public_memorials, "Path", _fake_path)
    from app.api.routes import public_memorial_operator

    monkeypatch.setattr(
        public_memorial_operator,
        "_memorial_route_probe",
        lambda current_slug: {
            "configured_public_origin": "https://ea.example.test",
            "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
            "local_runtime": {
                "url": f"http://127.0.0.1:8090/memorials/{current_slug}",
                "status_code": 404,
                "status": "blocked",
                "detail": '{"detail":"Not Found"}',
            },
            "public_origin_runtime": {
                "url": f"https://ea.example.test/memorials/{current_slug}",
                "status_code": 403,
                "status": "blocked",
                "detail": "error code: 1010",
            },
            "next_action": "allow_memorial_route_through_edge_firewall",
        },
    )

    client = _client(principal_id="exec-memorial-operator-status")
    response = client.get(
        f"/memorials/{slug}/operator-status",
        headers={"x-memorial-write-token": "unit-write-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers.get("x-robots-tag") == "noindex, nofollow"
    payload = response.json()
    assert payload["current_label"] == "Memorial public-origin gold: blocked"
    assert payload["slug"] == slug
    assert payload["status_artifact"] == "MEMORIAL_OPERATOR_STATUS.generated.json"
    assert payload["phrase_bank_artifact"] == "MEMORIAL_PHRASE_BANK.manfred.generated.json"
    assert "status_path" not in payload
    assert "phrase_bank_path" not in payload
    assert payload["actions"]["refresh_operator_status"] == "make materialize-memorial-operator-status"
    assert payload["actions"]["refresh_phrase_bank"] == "make materialize-memorial-phrase-bank"
    assert payload["actions"]["refresh_public_auto_receipts_clean"] == "make materialize-memorial-public-auto-receipts-clean"
    assert payload["actions"]["prepare_room_audio_attestation_packet"] == "make materialize-memorial-room-audio-attestation-packet"
    assert payload["actions"]["record_room_audio_proof_clean"] == "make materialize-memorial-room-audio-gold-clean"
    assert "route_probe" in payload
    assert payload["route_probe"]["configured_public_origin"] == "https://ea.example.test"
    assert payload["route_probe"]["public_origin_source"] == "EA_PUBLIC_APP_BASE_URL"
    assert payload["route_probe"]["local_runtime"]["status_code"] == 404
    assert payload["route_probe"]["public_origin_runtime"]["status_code"] == 403
    assert payload["route_probe"]["next_action"] == "allow_memorial_route_through_edge_firewall"
    assert payload["room_audio_receipt_detail"]["status"] == "fail"
    assert payload["room_audio_receipt_detail"]["missing_check_ids"] == [
        "normal_spoken_turn_confirmed",
        "interruption_behavior_confirmed",
    ]
    assert payload["source_worktree_dirty"] is True
    assert payload["source_dirty_count"] == 2
    assert payload["source_dirty_verifier"]["contract_name"] == "ea.source_dirty_groups_verifier.v1"
    assert payload["source_dirty_verifier"]["status"] == "pass"
    assert payload["source_cleanup"]["status"] == "blocked"
    assert payload["source_cleanup"]["verifier_status"] == "pass"
    assert payload["source_cleanup"]["handoff_commands"][0] == "git status --short"
    assert payload["source_cleanup"]["next_command"] == "scripts/inspect_source_dirty_groups.py --list-categories"
    assert payload["memorial_public_gold_next_command"] == "scripts/inspect_source_dirty_groups.py --list-categories"
    assert payload["governance"]["authority"] == "ea_local_operator_diagnostics"
    assert payload["governance"]["canonical"] is False
    assert payload["governance"]["privacy_controls"]["voice_ab_feedback"] == {
        "free_text_retained": False,
        "client_identity": "hmac_sha256_receipt",
        "current_vote_event_retention_days": 30,
        "historical_rounds": "aggregate_receipts_only",
    }
    assert [item["owner"] for item in payload["governance"]["external_handoffs"]] == [
        "chummer6-hub",
        "chummer6-hub",
        "chummer6-hub-registry",
    ]


def test_public_memorial_operator_status_degrades_to_structured_payload_when_artifact_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    from app.api.routes import public_memorials

    missing_status = tmp_path / "missing" / "MEMORIAL_OPERATOR_STATUS.generated.json"
    phrase_bank = tmp_path / "MEMORIAL_PHRASE_BANK.manfred.generated.json"
    phrase_bank.write_text(json.dumps({"phrases": []}), encoding="utf-8")

    real_path = Path

    def _fake_path(value: str | Path) -> Path:
        text = str(value)
        if text.endswith("/MEMORIAL_OPERATOR_STATUS.generated.json"):
            return missing_status
        if text.endswith("/MEMORIAL_PHRASE_BANK.manfred.generated.json"):
            return phrase_bank
        return real_path(value)

    monkeypatch.setattr(public_memorials, "Path", _fake_path)

    client = _client(principal_id="exec-memorial-operator-status-missing-status")
    response = client.get(
        f"/memorials/{slug}/operator-status",
        headers={"x-memorial-write-token": "unit-write-token"},
    )

    assert response.status_code == 503
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    payload = response.json()
    assert payload["current_label"] == "Memorial operator status unavailable"
    assert payload["status"] == "blocked"
    assert payload["slug"] == slug
    assert payload["status_artifact"] == "MEMORIAL_OPERATOR_STATUS.generated.json"
    assert payload["phrase_bank_artifact"] == "MEMORIAL_PHRASE_BANK.manfred.generated.json"
    assert payload["actions"]["refresh_operator_status"] == "make materialize-memorial-operator-status"
    assert payload["source_worktree_dirty"] is False
    assert payload["source_dirty_count"] == 0
    assert payload["source_dirty_verifier"]["contract_name"] == "ea.source_dirty_groups_verifier.v1"
    assert payload["source_dirty_verifier"]["status"] == "missing"
    assert payload["source_dirty_verifier"]["issues"] == ["operator_status_artifact_missing"]
    assert payload["source_cleanup"]["status"] == "missing"
    assert payload["source_cleanup"]["verifier_status"] == "missing"
    assert payload["source_cleanup"]["verifier_issues"] == ["operator_status_artifact_missing"]
    assert payload["source_cleanup"]["handoff_commands"] == ["make materialize-memorial-operator-status"]
    assert payload["source_cleanup"]["next_command"] == "make materialize-memorial-operator-status"
    assert payload["memorial_public_gold_next_command"] == "make materialize-memorial-operator-status"
    assert "Status artifact unavailable for manfred." in payload["operator_notes"]


def test_public_memorial_operator_gold_page_renders_human_status_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    from app.api.routes import public_memorials

    operator_status = tmp_path / "MEMORIAL_OPERATOR_STATUS.generated.json"
    operator_status.write_text(
        json.dumps(
            {
                "current_label": "Memorial public-origin gold: pass",
                "status": "pass",
                "public_voice_receipt": "pass",
                "public_browser_receipt": "pass",
                "public_browser_meaningful_receipt": "pass",
                "room_audio_receipt": "pass",
                "whole_project_gold": "pass",
                "spoken_conversation_stt": {
                    "status": "blocked",
                    "best_provider": "",
                    "production_provider": "",
                    "top_candidate_provider": "full_runtime",
                    "passed_samples": 0,
                    "sample_count": 4,
                    "ground_truth_fixture_mode": "synthetic_only",
                    "next_action": "add_real_captured_stt_fixture",
                    "scoring": {
                        "production_eligible_rule": "provider must pass every ground-truth benchmark sample and hostile variant",
                        "text_mode": "redacted",
                        "redacted_text_fields": True,
                    },
                },
                "spoken_conversation_tts": {
                    "status": "pass",
                    "premium_status": "blocked",
                    "next_action": "collect_real_room_audio_attestation",
                },
                "room_audio_attestation_packet": {
                    "status": "ready",
                    "receipt_path": ".codex-studio/published/memorial_room_audio_attestation_packet.generated.json",
                    "manual_only": True,
                    "ci_must_not_auto_assert": True,
                    "operator_command": "make materialize-memorial-room-audio-gold-clean",
                    "next_action": "collect_real_room_audio_attestation",
                    "required_check_ids": [
                        "normal_spoken_turn_confirmed",
                        "interruption_behavior_confirmed",
                        "retry_path_confirmed",
                    ],
                },
                "room_audio_receipt_detail": {
                    "status": "fail",
                    "receipt_path": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
                    "failed_codes": [
                        "normal_spoken_turn_confirmed_missing",
                        "interruption_behavior_confirmed_missing",
                        "retry_path_confirmed_missing",
                    ],
                    "missing_check_ids": [
                        "normal_spoken_turn_confirmed",
                        "interruption_behavior_confirmed",
                        "retry_path_confirmed",
                    ],
                    "missing_checks": [
                        {
                            "id": "normal_spoken_turn_confirmed",
                            "requirement": "A normal spoken question completed as microphone capture, STT, answer, TTS, and playback.",
                        },
                        {
                            "id": "interruption_behavior_confirmed",
                            "requirement": "Intentional interruption or barge-in behavior was observed and was not harsh or confusing.",
                        },
                        {
                            "id": "retry_path_confirmed",
                            "requirement": "The tester observed a clear retry/recovery path after an acoustic or turn-taking problem.",
                        },
                    ],
                    "next_action": "collect_real_room_audio_attestation",
                },
                "workflow_backing": {"status": "no"},
                "public_voice_receipt_semantics": {"label": "Memorial public voice provenance proof", "transcriber_mode": "provenance_cache"},
                "readiness": {"current_head": "abc123"},
                "evidence_heads": {"whole_project_map": "abc123", "public_voice_receipt": "abc123", "public_browser_receipt": "abc123", "public_meaningful_browser_receipt": "abc123", "room_audio_receipt": "abc123"},
                "operator_notes": ["note"],
            }
        ),
        encoding="utf-8",
    )
    phrase_bank = tmp_path / "MEMORIAL_PHRASE_BANK.manfred.generated.json"
    phrase_bank.write_text(json.dumps({"phrases": []}), encoding="utf-8")

    real_path = Path

    def _fake_path(value: str | Path) -> Path:
        text = str(value)
        if text.endswith("/MEMORIAL_OPERATOR_STATUS.generated.json"):
            return operator_status
        if text.endswith("/MEMORIAL_PHRASE_BANK.manfred.generated.json"):
            return phrase_bank
        return real_path(value)

    monkeypatch.setattr(public_memorials, "Path", _fake_path)

    client = _client(principal_id="exec-memorial-operator-gold-page")
    response = client.get(
        f"/admin/memorials/{slug}/gold",
        headers={"x-memorial-write-token": "unit-write-token"},
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    assert "Memorial public-origin gold: pass" in response.text
    assert "Operator Actions" in response.text
    assert "make materialize-memorial-operator-status" in response.text
    assert "make materialize-memorial-phrase-bank" in response.text
    assert "Workflow-backed" in response.text
    assert "Spoken STT" in response.text
    assert "Spoken TTS" in response.text
    assert "Premium Speech" in response.text
    assert "Text fallback is useful, but it is not a premium spoken turn." in response.text
    assert "no_production_stt_provider" in response.text
    assert "full_runtime" in response.text
    assert ".codex-studio/published/memorial_room_audio_attestation_packet.generated.json" in response.text
    assert ".codex-studio/published/memorial_room_audio_public_origin.generated.json" in response.text
    assert "make materialize-memorial-room-audio-gold-clean" in response.text
    assert "normal_spoken_turn_confirmed" in response.text
    assert "interruption_behavior_confirmed" in response.text
    assert "retry_path_confirmed" in response.text
    assert "normal_spoken_turn_confirmed_missing" in response.text
    assert "provider must pass every ground-truth benchmark sample and hostile variant" in response.text
    assert "STT fixture mode" in response.text
    assert "synthetic_only" in response.text
    assert "add_real_captured_stt_fixture" in response.text
    assert "Route Probe" in response.text
    assert "Configured public origin" in response.text
    assert "Local runtime route" in response.text
    assert "Public origin route" in response.text
    assert '<a class="skip-link" href="#memorial-operator-main">' in response.text
    assert '<main id="memorial-operator-main" tabindex="-1">' in response.text
    assert "Governance and Privacy Boundaries" in response.text
    assert "ea_local_operator_diagnostics" in response.text
    assert "hmac_sha256_receipt" in response.text
    assert "chummer6-hub-registry" in response.text


def test_public_memorial_operator_gold_page_degrades_gracefully_when_status_artifact_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    from app.api.routes import public_memorials

    missing_status = tmp_path / "missing" / "MEMORIAL_OPERATOR_STATUS.generated.json"

    real_path = Path

    def _fake_path(value: str | Path) -> Path:
        text = str(value)
        if text.endswith("/MEMORIAL_OPERATOR_STATUS.generated.json"):
            return missing_status
        return real_path(value)

    monkeypatch.setattr(public_memorials, "Path", _fake_path)

    client = _client(principal_id="exec-memorial-operator-gold-page-missing-status")
    response = client.get(
        f"/admin/memorials/{slug}/gold",
        headers={"x-memorial-write-token": "unit-write-token"},
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "Memorial operator status unavailable" in response.text
    assert "Run make materialize-memorial-operator-status and refresh this page." in response.text
    assert "Operator Actions" in response.text
    assert "make materialize-memorial-operator-status" in response.text
    assert "STT benchmark privacy" in response.text
    assert "raw transcript fields redacted" in response.text
    assert "Memorial public voice provenance proof" in response.text


def test_public_memorial_operator_gold_page_requires_operator_surface_and_write_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-operator-gold-page-auth")
    response = client.get(f"/admin/memorials/{slug}/gold")

    assert response.status_code == 403
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy") == "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert "Memorial operator access required" in response.text
    assert "memorial_write_unauthorized" in response.text


def test_public_memorial_preserves_explicitly_approved_curated_memory_excerpt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    approved_excerpt = (
        "Manfred hörte aufmerksam zu, fragte nach den konkreten Folgen und half dann ruhig dabei, "
        "den nächsten verantwortbaren Schritt zu finden."
    )
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "memory_cards": [
                {
                    "visibility": "public",
                    "public": True,
                    "title": "Ruhig den nächsten Schritt finden",
                    "body": "Unredigierter Arbeitsentwurf darf nicht erscheinen.",
                    "public_excerpt": approved_excerpt,
                }
            ],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-curated-excerpt")
    public_json = client.get(f"/memorials/{slug}.json", headers={"host": "myexternalbrain.com"})
    public_page = client.get(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})

    assert public_json.status_code == 200
    assert public_json.json()["memory_cards"][0]["body"] == approved_excerpt
    assert public_json.json()["memory_cards"][0]["curation_status"] == "approved_public_excerpt"
    assert public_page.status_code == 200
    assert approved_excerpt in public_page.text
    assert "Freigegebene Erinnerung" in public_page.text
    assert "Unredigierter Arbeitsentwurf" not in public_json.text
    assert "Unredigierter Arbeitsentwurf" not in public_page.text


def test_difficult_memory_defaults_to_blocked_first_person_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-difficult")
    response = client.post(f"/memorials/{slug}/chat", json={"question": "Was dachte er ueber Kinder schlagen?"})

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "difficult_memory_guardrail"
    assert "keine Ich-Form-Rekonstruktion" in body["answer"]


def test_difficult_family_question_prefers_difficult_memory_guardrail_over_transcript_relationship(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-difficult-family")
    response = client.post(f"/memorials/{slug}/chat", json={"question": "Was haettest du ueber Schuld in der Familie gesagt?"})

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "difficult_memory_guardrail"
    assert "keine Ich-Form-Rekonstruktion" in body["answer"]


def test_family_contribution_management_and_proposal_routes_keep_auth_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    monkeypatch.setenv(
        "EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR",
        str(tmp_path / "contributions" / "public"),
    )
    monkeypatch.setenv(
        "EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR",
        str(tmp_path / "contributions" / "private"),
    )
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    client = _client(principal_id="exec-memorial-family-management-auth")

    submitted = client.post(
        f"/memorials/{slug}/contributions",
        json={
            "title": "PRIVATE_FAMILY_TITLE_SENTINEL",
            "body": "PRIVATE_FAMILY_BODY_SENTINEL",
            "contributor_name": "PRIVATE_FAMILY_NAME_SENTINEL",
            "relationship": "PRIVATE_FAMILY_RELATIONSHIP_SENTINEL",
            "publication_consent": True,
        },
    )
    assert submitted.status_code == 201
    receipt = submitted.json()
    contribution_id = receipt["contribution_id"]
    manage_path = f"/memorials/{slug}/contributions/{contribution_id}/manage"

    denied_management = client.get(manage_path)
    assert denied_management.status_code == 403
    assert denied_management.headers["cache-control"] == "no-store"
    assert denied_management.headers["referrer-policy"] == "no-referrer"
    assert "PRIVATE_FAMILY" not in denied_management.text

    allowed_management = client.get(
        manage_path,
        headers={"x-memorial-contribution-token": receipt["manage_token"]},
    )
    assert allowed_management.status_code == 200
    assert allowed_management.headers["cache-control"] == "no-store"
    management_payload = allowed_management.json()
    assert management_payload["submission"]["body"] == (
        "PRIVATE_FAMILY_BODY_SENTINEL"
    )
    serialized_management = json.dumps(management_payload)
    assert receipt["manage_token"] not in serialized_management
    assert "manage_token_hash" not in serialized_management
    assert "history" not in management_payload
    assert "review" not in management_payload

    unauthorized_proposal = client.post(
        f"/memorials/{slug}/contributions/{contribution_id}/propose",
        json={
            "reviewer": "Unauthorized curator",
            "title": "Safe public title",
            "body": "Safe public body",
        },
    )
    assert unauthorized_proposal.status_code == 403
    assert "PRIVATE_FAMILY" not in unauthorized_proposal.text

    proposed = client.post(
        f"/memorials/{slug}/contributions/{contribution_id}/propose",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={
            "reviewer": "Authorized curator",
            "review_note": "PRIVATE_OPERATOR_NOTE_SENTINEL",
            "title": "Safe public title",
            "body": "Safe public body",
        },
    )
    assert proposed.status_code == 200
    proposal_sha256 = proposed.json()["public_proposal"]["sha256"]

    denied_decision = client.post(
        f"/memorials/{slug}/contributions/{contribution_id}/proposal/approve",
        json={"proposal_sha256": proposal_sha256},
    )
    assert denied_decision.status_code == 403
    assert "PRIVATE_FAMILY" not in denied_decision.text
    assert "PRIVATE_OPERATOR_NOTE" not in denied_decision.text

    managed_proposal = client.get(
        manage_path,
        headers={"x-memorial-contribution-token": receipt["manage_token"]},
    )
    assert managed_proposal.status_code == 200
    assert managed_proposal.json()["public_proposal"]["sha256"] == (
        proposal_sha256
    )
    assert "PRIVATE_OPERATOR_NOTE" not in managed_proposal.text
    assert "Authorized curator" not in managed_proposal.text


def test_family_public_proposal_route_is_disabled_with_operator_surface_off(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "0")
    monkeypatch.setenv(
        "EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR",
        str(tmp_path / "contributions" / "public"),
    )
    monkeypatch.setenv(
        "EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR",
        str(tmp_path / "contributions" / "private"),
    )
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "write_token": "unit-write-token",
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)
    client = _client(principal_id="exec-memorial-proposal-surface-off")
    submitted = client.post(
        f"/memorials/{slug}/contributions",
        json={
            "title": "Private title",
            "body": "Private body",
            "publication_consent": True,
        },
    )
    assert submitted.status_code == 201

    blocked = client.post(
        (
            f"/memorials/{slug}/contributions/"
            f"{submitted.json()['contribution_id']}/propose"
        ),
        headers={"x-memorial-write-token": "unit-write-token"},
        json={
            "reviewer": "Curator",
            "title": "Public title",
            "body": "Public body",
        },
    )
    assert blocked.status_code == 404
    assert _error_code(blocked) == "memorial_operator_surface_disabled"
    assert blocked.headers["cache-control"] == "no-store"
