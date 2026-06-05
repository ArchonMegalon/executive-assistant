from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


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

    artifacts_root = tmp_path / "artifacts"
    public_memorials._PERSONAL_MEMORY_ROOT = artifacts_root / "memorial_user_memory"
    public_memorials._VOICE_AB_ROOT = artifacts_root / "memorial_voice_ab"
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"


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
    assert variant_b["tts_plugin_voice_id"] == "c381af52-a4de-4b0e-a974-99ebc1cfd0b3"

    stored_ratings = json.loads((voice_ab_root / "ratings.json").read_text(encoding="utf-8"))
    assert stored_ratings["round"] == 2
    assert stored_ratings["rounds"][0]["winner"] == "a"


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
