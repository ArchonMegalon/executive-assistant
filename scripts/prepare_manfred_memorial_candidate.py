#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import functools
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

SOURCE_ROOT = Path(__file__).resolve().parents[1]
EA_SOURCE_ROOT = SOURCE_ROOT / "ea"
for import_root in (SOURCE_ROOT, EA_SOURCE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.services.memorial_release_policy import (  # noqa: E402
    evaluate_memorial_voice_release_payload,
)
from app.services.manfred_voice_signing import (  # noqa: E402
    MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
    MANFRED_PROVIDER_FREE_CANDIDATE_BOUNDARY,
)

try:
    from scripts.manfred_candidate_fleet_lock import hold_candidate_fleet_lock
    from scripts.materialize_release_authority_status import build_status
    from scripts.verify_deploy_context import verify as verify_deploy_context
    from scripts.verify_release_authority import validate_release_authority
    from scripts.verify_release_manifest_runtime_mode import (
        validate_release_contract as validate_release_runtime_mode,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from manfred_candidate_fleet_lock import hold_candidate_fleet_lock
    from materialize_release_authority_status import build_status
    from verify_deploy_context import verify as verify_deploy_context
    from verify_release_authority import validate_release_authority
    from verify_release_manifest_runtime_mode import (
        validate_release_contract as validate_release_runtime_mode,
    )


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_projection.v3"
PROPERTY_PUBLICATION_AUTHORITY_SCHEMA = (
    "propertyquarry.generated-viewer-publication-authority.v1"
)
PROPERTY_PUBLIC_TOUR_PACKAGE_SCHEMA = (
    "propertyquarry.public-tour-generated-viewer-package.v1"
)
PROPERTY_RECONSTRUCTION_SCHEMA = (
    "propertyquarry.generated-reconstruction-publication.v1"
)
PROPERTY_AUTHORITY_OWNER = "PropertyQuarry"
PROPERTY_REPOSITORY = "ArchonMegalon/property"
PROPERTY_AUTHORIZED_SLUG = "360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
PROPERTY_ARTIFACT_COMMIT = "dd81d16421339d1ac4ca9f01d65f5ebcf607258f"
PROPERTY_PACKAGER_COMMIT = "b5eb627267dadb8dd5115dde7643cd8bdbad3317"
PROPERTY_USER_INSTRUCTION_SHA256 = (
    "4763872ed9080c1aae6fa6c16b923ed79ad8e776068a40fa960520d8e646e265"
)
PROPERTY_FINAL_REVIEW_SHA256 = (
    "08b79e6b69cdb6559339919bd9c9f414aa11cf747848e6a98565e3b59cef0c8d"
)
PROPERTY_BROWSER_REVIEW_SHA256 = (
    "866bc0c59952d1000a34d0685d31b539cde96beea3ab6598604f371e47c894c3"
)
PROPERTY_AUTHORITY_SHA256 = (
    "d4c45dcf5e9d09eb092934e3b2b586a8dda14ab5e320e0ae19b62c1ed2e4d9f1"
)
PROPERTY_TOUR_SHA256 = (
    "c5aa916d54bd7c549042c4e856c411a4a0f9f573e0354f6c27e555145489642c"
)
PROPERTY_PRE_AUTHORITY_SHA256 = (
    "0e35c90d5f7c66324e386a1e92643d5c3c07c668bcd35f984d297e4825568da0"
)
PROPERTY_ALLOWED_PUBLIC_ORIGINS = frozenset(
    {"https://myexternalbrain.com", "https://propertyquarry.com"}
)
PROPERTY_PRE_AUTHORITY_CANONICALIZATION = (
    "utf8_sorted_keys_compact_ensure_ascii_false_no_trailing_lf_"
    "with_publication_authority_receipt_sha256_null"
)
# Compatibility defaults for the low-level spatial intake helpers. Candidate
# preparation still requires both receipt paths explicitly, and the helpers
# continue to verify the exact pinned bytes, schemas, statuses, and digests.
PROPERTY_FINAL_REVIEW_RECEIPT = Path(
    "/home/tibor/.local/share/ea-spatial-review/"
    "20260714-neustift-viewer-accessibility-v1/flagship-3d-final-receipt.json"
)
PROPERTY_BROWSER_REVIEW_RECEIPT = Path(
    "/home/tibor/.local/share/ea-spatial-review/"
    "20260714-neustift-viewer-accessibility-v1/browser-audit/"
    "exact-viewer-browser-audit-v3.json"
)
SPATIAL_HANDOFF_SCHEMA = "ea.manfred_spatial_candidate_handoff.v1"
SPATIAL_PROJECTION_SCHEMA = "ea.manfred_memorial_spatial_projection.v2"
SPATIAL_HANDOFF_SCOPE = "candidate_spatial_handoff"
PROJECT_NAME_PREFIX = "ea-manfred-candidate-"
PRIVATE_CONTEXT_FILENAME = "memorial_private_context.json"
HELPER_IMAGE = "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229"
PUBLIC_GIT_FILES = (
    "memorial.json",
    "archive_registry.json",
    "archive_registry.generated.json",
)
PRIVATE_METADATA_FILES = (
    PRIVATE_CONTEXT_FILENAME,
    "audio_identification_safe_profile.json",
    "llm_profile_notes.json",
    "mail_cluster_report.json",
    "ratings.json",
    "transcript_persona_workflow.md",
    "transcript_signal_report.json",
    "tts_voice.json",
    "voice_ab.json",
    "voice_ab_challengers.json",
    "voice_profile_manifest.json",
)
PUBLIC_ASSET_SUFFIXES = {
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".svg",
    ".wav",
    ".webp",
}
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_SPATIAL_SOURCE_FILES = 64
MAX_SPATIAL_SOURCE_BYTES = 256 * 1024 * 1024
MAX_SPATIAL_FILE_BYTES = 32 * 1024 * 1024
MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES = 1024 * 1024
SPATIAL_LAYOUT_ROLE_COUNTS = {
    "floorplan_texture": 1,
    "reconstruction_manifest": 1,
    "viewer_document": 1,
    "viewer_module": 2,
}
SPATIAL_VIEWER_MODULE_PATHS = {
    "generated-reconstruction/vendor/three.module.js",
    "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
}
SPATIAL_PRIVATE_PATH_TOKENS = {
    ".env",
    "backup",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "debug",
    "private",
    "probe",
    "raw",
    "raw-bundle",
    "raw-export",
    "secret",
    "secrets",
    "session",
    "test",
    "tmp",
    "token",
    "tokens",
}
SPATIAL_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VOICE_BINDING_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._/+:-]{0,127}$")
MANFRED_TTS_PROVIDER = "unmixr_clone"
MANFRED_TTS_MODEL = "unmixr"
MANFRED_PROVIDER_VOICE_ID_PLACEHOLDER = "${UNMIXR_VOICE_ID}"
HOSTED_CLONE_VOICE_CONFIG_FIELDS = frozenset(
    {
        "consent_basis",
        "lang",
        "notes",
        "pitch",
        "provider_language",
        "rate",
        "synthetic_voice_clone_of_memorial_person",
        "tts_backup_candidates",
        "tts_base_voice_variant",
        "tts_mode",
        "tts_plugin",
        "tts_plugin_voice_id",
        "tts_postprocess_profile",
        "unmixr_pronunciation_dict",
        "unmixr_speaking_pitch",
        "unmixr_speaking_rate",
        "unmixr_speaking_volume",
        "voice_consent",
        "voice_label",
        "voice_name_hints",
        "voice_profile_id",
        "volume",
    }
)
HOSTED_CLONE_VOICE_CONSENT_FIELDS = frozenset(
    {
        "authorized_at",
        "authorized_by",
        "revoked",
        "scope",
        "source_assets_reviewed",
        "status",
    }
)
HOSTED_CLONE_BACKUP_CANDIDATE_FIELDS = frozenset(
    {
        "detail",
        "provider",
        "reason",
        "status",
        "voice_label",
    }
)
HOSTED_CLONE_PRONUNCIATION_DICT = {
    "Klar": "Klaar",
    "Ordne": "Ord-ne",
    "klar": "klaar",
    "ordne": "ord-ne",
}
HOSTED_CLONE_PLACEHOLDER_ID_PATHS = frozenset(
    {
        ("tts_plugin_voice_id",),
        ("voice_profile_id",),
    }
)
HOSTED_CLONE_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "api_secret",
        "client_secret",
        "clone_id",
        "credential",
        "credentials",
        "password",
        "provider_voice_id",
        "raw_provider_voice_id",
        "raw_voice_id",
        "refresh_token",
        "secret",
        "token",
        "voice_id",
    }
)
HOSTED_CLONE_VOICE_MANIFEST_SCHEMA = (
    "ea.manfred_provider_managed_hosted_clone_manifest.v1"
)
HOSTED_CLONE_PROVENANCE_VOICE_MANIFEST_SCHEMA = (
    "ea.manfred_provider_managed_hosted_clone_manifest.v2"
)
VOICE_SOURCE_PROVENANCE_RECEIPT_TYPE = "ea.memorial_voice_source_intake.v1"
VOICE_SOURCE_PROVENANCE_READY_STATUS = "ready_for_single_candidate_clone"
VOICE_SOURCE_PROVENANCE_RECEIPT_SHA256_SEMANTICS = (
    "sha256_exact_private_receipt_bytes"
)
VOICE_ARTIFACT_DIGEST_SEMANTICS = "sha256_exact_file_bytes"
VOICE_REFERENCE_AGGREGATE_SEMANTICS = (
    "sha256_canonical_json_utf8_sorted_reference_sha256_list_v1"
)
PROVIDER_VOICE_ID_SHA256_SEMANTICS = "sha256_utf8_provider_voice_id"
VOICE_IDENTITY_SHA256_SEMANTICS = "sha256_canonical_json_utf8_voice_identity_v1"
CANDIDATE_RELEASE_AUTHORITY_SCHEMA = "ea.manfred_candidate_release_authority.v2"
CANDIDATE_RELEASE_AUTHORITY_DIRNAME = "release-authority"
CANDIDATE_RELEASE_AUTHORITY_CONTAINER_ROOT = Path("/data/release-authority")
VOICE_ACCESS_MODE_TEXT_ONLY = "text-only"
VOICE_ACCESS_MODE_PUBLIC_RELEASE = "public-release"
VOICE_ACCESS_MODE_PUBLIC_EVALUATION = "owner-authorized-public-evaluation"
CANDIDATE_RELEASE_AUTHORITY_FILENAMES = {
    "deploy_context": "deploy_context.generated.json",
    "voice_release": "manfred_voice_release.generated.json",
    "project_modes": "PROJECT_MODES.generated.json",
    "release_manifest": "release_manifest.generated.json",
    "release_status": "release_authority_status.generated.json",
    "receipt": "candidate_release_authority.json",
}
OFFICIAL_EA_REMOTE_ORIGIN = "https://github.com/ArchonMegalon/executive-assistant.git"
OFFICIAL_EA_REMOTE_ORIGINS = frozenset({OFFICIAL_EA_REMOTE_ORIGIN})
LIVE_REMOTE_REF_EVIDENCE = "isolated_git_ls_remote_exact_https_ref"
PRIVATE_OUTPUT_MAX_BYTES = 8 * 1024 * 1024


def _validate_project_name(value: object) -> str:
    project = str(value or "").strip()
    suffix = project.removeprefix(PROJECT_NAME_PREFIX)
    if (
        project != project.lower()
        or project == "ea"
        or not project.startswith(PROJECT_NAME_PREFIX)
        or len(project) > 63
        or len(suffix) < 8
        or re.fullmatch(r"[a-z0-9][a-z0-9-]*", suffix) is None
    ):
        raise ValueError("manfred_candidate_project_name_invalid")
    return project


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    timeout: int | None = None,
    environment: dict[str, str] | None = None,
) -> bytes:
    completed = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=True,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=environment,
    )
    return completed.stdout


def _commit(source_root: Path, ref: str) -> str:
    value = (
        _run(
            [
                "git",
                "rev-parse",
                "--verify",
                f"{str(ref or 'HEAD').strip()}^{{commit}}",
            ],
            cwd=source_root,
        )
        .decode("ascii")
        .strip()
        .lower()
    )
    if len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("manfred_candidate_commit_invalid")
    return value


