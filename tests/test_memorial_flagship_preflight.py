from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def test_preflight_missing_public_manifest_is_structured(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    monkeypatch.setattr(preflight, "public_memorial_root", lambda: tmp_path / "public")
    report = preflight.Report(slug="manfred")

    preflight.check_filesystem("manfred", report)

    assert report.failed is True
    assert [(item.status, item.code) for item in report.findings] == [
        ("fail", "public_manifest_missing")
    ]


def test_preflight_invalid_public_manifest_is_structured(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    bundle = tmp_path / "public" / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: tmp_path / "public")
    report = preflight.Report(slug="manfred")

    preflight.check_filesystem("manfred", report)

    assert report.failed is True
    assert [(item.status, item.code) for item in report.findings] == [
        ("fail", "public_manifest_invalid")
    ]


def _write_verified_joggai_provider_receipt(
    bundle, relpath: str = "receipts/JOGGAI_PROVIDER_VERIFICATION.generated.json"
) -> tuple[str, str]:
    payload = {
        "contract_name": "executive_assistant.joggai_provider_verification.v1",
        "provider": "joggai",
        "provider_key": "joggai",
        "verdict": "VERIFIED_PROVIDER",
        "provider_ready": True,
    }
    path = bundle / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return relpath, hashlib.sha256(raw).hexdigest()


def _write_public_archive_registry(
    bundle: Path,
    *,
    publication_audience: str = "public",
    review_status: str = "published",
) -> None:
    (bundle / "archive_registry.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "archive_sections": [
                    {"title": "Public", "audience": "public", "items": ["doc-public"]}
                ],
                "fliplink_publications": [
                    {
                        "id": "doc-public",
                        "audience": publication_audience,
                        "review_status": review_status,
                        "url": "https://archive.example/public",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_private_voice_consent(private_root: Path, consent: object) -> None:
    profile = private_root / "manfred"
    profile.mkdir(parents=True, exist_ok=True)
    profile.chmod(0o700)
    path = profile / "tts_voice.json"
    path.write_text(
        json.dumps({"voice_consent": consent}), encoding="utf-8"
    )
    path.chmod(0o600)


def _write_private_context(private_root: Path) -> None:
    from app.services.memorial_private_context import (
        PRIVATE_CONTEXT_FILENAME,
        private_context_payload,
    )

    profile = private_root / "manfred"
    profile.mkdir(parents=True, exist_ok=True)
    payload = private_context_payload(
        slug="manfred",
        overrides={
            "audio_clips": [],
            "memory_cards": [],
            "candidate_recordings": [],
            "source_grounded_profile": [],
            "character_notes": [],
            "conversation_style": {},
            "external_sources": [],
            "memory_principal_id": "memorial:test",
            "chat_models": [{"llm_model": "local", "label": "Local"}],
            "chat_model_default": "local",
        },
    )
    path = profile / PRIVATE_CONTEXT_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def test_preflight_defaults_to_repository_memorial_data(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    monkeypatch.delenv("EA_PUBLIC_MEMORIAL_DIR", raising=False)
    monkeypatch.delenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", raising=False)
    repo_root = Path(preflight.__file__).resolve().parents[1]

    assert (
        preflight.public_memorial_root()
        == repo_root / "memorial_data" / "public_memorials"
    )
    assert (
        preflight.private_profile_root()
        == repo_root / "memorial_data" / "private_memorial_profiles"
    )


def test_preflight_root_environment_overrides(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public-override"
    private_root = tmp_path / "private-override"
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))

    assert preflight.public_memorial_root() == public_root
    assert preflight.private_profile_root() == private_root


def test_preflight_private_context_declaration_reports_missing_invalid_and_pass(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    _write_public_archive_registry(bundle)
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": False,
        },
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    manifest_path = bundle / "memorial.json"
    manifest_path.write_text(
        json.dumps(
            {
                "slug": "manfred",
                "private_context": {
                    "required": True,
                    "schema": "ea.memorial_private_context.v1",
                },
            }
        ),
        encoding="utf-8",
    )
    missing = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", missing)
    assert any(
        item.code == "private_context_missing" and item.status == "fail"
        for item in missing.findings
    )

    context_path = private_root / "manfred" / "memorial_private_context.json"
    context_path.write_text("{invalid", encoding="utf-8")
    context_path.chmod(0o600)
    invalid = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", invalid)
    assert any(
        item.code == "private_context_invalid" and item.status == "fail"
        for item in invalid.findings
    )

    _write_private_context(private_root)
    valid = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", valid)
    assert any(
        item.code == "private_context_valid" and item.status == "pass"
        for item in valid.findings
    )

    manifest_path.write_text(json.dumps({"slug": "manfred"}), encoding="utf-8")
    undeclared = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", undeclared)
    assert not any(
        item.code.startswith("private_context_") for item in undeclared.findings
    )


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
    (private_root / "manfred").chmod(0o700)
    voice_path = private_root / "manfred" / "tts_voice.json"
    voice_path.write_text(
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
    voice_path.chmod(0o600)

    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)
    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "public_manifest_contains_tokens" and item.status == "fail"
        for item in report.findings
    )


def test_preflight_rejects_unreferenced_family_publication_in_public_registry(
    monkeypatch, tmp_path
) -> None:
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
            }
        ),
        encoding="utf-8",
    )
    private_root = tmp_path / "private"
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": False,
        },
    )
    registry_root = tmp_path / "registry" / "manfred"
    registry_root.mkdir(parents=True)
    (registry_root / "archive_registry.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "archive_sections": [
                    {"title": "Public", "audience": "public", "items": ["doc-public"]}
                ],
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
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: registry_root / "archive_registry.json",
    )
    monkeypatch.setattr(
        preflight,
        "load_registry_json",
        lambda path: json.loads(path.read_text(encoding="utf-8")),
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "voice_consent_ok" and item.status == "pass"
        for item in report.findings
    )
    assert any(
        item.code == "archive_registry_not_public" and item.status == "fail"
        for item in report.findings
    )
    assert any(
        item.code == "avatar_manifest_missing" and item.status == "warn"
        for item in report.findings
    )


