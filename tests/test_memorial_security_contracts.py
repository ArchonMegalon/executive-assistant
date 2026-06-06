from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request


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
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = tmp_path / "public_registry"
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"


def _error_code(response) -> str:
    body = response.json()
    if isinstance(body.get("error"), dict):
        return str(body["error"].get("code") or "")
    return str(body.get("detail") or "")


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
            "character_notes": [{"note": "private-note", "public": False}],
            "audio_clips": [],
        },
    )
    (bundle_dir / "audio").mkdir()
    (bundle_dir / "audio" / "clip.mp3").write_bytes(b"clip")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-sanitize")

    response = client.get(f"/memorials/{slug}.json")
    assert response.status_code == 200
    body = response.json()
    assert "write_token" not in body
    assert body.get("character_notes") == []

    raw_manifest = client.get(f"/memorials/files/{slug}/memorial.json")
    assert raw_manifest.status_code == 404


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
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-pwa-icons")

    manifest = client.get(f"/memorials/{slug}/app.webmanifest")
    assert manifest.status_code == 200
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
    assert "Am Handy/Desktop installieren" in page.text
    assert "App installieren" not in page.text
    assert f"/memorials/{slug}/icon-180.png" in page.text

    icon_response = client.get(f"/memorials/{slug}/icon-512.png")
    assert icon_response.status_code == 200
    assert icon_response.headers["content-type"].startswith("image/png")
    assert icon_response.content.startswith(b"\x89PNG")

    service_worker = client.get(f"/memorials/{slug}/service-worker.js")
    assert service_worker.status_code == 200
    assert service_worker.headers["service-worker-allowed"] == f"/memorials/{slug}"
    assert f"/memorials/{slug}/icon-512.png" in service_worker.text


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
    assert _error_code(unauthorized) == "memorial_fliplink_webhook_secret_invalid"

    empty = client.post(
        f"/v1/integrations/fliplink/memorials/{slug}/webhook",
        headers={"x-memorial-fliplink-secret": "secret-123"},
        json={"publication_slug": "share-a-memory"},
    )
    assert empty.status_code == 422
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
    assert '<details class="hero-settings minimal-disclosure">' in body
    assert '<summary class="collapse-summary">Optionen</summary>' in body
    assert '<details class="voice-tools minimal-disclosure" id="memorial-voice-ab-wrap"' in body
    assert 'Stimmvergleich und Feedback</summary>' in body
    assert '<div class="voice-ab-choice-grid">' in body
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" not in body
    assert '<section id="memorial-archive">' in body
    assert '<details class="minimal-disclosure archive-disclosure">' in body
    assert '<summary class="collapse-summary">Archiv lesen</summary>' in body
    assert "overflow-wrap: anywhere;" in body
    assert ".collapse-summary:focus-visible" in body
    assert "<h2>Archiv lesen</h2>" not in body
    assert "<h2>Stimmvergleich</h2>" not in body
    assert body.index('<section class="chat quiet-shell">') < body.index('<section id="memorial-archive">')


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


def test_public_voice_ab_auto_rotates_challenger_after_effective_margin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
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
                        "tts_plugin_voice_id": "558a4e6f-b80b-474d-a48b-09bd46c4f9eb",
                        "description": "Champion",
                    },
                    {
                        "id": "b",
                        "label": "Stimme B · challenger",
                        "tts_plugin": "unmixr_clone",
                        "tts_plugin_voice_id": "e8eced7f-35fa-4036-af46-ba2b748afd70",
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
    assert variant_b["tts_plugin_voice_id"] == "26858715-06e2-4bd3-a100-e0c1c1676466"

    stored_ratings = json.loads((voice_ab_root / "ratings.json").read_text(encoding="utf-8"))
    assert stored_ratings["round"] == 2
    assert stored_ratings["rounds"][0]["winner"] == "a"


def test_public_voice_ab_admin_requires_write_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    public_root = tmp_path / "public"
    slug = "manfred"
    _write_public_memorial(public_root, slug, {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []})
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-voice-admin")
    response = client.get(f"/memorials/{slug}/voice-ab-admin")

    assert response.status_code in {403, 503}


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