def _commit_generated_at(source_root: Path, commit: str) -> str:
    try:
        raw = (
            _run(
                ["git", "show", "-s", "--format=%cI", commit],
                cwd=source_root,
            )
            .decode("ascii", errors="strict")
            .strip()
        )
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        raise ValueError("manfred_candidate_commit_time_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("manfred_candidate_commit_time_invalid")
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _git_blob(source_root: Path, commit: str, path: str) -> bytes:
    return _run(["git", "show", f"{commit}:{path}"], cwd=source_root)


def _safe_relative(value: object, *, suffix_required: bool = False) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("manfred_candidate_asset_path_invalid")
    path = Path(*pure.parts)
    if suffix_required and path.suffix.lower() not in PUBLIC_ASSET_SUFFIXES:
        raise ValueError("manfred_candidate_asset_type_forbidden")
    return path


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _voice_reference_aggregate_sha256(reference_sha256s: list[str]) -> str:
    if type(reference_sha256s) is not list or any(
        type(value) is not str
        or not SHA256_RE.fullmatch(value)
        for value in reference_sha256s
    ):
        raise ValueError("manfred_candidate_voice_reference_digest_invalid")
    encoded = json.dumps(
        sorted(reference_sha256s),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256(encoded)


def _validated_voice_source_provenance_receipt_sha256(
    receipt_bytes: bytes,
) -> str:
    receipt = _strict_json_object(
        receipt_bytes,
        error="manfred_candidate_voice_source_provenance_invalid",
    )
    subject = receipt.get("subject")
    authorization = receipt.get("user_authorization")
    source = receipt.get("source")
    selected_audio = receipt.get("selected_audio")
    speaker_isolation = receipt.get("speaker_isolation")
    publication_constraints = receipt.get("publication_constraints")
    if (
        receipt.get("receipt_type") != VOICE_SOURCE_PROVENANCE_RECEIPT_TYPE
        or receipt.get("status") != VOICE_SOURCE_PROVENANCE_READY_STATUS
        or type(subject) is not dict
        or subject.get("memorial_slug") != "manfred"
        or subject.get("name") != "Manfred Hoza"
        or type(authorization) is not dict
        or authorization.get("received") is not True
        or authorization.get("provider_upload_for_voice_cloning") is not True
        or type(source) is not dict
        or not SHA256_RE.fullmatch(str(source.get("raw_sha256") or ""))
        or type(selected_audio) is not dict
        or not SHA256_RE.fullmatch(str(selected_audio.get("sha256") or ""))
        or type(speaker_isolation) is not dict
        or speaker_isolation.get("required_speaker") != "Manfred Hoza"
        or not str(speaker_isolation.get("excluded_speaker") or "").strip()
        or speaker_isolation.get("contiguous_segment") is not True
        or speaker_isolation.get("video_contact_sheet_reviewed") is not True
        or speaker_isolation.get("first_person_answer_only") is not True
        or speaker_isolation.get("interviewer_turn_detected") is not False
        or type(publication_constraints) is not dict
        or publication_constraints.get("source_media_must_remain_private")
        is not True
        or publication_constraints.get(
            "voice_profile_identifier_must_remain_private"
        )
        is not True
    ):
        raise ValueError("manfred_candidate_voice_source_provenance_invalid")
    return _sha256(receipt_bytes)


def _assert_hosted_clone_config_has_no_secret_id_fields(
    value: object,
    *,
    path: tuple[str, ...] = (),
) -> None:
    if type(value) is dict:
        for raw_key, nested in value.items():
            key = str(raw_key).strip().casefold().replace("-", "_")
            child_path = (*path, key)
            secret_or_id_looking = (
                key in HOSTED_CLONE_FORBIDDEN_FIELD_NAMES
                or key.endswith(
                    (
                        "_access_token",
                        "_api_key",
                        "_api_secret",
                        "_client_secret",
                        "_clone_id",
                        "_credential",
                        "_credentials",
                        "_password",
                        "_provider_voice_id",
                        "_raw_voice_id",
                        "_refresh_token",
                        "_secret",
                        "_token",
                        "_voice_id",
                    )
                )
            )
            if (
                secret_or_id_looking
                and child_path not in HOSTED_CLONE_PLACEHOLDER_ID_PATHS
            ):
                raise ValueError(
                    "manfred_candidate_voice_config_secret_field_forbidden"
                )
            _assert_hosted_clone_config_has_no_secret_id_fields(
                nested,
                path=child_path,
            )
    elif type(value) is list:
        for nested in value:
            _assert_hosted_clone_config_has_no_secret_id_fields(
                nested,
                path=path,
            )


def _validate_hosted_clone_config_schema(
    voice_config: dict[str, object],
) -> None:
    _assert_hosted_clone_config_has_no_secret_id_fields(voice_config)
    consent = voice_config.get("voice_consent")
    backups = voice_config.get("tts_backup_candidates")
    pronunciation_dict = voice_config.get("unmixr_pronunciation_dict")
    if (
        set(voice_config) != HOSTED_CLONE_VOICE_CONFIG_FIELDS
        or voice_config.get("lang") != "de-AT"
        or voice_config.get("provider_language") != "de-AT"
        or type(consent) is not dict
        or set(consent) != HOSTED_CLONE_VOICE_CONSENT_FIELDS
        or type(backups) is not dict
        or any(
            type(provider) is not str
            or not provider.strip()
            or type(candidate) is not dict
            or set(candidate) != HOSTED_CLONE_BACKUP_CANDIDATE_FIELDS
            for provider, candidate in backups.items()
        )
        or type(pronunciation_dict) is not dict
        or pronunciation_dict != HOSTED_CLONE_PRONUNCIATION_DICT
        or type(voice_config.get("voice_name_hints")) is not list
        or any(
            type(value) is not str or not value.strip()
            for value in voice_config.get("voice_name_hints", [])
        )
        or type(consent.get("scope")) is not list
        or any(
            type(value) is not str or not value.strip()
            for value in consent.get("scope", [])
        )
    ):
        raise ValueError("manfred_candidate_voice_config_fields_invalid")


def _hosted_clone_voice_binding(
    *,
    voice_config_bytes: bytes,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
    source_provenance_receipt_sha256: str = "",
) -> tuple[bytes, dict[str, str]]:
    voice_config = _strict_json_object(
        voice_config_bytes,
        error="manfred_candidate_voice_config_invalid",
    )
    _validate_hosted_clone_config_schema(voice_config)
    provider_id_fields = {
        name: str(voice_config.get(name) or "").strip()
        for name in ("tts_plugin_voice_id", "voice_profile_id")
    }
    if (
        voice_config.get("tts_plugin") != MANFRED_TTS_PROVIDER
        or voice_config.get("tts_mode") != MANFRED_TTS_PROVIDER
        or voice_config.get("tts_base_voice_variant") != MANFRED_TTS_MODEL
        or not SHA256_RE.fullmatch(provider_voice_id_sha256)
        or tts_provider != MANFRED_TTS_PROVIDER
        or tts_model != MANFRED_TTS_MODEL
        or any(
            value != MANFRED_PROVIDER_VOICE_ID_PLACEHOLDER
            for value in provider_id_fields.values()
        )
    ):
        raise ValueError("manfred_candidate_voice_config_invalid")
    source_provenance_receipt_sha256 = str(
        source_provenance_receipt_sha256 or ""
    ).strip()
    if (
        source_provenance_receipt_sha256
        and not SHA256_RE.fullmatch(source_provenance_receipt_sha256)
    ):
        raise ValueError("manfred_candidate_voice_source_provenance_invalid")

    voice_config_sha256 = _sha256(voice_config_bytes)
    reference_aggregate_sha256 = _voice_reference_aggregate_sha256([])
    manifest = {
        "schema": (
            HOSTED_CLONE_PROVENANCE_VOICE_MANIFEST_SCHEMA
            if source_provenance_receipt_sha256
            else HOSTED_CLONE_VOICE_MANIFEST_SCHEMA
        ),
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "memorial_slug": "manfred",
        "provider_managed_hosted_clone": True,
        "no_local_reference_assets": True,
        "reference_assets": [],
        "voice_config_sha256": voice_config_sha256,
        "voice_artifact_digest_semantics": VOICE_ARTIFACT_DIGEST_SEMANTICS,
        "voice_reference_aggregate_sha256": reference_aggregate_sha256,
        "voice_reference_aggregate_sha256_semantics": (
            VOICE_REFERENCE_AGGREGATE_SEMANTICS
        ),
        "provider_voice_id_sha256": provider_voice_id_sha256,
        "provider_voice_id_sha256_semantics": (
            PROVIDER_VOICE_ID_SHA256_SEMANTICS
        ),
        "tts_provider": tts_provider,
        "tts_model": tts_model,
        "raw_provider_voice_id_recorded": False,
        "provider_credentials_recorded": False,
    }
    if source_provenance_receipt_sha256:
        manifest.update(
            {
                "source_provenance_receipt_embedded": False,
                "source_provenance_receipt_sha256": (
                    source_provenance_receipt_sha256
                ),
                "source_provenance_receipt_sha256_semantics": (
                    VOICE_SOURCE_PROVENANCE_RECEIPT_SHA256_SEMANTICS
                ),
            }
        )
    voice_manifest_bytes = _receipt_bytes(manifest)
    voice_identity = _voice_identity(
        voice_config_sha256=voice_config_sha256,
        voice_manifest_sha256=_sha256(voice_manifest_bytes),
        voice_reference_aggregate_sha256=reference_aggregate_sha256,
        provider_voice_id_sha256=provider_voice_id_sha256,
        tts_provider=tts_provider,
        tts_model=tts_model,
    )
    return voice_manifest_bytes, voice_identity


def _voice_identity(
    *,
    voice_config_sha256: str,
    voice_manifest_sha256: str,
    voice_reference_aggregate_sha256: str,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
) -> dict[str, str]:
    values = {
        "provider_voice_id_sha256": str(provider_voice_id_sha256 or "").strip(),
        "tts_model": str(tts_model or "").strip(),
        "tts_provider": str(tts_provider or "").strip(),
        "voice_config_sha256": str(voice_config_sha256 or "").strip(),
        "voice_manifest_sha256": str(voice_manifest_sha256 or "").strip(),
        "voice_reference_aggregate_sha256": str(
            voice_reference_aggregate_sha256 or ""
        ).strip(),
    }
    if (
        any(
            not SHA256_RE.fullmatch(values[name])
            for name in (
                "provider_voice_id_sha256",
                "voice_config_sha256",
                "voice_manifest_sha256",
                "voice_reference_aggregate_sha256",
            )
        )
        or values["tts_provider"] != MANFRED_TTS_PROVIDER
        or values["tts_model"] != MANFRED_TTS_MODEL
        or not VOICE_BINDING_LABEL_RE.fullmatch(values["tts_provider"])
        or not VOICE_BINDING_LABEL_RE.fullmatch(values["tts_model"])
    ):
        raise ValueError("manfred_candidate_voice_identity_invalid")
    identity_sha256 = _sha256(
        json.dumps(
            values,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    )
    return {
        **values,
        "image_id_semantics": "docker_image_id_sha256",
        "provider_voice_id_sha256_semantics": (
            PROVIDER_VOICE_ID_SHA256_SEMANTICS
        ),
        "voice_artifact_digest_semantics": VOICE_ARTIFACT_DIGEST_SEMANTICS,
        "voice_identity_sha256": identity_sha256,
        "voice_identity_sha256_semantics": VOICE_IDENTITY_SHA256_SEMANTICS,
        "voice_reference_aggregate_sha256_semantics": (
            VOICE_REFERENCE_AGGREGATE_SEMANTICS
        ),
    }


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _receipt_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )


def _spatial_path_has_private_raw_pattern(path: str) -> bool:
    lowered = str(path or "").strip().replace("\\", "/").lower()
    tokens = {
        token
        for part in PurePosixPath(lowered).parts
        for token in re.split(r"[^a-z0-9.]+", part)
        if token
    }
    return bool(tokens.intersection(SPATIAL_PRIVATE_PATH_TOKENS))


def _canonical_json_bytes_without_lf(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("manfred_candidate_spatial_json_invalid") from exc


def _strict_json_object(content: bytes, *, error: str) -> dict[str, object]:
    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(error)
            payload[key] = value
        return payload

    def reject_constant(_value: str) -> None:
        raise ValueError(error)

    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not isinstance(payload, dict):
        raise ValueError(error)
    return payload


def _spatial_payload_has_private_host_path(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _spatial_payload_has_private_host_path(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_spatial_payload_has_private_host_path(child) for child in value)
    if not isinstance(value, str):
        return False
    normalized = value.strip().replace("\\", "/").lower()
    return (
        normalized.startswith(("/home/", "/tmp/", "/var/tmp/", "file://", "pcloud://"))
        or "/home/" in normalized
        or "/tmp/" in normalized
        or "/var/tmp/" in normalized
    )


def _spatial_release_contract(
    payload: dict[str, object], *, expected_slug: str = ""
) -> tuple[str, list[str], str, str]:
    slug = str(payload.get("slug") or "").strip()
    if (
        not SPATIAL_SLUG_RE.fullmatch(slug)
        or slug in {".", ".."}
        or (expected_slug and slug != expected_slug)
    ):
        raise ValueError("manfred_candidate_spatial_slug_invalid")
    release_raw = payload.get("generated_viewer_release")
    generated_raw = payload.get("generated_reconstruction")
    if not isinstance(release_raw, dict) or not isinstance(generated_raw, dict):
        raise ValueError("manfred_candidate_spatial_release_contract_invalid")
    bindings_raw = release_raw.get("asset_bindings")
    if not isinstance(bindings_raw, list) or len(bindings_raw) != 5:
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    role_counts: dict[str, int] = {}
    paths: list[str] = []
    proof_relpath = ""
    viewer_relpath = ""
    floorplan_relpath = ""
    module_paths: set[str] = set()
    expected_mimes = {
        "viewer_document": {"text/html"},
        "reconstruction_manifest": {"application/json"},
        "floorplan_texture": {"image/png"},
        "viewer_module": {"text/javascript"},
    }
    for raw_binding in bindings_raw:
        if not isinstance(raw_binding, dict):
            raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
        path = _safe_relative(raw_binding.get("path")).as_posix()
        role = str(raw_binding.get("role") or "").strip().lower()
        digest = str(raw_binding.get("sha256") or "").strip().lower()
        mime_type = str(raw_binding.get("mime_type") or "").strip().lower()
        size_bytes = raw_binding.get("size_bytes")
        if (
            set(raw_binding) != {"path", "sha256", "size_bytes", "mime_type", "role"}
            or not path.startswith("generated-reconstruction/")
            or _spatial_path_has_private_raw_pattern(path)
            or role not in SPATIAL_LAYOUT_ROLE_COUNTS
            or mime_type not in expected_mimes.get(role, set())
            or not SHA256_RE.fullmatch(digest)
            or type(size_bytes) is not int
            or int(size_bytes) <= 0
            or int(size_bytes) > MAX_SPATIAL_FILE_BYTES
        ):
            raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
        paths.append(path)
        role_counts[role] = role_counts.get(role, 0) + 1
        if role == "reconstruction_manifest":
            proof_relpath = path
        elif role == "viewer_document":
            viewer_relpath = path
        elif role == "floorplan_texture":
            floorplan_relpath = path
        elif role == "viewer_module":
            module_paths.add(path)
    if (
        role_counts != SPATIAL_LAYOUT_ROLE_COUNTS
        or len(set(paths)) != 5
        or str(release_raw.get("viewer_relpath") or "").strip() != viewer_relpath
        or str(generated_raw.get("manifest_relpath") or "").strip() != proof_relpath
        or viewer_relpath != "generated-reconstruction/viewer.html"
        or proof_relpath != "generated-reconstruction/reconstruction.json"
        or floorplan_relpath
        != str(generated_raw.get("floorplan_relpath") or "").strip()
        or not floorplan_relpath.startswith("generated-reconstruction/")
        or Path(floorplan_relpath).suffix.lower() != ".png"
        or module_paths != SPATIAL_VIEWER_MODULE_PATHS
    ):
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    return slug, sorted(paths), viewer_relpath, proof_relpath


def _spatial_package_sha256(snapshot: dict[str, bytes]) -> str:
    rows = [
        {
            "path": path,
            "sha256": _sha256(content),
            "size_bytes": len(content),
        }
        for path, content in sorted(snapshot.items())
    ]
    return _sha256(_canonical_json_bytes_without_lf(rows))


def _safe_spatial_source_mode(mode: int, *, directory: bool) -> bool:
    normalized = stat.S_IMODE(mode)
    if normalized & 0o7000 or normalized & 0o002:
        return False
    if directory:
        return bool(normalized & 0o500 == 0o500)
    return bool(normalized & 0o400)


def _read_spatial_file_snapshot(path: Path, *, require_sanitized_modes: bool) -> bytes:
    path = Path(os.path.abspath(os.fspath(path.expanduser())))
    if path.name in {"", ".", ".."}:
        raise ValueError("manfred_candidate_spatial_source_invalid")
    parent_descriptor = _open_directory_path_nofollow(path.parent)
    try:

        def identity(metadata: os.stat_result) -> tuple[int, ...]:
            return (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_nlink,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )

        try:
            initial = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_invalid") from exc
        expected_mode = 0o644
        if (
            not stat.S_ISREG(initial.st_mode)
            or stat.S_ISLNK(initial.st_mode)
            or initial.st_nlink != 1
            or initial.st_size <= 0
            or initial.st_size > MAX_SPATIAL_FILE_BYTES
            or (
                require_sanitized_modes
                and stat.S_IMODE(initial.st_mode) != expected_mode
            )
            or (
                not require_sanitized_modes
                and not _safe_spatial_source_mode(initial.st_mode, directory=False)
            )
        ):
            raise ValueError("manfred_candidate_spatial_source_invalid")
        flags = (
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_invalid") from exc
        try:
            opened = os.fstat(descriptor)
            if identity(initial) != identity(opened):
                raise ValueError("manfred_candidate_spatial_source_changed")
            chunks: list[bytes] = []
            remaining = int(opened.st_size)
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("manfred_candidate_spatial_source_changed")
                chunks.append(chunk)
                remaining -= len(chunk)
            if identity(opened) != identity(os.fstat(descriptor)):
                raise ValueError("manfred_candidate_spatial_source_changed")
        finally:
            os.close(descriptor)
        try:
            final_path_metadata = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_changed") from exc
        if identity(initial) != identity(final_path_metadata):
            raise ValueError("manfred_candidate_spatial_source_changed")
        return b"".join(chunks)
    finally:
        os.close(parent_descriptor)


def _open_directory_path_nofollow(
    path: Path,
    *,
    create_missing: bool = False,
    create_mode: int = 0o700,
) -> int:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        raise ValueError("manfred_candidate_spatial_nofollow_unavailable")
    flags = os.O_RDONLY | os.O_CLOEXEC | directory_flag | nofollow
    try:
        descriptor = os.open("/", flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_spatial_root_invalid") from exc
    try:
        for part in normalized.parts[1:]:
            if part in {"", ".", ".."} or "/" in part:
                raise ValueError("manfred_candidate_spatial_path_invalid")
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError as exc:
                if not create_missing:
                    raise ValueError("manfred_candidate_spatial_root_invalid") from exc
                try:
                    os.mkdir(part, create_mode, dir_fd=descriptor)
                    child = os.open(part, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_spatial_output_parent_invalid"
                    ) from exc
            except OSError as exc:
                raise ValueError("manfred_candidate_spatial_root_invalid") from exc
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _spatial_tree_snapshot(
    root: Path,
    *,
    require_sanitized_modes: bool,
    expected_root_identity: tuple[int, int] | None = None,
    expected_file_identities: dict[str, tuple[int, int]] | None = None,
) -> dict[str, bytes]:
    root = Path(os.path.abspath(os.fspath(root.expanduser())))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError("manfred_candidate_spatial_nofollow_unavailable")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | nofollow
    file_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0) | nofollow

    def directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def file_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def validate_directory(metadata: os.stat_result, *, root_entry: bool) -> None:
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(
                "manfred_candidate_spatial_root_invalid"
                if root_entry
                else "manfred_candidate_spatial_source_invalid"
            )
        if require_sanitized_modes:
            safe_mode = stat.S_IMODE(metadata.st_mode) == 0o755
        else:
            safe_mode = _safe_spatial_source_mode(metadata.st_mode, directory=True)
        if not safe_mode:
            raise ValueError(
                "manfred_candidate_spatial_root_invalid"
                if root_entry
                else "manfred_candidate_spatial_mode_invalid"
            )

    root_descriptor = _open_directory_path_nofollow(root)
    files: dict[str, bytes] = {}
    total_bytes = 0

    def walk(directory_descriptor: int, relative: tuple[str, ...]) -> None:
        nonlocal total_bytes
        before = os.fstat(directory_descriptor)
        validate_directory(before, root_entry=False)
        try:
            with os.scandir(directory_descriptor) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_invalid") from exc
        for name in names:
            if name in {"", ".", ".."} or "/" in name:
                raise ValueError("manfred_candidate_spatial_path_invalid")
            try:
                initial = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise ValueError("manfred_candidate_spatial_source_changed") from exc
            projected = (*relative, name)
            relpath = PurePosixPath(*projected).as_posix()
            if stat.S_ISLNK(initial.st_mode):
                raise ValueError("manfred_candidate_spatial_symlink_forbidden")
            if stat.S_ISDIR(initial.st_mode):
                validate_directory(initial, root_entry=False)
                try:
                    child_descriptor = os.open(
                        name,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_spatial_source_changed"
                    ) from exc
                try:
                    opened = os.fstat(child_descriptor)
                    if directory_identity(initial) != directory_identity(opened):
                        raise ValueError("manfred_candidate_spatial_source_changed")
                    walk(child_descriptor, projected)
                    if directory_identity(opened) != directory_identity(
                        os.fstat(child_descriptor)
                    ):
                        raise ValueError("manfred_candidate_spatial_source_changed")
                finally:
                    os.close(child_descriptor)
                try:
                    final_path_metadata = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_spatial_source_changed"
                    ) from exc
                if directory_identity(initial) != directory_identity(
                    final_path_metadata
                ):
                    raise ValueError("manfred_candidate_spatial_source_changed")
                continue
            if not stat.S_ISREG(initial.st_mode):
                raise ValueError("manfred_candidate_spatial_nonregular_forbidden")
            expected_mode = 0o644
            if (
                initial.st_nlink != 1
                or initial.st_size <= 0
                or initial.st_size > MAX_SPATIAL_FILE_BYTES
                or (
                    require_sanitized_modes
                    and stat.S_IMODE(initial.st_mode) != expected_mode
                )
                or (
                    not require_sanitized_modes
                    and not _safe_spatial_source_mode(initial.st_mode, directory=False)
                )
            ):
                raise ValueError("manfred_candidate_spatial_source_invalid")
            try:
                file_descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=directory_descriptor,
                )
            except OSError as exc:
                raise ValueError("manfred_candidate_spatial_source_changed") from exc
            try:
                opened = os.fstat(file_descriptor)
                if (
                    file_identity(initial) != file_identity(opened)
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (
                        expected_file_identities is not None
                        and (opened.st_dev, opened.st_ino)
                        != expected_file_identities.get(relpath)
                    )
                ):
                    raise ValueError("manfred_candidate_spatial_source_changed")
                chunks: list[bytes] = []
                remaining = int(opened.st_size)
                while remaining:
                    chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("manfred_candidate_spatial_source_changed")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                final = os.fstat(file_descriptor)
                if file_identity(opened) != file_identity(final):
                    raise ValueError("manfred_candidate_spatial_source_changed")
                content = b"".join(chunks)
            finally:
                os.close(file_descriptor)
            try:
                final_path_metadata = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise ValueError("manfred_candidate_spatial_source_changed") from exc
            if file_identity(initial) != file_identity(final_path_metadata):
                raise ValueError("manfred_candidate_spatial_source_changed")
            files[relpath] = content
            total_bytes += len(content)
            if (
                len(files) > MAX_SPATIAL_SOURCE_FILES
                or total_bytes > MAX_SPATIAL_SOURCE_BYTES
            ):
                raise ValueError("manfred_candidate_spatial_bundle_oversize")
        if directory_identity(before) != directory_identity(
            os.fstat(directory_descriptor)
        ):
            raise ValueError("manfred_candidate_spatial_source_changed")

    try:
        root_metadata = os.fstat(root_descriptor)
        if (
            expected_root_identity is not None
            and (
                root_metadata.st_dev,
                root_metadata.st_ino,
            )
            != expected_root_identity
        ):
            raise ValueError("manfred_candidate_spatial_root_identity_changed")
        validate_directory(root_metadata, root_entry=True)
        try:
            root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_root_invalid") from exc
        if directory_identity(root_metadata) != directory_identity(root_path_metadata):
            raise ValueError("manfred_candidate_spatial_root_invalid")
        walk(root_descriptor, ())
        final_root_metadata = os.fstat(root_descriptor)
        try:
            final_root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_changed") from exc
        if (
            directory_identity(root_metadata) != directory_identity(final_root_metadata)
            or directory_identity(final_root_metadata)
            != directory_identity(final_root_path_metadata)
            or (
                expected_root_identity is not None
                and (
                    final_root_metadata.st_dev,
                    final_root_metadata.st_ino,
                )
                != expected_root_identity
            )
        ):
            raise ValueError("manfred_candidate_spatial_source_changed")
    finally:
        os.close(root_descriptor)
    if not files:
        raise ValueError("manfred_candidate_spatial_bundle_empty")
    if expected_file_identities is not None and set(files) != set(
        expected_file_identities
    ):
        raise ValueError("manfred_candidate_spatial_source_changed")
    return files


def _verify_spatial_bundle_before_copy(bundle: Path, *, slug: str) -> dict[str, object]:
    verifier = Path(__file__).with_name(
        "verify_public_tour_generated_viewer_release.py"
    )
    try:
        raw = _run(
            [
                sys.executable,
                str(verifier),
                "--bundle-dir",
                str(bundle),
                "--slug",
                slug,
            ]
        )
        receipt = json.loads(raw)
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise ValueError("manfred_candidate_spatial_verifier_blocked") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("pass") is not True
        or receipt.get("status") != "pass"
        or receipt.get("slug") != slug
        or dict(receipt.get("checks") or {}).get("binding_count") != 5
    ):
        raise ValueError("manfred_candidate_spatial_verifier_blocked")
    return receipt


def _property_review_evidence(
    snapshot: dict[str, bytes],
    *,
    final_review_receipt_path: Path,
    browser_review_receipt_path: Path,
) -> dict[str, object]:
    final_path = Path(
        os.path.abspath(os.fspath(final_review_receipt_path.expanduser()))
    )
    browser_path = Path(
        os.path.abspath(os.fspath(browser_review_receipt_path.expanduser()))
    )
    if final_path == browser_path:
        raise ValueError("manfred_candidate_spatial_review_evidence_invalid")
    final_bytes = _read_spatial_file_snapshot(final_path, require_sanitized_modes=False)
    browser_bytes = _read_spatial_file_snapshot(
        browser_path, require_sanitized_modes=False
    )
    for path, content, expected in (
        (final_path, final_bytes, PROPERTY_FINAL_REVIEW_SHA256),
        (browser_path, browser_bytes, PROPERTY_BROWSER_REVIEW_SHA256),
    ):
        metadata = os.lstat(path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or _sha256(content) != expected
        ):
            raise ValueError("manfred_candidate_spatial_review_evidence_invalid")
    final = _strict_json_object(
        final_bytes, error="manfred_candidate_spatial_final_review_invalid"
    )
    browser = _strict_json_object(
        browser_bytes, error="manfred_candidate_spatial_browser_review_invalid"
    )
    final_source = dict(final.get("source") or {})
    review_bundle = dict(final.get("review_bundle") or {})
    visual = dict(final.get("visual_verification") or {})
    verification = dict(final.get("verification") or {})
    live_guard = dict(final.get("live_guard") or {})
    if (
        final.get("schema") != "propertyquarry.flagship_3d_review_receipt.v1"
        or final.get("status") != "polished_review_candidate_pass_guarded_not_published"
        or final.get("slug") != PROPERTY_AUTHORIZED_SLUG
        or final_source.get("commit") != PROPERTY_ARTIFACT_COMMIT
        or final_source.get("worktree_clean") is not True
        or review_bundle.get("viewer_sha256")
        != _sha256(snapshot["generated-reconstruction/viewer.html"])
        or review_bundle.get("floorplan_sha256")
        != _sha256(snapshot["generated-reconstruction/source-floorplan.png"])
        or review_bundle.get("runtime_publish_required") is not False
        or review_bundle.get("runtime_publish_ok") is not True
        or review_bundle.get("verified_provider_capture") is not False
        or review_bundle.get("satisfies_verified_tour_gate") is not False
        or visual.get("browser_receipt_sha256") != PROPERTY_BROWSER_REVIEW_SHA256
        or visual.get("browser_status") != "pass"
        or visual.get("browser_failures") != []
        or visual.get("route_status") != "pass"
        or visual.get("route_failures") != []
        or visual.get("route_stop_count") != 9
        or set(visual.get("surfaces") or [])
        != {"desktop", "mobile", "reduced-motion", "webgl-fallback"}
        or dict(verification.get("property_generated_reconstruction") or {}).get(
            "result"
        )
        != "pass"
        or dict(verification.get("property_tour_control_and_importers") or {}).get(
            "result"
        )
        != "pass"
        or dict(
            verification.get("independent_camera_geometry_accessibility_review") or {}
        ).get("result")
        != "approved"
        or dict(
            verification.get("independent_runtime_publish_safety_review") or {}
        ).get("result")
        != "approved"
        or live_guard.get("runtime_mutation_detected") is not False
        or live_guard.get("all_observed_product_routes_guarded_404") is not True
    ):
        raise ValueError("manfred_candidate_spatial_final_review_invalid")
    browser_surfaces = dict(browser.get("surfaces") or {})
    if (
        browser.get("schema") != "propertyquarry.exact_viewer_browser_audit.v3"
        or browser.get("status") != "pass"
        or browser.get("slug") != PROPERTY_AUTHORIZED_SLUG
        or browser.get("failures") != []
        or browser.get("viewer_sha256")
        != _sha256(snapshot["generated-reconstruction/viewer.html"])
        or browser.get("reconstruction_sha256")
        != review_bundle.get("reconstruction_sha256")
        or set(browser_surfaces)
        != {"desktop", "mobile", "reduced-motion", "webgl-fallback"}
    ):
        raise ValueError("manfred_candidate_spatial_browser_review_invalid")
    for name, raw_surface in browser_surfaces.items():
        surface = dict(raw_surface or {})
        expected_status = "not-ready" if name == "webgl-fallback" else "ready"
        if (
            surface.get("http_status") != 200
            or surface.get("viewerStatus") != expected_status
            or surface.get("page_errors") != []
            or surface.get("console_errors") != []
            or surface.get("horizontalOverflowPx") != 0
            or surface.get("undersizedTargets") != []
            or (
                name == "webgl-fallback"
                and (
                    surface.get("alertRole") != "alert"
                    or surface.get("alertVisible") is not True
                    or surface.get("enabledInteractiveControlCount") != 0
                )
            )
        ):
            raise ValueError("manfred_candidate_spatial_browser_review_invalid")
    return {
        "flagship_final": {
            "schema": str(final["schema"]),
            "status": str(final["status"]),
            "sha256": PROPERTY_FINAL_REVIEW_SHA256,
            "source_path": str(final_path),
        },
        "exact_viewer_browser": {
            "schema": str(browser["schema"]),
            "status": str(browser["status"]),
            "sha256": PROPERTY_BROWSER_REVIEW_SHA256,
            "source_path": str(browser_path),
        },
    }


def _validated_property_publication(
    *,
    snapshot: dict[str, bytes],
    authority_bytes: bytes,
    target_origin: str,
    final_review_receipt_path: Path,
    browser_review_receipt_path: Path,
) -> dict[str, object]:
    target_origin = _validate_public_base_url(target_origin)
    if len(authority_bytes) > MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    try:
        tour_bytes = snapshot["tour.json"]
        proof_bytes = snapshot["generated-reconstruction/reconstruction.json"]
    except KeyError as exc:
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid") from exc
    tour = _strict_json_object(
        tour_bytes, error="manfred_candidate_spatial_manifest_invalid"
    )
    authority = _strict_json_object(
        authority_bytes,
        error="manfred_candidate_spatial_authority_receipt_invalid",
    )
    proof = _strict_json_object(
        proof_bytes, error="manfred_candidate_spatial_proof_manifest_invalid"
    )
    if tour_bytes != _canonical_json_bytes(
        tour
    ) or authority_bytes != _canonical_json_bytes(authority):
        raise ValueError("manfred_candidate_spatial_manifest_not_canonical")
    slug, asset_paths, viewer_relpath, proof_relpath = _spatial_release_contract(
        tour, expected_slug=PROPERTY_AUTHORIZED_SLUG
    )
    expected_paths = {"tour.json", *asset_paths}
    if set(snapshot) != expected_paths or len(snapshot) != 6:
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    release = dict(tour.get("generated_viewer_release") or {})
    generated = dict(tour.get("generated_reconstruction") or {})
    bindings = list(release.get("asset_bindings") or [])
    route_labels = list(generated.get("route_labels") or [])
    for raw_binding in bindings:
        binding = dict(raw_binding or {})
        path = str(binding.get("path") or "")
        content = snapshot.get(path)
        if (
            content is None
            or binding.get("sha256") != _sha256(content)
            or binding.get("size_bytes") != len(content)
        ):
            raise ValueError("manfred_candidate_spatial_asset_digest_mismatch")
    authority_sha256 = _sha256(authority_bytes)
    if (
        tour.get("schema") != PROPERTY_PUBLIC_TOUR_PACKAGE_SCHEMA
        or tour.get("source_commit") != PROPERTY_ARTIFACT_COMMIT
        or tour.get("synthetic") is not True
        or generated.get("synthetic") is not True
        or generated.get("capture_mode") is not False
        or generated.get("verified_provider_capture") is not False
        or generated.get("satisfies_verified_tour_gate") is not False
        or release.get("contract") != "ea.public-tour-generated-viewer-release.v1"
        or release.get("status") != "ready"
        or release.get("public_activation_authority") is not True
        or release.get("publication_authority_verified") is not True
        or release.get("publication_authority_receipt_sha256") != authority_sha256
        or release.get("browser_receipt_sha256") != PROPERTY_BROWSER_REVIEW_SHA256
        or release.get("source_provenance_receipt_sha256")
        != PROPERTY_FINAL_REVIEW_SHA256
        or release.get("security_review_receipt_sha256") != PROPERTY_FINAL_REVIEW_SHA256
        or release.get("accessibility_review_receipt_sha256")
        != PROPERTY_FINAL_REVIEW_SHA256
        or release.get("browser_interaction_verified") is not True
        or release.get("visual_quality_review_passed") is not True
        or release.get("security_review_passed") is not True
        or release.get("accessibility_review_passed") is not True
        or release.get("source_provenance_verified") is not True
        or release.get("revoked") is not False
        or release.get("disqualified") is not False
        or len(route_labels) != 9
        or route_labels != list(tour.get("route_labels") or [])
        or len(set(str(label) for label in route_labels)) != 9
        or any(
            not isinstance(label, str) or not label.strip() or label != label.strip()
            for label in route_labels
        )
        or _spatial_payload_has_private_host_path(tour)
    ):
        raise ValueError("manfred_candidate_spatial_release_contract_invalid")
    authority_source = dict(authority.get("source") or {})
    classification = dict(authority.get("classification") or {})
    authority_package = dict(authority.get("package") or {})
    authority_reviews = dict(authority.get("review_receipts") or {})
    if (
        set(authority)
        != {
            "allowed_public_origins",
            "classification",
            "owner",
            "package",
            "public_activation_authority",
            "publication_authority_verified",
            "repository",
            "review_receipts",
            "schema",
            "slug",
            "source",
            "status",
            "user_instruction_sha256",
        }
        or authority.get("schema") != PROPERTY_PUBLICATION_AUTHORITY_SCHEMA
        or authority.get("status") != "authorized"
        or authority.get("owner") != PROPERTY_AUTHORITY_OWNER
        or authority.get("repository") != PROPERTY_REPOSITORY
        or authority.get("slug") != slug
        or authority.get("public_activation_authority") is not True
        or authority.get("publication_authority_verified") is not True
        or authority.get("user_instruction_sha256") != PROPERTY_USER_INSTRUCTION_SHA256
        or set(authority.get("allowed_public_origins") or [])
        != PROPERTY_ALLOWED_PUBLIC_ORIGINS
        or target_origin not in PROPERTY_ALLOWED_PUBLIC_ORIGINS
        or target_origin not in list(authority.get("allowed_public_origins") or [])
        or authority_source
        != {
            "artifact_commit": PROPERTY_ARTIFACT_COMMIT,
            "packager_commit": PROPERTY_PACKAGER_COMMIT,
            "worktree_clean": True,
        }
        or classification.get("synthetic") is not True
        or classification.get("capture_mode") is not False
        or classification.get("verified_provider_capture") is not False
        or classification.get("satisfies_verified_tour_gate") is not False
        or not str(classification.get("disclosure") or "").strip()
        or authority_reviews
        != {
            "flagship_final": {
                "schema": "propertyquarry.flagship_3d_review_receipt.v1",
                "status": "polished_review_candidate_pass_guarded_not_published",
                "sha256": PROPERTY_FINAL_REVIEW_SHA256,
            },
            "exact_viewer_browser": {
                "schema": "propertyquarry.exact_viewer_browser_audit.v3",
                "status": "pass",
                "sha256": PROPERTY_BROWSER_REVIEW_SHA256,
            },
        }
        or authority_package.get("public_bundle_relpath")
        != f"public_property_tours/{slug}"
        or authority_package.get("public_file_relpaths") != sorted(expected_paths)
        or authority_package.get("public_file_count") != 6
        or authority_package.get("pre_authority_manifest_canonicalization")
        != PROPERTY_PRE_AUTHORITY_CANONICALIZATION
        or authority_package.get("asset_bindings") != bindings
        or authority_sha256 != PROPERTY_AUTHORITY_SHA256
        or _sha256(tour_bytes) != PROPERTY_TOUR_SHA256
    ):
        raise ValueError("manfred_candidate_spatial_authority_receipt_mismatch")
    pre_authority = copy.deepcopy(tour)
    pre_release = dict(pre_authority.get("generated_viewer_release") or {})
    pre_release["publication_authority_receipt_sha256"] = None
    pre_authority["generated_viewer_release"] = pre_release
    pre_authority_sha256 = _sha256(_canonical_json_bytes_without_lf(pre_authority))
    if (
        pre_authority_sha256 != PROPERTY_PRE_AUTHORITY_SHA256
        or authority_package.get("pre_authority_manifest_canonical_sha256")
        != pre_authority_sha256
    ):
        raise ValueError("manfred_candidate_spatial_pre_authority_digest_mismatch")
    floorplan = dict(proof.get("floorplan") or {})
    viewer = dict(proof.get("viewer") or {})
    if (
        proof_bytes != _canonical_json_bytes(proof)
        or proof.get("schema") != PROPERTY_RECONSTRUCTION_SCHEMA
        or proof.get("slug") != slug
        or proof.get("source_commit") != PROPERTY_ARTIFACT_COMMIT
        or proof.get("synthetic") is not True
        or proof.get("capture_mode") is not False
        or proof.get("verified_provider_capture") is not False
        or proof.get("satisfies_verified_tour_gate") is not False
        or proof.get("route_labels") != route_labels
        or floorplan.get("source_path")
        != (
            f"property://{PROPERTY_REPOSITORY}/{PROPERTY_ARTIFACT_COMMIT}/"
            "floorplan-apartment-crop.png"
        )
        or floorplan.get("sha256")
        != _sha256(snapshot["generated-reconstruction/source-floorplan.png"])
        or viewer.get("sha256")
        != _sha256(snapshot["generated-reconstruction/viewer.html"])
        or _spatial_payload_has_private_host_path(proof)
    ):
        raise ValueError("manfred_candidate_spatial_proof_manifest_invalid")
    review_evidence = _property_review_evidence(
        snapshot,
        final_review_receipt_path=final_review_receipt_path,
        browser_review_receipt_path=browser_review_receipt_path,
    )
    review_contract = {
        name: {
            key: value for key, value in dict(row or {}).items() if key != "source_path"
        }
        for name, row in review_evidence.items()
    }
    if review_contract != authority_reviews:
        raise ValueError("manfred_candidate_spatial_review_evidence_mismatch")
    return {
        "slug": slug,
        "asset_paths": asset_paths,
        "viewer_relpath": viewer_relpath,
        "proof_relpath": proof_relpath,
        "route_labels": route_labels,
        "upstream_publication_authority": authority,
        "upstream_publication_authority_sha256": authority_sha256,
        "upstream_public_activation_authority": True,
        "upstream_package_sha256": _spatial_package_sha256(snapshot),
        "upstream_tour_manifest_sha256": _sha256(tour_bytes),
        "pre_authority_manifest_canonical_sha256": pre_authority_sha256,
        "review_evidence": review_evidence,
    }


def _exclusive_write_at(
    parent_descriptor: int,
    name: str,
    content: bytes,
    *,
    mode: int,
    retain_as: str | None = None,
    retained_files: dict[str, tuple[int, tuple[int, int]]] | None = None,
) -> tuple[int, int]:
    if name in {"", ".", ".."} or "/" in name:
        raise ValueError("manfred_candidate_spatial_output_name_invalid")
    if (retain_as is None) != (retained_files is None):
        raise ValueError("manfred_candidate_spatial_retention_invalid")
    if retain_as is not None and retain_as in retained_files:
        raise ValueError("manfred_candidate_spatial_retention_invalid")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, mode, dir_fd=parent_descriptor)
    except OSError as exc:
        raise ValueError("manfred_candidate_spatial_output_exists") from exc
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise ValueError("manfred_candidate_spatial_output_write_failed")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        if retain_as is not None and retained_files is not None:
            retained_files[retain_as] = (os.dup(descriptor), identity)
        return identity
    except BaseException as exc:
        cleanup_failed = False
        identity: tuple[int, int] | None = None
        try:
            metadata = os.fstat(descriptor)
            identity = (metadata.st_dev, metadata.st_ino)
            if not _quarantine_entry_nondestructive(
                parent_descriptor,
                name,
            ):
                cleanup_failed = True
        except (OSError, ValueError):
            cleanup_failed = True
        try:
            metadata = os.fstat(descriptor)
            if (
                identity is not None
                and (
                    metadata.st_dev,
                    metadata.st_ino,
                )
                != identity
            ):
                cleanup_failed = True
            os.ftruncate(descriptor, 0)
            os.fchmod(descriptor, 0o000)
            os.fsync(descriptor)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError(
                "manfred_candidate_spatial_partial_output_rollback_incomplete"
            ) from exc
        raise
    finally:
        os.close(descriptor)


def _write_spatial_bundle_at(
    root_descriptor: int,
    files: dict[str, bytes],
    *,
    retained_files: dict[str, tuple[int, tuple[int, int]]] | None = None,
) -> None:
    directory_flags = (
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    )
    for relpath, content in sorted(files.items()):
        parts = _safe_relative(relpath).parts
        descriptor = os.dup(root_descriptor)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, directory_flags, dir_fd=descriptor)
                os.fchmod(child, 0o755)
                os.close(descriptor)
                descriptor = child
            _exclusive_write_at(
                descriptor,
                parts[-1],
                content,
                mode=0o644,
                retain_as=relpath if retained_files is not None else None,
                retained_files=retained_files,
            )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.fchmod(root_descriptor, 0o755)
    os.fsync(root_descriptor)


