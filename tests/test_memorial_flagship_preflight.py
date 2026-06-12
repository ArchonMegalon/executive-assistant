from __future__ import annotations

import hashlib
import json


def test_preflight_detects_public_manifest_tokens(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "write_token": "do-not-ship",
                "audio_clips": [],
            }
        ),
        encoding="utf-8",
    )
    private_root = tmp_path / "private"
    (private_root / "manfred").mkdir(parents=True)
    (private_root / "manfred" / "tts_voice.json").write_text(
        json.dumps(
            {
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)
    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(item.code == "public_manifest_contains_tokens" and item.status == "fail" for item in report.findings)


def test_preflight_passes_explicit_consent_and_public_registry(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "audio").mkdir()
    (bundle / "audio" / "clip.mp3").write_bytes(b"clip")
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [{"asset_relpath": "audio/clip.mp3"}],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
            }
        ),
        encoding="utf-8",
    )
    registry_root = tmp_path / "registry" / "manfred"
    registry_root.mkdir(parents=True)
    (registry_root / "archive_registry.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "archive_sections": [{"title": "Public", "audience": "public", "items": ["doc-public"]}],
                "fliplink_publications": [
                    {
                        "id": "doc-public",
                        "title": "Public Doc",
                        "audience": "public",
                        "review_status": "published",
                        "url": "https://archive.example/public",
                    },
                    {
                        "id": "doc-family",
                        "title": "Family Doc",
                        "audience": "family",
                        "review_status": "published",
                        "url": "https://archive.example/family",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: registry_root / "archive_registry.json")
    monkeypatch.setattr(preflight, "load_registry_json", lambda path: json.loads(path.read_text(encoding="utf-8")))

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(item.code == "voice_consent_ok" and item.status == "pass" for item in report.findings)
    assert any(item.code == "archive_registry_public_only" and item.status == "pass" for item in report.findings)
    assert any(item.code == "avatar_manifest_missing" and item.status == "warn" for item in report.findings)


def test_preflight_passes_verified_avatar_bundle(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video").mkdir(parents=True)
    (bundle / "video" / "avatar.mp4").write_bytes(b"mp4")
    (bundle / "video" / "avatar-poster.png").write_bytes(b"\x89PNG\r\n\x1a\nposter")
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "video_call_avatar": {
                    "provider_key": "vidboard",
                    "provider_proof_verdict": "VERIFIED_PROVIDER",
                    "public_ready": True,
                    "asset_relpath": "video/avatar.mp4",
                    "poster_relpath": "video/avatar-poster.png",
                    "asset_sha256": hashlib.sha256(b"mp4").hexdigest(),
                    "poster_sha256": hashlib.sha256(b"\x89PNG\r\n\x1a\nposter").hexdigest(),
                    "avatar_consent": {
                        "status": "approved",
                        "scope": ["public_video_call", "avatar_playback"],
                        "authorized_by": "family-owner",
                        "authorized_at": "2026-06-09T00:00:00Z",
                        "source_assets_reviewed": True,
                        "revoked": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: tmp_path / "missing.json")

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(item.code == "avatar_video_asset_present" and item.status == "pass" for item in report.findings)
    assert any(item.code == "avatar_manifest_verified" and item.status == "pass" for item in report.findings)
    assert any(item.code == "avatar_video_hash_ok" and item.status == "pass" for item in report.findings)
    assert any(item.code == "avatar_consent_ok" and item.status == "pass" for item in report.findings)


def test_preflight_fails_enabled_avatar_hash_mismatch(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video").mkdir(parents=True)
    (bundle / "video" / "avatar.mp4").write_bytes(b"mp4-changed")
    (bundle / "video" / "avatar-poster.png").write_bytes(b"\x89PNG\r\n\x1a\nposter")
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "video_call_avatar": {
                    "provider_key": "vidboard",
                    "provider_proof_verdict": "VERIFIED_PROVIDER",
                    "public_ready": True,
                    "asset_relpath": "video/avatar.mp4",
                    "poster_relpath": "video/avatar-poster.png",
                    "asset_sha256": hashlib.sha256(b"mp4").hexdigest(),
                    "poster_sha256": hashlib.sha256(b"\x89PNG\r\n\x1a\nposter").hexdigest(),
                    "avatar_consent": {
                        "status": "approved",
                        "scope": ["public_video_call", "avatar_playback"],
                        "authorized_by": "family-owner",
                        "authorized_at": "2026-06-09T00:00:00Z",
                        "source_assets_reviewed": True,
                        "revoked": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: tmp_path / "missing.json")

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(item.code == "avatar_video_hash_mismatch" and item.status == "fail" for item in report.findings)


def test_preflight_passes_public_joggai_video_with_receipt_and_hash(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    (bundle / "receipts").mkdir()
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    receipt_relpath = "receipts/joggai-how-this-memorial-works.generated.json"
    asset_bytes = b"joggai-video"
    asset_hash = hashlib.sha256(asset_bytes).hexdigest()
    (bundle / asset_relpath).write_bytes(asset_bytes)
    (bundle / receipt_relpath).write_text(
        json.dumps(
            {
                "contract_name": "executive_assistant.memorial_joggai_render.v1",
                "provider": "joggai",
                "asset_relpath": asset_relpath,
                "asset_sha256": asset_hash,
                "review_status": "approved",
                "public_ready": True,
            }
        ),
        encoding="utf-8",
    )
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "public_documents": [
                    {
                        "title": "How this memorial works",
                        "asset_relpath": asset_relpath,
                        "public": True,
                        "visibility": "public",
                        "provider": "joggai",
                        "review_status": "approved",
                        "sha256": asset_hash,
                        "receipt_relpath": receipt_relpath,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: tmp_path / "missing.json")

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(item.code == "joggai_public_asset_gate_ok" and item.status == "pass" for item in report.findings)
    assert not any(item.code == "asset_suffix_not_allowed" and item.detail.get("relpath") == asset_relpath for item in report.findings)


def test_preflight_fails_public_joggai_video_without_receipt(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    asset_bytes = b"joggai-video"
    (bundle / asset_relpath).write_bytes(asset_bytes)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "public_documents": [
                    {
                        "title": "How this memorial works",
                        "asset_relpath": asset_relpath,
                        "public": True,
                        "visibility": "public",
                        "provider": "joggai",
                        "review_status": "approved",
                        "sha256": hashlib.sha256(asset_bytes).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: tmp_path / "missing.json")

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(item.code == "joggai_public_asset_missing_receipt_gate" and item.status == "fail" for item in report.findings)


def test_preflight_fails_public_joggai_video_hash_mismatch(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    (bundle / "receipts").mkdir()
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    receipt_relpath = "receipts/joggai-how-this-memorial-works.generated.json"
    manifest_hash = hashlib.sha256(b"original").hexdigest()
    (bundle / asset_relpath).write_bytes(b"changed")
    (bundle / receipt_relpath).write_text(
        json.dumps(
            {
                "contract_name": "executive_assistant.memorial_joggai_render.v1",
                "provider": "joggai",
                "asset_relpath": asset_relpath,
                "asset_sha256": manifest_hash,
                "review_status": "approved",
                "public_ready": True,
            }
        ),
        encoding="utf-8",
    )
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "public_documents": [
                    {
                        "title": "How this memorial works",
                        "asset_relpath": asset_relpath,
                        "public": True,
                        "visibility": "public",
                        "provider": "joggai",
                        "review_status": "approved",
                        "sha256": manifest_hash,
                        "receipt_relpath": receipt_relpath,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: tmp_path / "missing.json")

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(item.code == "joggai_public_asset_hash_mismatch" and item.status == "fail" for item in report.findings)


def test_preflight_fails_public_joggai_video_unsafe_receipt_path(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    asset_bytes = b"joggai-video"
    (bundle / asset_relpath).write_bytes(asset_bytes)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "public_documents": [
                    {
                        "title": "How this memorial works",
                        "asset_relpath": asset_relpath,
                        "public": True,
                        "visibility": "public",
                        "provider": "joggai",
                        "review_status": "approved",
                        "sha256": hashlib.sha256(asset_bytes).hexdigest(),
                        "receipt_relpath": "../private/generated.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: tmp_path / "missing.json")

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "joggai_public_asset_missing_receipt_gate"
        and item.status == "fail"
        and "receipt_relpath" in item.detail.get("missing", [])
        for item in report.findings
    )


def test_preflight_fails_public_joggai_poster_hash_mismatch(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    (bundle / "receipts").mkdir()
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    poster_relpath = "video/joggai/how-this-memorial-works-poster.webp"
    receipt_relpath = "receipts/joggai-how-this-memorial-works.generated.json"
    asset_bytes = b"joggai-video"
    asset_hash = hashlib.sha256(asset_bytes).hexdigest()
    (bundle / asset_relpath).write_bytes(asset_bytes)
    (bundle / poster_relpath).write_bytes(b"poster-changed")
    (bundle / receipt_relpath).write_text(
        json.dumps(
            {
                "contract_name": "executive_assistant.memorial_joggai_render.v1",
                "provider": "joggai",
                "asset_relpath": asset_relpath,
                "asset_sha256": asset_hash,
                "poster_relpath": poster_relpath,
                "poster_sha256": hashlib.sha256(b"poster-original").hexdigest(),
                "review_status": "approved",
                "public_ready": True,
            }
        ),
        encoding="utf-8",
    )
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "audio_clips": [],
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "public_documents": [
                    {
                        "title": "How this memorial works",
                        "asset_relpath": asset_relpath,
                        "public": True,
                        "visibility": "public",
                        "provider": "joggai",
                        "review_status": "approved",
                        "sha256": asset_hash,
                        "receipt_relpath": receipt_relpath,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "public_registry_path", lambda slug, generated=False: tmp_path / "missing.json")

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "joggai_public_asset_hash_mismatch"
        and item.status == "fail"
        and item.detail.get("poster_relpath") == poster_relpath
        for item in report.findings
    )


def test_preflight_live_checks_current_minimal_surface(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    responses = {
        "https://example.test/memorials/files/manfred/memorial.json": (404, ""),
        "https://example.test/memorials/manfred.json": (200, json.dumps({"slug": "manfred", "person_name": "Manfred", "video_call_avatar": {"enabled": False, "kind": "portrait"}})),
        "https://example.test/memorials/manfred": (
            200,
            "<html><body>Gespräch beginnen"
            "Am Handy/Desktop installieren"
            "<button id=\"memorial-conversation\">Gespräch beginnen</button>"
            "<button id=\"memorial-retry-button\">Bitte noch einmal sprechen</button></body></html>",
        ),
        "https://example.test/memorials/manfred/voice-config": (
            200,
            json.dumps({"slug": "manfred", "tts_plugin": "browser_speech_synthesis", "voice_label": "Safe"}),
        ),
        "https://example.test/memorials/manfred/archive.json": (
            200,
            json.dumps(
                {
                    "fliplink_publications": [
                        {
                            "id": "doc-public",
                            "title": "Public Doc",
                            "audience": "public",
                            "review_status": "published",
                            "url": "https://archive.example/public",
                        }
                    ]
                }
            ),
        ),
        "https://example.test/memorials/manfred/speech-synthesize": (400, '{"error":{"code":"unsupported_public_tts_fields"}}'),
    }

    def fake_http_request(url: str, *, method: str = "GET", body: bytes | None = None, headers=None):
        return responses[url]

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    assert report.failed is False
    assert any(item.code == "live_public_page_minimal" and item.status == "pass" for item in report.findings)
    assert any(item.code == "live_public_tts_rejects_override" and item.status == "pass" for item in report.findings)
    assert any(item.code == "live_avatar_portrait_fallback_consistent" and item.status == "pass" for item in report.findings)


def test_preflight_live_checks_avatar_video_when_public_json_enabled(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    responses = {
        "https://example.test/memorials/files/manfred/memorial.json": (404, ""),
        "https://example.test/memorials/manfred.json": (
            200,
            json.dumps(
                {
                    "slug": "manfred",
                    "person_name": "Manfred",
                    "video_call_avatar": {
                        "enabled": True,
                        "kind": "video",
                        "asset_url": "/memorials/files/manfred/video/avatar.mp4",
                        "poster_url": "/memorials/files/manfred/video/avatar-poster.png",
                    },
                }
            ),
        ),
        "https://example.test/memorials/manfred": (
            200,
            "<html><body>Gespräch beginnen"
            "Am Handy/Desktop installieren"
            "<video id=\"memorial-video-call-avatar-video\" src=\"/memorials/files/manfred/video/avatar.mp4\"></video></body></html>",
        ),
        "https://example.test/memorials/manfred/voice-config": (
            200,
            json.dumps({"slug": "manfred", "tts_plugin": "browser_speech_synthesis", "voice_label": "Safe"}),
        ),
        "https://example.test/memorials/manfred/archive.json": (200, json.dumps({"fliplink_publications": []})),
        "https://example.test/memorials/manfred/speech-synthesize": (400, '{"error":{"code":"unsupported_public_tts_fields"}}'),
    }

    def fake_http_request(url: str, *, method: str = "GET", body: bytes | None = None, headers=None):
        return responses[url]

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    assert report.failed is False
    assert any(item.code == "live_avatar_video_present_on_page" and item.status == "pass" for item in report.findings)


def test_preflight_http_request_returns_zero_for_transport_failure(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    def fail_urlopen(*_args, **_kwargs):
        raise ConnectionResetError("startup race")

    monkeypatch.setattr(preflight.urllib.request, "urlopen", fail_urlopen)

    status, body = preflight.http_request("https://example.test/memorials/manfred")

    assert status == 0
    assert "ConnectionResetError" in body


def test_preflight_live_transport_failures_are_structured_findings(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    def fake_http_request(url: str, *, method: str = "GET", body: bytes | None = None, headers=None):
        return 0, "ConnectionResetError: startup race"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    failures = [item for item in report.findings if item.code == "live_endpoint_request_failed"]
    assert report.failed is True
    assert len(failures) == 6
    assert {item.detail["route"] for item in failures} == {
        "raw_manifest",
        "public_json",
        "public_page",
        "voice_config",
        "archive_json",
        "speech_synthesize_override_probe",
    }