def test_preflight_private_voice_consent_is_authoritative(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_public_archive_registry(bundle)
    private_root = tmp_path / "private"
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": True,
            "authorized_by": "must-not-leak",
        },
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    finding = next(
        item for item in report.findings if item.code == "voice_consent_revoked"
    )
    assert finding.status == "fail"
    assert finding.detail == {}
    assert not any(item.code == "voice_consent_ok" for item in report.findings)


@pytest.mark.parametrize(
    ("file_mode", "profile_mode"),
    [
        (0o640, 0o700),
        (0o600, 0o750),
        (0o200, 0o700),
        (0o600, 0o600),
    ],
)
def test_preflight_rejects_broad_private_voice_profile_permissions(
    monkeypatch, tmp_path, file_mode, profile_mode
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    _write_public_archive_registry(bundle)
    private_root = tmp_path / "private"
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": False,
        },
    )
    profile = private_root / "manfred"
    (profile / "tts_voice.json").chmod(file_mode)
    profile.chmod(profile_mode)
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)
    profile.chmod(0o700)

    finding = next(
        item for item in report.findings if item.code == "voice_profile_security_invalid"
    )
    assert finding.status == "fail"
    assert not any(item.code == "voice_consent_ok" for item in report.findings)


def test_preflight_rejects_private_voice_profile_owner_mismatch(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    _write_public_archive_registry(bundle)
    private_root = tmp_path / "private"
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": False,
        },
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)
    actual_uid = preflight.os.geteuid()
    monkeypatch.setattr(preflight.os, "geteuid", lambda: actual_uid + 1)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    finding = next(
        item for item in report.findings if item.code == "voice_profile_security_invalid"
    )
    assert finding.status == "fail"
    assert finding.detail["profile_owner_ok"] is False