def _rename_noreplace(
    source_parent_descriptor: int,
    source_name: str,
    destination_parent_descriptor: int,
    destination_name: str,
) -> None:
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise ValueError("manfred_candidate_spatial_rename_noreplace_unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if (
        renameat2(
            source_parent_descriptor,
            os.fsencode(source_name),
            destination_parent_descriptor,
            os.fsencode(destination_name),
            1,
        )
        == 0
    ):
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise ValueError("manfred_candidate_spatial_output_exists")
    raise ValueError("manfred_candidate_spatial_output_install_failed")


def _entry_identity(
    parent_descriptor: int,
    name: str,
    *,
    directory: bool,
) -> tuple[int, int] | None:
    try:
        metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError:
        return None
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(metadata.st_mode):
        return None
    return metadata.st_dev, metadata.st_ino


def _entry_exists_at(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _quarantine_entry_nondestructive(
    parent_descriptor: int,
    name: str,
    *,
    maximum_attempts: int = 16,
) -> bool:
    if name in {"", ".", ".."} or "/" in name:
        raise ValueError("manfred_candidate_spatial_output_name_invalid")
    for _attempt in range(maximum_attempts):
        if not _entry_exists_at(parent_descriptor, name):
            os.fsync(parent_descriptor)
            return not _entry_exists_at(parent_descriptor, name)
        quarantine_name = f".{name}.{uuid.uuid4().hex}.rollback"
        try:
            _rename_noreplace(
                parent_descriptor,
                name,
                parent_descriptor,
                quarantine_name,
            )
        except ValueError:
            if not _entry_exists_at(parent_descriptor, name):
                os.fsync(parent_descriptor)
                return True
            continue
        if not _entry_exists_at(parent_descriptor, quarantine_name):
            return False
        os.fsync(parent_descriptor)
    return not _entry_exists_at(parent_descriptor, name)


def _restore_quarantined_entry(
    parent_descriptor: int,
    quarantine_name: str,
    original_name: str,
) -> None:
    if (
        _entry_identity(
            parent_descriptor,
            original_name,
            directory=False,
        )
        is not None
        or _entry_identity(
            parent_descriptor,
            original_name,
            directory=True,
        )
        is not None
    ):
        return
    try:
        _rename_noreplace(
            parent_descriptor,
            quarantine_name,
            parent_descriptor,
            original_name,
        )
    except ValueError:
        return


def _remove_bundle_if_identity(
    parent_descriptor: int, name: str, identity: tuple[int, int]
) -> bool:
    if (
        _entry_identity(
            parent_descriptor,
            name,
            directory=True,
        )
        != identity
    ):
        return False
    quarantine_name = f".{name}.{uuid.uuid4().hex}.rollback"
    _rename_noreplace(
        parent_descriptor,
        name,
        parent_descriptor,
        quarantine_name,
    )
    if (
        _entry_identity(
            parent_descriptor,
            quarantine_name,
            directory=True,
        )
        != identity
    ):
        _restore_quarantined_entry(
            parent_descriptor,
            quarantine_name,
            name,
        )
        return False
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        quarantine_name,
        flags,
        dir_fd=parent_descriptor,
    )
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != identity:
            _restore_quarantined_entry(
                parent_descriptor,
                quarantine_name,
                name,
            )
            return False
        current = os.stat(
            quarantine_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            current.st_dev,
            current.st_ino,
        ) != identity or not stat.S_ISDIR(current.st_mode):
            raise ValueError("manfred_candidate_spatial_rollback_identity_drift")
        os.fchmod(descriptor, 0o000)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(parent_descriptor)
    return True


