from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint
from scripts.verify_memorial_stt_captured_candidate_diagnostic import verify_diagnostic


REQUIRED_ROOM_CHECK_IDS = [
    "actual_device_checked",
    "actual_speaker_checked",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "answer_text_fallback_visible",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "interruption_behavior_confirmed",
    "retry_path_confirmed",
]
ROOM_AUDIO_RECEIPT_CONTRACT = "ea.memorial_room_audio_public_origin"
ROOM_AUDIO_RECEIPT_CONTRACT_VERSION = 2
ROOM_AUDIO_RECEIPT_GENERATED_BY = (
    "scripts/materialize_memorial_room_audio_receipt.py"
)
ROOM_AUDIO_RECEIPT_PROOF_TYPE = "manual_room_attestation"
ROOM_AUDIO_RECEIPT_FIELDS = {
    "access_mode",
    "base_url",
    "check_requirements",
    "checks",
    "contract_name",
    "contract_version",
    "dirty_worktree",
    "evidence_scope",
    "failed_codes",
    "generated_at",
    "generated_by",
    "gold_claim_allowed",
    "head_semantics",
    "manual_attestation",
    "notes",
    "private_review_evidence_allowed",
    "proof_type",
    "require_public_origin",
    "review_session_authenticated",
    "review_session_binding",
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
    "device_label",
}
ROOM_AUDIO_MANUAL_ATTESTATION_FIELDS = {
    "attestation_id",
    "ci_must_not_auto_assert",
    "signed_at",
    "source",
}
ROOM_AUDIO_GENERIC_LABELS = {
    "reviewer": {
        "qa-room-reviewer",
        "qa room reviewer",
        "reviewer",
        "test reviewer",
    },
    "device_label": {
        "laptop speaker test",
        "presentation laptop",
        "laptop",
        "test device",
    },
    "speaker_label": {
        "room speaker",
        "speaker",
        "laptop speaker",
        "test speaker",
    },
    "room_label": {
        "office",
        "room",
        "test room",
    },
}

REQUIRED_LIVE_PROOF_AFTER_READINESS = [
    "operator acceptance that this behaves like an ongoing spoken conversation",
    "real room audio acceptance with actual device and speaker",
]

DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "manfred_realtime_conversation_readiness.generated.json"
DEFAULT_EVIDENCE_ROOT = DEFAULT_RECEIPT.parent
EVIDENCE_RECEIPTS = {
    "stt_candidate": (
        "memorial_stt_fixture_candidate.generated.json",
        "ea.memorial_stt_fixture_candidate",
    ),
    "stt_captured_benchmark": (
        "memorial_stt_provider_benchmark_captured_candidate.generated.json",
        "ea.memorial_stt_provider_benchmark",
    ),
    "stt_benchmark": (
        "memorial_stt_provider_benchmark.generated.json",
        "ea.memorial_stt_provider_benchmark",
    ),
    "captured_candidate_diagnostic": (
        "memorial_stt_captured_candidate_diagnostic.generated.json",
        "ea.memorial_stt_captured_candidate_diagnostic",
    ),
    "voice_roundtrip": (
        "memorial_voice_roundtrip_public_origin.generated.json",
        "ea.memorial_voice_roundtrip_exit_gate",
    ),
    "realtime_browser": (
        "memorial_realtime_browser_public_origin.generated.json",
        "ea.memorial_realtime_browser_exit_gate",
    ),
    "room_audio": (
        "memorial_room_audio_public_origin.generated.json",
        "ea.memorial_room_audio_public_origin",
    ),
    "room_audio_attestation_packet": (
        "memorial_room_audio_attestation_packet.generated.json",
        "ea.memorial_room_audio_attestation_packet",
    ),
}
EVIDENCE_MAX_AGE_SECONDS = {
    "stt_candidate": 72 * 60 * 60,
    "stt_captured_benchmark": 72 * 60 * 60,
    "stt_benchmark": 72 * 60 * 60,
    "captured_candidate_diagnostic": 72 * 60 * 60,
    "voice_roundtrip": 72 * 60 * 60,
    "realtime_browser": 24 * 60 * 60,
    "room_audio": 30 * 24 * 60 * 60,
    "room_audio_attestation_packet": 7 * 24 * 60 * 60,
}
READINESS_MAX_AGE_SECONDS = 24 * 60 * 60
PRIVATE_REVIEW_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
PRIVATE_REVIEW_EVIDENCE_SCOPE = "private_authenticated_review"
ANONYMOUS_PUBLIC_EVIDENCE_SCOPE = "anonymous_public"
PRIVATE_REVIEW_BROWSER_LAUNCH_SCOPE = "real_public_private_review_microphone"
MANFRED_VOICE_GOLD_PATH = "/admin/memorials/manfred/gold"
MANFRED_VOICE_GOLD_LABEL = "Open voice gold"
MANFRED_PROOF_PATH = "/memorials/manfred/voice-config"
MANFRED_PROOF_LABEL = "Spoken conversation proof"
MANFRED_REVIEW_LABEL = "Review spoken conversation"
ACTION_METHOD = "get"
MANFRED_OPERATOR_ACTION_KEY = "manfred_stt_tts_realtime_conversation"
STT_REMEDIATION_ACTION = "review_private_ground_truth_and_run_bound_stt_benchmark"
AUTOMATED_VOICE_REMEDIATION_ACTION = "repair_automated_voice_browser_tts_prerequisites"
ROOM_ATTESTATION_REMEDIATION_ACTION = "regenerate_current_safe_room_attestation_packet"
BENCHMARK_GENERATED_BY = "scripts/benchmark_memorial_stt_providers.py"
CANDIDATE_GENERATED_BY = "scripts/materialize_memorial_stt_fixture_candidate.py"
CANDIDATE_CONTRACT_VERSION = 3
DIAGNOSTIC_GENERATED_BY = "scripts/materialize_memorial_stt_captured_candidate_diagnostic.py"
DIAGNOSTIC_CONTRACT_VERSION = 2
CANDIDATE_BINDING_CONTRACT = "ea.memorial_stt_fixture_candidate_binding.v2"
GROUND_TRUTH_REVIEW_BINDING_CONTRACT = "ea.memorial_stt_operator_ground_truth_review_binding.v2"
DIAGNOSTIC_INPUT_BINDING_CONTRACT = (
    "ea.memorial_stt_captured_candidate_diagnostic_input_binding.v1"
)
TRANSFORMATION_RECEIPT_CONTRACT = "ea.memorial_stt_audio_transformation_receipt.v1"
CANONICALIZATION = "json_utf8_sorted_keys_compact_v1"
FINAL_CANDIDATE_SCOPE = "audio_quality_provenance_and_bound_ground_truth"
FULL_RUNTIME_TRANSCRIBER = "cartesia/ink-whisper+enhanced_wav"
FULL_RUNTIME_TRANSCRIBER_RECEIPT = {
    "family": "cartesia",
    "identifier_sha256": hashlib.sha256(
        FULL_RUNTIME_TRANSCRIBER.encode("utf-8")
    ).hexdigest(),
}
GOVERNED_MIN_TOKEN_F1 = 0.55
GOVERNED_MAX_WER = 0.55
GOVERNED_THRESHOLD_PAIRS = {
    (GOVERNED_MIN_TOKEN_F1, GOVERNED_MAX_WER),
    (0.65, 0.45),
}
PROVIDER_UPLOAD_AUTHORIZATION_KEYS = {"full_runtime", "onemin_sample", "shadow"}
ALLOWED_PROVIDER_STATUSES = {
    "empty",
    "error",
    "fixture_invalid",
    "http_error",
    "known_bad",
    "not_authorized",
    "ok",
    "skipped",
    "success",
    "transcribed",
    "unavailable",
    "unknown",
}
SUCCESSFUL_PROVIDER_STATUSES = {"ok", "success", "transcribed"}
ROOM_PROOF_BLOCKED_CHECKS = {
    "room_audio_receipt_passed",
    "manual_room_checks_confirmed",
}
STT_OR_EVIDENCE_BLOCKED_CHECKS = {
    "current_evidence_aggregation_required",
    "real_captured_stt_fixture_ready",
    "captured_candidate_diagnostic_clean",
}
RAW_TRANSCRIPT_KEYS = {
    "actual_text",
    "expected_text",
    "primary_transcript_text",
    "required_tokens",
    "text",
    "transcript_text",
}
ALLOWED_RAW_CONTROL_KEYS = {
    "candidate_raw_text_fields",
    "public_receipt_must_not_include_full_text",
    "raw_provider_transcript_scored",
    "raw_text_fields",
    "raw_transcript_fields",
    "redacted_text_fields",
}
RAW_CREDENTIAL_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "bearer_token",
    "cookie",
    "cookie_header",
    "cookie_value",
    "password",
    "proxy_authorization",
    "refresh_token",
    "secret",
    "session_token",
    "set_cookie",
}
RAW_CREDENTIAL_STRING_PREFIXES = (
    "authorization:",
    "bearer ",
    "bearer:",
    "cookie:",
    "set-cookie:",
)
ATTESTATION_GENERATED_BY = "scripts/materialize_memorial_room_audio_attestation_packet.py"
MAX_LOCAL_JSON_BYTES = 4 * 1024 * 1024
LOCAL_FILE_READ_CHUNK_BYTES = 64 * 1024


