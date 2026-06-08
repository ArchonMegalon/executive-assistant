from __future__ import annotations

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


def test_preflight_live_checks_current_minimal_surface(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    responses = {
        "https://example.test/memorials/files/manfred/memorial.json": (404, ""),
        "https://example.test/memorials/manfred.json": (200, json.dumps({"slug": "manfred", "person_name": "Manfred"})),
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