def _scrub_retained_spatial_files(
    retained_files: dict[str, tuple[int, tuple[int, int]]],
) -> bool:
    scrubbed = True
    for descriptor, identity in retained_files.values():
        try:
            metadata = os.fstat(descriptor)
            if (metadata.st_dev, metadata.st_ino) != identity or not stat.S_ISREG(
                metadata.st_mode
            ):
                scrubbed = False
                continue
            os.ftruncate(descriptor, 0)
            os.fchmod(descriptor, 0o000)
            os.fsync(descriptor)
            final = os.fstat(descriptor)
            if (
                (final.st_dev, final.st_ino) != identity
                or final.st_size != 0
                or stat.S_IMODE(final.st_mode) != 0o000
            ):
                scrubbed = False
        except OSError:
            scrubbed = False
    return scrubbed


def _unlink_file_if_identity(
    parent_descriptor: int, name: str, identity: tuple[int, int]
) -> bool:
    if (
        _entry_identity(
            parent_descriptor,
            name,
            directory=False,
        )
        != identity
    ):
        return False
    quarantine_name = f".{name}.{uuid.uuid4().hex}.rollback"
    _rename_noreplace(
        parent_descriptor,
        name,
        parent_descriptor,
        quarantine_name,
    )
    if (
        _entry_identity(
            parent_descriptor,
            quarantine_name,
            directory=False,
        )
        != identity
    ):
        _restore_quarantined_entry(
            parent_descriptor,
            quarantine_name,
            name,
        )
        return False
    flags = (
        os.O_WRONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(
        quarantine_name,
        flags,
        dir_fd=parent_descriptor,
    )
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != identity:
            _restore_quarantined_entry(
                parent_descriptor,
                quarantine_name,
                name,
            )
            return False
        os.ftruncate(descriptor, 0)
        os.fchmod(descriptor, 0o000)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if (
        _entry_identity(
            parent_descriptor,
            quarantine_name,
            directory=False,
        )
        != identity
    ):
        return False
    os.fsync(parent_descriptor)
    return True


def _read_file_at_identity(
    parent_descriptor: int,
    name: str,
    identity: tuple[int, int],
    *,
    maximum: int,
) -> bytes:
    flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if (
            (metadata.st_dev, metadata.st_ino) != identity
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > maximum
        ):
            raise ValueError("manfred_candidate_spatial_output_identity_drift")
        chunks: list[bytes] = []
        remaining = int(metadata.st_size)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("manfred_candidate_spatial_output_identity_drift")
            chunks.append(chunk)
            remaining -= len(chunk)
        final = os.fstat(descriptor)
        if (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        ):
            raise ValueError("manfred_candidate_spatial_output_identity_drift")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def materialize_spatial_handoff(
    *,
    source_bundle_dir: Path,
    upstream_authority_receipt_path: Path,
    final_review_receipt_path: Path | None = None,
    browser_review_receipt_path: Path | None = None,
    handoff_bundle_dir: Path,
    handoff_receipt_path: Path,
    target_origin: str,
) -> dict[str, object]:
    source_bundle_dir = Path(os.path.abspath(os.fspath(source_bundle_dir.expanduser())))
    upstream_authority_receipt_path = Path(
        os.path.abspath(os.fspath(upstream_authority_receipt_path.expanduser()))
    )
    final_review_receipt_path = Path(
        os.path.abspath(
            os.fspath(
                (
                    final_review_receipt_path
                    if final_review_receipt_path is not None
                    else PROPERTY_FINAL_REVIEW_RECEIPT
                ).expanduser()
            )
        )
    )
    browser_review_receipt_path = Path(
        os.path.abspath(
            os.fspath(
                (
                    browser_review_receipt_path
                    if browser_review_receipt_path is not None
                    else PROPERTY_BROWSER_REVIEW_RECEIPT
                ).expanduser()
            )
        )
    )
    handoff_bundle_dir = Path(
        os.path.abspath(os.fspath(handoff_bundle_dir.expanduser()))
    )
    handoff_receipt_path = Path(
        os.path.abspath(os.fspath(handoff_receipt_path.expanduser()))
    )
    target_origin = _validate_public_base_url(target_origin)
    output_paths = (handoff_bundle_dir, handoff_receipt_path)
    property_inputs = (
        source_bundle_dir,
        upstream_authority_receipt_path,
        final_review_receipt_path,
        browser_review_receipt_path,
    )
    if handoff_bundle_dir.name != PROPERTY_AUTHORIZED_SLUG or any(
        output == property_input or property_input in output.parents
        for output in output_paths
        for property_input in property_inputs
    ):
        raise ValueError("manfred_candidate_spatial_materialization_target_invalid")
    # Intake may be operator-private (0700/0600) or group-readable/writable.
    # The stable descriptor snapshot rejects unsafe/world-writable inputs and
    # materialization below emits a detached, sanitized 0755/0644 projection.
    snapshot = _spatial_tree_snapshot(source_bundle_dir, require_sanitized_modes=False)
    authority_bytes = _read_spatial_file_snapshot(
        upstream_authority_receipt_path,
        require_sanitized_modes=False,
    )
    if stat.S_IMODE(os.lstat(upstream_authority_receipt_path).st_mode) != 0o600:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    validated = _validated_property_publication(
        snapshot=snapshot,
        authority_bytes=authority_bytes,
        target_origin=target_origin,
        final_review_receipt_path=final_review_receipt_path,
        browser_review_receipt_path=browser_review_receipt_path,
    )
    _verify_spatial_bundle_before_copy(source_bundle_dir, slug=str(validated["slug"]))
    receipt = {
        "schema": SPATIAL_HANDOFF_SCHEMA,
        "status": "pass",
        "scope": SPATIAL_HANDOFF_SCOPE,
        "candidate_handoff_authorized": True,
        "public_activation_authority": False,
        "target_origin": target_origin,
        "slug": validated["slug"],
        "asset_paths": validated["asset_paths"],
        "upstream_owner": PROPERTY_AUTHORITY_OWNER,
        "upstream_repository": PROPERTY_REPOSITORY,
        "upstream_publication_authority_schema": (
            PROPERTY_PUBLICATION_AUTHORITY_SCHEMA
        ),
        "upstream_publication_authority_sha256": validated[
            "upstream_publication_authority_sha256"
        ],
        "upstream_public_activation_authority": True,
        "upstream_package_sha256": validated["upstream_package_sha256"],
        "upstream_tour_manifest_sha256": validated["upstream_tour_manifest_sha256"],
        "source_artifact_commit": PROPERTY_ARTIFACT_COMMIT,
        "source_packager_commit": PROPERTY_PACKAGER_COMMIT,
        "review_evidence": validated["review_evidence"],
    }
    receipt_bytes = _receipt_bytes(receipt)
    bundle_parent_descriptor = _open_directory_path_nofollow(
        handoff_bundle_dir.parent, create_missing=True
    )
    receipt_parent_descriptor = _open_directory_path_nofollow(
        handoff_receipt_path.parent, create_missing=True
    )
    temporary_name = f".{handoff_bundle_dir.name}.{uuid.uuid4().hex}.tmp"
    staging_descriptor = -1
    bundle_installed = False
    receipt_identity: tuple[int, int] | None = None
    staging_identity: tuple[int, int] | None = None
    installed_identity: tuple[int, int] | None = None
    retained_files: dict[str, tuple[int, tuple[int, int]]] = {}
    retained_receipt: dict[str, tuple[int, tuple[int, int]]] = {}
    try:
        try:
            os.mkdir(temporary_name, 0o700, dir_fd=bundle_parent_descriptor)
            staging_descriptor = os.open(
                temporary_name,
                os.O_RDONLY
                | os.O_CLOEXEC
                | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=bundle_parent_descriptor,
            )
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_output_staging_failed") from exc
        staging_metadata = os.fstat(staging_descriptor)
        staging_identity = (staging_metadata.st_dev, staging_metadata.st_ino)
        _write_spatial_bundle_at(
            staging_descriptor,
            snapshot,
            retained_files=retained_files,
        )
        if set(retained_files) != set(snapshot):
            raise ValueError("manfred_candidate_spatial_retention_invalid")
        retained_identities = {
            relpath: identity
            for relpath, (_descriptor, identity) in retained_files.items()
        }
        staging_path = handoff_bundle_dir.parent / temporary_name
        path_metadata = os.lstat(staging_path)
        if (path_metadata.st_dev, path_metadata.st_ino) != staging_identity:
            raise ValueError("manfred_candidate_spatial_output_parent_changed")
        _verify_spatial_bundle_before_copy(staging_path, slug=str(validated["slug"]))
        staged_snapshot = _spatial_tree_snapshot(
            staging_path,
            require_sanitized_modes=True,
            expected_root_identity=staging_identity,
            expected_file_identities=retained_identities,
        )
        if staged_snapshot != snapshot:
            raise ValueError("manfred_candidate_spatial_output_digest_drift")
        _rename_noreplace(
            bundle_parent_descriptor,
            temporary_name,
            bundle_parent_descriptor,
            handoff_bundle_dir.name,
        )
        bundle_installed = True
        installed_identity = _entry_identity(
            bundle_parent_descriptor,
            handoff_bundle_dir.name,
            directory=True,
        )
        if installed_identity is None:
            raise ValueError("manfred_candidate_spatial_output_install_drift")
        try:
            installed_snapshot = _spatial_tree_snapshot(
                handoff_bundle_dir,
                require_sanitized_modes=True,
                expected_root_identity=staging_identity,
                expected_file_identities=retained_identities,
            )
        except (OSError, ValueError) as exc:
            raise ValueError("manfred_candidate_spatial_output_install_drift") from exc
        if installed_identity != staging_identity or installed_snapshot != snapshot:
            raise ValueError("manfred_candidate_spatial_output_install_drift")
        os.fsync(bundle_parent_descriptor)
        receipt_identity = _exclusive_write_at(
            receipt_parent_descriptor,
            handoff_receipt_path.name,
            receipt_bytes,
            mode=0o600,
            retain_as=handoff_receipt_path.name,
            retained_files=retained_receipt,
        )
        if (
            set(retained_receipt) != {handoff_receipt_path.name}
            or retained_receipt[handoff_receipt_path.name][1] != receipt_identity
        ):
            raise ValueError("manfred_candidate_spatial_retention_invalid")
        if (
            _read_file_at_identity(
                receipt_parent_descriptor,
                handoff_receipt_path.name,
                receipt_identity,
                maximum=MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES,
            )
            != receipt_bytes
        ):
            raise ValueError("manfred_candidate_spatial_output_receipt_drift")
        try:
            final_installed_snapshot = _spatial_tree_snapshot(
                handoff_bundle_dir,
                require_sanitized_modes=True,
                expected_root_identity=staging_identity,
                expected_file_identities=retained_identities,
            )
        except (OSError, ValueError) as exc:
            raise ValueError("manfred_candidate_spatial_output_install_drift") from exc
        if final_installed_snapshot != snapshot:
            raise ValueError("manfred_candidate_spatial_output_install_drift")
        os.fsync(receipt_parent_descriptor)
    except BaseException:
        rollback_failures: list[str] = []
        if receipt_identity is not None:
            receipt_cleanup_failed = False
            try:
                if not _quarantine_entry_nondestructive(
                    receipt_parent_descriptor,
                    handoff_receipt_path.name,
                ):
                    receipt_cleanup_failed = True
            except (OSError, ValueError):
                receipt_cleanup_failed = True
            if retained_receipt and not _scrub_retained_spatial_files(retained_receipt):
                receipt_cleanup_failed = True
            if receipt_cleanup_failed:
                rollback_failures.append("receipt")
        if retained_files and not _scrub_retained_spatial_files(retained_files):
            rollback_failures.append("staging_files")
        if staging_identity is not None:
            cleanup_name = (
                handoff_bundle_dir.name if bundle_installed else temporary_name
            )
            try:
                _remove_bundle_if_identity(
                    bundle_parent_descriptor,
                    cleanup_name,
                    staging_identity,
                )
                if not _quarantine_entry_nondestructive(
                    bundle_parent_descriptor,
                    cleanup_name,
                ):
                    rollback_failures.append("bundle")
            except (OSError, ValueError):
                rollback_failures.append("bundle")
        if staging_descriptor >= 0:
            try:
                os.fchmod(staging_descriptor, 0o000)
                os.fsync(staging_descriptor)
            except (OSError, ValueError):
                rollback_failures.append("staging")
        if rollback_failures:
            raise RuntimeError(
                "manfred_candidate_spatial_rollback_incomplete:"
                + ",".join(sorted(set(rollback_failures)))
            )
        raise
    finally:
        for descriptor, _identity in retained_receipt.values():
            os.close(descriptor)
        for descriptor, _identity in retained_files.values():
            os.close(descriptor)
        if staging_descriptor >= 0:
            os.close(staging_descriptor)
        os.close(bundle_parent_descriptor)
        os.close(receipt_parent_descriptor)
    return {
        **receipt,
        "handoff_bundle_dir": str(handoff_bundle_dir),
        "handoff_receipt_path": str(handoff_receipt_path),
        "handoff_receipt_sha256": _sha256(receipt_bytes),
        "public_file_count": len(snapshot),
    }


def _validated_spatial_handoff_input(
    *,
    bundle_dir: Path,
    authority_receipt_path: Path,
    final_review_receipt_path: Path | None = None,
    browser_review_receipt_path: Path | None = None,
    target_origin: str,
) -> dict[str, object]:
    final_review_receipt_path = (
        final_review_receipt_path
        if final_review_receipt_path is not None
        else PROPERTY_FINAL_REVIEW_RECEIPT
    )
    browser_review_receipt_path = (
        browser_review_receipt_path
        if browser_review_receipt_path is not None
        else PROPERTY_BROWSER_REVIEW_RECEIPT
    )
    snapshot = _spatial_tree_snapshot(bundle_dir, require_sanitized_modes=True)
    authority_bytes = _read_spatial_file_snapshot(
        authority_receipt_path, require_sanitized_modes=False
    )
    if stat.S_IMODE(os.lstat(authority_receipt_path).st_mode) != 0o600:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    validated = _validated_property_publication(
        snapshot=snapshot,
        authority_bytes=authority_bytes,
        target_origin=target_origin,
        final_review_receipt_path=final_review_receipt_path,
        browser_review_receipt_path=browser_review_receipt_path,
    )
    if bundle_dir.name != validated["slug"]:
        raise ValueError("manfred_candidate_spatial_slug_invalid")
    verifier_receipt = _verify_spatial_bundle_before_copy(
        bundle_dir, slug=str(validated["slug"])
    )
    return {
        "included": True,
        "files": snapshot,
        **validated,
        "verifier_receipt": verifier_receipt,
    }


def _read_regular_source(
    source: Path,
    *,
    maximum: int,
    missing_ok: bool = False,
) -> bytes | None:
    source = Path(os.path.abspath(os.fspath(source.expanduser())))
    parent_descriptor = _open_directory_path_nofollow(source.parent)

    def identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_uid,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    try:
        try:
            initial = os.stat(
                source.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ValueError("manfred_candidate_source_asset_missing") from None
        if (
            not stat.S_ISREG(initial.st_mode)
            or stat.S_ISLNK(initial.st_mode)
            or initial.st_uid != os.getuid()
            or initial.st_nlink != 1
            or stat.S_IMODE(initial.st_mode) & 0o002
            or initial.st_size <= 0
            or initial.st_size > maximum
        ):
            raise ValueError("manfred_candidate_source_asset_invalid")
        flags = (
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(source.name, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise ValueError("manfred_candidate_source_asset_invalid") from exc
        try:
            opened = os.fstat(descriptor)
            if identity(initial) != identity(opened):
                raise ValueError("manfred_candidate_source_asset_changed")
            chunks: list[bytes] = []
            remaining = int(opened.st_size)
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("manfred_candidate_source_asset_changed")
                chunks.append(chunk)
                remaining -= len(chunk)
            if identity(opened) != identity(os.fstat(descriptor)):
                raise ValueError("manfred_candidate_source_asset_changed")
        finally:
            os.close(descriptor)
        try:
            final_path = os.stat(
                source.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError("manfred_candidate_source_asset_changed") from exc
        if identity(initial) != identity(final_path):
            raise ValueError("manfred_candidate_source_asset_changed")
        return b"".join(chunks)
    finally:
        os.close(parent_descriptor)


def _copy_regular(
    source: Path, destination: Path, *, maximum: int, mode: int
) -> dict[str, object]:
    content = _read_regular_source(source, maximum=maximum)
    if content is None:  # pragma: no cover - missing_ok is false
        raise ValueError("manfred_candidate_source_asset_missing")
    _write_bytes(destination, content, mode=mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _write_bytes(destination: Path, content: bytes, *, mode: int) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_bytes(content)
    destination.chmod(mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _candidate_release_authority_paths(
    root: Path,
    *,
    voice_release_included: bool = True,
) -> dict[str, Path]:
    return {
        name: root / filename
        for name, filename in CANDIDATE_RELEASE_AUTHORITY_FILENAMES.items()
        if voice_release_included or name != "voice_release"
    }


def _candidate_release_authority_container_paths(
    *,
    voice_release_included: bool = True,
) -> dict[str, str]:
    return {
        name: str(CANDIDATE_RELEASE_AUTHORITY_CONTAINER_ROOT / filename)
        for name, filename in CANDIDATE_RELEASE_AUTHORITY_FILENAMES.items()
        if voice_release_included or name != "voice_release"
    }


def _candidate_voice_authorization_state(
    decision: dict[str, object] | None,
) -> dict[str, object]:
    if decision is None:
        return {
            "voice_release_allowed": False,
            "public_evaluation_allowed": False,
            "voice_runtime_enablement_allowed": False,
            "voice_access_mode": VOICE_ACCESS_MODE_TEXT_ONLY,
        }
    if (
        decision.get("allowed") is True
        and decision.get("status") == "released"
        and decision.get("reason") == ""
    ):
        return {
            "voice_release_allowed": True,
            "public_evaluation_allowed": False,
            "voice_runtime_enablement_allowed": True,
            "voice_access_mode": VOICE_ACCESS_MODE_PUBLIC_RELEASE,
        }
    if (
        decision.get("allowed") is False
        and decision.get("public_evaluation") is True
        and decision.get("status") == "public_evaluation"
        and decision.get("reason") == ""
        and decision.get("receipt_status") == "public_evaluation_authorized"
        and decision.get("access_mode") == VOICE_ACCESS_MODE_PUBLIC_EVALUATION
        and decision.get("disclosure_required") is True
    ):
        return {
            "voice_release_allowed": False,
            "public_evaluation_allowed": True,
            "voice_runtime_enablement_allowed": True,
            "voice_access_mode": VOICE_ACCESS_MODE_PUBLIC_EVALUATION,
        }
    raise ValueError(
        "manfred_candidate_voice_release_"
        + str(decision.get("reason") or "invalid")
    )


def _candidate_remote_main_evidence(
    source_root: Path,
    *,
    commit: str,
) -> dict[str, object]:
    if _run(["git", "status", "--short"], cwd=source_root).strip():
        raise ValueError("manfred_candidate_release_source_dirty")
    head_commit = _commit(source_root, "HEAD")
    if head_commit != commit:
        raise ValueError("manfred_candidate_release_head_mismatch")
    remote_ref = "refs/remotes/origin/main"
    remote_commit = _commit(source_root, remote_ref)
    if remote_commit != commit:
        raise ValueError("manfred_candidate_release_remote_main_mismatch")
    try:
        configured_origin = (
            _run(["git", "remote", "get-url", "origin"], cwd=source_root)
            .decode("utf-8", errors="strict")
            .strip()
        )
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise ValueError("manfred_candidate_release_remote_main_unverifiable") from exc
    if configured_origin not in OFFICIAL_EA_REMOTE_ORIGINS:
        raise ValueError("manfred_candidate_release_remote_origin_invalid")

    live_git_environment = {
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_ASKPASS": "/bin/false",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.sep,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH") or os.defpath,
        "SSH_ASKPASS": "/bin/false",
    }
    try:
        _run(
            ["git", "merge-base", "--is-ancestor", commit, remote_ref],
            cwd=source_root,
        )
        live_output = (
            _run(
                [
                    "git",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "protocol.https.allow=always",
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.askPass=",
                    "ls-remote",
                    "--exit-code",
                    OFFICIAL_EA_REMOTE_ORIGIN,
                    "refs/heads/main",
                ],
                cwd=Path(os.sep),
                timeout=30,
                environment=live_git_environment,
            )
            .decode("ascii", errors="strict")
            .strip()
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        UnicodeError,
    ) as exc:
        raise ValueError("manfred_candidate_release_remote_main_unverifiable") from exc
    live_rows = live_output.splitlines()
    if len(live_rows) != 1:
        raise ValueError("manfred_candidate_release_remote_main_unverifiable")
    live_commit, separator, live_ref = live_rows[0].partition("\t")
    live_commit = live_commit.strip().lower()
    if (
        separator != "\t"
        or live_ref != "refs/heads/main"
        or not COMMIT_RE.fullmatch(live_commit)
        or live_commit != commit
    ):
        raise ValueError("manfred_candidate_release_live_main_mismatch")
    return {
        "source_head_commit_sha": head_commit,
        "source_head_matches_candidate_commit": True,
        "source_remote_ref": remote_ref,
        "source_remote_ref_commit_sha": remote_commit,
        "source_remote_ref_evidence": "local_remote_tracking_ref",
        "source_commit_reachable_from_remote_ref": True,
        "git_remote_origin": OFFICIAL_EA_REMOTE_ORIGIN,
        "live_remote_ref": live_ref,
        "live_remote_ref_commit_sha": live_commit,
        "live_remote_ref_evidence": LIVE_REMOTE_REF_EVIDENCE,
    }


def _materialize_candidate_release_authority(
    *,
    root: Path,
    source_root: Path,
    commit: str,
    image_id: str,
    image_revision: str,
    project_name: str,
    public_origin: str,
    generated_at: str,
    public_artifacts: list[str],
    voice_identity: dict[str, str],
    voice_release_bytes: bytes | None,
) -> dict[str, object]:
    if (
        commit != image_revision
        or not COMMIT_RE.fullmatch(commit)
        or not IMAGE_ID_RE.fullmatch(image_id)
    ):
        raise ValueError("manfred_candidate_release_identity_mismatch")
    normalized_voice_identity = _voice_identity(
        voice_config_sha256=voice_identity.get("voice_config_sha256", ""),
        voice_manifest_sha256=voice_identity.get("voice_manifest_sha256", ""),
        voice_reference_aggregate_sha256=voice_identity.get(
            "voice_reference_aggregate_sha256", ""
        ),
        provider_voice_id_sha256=voice_identity.get(
            "provider_voice_id_sha256", ""
        ),
        tts_provider=voice_identity.get("tts_provider", ""),
        tts_model=voice_identity.get("tts_model", ""),
    )
    if voice_identity != normalized_voice_identity:
        raise ValueError("manfred_candidate_voice_identity_invalid")
    voice_authorization = _candidate_voice_authorization_state(None)
    remote = _candidate_remote_main_evidence(source_root, commit=commit)
    deployment_id = f"{project_name}-{commit[:12]}"
    enabled_modes = ["MEMORIAL", "PROPERTY"]
    compose_files = ["deploy/manfred-memorial/docker-compose.candidate.yml"]
    paths = _candidate_release_authority_paths(
        root,
        voice_release_included=voice_release_bytes is not None,
    )
    container_paths = _candidate_release_authority_container_paths(
        voice_release_included=voice_release_bytes is not None,
    )
    root.mkdir(parents=True, mode=0o700)

    if voice_release_bytes is not None:
        voice_release = _strict_json_object(
            voice_release_bytes,
            error="manfred_candidate_voice_release_invalid",
        )
        voice_release_decision = evaluate_memorial_voice_release_payload(
            slug="manfred",
            payload=voice_release,
            expected_source_revision=commit,
            expected_public_origin=public_origin,
            expected_image_id=image_id,
            expected_voice_config_sha256=normalized_voice_identity[
                "voice_config_sha256"
            ],
            expected_voice_manifest_sha256=normalized_voice_identity[
                "voice_manifest_sha256"
            ],
            expected_voice_reference_aggregate_sha256=(
                normalized_voice_identity["voice_reference_aggregate_sha256"]
            ),
            expected_provider_voice_id_sha256=normalized_voice_identity[
                "provider_voice_id_sha256"
            ],
            expected_tts_provider=normalized_voice_identity["tts_provider"],
            expected_tts_model=normalized_voice_identity["tts_model"],
        )
        voice_authorization = _candidate_voice_authorization_state(
            voice_release_decision
        )
        _write_bytes(paths["voice_release"], voice_release_bytes, mode=0o400)

    tracked_modes = _strict_json_object(
        _git_blob(
            source_root,
            commit,
            ".codex-design/product/PROJECT_MODES.generated.json",
        ),
        error="manfred_candidate_release_project_modes_invalid",
    )
    declared_modes = {
        str(row.get("key") or "").strip()
        for row in list(tracked_modes.get("modes") or [])
        if isinstance(row, dict)
    }
    if tracked_modes.get("contract_name") != "ea.project_modes" or not set(
        enabled_modes
    ).issubset(declared_modes):
        raise ValueError("manfred_candidate_release_project_modes_invalid")
    project_modes = {
        **tracked_modes,
        "generated_at": generated_at,
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "source_git_head": commit,
        "head_semantics": "candidate_release",
    }
    project_modes_bytes = _receipt_bytes(project_modes)
    _write_bytes(paths["project_modes"], project_modes_bytes, mode=0o444)

    deploy_context = {
        "contract_name": "ea.deploy_context.v1",
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "generated_at": generated_at,
        "repository": "EA",
        "deployment_id": deployment_id,
        "deployment_id_source": "explicit",
        "public_origin": public_origin,
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": commit,
        "release_label": deployment_id,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": enabled_modes,
        "compose_files": compose_files,
        "compose_overrides": [],
    }
    deploy_context_gate = verify_deploy_context(deploy_context=deploy_context)
    if deploy_context_gate.get("status") != "pass":
        raise ValueError("manfred_candidate_release_deploy_context_invalid")
    deploy_context_bytes = _receipt_bytes(deploy_context)
    _write_bytes(paths["deploy_context"], deploy_context_bytes, mode=0o444)

    artifact_values = [*public_artifacts]
    if voice_authorization["voice_runtime_enablement_allowed"] is True:
        artifact_values.append(
            f"{CANDIDATE_RELEASE_AUTHORITY_DIRNAME}/"
            f"{CANDIDATE_RELEASE_AUTHORITY_FILENAMES['voice_release']}"
        )
    artifacts = sorted(
        {
            str(value).strip()
            for value in artifact_values
            if str(value).strip()
        }
    )
    if not artifacts:
        raise ValueError("manfred_candidate_release_artifacts_missing")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "generated_at": generated_at,
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": commit,
        **remote,
        "dirty_worktree": False,
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
        "source_dirty_omitted_count": 0,
        "source_dirty_status_sha256": "",
        "deploy_context_generated_at": generated_at,
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": commit,
        "deployment_id": deployment_id,
        "deployment_id_source": "explicit",
        "public_origin": public_origin,
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "project_mode": "MEMORIAL",
        "enabled_project_modes": enabled_modes,
        "compose_files": compose_files,
        "compose_overrides": [],
        "artifact_set": artifacts,
        "release_label": deployment_id,
    }
    if validate_release_authority(
        release_manifest=release_manifest,
        project_modes=project_modes,
    ) or validate_release_runtime_mode(
        release_manifest=release_manifest,
        project_modes=project_modes,
        requested_mode="MEMORIAL",
        enabled_modes=enabled_modes,
        compose_overrides=[],
        manfred_composite_candidate_observed=True,
    ):
        raise ValueError("manfred_candidate_release_manifest_invalid")
    release_manifest_bytes = _receipt_bytes(release_manifest)
    _write_bytes(
        paths["release_manifest"],
        release_manifest_bytes,
        mode=0o444,
    )

    release_status = build_status(
        release_manifest_path=paths["release_manifest"],
        deploy_context_path=paths["deploy_context"],
        project_modes_path=paths["project_modes"],
        generated_at=generated_at,
    )
    release_status["manifest_path"] = container_paths["release_manifest"]
    release_status["deploy_context_path"] = container_paths["deploy_context"]
    release_status["project_modes_path"] = container_paths["project_modes"]
    gate = dict(release_status.get("gate") or {})
    gate["manifest_path"] = container_paths["release_manifest"]
    gate["deploy_context_path"] = container_paths["deploy_context"]
    gate["project_modes_path"] = container_paths["project_modes"]
    release_status["gate"] = gate
    release_status["candidate_runtime"] = True
    release_status["promotion_authority"] = False
    if (
        release_status.get("state") != "clear"
        or release_status.get("authority_posture") != "authoritative_runtime"
        or gate.get("status") != "pass"
        or release_status.get("commit_sha") != commit
        or release_status.get("deployment_id") != deployment_id
    ):
        raise ValueError("manfred_candidate_release_status_invalid")
    release_status_bytes = _receipt_bytes(release_status)
    _write_bytes(paths["release_status"], release_status_bytes, mode=0o444)

    document_bytes = {
        "deploy_context": deploy_context_bytes,
        "project_modes": project_modes_bytes,
        "release_manifest": release_manifest_bytes,
        "release_status": release_status_bytes,
    }
    if voice_release_bytes is not None:
        document_bytes["voice_release"] = voice_release_bytes
    receipt = {
        "schema": CANDIDATE_RELEASE_AUTHORITY_SCHEMA,
        "status": "pass",
        "generated_at": generated_at,
        "commit_sha": commit,
        "image_id": image_id,
        "image_revision": image_revision,
        "deployment_id": deployment_id,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": enabled_modes,
        "container_paths": container_paths,
        "documents": {
            name: {
                "sha256": _sha256(content),
                "size_bytes": len(content),
            }
            for name, content in sorted(document_bytes.items())
        },
        "source_remote_ref": remote["source_remote_ref"],
        "source_remote_ref_commit_sha": remote["source_remote_ref_commit_sha"],
        "source_commit_reachable_from_remote_ref": True,
        "git_remote_origin": remote["git_remote_origin"],
        "live_remote_ref": remote["live_remote_ref"],
        "live_remote_ref_commit_sha": remote["live_remote_ref_commit_sha"],
        "live_remote_ref_evidence": remote["live_remote_ref_evidence"],
        "runtime_authority_state": "clear",
        "runtime_authority_posture": "authoritative_runtime",
        "promotion_authority": False,
        **voice_authorization,
        "candidate_provider_boundary": (
            MANFRED_PROVIDER_FREE_CANDIDATE_BOUNDARY
        ),
        "final_voice_promotion_requires_live_review": True,
        "final_voice_promotion_review_surface": (
            MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
        ),
        **normalized_voice_identity,
        "secret_material_recorded": False,
    }
    receipt_bytes = _receipt_bytes(receipt)
    _write_bytes(paths["receipt"], receipt_bytes, mode=0o444)
    return _validate_candidate_release_authority_bundle(
        root,
        expected_commit=commit,
        expected_image_id=image_id,
        expected_project_name=project_name,
        expected_public_origin=public_origin,
        expected_voice_release_allowed=bool(
            voice_authorization["voice_release_allowed"]
        ),
        expected_voice_identity=normalized_voice_identity,
        expected_public_evaluation_allowed=bool(
            voice_authorization["public_evaluation_allowed"]
        ),
    )


def _candidate_release_authority_snapshot(
    root: Path,
    *,
    expected_names: set[str],
) -> tuple[Path, dict[str, bytes]]:
    normalized_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    if (
        not expected_names
        or any(
            not name
            or name in {".", ".."}
            or Path(name).name != name
            for name in expected_names
        )
    ):
        raise ValueError("manfred_candidate_release_authority_files_invalid")

    def identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    try:
        root_descriptor = _open_directory_path_nofollow(normalized_root)
    except (OSError, ValueError) as exc:
        raise ValueError(
            "manfred_candidate_release_authority_root_invalid"
        ) from exc
    try:
        root_before = os.fstat(root_descriptor)
        if not stat.S_ISDIR(root_before.st_mode):
            raise ValueError(
                "manfred_candidate_release_authority_root_invalid"
            )
        try:
            if set(os.listdir(root_descriptor)) != expected_names:
                raise ValueError(
                    "manfred_candidate_release_authority_files_invalid"
                )
        except OSError as exc:
            raise ValueError(
                "manfred_candidate_release_authority_files_invalid"
            ) from exc

        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ValueError(
                "manfred_candidate_release_authority_nofollow_unavailable"
            )
        file_flags = (
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_NONBLOCK", 0)
            | nofollow
        )
        contents: dict[str, bytes] = {}
        for name in sorted(expected_names):
            descriptor = -1
            try:
                before_path = os.stat(
                    name,
                    dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(before_path.st_mode)
                    or stat.S_ISLNK(before_path.st_mode)
                    or before_path.st_nlink != 1
                    or before_path.st_size <= 0
                    or before_path.st_size > 8 * 1024 * 1024
                ):
                    raise ValueError(
                        "manfred_candidate_release_authority_files_invalid"
                    )
                descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=root_descriptor,
                )
                before_open = os.fstat(descriptor)
                if identity(before_open) != identity(before_path):
                    raise ValueError(
                        "manfred_candidate_release_authority_files_changed"
                    )
                chunks: list[bytes] = []
                remaining = int(before_open.st_size)
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 64 * 1024))
                    if not chunk:
                        raise ValueError(
                            "manfred_candidate_release_authority_files_changed"
                        )
                    chunks.append(chunk)
                    remaining -= len(chunk)
                if os.read(descriptor, 1):
                    raise ValueError(
                        "manfred_candidate_release_authority_files_changed"
                    )
                after_open = os.fstat(descriptor)
                if identity(after_open) != identity(before_open):
                    raise ValueError(
                        "manfred_candidate_release_authority_files_changed"
                    )
                after_path = os.stat(
                    name,
                    dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
                if identity(after_path) != identity(before_open):
                    raise ValueError(
                        "manfred_candidate_release_authority_files_changed"
                    )
                contents[name] = b"".join(chunks)
            except ValueError:
                raise
            except OSError as exc:
                raise ValueError(
                    "manfred_candidate_release_authority_files_invalid"
                ) from exc
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

        if (
            set(os.listdir(root_descriptor)) != expected_names
            or identity(os.fstat(root_descriptor)) != identity(root_before)
        ):
            raise ValueError(
                "manfred_candidate_release_authority_files_changed"
            )
        try:
            final_root_descriptor = _open_directory_path_nofollow(
                normalized_root
            )
        except (OSError, ValueError) as exc:
            raise ValueError(
                "manfred_candidate_release_authority_root_changed"
            ) from exc
        try:
            if identity(os.fstat(final_root_descriptor)) != identity(root_before):
                raise ValueError(
                    "manfred_candidate_release_authority_root_changed"
                )
        finally:
            os.close(final_root_descriptor)
        return normalized_root, contents
    finally:
        os.close(root_descriptor)


def _validate_candidate_release_authority_bundle(
    root: Path,
    *,
    expected_commit: str,
    expected_image_id: str,
    expected_project_name: str,
    expected_public_origin: str,
    expected_voice_release_allowed: bool,
    expected_voice_identity: dict[str, str],
    expected_public_evaluation_allowed: bool = False,
) -> dict[str, object]:
    if (
        type(expected_voice_release_allowed) is not bool
        or type(expected_public_evaluation_allowed) is not bool
        or (
            expected_voice_release_allowed
            and expected_public_evaluation_allowed
        )
    ):
        raise ValueError("manfred_candidate_voice_release_state_invalid")
    expected_voice_runtime_enablement_allowed = (
        expected_voice_release_allowed or expected_public_evaluation_allowed
    )
    expected_voice_access_mode = (
        VOICE_ACCESS_MODE_PUBLIC_RELEASE
        if expected_voice_release_allowed
        else (
            VOICE_ACCESS_MODE_PUBLIC_EVALUATION
            if expected_public_evaluation_allowed
            else VOICE_ACCESS_MODE_TEXT_ONLY
        )
    )
    normalized_voice_identity = _voice_identity(
        voice_config_sha256=expected_voice_identity.get(
            "voice_config_sha256", ""
        ),
        voice_manifest_sha256=expected_voice_identity.get(
            "voice_manifest_sha256", ""
        ),
        voice_reference_aggregate_sha256=expected_voice_identity.get(
            "voice_reference_aggregate_sha256", ""
        ),
        provider_voice_id_sha256=expected_voice_identity.get(
            "provider_voice_id_sha256", ""
        ),
        tts_provider=expected_voice_identity.get("tts_provider", ""),
        tts_model=expected_voice_identity.get("tts_model", ""),
    )
    if expected_voice_identity != normalized_voice_identity:
        raise ValueError("manfred_candidate_voice_identity_invalid")
    unresolved_paths = _candidate_release_authority_paths(
        root,
        voice_release_included=expected_voice_runtime_enablement_allowed,
    )
    normalized_root, contents_by_filename = (
        _candidate_release_authority_snapshot(
            root,
            expected_names={
                path.name for path in unresolved_paths.values()
            },
        )
    )
    paths = _candidate_release_authority_paths(
        normalized_root,
        voice_release_included=expected_voice_runtime_enablement_allowed,
    )
    payloads: dict[str, dict[str, object]] = {}
    contents: dict[str, bytes] = {}
    for name, path in paths.items():
        contents[name] = contents_by_filename[path.name]
        payloads[name] = _strict_json_object(
            contents[name],
            error="manfred_candidate_release_authority_json_invalid",
        )
    manifest = payloads["release_manifest"]
    project_modes = payloads["project_modes"]
    deploy_context = payloads["deploy_context"]
    status = payloads["release_status"]
    voice_release = payloads.get("voice_release")
    receipt = payloads["receipt"]
    expected_deployment_id = (
        f"{_validate_project_name(expected_project_name)}-{expected_commit[:12]}"
    )
    container_paths = _candidate_release_authority_container_paths(
        voice_release_included=expected_voice_runtime_enablement_allowed,
    )
    document_evidence = {
        name: {
            "sha256": _sha256(contents[name]),
            "size_bytes": len(contents[name]),
        }
        for name in (
            "deploy_context",
            "project_modes",
            "release_manifest",
            "release_status",
            *(
                ("voice_release",)
                if expected_voice_runtime_enablement_allowed
                else ()
            ),
        )
    }
    voice_release_decision: dict[str, object] = {
        "allowed": False,
        "reason": "missing",
    }
    if expected_voice_runtime_enablement_allowed:
        if not isinstance(voice_release, dict):
            raise ValueError("manfred_candidate_voice_release_invalid")
        voice_release_decision = evaluate_memorial_voice_release_payload(
            slug="manfred",
            payload=voice_release,
            expected_source_revision=expected_commit,
            expected_public_origin=expected_public_origin,
            expected_image_id=expected_image_id,
            expected_voice_config_sha256=normalized_voice_identity[
                "voice_config_sha256"
            ],
            expected_voice_manifest_sha256=normalized_voice_identity[
                "voice_manifest_sha256"
            ],
            expected_voice_reference_aggregate_sha256=(
                normalized_voice_identity["voice_reference_aggregate_sha256"]
            ),
            expected_provider_voice_id_sha256=normalized_voice_identity[
                "provider_voice_id_sha256"
            ],
            expected_tts_provider=normalized_voice_identity["tts_provider"],
            expected_tts_model=normalized_voice_identity["tts_model"],
        )
    voice_release_artifact = (
        f"{CANDIDATE_RELEASE_AUTHORITY_DIRNAME}/"
        f"{CANDIDATE_RELEASE_AUTHORITY_FILENAMES['voice_release']}"
    )
    if (
        not COMMIT_RE.fullmatch(expected_commit)
        or not IMAGE_ID_RE.fullmatch(expected_image_id)
        or (
            expected_voice_runtime_enablement_allowed
            and _candidate_voice_authorization_state(voice_release_decision)
            != {
                "voice_release_allowed": expected_voice_release_allowed,
                "public_evaluation_allowed": (
                    expected_public_evaluation_allowed
                ),
                "voice_runtime_enablement_allowed": (
                    expected_voice_runtime_enablement_allowed
                ),
                "voice_access_mode": expected_voice_access_mode,
            }
        )
        or validate_release_authority(
            release_manifest=manifest,
            project_modes=project_modes,
        )
        or validate_release_runtime_mode(
            release_manifest=manifest,
            project_modes=project_modes,
            requested_mode="MEMORIAL",
            enabled_modes=["MEMORIAL", "PROPERTY"],
            compose_overrides=[],
            manfred_composite_candidate_observed=True,
        )
        or verify_deploy_context(deploy_context=deploy_context).get("status") != "pass"
        or manifest.get("commit_sha") != expected_commit
        or manifest.get("source_remote_ref_commit_sha") != expected_commit
        or manifest.get("source_commit_reachable_from_remote_ref") is not True
        or manifest.get("git_remote_origin") != OFFICIAL_EA_REMOTE_ORIGIN
        or manifest.get("live_remote_ref") != "refs/heads/main"
        or manifest.get("live_remote_ref_commit_sha") != expected_commit
        or manifest.get("live_remote_ref_evidence") != LIVE_REMOTE_REF_EVIDENCE
        or manifest.get("deployment_id") != expected_deployment_id
        or manifest.get("public_origin") != expected_public_origin
        or manifest.get("project_mode") != "MEMORIAL"
        or manifest.get("enabled_project_modes") != ["MEMORIAL", "PROPERTY"]
        or manifest.get("compose_files")
        != ["deploy/manfred-memorial/docker-compose.candidate.yml"]
        or manifest.get("compose_overrides") != []
        or (
            voice_release_artifact in list(manifest.get("artifact_set") or [])
        )
        is not expected_voice_runtime_enablement_allowed
        or deploy_context.get("commit_sha") != expected_commit
        or deploy_context.get("deployment_id") != expected_deployment_id
        or deploy_context.get("public_origin") != expected_public_origin
        or deploy_context.get("compose_files")
        != ["deploy/manfred-memorial/docker-compose.candidate.yml"]
        or deploy_context.get("compose_overrides") != []
        or project_modes.get("source_git_head") != expected_commit
        or status.get("contract_name") != "ea.release_authority_status.v1"
        or status.get("state") != "clear"
        or status.get("authority_posture") != "authoritative_runtime"
        or status.get("commit_sha") != expected_commit
        or status.get("deployment_id") != expected_deployment_id
        or status.get("manifest_path") != container_paths["release_manifest"]
        or status.get("deploy_context_path") != container_paths["deploy_context"]
        or status.get("project_modes_path") != container_paths["project_modes"]
        or status.get("candidate_runtime") is not True
        or status.get("promotion_authority") is not False
        or dict(status.get("gate") or {}).get("status") != "pass"
        or receipt.get("schema") != CANDIDATE_RELEASE_AUTHORITY_SCHEMA
        or receipt.get("status") != "pass"
        or receipt.get("commit_sha") != expected_commit
        or receipt.get("image_id") != expected_image_id
        or receipt.get("image_revision") != expected_commit
        or receipt.get("deployment_id") != expected_deployment_id
        or receipt.get("git_remote_origin") != OFFICIAL_EA_REMOTE_ORIGIN
        or receipt.get("live_remote_ref") != "refs/heads/main"
        or receipt.get("live_remote_ref_commit_sha") != expected_commit
        or receipt.get("live_remote_ref_evidence") != LIVE_REMOTE_REF_EVIDENCE
        or receipt.get("container_paths") != container_paths
        or receipt.get("documents") != document_evidence
        or receipt.get("runtime_authority_state") != "clear"
        or receipt.get("runtime_authority_posture") != "authoritative_runtime"
        or receipt.get("promotion_authority") is not False
        or receipt.get("voice_release_allowed")
        is not expected_voice_release_allowed
        or receipt.get("public_evaluation_allowed")
        is not expected_public_evaluation_allowed
        or receipt.get("voice_runtime_enablement_allowed")
        is not expected_voice_runtime_enablement_allowed
        or receipt.get("voice_access_mode") != expected_voice_access_mode
        or receipt.get("candidate_provider_boundary")
        != MANFRED_PROVIDER_FREE_CANDIDATE_BOUNDARY
        or receipt.get("final_voice_promotion_requires_live_review") is not True
        or receipt.get("final_voice_promotion_review_surface")
        != MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
        or any(
            receipt.get(name) != value
            for name, value in normalized_voice_identity.items()
        )
        or receipt.get("secret_material_recorded") is not False
    ):
        raise ValueError("manfred_candidate_release_authority_binding_invalid")
    return {
        "schema": CANDIDATE_RELEASE_AUTHORITY_SCHEMA,
        "status": "pass",
        "root": str(normalized_root),
        "commit_sha": expected_commit,
        "image_id": expected_image_id,
        "deployment_id": expected_deployment_id,
        "git_remote_origin": OFFICIAL_EA_REMOTE_ORIGIN,
        "live_remote_ref": "refs/heads/main",
        "live_remote_ref_commit_sha": expected_commit,
        "live_remote_ref_evidence": LIVE_REMOTE_REF_EVIDENCE,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL", "PROPERTY"],
        "container_paths": container_paths,
        "documents": document_evidence,
        "runtime_authority_state": "clear",
        "runtime_authority_posture": "authoritative_runtime",
        "promotion_authority": False,
        "voice_release_allowed": expected_voice_release_allowed,
        "public_evaluation_allowed": expected_public_evaluation_allowed,
        "voice_runtime_enablement_allowed": (
            expected_voice_runtime_enablement_allowed
        ),
        "voice_access_mode": expected_voice_access_mode,
        "descriptor_stable_read": True,
        "candidate_provider_boundary": MANFRED_PROVIDER_FREE_CANDIDATE_BOUNDARY,
        "final_voice_promotion_requires_live_review": True,
        "final_voice_promotion_review_surface": (
            MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
        ),
        "phase_1_live_review_verified": bool(
            expected_voice_release_allowed
            and isinstance(voice_release, dict)
            and voice_release.get("operator_acceptance_verified") is True
            and voice_release.get("operator_acceptance_review_surface")
            == MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
        ),
        **normalized_voice_identity,
        "secret_material_recorded": False,
    }


def _load_private_context(
    source_root: Path, slug: str
) -> tuple[dict[str, object], bytes]:
    app_root = source_root / "ea"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from app.services.memorial_private_context import (  # noqa: PLC0415
        read_private_memorial_context_document,
    )

    return read_private_memorial_context_document(
        private_root=source_root / "memorial_data" / "private_memorial_profiles",
        slug=slug,
    )


def _declared_assets(
    public_payload: dict[str, object], private_overrides: dict[str, object]
) -> dict[Path, int]:
    merged = dict(public_payload)
    merged.update(private_overrides)
    assets: dict[Path, int] = {}

    def add(value: object, *, private: bool) -> None:
        if not str(value or "").strip():
            return
        assets[_safe_relative(value, suffix_required=True)] = (
            0o400 if private else 0o444
        )

    for field in ("audio_clips", "public_documents", "candidate_recordings"):
        rows = merged.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            visibility = str(row.get("visibility") or "").strip().lower()
            add(row.get("asset_relpath"), private=visibility != "public")
    for field in ("pwa_icon", "video_call_avatar"):
        row = merged.get(field)
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if "relpath" in str(key) or str(key).startswith("src_"):
                add(value, private=False)
    return assets


def _copy_archive(
    *, source_root: Path, commit: str, destination: Path
) -> list[dict[str, object]]:
    archive = _run(
        ["git", "archive", "--format=tar", commit, "memorial_archive/manfred/public"],
        cwd=source_root,
    )
    receipts: list[dict[str, object]] = []
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("manfred_candidate_archive_entry_invalid")
            relative = _safe_relative(member.name)
            prefix = Path("memorial_archive")
            try:
                projected = relative.relative_to(prefix)
            except ValueError as exc:
                raise ValueError("manfred_candidate_archive_path_invalid") from exc
            extracted = bundle.extractfile(member)
            if extracted is None:
                raise ValueError("manfred_candidate_archive_entry_invalid")
            content = extracted.read(MAX_ARCHIVE_BYTES + 1)
            total += len(content)
            if len(content) != member.size or total > MAX_ARCHIVE_BYTES:
                raise ValueError("manfred_candidate_archive_size_invalid")
            target = destination / projected
            info = _write_bytes(target, content, mode=0o444)
            receipts.append({"path": projected.as_posix(), **info})
    return sorted(receipts, key=lambda item: str(item["path"]))


def _tree_digest(root: Path) -> tuple[str, list[dict[str, object]]]:
    def directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def file_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    file_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(root, directory_flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_projection_root_invalid") from exc
    rows: list[dict[str, object]] = []
    try:
        root_metadata = os.fstat(root_descriptor)
        try:
            root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("manfred_candidate_projection_root_invalid") from exc
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_ISLNK(root_path_metadata.st_mode)
            or stat.S_IMODE(root_metadata.st_mode) != 0o550
            or (root_metadata.st_dev, root_metadata.st_ino)
            != (root_path_metadata.st_dev, root_path_metadata.st_ino)
        ):
            raise ValueError("manfred_candidate_projection_root_invalid")

        def walk(directory_descriptor: int, relative: tuple[str, ...]) -> None:
            before = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o550
            ):
                raise ValueError("manfred_candidate_projection_directory_mode_invalid")
            try:
                with os.scandir(directory_descriptor) as iterator:
                    entries = sorted(iterator, key=lambda row: row.name)
            except OSError as exc:
                raise ValueError("manfred_candidate_projection_entry_invalid") from exc
            for entry in entries:
                name = entry.name
                try:
                    initial = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_projection_changed_during_digest"
                    ) from exc
                projected = (*relative, name)
                if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
                    try:
                        child_descriptor = os.open(
                            name,
                            directory_flags,
                            dir_fd=directory_descriptor,
                        )
                    except OSError as exc:
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        ) from exc
                    try:
                        opened = os.fstat(child_descriptor)
                        if (
                            directory_identity(initial) != directory_identity(opened)
                            or stat.S_IMODE(opened.st_mode) != 0o550
                        ):
                            raise ValueError(
                                "manfred_candidate_projection_changed_during_digest"
                            )
                        walk(child_descriptor, projected)
                        if directory_identity(opened) != directory_identity(
                            os.fstat(child_descriptor)
                        ):
                            raise ValueError(
                                "manfred_candidate_projection_changed_during_digest"
                            )
                    finally:
                        os.close(child_descriptor)
                    continue
                if not stat.S_ISREG(initial.st_mode) or stat.S_ISLNK(initial.st_mode):
                    raise ValueError("manfred_candidate_projection_entry_invalid")
                if initial.st_nlink != 1:
                    raise ValueError("manfred_candidate_projection_file_links_invalid")
                mode = stat.S_IMODE(initial.st_mode)
                if mode not in {0o440, 0o444}:
                    raise ValueError("manfred_candidate_projection_file_mode_invalid")
                try:
                    file_descriptor = os.open(
                        name,
                        file_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_projection_changed_during_digest"
                    ) from exc
                try:
                    opened = os.fstat(file_descriptor)
                    if (
                        file_identity(initial) != file_identity(opened)
                        or not stat.S_ISREG(opened.st_mode)
                        or opened.st_nlink != 1
                    ):
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        )
                    digest = hashlib.sha256()
                    size = 0
                    while True:
                        chunk = os.read(file_descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                    final = os.fstat(file_descriptor)
                    if file_identity(opened) != file_identity(final) or size != int(
                        opened.st_size
                    ):
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        )
                finally:
                    os.close(file_descriptor)
                rows.append(
                    {
                        "path": PurePosixPath(*projected).as_posix(),
                        "sha256": digest.hexdigest(),
                        "size_bytes": size,
                        "mode": format(mode, "03o"),
                    }
                )
            if directory_identity(before) != directory_identity(
                os.fstat(directory_descriptor)
            ):
                raise ValueError("manfred_candidate_projection_changed_during_digest")

        walk(root_descriptor, ())
        final_root_metadata = os.fstat(root_descriptor)
        try:
            final_root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError(
                "manfred_candidate_projection_changed_during_digest"
            ) from exc
        if directory_identity(root_metadata) != directory_identity(
            final_root_metadata
        ) or (final_root_metadata.st_dev, final_root_metadata.st_ino) != (
            final_root_path_metadata.st_dev,
            final_root_path_metadata.st_ino,
        ):
            raise ValueError("manfred_candidate_projection_changed_during_digest")
    finally:
        os.close(root_descriptor)
    encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _sha256(encoded), rows