def test_preflight_rejects_symlinked_private_voice_profile(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    _write_public_archive_registry(bundle)
    private_root = tmp_path / "private"
    profile = private_root / "manfred"
    profile.mkdir(parents=True)
    profile.chmod(0o700)
    outside = tmp_path / "outside-voice.json"
    outside.write_text(
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
    outside.chmod(0o600)
    (profile / "tts_voice.json").symlink_to(outside)
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.status == "fail" and item.code == "voice_profile_security_invalid"
        for item in report.findings
    )
    assert not any(item.code == "voice_consent_ok" for item in report.findings)


def test_preflight_accepts_legacy_public_consent_only_when_private_profile_is_absent(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_public_archive_registry(bundle)
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(
        preflight, "private_profile_root", lambda: tmp_path / "missing-private"
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "voice_consent_ok" and item.status == "pass"
        for item in report.findings
    )


def test_preflight_fails_when_voice_consent_is_missing(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    _write_public_archive_registry(bundle)
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(
        preflight, "private_profile_root", lambda: tmp_path / "missing-private"
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    finding = next(
        item for item in report.findings if item.code == "voice_consent_missing"
    )
    assert finding.status == "fail"
    assert finding.detail == {}


def test_preflight_fails_invalid_private_consent_without_public_fallback(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_public_archive_registry(bundle)
    private_root = tmp_path / "private"
    profile = private_root / "manfred"
    profile.mkdir(parents=True)
    profile.chmod(0o700)
    voice_path = profile / "tts_voice.json"
    voice_path.write_text("{not-json", encoding="utf-8")
    voice_path.chmod(0o600)
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    finding = next(
        item for item in report.findings if item.code == "voice_consent_invalid"
    )
    assert finding.status == "fail"
    assert finding.detail == {}
    assert not any(item.code == "voice_consent_ok" for item in report.findings)


@pytest.mark.parametrize(
    ("consent", "expected_code"),
    [
        (
            {
                "status": "pending",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "revoked": False,
            },
            "voice_consent_not_approved",
        ),
        (
            {"status": "approved", "scope": ["synthesize"], "revoked": False},
            "voice_consent_scope_missing",
        ),
        (
            {"status": "approved", "scope": "synthesize", "revoked": False},
            "voice_consent_invalid",
        ),
    ],
)
def test_preflight_fails_unusable_private_consent(
    monkeypatch, tmp_path, consent, expected_code
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    _write_public_archive_registry(bundle)
    private_root = tmp_path / "private"
    _write_private_voice_consent(private_root, consent)
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == expected_code and item.status == "fail" for item in report.findings
    )


def test_preflight_fails_when_archive_registry_is_missing(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    private_root = tmp_path / "private"
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": False,
        },
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    finding = next(
        item for item in report.findings if item.code == "archive_registry_missing"
    )
    assert finding.status == "fail"
    assert finding.detail == {}


def test_preflight_fails_when_archive_registry_is_invalid(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    (bundle / "archive_registry.json").write_text("{not-json", encoding="utf-8")
    private_root = tmp_path / "private"
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": False,
        },
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    finding = next(
        item for item in report.findings if item.code == "archive_registry_invalid"
    )
    assert finding.status == "fail"
    assert finding.detail == {}


@pytest.mark.parametrize(
    ("publication_audience", "review_status"),
    [("family", "published"), ("public", "approved")],
)
def test_preflight_fails_when_archive_registry_is_not_public(
    monkeypatch,
    tmp_path,
    publication_audience,
    review_status,
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps({"slug": "manfred"}), encoding="utf-8"
    )
    _write_public_archive_registry(
        bundle,
        publication_audience=publication_audience,
        review_status=review_status,
    )
    private_root = tmp_path / "private"
    _write_private_voice_consent(
        private_root,
        {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn", "realtime"],
            "revoked": False,
        },
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)
    monkeypatch.setattr(preflight, "private_profile_root", lambda: private_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    finding = next(
        item for item in report.findings if item.code == "archive_registry_not_public"
    )
    assert finding.status == "fail"
    assert finding.detail == {}


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
                    "poster_sha256": hashlib.sha256(
                        b"\x89PNG\r\n\x1a\nposter"
                    ).hexdigest(),
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
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: tmp_path / "missing.json",
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "avatar_video_asset_present" and item.status == "pass"
        for item in report.findings
    )
    assert any(
        item.code == "avatar_manifest_verified" and item.status == "pass"
        for item in report.findings
    )
    assert any(
        item.code == "avatar_video_hash_ok" and item.status == "pass"
        for item in report.findings
    )
    assert any(
        item.code == "avatar_consent_ok" and item.status == "pass"
        for item in report.findings
    )


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
                    "poster_sha256": hashlib.sha256(
                        b"\x89PNG\r\n\x1a\nposter"
                    ).hexdigest(),
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
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: tmp_path / "missing.json",
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "avatar_video_hash_mismatch" and item.status == "fail"
        for item in report.findings
    )


def test_preflight_passes_public_joggai_video_with_receipt_and_hash(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    (bundle / "receipts").mkdir()
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    receipt_relpath = "receipts/joggai-how-this-memorial-works.generated.json"
    provider_receipt_relpath, provider_receipt_hash = (
        _write_verified_joggai_provider_receipt(bundle)
    )
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
                "provider_verification_receipt": provider_receipt_relpath,
                "provider_verification_sha256": provider_receipt_hash,
                "provider_verdict_required": "VERIFIED_PROVIDER",
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
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: tmp_path / "missing.json",
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "joggai_public_asset_gate_ok" and item.status == "pass"
        for item in report.findings
    )
    assert not any(
        item.code == "asset_suffix_not_allowed"
        and item.detail.get("relpath") == asset_relpath
        for item in report.findings
    )


def test_preflight_fails_public_joggai_video_without_receipt(
    monkeypatch, tmp_path
) -> None:
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
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: tmp_path / "missing.json",
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "joggai_public_asset_missing_receipt_gate"
        and item.status == "fail"
        for item in report.findings
    )


def test_preflight_fails_public_joggai_video_hash_mismatch(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    (bundle / "receipts").mkdir()
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    receipt_relpath = "receipts/joggai-how-this-memorial-works.generated.json"
    provider_receipt_relpath, provider_receipt_hash = (
        _write_verified_joggai_provider_receipt(bundle)
    )
    manifest_hash = hashlib.sha256(b"original").hexdigest()
    (bundle / asset_relpath).write_bytes(b"changed")
    (bundle / receipt_relpath).write_text(
        json.dumps(
            {
                "contract_name": "executive_assistant.memorial_joggai_render.v1",
                "provider": "joggai",
                "asset_relpath": asset_relpath,
                "asset_sha256": manifest_hash,
                "provider_verification_receipt": provider_receipt_relpath,
                "provider_verification_sha256": provider_receipt_hash,
                "provider_verdict_required": "VERIFIED_PROVIDER",
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
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: tmp_path / "missing.json",
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "joggai_public_asset_hash_mismatch" and item.status == "fail"
        for item in report.findings
    )


def test_preflight_fails_public_joggai_video_unsafe_receipt_path(
    monkeypatch, tmp_path
) -> None:
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
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: tmp_path / "missing.json",
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "joggai_public_asset_missing_receipt_gate"
        and item.status == "fail"
        and "receipt_relpath" in item.detail.get("missing", [])
        for item in report.findings
    )


def test_preflight_fails_public_joggai_poster_hash_mismatch(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "video" / "joggai").mkdir(parents=True)
    (bundle / "receipts").mkdir()
    asset_relpath = "video/joggai/how-this-memorial-works.mp4"
    poster_relpath = "video/joggai/how-this-memorial-works-poster.webp"
    receipt_relpath = "receipts/joggai-how-this-memorial-works.generated.json"
    provider_receipt_relpath, provider_receipt_hash = (
        _write_verified_joggai_provider_receipt(bundle)
    )
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
                "provider_verification_receipt": provider_receipt_relpath,
                "provider_verification_sha256": provider_receipt_hash,
                "provider_verdict_required": "VERIFIED_PROVIDER",
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
    monkeypatch.setattr(
        preflight,
        "public_registry_path",
        lambda slug, generated=False: tmp_path / "missing.json",
    )

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.code == "joggai_public_asset_hash_mismatch"
        and item.status == "fail"
        and item.detail.get("poster_relpath") == poster_relpath
        for item in report.findings
    )


def test_preflight_live_accepts_internal_archive_evidence_without_external_sources(
    monkeypatch,
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    responses = {
        "https://example.test/memorials/files/manfred/memorial.json": (404, ""),
        "https://example.test/memorials/manfred.json": (
            200,
            json.dumps(
                {
                    "slug": "manfred",
                    "memory_cards": [
                        {
                            "title": "Schach",
                            "body": "Familie",
                            "curation_status": "approved_public_excerpt",
                        }
                    ],
                    "external_sources": [],
                    "suggested_prompts": ["Was ist belegt?"],
                    "video_call_avatar": {"enabled": False, "kind": "portrait"},
                }
            ),
        ),
        "https://example.test/memorials/manfred": (
            200,
            '<html><main id="memorial-story" tabindex="-1">Erinnerungen und belegte Quellen</main>'
            '<a href="#memorial-conversation-region">Gespräch</a>'
            '<aside id="memorial-conversation-region" tabindex="-1">'
            '<button id="memorial-conversation"></button><button id="memorial-retry-button"></button>'
            "</aside></html>",
        ),
        "https://example.test/memorials/manfred/voice-config": (200, "{}"),
        "https://example.test/memorials/manfred/archive.json": (
            200,
            json.dumps(
                {
                    "fliplink_publications": [
                        {
                            "id": "life",
                            "audience": "public",
                            "review_status": "published",
                            "url": "/memorials/manfred/archive/life",
                        }
                    ]
                }
            ),
        ),
        "https://example.test/memorials/manfred/speech-synthesize": (
            400,
            '{"error":{"code":"unsupported_public_tts_fields"}}',
        ),
    }

    monkeypatch.setattr(
        preflight,
        "http_request",
        lambda url, **_kwargs: responses[url],
    )
    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    assert report.failed is False
    assert any(
        item.code == "live_public_payload_private_shapes_omitted"
        and item.status == "pass"
        for item in report.findings
    )
    assert not any(
        item.code == "live_public_payload_empty_private_fields"
        for item in report.findings
    )
    finding = next(
        item for item in report.findings if item.code == "live_public_page_source_first"
    )
    assert finding.status == "pass"
    assert finding.detail["public_source_count"] == 0
    assert finding.detail["public_archive_source_count"] == 1


def test_preflight_live_checks_current_source_first_surface(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    responses = {
        "https://example.test/memorials/files/manfred/memorial.json": (404, ""),
        "https://example.test/memorials/manfred.json": (
            200,
            json.dumps(
                {
                    "slug": "manfred",
                    "person_name": "Manfred",
                    "memory_cards": [
                        {"title": "Schach", "body": "[stark redigiert] Familie"}
                    ],
                    "external_sources": [
                        {"label": "Quelle", "url": "https://example.test/source"}
                    ],
                    "suggested_prompts": ["Was ist belegt?"],
                    "video_call_avatar": {"enabled": False, "kind": "portrait"},
                }
            ),
        ),
        "https://example.test/memorials/manfred": (
            200,
            '<html><body><a href="#memorial-conversation-region">Zum Gespräch springen</a>'
            '<main id="memorial-story" tabindex="-1">Erinnerungen und belegte Quellen</main>'
            '<aside id="memorial-conversation-region" tabindex="-1">Gespräch beginnen'
            '<button id="memorial-conversation">Gespräch beginnen</button>'
            '<button id="memorial-retry-button">Bitte noch einmal sprechen</button></aside></body></html>',
        ),
        "https://example.test/memorials/manfred/voice-config": (
            200,
            json.dumps(
                {
                    "slug": "manfred",
                    "tts_plugin": "browser_speech_synthesis",
                    "voice_label": "Safe",
                }
            ),
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
        "https://example.test/memorials/manfred/speech-synthesize": (
            400,
            '{"error":{"code":"unsupported_public_tts_fields"}}',
        ),
    }

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        return responses[url]

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    assert report.failed is False
    assert any(
        item.code == "live_public_page_source_first" and item.status == "pass"
        for item in report.findings
    )
    assert any(
        item.code == "live_public_tts_rejects_override" and item.status == "pass"
        for item in report.findings
    )
    assert any(
        item.code == "live_avatar_portrait_fallback_consistent"
        and item.status == "pass"
        for item in report.findings
    )


def test_preflight_live_checks_avatar_video_when_public_json_enabled(
    monkeypatch,
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    responses = {
        "https://example.test/memorials/files/manfred/memorial.json": (404, ""),
        "https://example.test/memorials/manfred.json": (
            200,
            json.dumps(
                {
                    "slug": "manfred",
                    "person_name": "Manfred",
                    "memory_cards": [
                        {"title": "Schach", "body": "[stark redigiert] Familie"}
                    ],
                    "external_sources": [
                        {"label": "Quelle", "url": "https://example.test/source"}
                    ],
                    "suggested_prompts": ["Was ist belegt?"],
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
            '<html><body><a href="#memorial-conversation-region">Zum Gespräch springen</a>'
            '<main id="memorial-story" tabindex="-1">Erinnerungen und belegte Quellen</main>'
            '<aside id="memorial-conversation-region" tabindex="-1">Gespräch beginnen'
            '<button id="memorial-conversation">Gespräch beginnen</button>'
            '<button id="memorial-retry-button">Bitte noch einmal sprechen</button>'
            '<video id="memorial-video-call-avatar-video" src="/memorials/files/manfred/video/avatar.mp4"></video>'
            "</aside></body></html>",
        ),
        "https://example.test/memorials/manfred/voice-config": (
            200,
            json.dumps(
                {
                    "slug": "manfred",
                    "tts_plugin": "browser_speech_synthesis",
                    "voice_label": "Safe",
                }
            ),
        ),
        "https://example.test/memorials/manfred/archive.json": (
            200,
            json.dumps({"fliplink_publications": []}),
        ),
        "https://example.test/memorials/manfred/speech-synthesize": (
            400,
            '{"error":{"code":"unsupported_public_tts_fields"}}',
        ),
    }

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        return responses[url]

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    assert report.failed is False
    assert any(
        item.code == "live_avatar_video_present_on_page" and item.status == "pass"
        for item in report.findings
    )


def test_preflight_live_http_failures_are_structured_without_json_crash(
    monkeypatch,
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if url.endswith("/speech-synthesize"):
            return 400, '{"error":{"code":"unsupported_public_tts_fields"}}'
        return 404, '{"detail":"not found"}'

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    failures = [
        item
        for item in report.findings
        if item.code == "live_endpoint_http_status_failed"
    ]
    assert report.failed is True
    assert {item.detail["route"] for item in failures} == {
        "public_json",
        "public_page",
        "voice_config",
        "archive_json",
    }
    assert all(item.detail["http_status"] == 404 for item in failures)
    assert any(
        item.code == "live_raw_manifest_not_public" and item.status == "pass"
        for item in report.findings
    )


def test_preflight_live_invalid_json_is_structured(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if "/files/" in url:
            return 404, ""
        if url.endswith("/speech-synthesize"):
            return 400, '{"error":{"code":"unsupported_public_tts_fields"}}'
        if url.endswith(".json"):
            return 200, "<html>not json</html>"
        if url.endswith("/voice-config"):
            return 200, "{}"
        return 200, "<html>page</html>"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    failures = [
        item for item in report.findings if item.code == "live_endpoint_json_invalid"
    ]
    assert report.failed is True
    assert {item.detail["route"] for item in failures} == {
        "public_json",
        "archive_json",
    }
    assert all("detail" not in item.detail for item in failures)


def test_preflight_live_tts_override_must_fail_closed(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if "/files/" in url:
            return 404, ""
        if url.endswith("/speech-synthesize"):
            return 500, "provider body must not be projected"
        if url.endswith("/voice-config") or url.endswith(".json"):
            return 200, "{}"
        return 200, "<html></html>"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    failure = next(
        item
        for item in report.findings
        if item.code == "live_public_tts_override_rejection_failed"
    )
    assert report.failed is True
    assert failure.detail == {"http_status": 500, "field": "voice_name"}


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

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        return 0, "ConnectionResetError: startup race"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)

    report = preflight.Report(slug="manfred")
    preflight.check_live("manfred", report, "https://example.test")

    failures = [
        item for item in report.findings if item.code == "live_endpoint_request_failed"
    ]
    assert report.failed is True
    assert len(failures) == 7
    assert {item.detail["route"] for item in failures} == {
        "raw_manifest",
        "public_json",
        "public_page",
        "voice_config",
        "archive_json",
        "speech_synthesize_voice_name_override_probe",
        "speech_synthesize_tts_plugin_voice_id_override_probe",
    }


def test_preflight_live_requires_raw_manifest_exactly_404(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if "/files/" in url:
            return 403, ""
        if url.endswith("/speech-synthesize"):
            return 400, '{"error":{"code":"unsupported_public_tts_fields"}}'
        if url.endswith("/voice-config") or url.endswith(".json"):
            return 200, "{}"
        return 200, "<html></html>"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)
    report = preflight.Report(slug="manfred")

    preflight.check_live("manfred", report, "https://example.test")

    finding = next(
        item
        for item in report.findings
        if item.code == "live_raw_manifest_access_policy_failed"
    )
    assert finding.status == "fail"
    assert finding.detail == {"http_status": 403}
    assert not any(item.code == "live_raw_manifest_not_public" for item in report.findings)


def test_preflight_live_probes_both_public_tts_override_fields(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    probed_fields: list[str] = []

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if url.endswith("/speech-synthesize"):
            assert method == "POST"
            payload = json.loads((body or b"{}").decode("utf-8"))
            probed_fields.extend(payload)
            return 400, '{"error":{"code":"unsupported_public_tts_fields"}}'
        if "/files/" in url:
            return 404, ""
        if url.endswith("/voice-config") or url.endswith(".json"):
            return 200, "{}"
        return 200, "<html></html>"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)
    report = preflight.Report(slug="manfred")

    preflight.check_live("manfred", report, "https://example.test")

    assert probed_fields == ["voice_name", "tts_plugin_voice_id"]
    finding = next(
        item for item in report.findings if item.code == "live_public_tts_rejects_override"
    )
    assert finding.detail == {"fields": ["tts_plugin_voice_id", "voice_name"]}


def test_preflight_live_rejects_sensitive_fields_in_public_payloads(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if url.endswith("/speech-synthesize"):
            return 400, '{"error":{"code":"unsupported_public_tts_fields"}}'
        if "/files/" in url:
            return 404, ""
        if url.endswith("/voice-config"):
            return 200, json.dumps({"nested": {"tts_plugin_voice_id": "must-not-escape"}})
        if url.endswith("/manfred.json"):
            return 200, json.dumps(
                {
                    "metadata": {"write_token": "must-not-escape"},
                    "candidate_recordings": [{"asset": "private.wav"}],
                }
            )
        if url.endswith("/archive.json"):
            return 200, "{}"
        return 200, "<html></html>"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)
    report = preflight.Report(slug="manfred")

    preflight.check_live("manfred", report, "https://example.test")

    findings = [
        item for item in report.findings if item.code == "live_public_payload_forbidden_fields"
    ]
    assert [(item.detail["route"], item.detail["fields"]) for item in findings] == [
        (
            "public_json",
            ["$.metadata.write_token", "$.candidate_recordings"],
        ),
        ("voice_config", ["$.nested.tts_plugin_voice_id"]),
    ]


def test_preflight_live_rejects_nested_sensitive_field_in_public_archive(
    monkeypatch,
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    archive_payload = {
        "archive_sections": [
            {
                "audience": "public",
                "items": ["public-document"],
            }
        ],
        "fliplink_publications": [
            {
                "id": "public-document",
                "audience": "public",
                "review_status": "published",
                "url": "https://archive.example/public-document",
                "provider_metadata": {
                    "access_token": "must-not-escape",
                },
            }
        ],
    }

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if url.endswith("/speech-synthesize"):
            return 400, '{"error":{"code":"unsupported_public_tts_fields"}}'
        if "/files/" in url:
            return 404, ""
        if url.endswith("/manfred.json") or url.endswith("/voice-config"):
            return 200, "{}"
        if url.endswith("/archive.json"):
            return 200, json.dumps(archive_payload)
        return 200, "<html></html>"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)
    report = preflight.Report(slug="manfred")

    preflight.check_live("manfred", report, "https://example.test")

    finding = next(
        item
        for item in report.findings
        if item.code == "live_public_payload_forbidden_fields"
    )
    assert finding.status == "fail"
    assert finding.detail == {
        "route": "archive_json",
        "fields": [
            "$.fliplink_publications[0].provider_metadata.access_token"
        ],
        "omitted_count": 0,
    }


def test_preflight_live_rejects_family_items_in_public_archive_projection(monkeypatch) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_payload = {
        "memory_cards": [
            {"body": "[stark redigiert] Familie", "title": "Schach"}
        ],
        "external_sources": [{"url": "https://sources.example/manfred"}],
        "suggested_prompts": ["Was ist belegt?"],
    }
    archive_payload = {
        "fliplink_publications": [
            {
                "id": "family-only",
                "audience": "family",
                "review_status": "published",
                "url": "https://archive.example/family",
            }
        ]
    }

    def fake_http_request(
        url: str, *, method: str = "GET", body: bytes | None = None, headers=None
    ):
        if url.endswith("/speech-synthesize"):
            return 400, '{"error":{"code":"unsupported_public_tts_fields"}}'
        if "/files/" in url:
            return 404, ""
        if url.endswith("/manfred.json"):
            return 200, json.dumps(public_payload)
        if url.endswith("/voice-config"):
            return 200, "{}"
        if url.endswith("/archive.json"):
            return 200, json.dumps(archive_payload)
        return 200, "<html></html>"

    monkeypatch.setattr(preflight, "http_request", fake_http_request)
    report = preflight.Report(slug="manfred")

    preflight.check_live("manfred", report, "https://example.test")

    finding = next(
        item
        for item in report.findings
        if item.code == "live_archive_projection_contains_nonpublic_items"
    )
    assert finding.status == "fail"
    assert finding.detail == {
        "nonpublic_item_count": 1,
        "unapproved_publication_count": 0,
    }


def test_preflight_rejects_malformed_joggai_receipt_without_crashing(
    monkeypatch, tmp_path
) -> None:
    import scripts.memorial_flagship_preflight as preflight

    public_root = tmp_path / "public"
    bundle = public_root / "manfred"
    (bundle / "receipts").mkdir(parents=True)
    (bundle / "receipts" / "bad.json").write_text("{not-json", encoding="utf-8")
    (bundle / "video.mp4").write_bytes(b"video")
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "revoked": False,
                },
                "public_documents": [
                    {
                        "provider": "joggai",
                        "asset_relpath": "video.mp4",
                        "receipt_relpath": "receipts/bad.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "public_memorial_root", lambda: public_root)

    report = preflight.Report(slug="manfred")
    preflight.check_filesystem("manfred", report)

    assert any(
        item.status == "fail" and item.code == "joggai_public_asset_receipt_invalid"
        for item in report.findings
    )


def test_preflight_rejects_unsafe_slug_before_filesystem_access(monkeypatch, tmp_path) -> None:
    import scripts.memorial_flagship_preflight as preflight

    monkeypatch.setattr(preflight, "public_memorial_root", lambda: tmp_path)
    report = preflight.Report(slug="../private")

    preflight.check_filesystem("../private", report)

    assert [(item.status, item.code) for item in report.findings] == [
        ("fail", "slug_invalid")
    ]
