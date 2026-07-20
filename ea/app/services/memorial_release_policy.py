from __future__ import annotations

"""Runtime verification for the sealed Manfred conversation prerequisites.

The host-side prerequisites packet is not deploy authority.  Public voice is
enabled only when the governed deploy lane also sets the explicit activation
flag and the packet still binds every immutable file mounted into this exact
runtime.  Missing, mutable, stale, or ambiguous input always blocks before a
provider call.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import stat
import time
from typing import Any, Mapping
from urllib.parse import urlsplit


MANFRED_CONVERSATION_PREREQUISITES_CONTRACT = (
    "ea.manfred_realtime_conversation_release.v1"
)
MANFRED_CONVERSATION_PREREQUISITES_GENERATOR = (
    "ea/scripts/manfred_realtime_conversation_release.py"
)
MEMORIAL_VOICE_RELEASE_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MEMORIAL_PUBLIC_ORIGINS = frozenset({"https://myexternalbrain.com"})

_READINESS_FILENAME = "manfred_realtime_conversation_readiness.generated.json"
_ROOM_FILENAME = "memorial_room_audio_public_origin.generated.json"
_EVIDENCE_FILES = {
    "stt_candidate": (
        "memorial_stt_fixture_candidate.generated.json",
        72 * 60 * 60,
    ),
    "stt_captured_benchmark": (
        "memorial_stt_provider_benchmark_captured_candidate.generated.json",
        72 * 60 * 60,
    ),
    "stt_benchmark": (
        "memorial_stt_provider_benchmark.generated.json",
        72 * 60 * 60,
    ),
    "captured_candidate_diagnostic": (
        "memorial_stt_captured_candidate_diagnostic.generated.json",
        72 * 60 * 60,
    ),
    "voice_roundtrip": (
        "memorial_voice_roundtrip_public_origin.generated.json",
        72 * 60 * 60,
    ),
    "realtime_browser": (
        "memorial_realtime_browser_public_origin.generated.json",
        24 * 60 * 60,
    ),
    "room_audio": (_ROOM_FILENAME, 30 * 24 * 60 * 60),
    "room_audio_attestation_packet": (
        "memorial_room_audio_attestation_packet.generated.json",
        7 * 24 * 60 * 60,
    ),
}
_EVIDENCE_CONTRACTS = {
    "stt_candidate": (
        "ea.memorial_stt_fixture_candidate",
        "scripts/materialize_memorial_stt_fixture_candidate.py",
        "pass",
    ),
    "stt_captured_benchmark": (
        "ea.memorial_stt_provider_benchmark",
        "scripts/benchmark_memorial_stt_providers.py",
        "pass",
    ),
    "stt_benchmark": (
        "ea.memorial_stt_provider_benchmark",
        "scripts/benchmark_memorial_stt_providers.py",
        "pass",
    ),
    "captured_candidate_diagnostic": (
        "ea.memorial_stt_captured_candidate_diagnostic",
        "scripts/materialize_memorial_stt_captured_candidate_diagnostic.py",
        "pass",
    ),
    "voice_roundtrip": (
        "ea.memorial_voice_roundtrip_exit_gate",
        "scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "pass",
    ),
    "realtime_browser": (
        "ea.memorial_realtime_browser_exit_gate",
        "scripts/measure_memorial_live_browser.py",
        "pass",
    ),
    "room_audio": (
        "ea.memorial_room_audio_public_origin",
        "scripts/materialize_memorial_room_audio_receipt.py",
        "pass",
    ),
    "room_audio_attestation_packet": (
        "ea.memorial_room_audio_attestation_packet",
        "scripts/materialize_memorial_room_audio_attestation_packet.py",
        "ready",
    ),
}
_READINESS_EVIDENCE_ROW_KEYS = {
    "contract_name",
    "contract_valid",
    "fresh",
    "generated_at",
    "max_age_seconds",
    "present",
    "raw_credentials_exposed",
    "raw_private_context_exposed",
    "raw_receipt_payload_exposed",
    "raw_transcript_fields_exposed",
    "receipt_name",
    "receipt_sha256",
    "source_git_head_matches_current",
    "source_git_head_present",
    "source_state_fingerprint_present",
    "source_state_matches_current",
    "status",
}
_ROOM_CHECK_IDS = {
    "actual_device_checked",
    "actual_speaker_checked",
    "answer_text_fallback_visible",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "interruption_behavior_confirmed",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "retry_path_confirmed",
}
_ROOM_RECEIPT_KEYS = {
    "base_url",
    "check_requirements",
    "checks",
    "contract_name",
    "device_label",
    "dirty_worktree",
    "failed_codes",
    "generated_at",
    "generated_by",
    "gold_claim_allowed",
    "head_semantics",
    "manual_attestation",
    "notes",
    "proof_type",
    "require_public_origin",
    "reviewer",
    "room_label",
    "runtime_source_revision",
    "runtime_source_revision_required",
    "slug",
    "source_git_head",
    "source_state_fingerprint",
    "source_state_fingerprint_semantics",
    "source_tree_fingerprint",
    "speaker_label",
    "status",
}
_PACKET_KEYS = {
    "contract_name",
    "conversation_prerequisites_pass",
    "deployment_id",
    "deployment_id_source",
    "deployment_revision",
    "effective_expires_at",
    "enabled_project_modes",
    "generated_at",
    "generated_by",
    "head_semantics",
    "memorial_slug",
    "project_mode",
    "public_origin",
    "raw_input_sha256",
    "readiness_evidence_raw_sha256",
    "release_context_verified",
    "room_audio_attestation_verified",
    "source_git_head",
    "source_state_fingerprint",
    "source_state_fingerprint_semantics",
    "status",
    "voice_authority",
}
_RAW_INPUT_KEYS = {
    "readiness_receipt",
    "room_audio_receipt",
    "tts_voice_consent",
    "release_manifest",
    "release_authority_status",
    "project_modes",
}
_VOICE_AUTHORITY = {
    "authority_source": "private_tts_voice_consent",
    "consent_status": "approved",
    "realtime_scope": True,
    "revoked": False,
    "source_assets_reviewed": True,
    "synthetic_voice_clone_disclosure": True,
    "tts_mode": "unmixr_clone",
    "tts_plugin": "unmixr_clone",
}
_MANFRED_VOICE_ID = "${UNMIXR_VOICE_ID}"
_MANFRED_VOICE_LABEL = "Manfred Hoza · Unmixr-Klon"
_SOURCE_FINGERPRINT_SEMANTICS = (
    "worktree_source_files_sha256_excluding_generated_only_paths"
)
_DIR_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    path: Path
    raw: bytes
    payload: dict[str, Any]
    sha256: str
    identity: tuple[int, ...]


class _ReleaseBlocked(ValueError):
    pass


def _blocked(reason: str, *, receipt_status: str = "") -> dict[str, object]:
    return {
        "allowed": False,
        "status": "blocked",
        "reason": reason,
        "receipt_status": receipt_status,
    }


def _fail(reason: str) -> None:
    raise _ReleaseBlocked(reason)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _absolute_parts(path: Path, *, label: str) -> tuple[str, ...]:
    raw = os.fspath(path)
    if (
        not path.is_absolute()
        or not raw.startswith("/")
        or raw.startswith("//")
        or "\x00" in raw
        or raw != os.path.normpath(raw)
    ):
        _fail(f"{label}_path_invalid")
    parts = tuple(part for part in raw.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        _fail(f"{label}_path_invalid")
    return parts


def _open_parent(path: Path, *, label: str) -> tuple[int, str]:
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0):
        _fail(f"{label}_nofollow_unavailable")
    parts = _absolute_parts(path, label=label)
    try:
        descriptor = os.open("/", _DIR_FLAGS)
    except OSError:
        _fail(f"{label}_path_unavailable")
    try:
        for component in parts[:-1]:
            try:
                next_descriptor = os.open(
                    component,
                    _DIR_FLAGS,
                    dir_fd=descriptor,
                )
            except OSError:
                _fail(f"{label}_path_unsafe")
            os.close(descriptor)
            descriptor = next_descriptor
        parent = os.fstat(descriptor)
        mode = stat.S_IMODE(parent.st_mode)
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid not in {0, os.geteuid()}
            or mode & 0o222
        ):
            _fail(f"{label}_parent_untrusted")
        return descriptor, parts[-1]
    except Exception:
        os.close(descriptor)
        raise


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("release_receipt_duplicate_field")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    _fail(f"release_receipt_nonfinite:{value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _fail("release_receipt_nonfinite")
    return parsed


def _snapshot(path: str | Path, *, label: str) -> _Snapshot:
    target = Path(path)
    parent_fd, name = _open_parent(target, label=label)
    file_fd = -1
    try:
        parent_before = _identity(os.fstat(parent_fd))
        try:
            path_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            file_fd = os.open(name, _FILE_FLAGS, dir_fd=parent_fd)
        except OSError:
            _fail(f"{label}_missing_or_unsafe")
        before = os.fstat(file_fd)
        mode = stat.S_IMODE(before.st_mode)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, os.geteuid()}
            or mode & 0o222
            or not 1 < before.st_size <= MAX_JSON_BYTES
            or _identity(path_before) != _identity(before)
        ):
            _fail(f"{label}_untrusted")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(file_fd, min(remaining, 64 * 1024))
            if not chunk:
                _fail(f"{label}_short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            _fail(f"{label}_grew_during_read")
        after = os.fstat(file_fd)
        path_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _identity(before) != _identity(after)
            or _identity(after) != _identity(path_after)
            or parent_before != _identity(os.fstat(parent_fd))
        ):
            _fail(f"{label}_changed_during_read")
        raw = b"".join(chunks)
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_pairs,
                parse_constant=_reject_nonfinite,
                parse_float=_parse_finite_float,
            )
        except _ReleaseBlocked:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            _fail(f"{label}_invalid_json")
        if not isinstance(payload, dict):
            _fail(f"{label}_invalid_shape")
        return _Snapshot(
            path=target,
            raw=raw,
            payload=dict(payload),
            sha256=hashlib.sha256(raw).hexdigest(),
            identity=_identity(after),
        )
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(parent_fd)


def _assert_unchanged(snapshots: list[_Snapshot]) -> None:
    for previous in snapshots:
        current = _snapshot(previous.path, label="release_input_recheck")
        if (
            current.identity != previous.identity
            or current.sha256 != previous.sha256
            or current.raw != previous.raw
        ):
            _fail("release_input_changed_before_decision")


def _parse_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError):
        _fail(f"{label}_invalid")
    if parsed.tzinfo is None:
        _fail(f"{label}_invalid")
    return parsed.astimezone(UTC)


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _source_revision(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _deployment_id(value: object) -> bool:
    if not isinstance(value, str) or not 8 <= len(value) <= 160:
        return False
    lowered = value.lower()
    return (
        value == value.strip()
        and "local" not in lowered
        and "fallback" not in lowered
        and all(
            character
            in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for character in value
        )
    )


def _public_origin(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        _fail("release_public_origin_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _fail("release_public_origin_invalid")
    hostname = str(parsed.hostname or "").lower()
    labels = hostname.split(".")
    reserved_suffixes = (
        ".example",
        ".example.com",
        ".example.net",
        ".example.org",
        ".home.arpa",
        ".internal",
        ".invalid",
        ".lan",
        ".local",
        ".localhost",
        ".test",
    )
    if (
        parsed.scheme != "https"
        or not hostname
        or hostname.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
        or hostname
        in {
            "example.com",
            "example.net",
            "example.org",
            "localhost",
            "localhost.localdomain",
        }
        or hostname.endswith(reserved_suffixes)
        or len(labels) < 2
        or any(
            not label
            or label.startswith("-")
            or label.endswith("-")
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                for character in label
            )
            for label in labels
        )
    ):
        _fail("release_public_origin_invalid")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        _fail("release_public_origin_invalid")
    canonical = f"https://{hostname}"
    if value != canonical or canonical not in _MEMORIAL_PUBLIC_ORIGINS:
        _fail("release_public_origin_not_canonical")
    return canonical


def _bool_env(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _exact_memorial_runtime_topology() -> bool:
    """Require the literal deploy-lane topology, without normalization."""

    return bool(
        os.getenv("EA_DEPLOY_PRIMARY_MODE") == "MEMORIAL"
        and os.getenv("EA_DEPLOY_ENABLED_MODES") == "MEMORIAL"
    )


def _default_input_paths(receipt_path: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    bundle_root = receipt_path.parent
    private_root = Path(str(os.getenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR") or ""))
    inputs = {
        "readiness_receipt": bundle_root / _READINESS_FILENAME,
        "room_audio_receipt": bundle_root / _ROOM_FILENAME,
        "tts_voice_consent": private_root / "manfred" / "tts_voice.json",
        "release_manifest": Path(str(os.getenv("EA_RELEASE_MANIFEST_PATH") or "")),
        "release_authority_status": Path(
            str(os.getenv("EA_RELEASE_AUTHORITY_STATUS_PATH") or "")
        ),
        "project_modes": Path(str(os.getenv("EA_PROJECT_MODES_MANIFEST_PATH") or "")),
    }
    evidence = {
        key: bundle_root / filename for key, (filename, _max_age) in _EVIDENCE_FILES.items()
    }
    return inputs, evidence


def _validate_voice(payload: Mapping[str, Any]) -> None:
    consent = payload.get("voice_consent")
    if (
        payload.get("voice_profile_id") != _MANFRED_VOICE_ID
        or payload.get("tts_plugin_voice_id") != _MANFRED_VOICE_ID
        or payload.get("voice_label") != _MANFRED_VOICE_LABEL
        or payload.get("lang") != "de-AT"
        or payload.get("tts_plugin") != "unmixr_clone"
        or payload.get("tts_mode") != "unmixr_clone"
        or payload.get("synthetic_voice_clone_of_memorial_person") is not True
        or payload.get("consent_basis") != "owner_consented_voice_clone"
        or not isinstance(consent, dict)
        or consent.get("status") != "approved"
        or consent.get("revoked") is not False
        or consent.get("source_assets_reviewed") is not True
        or consent.get("scope")
        != ["clone", "profile_build", "synthesize", "conversation_turn", "realtime"]
    ):
        _fail("release_voice_authority_invalid")


def _strict_nonnegative_int(value: object) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _validate_readiness_evidence_row(
    *,
    key: str,
    row: Mapping[str, Any],
    evidence: _Snapshot,
    expected_max_age: int,
) -> None:
    filename, _ = _EVIDENCE_FILES[key]
    contract_name, _generated_by, expected_status = _EVIDENCE_CONTRACTS[key]
    if (
        set(row) != _READINESS_EVIDENCE_ROW_KEYS
        or row.get("receipt_name") != filename
        or row.get("present") is not True
        or row.get("contract_name") != contract_name
        or row.get("contract_valid") is not True
        or row.get("status") != expected_status
        or row.get("generated_at") != evidence.payload.get("generated_at")
        or row.get("max_age_seconds") != expected_max_age
        or row.get("fresh") is not True
        or row.get("receipt_sha256") != evidence.sha256
        or row.get("source_git_head_present") is not True
        or row.get("source_git_head_matches_current") is not True
        or row.get("source_state_fingerprint_present") is not True
        or row.get("source_state_matches_current") is not True
        or row.get("raw_private_context_exposed") is not False
        or row.get("raw_transcript_fields_exposed") is not False
        or row.get("raw_credentials_exposed") is not False
        or row.get("raw_receipt_payload_exposed") is not False
    ):
        _fail(f"release_readiness_evidence_invalid:{key}")


def _validate_evidence_receipt(
    *,
    key: str,
    payload: Mapping[str, Any],
    generated_at: datetime,
    expected_source_revision: str,
    expected_source_fingerprint: str,
    expected_public_origin: str,
) -> None:
    contract_name, generated_by, expected_status = _EVIDENCE_CONTRACTS[key]
    if (
        payload.get("contract_name") != contract_name
        or payload.get("generated_by") != generated_by
        or payload.get("status") != expected_status
        or payload.get("head_semantics") != "source_state"
        or payload.get("source_git_head") != expected_source_revision
        or payload.get("source_state_fingerprint")
        != expected_source_fingerprint
        or payload.get("source_state_fingerprint_semantics")
        != _SOURCE_FINGERPRINT_SEMANTICS
    ):
        _fail(f"release_evidence_contract_invalid:{key}")

    if key == "stt_candidate":
        if (
            payload.get("contract_version") != 3
            or payload.get("candidate_scope")
            != "audio_quality_provenance_and_bound_ground_truth"
            or payload.get("failed_codes") != []
            or payload.get("privacy_mode") != "redacted"
            or payload.get("text_mode") != "redacted"
            or payload.get("raw_text_fields") is not False
        ):
            _fail(f"release_evidence_status_invalid:{key}")
        return

    if key in {"stt_captured_benchmark", "stt_benchmark"}:
        scoring = payload.get("scoring")
        if (
            payload.get("fixture_quality_status") != "pass"
            or payload.get("fixture_quality_failed_codes") != []
            or not isinstance(scoring, dict)
            or scoring.get("raw_provider_transcript_scored") is not True
            or scoring.get("semantic_repair_applied") is not False
            or scoring.get("text_mode") != "redacted"
            or scoring.get("raw_transcript_fields") is not False
            or scoring.get("redacted_text_fields") is not True
        ):
            _fail(f"release_evidence_status_invalid:{key}")
        return

    if key == "captured_candidate_diagnostic":
        if (
            payload.get("contract_version") != 2
            or payload.get("diagnostic_status") != "ready"
            or payload.get("promotion_allowed") is not True
            or payload.get("may_update_fixture_manifest") is not True
            or payload.get("issues") != []
            or _strict_nonnegative_int(payload.get("captured_row_count")) != 2
        ):
            _fail(f"release_evidence_status_invalid:{key}")
        return

    if key == "voice_roundtrip":
        if (
            payload.get("slug") != "manfred"
            or payload.get("base_url") != expected_public_origin
            or payload.get("require_public_origin") is not True
            or payload.get("dirty_worktree") is not False
            or payload.get("gold_claim_allowed") is not True
            or payload.get("failed_codes") != []
        ):
            _fail(f"release_evidence_status_invalid:{key}")
        return

    if key == "realtime_browser":
        if (
            payload.get("slug") != "manfred"
            or payload.get("base_url") != expected_public_origin
            or payload.get("require_public_origin") is not True
            or payload.get("dirty_worktree") is not False
            or payload.get("gold_claim_allowed") is not True
            or payload.get("failed_codes") != []
            or payload.get("audio_ready_for_ui") is not True
            or (_strict_nonnegative_int(payload.get("ui_audio_play_calls")) or 0)
            < 1
            or (_strict_nonnegative_int(payload.get("ui_audio_play_ended")) or 0)
            < 1
        ):
            _fail(f"release_evidence_status_invalid:{key}")
        return

    if key == "room_audio":
        checks = payload.get("checks")
        requirements = payload.get("check_requirements")
        attestation = payload.get("manual_attestation")
        if (
            set(payload) != _ROOM_RECEIPT_KEYS
            or payload.get("slug") != "manfred"
            or payload.get("base_url") != expected_public_origin
            or payload.get("proof_type") != "manual_room_attestation"
            or payload.get("require_public_origin") is not True
            or payload.get("runtime_source_revision_required") is not True
            or payload.get("runtime_source_revision") != expected_source_revision
            or payload.get("dirty_worktree") is not False
            or payload.get("gold_claim_allowed") is not True
            or payload.get("failed_codes") != []
            or not _sha256(payload.get("source_tree_fingerprint"))
            or not isinstance(checks, dict)
            or set(checks) != _ROOM_CHECK_IDS
            or any(value is not True for value in checks.values())
            or not isinstance(requirements, dict)
            or set(requirements) != _ROOM_CHECK_IDS
            or any(
                not isinstance(value, str) or not value.strip()
                for value in requirements.values()
            )
            or any(
                not isinstance(payload.get(field), str)
                or not str(payload.get(field)).strip()
                for field in (
                    "reviewer",
                    "device_label",
                    "speaker_label",
                    "room_label",
                    "notes",
                )
            )
            or not isinstance(attestation, dict)
            or set(attestation)
            != {"attestation_id", "signed_at", "source", "ci_must_not_auto_assert"}
            or not str(attestation.get("attestation_id") or "").strip()
            or attestation.get("source") != "operator_room_review"
            or attestation.get("ci_must_not_auto_assert") is not True
        ):
            _fail(f"release_evidence_status_invalid:{key}")
        signed_at = _parse_timestamp(
            attestation.get("signed_at"),
            label="release_room_attestation_signed_at",
        )
        if abs(signed_at - generated_at).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
            _fail(f"release_evidence_status_invalid:{key}")
        return

    if key == "room_audio_attestation_packet":
        required_checks = payload.get("required_checks")
        required_ids = [
            str(item.get("id") or "")
            for item in required_checks
            if isinstance(item, dict)
        ] if isinstance(required_checks, list) else []
        if (
            payload.get("slug") != "manfred"
            or payload.get("manual_only") is not True
            or payload.get("ci_must_not_auto_assert") is not True
            or payload.get("proof_target")
            != ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
            or payload.get("operator_command")
            != "make materialize-memorial-room-audio-gold-clean"
            or len(required_ids) != len(_ROOM_CHECK_IDS)
            or set(required_ids) != _ROOM_CHECK_IDS
        ):
            _fail(f"release_evidence_status_invalid:{key}")
        return

    _fail(f"release_evidence_contract_invalid:{key}")


def _validate_runtime_context(
    *,
    packet: Mapping[str, Any],
    manifest: Mapping[str, Any],
    authority: Mapping[str, Any],
    expected_source_revision: str,
    expected_deployment_id: str,
    expected_public_origin: str,
) -> None:
    gate = authority.get("gate")
    gate = gate if isinstance(gate, dict) else {}
    if (
        manifest.get("contract_name") != "ea.release_manifest.v1"
        or manifest.get("commit_sha") != expected_source_revision
        or manifest.get("deploy_context_commit_sha") != expected_source_revision
        or manifest.get("deployment_id") != expected_deployment_id
        or manifest.get("deployment_id_source") != packet.get("deployment_id_source")
        or not isinstance(manifest.get("deployment_id_source"), str)
        or not str(manifest.get("deployment_id_source")).strip()
        or "fallback" in str(manifest.get("deployment_id_source")).lower()
        or "local" in str(manifest.get("deployment_id_source")).lower()
        or manifest.get("public_origin") != expected_public_origin
        or manifest.get("project_mode") != "MEMORIAL"
        or manifest.get("enabled_project_modes") != ["MEMORIAL"]
        or manifest.get("dirty_worktree") is not False
        or manifest.get("source_worktree_dirty") is not False
        or manifest.get("source_dirty_count") != 0
        or manifest.get("source_dirty_files") != []
        or authority.get("contract_name") != "ea.release_authority_status.v1"
        or authority.get("state") != "clear"
        or authority.get("authority_posture") != "authoritative_runtime"
        or authority.get("issues") != []
        or authority.get("commit_sha") != expected_source_revision
        or authority.get("deployment_id") != expected_deployment_id
        or not isinstance(gate, dict)
        or gate.get("status") != "pass"
        or gate.get("issues") != []
        or gate.get("commit_sha") != expected_source_revision
        or gate.get("deployment_id") != expected_deployment_id
    ):
        _fail("release_runtime_context_invalid")


def evaluate_memorial_voice_release(
    *,
    slug: str,
    receipt_path: str | Path,
    now: float | None = None,
    max_age_seconds: float = MEMORIAL_VOICE_RELEASE_MAX_AGE_SECONDS,
    activation_enabled: bool | None = None,
    input_paths: Mapping[str, str | Path] | None = None,
    readiness_evidence_paths: Mapping[str, str | Path] | None = None,
    expected_source_revision: str | None = None,
    expected_deployment_id: str | None = None,
    expected_public_origin: str | None = None,
) -> dict[str, object]:
    """Return a voice-access decision, never a release-authority decision."""

    if not isinstance(slug, str) or slug.strip().lower() != "manfred":
        return _blocked("release_receipt_not_configured")
    enabled = (
        _bool_env("EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION")
        if activation_enabled is None
        else activation_enabled is True
    )
    if not enabled:
        return _blocked("release_activation_disabled")
    if not _exact_memorial_runtime_topology():
        return _blocked("release_runtime_topology_invalid")
    try:
        configured_max_age = float(max_age_seconds)
    except (TypeError, ValueError, OverflowError):
        return _blocked("release_max_age_invalid")
    if not math.isfinite(configured_max_age) or configured_max_age <= 0:
        return _blocked("release_max_age_invalid")

    receipt = Path(receipt_path)
    default_inputs, default_evidence = _default_input_paths(receipt)
    configured_inputs = {
        key: Path(value)
        for key, value in (input_paths or default_inputs).items()
    }
    configured_evidence = {
        key: Path(value)
        for key, value in (readiness_evidence_paths or default_evidence).items()
    }
    if set(configured_inputs) != _RAW_INPUT_KEYS or set(configured_evidence) != set(
        _EVIDENCE_FILES
    ):
        return _blocked("release_input_paths_incomplete")

    try:
        packet_snapshot = _snapshot(receipt, label="release_receipt")
        snapshots = [packet_snapshot]
        inputs = {
            key: _snapshot(path, label=f"release_input_{key}")
            for key, path in configured_inputs.items()
        }
        evidence = {
            key: _snapshot(path, label=f"release_evidence_{key}")
            for key, path in configured_evidence.items()
        }
        snapshots.extend(inputs.values())
        snapshots.extend(evidence.values())
        packet = packet_snapshot.payload
        receipt_status = str(packet.get("status") or "")
        if set(packet) != _PACKET_KEYS:
            _fail("release_receipt_schema_invalid")
        if (
            packet.get("contract_name")
            != MANFRED_CONVERSATION_PREREQUISITES_CONTRACT
            or packet.get("generated_by")
            != MANFRED_CONVERSATION_PREREQUISITES_GENERATOR
            or receipt_status != "pass"
            or packet.get("memorial_slug") != "manfred"
            or packet.get("conversation_prerequisites_pass") is not True
            or packet.get("release_context_verified") is not True
            or packet.get("room_audio_attestation_verified") is not True
            or packet.get("voice_authority") != _VOICE_AUTHORITY
            or packet.get("project_mode") != "MEMORIAL"
            or packet.get("enabled_project_modes") != ["MEMORIAL"]
            or packet.get("head_semantics") != "source_state"
            or packet.get("source_state_fingerprint_semantics")
            != _SOURCE_FINGERPRINT_SEMANTICS
            or not _sha256(packet.get("source_state_fingerprint"))
        ):
            _fail("release_prerequisites_invalid")

        source_revision = (
            str(os.getenv("EA_SOURCE_REVISION") or "")
            if expected_source_revision is None
            else expected_source_revision
        )
        deployment_id = (
            str(os.getenv("EA_MEMORIAL_DEPLOYMENT_ID") or "")
            if expected_deployment_id is None
            else expected_deployment_id
        )
        public_origin = (
            str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "")
            if expected_public_origin is None
            else expected_public_origin
        )
        if not _source_revision(source_revision):
            _fail("release_runtime_source_revision_invalid")
        if not _deployment_id(deployment_id):
            _fail("release_runtime_deployment_id_invalid")
        canonical_origin = _public_origin(public_origin)
        if (
            packet.get("source_git_head") != source_revision
            or packet.get("deployment_revision") != source_revision
            or packet.get("deployment_id") != deployment_id
            or packet.get("public_origin") != canonical_origin
        ):
            _fail("release_runtime_binding_mismatch")

        raw_hashes = packet.get("raw_input_sha256")
        evidence_hashes = packet.get("readiness_evidence_raw_sha256")
        if (
            not isinstance(raw_hashes, dict)
            or set(raw_hashes) != _RAW_INPUT_KEYS
            or not isinstance(evidence_hashes, dict)
            or set(evidence_hashes) != set(_EVIDENCE_FILES)
            or any(raw_hashes[key] != inputs[key].sha256 for key in _RAW_INPUT_KEYS)
            or any(
                evidence_hashes[key] != evidence[key].sha256 for key in _EVIDENCE_FILES
            )
        ):
            _fail("release_raw_input_hash_mismatch")
        if (
            inputs["room_audio_receipt"].raw != evidence["room_audio"].raw
            or inputs["room_audio_receipt"].sha256
            != evidence["room_audio"].sha256
        ):
            _fail("release_room_readiness_binding_mismatch")

        checked_at = datetime.fromtimestamp(
            time.time() if now is None else float(now), tz=UTC
        )
        generated_at = _parse_timestamp(
            packet.get("generated_at"), label="release_generated_at"
        )
        effective_expiry = _parse_timestamp(
            packet.get("effective_expires_at"), label="release_effective_expires_at"
        )
        if (
            (generated_at - checked_at).total_seconds() > MAX_FUTURE_SKEW_SECONDS
            or generated_at >= effective_expiry
            or (effective_expiry - generated_at).total_seconds()
            > min(configured_max_age, MEMORIAL_VOICE_RELEASE_MAX_AGE_SECONDS)
        ):
            _fail("release_receipt_timestamp_invalid")
        if checked_at >= effective_expiry:
            _fail("release_receipt_stale")
        if (
            effective_expiry - checked_at
        ).total_seconds() > min(
            configured_max_age,
            MEMORIAL_VOICE_RELEASE_MAX_AGE_SECONDS,
        ) + MAX_FUTURE_SKEW_SECONDS:
            _fail("release_effective_expiry_invalid")

        readiness = inputs["readiness_receipt"].payload
        input_evidence = readiness.get("input_evidence")
        if (
            readiness.get("contract_name")
            != "ea.manfred_realtime_conversation_readiness.v1"
            or readiness.get("generated_by")
            != "ea/scripts/materialize_manfred_realtime_conversation_readiness.py"
            or readiness.get("memorial_slug") != "manfred"
            or readiness.get("evidence_source") != "receipt_aggregation"
            or readiness.get("status")
            != "ready_for_realtime_conversation_review"
            or readiness.get("ready_for_realtime_conversation_review") is not True
            or readiness.get("blocked_checks") != []
            or readiness.get("head_semantics") != "source_state"
            or readiness.get("source_git_head") != source_revision
            or readiness.get("source_state_fingerprint")
            != packet.get("source_state_fingerprint")
            or readiness.get("source_state_fingerprint_semantics")
            != _SOURCE_FINGERPRINT_SEMANTICS
            or not isinstance(input_evidence, dict)
            or set(input_evidence) != set(_EVIDENCE_FILES)
        ):
            _fail("release_readiness_invalid")
        readiness_generated_at = _parse_timestamp(
            readiness.get("generated_at"), label="release_readiness_generated_at"
        )
        if (
            readiness_generated_at - checked_at
        ).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
            _fail("release_readiness_generated_at_future")
        if (
            readiness_generated_at - generated_at
        ).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
            _fail("release_readiness_generated_after_packet")
        calculated_expiry = readiness_generated_at + timedelta(
            seconds=MEMORIAL_VOICE_RELEASE_MAX_AGE_SECONDS
        )
        for key, (_filename, expected_max_age) in _EVIDENCE_FILES.items():
            row = input_evidence.get(key)
            if not isinstance(row, dict):
                _fail(f"release_readiness_evidence_invalid:{key}")
            _validate_readiness_evidence_row(
                key=key,
                row=row,
                evidence=evidence[key],
                expected_max_age=expected_max_age,
            )
            evidence_generated_at = _parse_timestamp(
                row.get("generated_at"),
                label=f"release_readiness_evidence_generated_at:{key}",
            )
            if (
                evidence_generated_at - checked_at
            ).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
                _fail(f"release_evidence_generated_at_future:{key}")
            if (
                evidence_generated_at - generated_at
            ).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
                _fail(f"release_evidence_generated_after_packet:{key}")
            _validate_evidence_receipt(
                key=key,
                payload=evidence[key].payload,
                generated_at=evidence_generated_at,
                expected_source_revision=source_revision,
                expected_source_fingerprint=str(
                    packet.get("source_state_fingerprint") or ""
                ),
                expected_public_origin=canonical_origin,
            )
            expires = evidence_generated_at + timedelta(seconds=expected_max_age)
            if expires <= checked_at:
                _fail(f"release_evidence_stale:{key}")
            calculated_expiry = min(calculated_expiry, expires)
        if effective_expiry != calculated_expiry:
            _fail("release_effective_expiry_mismatch")

        _validate_voice(inputs["tts_voice_consent"].payload)
        _validate_runtime_context(
            packet=packet,
            manifest=inputs["release_manifest"].payload,
            authority=inputs["release_authority_status"].payload,
            expected_source_revision=source_revision,
            expected_deployment_id=deployment_id,
            expected_public_origin=canonical_origin,
        )
        project_modes = inputs["project_modes"].payload
        declared_modes = {
            str(row.get("key") or "")
            for row in list(project_modes.get("modes") or [])
            if isinstance(row, dict)
        }
        if (
            project_modes.get("contract_name") != "ea.project_modes"
            or project_modes.get("source_git_head") not in {None, source_revision}
            or "MEMORIAL" not in declared_modes
        ):
            _fail("release_project_modes_invalid")
        _assert_unchanged(snapshots)
    except _ReleaseBlocked as exc:
        return _blocked(str(exc))
    except (OSError, ValueError, TypeError, OverflowError):
        return _blocked("release_receipt_invalid")

    return {
        "allowed": True,
        "status": "prerequisites_active",
        "reason": "",
        "receipt_status": "pass",
    }