def _set_modes(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o550)
        elif path.is_file():
            current = stat.S_IMODE(path.stat().st_mode)
            path.chmod(0o440 if current & 0o044 == 0 else 0o444)
    root.chmod(0o550)


def _make_tree_removable(root: Path) -> None:
    if not root.exists():
        return
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)


def _install_or_verify_release(
    *,
    staging: Path,
    release_root: Path,
    projection_sha256: str,
    projected_files: list[dict[str, object]],
) -> None:
    if release_root.exists():
        if release_root.is_symlink() or not release_root.is_dir():
            raise ValueError("manfred_candidate_existing_release_invalid")
        try:
            existing_sha256, existing_files = _tree_digest(release_root)
        except (OSError, ValueError) as exc:
            raise ValueError("manfred_candidate_existing_release_unverifiable") from exc
        if existing_sha256 != projection_sha256 or existing_files != projected_files:
            raise ValueError("manfred_candidate_existing_release_digest_mismatch")
        _make_tree_removable(staging)
        shutil.rmtree(staging)
        return
    os.replace(staging, release_root)


def _chown_for_runtime(paths: list[Path], *, uid: int, gid: int) -> None:
    if os.geteuid() == 0:
        for root in paths:
            os.chown(root, uid, gid)
            for path in root.rglob("*"):
                os.chown(path, uid, gid, follow_symlinks=False)
        return
    command = (
        "chown -R "
        + f"{uid}:{gid} "
        + " ".join(f"/target/{index}" for index in range(len(paths)))
    )
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "0:0",
        "--read-only",
        "--pull",
        "never",
        "--entrypoint",
        "/bin/sh",
    ]
    for index, path in enumerate(paths):
        argv.extend(["--volume", f"{path.resolve()}:/target/{index}:rw"])
    argv.extend([HELPER_IMAGE, "-ec", command])
    _run(argv)