class UnsafeLocalFileError(ValueError):
    """Raised when a local receipt path cannot be used without following unsafe links."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validated_generated_at(value: object) -> str:
    if value in (None, ""):
        return _now()
    normalized = _safe_timestamp(value)
    if not normalized:
        raise ValueError("generated_at_invalid_or_timezone_missing")
    observed = datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    age_seconds = (observed - parsed).total_seconds()
    if age_seconds < -float(MAX_FUTURE_SKEW_SECONDS):
        raise ValueError("generated_at_future")
    if age_seconds > float(READINESS_MAX_AGE_SECONDS):
        raise ValueError("generated_at_stale")
    return normalized


def _open_parent_dirfd(
    path: str | Path,
    *,
    create: bool,
    anchor_fd: int | None = None,
) -> tuple[int, str]:
    target = Path(path)
    target_name = target.name
    if not target_name or target_name in {".", ".."}:
        raise UnsafeLocalFileError("local_target_name_invalid")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise UnsafeLocalFileError("local_nofollow_directory_walk_unavailable")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    if target.is_absolute():
        if target.anchor != os.sep:
            raise UnsafeLocalFileError("local_target_anchor_unsupported")
        parent_parts = target.parent.parts[1:]
        current_fd = os.open(os.sep, directory_flags)
    else:
        parent_parts = target.parent.parts
        current_fd = (
            os.open(".", directory_flags)
            if anchor_fd is None
            else os.dup(anchor_fd)
        )
        try:
            if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
                raise UnsafeLocalFileError("local_anchor_not_directory")
        except Exception:
            os.close(current_fd)
            raise

    try:
        for component in parent_parts:
            if component in {"", "."}:
                continue
            if component == "..":
                raise UnsafeLocalFileError("local_parent_traversal_forbidden")
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                raise UnsafeLocalFileError("local_parent_component_unsafe") from exc
            try:
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    raise UnsafeLocalFileError("local_parent_component_not_directory")
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd, target_name
    except Exception:
        os.close(current_fd)
        raise


def _open_directory_fd(
    path: str | Path,
    *,
    anchor_fd: int | None = None,
) -> int:
    directory_fd, _sentinel_name = _open_parent_dirfd(
        Path(path) / ".manfred-readiness-directory-handle",
        create=False,
        anchor_fd=anchor_fd,
    )
    return directory_fd


def _duplicate_directory_fd(directory_fd: int) -> int:
    duplicated_fd = os.dup(directory_fd)
    try:
        if not stat.S_ISDIR(os.fstat(duplicated_fd).st_mode):
            raise UnsafeLocalFileError("local_evidence_root_not_directory")
    except Exception:
        os.close(duplicated_fd)
        raise
    return duplicated_fd


def _directory_fd_snapshot(directory_fd: int) -> tuple[int, ...]:
    observed = os.fstat(directory_fd)
    if not stat.S_ISDIR(observed.st_mode):
        raise UnsafeLocalFileError("local_evidence_root_not_directory")
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_nlink,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _directory_fd_reference_path(directory_fd: int) -> Path:
    try:
        opened = os.fstat(directory_fd)
    except OSError as exc:
        raise UnsafeLocalFileError("local_directory_fd_reference_unavailable") from exc
    if not stat.S_ISDIR(opened.st_mode):
        raise UnsafeLocalFileError("local_directory_fd_reference_mismatch")
    for descriptor_root in (Path("/proc/self/fd"), Path("/dev/fd")):
        reference = descriptor_root / str(directory_fd)
        try:
            referenced = os.stat(reference)
        except OSError:
            continue
        if referenced.st_dev == opened.st_dev and referenced.st_ino == opened.st_ino:
            return reference
    raise UnsafeLocalFileError("local_directory_fd_reference_unavailable")


def _regular_target_stat(parent_fd: int, target_name: str) -> os.stat_result | None:
    try:
        target_stat = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise UnsafeLocalFileError("local_target_stat_failed") from exc
    if not stat.S_ISREG(target_stat.st_mode):
        raise UnsafeLocalFileError("local_target_not_regular")
    return target_stat


def _target_identity(target_stat: os.stat_result | None) -> tuple[int, int, int] | None:
    if target_stat is None:
        return None
    return (target_stat.st_dev, target_stat.st_ino, stat.S_IFMT(target_stat.st_mode))


def _render_bounded_json(payload: dict[str, Any]) -> bytes:
    try:
        rendered = (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnsafeLocalFileError("local_json_not_finite_or_serializable") from exc
    if len(rendered) > MAX_LOCAL_JSON_BYTES:
        raise UnsafeLocalFileError("local_json_too_large")
    return rendered


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    rendered = _render_bounded_json(payload)
    parent_fd, target_name = _open_parent_dirfd(path, create=True)
    temp_fd = -1
    temp_name = ""
    try:
        initial_identity = _target_identity(_regular_target_stat(parent_fd, target_name))
        open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        open_flags |= getattr(os, "O_CLOEXEC", 0)
        for _attempt in range(32):
            candidate = (
                f".{target_name[:32]}.tmp-{os.getpid()}-{secrets.token_hex(12)}"
            )
            try:
                temp_fd = os.open(
                    candidate,
                    open_flags,
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                continue
            temp_name = candidate
            break
        if temp_fd < 0 or not temp_name:
            raise UnsafeLocalFileError("local_atomic_temp_unavailable")

        view = memoryview(rendered)
        offset = 0
        while offset < len(view):
            written = os.write(temp_fd, view[offset:])
            if written <= 0:
                raise UnsafeLocalFileError("local_atomic_temp_short_write")
            offset += written
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1

        final_identity = _target_identity(_regular_target_stat(parent_fd, target_name))
        if final_identity != initial_identity:
            raise UnsafeLocalFileError("local_target_changed_before_commit")
        os.replace(
            temp_name,
            target_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temp_name = ""
        os.fsync(parent_fd)
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _read_regular_file_snapshot_at(
    parent_fd: int,
    target_name: str,
    *,
    max_bytes: int = MAX_LOCAL_JSON_BYTES,
) -> bytes:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise UnsafeLocalFileError("local_snapshot_limit_invalid")
    if (
        not target_name
        or target_name in {".", ".."}
        or Path(target_name).name != target_name
    ):
        raise UnsafeLocalFileError("local_snapshot_name_invalid")
    file_fd = -1
    try:
        open_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            file_fd = os.open(target_name, open_flags, dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise UnsafeLocalFileError("local_snapshot_open_failed") from exc
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise UnsafeLocalFileError("local_snapshot_not_regular")
        if before.st_size < 0 or before.st_size > max_bytes:
            raise UnsafeLocalFileError("local_snapshot_too_large")

        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(file_fd, min(LOCAL_FILE_READ_CHUNK_BYTES, remaining))
            if not chunk:
                raise UnsafeLocalFileError("local_snapshot_short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            raise UnsafeLocalFileError("local_snapshot_grew_during_read")
        after = os.fstat(file_fd)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_identity != after_identity:
            raise UnsafeLocalFileError("local_snapshot_changed_during_read")
        return b"".join(chunks)
    finally:
        if file_fd >= 0:
            os.close(file_fd)


def _read_regular_file_snapshot(
    path: str | Path,
    *,
    max_bytes: int = MAX_LOCAL_JSON_BYTES,
) -> bytes:
    parent_fd, target_name = _open_parent_dirfd(path, create=False)
    try:
        return _read_regular_file_snapshot_at(
            parent_fd,
            target_name,
            max_bytes=max_bytes,
        )
    finally:
        os.close(parent_fd)


def _source_state() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _default_operator_status() -> dict[str, Any]:
    return {
        "status": "blocked",
        "current_label": "Memorial public-origin gold: blocked",
        "room_audio_receipt": "missing_or_blocked",
        "spoken_conversation_stt": {
            "status": "pass",
            "production_eligible": True,
            "ground_truth_fixture_mode": "synthetic_only",
            "real_captured_fixture_status": "captured_candidate_diagnostic_blocked",
        },
        "captured_candidate_diagnostic": {"status": "blocked", "promotion_allowed": False, "row_failure_codes": ["missing_live_candidate"]},
        "spoken_conversation_tts": {"status": "pass", "premium_status": "blocked", "room_audio_receipt": "blocked"},
        "room_audio_attestation_packet": {
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "required_check_ids": REQUIRED_ROOM_CHECK_IDS,
        },
    }


def _safe_nonnegative_int(value: object) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_finite_float(value: object) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return 0.0
    return round(parsed, 4)


def _safe_timestamp(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _evidence_is_fresh(generated_at: str, *, max_age_seconds: int) -> bool:
    if not generated_at or max_age_seconds <= 0:
        return False
    try:
        observed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    if observed.tzinfo is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    return -300.0 <= age_seconds <= float(max_age_seconds)


def _safe_failure_codes(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    codes: list[str] = []
    for item in list(value or []):
        normalized = str(item or "").strip()[:80]
        if normalized and normalized.replace("_", "").replace("-", "").isalnum():
            codes.append(normalized)
    return sorted(set(codes))


def _failure_codes_are_empty(value: object) -> bool:
    return isinstance(value, (list, tuple, set)) and not list(value)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _valid_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _raw_credential_material_exposed(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().casefold() in RAW_CREDENTIAL_KEYS:
                return True
            if _raw_credential_material_exposed(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_raw_credential_material_exposed(item) for item in value)
    if isinstance(value, str):
        normalized = value.lstrip().casefold()
        return any(
            normalized.startswith(prefix)
            for prefix in RAW_CREDENTIAL_STRING_PREFIXES
        )
    return False


def _private_review_binding_is_valid(receipt: dict[str, Any]) -> bool:
    binding = _mapping(receipt.get("review_session_binding"))
    expected_fields = {
        "contract_name",
        "access_mode",
        "source_revision",
        "image_id",
        "voice_identity_sha256",
        "expires_at_epoch",
        "bearer_material_exposed",
    }
    source_revision = str(receipt.get("source_git_head") or "")
    runtime_revision = str(receipt.get("runtime_source_revision") or "")
    image_id = str(binding.get("image_id") or "")
    expires_at = binding.get("expires_at_epoch")
    generated_at_value = _safe_timestamp(receipt.get("generated_at"))
    if not _evidence_is_fresh(
        generated_at_value,
        max_age_seconds=PRIVATE_REVIEW_MAX_AGE_SECONDS,
    ):
        return False
    generated_at = datetime.fromisoformat(
        generated_at_value.replace("Z", "+00:00")
    )
    return bool(
        set(binding) == expected_fields
        and binding.get("contract_name")
        == "ea.manfred_voice_review.v1"
        and binding.get("access_mode") == "private_review_session"
        and receipt.get("access_mode") == "private_review_session"
        and receipt.get("review_session_authenticated") is True
        and receipt.get("evidence_scope") == PRIVATE_REVIEW_EVIDENCE_SCOPE
        and receipt.get("private_review_evidence_allowed") is True
        and receipt.get("gold_claim_allowed") is False
        and receipt.get("base_url") == "https://myexternalbrain.com"
        and receipt.get("slug") == "manfred"
        and binding.get("source_revision") == source_revision
        and runtime_revision == source_revision
        and len(source_revision) == 40
        and all(
            character in "0123456789abcdef"
            for character in source_revision
        )
        and image_id.startswith("sha256:")
        and _valid_sha256(image_id.removeprefix("sha256:"))
        and _valid_sha256(binding.get("voice_identity_sha256"))
        and type(expires_at) is int
        and expires_at > int(generated_at.timestamp())
        and binding.get("bearer_material_exposed") is False
        and not _raw_credential_material_exposed(receipt)
    )


def _release_evidence_claim_allowed(
    receipt: dict[str, Any],
) -> bool:
    scope = str(receipt.get("evidence_scope") or "").strip()
    if scope == PRIVATE_REVIEW_EVIDENCE_SCOPE:
        return _private_review_binding_is_valid(receipt)
    if scope == ANONYMOUS_PUBLIC_EVIDENCE_SCOPE:
        return bool(
            receipt.get("gold_claim_allowed") is True
            and receipt.get("review_session_authenticated") is not True
            and receipt.get("private_review_evidence_allowed") is not True
            and not _mapping(receipt.get("review_session_binding"))
            and not _raw_credential_material_exposed(receipt)
        )
    if (
        receipt.get("review_session_authenticated") is True
        or receipt.get("private_review_evidence_allowed") is True
        or _mapping(receipt.get("review_session_binding"))
        or scope
    ):
        return False
    # Scope-less receipts are retained as a compatibility seam for the
    # pre-scope receipt contracts. They retain their original gold semantics;
    # new receipts must use an explicit scope.
    contract_name = str(receipt.get("contract_name") or "")
    if contract_name == EVIDENCE_RECEIPTS["voice_roundtrip"][1]:
        return bool(
            receipt.get("gold_claim_allowed") is True
            and not _raw_credential_material_exposed(receipt)
        )
    if contract_name == EVIDENCE_RECEIPTS["realtime_browser"][1]:
        return bool(
            (
                receipt.get("gold_claim_allowed") is None
                or receipt.get("gold_claim_allowed") is True
            )
            and not _raw_credential_material_exposed(receipt)
        )
    return False


def _release_evidence_scopes_are_consistent(
    *receipts: dict[str, Any],
) -> bool:
    scopes = [
        str(receipt.get("evidence_scope") or "").strip()
        for receipt in receipts
    ]
    if not any(scopes):
        return True
    if any(not scope for scope in scopes) or len(set(scopes)) != 1:
        return False
    if scopes[0] == ANONYMOUS_PUBLIC_EVIDENCE_SCOPE:
        return True
    if scopes[0] != PRIVATE_REVIEW_EVIDENCE_SCOPE:
        return False
    bindings = [
        _mapping(receipt.get("review_session_binding"))
        for receipt in receipts
    ]
    return bool(
        all(_private_review_binding_is_valid(receipt) for receipt in receipts)
        and bindings
        and all(binding == bindings[0] for binding in bindings[1:])
    )


def _browser_release_evidence_is_valid(receipt: dict[str, Any]) -> bool:
    scope = str(receipt.get("evidence_scope") or "").strip()
    if not scope:
        return True
    if (
        receipt.get("gold_mode") is not True
        or receipt.get("require_public_origin") is not True
        or receipt.get("speech_transcribe_mode") != "live"
    ):
        return False
    if scope == PRIVATE_REVIEW_EVIDENCE_SCOPE:
        return (
            receipt.get("launch_proof_scope")
            == PRIVATE_REVIEW_BROWSER_LAUNCH_SCOPE
        )
    return bool(
        scope == ANONYMOUS_PUBLIC_EVIDENCE_SCOPE
        and receipt.get("launch_proof_scope") == "real_public_microphone"
    )


def _room_audio_label_is_specific(field: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped or stripped != value:
        return False
    normalized = " ".join(stripped.casefold().split())
    return normalized not in ROOM_AUDIO_GENERIC_LABELS.get(field, set())


def _room_audio_receipt_is_authoritative(
    receipt: dict[str, Any],
) -> bool:
    if set(receipt) != ROOM_AUDIO_RECEIPT_FIELDS:
        return False

    source_revision = str(receipt.get("source_git_head") or "")
    runtime_revision = str(receipt.get("runtime_source_revision") or "")
    checks = _mapping(receipt.get("checks"))
    requirements = _mapping(receipt.get("check_requirements"))
    manual_attestation = _mapping(receipt.get("manual_attestation"))
    signed_at = manual_attestation.get("signed_at")
    if (
        receipt.get("contract_name") != ROOM_AUDIO_RECEIPT_CONTRACT
        or receipt.get("contract_version")
        != ROOM_AUDIO_RECEIPT_CONTRACT_VERSION
        or receipt.get("generated_by")
        != ROOM_AUDIO_RECEIPT_GENERATED_BY
        or receipt.get("proof_type") != ROOM_AUDIO_RECEIPT_PROOF_TYPE
        or receipt.get("head_semantics") != "source_state"
        or receipt.get("source_state_fingerprint_semantics")
        != "worktree_source_files_sha256_excluding_generated_only_paths"
        or not _valid_sha256(receipt.get("source_tree_fingerprint"))
        or not _valid_sha256(receipt.get("source_state_fingerprint"))
        or len(source_revision) != 40
        or any(
            character not in "0123456789abcdef"
            for character in source_revision
        )
        or runtime_revision != source_revision
        or receipt.get("runtime_source_revision_required") is not True
        or receipt.get("dirty_worktree") is not False
        or receipt.get("status") != "pass"
        or receipt.get("base_url") != "https://myexternalbrain.com"
        or receipt.get("slug") != "manfred"
        or receipt.get("require_public_origin") is not True
        or not _failure_codes_are_empty(receipt.get("failed_codes"))
        or set(checks) != set(REQUIRED_ROOM_CHECK_IDS)
        or any(value is not True for value in checks.values())
        or set(requirements) != set(REQUIRED_ROOM_CHECK_IDS)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in requirements.values()
        )
        or not _room_audio_label_is_specific(
            "reviewer",
            receipt.get("reviewer"),
        )
        or not _room_audio_label_is_specific(
            "device_label",
            receipt.get("device_label"),
        )
        or not _room_audio_label_is_specific(
            "speaker_label",
            receipt.get("speaker_label"),
        )
        or not _room_audio_label_is_specific(
            "room_label",
            receipt.get("room_label"),
        )
        or not isinstance(receipt.get("notes"), str)
        or not str(receipt.get("notes") or "").strip()
        or str(receipt.get("notes") or "").strip()
        != receipt.get("notes")
        or set(manual_attestation)
        != ROOM_AUDIO_MANUAL_ATTESTATION_FIELDS
        or not isinstance(
            manual_attestation.get("attestation_id"),
            str,
        )
        or not str(
            manual_attestation.get("attestation_id") or ""
        ).strip()
        or str(
            manual_attestation.get("attestation_id") or ""
        ).strip()
        != manual_attestation.get("attestation_id")
        or not isinstance(signed_at, str)
        or not signed_at.endswith("Z")
        or not _safe_timestamp(signed_at)
        or not isinstance(manual_attestation.get("source"), str)
        or not str(manual_attestation.get("source") or "").strip()
        or str(manual_attestation.get("source") or "").strip()
        != manual_attestation.get("source")
        or manual_attestation.get("ci_must_not_auto_assert") is not True
    ):
        return False

    scope = str(receipt.get("evidence_scope") or "").strip()
    if scope == PRIVATE_REVIEW_EVIDENCE_SCOPE:
        return _private_review_binding_is_valid(receipt)
    if scope != ANONYMOUS_PUBLIC_EVIDENCE_SCOPE:
        return False
    return bool(
        receipt.get("access_mode") == "anonymous_public"
        and receipt.get("review_session_authenticated") is False
        and receipt.get("review_session_binding") == {}
        and receipt.get("gold_claim_allowed") is True
        and receipt.get("private_review_evidence_allowed") is False
        and _release_evidence_claim_allowed(receipt)
    )


def _strict_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _strict_finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def _canonical_sha256(value: object) -> str:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _redacted_text_descriptor_is_safe(value: object) -> bool:
    descriptor = _mapping(value)
    return bool(
        set(descriptor) == {"text_chars", "text_redacted", "text_sha256"}
        and _strict_nonnegative_int(descriptor.get("text_chars")) not in {None, 0}
        and descriptor.get("text_redacted") is True
        and _valid_sha256(descriptor.get("text_sha256"))
    )


def _redacted_required_tokens_are_safe(value: object) -> bool:
    return bool(
        isinstance(value, list)
        and value
        and all(_redacted_text_descriptor_is_safe(item) for item in value)
    )


def _raw_transcript_key_exposed(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized == "expected_text":
                if not _redacted_text_descriptor_is_safe(item):
                    return True
                continue
            if normalized == "required_tokens":
                if not _redacted_required_tokens_are_safe(item):
                    return True
                continue
            if normalized in RAW_TRANSCRIPT_KEYS:
                return True
            looks_raw = "raw" in normalized or "transcript" in normalized
            if looks_raw and normalized not in ALLOWED_RAW_CONTROL_KEYS:
                return True
            if normalized == "raw_provider_transcript_scored" and item is not True:
                return True
            if normalized in {
                "public_receipt_must_not_include_full_text",
                "redacted_text_fields",
            } and item is not True:
                return True
            if normalized in {
                "candidate_raw_text_fields",
                "raw_text_fields",
                "raw_transcript_fields",
            } and item is not False:
                return True
            if _raw_transcript_key_exposed(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_raw_transcript_key_exposed(item) for item in value)
    return False


def _provider_result_is_bound(
    result: object,
    *,
    expected_text_sha256: str = "",
    required_token_sha256: list[str] | None = None,
    require_pass: bool,
    governed_thresholds: bool = False,
    upload_authorized: bool | None = None,
) -> bool:
    provider = _mapping(result)
    if not provider or any(key in provider for key in RAW_TRANSCRIPT_KEYS):
        return False
    expected_hash = str(provider.get("expected_text_sha256") or "")
    actual_hash = str(provider.get("actual_text_sha256") or "")
    raw_tokens = provider.get("required_token_sha256")
    tokens = [str(item) for item in _sequence(raw_tokens)]
    if not _valid_sha256(expected_hash) or not _valid_sha256(actual_hash):
        return False
    if not tokens or any(not _valid_sha256(item) for item in tokens):
        return False
    if expected_text_sha256 and expected_hash != expected_text_sha256:
        return False
    if required_token_sha256 is not None and tokens != required_token_sha256:
        return False
    if _strict_nonnegative_int(provider.get("required_token_count")) != len(tokens):
        return False
    if provider.get("text_mode") != "redacted" or provider.get("text_redacted") is not True:
        return False
    status = str(provider.get("status") or "")
    if status not in ALLOWED_PROVIDER_STATUSES:
        return False
    if any(not isinstance(provider.get(field), bool) for field in ("passed", "usable", "intent_correct")):
        return False
    if "fixture_invalid" in provider and not isinstance(provider.get("fixture_invalid"), bool):
        return False
    token_f1 = _strict_finite_float(provider.get("token_f1"))
    min_token_f1 = _strict_finite_float(provider.get("min_token_f1"))
    wer = _strict_finite_float(provider.get("wer"))
    max_wer = _strict_finite_float(provider.get("max_wer"))
    latency_ms = _strict_finite_float(provider.get("ms"))
    evidence_status = provider.get("provider_evidence_status")
    raw_evidence_failures = provider.get("provider_evidence_failed_codes")
    evidence_failures = _safe_failure_codes(raw_evidence_failures)
    if (
        token_f1 is None
        or not 0.0 <= token_f1 <= 1.0
        or min_token_f1 is None
        or not 0.0 <= min_token_f1 <= 1.0
        or wer is None
        or wer < 0.0
        or max_wer is None
        or max_wer < 0.0
        or latency_ms is None
        or latency_ms < 0.0
        or _strict_nonnegative_int(provider.get("expected_text_chars")) in {None, 0}
        or _strict_nonnegative_int(provider.get("actual_text_chars")) is None
        or evidence_status not in {"eligible", "blocked"}
        or not isinstance(raw_evidence_failures, list)
        or evidence_failures != raw_evidence_failures
        or (evidence_status == "eligible" and evidence_failures)
        or (evidence_status == "blocked" and not evidence_failures)
    ):
        return False
    if governed_thresholds and (min_token_f1, max_wer) not in GOVERNED_THRESHOLD_PAIRS:
        return False
    if upload_authorized is False:
        return bool(
            status == "not_authorized"
            and provider.get("passed") is False
            and evidence_status == "blocked"
            and "provider_upload_not_authorized" in evidence_failures
        )
    if upload_authorized is True and status == "not_authorized":
        return False
    if provider.get("passed") is True and (
        status not in SUCCESSFUL_PROVIDER_STATUSES
        or provider.get("usable") is not True
        or provider.get("intent_correct") is not True
        or provider.get("fixture_invalid") is True
        or evidence_status != "eligible"
        or evidence_failures
        or token_f1 is None
        or min_token_f1 is None
        or token_f1 < min_token_f1
        or wer is None
        or max_wer is None
        or wer > max_wer
    ):
        return False
    if not require_pass:
        return True
    return bool(
        provider.get("passed") is True
        and provider.get("usable") is True
        and provider.get("intent_correct") is True
        and provider.get("fixture_invalid") is not True
        and status in SUCCESSFUL_PROVIDER_STATUSES
        and provider.get("transcriber") == FULL_RUNTIME_TRANSCRIBER_RECEIPT
        and provider.get("scored_text_source") == "primary_transcript_text"
        and evidence_status == "eligible"
        and not evidence_failures
        and (
            "failure_codes" not in provider
            or _failure_codes_are_empty(provider.get("failure_codes"))
        )
        and token_f1 is not None
        and min_token_f1 is not None
        and token_f1 >= min_token_f1
        and wer is not None
        and max_wer is not None
        and wer <= max_wer
    )


def _transformation_is_bound(row: dict[str, Any], *, expected_id: str) -> bool:
    transformation = _mapping(row.get("transformation"))
    if set(transformation) != {"contract_name", "canonicalization", "sha256", "payload"}:
        return False
    if (
        transformation.get("contract_name") != TRANSFORMATION_RECEIPT_CONTRACT
        or transformation.get("canonicalization") != CANONICALIZATION
    ):
        return False
    payload = _mapping(transformation.get("payload"))
    if set(payload) != {
        "contract_name",
        "duration_preserved",
        "output_audio_sha256",
        "output_duration_seconds",
        "parameters",
        "source_audio_sha256",
        "source_duration_seconds",
        "transformation_id",
        "transformation_version",
    }:
        return False
    expected_parameters: dict[str, object] = (
        {}
        if expected_id == "identity_v1"
        else {
            "gain": 1.18,
            "echo_delay_ms": 76,
            "echo_mix": 0.22,
            "noise_cycle_pcm16": [132, -132, 66, -66],
            "speed_factor": 1.0,
        }
    )
    source_sha256 = str(row.get("source_fixture_sha256") or "")
    output_sha256 = str(row.get("fixture_sha256") or "")
    source_duration = _strict_finite_float(payload.get("source_duration_seconds"))
    output_duration = _strict_finite_float(payload.get("output_duration_seconds"))
    quality_duration = _strict_finite_float(
        _mapping(row.get("fixture_quality")).get("audio_duration_seconds")
    )
    if (
        payload.get("contract_name") != TRANSFORMATION_RECEIPT_CONTRACT
        or payload.get("transformation_id") != expected_id
        or payload.get("transformation_version") != 1
        or payload.get("parameters") != expected_parameters
        or payload.get("source_audio_sha256") != source_sha256
        or payload.get("output_audio_sha256") != output_sha256
        or payload.get("duration_preserved") is not True
        or source_duration is None
        or source_duration <= 0
        or output_duration is None
        or output_duration <= 0
        or abs(source_duration - output_duration) > 0.001
        or quality_duration is None
        or abs(output_duration - quality_duration) > 0.001
        or transformation.get("sha256") != _canonical_sha256(payload)
        or not _valid_sha256(transformation.get("sha256"))
    ):
        return False
    if expected_id == "identity_v1":
        return source_sha256 == output_sha256
    return source_sha256 != output_sha256


def _benchmark_binding(benchmark: dict[str, Any]) -> dict[str, Any]:
    binding = _mapping(benchmark.get("captured_candidate_binding"))
    if set(binding) != {
        "bundle_id",
        "candidate_binding_contract_name",
        "candidate_binding_sha256",
        "candidate_receipt_sha256",
        "operator_ground_truth_review_binding_sha256",
        "provider_upload_authorization",
        "sample",
        "source_audio_sha256",
    }:
        return {}
    if binding.get("candidate_binding_contract_name") != CANDIDATE_BINDING_CONTRACT:
        return {}
    if any(
        not _valid_sha256(binding.get(field))
        for field in (
            "candidate_binding_sha256",
            "candidate_receipt_sha256",
            "operator_ground_truth_review_binding_sha256",
            "source_audio_sha256",
        )
    ):
        return {}
    if not str(binding.get("bundle_id") or "").strip() or not str(binding.get("sample") or "").strip():
        return {}
    authorization = _mapping(binding.get("provider_upload_authorization"))
    if (
        set(authorization) != PROVIDER_UPLOAD_AUTHORIZATION_KEYS
        or any(not isinstance(value, bool) for value in authorization.values())
        or authorization.get("full_runtime") is not True
    ):
        return {}
    return binding


def _benchmark_receipt_is_authoritative(
    benchmark: dict[str, Any],
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    binding = _benchmark_binding(benchmark)
    scoring = _mapping(benchmark.get("scoring"))
    if (
        benchmark.get("contract_name") != EVIDENCE_RECEIPTS["stt_benchmark"][1]
        or benchmark.get("generated_by") != BENCHMARK_GENERATED_BY
        or benchmark.get("head_semantics") != "source_state"
        or benchmark.get("source_state_fingerprint_semantics")
        != "worktree_source_files_sha256_excluding_generated_only_paths"
        or benchmark.get("status") != "pass"
        or benchmark.get("fixture_quality_status") != "pass"
        or not _failure_codes_are_empty(benchmark.get("fixture_quality_failed_codes"))
        or not binding
        or scoring.get("raw_provider_transcript_scored") is not True
        or scoring.get("semantic_repair_applied") is not False
        or scoring.get("text_mode") != "redacted"
        or scoring.get("raw_transcript_fields") is not False
        or scoring.get("redacted_text_fields") is not True
        or _raw_transcript_key_exposed(benchmark)
    ):
        return False, binding, []

    raw_rows = benchmark.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows or any(not isinstance(row, dict) for row in raw_rows):
        return False, binding, []
    rows = [dict(row) for row in raw_rows]
    identities = [
        (str(row.get("sample") or ""), str(row.get("variant") or ""))
        for row in rows
    ]
    if len(set(identities)) != len(identities):
        return False, binding, []

    expected_sample = str(binding["sample"])
    source_audio_sha256 = str(binding["source_audio_sha256"])
    associated: list[dict[str, Any]] = []
    for row in rows:
        variant = str(row.get("variant") or "")
        if variant not in {"captured", "hostile", "synthetic"}:
            return False, binding, []
        source_sha256 = str(row.get("source_fixture_sha256") or "")
        fixture_sha256 = str(row.get("fixture_sha256") or "")
        fixture_quality = _mapping(row.get("fixture_quality"))
        source_quality = _mapping(row.get("source_fixture_quality"))
        if (
            not _valid_sha256(source_sha256)
            or not _valid_sha256(fixture_sha256)
            or fixture_quality.get("status") != "pass"
            or not _failure_codes_are_empty(fixture_quality.get("failed_codes"))
            or source_quality.get("status") != "pass"
            or not _failure_codes_are_empty(source_quality.get("failed_codes"))
        ):
            return False, binding, []
        expected_transformation = "hostile_room_v1" if variant == "hostile" else "identity_v1"
        if not _transformation_is_bound(row, expected_id=expected_transformation):
            return False, binding, []
        full_runtime = _mapping(row.get("full_runtime"))
        expected_text_sha256 = str(full_runtime.get("expected_text_sha256") or "")
        required_token_sha256 = [
            str(item) for item in _sequence(full_runtime.get("required_token_sha256"))
        ]
        authorization = _mapping(row.get("provider_upload_authorization"))
        if (
            set(authorization) != PROVIDER_UPLOAD_AUTHORIZATION_KEYS
            or any(not isinstance(value, bool) for value in authorization.values())
            or authorization.get("full_runtime") is not True
        ):
            return False, binding, []
        if not _provider_result_is_bound(
            full_runtime,
            require_pass=True,
            governed_thresholds=True,
            upload_authorized=authorization.get("full_runtime"),
        ):
            return False, binding, []
        for provider_name in ("onemin_sample", "shadow"):
            if not _provider_result_is_bound(
                row.get(provider_name),
                expected_text_sha256=expected_text_sha256,
                required_token_sha256=required_token_sha256,
                require_pass=False,
                upload_authorized=bool(authorization.get(provider_name)),
            ):
                return False, binding, []
        provenance = _mapping(row.get("provenance"))
        is_associated = bool(
            provenance.get("external_bundle") is True
            or source_sha256 == source_audio_sha256
            or row.get("sample") in {expected_sample, f"{expected_sample}_hostile"}
            or provenance.get("bundle_id") == binding.get("bundle_id")
            or provenance.get("candidate_binding_sha256")
            == binding.get("candidate_binding_sha256")
        )
        if is_associated:
            associated.append(row)

    expected_identities = {
        (expected_sample, "captured"),
        (f"{expected_sample}_hostile", "hostile"),
    }
    associated_identities = {
        (str(row.get("sample") or ""), str(row.get("variant") or ""))
        for row in associated
    }
    if len(associated) != 2 or associated_identities != expected_identities:
        return False, binding, []
    pair_expected_hash = ""
    pair_required_tokens: list[str] | None = None
    for row in associated:
        variant = str(row.get("variant") or "")
        provenance = _mapping(row.get("provenance"))
        authorization = _mapping(row.get("provider_upload_authorization"))
        if (
            row.get("source_fixture_sha256") != source_audio_sha256
            or provenance.get("external_bundle") is not True
            or provenance.get("synthetic") is not False
            or provenance.get("bundle_id") != binding.get("bundle_id")
            or provenance.get("candidate_receipt_sha256")
            != binding.get("candidate_receipt_sha256")
            or provenance.get("candidate_binding_contract_name")
            != CANDIDATE_BINDING_CONTRACT
            or provenance.get("candidate_binding_sha256")
            != binding.get("candidate_binding_sha256")
            or provenance.get("operator_ground_truth_review_binding_sha256")
            != binding.get("operator_ground_truth_review_binding_sha256")
            or provenance.get("provider_upload_authorization")
            != binding.get("provider_upload_authorization")
            or authorization != binding.get("provider_upload_authorization")
            or (variant == "captured" and row.get("fixture_sha256") != source_audio_sha256)
            or (variant == "hostile" and row.get("fixture_sha256") == source_audio_sha256)
        ):
            return False, binding, []
        full_runtime = _mapping(row.get("full_runtime"))
        if not _provider_result_is_bound(
            full_runtime,
            require_pass=True,
            governed_thresholds=True,
            upload_authorized=True,
        ):
            return False, binding, []
        row_expected_hash = str(full_runtime.get("expected_text_sha256") or "")
        row_required_tokens = [
            str(item) for item in _sequence(full_runtime.get("required_token_sha256"))
        ]
        if pair_expected_hash and row_expected_hash != pair_expected_hash:
            return False, binding, []
        if pair_required_tokens is not None and row_required_tokens != pair_required_tokens:
            return False, binding, []
        pair_expected_hash = row_expected_hash
        pair_required_tokens = row_required_tokens

    raw_ranking = benchmark.get("provider_ranking")
    if (
        not isinstance(raw_ranking, list)
        or any(not isinstance(item, dict) for item in raw_ranking)
    ):
        return False, binding, []
    ranking = [_mapping(item) for item in raw_ranking]
    ranking_by_provider = {
        str(item.get("provider") or ""): item
        for item in ranking
    }
    if (
        len(ranking_by_provider) != len(ranking)
        or "full_runtime" not in ranking_by_provider
        or not set(ranking_by_provider).issubset(
            {"full_runtime", "onemin_sample", "shadow"}
        )
    ):
        return False, binding, []
    row_count = len(rows)
    for provider_name, provider_ranking in ranking_by_provider.items():
        provider_rows = [_mapping(row.get(provider_name)) for row in rows]
        passed_samples = sum(result.get("passed") is True for result in provider_rows)
        scored_samples = sum("token_f1" in result for result in provider_rows)
        intent_correct_samples = sum(
            result.get("intent_correct") is True for result in provider_rows
        )
        token_f1_values = [
            _strict_finite_float(result.get("token_f1")) for result in provider_rows
        ]
        wer_values = [_strict_finite_float(result.get("wer")) for result in provider_rows]
        latency_values = [
            value
            for value in (
                _strict_finite_float(result.get("ms")) for result in provider_rows
            )
            if value is not None and value > 0.0
        ]
        if any(value is None for value in token_f1_values + wer_values):
            return False, binding, []
        expected_avg_token_f1 = round(
            sum(float(value) for value in token_f1_values) / len(token_f1_values),
            4,
        )
        expected_avg_wer = round(
            sum(float(value) for value in wer_values) / len(wer_values),
            4,
        )
        expected_avg_latency_ms = (
            round(sum(latency_values) / len(latency_values), 1)
            if latency_values
            else 0.0
        )
        production_eligible = passed_samples == row_count and row_count > 0
        if (
            _strict_nonnegative_int(provider_ranking.get("sample_count")) != row_count
            or _strict_nonnegative_int(provider_ranking.get("passed_samples"))
            != passed_samples
            or _strict_nonnegative_int(provider_ranking.get("scored_samples"))
            != scored_samples
            or _strict_nonnegative_int(provider_ranking.get("intent_correct_samples"))
            != intent_correct_samples
            or provider_ranking.get("production_eligible") is not production_eligible
            or _strict_finite_float(provider_ranking.get("avg_token_f1"))
            != expected_avg_token_f1
            or _strict_finite_float(provider_ranking.get("avg_wer"))
            != expected_avg_wer
            or _strict_finite_float(provider_ranking.get("avg_latency_ms"))
            != expected_avg_latency_ms
        ):
            return False, binding, []
    if ranking_by_provider["full_runtime"].get("production_eligible") is not True:
        return False, binding, []
    return True, binding, associated


def _candidate_receipt_is_authoritative(candidate: dict[str, Any]) -> bool:
    binding = _mapping(candidate.get("candidate_binding"))
    binding_payload = _mapping(binding.get("payload"))
    review = _mapping(candidate.get("operator_ground_truth_review"))
    return bool(
        candidate.get("contract_name") == EVIDENCE_RECEIPTS["stt_candidate"][1]
        and candidate.get("contract_version") == CANDIDATE_CONTRACT_VERSION
        and candidate.get("generated_by") == CANDIDATE_GENERATED_BY
        and candidate.get("head_semantics") == "source_state"
        and candidate.get("source_state_fingerprint_semantics")
        == "worktree_source_files_sha256_excluding_generated_only_paths"
        and candidate.get("status") == "pass"
        and candidate.get("candidate_scope") == FINAL_CANDIDATE_SCOPE
        and _failure_codes_are_empty(candidate.get("failed_codes"))
        and candidate.get("privacy_mode") == "redacted"
        and candidate.get("text_mode") == "redacted"
        and candidate.get("raw_text_fields") is False
        and binding.get("contract_name") == CANDIDATE_BINDING_CONTRACT
        and binding.get("canonicalization") == CANONICALIZATION
        and binding_payload.get("contract_name") == CANDIDATE_BINDING_CONTRACT
        and binding.get("sha256") == _canonical_sha256(binding_payload)
        and _valid_sha256(binding.get("sha256"))
        and review.get("contract_name") == GROUND_TRUTH_REVIEW_BINDING_CONTRACT
        and review.get("status") == "approved"
        and _valid_sha256(review.get("sha256"))
    )


def _strict_diagnostic_verifier_passes(
    *,
    root: Path | None = None,
    root_fd: int | None = None,
) -> bool:
    try:
        bound_root = (
            _directory_fd_reference_path(root_fd)
            if root_fd is not None
            else root
        )
        if bound_root is None:
            return False
        result = verify_diagnostic(
            bound_root / EVIDENCE_RECEIPTS["captured_candidate_diagnostic"][0],
            candidate_receipt_path=bound_root / EVIDENCE_RECEIPTS["stt_candidate"][0],
            benchmark_receipt_path=bound_root / EVIDENCE_RECEIPTS["stt_captured_benchmark"][0],
        )
    except (
        KeyError,
        OSError,
        OverflowError,
        RuntimeError,
        TypeError,
        UnsafeLocalFileError,
        ValueError,
    ):
        return False
    return bool(
        result.get("status") == "pass"
        and result.get("contract_name")
        == "ea.memorial_stt_captured_candidate_diagnostic_verifier"
        and _failure_codes_are_empty(result.get("issues"))
    )


def _diagnostic_failure_codes(diagnostic: dict[str, Any]) -> list[str]:
    blocker_summary = _mapping(diagnostic.get("blocker_summary"))
    values: list[object] = []
    values.extend(_sequence(diagnostic.get("issues")))
    values.extend(_sequence(blocker_summary.get("validation_issue_codes")))
    values.extend(_sequence(blocker_summary.get("fixture_quality_failed_code_sha256")))
    values.extend(_sequence(blocker_summary.get("row_failure_codes")))
    for row in _sequence(diagnostic.get("captured_rows")):
        values.extend(_sequence(_mapping(row).get("row_failure_codes")))
    for row in _sequence(blocker_summary.get("full_runtime_failed_rows")):
        values.extend(_sequence(_mapping(row).get("failure_codes")))
    return _safe_failure_codes(values)


def _diagnostic_provider_summary_is_bound(
    summary: object,
    *,
    benchmark_result: dict[str, Any],
    require_pass: bool,
) -> bool:
    provider = _mapping(summary)
    raw_failures = provider.get("failure_codes")
    benchmark_transcriber = _mapping(benchmark_result.get("transcriber"))
    expected_transcriber = benchmark_transcriber or {
        "family": "unknown",
        "identifier_sha256": "",
    }
    if not provider or any(key in provider for key in RAW_TRANSCRIPT_KEYS):
        return False
    if not isinstance(raw_failures, list) or len(_safe_failure_codes(raw_failures)) != len(raw_failures):
        return False
    if (
        provider.get("status") != benchmark_result.get("status")
        or provider.get("passed") is not benchmark_result.get("passed")
        or provider.get("usable") is not benchmark_result.get("usable")
        or provider.get("intent_correct") is not benchmark_result.get("intent_correct")
        or provider.get("fixture_invalid")
        is not (benchmark_result.get("fixture_invalid") is True)
        or _strict_finite_float(provider.get("token_f1"))
        != _strict_finite_float(benchmark_result.get("token_f1"))
        or provider.get("governed_min_token_f1") != GOVERNED_MIN_TOKEN_F1
        or _strict_finite_float(provider.get("wer"))
        != _strict_finite_float(benchmark_result.get("wer"))
        or provider.get("governed_max_wer") != GOVERNED_MAX_WER
        or provider.get("expected_text_chars") != benchmark_result.get("expected_text_chars")
        or provider.get("actual_text_chars") != benchmark_result.get("actual_text_chars")
        or provider.get("expected_text_sha256")
        != benchmark_result.get("expected_text_sha256")
        or provider.get("actual_text_sha256") != benchmark_result.get("actual_text_sha256")
        or provider.get("required_token_count") != benchmark_result.get("required_token_count")
        or provider.get("required_token_sha256")
        != benchmark_result.get("required_token_sha256")
        or provider.get("text_mode") != "redacted"
        or provider.get("text_redacted") is not True
        or provider.get("transcriber") != expected_transcriber
    ):
        return False
    if not require_pass:
        return True
    return bool(
        provider.get("status") in SUCCESSFUL_PROVIDER_STATUSES
        and provider.get("passed") is True
        and provider.get("usable") is True
        and provider.get("intent_correct") is True
        and provider.get("fixture_invalid") is False
        and provider.get("transcriber") == FULL_RUNTIME_TRANSCRIBER_RECEIPT
        and not raw_failures
    )


def _diagnostic_receipt_is_authoritative(
    diagnostic: dict[str, Any],
    *,
    benchmark_binding: dict[str, Any],
    benchmark_rows: list[dict[str, Any]],
    benchmark_receipt_sha256: str,
) -> bool:
    if (
        diagnostic.get("contract_name")
        != EVIDENCE_RECEIPTS["captured_candidate_diagnostic"][1]
        or diagnostic.get("contract_version") != DIAGNOSTIC_CONTRACT_VERSION
        or diagnostic.get("generated_by") != DIAGNOSTIC_GENERATED_BY
        or diagnostic.get("head_semantics") != "source_state"
        or diagnostic.get("source_state_fingerprint_semantics")
        != "worktree_source_files_sha256_excluding_generated_only_paths"
        or diagnostic.get("status") != "pass"
        or diagnostic.get("diagnostic_status") != "ready"
        or diagnostic.get("promotion_allowed") is not True
        or diagnostic.get("may_update_fixture_manifest") is not True
        or not _failure_codes_are_empty(diagnostic.get("issues"))
        or _strict_nonnegative_int(diagnostic.get("captured_row_count")) != 2
        or not benchmark_binding
        or not _valid_sha256(benchmark_receipt_sha256)
        or _raw_transcript_key_exposed(diagnostic)
    ):
        return False

    privacy = _mapping(diagnostic.get("privacy"))
    if (
        privacy.get("text_mode") != "redacted"
        or privacy.get("raw_transcript_fields") is not False
        or privacy.get("redacted_text_fields") is not True
        or privacy.get("candidate_raw_text_fields") is not False
        or privacy.get("public_receipt_must_not_include_full_text") is not True
    ):
        return False

    input_binding = _mapping(diagnostic.get("input_binding"))
    input_payload = _mapping(input_binding.get("payload"))
    if set(input_binding) != {"canonicalization", "contract_name", "payload", "sha256"}:
        return False
    if set(input_payload) != {
        "benchmark_receipt_sha256",
        "candidate_binding_sha256",
        "candidate_receipt_sha256",
        "contract_name",
        "operator_ground_truth_review_binding_sha256",
        "source_audio_sha256",
        "source_git_head",
        "source_state_fingerprint",
    }:
        return False
    expected_input_hash = _canonical_sha256(input_payload)
    if (
        input_binding.get("contract_name") != DIAGNOSTIC_INPUT_BINDING_CONTRACT
        or input_binding.get("canonicalization") != CANONICALIZATION
        or input_payload.get("contract_name") != DIAGNOSTIC_INPUT_BINDING_CONTRACT
        or input_binding.get("sha256") != expected_input_hash
        or diagnostic.get("input_binding_sha256") != expected_input_hash
        or not _valid_sha256(expected_input_hash)
        or input_payload.get("benchmark_receipt_sha256") != benchmark_receipt_sha256
        or input_payload.get("candidate_receipt_sha256")
        != benchmark_binding.get("candidate_receipt_sha256")
        or input_payload.get("candidate_binding_sha256")
        != benchmark_binding.get("candidate_binding_sha256")
        or input_payload.get("operator_ground_truth_review_binding_sha256")
        != benchmark_binding.get("operator_ground_truth_review_binding_sha256")
        or input_payload.get("source_audio_sha256")
        != benchmark_binding.get("source_audio_sha256")
        or input_payload.get("source_git_head") != diagnostic.get("source_git_head")
        or input_payload.get("source_state_fingerprint")
        != diagnostic.get("source_state_fingerprint")
    ):
        return False
    if any(
        not _valid_sha256(input_payload.get(field))
        for field in (
            "benchmark_receipt_sha256",
            "candidate_binding_sha256",
            "candidate_receipt_sha256",
            "operator_ground_truth_review_binding_sha256",
            "source_audio_sha256",
        )
    ):
        return False

    candidate_receipt = _mapping(diagnostic.get("candidate_receipt"))
    benchmark_receipt = _mapping(diagnostic.get("benchmark_receipt"))
    if (
        candidate_receipt.get("exists") is not True
        or candidate_receipt.get("sha256") != input_payload.get("candidate_receipt_sha256")
        or benchmark_receipt.get("exists") is not True
        or benchmark_receipt.get("sha256") != benchmark_receipt_sha256
    ):
        return False
    candidate = _mapping(diagnostic.get("candidate"))
    candidate_binding = _mapping(candidate.get("candidate_binding"))
    review_binding = _mapping(candidate.get("operator_ground_truth_review"))
    expected_sample_sha256 = hashlib.sha256(
        str(benchmark_binding.get("sample") or "").encode("utf-8")
    ).hexdigest()
    if (
        candidate.get("status") != "pass"
        or candidate.get("candidate_scope") != FINAL_CANDIDATE_SCOPE
        or not _failure_codes_are_empty(candidate.get("failed_code_sha256"))
        or candidate.get("privacy_mode") != "redacted"
        or candidate.get("raw_text_fields") is not False
        or candidate.get("audio_sha256") != benchmark_binding.get("source_audio_sha256")
        or candidate.get("sample_sha256") != expected_sample_sha256
        or candidate.get("speaker_consent_authorized") is not True
        or candidate.get("allowed_purpose_authorized") is not True
        or candidate.get("retention_authorized") is not True
        or candidate.get("language_authorized") is not True
        or candidate.get("provider_upload_authorization")
        != benchmark_binding.get("provider_upload_authorization")
        or candidate_binding.get("contract_name") != CANDIDATE_BINDING_CONTRACT
        or candidate_binding.get("sha256") != benchmark_binding.get("candidate_binding_sha256")
        or review_binding.get("contract_name") != GROUND_TRUTH_REVIEW_BINDING_CONTRACT
        or review_binding.get("status") != "approved"
        or review_binding.get("reviewer_authority") != "memorial_operator"
        or review_binding.get("sha256")
        != benchmark_binding.get("operator_ground_truth_review_binding_sha256")
    ):
        return False

    blocker_summary = _mapping(diagnostic.get("blocker_summary"))
    if (
        not _failure_codes_are_empty(blocker_summary.get("validation_issue_codes"))
        or not _failure_codes_are_empty(
            blocker_summary.get("fixture_quality_failed_code_sha256")
        )
        or not _failure_codes_are_empty(blocker_summary.get("full_runtime_failed_rows"))
        or _diagnostic_failure_codes(diagnostic)
    ):
        return False
    if (
        diagnostic.get("benchmark_status") != "pass"
        or diagnostic.get("benchmark_fixture_quality_status") != "pass"
        or diagnostic.get("next_action") != "promote_captured_candidate_to_fixture_manifest"
    ):
        return False

    rows = [_mapping(row) for row in _sequence(diagnostic.get("captured_rows"))]
    expected_sample = str(benchmark_binding.get("sample") or "")
    expected_sample_sha256 = hashlib.sha256(expected_sample.encode("utf-8")).hexdigest()
    expected_hostile_sample_sha256 = hashlib.sha256(
        f"{expected_sample}_hostile".encode("utf-8")
    ).hexdigest()
    identities = {
        (str(row.get("sample_sha256") or ""), str(row.get("variant") or ""))
        for row in rows
    }
    if len(rows) != 2 or identities != {
        (expected_sample_sha256, "captured"),
        (expected_hostile_sample_sha256, "hostile"),
    } or len(benchmark_rows) != 2:
        return False
    benchmark_by_identity = {
        (
            hashlib.sha256(str(row.get("sample") or "").encode("utf-8")).hexdigest(),
            str(row.get("variant") or ""),
        ): row
        for row in benchmark_rows
    }
    for row in rows:
        variant = str(row.get("variant") or "")
        identity = (str(row.get("sample_sha256") or ""), variant)
        benchmark_row = _mapping(benchmark_by_identity.get(identity))
        provenance = _mapping(row.get("provenance"))
        providers = _mapping(row.get("providers"))
        full_runtime = _mapping(providers.get("full_runtime"))
        benchmark_quality = _mapping(benchmark_row.get("fixture_quality"))
        expected_quality = {
            "status": str(benchmark_quality.get("status") or ""),
            "failed_code_sha256": [],
            "audio_duration_seconds": _strict_finite_float(
                benchmark_quality.get("audio_duration_seconds")
            ),
            "expected_min_duration_seconds": _strict_finite_float(
                benchmark_quality.get("expected_min_duration_seconds")
            ),
        }
        benchmark_transformation = _mapping(benchmark_row.get("transformation"))
        transformation_payload = _mapping(benchmark_transformation.get("payload"))
        expected_transformation = {
            "contract_name": str(benchmark_transformation.get("contract_name") or ""),
            "transformation_id": str(transformation_payload.get("transformation_id") or ""),
            "transformation_version": transformation_payload.get("transformation_version"),
            "source_audio_sha256": str(
                transformation_payload.get("source_audio_sha256") or ""
            ),
            "output_audio_sha256": str(
                transformation_payload.get("output_audio_sha256") or ""
            ),
            "source_duration_seconds": _strict_finite_float(
                transformation_payload.get("source_duration_seconds")
            ),
            "output_duration_seconds": _strict_finite_float(
                transformation_payload.get("output_duration_seconds")
            ),
            "duration_preserved": transformation_payload.get("duration_preserved") is True,
            "sha256": str(benchmark_transformation.get("sha256") or ""),
        }
        if (
            not benchmark_row
            or row.get("source_fixture_sha256") != benchmark_binding.get("source_audio_sha256")
            or row.get("source_fixture_sha256") != benchmark_row.get("source_fixture_sha256")
            or not _valid_sha256(row.get("actual_fixture_sha256"))
            or row.get("actual_fixture_sha256") != benchmark_row.get("fixture_sha256")
            or (variant == "captured" and row.get("actual_fixture_sha256") != row.get("source_fixture_sha256"))
            or (variant == "hostile" and row.get("actual_fixture_sha256") == row.get("source_fixture_sha256"))
            or _mapping(row.get("fixture_quality")) != expected_quality
            or _mapping(row.get("transformation")) != expected_transformation
            or not _failure_codes_are_empty(row.get("row_failure_codes"))
            or provenance.get("external_bundle") is not True
            or provenance.get("synthetic") is not False
            or provenance.get("speaker_consent_authorized") is not True
            or provenance.get("allowed_purpose_authorized") is not True
            or provenance.get("retention_authorized") is not True
            or provenance.get("language_authorized") is not True
            or provenance.get("candidate_receipt_sha256")
            != benchmark_binding.get("candidate_receipt_sha256")
            or provenance.get("candidate_binding_sha256")
            != benchmark_binding.get("candidate_binding_sha256")
            or provenance.get("operator_ground_truth_review_binding_sha256")
            != benchmark_binding.get("operator_ground_truth_review_binding_sha256")
            or provenance.get("provider_upload_authorization")
            != benchmark_binding.get("provider_upload_authorization")
        ):
            return False
        if set(providers) != {"full_runtime", "onemin_sample", "shadow"}:
            return False
        for provider_name in ("full_runtime", "onemin_sample", "shadow"):
            provider = _mapping(providers.get(provider_name))
            benchmark_provider = _mapping(benchmark_row.get(provider_name))
            if not _diagnostic_provider_summary_is_bound(
                provider,
                benchmark_result=benchmark_provider,
                require_pass=provider_name == "full_runtime",
            ):
                return False
    return True


def _load_evidence_receipt(
    *,
    root: Path | None = None,
    root_fd: int | None = None,
    root_missing: bool = False,
    receipt_name: str,
    expected_contract: str,
    current_head: str,
    current_fingerprint: str,
    max_age_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence: dict[str, Any] = {
        "receipt_name": receipt_name,
        "present": False,
        "contract_name": expected_contract,
        "contract_valid": False,
        "status": "missing",
        "generated_at": "",
        "max_age_seconds": int(max_age_seconds),
        "fresh": False,
        "receipt_sha256": "",
        "source_git_head_present": False,
        "source_git_head_matches_current": False,
        "source_state_fingerprint_present": False,
        "source_state_matches_current": False,
        "raw_private_context_exposed": False,
        "raw_transcript_fields_exposed": False,
        "raw_credentials_exposed": False,
        "raw_receipt_payload_exposed": False,
    }
    if root_missing:
        return {}, evidence
    try:
        if root_fd is not None:
            raw = _read_regular_file_snapshot_at(root_fd, receipt_name)
        elif root is not None:
            raw = _read_regular_file_snapshot(root / receipt_name)
        else:
            raise UnsafeLocalFileError("local_evidence_root_missing")
    except FileNotFoundError:
        return {}, evidence
    except (OSError, UnsafeLocalFileError):
        evidence["status"] = "invalid"
        return {}, evidence
    evidence["present"] = True
    evidence["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        evidence["status"] = "invalid_json"
        return {}, evidence
    if not isinstance(parsed, dict):
        evidence["status"] = "invalid_shape"
        return {}, evidence
    payload = dict(parsed)
    if _raw_credential_material_exposed(payload):
        evidence["raw_credentials_exposed"] = True
        evidence["status"] = "invalid"
        return {}, evidence
    contract_name = str(payload.get("contract_name") or "").strip()
    contract_valid = contract_name == expected_contract
    recorded_head = str(payload.get("source_git_head") or "").strip()
    recorded_fingerprint = str(payload.get("source_state_fingerprint") or "").strip()
    raw_status = str(payload.get("status") or "unknown").strip()
    safe_status = (
        raw_status
        if raw_status
        in {
            "blocked",
            "fail",
            "invalid",
            "pass",
            "ready",
            "skipped",
            "unknown",
            "warn",
        }
        else "unknown"
    )
    generated_at = _safe_timestamp(payload.get("generated_at") or payload.get("checked_at"))
    effective_max_age_seconds = int(max_age_seconds)
    if payload.get("evidence_scope") == PRIVATE_REVIEW_EVIDENCE_SCOPE:
        effective_max_age_seconds = min(
            effective_max_age_seconds,
            PRIVATE_REVIEW_MAX_AGE_SECONDS,
        )
    evidence.update(
        {
            "contract_valid": contract_valid,
            "status": safe_status,
            "generated_at": generated_at,
            "fresh": _evidence_is_fresh(
                generated_at,
                max_age_seconds=effective_max_age_seconds,
            ),
            "max_age_seconds": effective_max_age_seconds,
            "source_git_head_present": bool(recorded_head),
            "source_git_head_matches_current": bool(
                recorded_head and current_head and recorded_head == current_head
            ),
            "source_state_fingerprint_present": bool(recorded_fingerprint),
            "source_state_matches_current": bool(
                recorded_fingerprint
                and current_fingerprint
                and recorded_fingerprint == current_fingerprint
                and payload.get("source_state_fingerprint_semantics")
                == "worktree_source_files_sha256_excluding_generated_only_paths"
            ),
        }
    )
    if _raw_transcript_key_exposed(payload):
        evidence["status"] = "invalid"
        return {}, evidence
    return payload if contract_valid else {}, evidence


def _full_runtime_ranking(benchmark: dict[str, Any]) -> dict[str, Any]:
    for row in list(benchmark.get("provider_ranking") or []):
        if isinstance(row, dict) and str(row.get("provider") or "").strip() == "full_runtime":
            return dict(row)
    return {}


def _benchmark_claim_semantics_match(
    main_benchmark: dict[str, Any],
    captured_benchmark: dict[str, Any],
) -> bool:
    claim_fields = (
        "captured_candidate_binding",
        "fixture_quality_failed_codes",
        "fixture_quality_status",
        "provider_ranking",
        "rows",
        "scoring",
        "status",
    )
    return all(
        main_benchmark.get(field) == captured_benchmark.get(field)
        for field in claim_fields
    )


def _operator_status_from_receipts(
    receipt_root: str | Path = DEFAULT_EVIDENCE_ROOT,
    *,
    receipt_root_fd: int | None = None,
) -> dict[str, Any]:
    if receipt_root_fd is None and not str(receipt_root).strip():
        raise UnsafeLocalFileError("local_evidence_root_empty")
    try:
        opened_root_fd = (
            _open_directory_fd(receipt_root)
            if receipt_root_fd is None
            else _duplicate_directory_fd(receipt_root_fd)
        )
    except FileNotFoundError:
        return _operator_status_from_open_receipts(None)
    try:
        initial_root_snapshot = _directory_fd_snapshot(opened_root_fd)
        result = _operator_status_from_open_receipts(opened_root_fd)
        if _directory_fd_snapshot(opened_root_fd) != initial_root_snapshot:
            raise UnsafeLocalFileError(
                "local_evidence_root_changed_during_aggregation"
            )
        return result
    finally:
        os.close(opened_root_fd)


def _operator_status_from_open_receipts(
    receipt_root_fd: int | None,
) -> dict[str, Any]:
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    receipts: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for key, (receipt_name, expected_contract) in EVIDENCE_RECEIPTS.items():
        payload, receipt_evidence = _load_evidence_receipt(
            root_fd=receipt_root_fd,
            root_missing=receipt_root_fd is None,
            receipt_name=receipt_name,
            expected_contract=expected_contract,
            current_head=current_head,
            current_fingerprint=current_fingerprint,
            max_age_seconds=EVIDENCE_MAX_AGE_SECONDS[key],
        )
        receipts[key] = payload
        evidence[key] = receipt_evidence

    candidate_receipt = receipts["stt_candidate"]
    candidate_evidence = evidence["stt_candidate"]
    candidate_authoritative = bool(
        candidate_evidence.get("contract_valid")
        and candidate_evidence.get("source_state_matches_current")
        and candidate_evidence.get("fresh")
        and _candidate_receipt_is_authoritative(candidate_receipt)
    )
    captured_benchmark = receipts["stt_captured_benchmark"]
    captured_benchmark_evidence = evidence["stt_captured_benchmark"]
    (
        captured_benchmark_authoritative,
        captured_benchmark_binding,
        captured_source_rows,
    ) = _benchmark_receipt_is_authoritative(captured_benchmark)
    captured_source_authoritative = bool(
        captured_benchmark_evidence.get("contract_valid")
        and captured_benchmark_evidence.get("source_state_matches_current")
        and captured_benchmark_evidence.get("fresh")
        and captured_benchmark_authoritative
        and captured_benchmark_binding.get("candidate_receipt_sha256")
        == candidate_evidence.get("receipt_sha256")
    )

    benchmark = receipts["stt_benchmark"]
    benchmark_evidence = evidence["stt_benchmark"]
    ranking = _full_runtime_ranking(benchmark)
    benchmark_authoritative, benchmark_binding, main_captured_rows = (
        _benchmark_receipt_is_authoritative(benchmark)
    )
    strict_diagnostic_verified = bool(
        receipt_root_fd is not None
        and _strict_diagnostic_verifier_passes(root_fd=receipt_root_fd)
    )
    captured_benchmark_ready = bool(
        candidate_authoritative
        and captured_source_authoritative
        and benchmark_evidence.get("contract_valid")
        and benchmark_evidence.get("source_state_matches_current")
        and benchmark_evidence.get("fresh")
        and benchmark_authoritative
        and benchmark_binding == captured_benchmark_binding
        and _benchmark_claim_semantics_match(benchmark, captured_benchmark)
        and benchmark_binding.get("candidate_receipt_sha256")
        == candidate_evidence.get("receipt_sha256")
        and strict_diagnostic_verified
    )
    stt = {
        "status": "pass" if captured_benchmark_ready else "blocked",
        "production_eligible": captured_benchmark_ready,
        "production_provider": "full_runtime",
        "provider_label": "full_runtime",
        "passed_samples": _safe_nonnegative_int(ranking.get("passed_samples")),
        "sample_count": _safe_nonnegative_int(ranking.get("sample_count")),
        "avg_token_f1": _safe_finite_float(ranking.get("avg_token_f1")),
        "avg_wer": _safe_finite_float(ranking.get("avg_wer")),
        "ground_truth_fixture_mode": (
            "captured_external" if main_captured_rows else "synthetic_only"
        ),
        "real_captured_fixture_status": (
            "captured_candidate_benchmark_pass"
            if captured_benchmark_ready
            else "captured_candidate_diagnostic_blocked"
        ),
        "next_action": (
            "" if captured_benchmark_ready else STT_REMEDIATION_ACTION
        ),
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['stt_benchmark'][0]}",
        "scoring": {
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    diagnostic_receipt = receipts["captured_candidate_diagnostic"]
    diagnostic_evidence = evidence["captured_candidate_diagnostic"]
    diagnostic_failure_codes = _diagnostic_failure_codes(diagnostic_receipt)
    diagnostic_ready = bool(
        diagnostic_evidence.get("contract_valid")
        and diagnostic_evidence.get("source_state_matches_current")
        and diagnostic_evidence.get("fresh")
        and _diagnostic_receipt_is_authoritative(
            diagnostic_receipt,
            benchmark_binding=captured_benchmark_binding,
            benchmark_rows=captured_source_rows,
            benchmark_receipt_sha256=str(
                captured_benchmark_evidence.get("receipt_sha256") or ""
            ),
        )
        and strict_diagnostic_verified
    )
    raw_diagnostic_status = str(diagnostic_receipt.get("diagnostic_status") or "missing").strip()
    diagnostic = {
        "status": "ready" if diagnostic_ready else "blocked",
        "diagnostic_status": (
            raw_diagnostic_status
            if raw_diagnostic_status in {"blocked", "fail", "missing", "pass", "ready"}
            else "unknown"
        ),
        "promotion_allowed": diagnostic_ready,
        "may_update_fixture_manifest": diagnostic_ready,
        "captured_row_count": _safe_nonnegative_int(diagnostic_receipt.get("captured_row_count")),
        "row_failure_codes": diagnostic_failure_codes,
        "next_action": (
            "" if diagnostic_ready else STT_REMEDIATION_ACTION
        ),
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['captured_candidate_diagnostic'][0]}",
        "privacy": {
            "candidate_raw_text_fields": False,
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    roundtrip = receipts["voice_roundtrip"]
    roundtrip_evidence = evidence["voice_roundtrip"]
    browser = receipts["realtime_browser"]
    room_audio = receipts["room_audio"]
    release_evidence_scopes_consistent = (
        _release_evidence_scopes_are_consistent(
            roundtrip,
            browser,
            room_audio,
        )
    )
    roundtrip_ready = bool(
        roundtrip_evidence.get("contract_valid")
        and roundtrip_evidence.get("source_state_matches_current")
        and roundtrip_evidence.get("fresh")
        and roundtrip.get("status") == "pass"
        and _release_evidence_claim_allowed(roundtrip)
        and release_evidence_scopes_consistent
        and _failure_codes_are_empty(roundtrip.get("failed_codes"))
    )
    browser_evidence = evidence["realtime_browser"]
    browser_ready = bool(
        browser_evidence.get("contract_valid")
        and browser_evidence.get("source_state_matches_current")
        and browser_evidence.get("fresh")
        and browser.get("status") == "pass"
        and _release_evidence_claim_allowed(browser)
        and _browser_release_evidence_is_valid(browser)
        and release_evidence_scopes_consistent
        and _failure_codes_are_empty(browser.get("failed_codes"))
        and browser.get("audio_ready_for_ui") is True
        and _safe_nonnegative_int(browser.get("ui_audio_play_ended")) >= 1
    )
    room_evidence = evidence["room_audio"]
    room_audio_ready = bool(
        room_evidence.get("contract_valid")
        and room_evidence.get("source_state_matches_current")
        and room_evidence.get("fresh")
        and _room_audio_receipt_is_authoritative(room_audio)
        and release_evidence_scopes_consistent
    )
    roundtrip_metrics = dict(roundtrip.get("metrics") or {})
    tts_automated_ready = roundtrip_ready and browser_ready
    tts = {
        "status": "pass" if tts_automated_ready else "blocked",
        "premium_status": "pass" if tts_automated_ready and room_audio_ready else "blocked",
        "direct_tts_audio_status": "pass" if roundtrip_ready else "blocked",
        "conversation_turn_audio_status": "pass" if roundtrip_ready else "blocked",
        "direct_tts_f1": _safe_finite_float(roundtrip_metrics.get("direct_tts_f1")),
        "conversation_turn_audio_f1": _safe_finite_float(
            roundtrip_metrics.get("conversation_turn_audio_f1")
        ),
        "browser_audio_ready_for_ui": browser_ready,
        "browser_audio_transport": "ui_playback_probe",
        "browser_play_calls": _safe_nonnegative_int(browser.get("ui_audio_play_calls")),
        "browser_play_ended": _safe_nonnegative_int(browser.get("ui_audio_play_ended")),
        "room_audio_receipt": "pass" if room_audio_ready else "blocked",
        "premium_failed_codes": sorted(
            set(
                ([] if roundtrip_ready else ["voice_roundtrip_not_current"])
                + ([] if browser_ready else ["browser_audio_not_current"])
                + ([] if room_audio_ready else ["room_audio_attestation_not_pass"])
            )
        ),
        "next_action": (
            STT_REMEDIATION_ACTION
            if not (captured_benchmark_ready and diagnostic_ready)
            else (
                AUTOMATED_VOICE_REMEDIATION_ACTION
                if not tts_automated_ready
                else ("" if room_audio_ready else "collect_real_room_audio_attestation")
            )
        ),
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['voice_roundtrip'][0]}",
        "browser_receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['realtime_browser'][0]}",
        "room_audio_receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['room_audio'][0]}",
    }

    packet = receipts["room_audio_attestation_packet"]
    packet_evidence = evidence["room_audio_attestation_packet"]
    raw_packet_required_ids = [
        str(item.get("id") or "").strip()
        for item in list(packet.get("required_checks") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    packet_required_ids = [
        check_id
        for check_id in raw_packet_required_ids
        if check_id in REQUIRED_ROOM_CHECK_IDS
    ]
    attestation_ready = bool(
        packet_evidence.get("contract_valid")
        and packet_evidence.get("source_state_matches_current")
        and packet_evidence.get("fresh")
        and packet.get("generated_by") == ATTESTATION_GENERATED_BY
        and packet.get("head_semantics") == "source_state"
        and packet.get("source_state_fingerprint_semantics")
        == "worktree_source_files_sha256_excluding_generated_only_paths"
        and packet.get("status") == "ready"
        and packet.get("slug") == "manfred"
        and packet.get("proof_target")
        == ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
        and packet.get("manual_only") is True
        and packet.get("ci_must_not_auto_assert") is True
        and len(raw_packet_required_ids) == len(REQUIRED_ROOM_CHECK_IDS)
        and set(raw_packet_required_ids) == set(REQUIRED_ROOM_CHECK_IDS)
        and packet.get("operator_command")
        == "make materialize-memorial-room-audio-gold-clean"
        and not _raw_transcript_key_exposed(packet)
    )
    attestation = {
        "status": "ready" if attestation_ready else "blocked",
        "manual_only": packet.get("manual_only") is True,
        "ci_must_not_auto_assert": packet.get("ci_must_not_auto_assert") is True,
        "required_check_ids": packet_required_ids,
        "operator_command": (
            "make materialize-memorial-room-audio-gold-clean"
            if packet.get("operator_command") == "make materialize-memorial-room-audio-gold-clean"
            else ""
        ),
        "next_action": (
            "collect_real_room_audio_attestation"
            if (
                captured_benchmark_ready
                and diagnostic_ready
                and tts_automated_ready
                and (not room_audio_ready or not attestation_ready)
            )
            else ""
        ),
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['room_audio_attestation_packet'][0]}",
        "source_state_matches_current": bool(packet_evidence.get("source_state_matches_current")),
        "evidence_fresh": bool(packet_evidence.get("fresh")),
    }

    ready = (
        captured_benchmark_ready
        and diagnostic_ready
        and tts_automated_ready
        and room_audio_ready
        and attestation_ready
    )
    return {
        "status": "pass" if ready else "blocked",
        "current_label": (
            "Memorial public-origin gold: pass" if ready else "Memorial public-origin gold: blocked"
        ),
        "room_audio_receipt": "pass" if room_audio_ready else "missing_or_blocked",
        "spoken_conversation_stt": stt,
        "captured_candidate_diagnostic": diagnostic,
        "spoken_conversation_tts": tts,
        "room_audio_attestation_packet": attestation,
        "input_evidence": evidence,
    }


def _sanitize_provided_operator_status(status: dict[str, Any]) -> dict[str, Any]:
    raw_stt = dict(status.get("spoken_conversation_stt") or {})
    captured_ready = (
        raw_stt.get("status") == "pass"
        and raw_stt.get("production_eligible") is True
        and raw_stt.get("real_captured_fixture_status") == "captured_candidate_benchmark_pass"
    )
    stt = {
        "status": "pass" if captured_ready else "blocked",
        "production_eligible": captured_ready,
        "production_provider": "full_runtime",
        "provider_label": "full_runtime",
        "passed_samples": _safe_nonnegative_int(raw_stt.get("passed_samples")),
        "sample_count": _safe_nonnegative_int(raw_stt.get("sample_count")),
        "avg_token_f1": _safe_finite_float(raw_stt.get("avg_token_f1")),
        "avg_wer": _safe_finite_float(raw_stt.get("avg_wer")),
        "ground_truth_fixture_mode": (
            "captured_external"
            if raw_stt.get("ground_truth_fixture_mode") == "captured_external"
            else "synthetic_only"
        ),
        "real_captured_fixture_status": (
            "captured_candidate_benchmark_pass"
            if captured_ready
            else "captured_candidate_diagnostic_blocked"
        ),
        "next_action": (
            "" if captured_ready else STT_REMEDIATION_ACTION
        ),
        "receipt_path": ".codex-studio/published/memorial_stt_provider_benchmark.generated.json",
        "scoring": {
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    raw_diagnostic = dict(status.get("captured_candidate_diagnostic") or {})
    diagnostic_ready = bool(
        raw_diagnostic.get("status") in {"pass", "ready"}
        and raw_diagnostic.get("diagnostic_status") == "ready"
        and raw_diagnostic.get("promotion_allowed") is True
        and raw_diagnostic.get("may_update_fixture_manifest") is True
        and _strict_nonnegative_int(raw_diagnostic.get("captured_row_count")) == 2
        and _failure_codes_are_empty(raw_diagnostic.get("issues"))
        and _failure_codes_are_empty(raw_diagnostic.get("row_failure_codes"))
        and _mapping(raw_diagnostic.get("input_binding")).get("contract_name")
        == DIAGNOSTIC_INPUT_BINDING_CONTRACT
        and _valid_sha256(raw_diagnostic.get("input_binding_sha256"))
    )
    diagnostic = {
        "status": "ready" if diagnostic_ready else "blocked",
        "diagnostic_status": "ready" if diagnostic_ready else "blocked",
        "promotion_allowed": diagnostic_ready,
        "may_update_fixture_manifest": diagnostic_ready,
        "captured_row_count": _safe_nonnegative_int(raw_diagnostic.get("captured_row_count")),
        "row_failure_codes": _safe_failure_codes(raw_diagnostic.get("row_failure_codes")),
        "next_action": (
            "" if diagnostic_ready else STT_REMEDIATION_ACTION
        ),
        "receipt_path": ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json",
        "privacy": {
            "candidate_raw_text_fields": False,
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    raw_tts = dict(status.get("spoken_conversation_tts") or {})
    tts_automated_ready = bool(
        raw_tts.get("status") == "pass"
        and raw_tts.get("direct_tts_audio_status") == "pass"
        and raw_tts.get("conversation_turn_audio_status") == "pass"
        and raw_tts.get("browser_audio_ready_for_ui") is True
        and _safe_nonnegative_int(raw_tts.get("browser_play_calls")) >= 1
        and _safe_nonnegative_int(raw_tts.get("browser_play_ended")) >= 1
    )
    room_audio_ready = bool(
        status.get("room_audio_receipt") == "pass"
        and raw_tts.get("room_audio_receipt") == "pass"
        and raw_tts.get("premium_status") == "pass"
    )
    tts = {
        "status": "pass" if tts_automated_ready else "blocked",
        "premium_status": "pass" if tts_automated_ready and room_audio_ready else "blocked",
        "direct_tts_audio_status": "pass" if tts_automated_ready else "blocked",
        "conversation_turn_audio_status": "pass" if tts_automated_ready else "blocked",
        "direct_tts_f1": _safe_finite_float(raw_tts.get("direct_tts_f1")),
        "conversation_turn_audio_f1": _safe_finite_float(
            raw_tts.get("conversation_turn_audio_f1")
        ),
        "browser_audio_ready_for_ui": tts_automated_ready,
        "browser_audio_transport": "ui_playback_probe",
        "browser_play_calls": _safe_nonnegative_int(raw_tts.get("browser_play_calls")),
        "browser_play_ended": _safe_nonnegative_int(raw_tts.get("browser_play_ended")),
        "room_audio_receipt": "pass" if room_audio_ready else "blocked",
        "premium_failed_codes": (
            ([] if tts_automated_ready else ["automated_voice_browser_tts_not_ready"])
            + ([] if room_audio_ready else ["room_audio_attestation_not_pass"])
        ),
        "next_action": (
            STT_REMEDIATION_ACTION
            if not (captured_ready and diagnostic_ready)
            else (AUTOMATED_VOICE_REMEDIATION_ACTION if not tts_automated_ready else "")
        ),
        "receipt_path": ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        "browser_receipt_path": ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
        "room_audio_receipt_path": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
    }

    raw_attestation = dict(status.get("room_audio_attestation_packet") or {})
    required_check_ids = [
        check_id
        for check_id in REQUIRED_ROOM_CHECK_IDS
        if check_id in list(raw_attestation.get("required_check_ids") or [])
    ]
    attestation_ready = bool(
        raw_attestation.get("status") == "ready"
        and raw_attestation.get("manual_only") is True
        and raw_attestation.get("ci_must_not_auto_assert") is True
        and all(check_id in required_check_ids for check_id in REQUIRED_ROOM_CHECK_IDS)
    )
    attestation = {
        "status": "ready" if attestation_ready else "blocked",
        "manual_only": raw_attestation.get("manual_only") is True,
        "ci_must_not_auto_assert": raw_attestation.get("ci_must_not_auto_assert") is True,
        "required_check_ids": required_check_ids,
        "operator_command": (
            "make materialize-memorial-room-audio-gold-clean"
            if raw_attestation.get("operator_command") == "make materialize-memorial-room-audio-gold-clean"
            else ""
        ),
        "next_action": "",
        "receipt_path": ".codex-studio/published/memorial_room_audio_attestation_packet.generated.json",
    }
    # Supplied status is a test/in-process compatibility seam, not authenticated
    # current evidence. It may describe nested readiness, but it cannot promote
    # the public claim without the receipt-aggregation path.
    all_ready = False
    return {
        "status": "pass" if all_ready else "blocked",
        "current_label": (
            "Memorial public-origin gold: pass"
            if all_ready
            else "Memorial public-origin gold: blocked"
        ),
        "room_audio_receipt": "pass" if room_audio_ready else "missing_or_blocked",
        "spoken_conversation_stt": stt,
        "captured_candidate_diagnostic": diagnostic,
        "spoken_conversation_tts": tts,
        "room_audio_attestation_packet": attestation,
    }


def _attestation_packet_is_structurally_safe(attestation: dict[str, Any]) -> bool:
    required_ids = [
        str(item).strip()
        for item in _sequence(attestation.get("required_check_ids"))
        if isinstance(item, str) and str(item).strip()
    ]
    return bool(
        attestation.get("status") == "ready"
        and attestation.get("manual_only") is True
        and attestation.get("ci_must_not_auto_assert") is True
        and len(required_ids) == len(REQUIRED_ROOM_CHECK_IDS)
        and set(required_ids) == set(REQUIRED_ROOM_CHECK_IDS)
        and attestation.get("operator_command")
        == "make materialize-memorial-room-audio-gold-clean"
        and attestation.get("source_state_matches_current") is True
        and attestation.get("evidence_fresh") is True
    )


def _readiness_blocked_checks(
    *,
    stt: dict[str, Any],
    diagnostic: dict[str, Any],
    tts: dict[str, Any],
    attestation: dict[str, Any],
    room_audio_receipt: object,
    evidence_source: str,
) -> list[str]:
    blocked: list[str] = []
    if evidence_source != "receipt_aggregation":
        blocked.append("current_evidence_aggregation_required")
    stt_ready = bool(
        stt.get("status") == "pass"
        and stt.get("production_eligible") is True
        and stt.get("real_captured_fixture_status") == "captured_candidate_benchmark_pass"
    )
    if not stt_ready:
        blocked.append("real_captured_stt_fixture_ready")
    diagnostic_ready = bool(
        diagnostic.get("status") == "ready"
        and diagnostic.get("promotion_allowed") is True
        and diagnostic.get("may_update_fixture_manifest") is True
        and _failure_codes_are_empty(diagnostic.get("row_failure_codes"))
    )
    if not diagnostic_ready:
        blocked.append("captured_candidate_diagnostic_clean")
    tts_automated_ready = bool(
        tts.get("status") == "pass"
        and tts.get("direct_tts_audio_status") == "pass"
        and tts.get("conversation_turn_audio_status") == "pass"
        and tts.get("browser_audio_ready_for_ui") is True
        and _safe_nonnegative_int(tts.get("browser_play_calls")) >= 1
        and _safe_nonnegative_int(tts.get("browser_play_ended")) >= 1
    )
    if not tts_automated_ready:
        blocked.append("automated_voice_browser_tts_ready")
    if tts.get("room_audio_receipt") != "pass":
        blocked.append("room_audio_receipt_passed")
    attestation_ready = _attestation_packet_is_structurally_safe(attestation)
    if not attestation_ready or room_audio_receipt != "pass":
        blocked.append("manual_room_checks_confirmed")
    return blocked


def _manual_room_proof_is_sole_remaining_blocker(
    *,
    blocked_checks: list[str],
    stt: dict[str, Any],
    diagnostic: dict[str, Any],
    tts: dict[str, Any],
    attestation: dict[str, Any],
) -> bool:
    blocked = set(blocked_checks)
    if not blocked or not blocked.issubset(ROOM_PROOF_BLOCKED_CHECKS):
        return False
    attestation_action_safe = bool(
        _attestation_packet_is_structurally_safe(attestation)
        and attestation.get("next_action") == "collect_real_room_audio_attestation"
    )
    return bool(
        attestation_action_safe
        and stt.get("status") == "pass"
        and stt.get("production_eligible") is True
        and stt.get("real_captured_fixture_status") == "captured_candidate_benchmark_pass"
        and diagnostic.get("status") == "ready"
        and diagnostic.get("promotion_allowed") is True
        and diagnostic.get("may_update_fixture_manifest") is True
        and _failure_codes_are_empty(diagnostic.get("row_failure_codes"))
        and tts.get("status") == "pass"
        and tts.get("direct_tts_audio_status") == "pass"
        and tts.get("conversation_turn_audio_status") == "pass"
        and tts.get("browser_audio_ready_for_ui") is True
        and _safe_nonnegative_int(tts.get("browser_play_calls")) >= 1
        and _safe_nonnegative_int(tts.get("browser_play_ended")) >= 1
    )


def _next_action_surface(
    *,
    ready: bool,
    blocked_checks: list[str],
    stt: dict[str, Any],
    diagnostic: dict[str, Any],
    tts: dict[str, Any],
    attestation: dict[str, Any],
) -> dict[str, str]:
    if ready:
        return {
            "next_action": "review_realtime_conversation_in_real_room",
            "next_action_href": MANFRED_PROOF_PATH,
            "next_action_label": MANFRED_REVIEW_LABEL,
            "next_action_method": ACTION_METHOD,
        }

    manual_room_proof_only = _manual_room_proof_is_sole_remaining_blocker(
        blocked_checks=blocked_checks,
        stt=stt,
        diagnostic=diagnostic,
        tts=tts,
        attestation=attestation,
    )
    if manual_room_proof_only:
        action = str(attestation.get("next_action") or tts.get("next_action") or "collect_real_room_audio_attestation").strip()
        return {
            "next_action": action,
            "next_action_href": MANFRED_PROOF_PATH,
            "next_action_label": MANFRED_PROOF_LABEL,
            "next_action_method": ACTION_METHOD,
        }

    stt_or_evidence_blocked = bool(STT_OR_EVIDENCE_BLOCKED_CHECKS.intersection(blocked_checks))
    automated_voice_blocked = "automated_voice_browser_tts_ready" in blocked_checks
    room_only_but_unsafe = bool(
        blocked_checks and set(blocked_checks).issubset(ROOM_PROOF_BLOCKED_CHECKS)
    )
    if stt_or_evidence_blocked:
        diagnostic_action = str(
            diagnostic.get("next_action") or stt.get("next_action") or STT_REMEDIATION_ACTION
        ).strip()
    elif automated_voice_blocked:
        diagnostic_action = AUTOMATED_VOICE_REMEDIATION_ACTION
    elif room_only_but_unsafe:
        diagnostic_action = ROOM_ATTESTATION_REMEDIATION_ACTION
    else:
        diagnostic_action = AUTOMATED_VOICE_REMEDIATION_ACTION
    return {
        "next_action": diagnostic_action,
        "next_action_href": MANFRED_VOICE_GOLD_PATH,
        "next_action_label": MANFRED_VOICE_GOLD_LABEL,
        "next_action_method": ACTION_METHOD,
    }


def _operator_action_packet(
    *,
    ready: bool,
    blocked_checks: list[str],
    next_action_surface: dict[str, str],
    attestation: dict[str, Any],
    manual_room_proof_only: bool,
) -> dict[str, Any]:
    required_check_ids = (
        [
            str(item).strip()
            for item in list(attestation.get("required_check_ids") or [])
            if str(item).strip()
        ]
        if manual_room_proof_only
        else []
    )
    common = {
        "operator_action_key": MANFRED_OPERATOR_ACTION_KEY if not ready else "",
        "kind": (
            "manual_room_audio_attestation"
            if manual_room_proof_only
            else ("realtime_conversation_review" if ready else "automated_readiness_remediation")
        ),
        "next_action": str(next_action_surface.get("next_action") or ""),
        "next_action_href": str(next_action_surface.get("next_action_href") or ""),
        "next_action_label": str(next_action_surface.get("next_action_label") or ""),
        "next_action_method": str(next_action_surface.get("next_action_method") or ACTION_METHOD).lower(),
        "manual_only": manual_room_proof_only,
        "ci_must_not_auto_assert": bool(
            manual_room_proof_only and attestation.get("ci_must_not_auto_assert") is True
        ),
        "required_check_ids": required_check_ids,
        "required_check_count": len(required_check_ids),
        "blocked_checks": list(blocked_checks),
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_transcript_fields_exposed": False,
        "candidate_raw_text_fields_exposed": False,
        "raw_voice_ids_exposed": False,
    }
    if ready:
        return {
            **common,
            "status": "not_required",
            "user_action_required": False,
            "action_required_reason": "",
            "instruction": "Review the Manfred realtime conversation in a real room before widening product claims.",
            "delivery_policy": "queue_only",
            "telegram_push_allowed": False,
            "interruption_budget": "none",
        }
    if not manual_room_proof_only:
        stt_or_evidence_blocked = bool(
            STT_OR_EVIDENCE_BLOCKED_CHECKS.intersection(blocked_checks)
        )
        automated_voice_blocked = "automated_voice_browser_tts_ready" in blocked_checks
        if stt_or_evidence_blocked:
            action_required_reason = "stt_evidence_not_current_or_clean"
            instruction = (
                "Review the private ground truth through the approved local workflow, then regenerate "
                "the bound redacted STT benchmark and diagnostic evidence."
            )
            required_next_receipt = "current bound redacted STT benchmark and diagnostic evidence"
            claim_boundary = "does_not_request_manual_room_attestation_until_stt_evidence_is_current_and_clean"
        elif automated_voice_blocked:
            action_required_reason = "automated_voice_browser_tts_prerequisites_not_current_or_clean"
            instruction = (
                "Repair and rerun the automated voice roundtrip and browser playback probes before "
                "requesting manual room proof."
            )
            required_next_receipt = "current automated voice roundtrip and browser playback readiness evidence"
            claim_boundary = "does_not_request_manual_room_attestation_until_automated_voice_evidence_is_current_and_clean"
        else:
            action_required_reason = "room_attestation_packet_not_current_or_safe"
            instruction = (
                "Regenerate the current redacted room-attestation instruction packet with the CI guard "
                "and exact required checks before requesting manual room proof."
            )
            required_next_receipt = "current safe redacted room-attestation instruction packet"
            claim_boundary = "does_not_request_or_push_manual_room_attestation_without_a_current_safe_instruction_packet"
        return {
            **common,
            "status": "action_required",
            "user_action_required": True,
            "action_required_reason": action_required_reason,
            "instruction": instruction,
            "delivery_policy": "queue_only",
            "telegram_push_allowed": False,
            "interruption_budget": "none",
            "required_next_receipt": required_next_receipt,
            "claim_boundary": claim_boundary,
        }
    return {
        **common,
        "status": "action_required",
        "user_action_required": True,
        "action_required_reason": "real_room_realtime_proof_missing",
        "instruction": "Capture the manual real-room audio attestation for the Manfred spoken conversation proof. CI must not auto-assert this.",
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "interruption_budget": "action_required",
        "required_next_receipt": "consented Manfred STT/TTS realtime conversation proof",
        "claim_boundary": "does_not_prove_realtime_conversation_until_real_room_audio_and_operator_acceptance_are_recorded",
    }


def materialize_manfred_realtime_conversation_readiness(
    *,
    receipt_path: str | Path,
    generated_at: str = "",
    operator_status: dict[str, Any] | None = None,
    refresh: bool = True,
    evidence_root: str | Path = DEFAULT_EVIDENCE_ROOT,
) -> dict[str, Any]:
    if operator_status is not None:
        status = _sanitize_provided_operator_status(operator_status)
        evidence_source = "provided_operator_status"
    elif refresh:
        status = _operator_status_from_receipts(evidence_root)
        evidence_source = "receipt_aggregation"
    else:
        status = _sanitize_provided_operator_status(_default_operator_status())
        evidence_source = "conservative_default"
    stt = dict(status.get("spoken_conversation_stt") or {})
    diagnostic = dict(status.get("captured_candidate_diagnostic") or {})
    tts = dict(status.get("spoken_conversation_tts") or {})
    attestation = dict(status.get("room_audio_attestation_packet") or {})
    blocked = _readiness_blocked_checks(
        stt=stt,
        diagnostic=diagnostic,
        tts=tts,
        attestation=attestation,
        room_audio_receipt=status.get("room_audio_receipt"),
        evidence_source=evidence_source,
    )
    ready = not blocked
    manual_room_proof_only = _manual_room_proof_is_sole_remaining_blocker(
        blocked_checks=blocked,
        stt=stt,
        diagnostic=diagnostic,
        tts=tts,
        attestation=attestation,
    )
    next_action_surface = _next_action_surface(
        ready=ready,
        blocked_checks=blocked,
        stt=stt,
        diagnostic=diagnostic,
        tts=tts,
        attestation=attestation,
    )
    receipt = {
        "contract_name": "ea.manfred_realtime_conversation_readiness.v1",
        "generated_by": "ea/scripts/materialize_manfred_realtime_conversation_readiness.py",
        "status": "ready_for_realtime_conversation_review" if ready else "blocked_realtime_prerequisites",
        "generated_at": _validated_generated_at(generated_at),
        **_source_state(),
        "current_label": status.get("current_label"),
        "operator_status": status.get("status"),
        "ready_for_realtime_conversation_review": ready,
        "realtime_conversation_claim_allowed": False,
        "premium_spoken_claim_allowed": False,
        "goal_completion_claim_allowed": False,
        "blocked_checks": blocked,
        "evidence_source": evidence_source,
        "input_evidence": (
            dict(status.get("input_evidence") or {})
            if evidence_source == "receipt_aggregation"
            else {}
        ),
        "operator_action_key": "" if ready else MANFRED_OPERATOR_ACTION_KEY,
        "operator_action": _operator_action_packet(
            ready=ready,
            blocked_checks=blocked,
            next_action_surface=next_action_surface,
            attestation=attestation,
            manual_room_proof_only=manual_room_proof_only,
        ),
        "stt": stt,
        "captured_candidate_diagnostic": diagnostic,
        "tts": tts,
        "room_audio_attestation": attestation,
        "interaction_acceptance": {"ongoing_cinematic_narration_not_scene_bound": True},
        "required_live_proof_after_readiness": REQUIRED_LIVE_PROOF_AFTER_READINESS,
        "privacy": {
            "raw_private_context_exposed": False,
            "raw_transcript_fields": False,
            "candidate_raw_text_fields": False,
            "redacted_text_fields": True,
        },
        **next_action_surface,
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize Manfred realtime conversation readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--evidence-root", default=str(DEFAULT_EVIDENCE_ROOT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--no-refresh", action="store_true")
    args = parser.parse_args(argv)
    receipt = materialize_manfred_realtime_conversation_readiness(
        receipt_path=args.receipt,
        generated_at=args.generated_at,
        refresh=not args.no_refresh,
        evidence_root=args.evidence_root,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