def _validate_public_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    try:
        parsed = urlparse(normalized)
    except ValueError as exc:
        raise ValueError("manfred_candidate_public_base_url_invalid") from exc
    host = str(parsed.hostname or "").strip().lower().strip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or parsed.path not in {"", "/"}
        or host in {"localhost", "127.0.0.1", "example.test", "example.invalid"}
        or host.endswith(".invalid")
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".test")
    ):
        raise ValueError("manfred_candidate_public_base_url_invalid")
    return normalized


def _image_revision(image: str) -> tuple[str, str]:
    if not image or image.lower() == "latest" or image.lower().endswith(":latest"):
        raise ValueError("manfred_candidate_image_tag_invalid")
    payload = json.loads(_run(["docker", "image", "inspect", image]))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("manfred_candidate_image_missing")
    row = payload[0]
    labels = dict((row.get("Config") or {}).get("Labels") or {})
    return str(row.get("Id") or ""), str(
        labels.get("org.opencontainers.image.revision") or ""
    )


def _read_private_output(
    path: Path,
    *,
    maximum: int = PRIVATE_OUTPUT_MAX_BYTES,
    missing_ok: bool = False,
) -> bytes | None:
    absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    if missing_ok and not os.path.lexists(absolute):
        return None
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_private_output_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise ValueError("manfred_candidate_private_output_invalid")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise ValueError("manfred_candidate_private_output_changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_status = os.stat(absolute, follow_symlinks=False)
    except OSError as exc:
        raise ValueError("manfred_candidate_private_output_changed") from exc
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or (path_status.st_dev, path_status.st_ino) != (before.st_dev, before.st_ino):
        raise ValueError("manfred_candidate_private_output_changed")
    return b"".join(chunks)


def _install_private_output_noreplace(
    path: Path,
    content: bytes,
    *,
    conflict_error: str,
) -> bool:
    """Install private evidence once; return True only for exact-byte reuse."""

    if not content or len(content) > PRIVATE_OUTPUT_MAX_BYTES:
        raise ValueError("manfred_candidate_private_output_invalid")
    path = Path(os.path.abspath(os.fspath(path.expanduser())))
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        parent = path.parent.resolve(strict=True)
        parent_status = parent.stat()
    except OSError as exc:
        raise ValueError("manfred_candidate_private_output_parent_invalid") from exc
    if (
        parent != path.parent
        or not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or stat.S_IMODE(parent_status.st_mode) & 0o022
    ):
        raise ValueError("manfred_candidate_private_output_parent_invalid")

    existing = _read_private_output(path, missing_ok=True)
    if existing is not None:
        if existing == content:
            return True
        raise ValueError(conflict_error)

    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary_path = Path(temporary)
    directory_descriptor = -1
    installed = False
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ValueError("manfred_candidate_private_output_write_failed")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            _rename_noreplace(
                directory_descriptor,
                temporary_path.name,
                directory_descriptor,
                path.name,
            )
            installed = True
            temporary = ""
        except ValueError as exc:
            if str(exc) != "manfred_candidate_spatial_output_exists":
                raise ValueError(
                    "manfred_candidate_private_output_install_failed"
                ) from exc
            existing = _read_private_output(path)
            if existing != content:
                raise ValueError(conflict_error) from exc
        os.fsync(directory_descriptor)
        observed = _read_private_output(path)
        if observed != content:
            raise ValueError("manfred_candidate_private_output_changed")
        return not installed
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)
        if temporary:
            temporary_path.unlink(missing_ok=True)


def _parse_env_bytes(content: bytes) -> dict[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("manfred_candidate_env_invalid") from exc
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("manfred_candidate_env_invalid")
        key, value = line.split("=", 1)
        if (
            not key
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                for character in key
            )
            or key in values
        ):
            raise ValueError("manfred_candidate_env_invalid")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("manfred_candidate_env_invalid")
        values[key] = value
    return values


def _parse_env(path: Path) -> dict[str, str]:
    content = _read_private_output(path, missing_ok=True)
    if content is None:
        return {}
    return _parse_env_bytes(content)


def _write_env(
    *,
    path: Path,
    image: str,
    release_root: Path,
    runtime_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    commit: str,
    image_id: str,
    voice_identity: dict[str, str],
    spatial_release_root: Path | None = None,
    spatial_handoff_included: bool = False,
    spatial_slug: str = "",
    spatial_sha256: str = "",
    rotate_secrets: bool = False,
) -> None:
    if not COMMIT_RE.fullmatch(commit) or not IMAGE_ID_RE.fullmatch(image_id):
        raise ValueError("manfred_candidate_commit_invalid")
    normalized_voice_identity = _voice_identity(
        voice_config_sha256=voice_identity.get("voice_config_sha256", ""),
        voice_manifest_sha256=voice_identity.get("voice_manifest_sha256", ""),
        voice_reference_aggregate_sha256=voice_identity.get(
            "voice_reference_aggregate_sha256", ""
        ),
        provider_voice_id_sha256=voice_identity.get(
            "provider_voice_id_sha256", ""
        ),
        tts_provider=voice_identity.get("tts_provider", ""),
        tts_model=voice_identity.get("tts_model", ""),
    )
    if voice_identity != normalized_voice_identity:
        raise ValueError("manfred_candidate_voice_identity_invalid")
    normalized_project_name = _validate_project_name(project_name)
    deployment_id = f"{normalized_project_name}-{commit[:12]}"
    current = _parse_env(path)
    postgres_password = (
        "" if rotate_secrets else current.get("EA_MANFRED_POSTGRES_PASSWORD", "")
    ) or secrets.token_hex(32)
    api_token = (
        "" if rotate_secrets else current.get("EA_API_TOKEN", "")
    ) or secrets.token_urlsafe(48)
    signing_secret = (
        "" if rotate_secrets else current.get("EA_SIGNING_SECRET", "")
    ) or secrets.token_urlsafe(64)
    resolved_spatial_root = (
        spatial_release_root or (release_root / "public_property_tours")
    ).resolve()
    normalized_spatial_sha256 = spatial_sha256 or _sha256(b"[]")
    if not SHA256_RE.fullmatch(normalized_spatial_sha256):
        raise ValueError("manfred_candidate_spatial_digest_invalid")
    if spatial_handoff_included != bool(spatial_slug):
        raise ValueError("manfred_candidate_spatial_slug_invalid")
    values = {
        "EA_MANFRED_COMMIT": commit,
        "EA_MANFRED_COMPOSE_PROJECT": normalized_project_name,
        "EA_MANFRED_DEPLOYMENT_ID": deployment_id,
        "EA_MANFRED_IMAGE": image,
        "EA_MANFRED_ENV_FILE": str(path.resolve()),
        "EA_MANFRED_RELEASE_ROOT": str(release_root.resolve()),
        "EA_MANFRED_RELEASE_AUTHORITY_ROOT": str(
            (release_root / CANDIDATE_RELEASE_AUTHORITY_DIRNAME).resolve()
        ),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root.resolve()),
        "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED": (
            "1" if spatial_handoff_included else "0"
        ),
        "EA_MANFRED_SPATIAL_RELEASE_ROOT": str(resolved_spatial_root),
        "EA_MANFRED_SPATIAL_SHA256": normalized_spatial_sha256,
        "EA_MANFRED_SPATIAL_SLUG": spatial_slug,
        "EA_MANFRED_HOST_PORT": str(host_port),
        "EA_MANFRED_POSTGRES_PASSWORD": postgres_password,
        "DATABASE_URL": f"postgresql://ea:{postgres_password}@postgres:5432/ea",
        "EA_API_TOKEN": api_token,
        "EA_DEPLOY_IMAGE_ID": image_id,
        "EA_MEMORIAL_BLIPAI_STT_TIMEOUT_SECONDS": "8",
        "EA_MEMORIAL_PROVIDER_VOICE_ID_SHA256": normalized_voice_identity[
            "provider_voice_id_sha256"
        ],
        "EA_MEMORIAL_STT_PRIMARY_PROVIDER": "blipai",
        "EA_MEMORIAL_TTS_MODEL": normalized_voice_identity["tts_model"],
        "EA_MEMORIAL_TTS_PROVIDER": normalized_voice_identity["tts_provider"],
        "EA_MEMORIAL_VOICE_CONFIG_SHA256": normalized_voice_identity[
            "voice_config_sha256"
        ],
        "EA_MEMORIAL_VOICE_IDENTITY_SHA256": normalized_voice_identity[
            "voice_identity_sha256"
        ],
        "EA_MEMORIAL_VOICE_MANIFEST_SHA256": normalized_voice_identity[
            "voice_manifest_sha256"
        ],
        "EA_MEMORIAL_VOICE_REFERENCE_AGGREGATE_SHA256": (
            normalized_voice_identity["voice_reference_aggregate_sha256"]
        ),
        "EA_SIGNING_SECRET": signing_secret,
        "EA_PUBLIC_APP_BASE_URL": public_base_url,
    }
    encoded = "".join(f"{key}={values[key]}\n" for key in sorted(values)).encode(
        "utf-8"
    )
    _install_private_output_noreplace(
        path,
        encoded,
        conflict_error="manfred_candidate_env_existing_conflict",
    )


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    _install_private_output_noreplace(
        path,
        _receipt_bytes(payload),
        conflict_error="manfred_candidate_receipt_existing_conflict",
    )


def _hold_candidate_preparation_fleet_lock(function):  # type: ignore[no-untyped-def]
    @functools.wraps(function)
    def locked(*args, **kwargs):  # type: ignore[no-untyped-def]
        with hold_candidate_fleet_lock() as evidence:
            if evidence is None:  # pragma: no cover - raising mode
                raise RuntimeError("manfred_candidate_fleet_lock_held")
            return function(*args, **kwargs)

    return locked


@_hold_candidate_preparation_fleet_lock
def prepare_candidate(
    *,
    source_root: Path,
    ref: str,
    image: str,
    deploy_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    spatial_tour_bundle_dir: Path | None = None,
    spatial_authority_receipt: Path | None = None,
    spatial_final_review_receipt: Path | None = None,
    spatial_browser_review_receipt: Path | None = None,
    voice_source_provenance_receipt: Path | None = None,
    voice_release_receipt: Path | None = None,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
    runtime_uid: int = 10001,
    runtime_gid: int = 10001,
    rotate_secrets: bool = False,
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    deploy_root = deploy_root.expanduser().resolve()
    if not 1024 <= host_port <= 65535:
        raise ValueError("manfred_candidate_host_port_invalid")
    project_name = _validate_project_name(project_name)
    public_base_url = _validate_public_base_url(public_base_url)
    if bool(spatial_tour_bundle_dir) != bool(spatial_authority_receipt):
        raise ValueError("manfred_candidate_spatial_input_pair_required")
    if bool(spatial_final_review_receipt) != bool(spatial_browser_review_receipt):
        raise ValueError("manfred_candidate_spatial_review_input_pair_required")
    if bool(spatial_tour_bundle_dir) != bool(spatial_final_review_receipt):
        raise ValueError("manfred_candidate_spatial_review_evidence_required")
    if not all(
        (
            spatial_tour_bundle_dir,
            spatial_authority_receipt,
            spatial_final_review_receipt,
            spatial_browser_review_receipt,
        )
    ):
        raise ValueError("manfred_candidate_spatial_handoff_required")
    provider_voice_id_sha256 = str(provider_voice_id_sha256 or "").strip()
    tts_provider = str(tts_provider or "").strip()
    tts_model = str(tts_model or "").strip()
    if (
        not SHA256_RE.fullmatch(provider_voice_id_sha256)
        or tts_provider != MANFRED_TTS_PROVIDER
        or tts_model != MANFRED_TTS_MODEL
    ):
        raise ValueError("manfred_candidate_voice_provider_binding_invalid")
    if (
        voice_release_receipt is not None
        and voice_source_provenance_receipt is None
    ):
        raise ValueError(
            "manfred_candidate_voice_source_provenance_required"
        )
    commit = _commit(source_root, ref)
    image_id, image_commit = _image_revision(image)
    if image_commit != commit or not IMAGE_ID_RE.fullmatch(image_id):
        raise ValueError("manfred_candidate_image_revision_mismatch")
    voice_source_provenance_bytes = (
        _read_private_output(
            voice_source_provenance_receipt,
            maximum=PRIVATE_OUTPUT_MAX_BYTES,
        )
        if voice_source_provenance_receipt is not None
        else None
    )
    voice_source_provenance_sha256 = (
        _validated_voice_source_provenance_receipt_sha256(
            voice_source_provenance_bytes
        )
        if voice_source_provenance_bytes is not None
        else ""
    )
    voice_release_bytes = (
        _read_private_output(
            voice_release_receipt,
            maximum=PRIVATE_OUTPUT_MAX_BYTES,
        )
        if voice_release_receipt is not None
        else None
    )
    spatial_handoff: dict[str, object] = {
        "included": False,
        "slug": "",
        "files": {},
        "asset_paths": [],
        "viewer_relpath": "",
        "proof_relpath": "",
        "route_labels": [],
        "upstream_publication_authority": {},
        "upstream_publication_authority_sha256": "",
        "upstream_public_activation_authority": False,
        "upstream_package_sha256": "",
        "upstream_tour_manifest_sha256": "",
        "pre_authority_manifest_canonical_sha256": "",
        "review_evidence": {},
        "verifier_receipt": {},
    }
    if (
        spatial_tour_bundle_dir
        and spatial_authority_receipt
        and spatial_final_review_receipt
        and spatial_browser_review_receipt
    ):
        spatial_handoff = _validated_spatial_handoff_input(
            bundle_dir=Path(
                os.path.abspath(os.fspath(spatial_tour_bundle_dir.expanduser()))
            ),
            authority_receipt_path=Path(
                os.path.abspath(os.fspath(spatial_authority_receipt.expanduser()))
            ),
            final_review_receipt_path=Path(
                os.path.abspath(os.fspath(spatial_final_review_receipt.expanduser()))
            ),
            browser_review_receipt_path=Path(
                os.path.abspath(os.fspath(spatial_browser_review_receipt.expanduser()))
            ),
            target_origin=public_base_url,
        )

    slug = "manfred"
    public_documents: dict[str, bytes] = {}
    for name in PUBLIC_GIT_FILES:
        public_documents[name] = _git_blob(
            source_root,
            commit,
            f"memorial_data/public_memorials/{slug}/{name}",
        )
    try:
        public_payload = json.loads(public_documents["memorial.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manfred_candidate_public_manifest_invalid") from exc
    if not isinstance(public_payload, dict) or public_payload.get("slug") != slug:
        raise ValueError("manfred_candidate_public_manifest_invalid")
    private_overrides, private_document = _load_private_context(source_root, slug)

    releases_root = deploy_root / "releases"
    receipts_root = deploy_root / "receipts"
    runtime_root = deploy_root / "runtime"
    releases_root.mkdir(parents=True, exist_ok=True)
    receipts_root.mkdir(parents=True, exist_ok=True)
    staging = releases_root / f".{commit[:12]}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(mode=0o700)
    try:
        public_root = staging / "public_memorials" / slug
        private_root = staging / "private_memorial_profiles" / slug
        archive_root = staging / "memorial_archive"
        spatial_root = staging / "public_property_tours"
        spatial_root.mkdir(mode=0o700)
        file_receipts: list[dict[str, object]] = []
        for name, content in public_documents.items():
            info = _write_bytes(public_root / name, content, mode=0o444)
            file_receipts.append({"path": f"public_memorials/{slug}/{name}", **info})
        public_source = source_root / "memorial_data" / "public_memorials" / slug
        for relative, mode in sorted(
            _declared_assets(public_payload, private_overrides).items(),
            key=lambda item: item[0].as_posix(),
        ):
            info = _copy_regular(
                public_source / relative,
                public_root / relative,
                maximum=MAX_ASSET_BYTES,
                mode=mode,
            )
            file_receipts.append(
                {"path": f"public_memorials/{slug}/{relative.as_posix()}", **info}
            )

        private_source = (
            source_root / "memorial_data" / "private_memorial_profiles" / slug
        )
        voice_config_bytes: bytes | None = None
        for name in PRIVATE_METADATA_FILES:
            source = private_source / name
            if name == PRIVATE_CONTEXT_FILENAME:
                info = _write_bytes(private_root / name, private_document, mode=0o400)
            elif name == "voice_profile_manifest.json":
                continue
            elif name == "tts_voice.json":
                content = _read_regular_source(
                    source,
                    maximum=8 * 1024 * 1024,
                    missing_ok=True,
                )
                if content is None:
                    continue
                info = _write_bytes(private_root / name, content, mode=0o400)
                voice_config_bytes = content
            elif source.exists():
                info = _copy_regular(
                    source, private_root / name, maximum=8 * 1024 * 1024, mode=0o400
                )
            else:
                continue
            file_receipts.append(
                {"path": f"private_memorial_profiles/{slug}/{name}", **info}
            )

        if voice_config_bytes is None:
            raise ValueError("manfred_candidate_voice_config_required")
        voice_manifest_bytes, voice_identity = _hosted_clone_voice_binding(
            voice_config_bytes=voice_config_bytes,
            provider_voice_id_sha256=provider_voice_id_sha256,
            tts_provider=tts_provider,
            tts_model=tts_model,
            source_provenance_receipt_sha256=(
                voice_source_provenance_sha256
            ),
        )
        manifest_info = _write_bytes(
            private_root / "voice_profile_manifest.json",
            voice_manifest_bytes,
            mode=0o600,
        )
        file_receipts.append(
            {
                "path": (
                    f"private_memorial_profiles/{slug}/"
                    "voice_profile_manifest.json"
                ),
                **manifest_info,
            }
        )

        archive_receipts = _copy_archive(
            source_root=source_root,
            commit=commit,
            destination=archive_root,
        )
        file_receipts.extend(
            {
                "path": f"memorial_archive/{row['path']}",
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
            for row in archive_receipts
        )
        spatial_slug = str(spatial_handoff.get("slug") or "")
        if spatial_handoff.get("included") is True:
            spatial_files = dict(spatial_handoff.get("files") or {})
            for relpath, content in sorted(spatial_files.items()):
                if not isinstance(content, bytes):
                    raise ValueError("manfred_candidate_spatial_source_invalid")
                info = _write_bytes(
                    spatial_root / spatial_slug / _safe_relative(relpath),
                    content,
                    mode=0o444,
                )
                file_receipts.append(
                    {
                        "path": (f"public_property_tours/{spatial_slug}/{relpath}"),
                        **info,
                    }
                )
        authority_generated_at = _commit_generated_at(source_root, commit)
        created_at = authority_generated_at
        public_release_artifacts = [
            str(row.get("path") or "")
            for row in file_receipts
            if str(row.get("path") or "").startswith(
                ("public_memorials/", "public_property_tours/", "memorial_archive/")
            )
        ]
        authority_root = staging / CANDIDATE_RELEASE_AUTHORITY_DIRNAME
        staged_release_authority = _materialize_candidate_release_authority(
            root=authority_root,
            source_root=source_root,
            commit=commit,
            image_id=image_id,
            image_revision=image_commit,
            project_name=project_name,
            public_origin=public_base_url,
            generated_at=authority_generated_at,
            public_artifacts=public_release_artifacts,
            voice_identity=voice_identity,
            voice_release_bytes=voice_release_bytes,
        )
        _set_modes(staging)
        _authority_digest, authority_files = _tree_digest(authority_root)
        file_receipts.extend(
            {
                "path": (f"{CANDIDATE_RELEASE_AUTHORITY_DIRNAME}/{row['path']}"),
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
            for row in authority_files
        )
        spatial_projection_sha256, spatial_projected_files = _tree_digest(spatial_root)
        projection_sha256, projected_files = _tree_digest(staging)
        release_id = f"{commit[:12]}-{projection_sha256[:12]}"
        release_root = releases_root / release_id
        _install_or_verify_release(
            staging=staging,
            release_root=release_root,
            projection_sha256=projection_sha256,
            projected_files=projected_files,
        )

        public_contributions = runtime_root / "public-contributions"
        private_contributions = runtime_root / "private-contributions"
        state_root = runtime_root / "state"
        for path, mode in (
            (public_contributions, 0o700),
            (private_contributions, 0o700),
            (state_root, 0o700),
        ):
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                path.chmod(mode)
        operator_gid = os.getgid()
        _chown_for_runtime([release_root], uid=runtime_uid, gid=operator_gid)
        _chown_for_runtime(
            [public_contributions, private_contributions, state_root],
            uid=runtime_uid,
            gid=runtime_gid,
        )

        env_path = deploy_root / "candidate.env"
        _write_env(
            path=env_path,
            image=image,
            release_root=release_root,
            runtime_root=runtime_root,
            public_base_url=public_base_url,
            host_port=host_port,
            project_name=project_name,
            commit=commit,
            image_id=image_id,
            voice_identity=voice_identity,
            spatial_release_root=release_root / "public_property_tours",
            spatial_handoff_included=bool(spatial_handoff.get("included")),
            spatial_slug=spatial_slug,
            spatial_sha256=spatial_projection_sha256,
            rotate_secrets=rotate_secrets,
        )
        release_authority = _validate_candidate_release_authority_bundle(
            release_root / CANDIDATE_RELEASE_AUTHORITY_DIRNAME,
            expected_commit=commit,
            expected_image_id=image_id,
            expected_project_name=project_name,
            expected_public_origin=public_base_url,
            expected_voice_release_allowed=bool(
                staged_release_authority["voice_release_allowed"]
            ),
            expected_voice_identity=voice_identity,
            expected_public_evaluation_allowed=bool(
                staged_release_authority["public_evaluation_allowed"]
            ),
        )
        spatial_receipt_path = receipts_root / f"{release_id}.spatial.json"
        spatial_receipt = {
            "schema": SPATIAL_PROJECTION_SCHEMA,
            "status": "pass",
            "created_at": created_at,
            "release_id": release_id,
            "spatial_handoff_included": bool(spatial_handoff.get("included")),
            "slug": spatial_slug,
            "spatial_release_root": str(
                (release_root / "public_property_tours").resolve()
            ),
            "spatial_projection_sha256": spatial_projection_sha256,
            "file_count": len(spatial_projected_files),
            "projection_bytes": sum(
                int(row["size_bytes"]) for row in spatial_projected_files
            ),
            "files": spatial_projected_files,
            "asset_paths": list(spatial_handoff.get("asset_paths") or []),
            "viewer_relpath": str(spatial_handoff.get("viewer_relpath") or ""),
            "proof_relpath": str(spatial_handoff.get("proof_relpath") or ""),
            "route_labels": list(spatial_handoff.get("route_labels") or []),
            "upstream_publication_authority": dict(
                spatial_handoff.get("upstream_publication_authority") or {}
            ),
            "upstream_publication_authority_sha256": str(
                spatial_handoff.get("upstream_publication_authority_sha256") or ""
            ),
            "upstream_public_activation_authority": bool(
                spatial_handoff.get("upstream_public_activation_authority")
            ),
            "upstream_package_sha256": str(
                spatial_handoff.get("upstream_package_sha256") or ""
            ),
            "upstream_tour_manifest_sha256": str(
                spatial_handoff.get("upstream_tour_manifest_sha256") or ""
            ),
            "pre_authority_manifest_canonical_sha256": str(
                spatial_handoff.get("pre_authority_manifest_canonical_sha256") or ""
            ),
            "review_evidence": dict(spatial_handoff.get("review_evidence") or {}),
            "source_verifier": dict(spatial_handoff.get("verifier_receipt") or {}),
            "candidate_handoff_authorized": bool(spatial_handoff.get("included")),
            "public_activation_authority": False,
        }
        spatial_receipt_bytes = _receipt_bytes(spatial_receipt)
        _atomic_receipt(spatial_receipt_path, spatial_receipt)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "pass",
            "created_at": created_at,
            "commit": commit,
            "image": image,
            "image_id": image_id,
            "public_origin": public_base_url,
            "release_id": release_id,
            "release_root": str(release_root),
            "runtime_root": str(runtime_root),
            "env_file": str(env_path),
            "host_port": host_port,
            "compose_project": project_name,
            "projection_sha256": projection_sha256,
            "private_context_sha256": _sha256(private_document),
            "file_count": len(projected_files),
            "projection_bytes": sum(int(row["size_bytes"]) for row in projected_files),
            "tracked_public_manifest": True,
            "tracked_public_archive_only": True,
            "private_context_in_image": False,
            "provider_credentials_in_candidate_env": False,
            "candidate_secrets_rotated": rotate_secrets,
            "runtime_uid": runtime_uid,
            "runtime_gid": runtime_gid,
            "projection_operator_gid": operator_gid,
            "spatial_handoff_included": bool(spatial_handoff.get("included")),
            "spatial_slug": spatial_slug,
            "spatial_release_root": str(
                (release_root / "public_property_tours").resolve()
            ),
            "spatial_projection_sha256": spatial_projection_sha256,
            "spatial_file_count": len(spatial_projected_files),
            "spatial_projection_bytes": sum(
                int(row["size_bytes"]) for row in spatial_projected_files
            ),
            "spatial_receipt_path": str(spatial_receipt_path.resolve()),
            "spatial_receipt_sha256": _sha256(spatial_receipt_bytes),
            "spatial_upstream_public_activation_authority": bool(
                spatial_handoff.get("upstream_public_activation_authority")
            ),
            "spatial_ea_public_activation_authority": False,
            "release_authority": release_authority,
            "release_authority_runtime_clear": True,
            "release_authority_promotion_authority": False,
            "voice_release_allowed": release_authority[
                "voice_release_allowed"
            ],
            "public_evaluation_allowed": release_authority[
                "public_evaluation_allowed"
            ],
            "voice_runtime_enablement_allowed": release_authority[
                "voice_runtime_enablement_allowed"
            ],
            "voice_access_mode": release_authority["voice_access_mode"],
            "voice_release_receipt_sha256": (
                _sha256(voice_release_bytes)
                if release_authority["voice_release_allowed"] is True
                else ""
            ),
            "public_evaluation_receipt_sha256": (
                _sha256(voice_release_bytes)
                if release_authority["public_evaluation_allowed"] is True
                else ""
            ),
            "voice_authorization_receipt_sha256": (
                _sha256(voice_release_bytes)
                if voice_release_bytes is not None
                else ""
            ),
            **voice_identity,
        }
        _atomic_receipt(receipts_root / f"{release_id}.json", receipt)
        return receipt
    finally:
        if staging.exists():
            _make_tree_removable(staging)
            shutil.rmtree(staging)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a private, hash-receipted Manfred Memorial candidate projection."
    )
    parser.add_argument(
        "--source-root", default=str(Path(__file__).resolve().parents[1])
    )
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--deploy-root",
        default=str(Path("~/.local/share/ea-deploy/manfred-memorial")),
    )
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--host-port", type=int, default=18090)
    parser.add_argument(
        "--project-name",
        required=True,
        help="Unique ea-manfred-candidate-<deployment> Compose project name.",
    )
    parser.add_argument("--rotate-secrets", action="store_true")
    parser.add_argument(
        "--spatial-tour-bundle-dir",
        required=True,
        help="Required exact Property-owned six-file generated-viewer bundle.",
    )
    parser.add_argument(
        "--spatial-authority-receipt",
        required=True,
        help="Mode-0600 detached Property publication authority paired with the bundle.",
    )
    parser.add_argument(
        "--spatial-final-review-receipt",
        required=True,
        help="Mode-0600 pinned Property flagship final-review receipt paired with the bundle.",
    )
    parser.add_argument(
        "--spatial-browser-review-receipt",
        required=True,
        help="Mode-0600 pinned Property exact-viewer browser receipt paired with the bundle.",
    )
    parser.add_argument(
        "--voice-source-provenance-receipt",
        help=(
            "Optional mode-0600 private Manfred-only source-provenance "
            "receipt. Its exact-byte SHA-256 is bound; its content is never "
            "copied into the candidate. Required with --voice-release-receipt."
        ),
    )
    parser.add_argument(
        "--voice-release-receipt",
        help=(
            "Optional mode-0600 signed Manfred voice authorization: either "
            "the final human-reviewed release or the owner-authorized public "
            "evaluation receipt. Omit for the public-text-only phase."
        ),
    )
    parser.add_argument(
        "--provider-voice-id-sha256",
        required=True,
        help="SHA-256 of the resolved provider voice ID; never pass the raw ID.",
    )
    parser.add_argument(
        "--tts-provider",
        required=True,
        help=f"Exact governed TTS provider ({MANFRED_TTS_PROVIDER}).",
    )
    parser.add_argument(
        "--tts-model",
        required=True,
        help=f"Exact governed TTS model ({MANFRED_TTS_MODEL}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = prepare_candidate(
            source_root=Path(args.source_root),
            ref=args.ref,
            image=args.image,
            deploy_root=Path(args.deploy_root),
            public_base_url=args.public_base_url,
            host_port=args.host_port,
            project_name=args.project_name,
            spatial_tour_bundle_dir=(
                Path(args.spatial_tour_bundle_dir)
                if args.spatial_tour_bundle_dir
                else None
            ),
            spatial_authority_receipt=(
                Path(args.spatial_authority_receipt)
                if args.spatial_authority_receipt
                else None
            ),
            spatial_final_review_receipt=(
                Path(args.spatial_final_review_receipt)
                if args.spatial_final_review_receipt
                else None
            ),
            spatial_browser_review_receipt=(
                Path(args.spatial_browser_review_receipt)
                if args.spatial_browser_review_receipt
                else None
            ),
            voice_release_receipt=(
                Path(args.voice_release_receipt)
                if args.voice_release_receipt
                else None
            ),
            voice_source_provenance_receipt=(
                Path(args.voice_source_provenance_receipt)
                if args.voice_source_provenance_receipt
                else None
            ),
            provider_voice_id_sha256=args.provider_voice_id_sha256,
            tts_provider=args.tts_provider,
            tts_model=args.tts_model,
            rotate_secrets=args.rotate_secrets,
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "private_material_included": False,
                    "provider_credentials_included": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
