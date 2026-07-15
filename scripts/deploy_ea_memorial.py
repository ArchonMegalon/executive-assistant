#!/usr/bin/env python3
"""Governed, API-only deployment lane for the public Manfred memorial.

The general EA deploy script intentionally manages the complete legacy runtime.
This lane is narrower: it may start ``ea-redis`` and may recreate only
``ea-api``. A failed post-change check restores the previous API image through
the exact Compose files and working directory recorded on the prior container.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess  # nosec B404 - commands are fixed below
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

try:
    from scripts.source_state_head import source_worktree_metadata
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import source_worktree_metadata

try:
    from scripts.prepare_manfred_memorial_candidate import (
        PROPERTY_AUTHORITY_SHA256,
        PROPERTY_PRE_AUTHORITY_SHA256,
        PROPERTY_TOUR_SHA256,
        _spatial_package_sha256,
        _spatial_tree_snapshot,
        _tree_digest as _candidate_projection_tree_digest,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - direct script execution
    if exc.name not in {"scripts", "scripts.prepare_manfred_memorial_candidate"}:
        raise
    from prepare_manfred_memorial_candidate import (  # type: ignore[no-redef]
        PROPERTY_AUTHORITY_SHA256,
        PROPERTY_PRE_AUTHORITY_SHA256,
        PROPERTY_TOUR_SHA256,
        _spatial_package_sha256,
        _spatial_tree_snapshot,
        _tree_digest as _candidate_projection_tree_digest,
    )

try:
    from scripts.verify_manfred_spatial_candidate_browser import (
        validate_spatial_candidate_browser_receipt,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - direct script execution
    if exc.name not in {
        "scripts",
        "scripts.verify_manfred_spatial_candidate_browser",
    }:
        raise
    from verify_manfred_spatial_candidate_browser import (  # type: ignore[no-redef]
        validate_spatial_candidate_browser_receipt,
    )


ROOT = Path(__file__).resolve().parents[1]
MEMORIAL_COMPOSE_FILE = "docker-compose.memorial.yml"
PROJECT_NAME = "ea"
API_SERVICE = "ea-api"
REDIS_SERVICE = "ea-redis"
MEMORIAL_SLUG = "manfred"
REQUIRED_CONTROL_TOUR_SLUG = (
    "360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
)
CONTROL_TOUR_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
DEPLOYMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
IMAGE_REPOSITORY_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
DEFAULT_PUBLIC_HOSTS = ("myexternalbrain.com", "www.myexternalbrain.com")
BROWSER_ZERO_COUNT_FIELDS = (
    "automatic_provider_requests",
    "automatic_websockets",
    "external_requests",
    "failed_requests",
    "page_errors",
    "http_errors",
)
OPENAPI_EVIDENCE_FIELDS = frozenset(
    {
        "path_count",
        "operation_count",
        "schema_count",
        "security_scheme_count",
        "path_digest_sha256",
        "contract_digest_sha256",
    }
)
OPENAPI_HTTP_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
OPENAPI_RETIREMENT_POLICY_ID = "ea.openapi.safety-retirement.governed-spatial-routes.v1"
OPENAPI_RETIREMENT_ALLOWED_OPERATIONS = (
    "POST /v1/internal/governed-spatial-render/build",
    "POST /v1/internal/governed-spatial-render/compose",
)
OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID = (
    "ea.openapi.compatible-evolution.version-remote-reachability.v1"
)
OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS = ("GET /version",)
FORWARD_ONLY_ENV_KEYS = {
    "EA_MEMORIAL_IMAGE",
    "EA_SOURCE_REVISION",
    "EA_DEPLOYMENT_ID",
    "EA_DEPLOYMENT_ID_SOURCE",
    "EA_DEPLOY_PRIMARY_MODE",
    "EA_DEPLOY_ENABLED_MODES",
    "EA_DEPLOY_COMPOSE_FILES",
    "EA_DEPLOY_COMPOSE_OVERRIDES",
    "COMPOSE_PROJECT_NAME",
}
ROLLBACK_ENV_PASSTHROUGH = {
    "DOCKER_CONFIG",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SSH_AUTH_SOCK",
    "TMPDIR",
    "USER",
    "XDG_RUNTIME_DIR",
}
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024
MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES = 64 * 1024
MAX_PRIVATE_RELEASE_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_DEPLOYMENT_INPUT_BYTES = 8 * 1024 * 1024
MAX_GIT_INDEX_LIST_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_CONTENT_TYPE_CHARS = 160
MAX_VEXP_SENTINEL_STATE_BYTES = 1024 * 1024
VEXP_SENTINEL_STATE_VERSION = 6
VEXP_SUPPORTED_SENTINEL_STATE_VERSIONS = frozenset({5, 6})
VEXP_CERTIFICATION_SOAK_SECONDS = 7 * 24 * 60 * 60
VEXP_SENTINEL_FILE_MAX_AGE_SECONDS = 5 * 60
VEXP_SENTINEL_STATE_MAX_AGE_SECONDS = 75 * 60
VEXP_SENTINEL_CLOCK_SKEW_SECONDS = 60
VEXP_EFFECTIVE_ELAPSED_TOLERANCE_MS = 1
VEXP_TOKEN_COVERAGE_SCHEMA = "ea.vexp_certification_token_coverage.v1"
SAFE_VEXP_CERTIFICATION_BLOCKER_CODES = frozenset(
    {
        "daemon:swap_pressure_pending",
        "host_codex:swap_pressure_pending",
        "license:fresh_token_not_renewed",
    }
)
DEFAULT_VEXP_SENTINEL_STATE_PATH = (
    Path("~/.local/state/vexp-sentinel/state.json").expanduser()
)
RELEASE_EVIDENCE_ENV_ALLOWLIST = frozenset(
    {
        "EA_DEPLOY_BRANCH",
        "EA_DEPLOY_COMMIT_SHA",
        "EA_DEPLOY_COMPOSE_FILES",
        "EA_DEPLOY_COMPOSE_OVERRIDES",
        "EA_DEPLOY_ENABLED_MODES",
        "EA_DEPLOY_ENABLED_PROJECT_MODES",
        "EA_DEPLOY_PRIMARY_MODE",
        "EA_DEPLOY_PROJECT_MODE",
        "EA_DEPLOY_PUBLIC_ORIGIN",
        "EA_DEPLOY_PUBLIC_ORIGIN_SOURCE",
        "EA_DEPLOY_REPOSITORY",
        "EA_DEPLOY_TRACKING_BRANCH",
        "EA_DEPLOYMENT_ID",
        "EA_DEPLOYMENT_ID_SOURCE",
        "EA_HOST_PORT",
        "EA_PUBLIC_APP_BASE_URL",
        "EA_PUBLIC_ORIGIN",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PUBLIC_ORIGIN",
        "PROPERTYQUARRY_PUBLIC_BASE_URL",
        "RELEASE_LABEL",
        "TZ",
    }
)
FIXED_JSON_SCRIPT_LABELS = {
    "scripts/verify_release_authority.py": "release_authority",
    "scripts/verify_memorial_deploy_readiness.py": "memorial_deploy_readiness",
    "scripts/verify_manfred_memorial_candidate.py": "manfred_candidate_verifier",
}
SAFE_SCRIPT_ORIGIN_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SAFE_CANDIDATE_ERROR_CODES = frozenset(
    {
        "candidate_browser_accessibility_contract_failed",
        "candidate_browser_automatic_provider_work_detected",
        "candidate_browser_automatic_websocket_detected",
        "candidate_browser_desktop_layout_contract_failed",
        "candidate_browser_executable_invalid",
        "candidate_browser_executable_unavailable",
        "candidate_browser_external_request_detected",
        "candidate_browser_page_unavailable",
        "candidate_browser_performance_contract_failed",
        "candidate_browser_provider_boundary_invalid",
        "candidate_browser_runtime_error",
        "candidate_browser_runtime_unavailable",
        "candidate_browser_same_origin_http_error",
        "candidate_contribution_mode_conflict",
        "candidate_contribution_receipt_invalid",
        "candidate_contribution_receipt_missing",
        "candidate_contribution_receipt_permissions_invalid",
        "candidate_contribution_withdrawal_invalid",
        "candidate_health_timeout",
        "candidate_http_json_invalid",
        "candidate_http_response_too_large",
        "candidate_http_status_unexpected",
        "candidate_memorial_slug_mismatch",
        "candidate_memorial_alias_invalid",
        "candidate_narrator_boundary_invalid",
        "candidate_public_headers_incomplete",
        "candidate_public_manifest_private_data_exposed",
        "candidate_share_packet_private_data_exposed",
        "candidate_voice_release_boundary_invalid",
    }
)
CONTAINER_PROJECTION_DIGEST_SCRIPT = r"""
import hashlib
import json
import os
import signal
import stat
import sys
from pathlib import Path, PurePosixPath

def directory_identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )

def file_identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )

root = Path(sys.argv[1])
expected_file_count = int(sys.argv[2])
expected_projection_bytes = int(sys.argv[3])
if expected_file_count < 0 or expected_projection_bytes < 0:
    raise SystemExit(17)
maximum_entry_count = max(expected_file_count * 4 + 32, 64)
budget = {"entries": 0, "files": 0, "bytes": 0}
signal.signal(signal.SIGALRM, lambda _signum, _frame: (_ for _ in ()).throw(SystemExit(18)))
signal.alarm(20)
directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
file_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
if hasattr(os, "O_NOFOLLOW"):
    directory_flags |= os.O_NOFOLLOW
    file_flags |= os.O_NOFOLLOW
try:
    root_descriptor = os.open(root, directory_flags)
except OSError:
    raise SystemExit(10)
rows = []
try:
    root_metadata = os.fstat(root_descriptor)
    root_path_metadata = os.stat(root, follow_symlinks=False)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_path_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != 0o550
        or (root_metadata.st_dev, root_metadata.st_ino)
        != (root_path_metadata.st_dev, root_path_metadata.st_ino)
    ):
        raise SystemExit(10)

    def walk(directory_descriptor, relative):
        before = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o550
        ):
            raise SystemExit(11)
        with os.scandir(directory_descriptor) as iterator:
            entries = []
            for entry in iterator:
                budget["entries"] += 1
                if budget["entries"] > maximum_entry_count:
                    raise SystemExit(16)
                entries.append(entry)
            entries.sort(key=lambda row: row.name)
        for entry in entries:
            name = entry.name
            try:
                initial = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                raise SystemExit(14)
            projected = (*relative, name)
            if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
                try:
                    child_descriptor = os.open(
                        name,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError:
                    raise SystemExit(14)
                try:
                    opened = os.fstat(child_descriptor)
                    if (
                        directory_identity(initial) != directory_identity(opened)
                        or stat.S_IMODE(opened.st_mode) != 0o550
                    ):
                        raise SystemExit(14)
                    walk(child_descriptor, projected)
                    if directory_identity(opened) != directory_identity(
                        os.fstat(child_descriptor)
                    ):
                        raise SystemExit(14)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(initial.st_mode) or stat.S_ISLNK(initial.st_mode):
                raise SystemExit(12)
            if initial.st_nlink != 1:
                raise SystemExit(15)
            budget["files"] += 1
            budget["bytes"] += int(initial.st_size)
            if (
                budget["files"] > expected_file_count
                or budget["bytes"] > expected_projection_bytes
            ):
                raise SystemExit(16)
            mode = stat.S_IMODE(initial.st_mode)
            if mode not in {0o440, 0o444}:
                raise SystemExit(13)
            try:
                file_descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=directory_descriptor,
                )
            except OSError:
                raise SystemExit(14)
            try:
                opened = os.fstat(file_descriptor)
                if (
                    file_identity(initial) != file_identity(opened)
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                ):
                    raise SystemExit(14)
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(file_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    if size > int(opened.st_size):
                        raise SystemExit(14)
                    if file_identity(opened) != file_identity(
                        os.fstat(file_descriptor)
                    ):
                        raise SystemExit(14)
                if (
                    file_identity(opened) != file_identity(os.fstat(file_descriptor))
                    or size != int(opened.st_size)
                ):
                    raise SystemExit(14)
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
            raise SystemExit(14)

    walk(root_descriptor, ())
    final_root_metadata = os.fstat(root_descriptor)
    final_root_path_metadata = os.stat(root, follow_symlinks=False)
    if (
        directory_identity(root_metadata) != directory_identity(final_root_metadata)
        or (final_root_metadata.st_dev, final_root_metadata.st_ino)
        != (final_root_path_metadata.st_dev, final_root_path_metadata.st_ino)
    ):
        raise SystemExit(14)
finally:
    os.close(root_descriptor)
signal.alarm(0)
if (
    budget["files"] != expected_file_count
    or budget["bytes"] != expected_projection_bytes
):
    raise SystemExit(17)
encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
print(
    json.dumps(
        {
            "projection_sha256": hashlib.sha256(encoded).hexdigest(),
            "file_count": len(rows),
            "projection_bytes": sum(int(item["size_bytes"]) for item in rows),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
)
""".strip()


class DeployError(RuntimeError):
    """A fail-closed deployment or verification error."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    body: bytes
    source_revision: str = ""
    headers: Mapping[str, str] | None = None


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(  # nosec B603 - fixed executable/arguments
            list(args),
            cwd=cwd,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
        )
        if check and completed.returncode != 0:
            executable = Path(str(args[0] or "command")).name or "command"
            if executable.startswith("python") and len(args) > 1:
                executable = f"{executable}:{Path(str(args[1])).name}"
            raise DeployError(f"command_failed:{completed.returncode}:{executable}")
        return completed


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _utc_timestamp_ms(value: object) -> int | None:
    """Return exact epoch milliseconds for a bounded, timezone-aware timestamp."""

    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    parsed = parsed.astimezone(UTC)
    if parsed.microsecond % 1000:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = parsed - epoch
    return (
        delta.days * 86_400_000
        + delta.seconds * 1000
        + delta.microseconds // 1000
    )


def _utc_timestamp_from_ms(value: int) -> str:
    seconds, milliseconds = divmod(value, 1000)
    parsed = datetime.fromtimestamp(seconds, tz=UTC).replace(
        microsecond=milliseconds * 1000
    )
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _vexp_token_coverage_base(*, state_sha256: str) -> dict[str, object]:
    return {
        "contract_name": VEXP_TOKEN_COVERAGE_SCHEMA,
        "status": "fail",
        "reason": "sentinel_state_invalid",
        "issues": [],
        "state_sha256": state_sha256,
        "expected_state_version": VEXP_SENTINEL_STATE_VERSION,
        "current_state_version": VEXP_SENTINEL_STATE_VERSION,
        "supported_state_versions": sorted(VEXP_SUPPORTED_SENTINEL_STATE_VERSIONS),
        "required_window_seconds": VEXP_CERTIFICATION_SOAK_SECONDS,
        "token_coverage_safe": False,
        "promotion_authorized": False,
        "operator_action_required": True,
        "operator_guidance": [
            (
                "Restore a current owner-only supported v5 or v6 sentinel state, "
                "then rerun the governed readiness check."
            ),
            (
                "If renewal or coverage remains blocked, renew through the governed "
                "provider workflow and wait for the sentinel to prove coverage "
                "through certification_required_end_at."
            ),
            (
                "Never place credential material in a receipt, command argument, "
                "or support message."
            ),
        ],
        "credential_material_included": False,
        "secrets_included": False,
    }


def _vexp_certification_token_coverage(
    state: Mapping[str, Any],
    *,
    state_sha256: str,
    checked_at_ms: int | None = None,
    state_file_mtime_ns: int | None = None,
    required_window_seconds: int = VEXP_CERTIFICATION_SOAK_SECONDS,
) -> dict[str, object]:
    """Build a secret-free proof that a fresh token spans the certification soak."""

    evidence = _vexp_token_coverage_base(state_sha256=state_sha256)
    issues: list[str] = []
    if (
        type(required_window_seconds) is not int
        or required_window_seconds <= 0
        or required_window_seconds > 31 * 24 * 60 * 60
    ):
        evidence["issues"] = ["required_window_invalid"]
        return evidence
    evidence["required_window_seconds"] = required_window_seconds
    if SHA256_HEX_PATTERN.fullmatch(state_sha256) is None:
        issues.append("state_sha256_invalid")

    if checked_at_ms is None:
        checked_at_ms = int(time.time() * 1000)
    if type(checked_at_ms) is not int or checked_at_ms <= 0:
        evidence["issues"] = ["checked_at_invalid"]
        return evidence
    if type(state_file_mtime_ns) is not int or state_file_mtime_ns <= 0:
        issues.append("state_file_mtime_invalid")
        state_file_mtime_ms = None
    else:
        state_file_mtime_ms = state_file_mtime_ns // 1_000_000
        maximum_file_mtime_ms = (
            checked_at_ms + VEXP_SENTINEL_CLOCK_SKEW_SECONDS * 1000
        )
        minimum_file_mtime_ms = (
            checked_at_ms - VEXP_SENTINEL_FILE_MAX_AGE_SECONDS * 1000
        )
        if state_file_mtime_ms > maximum_file_mtime_ms:
            issues.append("state_file_mtime_from_future")
        if state_file_mtime_ms < minimum_file_mtime_ms:
            issues.append("state_file_mtime_stale")

    version = state.get("version")
    if type(version) is int:
        evidence["state_version"] = version
    if (
        type(version) is not int
        or version not in VEXP_SUPPORTED_SENTINEL_STATE_VERSIONS
    ):
        issues.append("state_version_invalid")

    epoch_started_ms = state.get("epoch_started_ms")
    if type(epoch_started_ms) is not int or epoch_started_ms <= 0:
        issues.append("epoch_started_ms_invalid")
        epoch_started_ms = None
    epoch_started_at_ms = _utc_timestamp_ms(state.get("epoch_started_at"))
    if epoch_started_at_ms is None:
        issues.append("epoch_started_at_invalid")
    elif epoch_started_ms is not None and epoch_started_at_ms != epoch_started_ms:
        issues.append("epoch_started_timestamp_mismatch")

    updated_at_ms = _utc_timestamp_ms(state.get("updated_at"))
    if updated_at_ms is None:
        issues.append("updated_at_invalid")
    else:
        maximum_future_ms = checked_at_ms + VEXP_SENTINEL_CLOCK_SKEW_SECONDS * 1000
        minimum_state_fresh_ms = (
            checked_at_ms - VEXP_SENTINEL_STATE_MAX_AGE_SECONDS * 1000
        )
        if updated_at_ms > maximum_future_ms:
            issues.append("sentinel_state_from_future")
        if updated_at_ms < minimum_state_fresh_ms:
            issues.append("sentinel_state_stale")

    qualification_deferred_ms: int | None = 0
    qualification_deferred_total_ms: int | None = 0
    qualification_effective_elapsed_ms: int | None = None
    qualification_earliest_completion_ms: int | None = None
    qualification_deferred_reasons: list[str] = []
    apparmor_qualification_ready: bool | None = None
    epoch_apparmor_enforced: bool | None = None
    current_resources_healthy: bool | None = None
    resource_samples_attempted: int | None = None
    resource_samples_passed: int | None = None
    if version == 6:
        qualification_deferred_ms = state.get("qualification_deferred_ms")
        if (
            type(qualification_deferred_ms) is not int
            or qualification_deferred_ms < 0
        ):
            issues.append("qualification_deferred_ms_invalid")
            qualification_deferred_ms = None

        qualification_deferred_total_ms = state.get(
            "qualification_deferred_total_ms"
        )
        if (
            type(qualification_deferred_total_ms) is not int
            or qualification_deferred_total_ms < 0
        ):
            issues.append("qualification_deferred_total_ms_invalid")
            qualification_deferred_total_ms = None
        if (
            qualification_deferred_ms is not None
            and qualification_deferred_total_ms is not None
            and qualification_deferred_ms > qualification_deferred_total_ms
        ):
            issues.append("qualification_deferred_totals_inconsistent")

        qualification_effective_elapsed_ms = state.get(
            "qualification_effective_elapsed_ms"
        )
        if (
            type(qualification_effective_elapsed_ms) is not int
            or qualification_effective_elapsed_ms < 0
        ):
            issues.append("qualification_effective_elapsed_ms_invalid")
            qualification_effective_elapsed_ms = None
        if (
            qualification_effective_elapsed_ms is not None
            and qualification_deferred_total_ms is not None
            and epoch_started_ms is not None
            and updated_at_ms is not None
        ):
            expected_effective_elapsed_ms = (
                updated_at_ms
                - epoch_started_ms
                - qualification_deferred_total_ms
            )
            if expected_effective_elapsed_ms < 0:
                issues.append("qualification_effective_elapsed_negative")
            elif (
                abs(
                    qualification_effective_elapsed_ms
                    - expected_effective_elapsed_ms
                )
                > VEXP_EFFECTIVE_ELAPSED_TOLERANCE_MS
            ):
                issues.append("qualification_effective_elapsed_inconsistent")

        qualification_earliest_completion_ms = _utc_timestamp_ms(
            state.get("qualification_earliest_completion_at")
        )
        if qualification_earliest_completion_ms is None:
            issues.append("qualification_earliest_completion_at_invalid")
        elif (
            epoch_started_ms is not None
            and qualification_deferred_total_ms is not None
            and abs(
                qualification_earliest_completion_ms
                - (
                    epoch_started_ms
                    + qualification_deferred_total_ms
                    + required_window_seconds * 1000
                )
            )
            > VEXP_EFFECTIVE_ELAPSED_TOLERANCE_MS
        ):
            issues.append("qualification_earliest_completion_inconsistent")

        deferred_reasons_value = state.get("qualification_deferred_reasons")
        if (
            not isinstance(deferred_reasons_value, list)
            or len(deferred_reasons_value) > 64
        ):
            issues.append("qualification_deferred_reasons_invalid")
        else:
            for deferred_reason in deferred_reasons_value:
                if (
                    not isinstance(deferred_reason, str)
                    or len(deferred_reason) > 128
                    or re.fullmatch(
                        r"[a-z][a-z0-9_-]{0,31}:[a-z][a-z0-9_.-]{0,95}",
                        deferred_reason,
                    )
                    is None
                ):
                    issues.append("qualification_deferred_reason_code_invalid")
                    qualification_deferred_reasons = []
                    break
                qualification_deferred_reasons.append(deferred_reason)
            if len(qualification_deferred_reasons) != len(
                set(qualification_deferred_reasons)
            ):
                issues.append("qualification_deferred_reason_code_duplicate")

        deferred_since_at_value = state.get("qualification_deferred_since_at")
        deferred_since_monotonic_ms = state.get(
            "qualification_deferred_since_monotonic_ms"
        )
        if qualification_deferred_reasons:
            deferred_since_at_ms = _utc_timestamp_ms(deferred_since_at_value)
            if deferred_since_at_ms is None:
                issues.append("qualification_deferred_since_at_invalid")
            else:
                if (
                    epoch_started_ms is not None
                    and deferred_since_at_ms < epoch_started_ms
                ):
                    issues.append("qualification_deferred_since_before_epoch")
                if updated_at_ms is not None and deferred_since_at_ms > updated_at_ms:
                    issues.append("qualification_deferred_since_after_update")
            if (
                type(deferred_since_monotonic_ms) is not int
                or deferred_since_monotonic_ms < 0
            ):
                issues.append("qualification_deferred_since_monotonic_ms_invalid")
        elif (
            deferred_since_at_value is not None
            or deferred_since_monotonic_ms is not None
        ):
            issues.append("qualification_deferred_since_without_reasons")

        apparmor_qualification_ready = state.get("apparmor_qualification_ready")
        if type(apparmor_qualification_ready) is not bool:
            issues.append("apparmor_qualification_ready_invalid")
            apparmor_qualification_ready = None
        epoch_apparmor_enforced = state.get("epoch_apparmor_enforced")
        if type(epoch_apparmor_enforced) is not bool:
            issues.append("epoch_apparmor_enforced_invalid")
            epoch_apparmor_enforced = None
        current_resources_healthy = state.get("current_resources_healthy")
        if type(current_resources_healthy) is not bool:
            issues.append("current_resources_healthy_invalid")
            current_resources_healthy = None
        if (
            apparmor_qualification_ready is True
            and epoch_apparmor_enforced is False
        ):
            issues.append("apparmor_qualification_state_inconsistent")

        sample_attempted_present = "resource_samples_attempted" in state
        sample_passed_present = "resource_samples_passed" in state
        if not (sample_attempted_present and sample_passed_present):
            issues.append("resource_sample_counts_incomplete")
        if sample_attempted_present:
            resource_samples_attempted = state.get("resource_samples_attempted")
            if (
                type(resource_samples_attempted) is not int
                or resource_samples_attempted <= 0
            ):
                issues.append("resource_samples_attempted_invalid")
                resource_samples_attempted = None
        if sample_passed_present:
            resource_samples_passed = state.get("resource_samples_passed")
            if (
                type(resource_samples_passed) is not int
                or resource_samples_passed <= 0
            ):
                issues.append("resource_samples_passed_invalid")
                resource_samples_passed = None
        if (
            resource_samples_attempted is not None
            and resource_samples_passed is not None
            and resource_samples_passed > resource_samples_attempted
        ):
            issues.append("resource_sample_counts_inconsistent")

    initial_expiration_ms = state.get("epoch_initial_fresh_exp_ms")
    if type(initial_expiration_ms) is not int or initial_expiration_ms <= 0:
        issues.append("initial_fresh_expiration_invalid")
        initial_expiration_ms = None
    observed_expiration_ms = state.get("last_observed_fresh_exp_ms")
    if type(observed_expiration_ms) is not int or observed_expiration_ms <= 0:
        issues.append("observed_fresh_expiration_invalid")
        observed_expiration_ms = None

    renewal_count = state.get("fresh_token_renewals")
    if type(renewal_count) is not int or renewal_count < 0:
        issues.append("fresh_token_renewal_count_invalid")
        renewal_count = None
    renewed_in_epoch = state.get("fresh_token_renewed_in_epoch")
    if type(renewed_in_epoch) is not bool:
        issues.append("fresh_token_renewal_flag_invalid")
        renewed_in_epoch = None
    if renewal_count is not None and renewed_in_epoch is not None:
        if renewed_in_epoch != (renewal_count > 0):
            issues.append("fresh_token_renewal_state_inconsistent")
        if initial_expiration_ms is not None and observed_expiration_ms is not None:
            if renewal_count == 0 and observed_expiration_ms != initial_expiration_ms:
                issues.append("fresh_token_expiration_advanced_without_renewal")
            if renewal_count > 0 and observed_expiration_ms <= initial_expiration_ms:
                issues.append("fresh_token_renewal_not_reflected_in_expiration")

    last_license_value = state.get("last_license")
    last_license = (
        dict(last_license_value) if isinstance(last_license_value, dict) else None
    )
    if last_license is None:
        issues.append("last_license_invalid")
    else:
        last_expiration_ms = last_license.get("fresh_expiration_ms")
        if type(last_expiration_ms) is not int or last_expiration_ms <= 0:
            issues.append("last_license_fresh_expiration_invalid")
        elif (
            observed_expiration_ms is not None
            and last_expiration_ms != observed_expiration_ms
        ):
            issues.append("last_license_fresh_expiration_mismatch")
        last_expiration_at_ms = _utc_timestamp_ms(
            last_license.get("fresh_expiration_at")
        )
        if last_expiration_at_ms is None:
            issues.append("last_license_fresh_expiration_at_invalid")
        elif (
            type(last_expiration_ms) is int
            and last_expiration_at_ms != last_expiration_ms
        ):
            issues.append("last_license_fresh_expiration_timestamp_mismatch")
        last_renewed = last_license.get("renewed")
        if type(last_renewed) is not bool:
            issues.append("last_license_renewed_flag_invalid")
        elif last_renewed and renewed_in_epoch is not True:
            issues.append("last_license_renewal_state_inconsistent")

    phase = state.get("qualification_phase")
    if not isinstance(phase, str) or phase not in {"enforced_soak", "qualified"}:
        issues.append("qualification_phase_invalid")
    qualified_at_value = state.get("qualified_at")
    qualified_at_ms: int | None = None
    if phase == "enforced_soak":
        if qualified_at_value is not None:
            issues.append("qualified_at_unexpected")
    elif phase == "qualified":
        qualified_at_ms = _utc_timestamp_ms(qualified_at_value)
        if qualified_at_ms is None:
            issues.append("qualified_at_invalid")

    blockers_value = state.get("certification_blockers")
    blockers: list[str] = []
    if not isinstance(blockers_value, list) or len(blockers_value) > 64:
        issues.append("certification_blockers_invalid")
    else:
        for blocker in blockers_value:
            if (
                not isinstance(blocker, str)
                or len(blocker) > 128
                or re.fullmatch(
                    r"[a-z][a-z0-9_-]{0,31}:[a-z][a-z0-9_.-]{0,95}",
                    blocker,
                )
                is None
            ):
                issues.append("certification_blocker_code_invalid")
                blockers = []
                break
            blockers.append(blocker)
        if len(blockers) != len(set(blockers)):
            issues.append("certification_blocker_code_duplicate")
        if (
            renewed_in_epoch is True
            and "license:fresh_token_not_renewed" in blockers
        ):
            issues.append("license_renewal_blocker_state_inconsistent")
        if phase == "qualified" and blockers:
            issues.append("qualified_state_has_certification_blockers")

    if epoch_started_ms is not None:
        required_end_ms = (
            epoch_started_ms
            + qualification_deferred_total_ms
            + required_window_seconds * 1000
            if qualification_deferred_total_ms is not None
            else None
        )
        if checked_at_ms + VEXP_SENTINEL_CLOCK_SKEW_SECONDS * 1000 < epoch_started_ms:
            issues.append("epoch_started_in_future")
        if updated_at_ms is not None and updated_at_ms < epoch_started_ms:
            issues.append("sentinel_updated_before_epoch")
        if (
            initial_expiration_ms is not None
            and initial_expiration_ms <= epoch_started_ms
        ):
            issues.append("initial_fresh_expiration_before_epoch")
        if (
            observed_expiration_ms is not None
            and observed_expiration_ms <= epoch_started_ms
        ):
            issues.append("observed_fresh_expiration_before_epoch")
        if (
            qualified_at_ms is not None
            and required_end_ms is not None
            and qualified_at_ms < required_end_ms
        ):
            issues.append("qualification_completed_before_required_window")
        if (
            qualified_at_ms is not None
            and qualified_at_ms
            > checked_at_ms + VEXP_SENTINEL_CLOCK_SKEW_SECONDS * 1000
        ):
            issues.append("qualification_completed_in_future")
        if (
            qualified_at_ms is not None
            and updated_at_ms is not None
            and updated_at_ms < qualified_at_ms
        ):
            issues.append("sentinel_updated_before_qualification")
    else:
        required_end_ms = None

    if issues:
        evidence["issues"] = sorted(set(issues))
        return evidence

    assert epoch_started_ms is not None
    assert required_end_ms is not None
    assert observed_expiration_ms is not None
    assert renewal_count is not None
    assert renewed_in_epoch is not None
    assert state_file_mtime_ms is not None
    assert qualification_deferred_total_ms is not None
    margin_ms = observed_expiration_ms - required_end_ms
    coverage_sufficient = margin_ms >= 0
    token_current = observed_expiration_ms > checked_at_ms
    renewal_observed = renewed_in_epoch and renewal_count > 0
    license_blockers = [
        blocker for blocker in blockers if blocker.startswith("license:")
    ]
    projected_blockers = [
        blocker
        for blocker in blockers
        if blocker in SAFE_VEXP_CERTIFICATION_BLOCKER_CODES
    ]
    projected_deferred_reasons = [
        reason
        for reason in qualification_deferred_reasons
        if reason in SAFE_VEXP_CERTIFICATION_BLOCKER_CODES
    ]
    gate_issues: list[str] = []
    if not coverage_sufficient:
        gate_issues.append("fresh_token_coverage_ends_before_certification_window")
    if not token_current:
        gate_issues.append("fresh_token_expired")
    if not renewal_observed:
        gate_issues.append("fresh_token_renewal_not_observed_in_epoch")
    if license_blockers:
        gate_issues.append("license_certification_blocker_present")
    if version == 6:
        if qualification_deferred_reasons:
            gate_issues.append("qualification_currently_deferred")
        if epoch_apparmor_enforced is not True:
            gate_issues.append("apparmor_not_enforced_in_epoch")
        if apparmor_qualification_ready is not True:
            gate_issues.append("apparmor_qualification_not_ready")
        if current_resources_healthy is not True:
            gate_issues.append("current_resources_unhealthy")

    evidence.update(
        {
            "checked_at": _utc_timestamp_from_ms(checked_at_ms),
            "state_file_mtime": _utc_timestamp_from_ms(state_file_mtime_ms),
            "state_file_age_seconds": max(
                checked_at_ms - state_file_mtime_ms, 0
            )
            / 1000,
            "epoch_started_at": _utc_timestamp_from_ms(epoch_started_ms),
            "epoch_started_ms": epoch_started_ms,
            "certification_required_end_at": _utc_timestamp_from_ms(required_end_ms),
            "certification_required_end_ms": required_end_ms,
            "qualification_deferred_ms": qualification_deferred_ms,
            "qualification_deferred_total_ms": qualification_deferred_total_ms,
            "qualification_effective_elapsed_ms": (
                qualification_effective_elapsed_ms if version == 6 else None
            ),
            "qualification_earliest_completion_at": (
                _utc_timestamp_from_ms(qualification_earliest_completion_ms)
                if qualification_earliest_completion_ms is not None
                else None
            ),
            "qualification_deferred_reasons": projected_deferred_reasons,
            "qualification_deferred_reason_count": len(
                qualification_deferred_reasons
            ),
            "qualification_deferred_reasons_sha256": _canonical_json_sha256(
                sorted(qualification_deferred_reasons)
            ),
            "unprojected_qualification_deferred_reason_count": (
                len(qualification_deferred_reasons)
                - len(projected_deferred_reasons)
            ),
            "apparmor_qualification_ready": apparmor_qualification_ready,
            "epoch_apparmor_enforced": epoch_apparmor_enforced,
            "current_resources_healthy": current_resources_healthy,
            "resource_samples_attempted": resource_samples_attempted,
            "resource_samples_passed": resource_samples_passed,
            "fresh_token_expiration_at": _utc_timestamp_from_ms(
                observed_expiration_ms
            ),
            "fresh_token_expiration_ms": observed_expiration_ms,
            "coverage_margin_seconds": max(margin_ms, 0) / 1000,
            "coverage_shortfall_seconds": max(-margin_ms, 0) / 1000,
            "fresh_token_renewal_observed": renewal_observed,
            "fresh_token_renewal_count": renewal_count,
            "qualification_phase": phase,
            "qualified_at": (
                _utc_timestamp_from_ms(qualified_at_ms)
                if qualified_at_ms is not None
                else None
            ),
            "certification_blockers": projected_blockers,
            "certification_blocker_count": len(blockers),
            "certification_blockers_sha256": _canonical_json_sha256(
                sorted(blockers)
            ),
            "unprojected_certification_blocker_count": (
                len(blockers) - len(projected_blockers)
            ),
            "issues": gate_issues,
        }
    )
    if not gate_issues:
        evidence.update(
            {
                "status": "pass",
                "reason": "fresh_token_covers_certification_window",
                "token_coverage_safe": True,
                "operator_action_required": False,
                "operator_guidance": [],
            }
        )
    elif not coverage_sufficient:
        evidence["reason"] = "fresh_token_coverage_insufficient"
    elif not token_current:
        evidence["reason"] = "fresh_token_expired"
    elif not renewal_observed:
        evidence["reason"] = "fresh_token_renewal_required"
    elif license_blockers:
        evidence["reason"] = "license_certification_blocked"
    else:
        evidence["reason"] = "sentinel_qualification_preconditions_not_ready"
    if gate_issues:
        guidance: list[str] = []
        if any(
            issue
            in {
                "fresh_token_coverage_ends_before_certification_window",
                "fresh_token_expired",
                "fresh_token_renewal_not_observed_in_epoch",
                "license_certification_blocker_present",
            }
            for issue in gate_issues
        ):
            guidance.extend(
                [
                    (
                        "Renew the vexp license token through the governed provider "
                        "workflow; do not copy or expose credential material."
                    ),
                    (
                        "Wait for the sentinel to record the in-epoch renewal, clear "
                        "all license blockers, and prove coverage through "
                        "certification_required_end_at before retrying promotion."
                    ),
                ]
            )
        if any(
            issue
            in {
                "apparmor_not_enforced_in_epoch",
                "apparmor_qualification_not_ready",
                "current_resources_unhealthy",
                "qualification_currently_deferred",
            }
            for issue in gate_issues
        ):
            guidance.append(
                "Restore enforced AppArmor and healthy resource qualification, then "
                "wait for a current v6 sentinel sample before retrying promotion."
            )
        evidence["operator_guidance"] = guidance
    return evidence


def _read_trusted_vexp_sentinel_state(
    path: Path,
) -> tuple[dict[str, Any], dict[str, object]]:
    """Read the private sentinel state once from a verified, single-link file."""

    candidate = path.expanduser()
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise DeployError("vexp_sentinel_state_path_invalid")
    parent = candidate.parent
    try:
        parent_before = parent.lstat()
    except OSError as exc:
        raise DeployError("vexp_sentinel_state_parent_unavailable") from exc
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or stat.S_ISLNK(parent_before.st_mode)
        or parent_before.st_uid != os.geteuid()
        or stat.S_IMODE(parent_before.st_mode) != 0o700
    ):
        raise DeployError("vexp_sentinel_state_parent_untrusted")

    directory_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    try:
        directory_descriptor = os.open(parent, directory_flags)
    except OSError as exc:
        raise DeployError("vexp_sentinel_state_parent_unavailable") from exc
    try:
        parent_opened = os.fstat(directory_descriptor)
    except OSError as exc:
        os.close(directory_descriptor)
        raise DeployError("vexp_sentinel_state_parent_unavailable") from exc
    parent_identity = (
        parent_opened.st_dev,
        parent_opened.st_ino,
        parent_opened.st_mode,
        parent_opened.st_uid,
    )
    if (
        not stat.S_ISDIR(parent_opened.st_mode)
        or parent_opened.st_uid != os.geteuid()
        or stat.S_IMODE(parent_opened.st_mode) != 0o700
        or (parent_before.st_dev, parent_before.st_ino)
        != (parent_opened.st_dev, parent_opened.st_ino)
    ):
        os.close(directory_descriptor)
        raise DeployError("vexp_sentinel_state_parent_untrusted")

    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(candidate.name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        os.close(directory_descriptor)
        raise DeployError("vexp_sentinel_state_unavailable") from exc

    def identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_VEXP_SENTINEL_STATE_BYTES
        ):
            raise DeployError("vexp_sentinel_state_file_untrusted")
        initial_identity = identity(before)
        payload = bytearray()
        while True:
            chunk = os.read(descriptor, min(64 * 1024, before.st_size + 1))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_VEXP_SENTINEL_STATE_BYTES:
                raise DeployError("vexp_sentinel_state_file_too_large")
        after = os.fstat(descriptor)
        try:
            path_after = os.stat(
                candidate.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            parent_path_after = parent.lstat()
        except OSError as exc:
            raise DeployError("vexp_sentinel_state_path_changed") from exc
        if (
            identity(after) != initial_identity
            or identity(path_after) != initial_identity
            or len(payload) != before.st_size
            or stat.S_ISLNK(path_after.st_mode)
            or (
                parent_path_after.st_dev,
                parent_path_after.st_ino,
                parent_path_after.st_mode,
                parent_path_after.st_uid,
            )
            != parent_identity
        ):
            raise DeployError("vexp_sentinel_state_changed_during_read")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_descriptor)

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, value in pairs:
            if key in decoded:
                raise ValueError("duplicate_key")
            decoded[key] = value
        return decoded

    try:
        decoded_payload = bytes(payload).decode("utf-8", errors="strict")
        state = json.loads(
            decoded_payload,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise DeployError("vexp_sentinel_state_json_invalid") from exc
    if not isinstance(state, dict):
        raise DeployError("vexp_sentinel_state_json_invalid")
    return dict(state), {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "mode": "0600",
        "owner_uid": before.st_uid,
        "link_count": before.st_nlink,
        "mtime_ns": before.st_mtime_ns,
        "trusted_private_file": True,
    }


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if (
            len(normalized_value) >= 2
            and normalized_value[0] == normalized_value[-1]
            and normalized_value[0] in {"'", '"'}
        ):
            normalized_value = normalized_value[1:-1]
        if normalized_key:
            values[normalized_key] = normalized_value
    return values


def _first_nonempty(*values: object) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _safe_deployment_id(env: Mapping[str, str]) -> str:
    deployment_id = _first_nonempty(
        env.get("EA_DEPLOYMENT_ID"),
        env.get("DEPLOYMENT_ID"),
        env.get("RENDER_GIT_COMMIT"),
    )
    if not deployment_id:
        raise DeployError("explicit_deployment_id_required")
    if deployment_id.startswith("local-") or not DEPLOYMENT_ID_PATTERN.fullmatch(
        deployment_id
    ):
        raise DeployError("explicit_deployment_id_invalid")
    return deployment_id


def _safe_rollback_tag(deployment_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", deployment_id.lower()).strip("-.")
    normalized = normalized[:96] or "unknown"
    return f"ea-runtime:memorial-rollback-{normalized}"


def _safe_tagged_image_reference(value: str, *, reason: str) -> str:
    reference = str(value or "").strip()
    if (
        not reference
        or len(reference) > 255
        or any(character.isspace() or ord(character) < 32 for character in reference)
        or "://" in reference
        or "@" in reference
        or reference.startswith("sha256:")
        or ":" not in reference.rsplit("/", 1)[-1]
    ):
        raise DeployError(reason)
    repository, tag = reference.rsplit(":", 1)
    if (
        not IMAGE_REPOSITORY_PATTERN.fullmatch(repository)
        or not IMAGE_TAG_PATTERN.fullmatch(tag)
        or ".." in repository
        or "//" in repository
    ):
        raise DeployError(reason)
    return reference


def _safe_candidate_image_reference(value: str, *, source_revision: str) -> str:
    reference = str(value or "").strip()
    digest_match = re.fullmatch(
        r"([a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
        r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)"
        r"@sha256:([0-9a-f]{64})",
        reference,
    )
    if digest_match:
        return reference
    tagged = _safe_tagged_image_reference(
        reference, reason="memorial_image_reference_invalid"
    )
    tag = tagged.rsplit(":", 1)[1]
    if source_revision not in tag and source_revision[:12] not in tag:
        raise DeployError("memorial_image_not_revision_bound")
    return tagged


def _require_durable_release_root(root: Path) -> None:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise DeployError("release_root_missing")
    for temporary_root in (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm")):
        if resolved == temporary_root or temporary_root in resolved.parents:
            raise DeployError("release_root_not_durable")


def _mount_identities(inspection: Mapping[str, Any]) -> list[dict[str, object]]:
    identities: list[dict[str, object]] = []
    for raw_mount in list(inspection.get("Mounts") or []):
        if not isinstance(raw_mount, dict):
            continue
        mount_type = str(raw_mount.get("Type") or "")
        source = str(
            (
                raw_mount.get("Name")
                if mount_type == "volume"
                else raw_mount.get("Source")
            )
            or ""
        )
        identities.append(
            {
                "type": mount_type,
                "source": source,
                "destination": str(raw_mount.get("Destination") or ""),
                "read_write": bool(raw_mount.get("RW")),
            }
        )
    return sorted(
        identities,
        key=lambda item: (
            str(item["destination"]),
            str(item["type"]),
            str(item["source"]),
            bool(item["read_write"]),
        ),
    )


def _identity_digest(identities: Sequence[Mapping[str, object]]) -> str:
    encoded = json.dumps(
        list(identities), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_environment(entries: Sequence[object]) -> list[str]:
    environment: dict[str, str] = {}
    for raw_entry in entries:
        if (
            not isinstance(raw_entry, str)
            or "\x00" in raw_entry
            or "=" not in raw_entry
        ):
            raise DeployError("container_environment_invalid")
        name, value = raw_entry.split("=", 1)
        if not name or "\x00" in name:
            raise DeployError("container_environment_invalid")
        environment[name] = value
    return [f"{name}={environment[name]}" for name in sorted(environment)]


def _environment_identity(entries: Sequence[object]) -> dict[str, object]:
    normalized = _normalized_environment(entries)
    return {
        "environment_sha256": hashlib.sha256(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "environment_count": len(normalized),
    }


def _normalized_command(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise DeployError("container_process_config_invalid")


def _compose_runtime_command(value: object) -> list[str]:
    """Normalize Compose-rendered process fields to Docker runtime values."""

    return [item.replace("$$", "$") for item in _normalized_command(value)]


def _process_config_identity(config: Mapping[str, Any]) -> str:
    process = {
        "command": _normalized_command(config.get("Cmd")),
        "entrypoint": _normalized_command(config.get("Entrypoint")),
        "user": str(config.get("User") or ""),
    }
    return hashlib.sha256(
        json.dumps(process, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _container_runtime_config_digests(
    inspection: Mapping[str, Any],
) -> dict[str, object]:
    config = dict(inspection.get("Config") or {})
    return {
        **_environment_identity(list(config.get("Env") or [])),
        "process_config_sha256": _process_config_identity(config),
    }


def _has_exact_zero_browser_counts(payload: Mapping[str, Any]) -> bool:
    return all(
        type(payload.get(field)) is int and payload[field] == 0
        for field in BROWSER_ZERO_COUNT_FIELDS
    )


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fixed_json_script_failure_evidence(
    *,
    script: str,
    origin: str,
    completed: subprocess.CompletedProcess[str],
) -> dict[str, object]:
    script_label = FIXED_JSON_SCRIPT_LABELS.get(script)
    if not script_label:
        raise DeployError("fixed_json_script_not_allowlisted")
    normalized_origin = str(origin or "").strip().lower()
    if not SAFE_SCRIPT_ORIGIN_PATTERN.fullmatch(normalized_origin):
        raise DeployError("fixed_json_script_origin_invalid")

    raw_stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    encoded_stdout: bytes | None = (
        raw_stdout.encode("utf-8", errors="replace")
        if len(raw_stdout) <= MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES
        else None
    )
    stdout_within_parse_limit = encoded_stdout is not None and (
        len(encoded_stdout) <= MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES
    )
    error_code = "fixed_json_script_failed"
    if stdout_within_parse_limit:
        try:
            payload = json.loads(raw_stdout)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and script_label == "manfred_candidate_verifier":
            candidate = str(payload.get("error") or "").split(":", 1)[0].strip()
            if candidate in SAFE_CANDIDATE_ERROR_CODES:
                error_code = candidate

    return_code = int(completed.returncode)
    return {
        "script": script_label,
        "origin": normalized_origin,
        "return_code": (return_code if -255 <= return_code <= 255 else 256),
        "error_code": error_code,
        "stdout_bytes": (
            len(encoded_stdout or b"")
            if stdout_within_parse_limit
            else MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES + 1
        ),
        "stdout_size_capped": not stdout_within_parse_limit,
    }


def _default_http_get(url: str, timeout_seconds: float) -> HttpResponse:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "User-Agent": "EA-Memorial-Scoped-Deploy/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_HTTP_BODY_BYTES + 1)
            if len(body) > MAX_HTTP_BODY_BYTES:
                raise DeployError(f"http_body_too_large:{url}")
            return HttpResponse(
                status=int(getattr(response, "status", 200) or 200),
                content_type=str(response.headers.get("Content-Type") or ""),
                body=body,
                source_revision=str(
                    response.headers.get("X-EA-Source-Revision") or ""
                ).strip(),
                headers={
                    name: str(response.headers.get(name) or "").strip()
                    for name in (
                        "Location",
                        "Cache-Control",
                        "Referrer-Policy",
                        "X-Content-Type-Options",
                        "X-Robots-Tag",
                    )
                },
            )
    except urllib.error.HTTPError as exc:
        raise DeployError(f"http_status_invalid:{url}:{int(exc.code or 0)}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise DeployError(f"http_probe_failed:{url}:{type(exc).__name__}") from exc


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        del req, fp, code, msg, headers, newurl
        return None


def _default_http_no_redirect(
    url: str,
    timeout_seconds: float,
    method: str,
) -> HttpResponse:
    if method not in {"GET", "HEAD"}:
        raise DeployError("http_no_redirect_method_invalid")
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "text/html,*/*;q=0.1",
            "User-Agent": "EA-Memorial-Scoped-Deploy/1.0",
        },
    )
    response: Any
    try:
        response = urllib.request.build_opener(_NoRedirectHandler()).open(
            request,
            timeout=timeout_seconds,
        )
    except urllib.error.HTTPError as exc:
        if int(exc.code or 0) not in {301, 302, 303, 307, 308}:
            raise DeployError(
                f"http_status_invalid:{url}:{int(exc.code or 0)}"
            ) from exc
        response = exc
    except (OSError, urllib.error.URLError) as exc:
        raise DeployError(f"http_probe_failed:{url}:{type(exc).__name__}") from exc
    try:
        body = response.read(MAX_HTTP_BODY_BYTES + 1)
        if len(body) > MAX_HTTP_BODY_BYTES:
            raise DeployError(f"http_body_too_large:{url}")
        return HttpResponse(
            status=int(getattr(response, "status", 0) or response.getcode() or 0),
            content_type=str(response.headers.get("Content-Type") or ""),
            body=body,
            source_revision=str(
                response.headers.get("X-EA-Source-Revision") or ""
            ).strip(),
            headers={
                name: str(response.headers.get(name) or "").strip()
                for name in (
                    "Location",
                    "Cache-Control",
                    "Referrer-Policy",
                    "X-Content-Type-Options",
                    "X-Robots-Tag",
                )
            },
        )
    finally:
        response.close()


def _validate_public_origin(value: str, *, allowed_hosts: Sequence[str]) -> str:
    origin = str(value or "").strip().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise DeployError("public_origin_invalid") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise DeployError("public_origin_invalid")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port not in {None, 443}
    ):
        raise DeployError("public_origin_invalid")
    hostname = parsed.hostname.lower()
    normalized_hosts = {
        str(item or "").strip().lower().rstrip(".")
        for item in allowed_hosts
        if str(item or "").strip()
    }
    if not normalized_hosts or hostname.rstrip(".") not in normalized_hosts:
        raise DeployError("public_origin_host_not_approved")
    return origin


def _json_object(raw: str, *, reason: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise DeployError(reason) from exc
    if not isinstance(payload, dict):
        raise DeployError(reason)
    return payload


def _resolve_openapi_ref(document: Mapping[str, Any], ref: str) -> object:
    if not ref.startswith("#/"):
        return None
    current: object = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise DeployError("openapi_ref_invalid")
        current = current[part]
    return current


def _canonical_openapi_value(
    value: object,
    *,
    document: Mapping[str, Any],
    seen_refs: frozenset[str] = frozenset(),
) -> object:
    if isinstance(value, dict):
        ref = str(value.get("$ref") or "")
        canonical: dict[str, object] = {}
        for key in sorted(value):
            if key == "$ref":
                continue
            canonical[str(key)] = _canonical_openapi_value(
                value[key], document=document, seen_refs=seen_refs
            )
        if ref:
            canonical["$ref"] = ref
            if ref not in seen_refs:
                canonical["$resolved"] = _canonical_openapi_value(
                    _resolve_openapi_ref(document, ref),
                    document=document,
                    seen_refs=seen_refs.union({ref}),
                )
        return canonical
    if isinstance(value, list):
        return [
            _canonical_openapi_value(item, document=document, seen_refs=seen_refs)
            for item in value
        ]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise DeployError("openapi_value_invalid")


def _collect_referenced_openapi_schemas(
    value: object,
    *,
    document: Mapping[str, Any],
    names: set[str],
    visited_refs: set[str],
) -> None:
    if isinstance(value, dict):
        ref = str(value.get("$ref") or "")
        if ref and ref not in visited_refs:
            visited_refs.add(ref)
            prefix = "#/components/schemas/"
            if ref.startswith(prefix):
                names.add(
                    ref.removeprefix(prefix).replace("~1", "/").replace("~0", "~")
                )
            _collect_referenced_openapi_schemas(
                _resolve_openapi_ref(document, ref),
                document=document,
                names=names,
                visited_refs=visited_refs,
            )
        for item in value.values():
            _collect_referenced_openapi_schemas(
                item,
                document=document,
                names=names,
                visited_refs=visited_refs,
            )
    elif isinstance(value, list):
        for item in value:
            _collect_referenced_openapi_schemas(
                item,
                document=document,
                names=names,
                visited_refs=visited_refs,
            )


def _canonical_openapi_contract(document: Mapping[str, Any]) -> dict[str, Any]:
    paths_value = document.get("paths")
    paths_payload = dict(paths_value) if isinstance(paths_value, dict) else {}
    components_value = document.get("components")
    components = dict(components_value) if isinstance(components_value, dict) else {}
    schemas_value = components.get("schemas")
    schemas = dict(schemas_value) if isinstance(schemas_value, dict) else {}
    security_value = components.get("securitySchemes")
    security_schemes = dict(security_value) if isinstance(security_value, dict) else {}
    root_security = document.get("security", [])
    operations: dict[str, object] = {}
    referenced_schema_names: set[str] = set()
    referenced_security_names: set[str] = set()
    for path, raw_path_item in sorted(paths_payload.items()):
        if not str(path).startswith("/") or not isinstance(raw_path_item, dict):
            raise DeployError("openapi_paths_invalid")
        path_parameters = list(raw_path_item.get("parameters") or [])
        for method, raw_operation in sorted(raw_path_item.items()):
            normalized_method = str(method).lower()
            if normalized_method not in OPENAPI_HTTP_METHODS:
                continue
            if not isinstance(raw_operation, dict):
                raise DeployError("openapi_operation_invalid")
            effective_security = (
                raw_operation["security"]
                if "security" in raw_operation
                else root_security
            )
            for requirement in list(effective_security or []):
                if not isinstance(requirement, dict):
                    raise DeployError("openapi_security_invalid")
                referenced_security_names.update(str(name) for name in requirement)
            parameters = path_parameters + list(raw_operation.get("parameters") or [])
            canonical_parameters = [
                _canonical_openapi_value(item, document=document) for item in parameters
            ]
            canonical_parameters.sort(
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            )
            contract_fields = {
                "security": effective_security,
                "parameters": parameters,
                "requestBody": raw_operation.get("requestBody"),
                "responses": raw_operation.get("responses", {}),
            }
            _collect_referenced_openapi_schemas(
                contract_fields,
                document=document,
                names=referenced_schema_names,
                visited_refs=set(),
            )
            operations[f"{normalized_method.upper()} {path}"] = {
                "security": _canonical_openapi_value(
                    effective_security, document=document
                ),
                "parameters": canonical_parameters,
                "requestBody": _canonical_openapi_value(
                    raw_operation.get("requestBody"), document=document
                ),
                "responses": _canonical_openapi_value(
                    raw_operation.get("responses", {}), document=document
                ),
            }
    if not operations:
        raise DeployError("openapi_operations_missing")
    if referenced_schema_names - set(schemas) or referenced_security_names - set(
        security_schemes
    ):
        raise DeployError("openapi_component_missing")
    return {
        "operations": operations,
        "schemas": {
            name: _canonical_openapi_value(schemas[name], document=document)
            for name in sorted(referenced_schema_names)
        },
        "security_schemes": {
            name: _canonical_openapi_value(security_schemes[name], document=document)
            for name in sorted(referenced_security_names)
        },
    }


def _openapi_control_evidence(
    *, contract: Mapping[str, Any], probe: Mapping[str, Any]
) -> dict[str, Any]:
    operations = dict(contract.get("operations") or {})
    schemas = dict(contract.get("schemas") or {})
    security_schemes = dict(contract.get("security_schemes") or {})
    paths = sorted({key.split(" ", 1)[1] for key in operations})
    encoded_paths = json.dumps(paths, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    encoded_contract = json.dumps(
        contract,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "paths": paths,
        "path_count": len(paths),
        "operation_count": len(operations),
        "schema_count": len(schemas),
        "security_scheme_count": len(security_schemes),
        "path_set_sha256": hashlib.sha256(encoded_paths).hexdigest(),
        "contract_sha256": hashlib.sha256(encoded_contract).hexdigest(),
        "probe": dict(probe),
    }


class MemorialDeployLane:
    def __init__(
        self,
        *,
        root: Path = ROOT,
        env: Mapping[str, str] | None = None,
        runner: Runner | None = None,
        http_get: Callable[[str, float], HttpResponse] = _default_http_get,
        http_no_redirect: Callable[
            [str, float, str], HttpResponse
        ] = _default_http_no_redirect,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 90.0,
        poll_seconds: float = 2.0,
        request_timeout_seconds: float = 10.0,
        receipt_dir: Path | None = None,
        global_lock_path: Path | None = None,
        vexp_sentinel_state_path: Path | None = None,
        durable_root_check: Callable[[Path], None] = _require_durable_release_root,
    ) -> None:
        self.root = root.resolve()
        self.env = dict(os.environ if env is None else env)
        self.runner = runner or SubprocessRunner()
        self.http_get = http_get
        self.http_no_redirect = http_no_redirect
        self.sleep = sleep
        self.monotonic = monotonic
        self.wait_seconds = max(float(wait_seconds), 0.0)
        self.poll_seconds = max(float(poll_seconds), 0.05)
        self.request_timeout_seconds = max(float(request_timeout_seconds), 0.1)
        self.durable_root_check = durable_root_check
        self.env_file_values = _parse_env_file(self.root / ".env")
        self.deployment_id = _safe_deployment_id(self.env)
        self.memorial_image_reference = str(
            self.env.get("EA_MEMORIAL_IMAGE") or ""
        ).strip()
        self.candidate_receipt_value = str(
            self.env.get("EA_MEMORIAL_CANDIDATE_RECEIPT") or ""
        ).strip()
        self.control_tour_slug = str(
            self.env.get("EA_MEMORIAL_CONTROL_TOUR_SLUG") or ""
        ).strip()
        if self.control_tour_slug and not CONTROL_TOUR_SLUG_PATTERN.fullmatch(
            self.control_tour_slug
        ):
            raise DeployError("memorial_control_tour_slug_invalid")
        configured_hosts = _first_nonempty(
            self.env.get("EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST"),
            self.env_file_values.get("EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST"),
            ",".join(DEFAULT_PUBLIC_HOSTS),
        )
        self.allowed_public_hosts = tuple(
            item.strip().lower().rstrip(".")
            for item in configured_hosts.split(",")
            if item.strip()
        )
        configured_receipt_dir = _first_nonempty(
            self.env.get("EA_MEMORIAL_DEPLOY_RECEIPT_DIR"),
            self.env_file_values.get("EA_MEMORIAL_DEPLOY_RECEIPT_DIR"),
        )
        self.receipt_dir = (
            receipt_dir.resolve()
            if receipt_dir is not None
            else (
                Path(configured_receipt_dir).expanduser()
                if configured_receipt_dir
                else self.root / ".runtime" / "deployments" / "memorial"
            )
        )
        if not self.receipt_dir.is_absolute():
            self.receipt_dir = self.root / self.receipt_dir
        self.receipt_dir = self.receipt_dir.resolve()
        self.receipt_path = self.receipt_dir / f"{self.deployment_id}.json"
        self.lock_path = self.receipt_dir / f"{self.deployment_id}.lock"
        self.global_lock_path = (
            global_lock_path.resolve()
            if global_lock_path is not None
            else Path("/run/lock/ea-memorial-ea-api.lock")
        )
        if not self.global_lock_path.is_absolute():
            raise DeployError("global_lock_path_not_absolute")
        self.vexp_sentinel_state_path = (
            vexp_sentinel_state_path.expanduser()
            if vexp_sentinel_state_path is not None
            else DEFAULT_VEXP_SENTINEL_STATE_PATH
        )
        if (
            not self.vexp_sentinel_state_path.is_absolute()
            or ".." in self.vexp_sentinel_state_path.parts
        ):
            raise DeployError("vexp_sentinel_state_path_invalid")
        self._lock_handle: Any | None = None
        self._global_lock_handle: Any | None = None
        self.compose_bin: tuple[str, ...] = ()
        self.target_compose_files: tuple[str, ...] = ()
        self.release_env = self._release_env()
        self.receipt: dict[str, Any] = {
            "contract_name": "ea.memorial_scoped_deploy_receipt.v1",
            "deployment_id": self.deployment_id,
            "project_name": PROJECT_NAME,
            "service_scope": [API_SERVICE, REDIS_SERVICE],
            "api_mutation_scope": [API_SERVICE],
            "target_compose_files": [],
            "rollback_compose_files": [],
            "started_at": _utc_now(),
            "status": "preflight",
            "rollback": {"status": "not_required"},
            "checks": [],
        }

    def _release_env(self) -> dict[str, str]:
        env = dict(self.env)
        env.update(
            {
                "COMPOSE_PROJECT_NAME": PROJECT_NAME,
                "EA_DEPLOYMENT_ID": self.deployment_id,
                "EA_DEPLOYMENT_ID_SOURCE": env.get(
                    "EA_DEPLOYMENT_ID_SOURCE", "ea_deploy_id_env"
                ),
                "EA_DEPLOY_PRIMARY_MODE": "MEMORIAL",
                "EA_DEPLOY_ENABLED_MODES": "MEMORIAL",
                "EA_DEPLOY_COMPOSE_FILES": "",
                "EA_DEPLOY_COMPOSE_OVERRIDES": MEMORIAL_COMPOSE_FILE,
            }
        )
        return env

    def _write_receipt(self) -> None:
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.receipt_dir.chmod(0o700)
        except OSError:
            pass
        payload = json.dumps(self.receipt, indent=2, sort_keys=True) + "\n"
        temporary = self.receipt_path.with_name(
            f".{self.receipt_path.name}.tmp.{os.getpid()}"
        )
        temporary.write_text(payload, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, self.receipt_path)

    def _open_lock(self, path: Path, *, busy_reason: str) -> Any:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise DeployError(f"lock_file_unavailable:{path.name}") from exc
        handle = os.fdopen(descriptor, "a+", encoding="utf-8")
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise DeployError(busy_reason) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        return handle

    def _acquire_lock(self) -> None:
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        if self.receipt_path.exists():
            raise DeployError("deployment_receipt_already_exists")
        self._global_lock_handle = self._open_lock(
            self.global_lock_path,
            busy_reason="memorial_api_deployment_already_running",
        )
        try:
            self._lock_handle = self._open_lock(
                self.lock_path, busy_reason="deployment_already_running"
            )
        except Exception:
            self._release_lock()
            raise

    def _release_lock(self) -> None:
        handles = (self._lock_handle, self._global_lock_handle)
        self._lock_handle = None
        self._global_lock_handle = None
        for handle in handles:
            if handle is None:
                continue
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _record_check(self, name: str, status: str, **detail: object) -> None:
        checks = list(self.receipt.get("checks") or [])
        checks.append({"name": name, "status": status, **detail})
        self.receipt["checks"] = checks
        self._write_receipt()

    def _require_vexp_certification_token_coverage(
        self, boundary: str
    ) -> dict[str, object]:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", boundary) is None:
            raise DeployError("vexp_token_coverage_boundary_invalid")
        checked_at_ms = int(time.time() * 1000)
        try:
            state, source = _read_trusted_vexp_sentinel_state(
                self.vexp_sentinel_state_path
            )
        except DeployError as exc:
            issue = str(exc)
            if re.fullmatch(r"vexp_sentinel_[a-z0-9_]+", issue) is None:
                issue = "vexp_sentinel_state_untrusted"
            evidence = _vexp_token_coverage_base(state_sha256="")
            evidence.update(
                {
                    "boundary": boundary,
                    "checked_at": _utc_timestamp_from_ms(checked_at_ms),
                    "reason": "sentinel_state_untrusted",
                    "issues": [issue],
                    "state_source": {
                        "trusted_private_file": False,
                        "credential_material_included": False,
                    },
                }
            )
        else:
            evidence = _vexp_certification_token_coverage(
                state,
                state_sha256=str(source["sha256"]),
                checked_at_ms=checked_at_ms,
                state_file_mtime_ns=int(source["mtime_ns"]),
            )
            evidence["boundary"] = boundary
            evidence["state_source"] = source

        history = list(
            self.receipt.get("vexp_certification_token_coverage_history") or []
        )
        history.append(dict(evidence))
        self.receipt["vexp_certification_token_coverage_history"] = history[-32:]
        self.receipt["vexp_certification_token_coverage"] = dict(evidence)
        status = str(evidence.get("status") or "fail").lower()
        self._record_check(
            f"vexp_token_coverage_{boundary}",
            "pass" if status == "pass" else "fail",
            reason=str(evidence.get("reason") or "sentinel_state_invalid"),
            state_sha256=str(evidence.get("state_sha256") or ""),
            certification_required_end_at=str(
                evidence.get("certification_required_end_at") or ""
            ),
            fresh_token_expiration_at=str(
                evidence.get("fresh_token_expiration_at") or ""
            ),
            coverage_shortfall_seconds=evidence.get("coverage_shortfall_seconds"),
            fresh_token_renewal_observed=bool(
                evidence.get("fresh_token_renewal_observed")
            ),
            credential_material_included=False,
            secrets_included=False,
        )
        if status == "pass":
            return evidence
        if str(evidence.get("reason") or "") in {
            "fresh_token_coverage_insufficient",
            "fresh_token_expired",
            "fresh_token_renewal_required",
            "license_certification_blocked",
        }:
            raise DeployError("vexp_certification_token_coverage_insufficient")
        raise DeployError("vexp_certification_token_coverage_untrusted")

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.runner.run(
            list(args),
            cwd=(cwd or self.root),
            env=(self.release_env if env is None else env),
            check=check,
        )

    def _detect_compose(self) -> None:
        docker_compose = self._run(["docker", "compose", "version"], check=False)
        if docker_compose.returncode == 0:
            self.compose_bin = ("docker", "compose")
            return
        legacy = self._run(["docker-compose", "version"], check=False)
        if legacy.returncode == 0:
            self.compose_bin = ("docker-compose",)
            return
        raise DeployError("docker_compose_unavailable")

    def _compose_args(self, *, root: Path, files: Sequence[str]) -> list[str]:
        if not self.compose_bin:
            raise DeployError("docker_compose_unavailable")
        env_file = root / ".env"
        if not env_file.is_file():
            raise DeployError(f"env_file_missing:{env_file}")
        args = [
            *self.compose_bin,
            "--project-name",
            PROJECT_NAME,
            "--project-directory",
            str(root),
            "--env-file",
            str(env_file),
        ]
        for filename in files:
            path = root / filename
            if not path.is_file():
                raise DeployError(f"compose_file_missing:{path}")
            args.extend(["-f", str(path)])
        return args

    def _target_compose(self, *args: str) -> list[str]:
        if not self.target_compose_files:
            raise DeployError("forward_compose_topology_unresolved")
        return [
            *self._compose_args(root=self.root, files=self.target_compose_files),
            *args,
        ]

    def _configure_forward_topology(self, previous: Mapping[str, Any]) -> None:
        prior_root = Path(str(previous.get("working_dir") or "")).resolve()
        prior_files = [
            Path(str(item)).resolve()
            for item in list(previous.get("compose_config_files") or [])
            if str(item).strip()
        ]
        if not prior_files:
            raise DeployError("forward_baseline_compose_files_missing")

        release_files: list[str] = []
        seen: set[str] = set()
        for prior_file in prior_files:
            try:
                relative = prior_file.relative_to(prior_root)
            except ValueError as exc:
                raise DeployError(
                    f"forward_baseline_compose_file_unmappable:{prior_file}"
                ) from exc
            relative_name = relative.as_posix()
            if relative.name == MEMORIAL_COMPOSE_FILE:
                raise DeployError("forward_baseline_already_contains_memorial")
            if relative_name in seen:
                raise DeployError("forward_baseline_compose_file_duplicate")
            release_file = (self.root / relative).resolve()
            try:
                release_file.relative_to(self.root)
            except ValueError as exc:
                raise DeployError(
                    f"forward_release_compose_file_escapes_root:{release_file}"
                ) from exc
            if not release_file.is_file():
                raise DeployError(
                    f"forward_release_compose_file_missing:{release_file}"
                )
            seen.add(relative_name)
            release_files.append(relative_name)

        memorial_path = (self.root / MEMORIAL_COMPOSE_FILE).resolve()
        if not memorial_path.is_file():
            raise DeployError(f"forward_memorial_compose_file_missing:{memorial_path}")
        release_files.append(MEMORIAL_COMPOSE_FILE)
        self.target_compose_files = tuple(release_files)
        self.release_env["EA_DEPLOY_COMPOSE_FILES"] = ",".join(release_files)
        self.receipt["target_compose_files"] = release_files
        self.receipt["forward_topology_source"] = {
            "working_dir": str(prior_root),
            "compose_config_files": [str(path) for path in prior_files],
            "mapping": "baseline_relative_paths_rebased_to_release_root_plus_memorial",
        }
        self._write_receipt()

    def _rollback_compose(
        self, root: Path, files: Sequence[str], *args: str
    ) -> list[str]:
        return [*self._compose_args(root=root, files=files), *args]

    def _rollback_environment(self) -> dict[str, str]:
        return {
            key: value
            for key, value in self.env.items()
            if key in ROLLBACK_ENV_PASSTHROUGH and key not in FORWARD_ONLY_ENV_KEYS
        }

    @staticmethod
    def _deployment_input_file_seal(path: Path) -> dict[str, object]:
        candidate = path.expanduser()
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise DeployError("deployment_input_path_invalid")
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW

        try:
            directory_descriptor = os.open("/", directory_flags)
        except OSError as exc:  # pragma: no cover - host invariant
            raise DeployError("deployment_input_root_unavailable") from exc
        try:
            for component in candidate.parts[1:-1]:
                try:
                    next_descriptor = os.open(
                        component,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise DeployError(
                        f"deployment_input_ancestor_invalid:{candidate.name}"
                    ) from exc
                try:
                    metadata = os.fstat(next_descriptor)
                    if not stat.S_ISDIR(metadata.st_mode):
                        raise DeployError(
                            f"deployment_input_ancestor_invalid:{candidate.name}"
                        )
                except BaseException:
                    os.close(next_descriptor)
                    raise
                os.close(directory_descriptor)
                directory_descriptor = next_descriptor

            name = candidate.name
            try:
                path_metadata = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                file_descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=directory_descriptor,
                )
            except OSError as exc:
                raise DeployError(
                    f"deployment_input_file_unavailable:{candidate.name}"
                ) from exc
        finally:
            os.close(directory_descriptor)

        try:
            before = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(path_metadata.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or (before.st_dev, before.st_ino)
                != (path_metadata.st_dev, path_metadata.st_ino)
            ):
                raise DeployError(f"deployment_input_file_invalid:{candidate.name}")
            if before.st_size > MAX_DEPLOYMENT_INPUT_BYTES:
                raise DeployError(f"deployment_input_file_too_large:{candidate.name}")
            identity = (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(file_descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DEPLOYMENT_INPUT_BYTES:
                    raise DeployError(
                        f"deployment_input_file_too_large:{candidate.name}"
                    )
                digest.update(chunk)
                current = os.fstat(file_descriptor)
                if (
                    current.st_dev,
                    current.st_ino,
                    current.st_mode,
                    current.st_uid,
                    current.st_gid,
                    current.st_nlink,
                    current.st_size,
                    current.st_mtime_ns,
                    current.st_ctime_ns,
                ) != identity:
                    raise DeployError(f"deployment_input_file_changed:{candidate.name}")
            after = os.fstat(file_descriptor)
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if after_identity != identity or total != after.st_size:
                raise DeployError(f"deployment_input_file_changed:{candidate.name}")
            return {
                "path": candidate.as_posix(),
                "sha256": digest.hexdigest(),
                "size_bytes": total,
                "mode": format(stat.S_IMODE(after.st_mode), "04o"),
                "device": int(after.st_dev),
                "inode": int(after.st_ino),
                "uid": int(after.st_uid),
                "gid": int(after.st_gid),
                "link_count": int(after.st_nlink),
                "mtime_ns": int(after.st_mtime_ns),
                "ctime_ns": int(after.st_ctime_ns),
            }
        finally:
            os.close(file_descriptor)

    @staticmethod
    def _deployment_input_absence_seal(path: Path) -> dict[str, object]:
        candidate = path.expanduser()
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise DeployError("deployment_input_path_invalid")
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        directory_descriptor = os.open("/", directory_flags)
        try:
            for component in candidate.parts[1:-1]:
                try:
                    next_descriptor = os.open(
                        component,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise DeployError(
                        f"deployment_input_ancestor_invalid:{candidate.name}"
                    ) from exc
                metadata = os.fstat(next_descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    os.close(next_descriptor)
                    raise DeployError(
                        f"deployment_input_ancestor_invalid:{candidate.name}"
                    )
                os.close(directory_descriptor)
                directory_descriptor = next_descriptor
            try:
                os.stat(
                    candidate.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return {"path": candidate.as_posix(), "present": False}
            except OSError as exc:
                raise DeployError(
                    f"deployment_input_optional_state_invalid:{candidate.name}"
                ) from exc
            raise DeployError(
                f"deployment_input_optional_presence_race:{candidate.name}"
            )
        finally:
            os.close(directory_descriptor)

    @classmethod
    def _deployment_optional_input_seal(cls, path: Path) -> dict[str, object]:
        try:
            return {"present": True, **cls._deployment_input_file_seal(path)}
        except DeployError as exc:
            if str(exc) != f"deployment_input_file_unavailable:{path.name}":
                raise
        return cls._deployment_input_absence_seal(path)

    def _capture_deployment_input_seal(
        self, previous: Mapping[str, Any]
    ) -> dict[str, list[dict[str, object]]]:
        rollback_root = Path(str(previous.get("working_dir") or ""))
        forward_required_paths = [
            self.root / ".env",
            *(self.root / item for item in self.target_compose_files),
        ]
        rollback_required_paths = [
            rollback_root / ".env",
            *(
                Path(str(item))
                for item in list(previous.get("compose_config_files") or [])
            ),
        ]

        def capture(paths: Sequence[Path]) -> list[dict[str, object]]:
            return [self._deployment_input_file_seal(path) for path in paths]

        def capture_optional(paths: Sequence[Path]) -> list[dict[str, object]]:
            return [self._deployment_optional_input_seal(path) for path in paths]

        first = {
            "forward": [
                *capture(forward_required_paths),
                *capture_optional([self.root / ".env.local"]),
            ],
            "rollback": [
                *capture(rollback_required_paths),
                *capture_optional([rollback_root / ".env.local"]),
            ],
        }
        second = {
            "forward": [
                *capture(forward_required_paths),
                *capture_optional([self.root / ".env.local"]),
            ],
            "rollback": [
                *capture(rollback_required_paths),
                *capture_optional([rollback_root / ".env.local"]),
            ],
        }
        if first != second:
            raise DeployError("deployment_input_seal_unstable")
        return first

    def _require_deployment_input_seal(
        self,
        expected: Mapping[str, Sequence[Mapping[str, object]]],
        *,
        scope: str | None = None,
    ) -> None:
        scopes = (scope,) if scope is not None else ("forward", "rollback")
        for current_scope in scopes:
            if current_scope not in {"forward", "rollback"}:
                raise DeployError("deployment_input_seal_scope_invalid")
            expected_rows = [dict(item) for item in expected.get(current_scope, ())]
            if not expected_rows:
                raise DeployError(f"deployment_input_seal_missing:{current_scope}")
            current_rows = [
                (
                    self._deployment_optional_input_seal(
                        Path(str(item.get("path") or ""))
                    )
                    if "present" in item
                    else self._deployment_input_file_seal(
                        Path(str(item.get("path") or ""))
                    )
                )
                for item in expected_rows
            ]
            if current_rows != expected_rows:
                raise DeployError(f"deployment_input_seal_changed:{current_scope}")

    def _run_json_script(
        self,
        script: str,
        *args: str,
        origin: str,
        expected_source_seal: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        command = [sys.executable, str(self.root / script), *args]
        completed = (
            self._run_release_evidence_command(
                command,
                expected_source_seal=expected_source_seal,
                label=origin,
                env=env,
            )
            if expected_source_seal is not None
            else self._run(command, env=env, check=False)
        )
        if completed.returncode != 0:
            evidence = _fixed_json_script_failure_evidence(
                script=script,
                origin=origin,
                completed=completed,
            )
            self._record_check("fixed_json_script", "fail", **evidence)
            raise DeployError(
                "fixed_json_script_failed:"
                f"{evidence['script']}:{evidence['origin']}:"
                f"{evidence['error_code']}:{evidence['return_code']}"
            )
        return _json_object(completed.stdout, reason=f"script_json_invalid:{script}")

    def _release_evidence_environment(self) -> dict[str, str]:
        environment = {
            key: str(value)
            for key, value in self.release_env.items()
            if key in RELEASE_EVIDENCE_ENV_ALLOWLIST and str(value)
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONNOUSERSITE"] = "1"
        return environment

    def _release_evidence_source_seal(self) -> dict[str, str]:
        evidence_env = self._release_evidence_environment()

        def git_value(args: list[str], *, reason: str) -> str:
            completed = self._run(args, env=evidence_env, check=False)
            if completed.returncode != 0:
                raise DeployError(reason)
            value = (completed.stdout or "").strip()
            if not re.fullmatch(r"[0-9a-f]{40,64}", value):
                raise DeployError(reason)
            return value

        head = git_value(
            ["git", "rev-parse", "HEAD"], reason="release_evidence_head_unavailable"
        )
        head_tree = git_value(
            ["git", "rev-parse", "HEAD^{tree}"],
            reason="release_evidence_head_tree_unavailable",
        )
        index_tree = git_value(
            ["git", "write-tree"], reason="release_evidence_index_tree_unavailable"
        )
        index_list_result = self._run(
            ["git", "ls-files", "-v", "-z"],
            env=evidence_env,
            check=False,
        )
        if index_list_result.returncode != 0:
            raise DeployError("release_evidence_index_flags_unavailable")
        raw_index_list = index_list_result.stdout or ""
        if len(raw_index_list.encode("utf-8")) > MAX_GIT_INDEX_LIST_BYTES:
            raise DeployError("release_evidence_index_flags_too_large")
        index_records = [item for item in raw_index_list.split("\0") if item]
        if not index_records or any(
            len(item) < 3 or item[:2] != "H " for item in index_records
        ):
            raise DeployError("release_evidence_nondefault_index_flags")
        status_result = self._run(
            [
                "git",
                "-c",
                "core.fileMode=true",
                "status",
                "--porcelain=v2",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ],
            env=evidence_env,
            check=False,
        )
        if status_result.returncode != 0:
            raise DeployError("release_evidence_source_status_unavailable")
        raw_status = status_result.stdout or ""
        if len(raw_status.encode("utf-8")) > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
            raise DeployError("release_evidence_source_status_too_large")
        if raw_status or index_tree != head_tree:
            raise DeployError("release_evidence_source_worktree_dirty")
        bound_revision = str(self.receipt.get("source_revision") or "").strip()
        if bound_revision and head != bound_revision:
            raise DeployError("release_evidence_source_revision_mismatch")
        return {
            "head": head,
            "head_tree": head_tree,
            "index_tree": index_tree,
            "index_flags_sha256": hashlib.sha256(
                raw_index_list.encode("utf-8")
            ).hexdigest(),
            "status_sha256": hashlib.sha256(raw_status.encode("utf-8")).hexdigest(),
        }

    def _require_release_evidence_source_seal(
        self, expected: Mapping[str, str]
    ) -> None:
        try:
            current = self._release_evidence_source_seal()
        except DeployError as exc:
            raise DeployError("release_evidence_mutated_tracked_worktree") from exc
        if current != dict(expected):
            raise DeployError("release_evidence_mutated_tracked_worktree")

    def _run_release_evidence_command(
        self,
        args: Sequence[str],
        *,
        expected_source_seal: Mapping[str, str],
        label: str,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not SAFE_SCRIPT_ORIGIN_PATTERN.fullmatch(label):
            raise DeployError("release_evidence_command_label_invalid")
        self._require_release_evidence_source_seal(expected_source_seal)
        command_error: BaseException | None = None
        completed: subprocess.CompletedProcess[str] | None = None
        try:
            completed = self._run(
                args,
                env=(env or self._release_evidence_environment()),
                check=False,
            )
        except BaseException as exc:  # preserve interrupts after the source audit
            command_error = exc
        try:
            self._require_release_evidence_source_seal(expected_source_seal)
        except DeployError as seal_error:
            if command_error is not None:
                raise DeployError(
                    f"release_evidence_command_failed_source_seal_changed:{label}"
                ) from command_error
            raise seal_error
        if command_error is not None:
            raise command_error
        if completed is None:  # pragma: no cover - defensive type narrowing
            raise DeployError(f"release_evidence_command_missing_result:{label}")
        return completed

    def _run_release_evidence_materializer(
        self,
        script: str,
        *args: str,
        expected_source_seal: Mapping[str, str],
        label: str,
        env: Mapping[str, str] | None = None,
    ) -> None:
        completed = self._run_release_evidence_command(
            [sys.executable, str(self.root / script), *args],
            expected_source_seal=expected_source_seal,
            label=label,
            env=env,
        )
        if completed.returncode != 0:
            raise DeployError(
                f"release_evidence_materializer_failed:{label}:{completed.returncode}"
            )

    def _private_evidence_directory(self, phase: str) -> Path:
        if phase not in {"predeploy", "postdeploy"}:
            raise DeployError("release_evidence_phase_invalid")
        try:
            relative_receipt_dir = self.receipt_dir.relative_to(self.root)
        except ValueError:
            relative_receipt_dir = None
        if relative_receipt_dir is not None and (
            not relative_receipt_dir.parts
            or relative_receipt_dir.parts[0] != ".runtime"
        ):
            raise DeployError("release_evidence_receipt_directory_not_private")
        try:
            receipt_metadata = self.receipt_dir.lstat()
        except OSError as exc:
            raise DeployError("release_evidence_receipt_directory_missing") from exc
        if (
            not stat.S_ISDIR(receipt_metadata.st_mode)
            or stat.S_ISLNK(receipt_metadata.st_mode)
            or receipt_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(receipt_metadata.st_mode) != 0o700
        ):
            raise DeployError("release_evidence_receipt_directory_invalid")
        evidence_root = self.receipt_dir / f"{self.deployment_id}.evidence"
        if phase == "predeploy":
            if os.path.lexists(evidence_root):
                raise DeployError("release_evidence_directory_already_exists")
            evidence_root.mkdir(mode=0o700)
        else:
            try:
                root_metadata = evidence_root.lstat()
            except OSError as exc:
                raise DeployError("release_evidence_directory_missing") from exc
            if (
                not stat.S_ISDIR(root_metadata.st_mode)
                or stat.S_ISLNK(root_metadata.st_mode)
                or root_metadata.st_uid != os.geteuid()
            ):
                raise DeployError("release_evidence_directory_invalid")
        try:
            evidence_root.chmod(0o700)
        except OSError as exc:
            raise DeployError("release_evidence_directory_permissions_invalid") from exc
        root_metadata = evidence_root.lstat()
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_ISLNK(root_metadata.st_mode)
            or root_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
        ):
            raise DeployError("release_evidence_directory_invalid")

        phase_directory = evidence_root / phase
        if os.path.lexists(phase_directory):
            raise DeployError("release_evidence_phase_directory_already_exists")
        phase_directory.mkdir(mode=0o700)
        phase_directory.chmod(0o700)
        phase_metadata = phase_directory.lstat()
        if (
            not stat.S_ISDIR(phase_metadata.st_mode)
            or stat.S_ISLNK(phase_metadata.st_mode)
            or phase_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(phase_metadata.st_mode) != 0o700
        ):
            raise DeployError("release_evidence_phase_directory_invalid")
        return phase_directory

    @staticmethod
    def _private_evidence_metadata(path: Path) -> dict[str, object]:
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise DeployError(f"release_evidence_file_unavailable:{path.name}") from exc
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
            ):
                raise DeployError(f"release_evidence_file_invalid:{path.name}")
            if before.st_size > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
                raise DeployError(f"release_evidence_file_too_large:{path.name}")
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            before = os.fstat(descriptor)
            identity = (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
                before.st_nlink,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
                    raise DeployError(f"release_evidence_file_too_large:{path.name}")
                digest.update(chunk)
            after = os.fstat(descriptor)
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_nlink,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if identity != after_identity or total != after.st_size:
                raise DeployError(f"release_evidence_file_changed:{path.name}")
            return {
                "sha256": digest.hexdigest(),
                "size_bytes": total,
                "mode": "0600",
            }
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_private_evidence_json(path: Path, payload: Mapping[str, object]) -> None:
        encoded = (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
            raise DeployError("release_evidence_phase_manifest_too_large")
        temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(temporary, flags, 0o600)
        except OSError as exc:
            raise DeployError("release_evidence_phase_manifest_unavailable") from exc
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise DeployError("release_evidence_phase_manifest_write_failed")
                view = view[written:]
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        finally:
            os.close(descriptor)
        if os.path.lexists(path):
            temporary.unlink(missing_ok=True)
            raise DeployError("release_evidence_phase_manifest_already_exists")
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def _materialize_and_verify_release_evidence(
        self,
        *,
        phase: str = "predeploy",
        deployment_input_seal: Mapping[str, Sequence[Mapping[str, object]]],
        expected_public_origin: str | None = None,
        expected_authority_posture: str | None = None,
    ) -> dict[str, Any]:
        source_seal = self._release_evidence_source_seal()
        authority: dict[str, Any] = {}
        readiness: dict[str, Any] = {}
        phase_error: BaseException | None = None
        try:
            self._require_deployment_input_seal(deployment_input_seal)
            evidence_directory = self._private_evidence_directory(phase)
            paths = {
                "deploy_context": evidence_directory / "deploy-context.json",
                "release_manifest": evidence_directory / "release-manifest.json",
                "release_authority_status": evidence_directory
                / "release-authority-status.json",
                "memorial_operator_status": evidence_directory
                / "memorial-operator-status.json",
                "phase_manifest": evidence_directory / "phase-manifest.json",
            }
            evidence_files: dict[str, dict[str, object]] = {}
            evidence_env = self._release_evidence_environment()

            self._run_release_evidence_materializer(
                "scripts/materialize_deploy_context.py",
                "--output",
                str(paths["deploy_context"]),
                expected_source_seal=source_seal,
                label=f"{phase}_deploy_context",
                env=evidence_env,
            )
            evidence_files["deploy_context"] = self._private_evidence_metadata(
                paths["deploy_context"]
            )
            self._require_deployment_input_seal(deployment_input_seal)

            manifest_env = dict(evidence_env)
            manifest_env["EA_DEPLOY_CONTEXT_PATH"] = str(paths["deploy_context"])
            self._run_release_evidence_materializer(
                "scripts/materialize_release_manifest.py",
                "--output",
                str(paths["release_manifest"]),
                expected_source_seal=source_seal,
                label=f"{phase}_release_manifest",
                env=manifest_env,
            )
            evidence_files["release_manifest"] = self._private_evidence_metadata(
                paths["release_manifest"]
            )
            self._require_deployment_input_seal(deployment_input_seal)

            self._run_release_evidence_materializer(
                "scripts/materialize_release_authority_status.py",
                "--output",
                str(paths["release_authority_status"]),
                "--release-manifest",
                str(paths["release_manifest"]),
                "--deploy-context",
                str(paths["deploy_context"]),
                expected_source_seal=source_seal,
                label=f"{phase}_authority_status",
                env=evidence_env,
            )
            evidence_files["release_authority_status"] = (
                self._private_evidence_metadata(paths["release_authority_status"])
            )
            self._require_deployment_input_seal(deployment_input_seal)

            self._run_release_evidence_materializer(
                "scripts/materialize_memorial_operator_status.py",
                "--output",
                str(paths["memorial_operator_status"]),
                "--deploy-context",
                str(paths["deploy_context"]),
                "--release-manifest",
                str(paths["release_manifest"]),
                "--release-authority-status",
                str(paths["release_authority_status"]),
                expected_source_seal=source_seal,
                label=f"{phase}_operator_status",
                env=evidence_env,
            )
            evidence_files["memorial_operator_status"] = (
                self._private_evidence_metadata(paths["memorial_operator_status"])
            )
            self._require_deployment_input_seal(deployment_input_seal)

            authority = self._run_json_script(
                "scripts/verify_release_authority.py",
                "--release-manifest",
                str(paths["release_manifest"]),
                "--pretty",
                origin=f"{phase}_release_authority",
                expected_source_seal=source_seal,
                env=evidence_env,
            )
            self._require_deployment_input_seal(deployment_input_seal)
            readiness = self._run_json_script(
                "scripts/verify_memorial_deploy_readiness.py",
                "--memorial-status",
                str(paths["memorial_operator_status"]),
                "--release-authority-status",
                str(paths["release_authority_status"]),
                "--pretty",
                origin=f"{phase}_memorial_readiness",
                expected_source_seal=source_seal,
                env=evidence_env,
            )
            self._require_deployment_input_seal(deployment_input_seal)

            if (
                str(authority.get("contract_name") or "")
                != "ea.release_authority_gate.v1"
            ):
                raise DeployError("release_authority_contract_invalid")
            if str(authority.get("status") or "").lower() != "pass":
                raise DeployError("release_authority_not_pass")
            if bool(authority.get("source_worktree_dirty")):
                raise DeployError("release_authority_source_worktree_dirty")
            if str(authority.get("deployment_id") or "") != self.deployment_id:
                raise DeployError("release_authority_deployment_id_mismatch")
            if str(authority.get("commit_sha") or "") != source_seal["head"]:
                raise DeployError("release_authority_commit_mismatch")
            if str(authority.get("project_mode") or "").upper() != "MEMORIAL":
                raise DeployError("release_authority_project_mode_mismatch")
            authority_public_origin = _validate_public_origin(
                str(authority.get("public_origin") or ""),
                allowed_hosts=self.allowed_public_hosts,
            )
            if (
                expected_public_origin is not None
                and authority_public_origin != expected_public_origin
            ):
                raise DeployError("release_authority_public_origin_mismatch")
            authority_posture = str(authority.get("authority_posture") or "").strip()
            if not authority_posture:
                raise DeployError("release_authority_posture_missing")
            if (
                expected_authority_posture is not None
                and authority_posture != expected_authority_posture
            ):
                raise DeployError("release_authority_posture_mismatch")
            if (
                str(readiness.get("contract_name") or "")
                != "ea.memorial_deploy_readiness.v1"
            ):
                raise DeployError("memorial_deploy_readiness_contract_invalid")
            if str(readiness.get("status") or "").lower() != "pass":
                raise DeployError("memorial_deploy_readiness_not_pass")

            for name, path in paths.items():
                if name == "phase_manifest":
                    continue
                if self._private_evidence_metadata(path) != evidence_files[name]:
                    raise DeployError(f"release_evidence_file_rehashed_mismatch:{name}")

            relative_directory = Path(f"{self.deployment_id}.evidence") / phase
            receipt_files = {
                name: {
                    "path": (relative_directory / paths[name].name).as_posix(),
                    **metadata,
                }
                for name, metadata in evidence_files.items()
            }
            authority_projection = {
                "contract_name": str(authority.get("contract_name") or ""),
                "status": str(authority.get("status") or ""),
                "authority_posture": str(authority.get("authority_posture") or ""),
                "deployment_id": str(authority.get("deployment_id") or ""),
                "commit_sha": str(authority.get("commit_sha") or ""),
                "project_mode": str(authority.get("project_mode") or ""),
                "public_origin": str(authority.get("public_origin") or ""),
                "source_worktree_dirty": bool(authority.get("source_worktree_dirty")),
            }
            readiness_projection = {
                "contract_name": str(readiness.get("contract_name") or ""),
                "status": str(readiness.get("status") or ""),
                "issues": [
                    str(item)
                    for item in list(readiness.get("issues") or [])
                    if str(item)
                ],
            }
            token_coverage = dict(
                self.receipt.get("vexp_certification_token_coverage") or {}
            )
            if (
                token_coverage.get("contract_name") != VEXP_TOKEN_COVERAGE_SCHEMA
                or str(token_coverage.get("status") or "").lower() != "pass"
                or token_coverage.get("token_coverage_safe") is not True
                or token_coverage.get("promotion_authorized") is not False
                or token_coverage.get("credential_material_included") is not False
                or token_coverage.get("secrets_included") is not False
            ):
                raise DeployError("vexp_certification_token_coverage_evidence_invalid")
            token_coverage_projection = {
                key: token_coverage.get(key)
                for key in (
                    "contract_name",
                    "status",
                    "reason",
                    "boundary",
                    "state_sha256",
                    "state_version",
                    "checked_at",
                    "state_file_mtime",
                    "state_file_age_seconds",
                    "required_window_seconds",
                    "epoch_started_at",
                    "epoch_started_ms",
                    "certification_required_end_at",
                    "certification_required_end_ms",
                    "fresh_token_expiration_at",
                    "fresh_token_expiration_ms",
                    "coverage_margin_seconds",
                    "coverage_shortfall_seconds",
                    "fresh_token_renewal_observed",
                    "fresh_token_renewal_count",
                    "qualification_phase",
                    "qualified_at",
                    "certification_blockers",
                    "certification_blocker_count",
                    "certification_blockers_sha256",
                    "unprojected_certification_blocker_count",
                    "token_coverage_safe",
                    "promotion_authorized",
                    "operator_action_required",
                    "credential_material_included",
                    "secrets_included",
                )
            }
            candidate_image = dict(self.receipt.get("candidate_image") or {})
            candidate_promotion = dict(
                self.receipt.get("candidate_promotion_evidence") or {}
            )
            projection = dict(candidate_promotion.get("projection") or {})
            phase_payload: dict[str, object] = {
                "contract_name": "ea.memorial_release_evidence_phase.v1",
                "generated_at": _utc_now(),
                "phase": phase,
                "deployment_id": self.deployment_id,
                "source_revision": source_seal["head"],
                "source_tree": source_seal["head_tree"],
                "index_tree": source_seal["index_tree"],
                "source_index_flags_sha256": source_seal["index_flags_sha256"],
                "source_status_sha256": source_seal["status_sha256"],
                "deployment_input_seal": {
                    key: [dict(item) for item in value]
                    for key, value in deployment_input_seal.items()
                },
                "candidate_image": {
                    "reference": str(candidate_image.get("reference") or ""),
                    "image_id": str(candidate_image.get("image_id") or ""),
                },
                "projection_sha256": str(projection.get("projection_sha256") or ""),
                "evidence_files": receipt_files,
                "authority": authority_projection,
                "readiness": readiness_projection,
                "vexp_token_coverage": token_coverage_projection,
            }
            self._write_private_evidence_json(paths["phase_manifest"], phase_payload)
            phase_metadata = self._private_evidence_metadata(paths["phase_manifest"])
            receipt_files["phase_manifest"] = {
                "path": (relative_directory / paths["phase_manifest"].name).as_posix(),
                **phase_metadata,
            }
            self._require_release_evidence_source_seal(source_seal)
            self._require_deployment_input_seal(deployment_input_seal)

            release_evidence = dict(self.receipt.get("release_evidence") or {})
            deployment_input_sha256 = hashlib.sha256(
                json.dumps(
                    deployment_input_seal,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            release_evidence[phase] = {
                "directory": relative_directory.as_posix(),
                "directory_mode": "0700",
                "source_seal": source_seal,
                "deployment_input_sha256": deployment_input_sha256,
                "files": receipt_files,
                "authority": authority_projection,
                "readiness": readiness_projection,
                "vexp_token_coverage": token_coverage_projection,
            }
            self.receipt["release_evidence"] = release_evidence
            self._write_receipt()
            self._record_check(f"release_authority_{phase}", "pass")
            self._record_check(f"memorial_deploy_readiness_{phase}", "pass")
        except BaseException as exc:
            phase_error = exc

        final_seal_error: DeployError | None = None
        try:
            self._require_release_evidence_source_seal(source_seal)
            self._require_deployment_input_seal(deployment_input_seal)
        except DeployError as exc:
            final_seal_error = exc
        if phase_error is not None:
            if final_seal_error is not None:
                if isinstance(phase_error, DeployError) and (
                    str(phase_error) == "release_evidence_mutated_tracked_worktree"
                    or str(phase_error).startswith("deployment_input_seal_changed:")
                ):
                    raise phase_error
                raise DeployError(
                    f"release_evidence_phase_failed_integrity_changed:{phase}"
                ) from phase_error
            raise phase_error
        if final_seal_error is not None:
            raise final_seal_error
        return authority

    def _validate_compose(
        self, *, candidate: Mapping[str, Any]
    ) -> list[dict[str, object]]:
        self._run(self._target_compose("config", "--quiet"))
        rendered = _json_object(
            self._run(self._target_compose("config", "--format", "json")).stdout,
            reason="memorial_compose_rendered_json_invalid",
        )
        services_payload = rendered.get("services")
        services_config = (
            dict(services_payload) if isinstance(services_payload, dict) else {}
        )
        api_payload = services_config.get(API_SERVICE)
        api_config = dict(api_payload) if isinstance(api_payload, dict) else {}
        if str(api_config.get("image") or "") != str(candidate.get("reference") or ""):
            raise DeployError("memorial_compose_candidate_image_mismatch")
        if str(api_config.get("pull_policy") or "").lower() != "never":
            raise DeployError("memorial_compose_pull_policy_invalid")
        target_mounts = self._rendered_mount_identities(
            rendered, api_config, root=self.root
        )
        memorial_mount = {
            "type": "bind",
            "source": str(self._configured_memorial_data_root()),
            "destination": "/data/memorial_data",
            "read_write": False,
        }
        memorial_mounts = [
            item
            for item in target_mounts
            if item.get("destination") == "/data/memorial_data"
        ]
        if memorial_mounts != [memorial_mount]:
            raise DeployError("memorial_compose_data_mount_mismatch")
        services = self._run(
            self._target_compose("config", "--services")
        ).stdout.splitlines()
        normalized = {item.strip() for item in services if item.strip()}
        if not {API_SERVICE, REDIS_SERVICE} <= normalized:
            raise DeployError("memorial_compose_services_missing")
        self._record_check(
            "compose_config",
            "pass",
            services=[API_SERVICE, REDIS_SERVICE],
            candidate_image=str(candidate.get("reference") or ""),
            pull_policy="never",
            mount_identity_count=len(target_mounts),
            mount_identity_sha256=_identity_digest(target_mounts),
        )
        return target_mounts

    def _inspect_container_optional(self, name: str) -> dict[str, Any] | None:
        completed = self._run(["docker", "inspect", name], check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            normalized = detail.casefold()
            if "no such object" in normalized or "no such container" in normalized:
                return None
            raise DeployError(f"container_inspect_failed:{name}")
        try:
            payload = json.loads(completed.stdout)
        except Exception as exc:
            raise DeployError(f"container_inspect_invalid:{name}") from exc
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError(f"container_inspect_invalid:{name}")
        return dict(payload[0])

    def _inspect_container(self, name: str) -> dict[str, Any]:
        inspection = self._inspect_container_optional(name)
        if inspection is None:
            raise DeployError(f"container_missing:{name}")
        return inspection

    @staticmethod
    def _require_compose_identity(
        inspection: Mapping[str, Any], *, service: str, reason_prefix: str
    ) -> None:
        labels = dict(dict(inspection.get("Config") or {}).get("Labels") or {})
        if labels.get("com.docker.compose.project") != PROJECT_NAME:
            raise DeployError(f"{reason_prefix}_project_mismatch")
        if labels.get("com.docker.compose.service") != service:
            raise DeployError(f"{reason_prefix}_service_mismatch")

    @staticmethod
    def _compose_topology(
        inspection: Mapping[str, Any], *, reason_prefix: str
    ) -> dict[str, Any]:
        labels = dict(dict(inspection.get("Config") or {}).get("Labels") or {})
        raw_working_dir = str(
            labels.get("com.docker.compose.project.working_dir") or ""
        ).strip()
        if not raw_working_dir:
            raise DeployError(f"{reason_prefix}_compose_working_dir_missing")
        working_dir = Path(raw_working_dir).expanduser()
        if not working_dir.is_absolute():
            raise DeployError(f"{reason_prefix}_working_dir_invalid")
        working_dir = working_dir.resolve()
        raw_config_files = str(
            labels.get("com.docker.compose.project.config_files") or ""
        ).strip()
        if not raw_config_files:
            raise DeployError(f"{reason_prefix}_compose_config_files_missing")
        compose_files: list[str] = []
        for raw_path in raw_config_files.split(","):
            candidate = Path(raw_path.strip()).expanduser()
            if not candidate.is_absolute():
                candidate = working_dir / candidate
            candidate = candidate.resolve()
            if not candidate.is_file():
                raise DeployError(f"{reason_prefix}_rollback_input_missing")
            compose_files.append(str(candidate))
        if not compose_files:
            raise DeployError(f"{reason_prefix}_compose_config_files_missing")
        return {
            "working_dir": str(working_dir),
            "compose_config_files": compose_files,
        }

    def _inspect_image(self, reference: str) -> dict[str, Any]:
        completed = self._run(["docker", "image", "inspect", reference])
        try:
            payload = json.loads(completed.stdout)
        except Exception as exc:
            raise DeployError("memorial_image_inspect_invalid") from exc
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError("memorial_image_inspect_invalid")
        image_id = str(payload[0].get("Id") or "").strip()
        if not IMAGE_ID_PATTERN.fullmatch(image_id):
            raise DeployError("memorial_image_id_invalid")
        return {"reference": reference, "image_id": image_id}

    def _inspect_image_config(self, reference: str) -> dict[str, Any]:
        completed = self._run(["docker", "image", "inspect", reference])
        try:
            payload = json.loads(completed.stdout)
        except Exception as exc:
            raise DeployError("rollback_image_config_inspect_invalid") from exc
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError("rollback_image_config_inspect_invalid")
        image_id = str(payload[0].get("Id") or "").strip()
        config = payload[0].get("Config")
        if not IMAGE_ID_PATTERN.fullmatch(image_id) or not isinstance(config, dict):
            raise DeployError("rollback_image_config_inspect_invalid")
        return {"image_id": image_id, "config": dict(config)}

    @staticmethod
    def _rendered_environment_entries(
        service: Mapping[str, Any], image_config: Mapping[str, Any]
    ) -> list[str]:
        defaults = _normalized_environment(list(image_config.get("Env") or []))
        merged = {item.split("=", 1)[0]: item.split("=", 1)[1] for item in defaults}
        environment = service.get("environment")
        if environment is None:
            return [f"{name}={merged[name]}" for name in sorted(merged)]
        if isinstance(environment, list):
            overrides = _normalized_environment(environment)
            for item in overrides:
                name, value = item.split("=", 1)
                merged[name] = value
        elif isinstance(environment, dict):
            for raw_name, raw_value in environment.items():
                name = str(raw_name or "")
                if not name or "\x00" in name:
                    raise DeployError("rollback_render_environment_invalid")
                if raw_value is None:
                    merged.pop(name, None)
                elif isinstance(raw_value, str) and "\x00" not in raw_value:
                    merged[name] = raw_value
                else:
                    raise DeployError("rollback_render_environment_invalid")
        else:
            raise DeployError("rollback_render_environment_invalid")
        return [f"{name}={merged[name]}" for name in sorted(merged)]

    @staticmethod
    def _rendered_process_config(
        service: Mapping[str, Any], image_config: Mapping[str, Any]
    ) -> dict[str, Any]:
        command_from_compose = (
            "command" in service and service.get("command") is not None
        )
        command = (
            service.get("command") if command_from_compose else image_config.get("Cmd")
        )
        entrypoint_from_compose = (
            "entrypoint" in service and service.get("entrypoint") is not None
        )
        entrypoint = (
            service.get("entrypoint")
            if entrypoint_from_compose
            else image_config.get("Entrypoint")
        )
        user = (
            service.get("user")
            if "user" in service and service.get("user") is not None
            else image_config.get("User")
        )
        return {
            "Cmd": (
                _compose_runtime_command(command)
                if command_from_compose
                else _normalized_command(command)
            ),
            "Entrypoint": (
                _compose_runtime_command(entrypoint)
                if entrypoint_from_compose
                else _normalized_command(entrypoint)
            ),
            "User": str(user or ""),
        }

    @staticmethod
    def _rendered_mount_identities(
        rendered: Mapping[str, Any], service: Mapping[str, Any], *, root: Path
    ) -> list[dict[str, object]]:
        raw_mounts = service.get("volumes") or []
        if not isinstance(raw_mounts, list):
            raise DeployError("rollback_render_mounts_invalid")
        top_level_value = rendered.get("volumes")
        top_level = dict(top_level_value) if isinstance(top_level_value, dict) else {}
        identities: list[dict[str, object]] = []
        for raw_mount in raw_mounts:
            if not isinstance(raw_mount, dict):
                raise DeployError("rollback_render_mounts_invalid")
            mount_type = str(raw_mount.get("type") or "")
            destination = str(raw_mount.get("target") or "")
            source = str(raw_mount.get("source") or "")
            if mount_type == "bind":
                source_path = Path(source).expanduser()
                if not source_path.is_absolute():
                    source_path = root / source_path
                source = str(source_path.resolve())
            elif mount_type == "volume":
                if not source:
                    raise DeployError("rollback_render_mount_unverifiable")
                volume_value = top_level.get(source)
                volume = dict(volume_value) if isinstance(volume_value, dict) else {}
                source = str(volume.get("name") or f"{PROJECT_NAME}_{source}")
            else:
                raise DeployError("rollback_render_mount_unverifiable")
            if not destination or not source:
                raise DeployError("rollback_render_mounts_invalid")
            identities.append(
                {
                    "type": mount_type,
                    "source": source,
                    "destination": destination,
                    "read_write": not bool(raw_mount.get("read_only")),
                }
            )
        return sorted(
            identities,
            key=lambda item: (
                str(item["destination"]),
                str(item["type"]),
                str(item["source"]),
                bool(item["read_write"]),
            ),
        )

    def _verify_rollback_renderability(
        self, previous: Mapping[str, Any]
    ) -> dict[str, Any]:
        rollback_root = Path(str(previous.get("working_dir") or "")).resolve()
        rollback_files = [
            str(item)
            for item in list(previous.get("compose_config_files") or [])
            if str(item).strip()
        ]
        rollback_env = self._rollback_environment()
        rendered = _json_object(
            self._run(
                self._rollback_compose(
                    rollback_root,
                    rollback_files,
                    "config",
                    "--format",
                    "json",
                ),
                cwd=rollback_root,
                env=rollback_env,
            ).stdout,
            reason="rollback_render_json_invalid",
        )
        if rendered.get("name") not in {None, PROJECT_NAME}:
            raise DeployError("rollback_render_project_mismatch")
        services_value = rendered.get("services")
        services = dict(services_value) if isinstance(services_value, dict) else {}
        service_value = services.get(API_SERVICE)
        service = dict(service_value) if isinstance(service_value, dict) else {}
        if not service:
            raise DeployError("rollback_render_api_missing")
        if str(service.get("image") or "") != str(
            previous.get("image_reference") or ""
        ):
            raise DeployError("rollback_render_image_reference_mismatch")
        image = self._inspect_image_config(str(previous.get("image_reference") or ""))
        if image["image_id"] != str(previous.get("image_id") or ""):
            raise DeployError("rollback_render_image_id_mismatch")
        image_config = dict(image["config"])
        expected_environment = _environment_identity(
            self._rendered_environment_entries(service, image_config)
        )
        if expected_environment["environment_sha256"] != previous.get(
            "environment_sha256"
        ) or expected_environment["environment_count"] != previous.get(
            "environment_count"
        ):
            raise DeployError("rollback_render_environment_identity_mismatch")
        process_digest = _process_config_identity(
            self._rendered_process_config(service, image_config)
        )
        if process_digest != previous.get("process_config_sha256"):
            raise DeployError("rollback_render_process_config_identity_mismatch")
        mounts = self._rendered_mount_identities(rendered, service, root=rollback_root)
        mount_digest = _identity_digest(mounts)
        if mount_digest != previous.get("mount_identity_sha256"):
            raise DeployError("rollback_render_mount_identity_mismatch")
        evidence = {
            "status": "pass",
            "working_dir": str(rollback_root),
            "compose_config_files": rollback_files,
            "image_id": str(previous.get("image_id") or ""),
            "image_reference": str(previous.get("image_reference") or ""),
            **expected_environment,
            "process_config_sha256": process_digest,
            "mount_identity_sha256": mount_digest,
            "mount_identity_count": len(mounts),
        }
        self.receipt["rollback_render_preflight"] = evidence
        self._record_check("rollback_render_preflight", "pass")
        return evidence

    def _resolve_candidate_image(self, source_revision: str) -> dict[str, Any]:
        if not self.memorial_image_reference:
            raise DeployError("explicit_memorial_image_required")
        reference = _safe_candidate_image_reference(
            self.memorial_image_reference,
            source_revision=source_revision,
        )
        candidate = self._inspect_image(reference)
        self.release_env["EA_MEMORIAL_IMAGE"] = reference
        self.receipt["candidate_image"] = candidate
        self._write_receipt()
        return candidate

    def _configured_memorial_data_root(self) -> Path:
        configured_data_root = _first_nonempty(
            self.env.get("EA_MEMORIAL_DATA_HOST_PATH"),
            self.env_file_values.get("EA_MEMORIAL_DATA_HOST_PATH"),
            "./memorial_data",
        )
        expected_data_root = Path(configured_data_root).expanduser()
        if not expected_data_root.is_absolute():
            expected_data_root = self.root / expected_data_root
        return expected_data_root.resolve()

    def _validate_candidate_promotion_receipt(
        self,
        *,
        candidate: Mapping[str, Any],
        source_revision: str,
    ) -> dict[str, Any]:
        if not self.candidate_receipt_value:
            raise DeployError("explicit_memorial_candidate_receipt_required")
        raw_path = Path(self.candidate_receipt_value).expanduser()
        if not raw_path.is_absolute() or raw_path.is_symlink():
            raise DeployError("memorial_candidate_receipt_path_invalid")
        path = raw_path.resolve()
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(raw_path, flags)
        except OSError as exc:
            raise DeployError("memorial_candidate_receipt_missing") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise DeployError("memorial_candidate_receipt_permissions_invalid")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read(MAX_HTTP_BODY_BYTES + 1)
        except OSError as exc:
            raise DeployError("memorial_candidate_receipt_unreadable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not raw or len(raw) > MAX_HTTP_BODY_BYTES:
            raise DeployError("memorial_candidate_receipt_size_invalid")
        try:
            payload = json.loads(raw)
        except Exception as exc:
            raise DeployError("memorial_candidate_receipt_json_invalid") from exc
        if not isinstance(payload, dict):
            raise DeployError("memorial_candidate_receipt_json_invalid")

        expected_data_root = self._configured_memorial_data_root()
        self.durable_root_check(expected_data_root)
        candidate_release_root = Path(
            str(payload.get("release_root") or "")
        ).expanduser()
        if not candidate_release_root.is_absolute():
            raise DeployError("memorial_candidate_release_root_invalid")
        candidate_release_root = candidate_release_root.resolve()

        browser_value = payload.get("browser_surface")
        browser = dict(browser_value) if isinstance(browser_value, dict) else {}
        candidate_project = str(payload.get("compose_project") or "")
        candidate_project_suffix = candidate_project.removeprefix(
            "ea-manfred-candidate-"
        )
        candidate_port = payload.get("candidate_port")
        candidate_preflight_value = payload.get("candidate_preflight")
        candidate_preflight = (
            dict(candidate_preflight_value)
            if isinstance(candidate_preflight_value, dict)
            else {}
        )
        locks_value = payload.get("locks")
        locks = dict(locks_value) if isinstance(locks_value, dict) else {}
        project_lock_value = locks.get("project")
        project_lock = (
            dict(project_lock_value) if isinstance(project_lock_value, dict) else {}
        )
        port_lock_value = locks.get("port")
        port_lock = dict(port_lock_value) if isinstance(port_lock_value, dict) else {}
        top_project_lock_value = payload.get("project_lock")
        top_project_lock = (
            dict(top_project_lock_value)
            if isinstance(top_project_lock_value, dict)
            else {}
        )
        top_port_lock_value = payload.get("port_lock")
        top_port_lock = (
            dict(top_port_lock_value) if isinstance(top_port_lock_value, dict) else {}
        )
        locator_value = payload.get("image_locator_evidence")
        locator = dict(locator_value) if isinstance(locator_value, dict) else {}
        container_images_value = payload.get("candidate_container_images")
        container_images = (
            dict(container_images_value)
            if isinstance(container_images_value, dict)
            else {}
        )
        candidate_api_image_value = container_images.get("api")
        candidate_api_image = (
            dict(candidate_api_image_value)
            if isinstance(candidate_api_image_value, dict)
            else {}
        )
        candidate_gateway_image_value = container_images.get("gateway")
        candidate_gateway_image = (
            dict(candidate_gateway_image_value)
            if isinstance(candidate_gateway_image_value, dict)
            else {}
        )
        named_resources_value = payload.get("candidate_named_resources")
        named_resources = (
            dict(named_resources_value)
            if isinstance(named_resources_value, dict)
            else {}
        )
        openapi_value = payload.get("openapi_contract")
        openapi = dict(openapi_value) if isinstance(openapi_value, dict) else {}
        live_before_value = payload.get("live_ea_project_before")
        live_after_value = payload.get("live_ea_project_after")
        live_before = (
            dict(live_before_value) if isinstance(live_before_value, dict) else {}
        )
        live_after = (
            dict(live_after_value) if isinstance(live_after_value, dict) else {}
        )

        def receipt_mapping(name: str) -> dict[str, Any]:
            value = payload.get(name)
            return dict(value) if isinstance(value, dict) else {}

        initial_container_images = receipt_mapping(
            "candidate_container_images_initial"
        )
        final_container_images = receipt_mapping("candidate_container_images_final")
        runtime_projection_initial = receipt_mapping("runtime_projection_initial")
        runtime_projection_final = receipt_mapping("runtime_projection_final")
        runtime_version = receipt_mapping("runtime_version_identity")
        compose_attestation = receipt_mapping("compose_attestation")
        execution_inputs = receipt_mapping("execution_inputs")
        runtime_api_posture = receipt_mapping("runtime_api_posture")
        registry_recovery = receipt_mapping("registry_recovery")
        spatial_projection = receipt_mapping("spatial_handoff")
        spatial_runtime = receipt_mapping("spatial_handoff_runtime")
        fleet_lock_value = locks.get("fleet")
        fleet_lock = (
            dict(fleet_lock_value) if isinstance(fleet_lock_value, dict) else {}
        )

        def openapi_snapshot(name: str) -> dict[str, Any]:
            value = openapi.get(name)
            return dict(value) if isinstance(value, dict) else {}

        live_openapi_before = openapi_snapshot("live_before")
        candidate_openapi = openapi_snapshot("candidate")
        candidate_openapi_public_endpoint = openapi_snapshot(
            "candidate_public_endpoint"
        )
        live_openapi_after = openapi_snapshot("live_after")

        def valid_openapi_snapshot(
            value: Mapping[str, Any], *, candidate_snapshot: bool = False
        ) -> bool:
            expected_fields = set(OPENAPI_EVIDENCE_FIELDS)
            if candidate_snapshot:
                expected_fields.update(
                    {"snapshot_source", "public_docs_config_retired"}
                )
            return (
                set(value) == expected_fields
                and type(value.get("path_count")) is int
                and int(value["path_count"]) > 0
                and type(value.get("operation_count")) is int
                and int(value["operation_count"]) > 0
                and type(value.get("schema_count")) is int
                and int(value["schema_count"]) >= 0
                and type(value.get("security_scheme_count")) is int
                and int(value["security_scheme_count"]) >= 0
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("path_digest_sha256") or "")
                )
                is not None
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("contract_digest_sha256") or "")
                )
                is not None
                and (
                    not candidate_snapshot
                    or (
                        value.get("snapshot_source")
                        == "candidate_api_container_app.openapi"
                        and value.get("public_docs_config_retired") is True
                    )
                )
            )

        def valid_candidate_openapi_public_endpoint(
            value: Mapping[str, Any],
        ) -> bool:
            security_headers = value.get("security_headers")
            if not isinstance(security_headers, dict) or set(security_headers) != {
                "content_security_policy",
                "x_content_type_options",
                "x_frame_options",
            }:
                return False
            directives: dict[str, tuple[str, ...]] = {}
            for raw_directive in str(
                security_headers.get("content_security_policy") or ""
            ).split(";"):
                parts = raw_directive.strip().split()
                if not parts:
                    continue
                name = parts[0].lower()
                if name in directives:
                    return False
                directives[name] = tuple(parts[1:])
            content_type = value.get("content_type")
            return (
                set(value)
                == {
                    "path",
                    "status",
                    "error_code",
                    "content_type",
                    "media_type",
                    "correlation_header_matches_body",
                    "security_headers",
                    "public_endpoint_retired",
                }
                and value.get("path") == "/openapi.json"
                and type(value.get("status")) is int
                and value.get("status") == 404
                and value.get("error_code") == "not_found"
                and type(content_type) is str
                and 0 < len(content_type) <= MAX_RECEIPT_CONTENT_TYPE_CHARS
                and str(content_type).partition(";")[0].strip().lower()
                == "application/json"
                and value.get("media_type") == "application/json"
                and value.get("correlation_header_matches_body") is True
                and directives.get("frame-ancestors") == ("'none'",)
                and str(security_headers.get("x_content_type_options") or "").lower()
                == "nosniff"
                and str(security_headers.get("x_frame_options") or "").upper()
                == "DENY"
                and value.get("public_endpoint_retired") is True
            )

        live_containers = live_before.get("containers")
        live_networks = live_before.get("networks")
        live_volumes = live_before.get("volumes")
        live_api_rows = (
            [
                dict(row)
                for row in live_containers
                if isinstance(row, dict)
                and (
                    str(row.get("service") or "") == API_SERVICE
                    or str(row.get("name") or "") == API_SERVICE
                )
            ]
            if isinstance(live_containers, list)
            else []
        )
        expected_named_resources = {
            "containers": sorted(
                [
                    f"{candidate_project}-{service}-1"
                    for service in ("api", "gateway", "postgres", "redis")
                ]
                + [
                    f"{candidate_project}_{service}_1"
                    for service in ("api", "gateway", "postgres", "redis")
                ]
            ),
            "networks": [
                f"{candidate_project}_backend",
                f"{candidate_project}_ingress",
            ],
            "volumes": [
                f"{candidate_project}_artifacts",
                f"{candidate_project}_postgres_data",
                f"{candidate_project}_redis_data",
            ],
        }
        required_smoke_checks = {
            "archive_publication_gate",
            "singular_memorial_alias",
            "source_grounded_narrator_boundary",
            "voice_provider_boundary_blocked",
        }
        first_checks = {
            str(item).strip()
            for item in list(payload.get("first_smoke_checks") or [])
            if str(item).strip()
        }
        second_checks = {
            str(item).strip()
            for item in list(payload.get("second_smoke_checks") or [])
            if str(item).strip()
        }

        image_reference = str(candidate.get("reference") or "")
        image_id = str(candidate.get("image_id") or "")
        container_id_pattern = re.compile(r"^[0-9a-f]{64}$")
        expected_projection_count = payload.get("projection_file_count")
        expected_projection_bytes = payload.get("projection_bytes")
        expected_runtime_mount_roots = [
            "/data/memorial/public",
            "/data/memorial/private",
            "/data/memorial/archive",
            "/data/public_property_tours",
            "/data/release-authority",
        ]
        expected_candidate_env_keys = sorted(
            {
                "DATABASE_URL",
                "EA_API_TOKEN",
                "EA_MANFRED_COMPOSE_PROJECT",
                "EA_MANFRED_COMMIT",
                "EA_MANFRED_DEPLOYMENT_ID",
                "EA_MANFRED_ENV_FILE",
                "EA_MANFRED_HOST_PORT",
                "EA_MANFRED_IMAGE",
                "EA_MANFRED_POSTGRES_PASSWORD",
                "EA_MANFRED_RELEASE_AUTHORITY_ROOT",
                "EA_MANFRED_RELEASE_ROOT",
                "EA_MANFRED_RUNTIME_ROOT",
                "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED",
                "EA_MANFRED_SPATIAL_RELEASE_ROOT",
                "EA_MANFRED_SPATIAL_SHA256",
                "EA_MANFRED_SPATIAL_SLUG",
                "EA_PUBLIC_APP_BASE_URL",
                "EA_SIGNING_SECRET",
            }
        )

        def valid_container_images(value: Mapping[str, Any]) -> bool:
            if set(value) != {
                "api",
                "gateway",
                "prepared_image_id",
                "revision_label",
                "all_match_prepared_image",
            }:
                return False
            api = value.get("api")
            gateway = value.get("gateway")
            if not isinstance(api, dict) or not isinstance(gateway, dict):
                return False
            if set(api) != {"container_id", "image_id"} or set(gateway) != {
                "container_id",
                "image_id",
            }:
                return False
            api_id = str(api.get("container_id") or "")
            gateway_id = str(gateway.get("container_id") or "")
            return (
                container_id_pattern.fullmatch(api_id) is not None
                and container_id_pattern.fullmatch(gateway_id) is not None
                and api_id != gateway_id
                and api.get("image_id") == image_id
                and gateway.get("image_id") == image_id
                and value.get("prepared_image_id") == image_id
                and value.get("revision_label") == source_revision
                and value.get("all_match_prepared_image") is True
            )

        def valid_runtime_projection(value: Mapping[str, Any]) -> bool:
            return (
                set(value)
                == {
                    "schema",
                    "projection_sha256",
                    "file_count",
                    "projection_bytes",
                    "mount_roots",
                    "runtime_bytes_match_prepared_projection",
                }
                and value.get("schema")
                == "ea.manfred_candidate_runtime_projection.v1"
                and value.get("projection_sha256") == payload.get("projection_sha256")
                and type(value.get("file_count")) is int
                and value.get("file_count") == expected_projection_count
                and type(value.get("projection_bytes")) is int
                and value.get("projection_bytes") == expected_projection_bytes
                and value.get("mount_roots") == expected_runtime_mount_roots
                and value.get("runtime_bytes_match_prepared_projection") is True
            )

        expected_runtime_version = {
            "path": "/version",
            "status": 200,
            "commit_sha": source_revision,
            "body_commit_sha": source_revision,
            "source_revision_header": source_revision,
            "expected_commit_sha": source_revision,
            "oci_image_revision": source_revision,
            "repository": "EA",
            "role": "api",
            "release_authority_state": "clear",
            "release_authority_posture": "authoritative_runtime",
            "release_authority_source": "published_status_artifact",
            "commit_observed_over_http": True,
            "revision_agreement_verified": True,
        }
        compose_relative_path = "deploy/manfred-memorial/docker-compose.candidate.yml"
        expected_compose_path = str((self.root / compose_relative_path).resolve())
        try:
            expected_compose_bytes = Path(expected_compose_path).read_bytes()
        except OSError:
            expected_compose_bytes = None

        def git_blob_oid(content: bytes, *, digest_chars: int) -> str:
            framed = f"blob {len(content)}\0".encode("ascii") + content
            if digest_chars == 40:
                return hashlib.sha1(  # noqa: S324 - Git object identity is SHA-1
                    framed,
                    usedforsecurity=False,
                ).hexdigest()
            if digest_chars == 64:
                return hashlib.sha256(framed).hexdigest()
            return ""

        def valid_compose_attestation(value: Mapping[str, Any]) -> bool:
            blob_oid = str(value.get("git_blob_oid") or "")
            producer_source = Path(str(value.get("canonical_source_path") or ""))
            relative_parts = Path(compose_relative_path).parts
            return (
                set(value)
                == {
                    "canonical_relative_path",
                    "canonical_source_path",
                    "candidate_commit",
                    "git_blob_oid",
                    "sha256",
                    "size_bytes",
                    "canonical_path_enforced",
                    "tracked_blob_bytes_enforced",
                }
                and value.get("canonical_relative_path") == compose_relative_path
                and producer_source.is_absolute()
                and producer_source.parts[-len(relative_parts) :] == relative_parts
                and value.get("candidate_commit") == source_revision
                and len(blob_oid) in {40, 64}
                and blob_oid == blob_oid.lower()
                and all(character in "0123456789abcdef" for character in blob_oid)
                and expected_compose_bytes is not None
                and blob_oid
                == git_blob_oid(expected_compose_bytes, digest_chars=len(blob_oid))
                and SHA256_HEX_PATTERN.fullmatch(str(value.get("sha256") or ""))
                is not None
                and value.get("sha256")
                == hashlib.sha256(expected_compose_bytes).hexdigest()
                and type(value.get("size_bytes")) is int
                and value.get("size_bytes") == len(expected_compose_bytes)
                and len(expected_compose_bytes) > 0
                and value.get("canonical_path_enforced") is True
                and value.get("tracked_blob_bytes_enforced") is True
            )

        def valid_execution_inputs(value: Mapping[str, Any]) -> bool:
            environment_keys = value.get("environment_keys")
            return (
                set(value)
                == {
                    "schema",
                    "compose_sha256",
                    "compose_size_bytes",
                    "compose_git_blob_oid",
                    "environment_sha256",
                    "environment_size_bytes",
                    "environment_keys",
                    "compose_image_id",
                    "compose_image_reference_source",
                    "transport",
                    "required_seals",
                    "all_compose_commands_use_sealed_inputs",
                    "mutable_source_paths_consumed_by_compose",
                    "mutable_image_locator_consumed_by_compose",
                }
                and value.get("schema")
                == "ea.manfred_candidate_execution_inputs.v1"
                and value.get("compose_sha256") == compose_attestation.get("sha256")
                and value.get("compose_size_bytes")
                == compose_attestation.get("size_bytes")
                and value.get("compose_git_blob_oid")
                == compose_attestation.get("git_blob_oid")
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("environment_sha256") or "")
                )
                is not None
                and type(value.get("environment_size_bytes")) is int
                and int(value.get("environment_size_bytes") or 0) > 0
                and environment_keys == expected_candidate_env_keys
                and value.get("compose_image_id") == image_id
                and value.get("compose_image_reference_source")
                == "prepared_image_id"
                and value.get("transport") == "sealed_memfd"
                and value.get("required_seals")
                == ["grow", "seal", "shrink", "write"]
                and value.get("all_compose_commands_use_sealed_inputs") is True
                and value.get("mutable_source_paths_consumed_by_compose") is False
                and value.get("mutable_image_locator_consumed_by_compose") is False
            )

        def valid_runtime_mounts(value: object) -> bool:
            if not isinstance(value, list) or len(value) != 9:
                return False
            rows: dict[str, dict[str, Any]] = {}
            for raw_row in value:
                if not isinstance(raw_row, dict) or set(raw_row) != {
                    "destination",
                    "identity",
                    "read_only",
                    "type",
                }:
                    return False
                destination = str(raw_row.get("destination") or "")
                if not destination or destination in rows:
                    return False
                rows[destination] = dict(raw_row)
            expected_read_only = {
                "/data/memorial/public": expected_data_root / "public_memorials",
                "/data/memorial/private": expected_data_root
                / "private_memorial_profiles",
                "/data/memorial/archive": expected_data_root / "memorial_archive",
                "/data/public_property_tours": expected_data_root
                / "public_property_tours",
                "/data/release-authority": expected_data_root / "release-authority",
            }
            for destination, source in expected_read_only.items():
                if rows.get(destination) != {
                    "destination": destination,
                    "identity": str(source.resolve()),
                    "read_only": True,
                    "type": "bind",
                }:
                    return False
            mutable_names = {
                "/data/memorial/public-contributions": "public-contributions",
                "/data/memorial/private-contributions": "private-contributions",
                "/data/memorial/state": "state",
            }
            mutable_parents: set[str] = set()
            for destination, basename in mutable_names.items():
                row = rows.get(destination, {})
                identity = Path(str(row.get("identity") or ""))
                if (
                    row.get("destination") != destination
                    or row.get("type") != "bind"
                    or row.get("read_only") is not False
                    or not identity.is_absolute()
                    or identity.name != basename
                ):
                    return False
                mutable_parents.add(str(identity.parent))
            return (
                len(mutable_parents) == 1
                and rows.get("/data/artifacts")
                == {
                    "destination": "/data/artifacts",
                    "identity": f"{candidate_project}_artifacts",
                    "read_only": False,
                    "type": "volume",
                }
            )

        def valid_runtime_posture(value: Mapping[str, Any]) -> bool:
            environment_keys = value.get("environment_keys")
            required_keys = {
                *expected_candidate_env_keys,
                "EA_ALLOW_LOOPBACK_NO_AUTH",
                "EA_DEPLOY_COMMIT_SHA",
                "EA_DEPLOY_PUBLIC_ORIGIN",
                "EA_ENABLE_PUBLIC_MEMORIALS",
                "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES",
                "EA_ENABLE_PUBLIC_TOURS",
                "EA_PUBLIC_MEMORIAL_RATE_BACKEND",
                "EA_PUBLIC_MEMORIAL_REDIS_URL",
                "EA_RELEASE_AUTHORITY_STATUS_PATH",
                "EA_SOURCE_REVISION",
                "EA_STORAGE_BACKEND",
                "EA_STORAGE_FALLBACK_ALLOWED",
                "EA_TRUST_PROXY_HEADERS",
            }
            return (
                set(value)
                == {
                    "schema",
                    "api_container_id",
                    "image_id",
                    "environment_sha256",
                    "execution_environment_sha256",
                    "environment_keys",
                    "environment_exact",
                    "provider_credentials_present",
                    "mounts",
                    "mounts_exact",
                    "tmpfs_exact",
                    "networks",
                    "network_exact",
                    "ingress_attached",
                    "read_only_rootfs",
                    "all_capabilities_dropped",
                    "no_new_privileges",
                    "runtime_user",
                    "running_and_healthy",
                }
                and value.get("schema")
                == "ea.manfred_candidate_api_runtime_posture.v1"
                and value.get("api_container_id")
                == dict(container_images.get("api") or {}).get("container_id")
                and value.get("image_id") == image_id
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("environment_sha256") or "")
                )
                is not None
                and value.get("execution_environment_sha256")
                == execution_inputs.get("environment_sha256")
                and isinstance(environment_keys, list)
                and environment_keys == sorted(set(environment_keys))
                and required_keys <= set(environment_keys)
                and value.get("environment_exact") is True
                and value.get("provider_credentials_present") is False
                and valid_runtime_mounts(value.get("mounts"))
                and value.get("mounts_exact") is True
                and value.get("tmpfs_exact") is True
                and value.get("networks") == [f"{candidate_project}_backend"]
                and value.get("network_exact") is True
                and value.get("ingress_attached") is False
                and value.get("read_only_rootfs") is True
                and value.get("all_capabilities_dropped") is True
                and value.get("no_new_privileges") is True
                and value.get("runtime_user") == "10001:10001"
                and value.get("running_and_healthy") is True
            )

        def valid_registry_recovery(value: Mapping[str, Any]) -> bool:
            if set(value) != {
                "state_before_launch",
                "crash_intent_reconciled",
                "pending_contribution_reconciled",
                "existing_receipt_resumed",
                "interrupted_receipt_publication_completed",
            }:
                return False
            state = value.get("state_before_launch")
            return (
                state in {"absent", "pending_only"}
                and value.get("crash_intent_reconciled")
                is (state == "pending_only")
                and type(value.get("pending_contribution_reconciled")) is bool
                and (
                    state == "pending_only"
                    or value.get("pending_contribution_reconciled") is False
                )
                and value.get("existing_receipt_resumed") is False
                and value.get("interrupted_receipt_publication_completed") is False
            )

        spatial_slug = str(spatial_projection.get("slug") or "")
        spatial_viewer_relpath = str(spatial_projection.get("viewer_relpath") or "")
        spatial_proof_relpath = str(spatial_projection.get("proof_relpath") or "")
        spatial_package_sha256 = str(
            spatial_projection.get("upstream_package_sha256") or ""
        )
        spatial_route_labels = spatial_projection.get("route_labels")
        spatial_root = expected_data_root / "public_property_tours"
        spatial_bundle_root = spatial_root / REQUIRED_CONTROL_TOUR_SLUG
        try:
            (
                observed_spatial_projection_sha256,
                observed_spatial_projection_files,
            ) = _candidate_projection_tree_digest(spatial_root)
            observed_spatial_snapshot = _spatial_tree_snapshot(
                spatial_bundle_root,
                require_sanitized_modes=False,
            )
        except (OSError, ValueError):
            observed_spatial_projection_sha256 = ""
            observed_spatial_projection_files = []
            observed_spatial_snapshot = {}
        observed_spatial_projection_bytes = sum(
            int(row.get("size_bytes") or 0)
            for row in observed_spatial_projection_files
            if isinstance(row, dict)
        )
        observed_spatial_local_files = [
            {
                "path": relpath,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for relpath, content in sorted(observed_spatial_snapshot.items())
        ]
        observed_spatial_package_sha256 = (
            _spatial_package_sha256(observed_spatial_snapshot)
            if observed_spatial_snapshot
            else ""
        )
        observed_spatial_tour_sha256 = (
            hashlib.sha256(observed_spatial_snapshot["tour.json"]).hexdigest()
            if "tour.json" in observed_spatial_snapshot
            else ""
        )

        def passing_spatial_verifier(value: object) -> bool:
            return (
                isinstance(value, dict)
                and value.get("pass") is True
                and isinstance(value.get("checks"), dict)
                and dict(value["checks"]).get("binding_count") == 5
            )

        def valid_spatial_projection(value: Mapping[str, Any]) -> bool:
            asset_paths = value.get("asset_paths")
            expected_spatial_files = {
                f"{spatial_slug}/tour.json",
                *(
                    f"{spatial_slug}/{asset_path}"
                    for asset_path in asset_paths
                    if isinstance(asset_path, str)
                ),
            } if isinstance(asset_paths, list) else set()
            return (
                set(value)
                == {
                    "included",
                    "slug",
                    "release_root",
                    "projection_sha256",
                    "file_count",
                    "projection_bytes",
                    "receipt_path",
                    "receipt_sha256",
                    "projection_tree_revalidated",
                    "ea_public_activation_authority",
                    "asset_paths",
                    "viewer_relpath",
                    "proof_relpath",
                    "route_labels",
                    "upstream_publication_authority_sha256",
                    "upstream_package_sha256",
                    "upstream_tour_manifest_sha256",
                    "pre_authority_manifest_canonical_sha256",
                    "upstream_public_activation_authority",
                    "local_release_verifier",
                }
                and value.get("included") is True
                and spatial_slug == REQUIRED_CONTROL_TOUR_SLUG
                and value.get("release_root")
                == str((expected_data_root / "public_property_tours").resolve())
                and value.get("projection_sha256")
                == observed_spatial_projection_sha256
                and value.get("file_count")
                == len(observed_spatial_projection_files)
                == 6
                and value.get("projection_bytes")
                == observed_spatial_projection_bytes
                and observed_spatial_projection_bytes > 0
                and type(value.get("receipt_path")) is str
                and Path(str(value["receipt_path"])).is_absolute()
                and value.get("projection_tree_revalidated") is True
                and value.get("ea_public_activation_authority") is False
                and isinstance(asset_paths, list)
                and len(asset_paths) == 5
                and all(isinstance(asset_path, str) for asset_path in asset_paths)
                and len(set(asset_paths)) == 5
                and set(observed_spatial_snapshot) == {"tour.json", *asset_paths}
                and {
                    str(row.get("path") or "")
                    for row in observed_spatial_projection_files
                    if isinstance(row, dict)
                }
                == expected_spatial_files
                and spatial_viewer_relpath
                == "generated-reconstruction/viewer.html"
                and spatial_proof_relpath
                == "generated-reconstruction/reconstruction.json"
                and isinstance(spatial_route_labels, list)
                and len(spatial_route_labels) == 9
                and all(
                    isinstance(route_label, str)
                    and route_label
                    and route_label == route_label.strip()
                    for route_label in spatial_route_labels
                )
                and len(set(spatial_route_labels)) == 9
                and all(
                    SHA256_HEX_PATTERN.fullmatch(str(value.get(name) or ""))
                    is not None
                    for name in (
                        "receipt_sha256",
                        "upstream_publication_authority_sha256",
                        "upstream_package_sha256",
                        "upstream_tour_manifest_sha256",
                        "pre_authority_manifest_canonical_sha256",
                    )
                )
                and value.get("upstream_publication_authority_sha256")
                == PROPERTY_AUTHORITY_SHA256
                and value.get("upstream_package_sha256")
                == observed_spatial_package_sha256
                and value.get("upstream_tour_manifest_sha256")
                == observed_spatial_tour_sha256
                == PROPERTY_TOUR_SHA256
                and value.get("pre_authority_manifest_canonical_sha256")
                == PROPERTY_PRE_AUTHORITY_SHA256
                and value.get("upstream_public_activation_authority") is True
                and passing_spatial_verifier(value.get("local_release_verifier"))
            )

        def valid_spatial_browser(value: object) -> bool:
            if not isinstance(value, dict):
                return False
            gateway_id = dict(container_images.get("gateway") or {}).get("container_id")
            try:
                validate_spatial_candidate_browser_receipt(
                    value,
                    base_url=f"http://127.0.0.1:{candidate_port}",
                    slug=spatial_slug,
                    viewer_relpath=spatial_viewer_relpath,
                    route_labels=list(spatial_route_labels or []),
                    candidate_commit=source_revision,
                    oci_image_id=image_id,
                    serving_container_id=str(gateway_id or ""),
                    package_sha256=spatial_package_sha256,
                )
            except (RuntimeError, TypeError, ValueError):
                return False
            version = value.get("candidate_version")
            oci_image = value.get("candidate_oci_image")
            serving = value.get("serving_container")
            package = value.get("package_binding")
            return (
                version == expected_runtime_version
                and isinstance(oci_image, dict)
                and oci_image
                == {
                    "image_id": image_id,
                    "oci_image_revision": source_revision,
                    "revision_source": "docker_image_inspect_by_immutable_id",
                    "immutable_image_id_verified": True,
                }
                and isinstance(serving, dict)
                and serving.get("container_id") == gateway_id
                and serving.get("image_id") == image_id
                and serving.get("compose_project") == candidate_project
                and serving.get("compose_service") == "gateway"
                and serving.get("running") is True
                and serving.get("container_port") == 18090
                and serving.get("host_ip") == "127.0.0.1"
                and serving.get("host_port") == candidate_port
                and serving.get("exact_loopback_publication_verified") is True
                and serving.get("inspection_source")
                == "docker_container_inspect_by_immutable_id"
                and value.get("package_sha256") == spatial_package_sha256
                and isinstance(package, dict)
                and package.get("package_sha256") == spatial_package_sha256
                and package.get("local_files") == observed_spatial_local_files
                and package.get("tour_manifest_sha256")
                == observed_spatial_tour_sha256
            )

        def valid_spatial_runtime(value: Mapping[str, Any]) -> bool:
            routes = value.get("routes")
            if not isinstance(routes, dict):
                return False
            quoted_slug = urllib.parse.quote(spatial_slug, safe="")
            expected_paths = {
                "html": f"/tours/{quoted_slug}",
                "json": f"/tours/{quoted_slug}.json",
                "viewer": (
                    f"/tours/viewer/{quoted_slug}/"
                    f"{urllib.parse.quote(spatial_viewer_relpath, safe='/')}"
                ),
                "proof_only": (
                    f"/tours/viewer/{quoted_slug}/"
                    f"{urllib.parse.quote(spatial_proof_relpath, safe='/')}"
                ),
            }
            if set(routes) != {
                f"{label}_{method}"
                for label in expected_paths
                for method in ("get", "head")
            }:
                return False
            for label, path in expected_paths.items():
                expected_status = 404 if label == "proof_only" else 200
                for method in ("get", "head"):
                    row = routes.get(f"{label}_{method}")
                    if (
                        not isinstance(row, dict)
                        or set(row) != {"path", "status", "content_type"}
                        or row.get("path") != path
                        or row.get("status") != expected_status
                        or not str(row.get("content_type") or "")
                    ):
                        return False
            return (
                set(value)
                == {
                    "included",
                    "routes_required",
                    "slug",
                    "routes",
                    "generated_viewer_release_verifier",
                    "candidate_browser_gate",
                    "html_json_viewer_200",
                    "proof_only_404",
                    "ea_public_activation_authority",
                    "upstream_public_activation_authority",
                }
                and value.get("included") is True
                and value.get("routes_required") is True
                and value.get("slug") == spatial_slug
                and passing_spatial_verifier(
                    value.get("generated_viewer_release_verifier")
                )
                and valid_spatial_browser(value.get("candidate_browser_gate"))
                and value.get("html_json_viewer_200") is True
                and value.get("proof_only_404") is True
                and value.get("ea_public_activation_authority") is False
                and value.get("upstream_public_activation_authority") is True
            )
        if (
            str(payload.get("schema") or "")
            != "ea.manfred_memorial_candidate_runtime.v4"
            or str(payload.get("status") or "").lower() != "pass"
            or str(payload.get("image") or "") != str(candidate.get("reference") or "")
            or str(payload.get("image_id") or "")
            != str(candidate.get("image_id") or "")
            or str(payload.get("image_source_revision") or "") != source_revision
            or locator
            != {
                "locator": image_reference,
                "resolved_image_id": image_id,
                "revision_label": source_revision,
                "used_for_attestation_only": True,
                "consumed_by_compose": False,
            }
            or payload.get("compose_uses_immutable_image_id") is not True
            or str(payload.get("runtime_source_revision") or "") != source_revision
            or payload.get("runtime_revision_matches_image") is not True
            or str(payload.get("projection_commit") or "") != source_revision
            or str(payload.get("prepared_image_locator") or "")
            != str(candidate.get("reference") or "")
            or str(payload.get("prepared_image_id") or "")
            != str(candidate.get("image_id") or "")
            or payload.get("projection_tree_revalidated") is not True
            or type(expected_projection_count) is not int
            or int(expected_projection_count) < 0
            or type(expected_projection_bytes) is not int
            or int(expected_projection_bytes) < 0
            or not isinstance(payload.get("projection_files"), list)
            or payload.get("live_ea_api_unchanged") is not True
            or payload.get("live_ea_project_unchanged") is not True
            or payload.get("provider_calls_performed") is not False
            or str(payload.get("release_id") or "") != expected_data_root.name
            or candidate_release_root != expected_data_root
            or SHA256_HEX_PATTERN.fullmatch(str(payload.get("projection_sha256") or ""))
            is None
            or not candidate_project.startswith("ea-manfred-candidate-")
            or len(candidate_project) > 63
            or len(candidate_project_suffix) < 8
            or re.fullmatch(r"[a-z0-9][a-z0-9-]*", candidate_project_suffix) is None
            or payload.get("compose_project_isolated") is not True
            or payload.get("compose_environment_bound_to_candidate_env") is not True
            or type(candidate_port) is not int
            or not 1024 <= int(candidate_port) <= 65535
            or candidate_preflight.get("project") != candidate_project
            or type(candidate_preflight.get("containers")) is not int
            or candidate_preflight["containers"] != 0
            or type(candidate_preflight.get("networks")) is not int
            or candidate_preflight["networks"] != 0
            or type(candidate_preflight.get("volumes")) is not int
            or candidate_preflight["volumes"] != 0
            or candidate_preflight.get("named_container_collisions") != []
            or candidate_preflight.get("named_network_collisions") != []
            or candidate_preflight.get("named_volume_collisions") != []
            or candidate_preflight.get("loopback_host") != "127.0.0.1"
            or candidate_preflight.get("loopback_port") != candidate_port
            or candidate_preflight.get("loopback_port_free_before_start") is not True
            or project_lock.get("scope") != "compose_project"
            or project_lock.get("project") != candidate_project
            or project_lock.get("held_through_candidate_proof") is not True
            or port_lock.get("scope") != "host_loopback_port"
            or port_lock.get("port") != candidate_port
            or port_lock.get("held_through_candidate_proof") is not True
            or top_project_lock != project_lock
            or top_port_lock != port_lock
            or fleet_lock
            != {
                "scope": "manfred_candidate_fleet",
                "lock_file": "ea-manfred-candidate-fleet.lock",
                "exclusive": True,
                "nonblocking": True,
                "held_through_candidate_proof": True,
            }
            or not valid_container_images(initial_container_images)
            or not valid_container_images(final_container_images)
            or not valid_container_images(container_images)
            or initial_container_images != final_container_images
            or container_images != final_container_images
            or payload.get("candidate_container_image_identity_stable") is not True
            or str(container_images.get("prepared_image_id") or "")
            != str(candidate.get("image_id") or "")
            or str(container_images.get("revision_label") or "") != source_revision
            or container_images.get("all_match_prepared_image") is not True
            or not str(candidate_api_image.get("container_id") or "").strip()
            or str(candidate_api_image.get("image_id") or "")
            != str(candidate.get("image_id") or "")
            or not str(candidate_gateway_image.get("container_id") or "").strip()
            or str(candidate_gateway_image.get("image_id") or "")
            != str(candidate.get("image_id") or "")
            or candidate_api_image.get("container_id")
            == candidate_gateway_image.get("container_id")
            or not valid_runtime_projection(runtime_projection_initial)
            or not valid_runtime_projection(runtime_projection_final)
            or runtime_projection_initial != runtime_projection_final
            or payload.get("runtime_projection_identity_stable") is not True
            or runtime_version != expected_runtime_version
            or str(payload.get("runtime_authority_commit") or "")
            != source_revision
            or not valid_compose_attestation(compose_attestation)
            or not valid_execution_inputs(execution_inputs)
            or not valid_runtime_posture(runtime_api_posture)
            or not valid_registry_recovery(registry_recovery)
            or not valid_spatial_projection(spatial_projection)
            or not valid_spatial_runtime(spatial_runtime)
            or named_resources != expected_named_resources
            or payload.get("api_network_internal") is not True
            or payload.get("gateway_has_runtime_secrets") is not False
            or payload.get("provider_credentials_present") is not False
            or not str(payload.get("candidate_api_container_id") or "").strip()
            or payload.get("candidate_api_container_id")
            != candidate_api_image.get("container_id")
            or payload.get("candidate_left_running_for_soak") is not True
            or payload.get("promotion_authority") is not False
            or str(browser.get("status") or "").lower() != "pass"
            or not _has_exact_zero_browser_counts(browser)
            or not required_smoke_checks <= first_checks
            or not required_smoke_checks <= second_checks
            or openapi.get("retirement_policy_id") != OPENAPI_RETIREMENT_POLICY_ID
            or openapi.get("retirement_allowed_operations")
            != list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
            or openapi.get("retired_operations")
            != list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
            or type(openapi.get("retired_operation_count")) is not int
            or openapi["retired_operation_count"]
            != len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
            or openapi.get("retirement_policy_exact_match") is not True
            or openapi.get("compatible_evolution_policy_id")
            != OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID
            or openapi.get("compatible_evolution_allowed_operations")
            != list(OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS)
            or not isinstance(openapi.get("compatible_evolved_operations"), list)
            or any(
                type(operation) is not str
                for operation in openapi["compatible_evolved_operations"]
            )
            or openapi.get("compatible_evolved_operations")
            != sorted(set(openapi["compatible_evolved_operations"]))
            or any(
                operation not in OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS
                for operation in openapi["compatible_evolved_operations"]
            )
            or type(openapi.get("compatible_evolved_operation_count")) is not int
            or openapi.get("compatible_evolved_operation_count")
            != len(openapi["compatible_evolved_operations"])
            or openapi.get("compatible_evolution_policy_exact_match") is not True
            or openapi.get("candidate_preserves_live_contract") is not True
            or type(openapi.get("missing_or_changed_operation_count")) is not int
            or openapi["missing_or_changed_operation_count"] != 0
            or type(openapi.get("missing_or_changed_schema_count")) is not int
            or openapi["missing_or_changed_schema_count"] != 0
            or type(openapi.get("missing_or_changed_security_scheme_count")) is not int
            or openapi["missing_or_changed_security_scheme_count"] != 0
            or not valid_openapi_snapshot(live_openapi_before)
            or not valid_openapi_snapshot(
                candidate_openapi, candidate_snapshot=True
            )
            or not valid_candidate_openapi_public_endpoint(
                candidate_openapi_public_endpoint
            )
            or not valid_openapi_snapshot(live_openapi_after)
            or live_openapi_before != live_openapi_after
            or int(candidate_openapi.get("path_count") or 0)
            < max(
                0,
                int(live_openapi_before.get("path_count") or 0)
                - len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
            )
            or int(candidate_openapi.get("operation_count") or 0)
            < max(
                0,
                int(live_openapi_before.get("operation_count") or 0)
                - len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
            )
            or int(candidate_openapi.get("schema_count") or 0)
            < int(live_openapi_before.get("schema_count") or 0)
            or int(candidate_openapi.get("security_scheme_count") or 0)
            < int(live_openapi_before.get("security_scheme_count") or 0)
            or live_before.get("project") != PROJECT_NAME
            or live_before != live_after
            or not isinstance(live_containers, list)
            or not isinstance(live_networks, list)
            or not isinstance(live_volumes, list)
            or any(not isinstance(row, dict) for row in live_containers)
            or any(not isinstance(row, dict) for row in live_networks)
            or any(not isinstance(row, dict) for row in live_volumes)
            or len(live_api_rows) != 1
            or payload.get("live_ea_api") != live_api_rows[0]
            or live_api_rows[0].get("running") is not True
            or live_api_rows[0].get("health") != "healthy"
            or payload.get("live_ea_api_unchanged") is not True
            or payload.get("live_ea_project_unchanged") is not True
        ):
            raise DeployError("memorial_candidate_receipt_contract_invalid")
        try:
            projection_sha256, projection_files = _candidate_projection_tree_digest(
                expected_data_root
            )
        except (OSError, ValueError) as exc:
            raise DeployError("memorial_candidate_projection_unverifiable") from exc
        projection_bytes = sum(int(item["size_bytes"]) for item in projection_files)
        if (
            projection_sha256 != str(payload.get("projection_sha256") or "")
            or payload.get("projection_files") != projection_files
            or expected_projection_count != len(projection_files)
            or expected_projection_bytes != projection_bytes
        ):
            raise DeployError("memorial_candidate_projection_digest_mismatch")
        evidence = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "schema": "ea.manfred_memorial_candidate_runtime.v4",
            "status": "pass",
            "image": str(candidate.get("reference") or ""),
            "image_id": str(candidate.get("image_id") or ""),
            "source_revision": source_revision,
            "release_root": str(candidate_release_root),
            "runtime_revision_matches_image": True,
            "image_locator_revalidated": True,
            "live_ea_unchanged": True,
            "provider_calls_performed": False,
            "projection": {
                "release_id": expected_data_root.name,
                "release_root": str(expected_data_root),
                "commit": source_revision,
                "prepared_image_id": str(candidate.get("image_id") or ""),
                "projection_sha256": projection_sha256,
                "file_count": len(projection_files),
                "projection_bytes": projection_bytes,
                "tree_revalidated": True,
            },
            "compose_project": candidate_project,
            "candidate_port": candidate_port,
            "candidate_preflight_clean": True,
            "locks": {"project_held": True, "port_held": True},
            "candidate_container_images": {
                "api_image_id": str(candidate.get("image_id") or ""),
                "gateway_image_id": str(candidate.get("image_id") or ""),
                "all_match_prepared_image": True,
                "identity_stable": True,
            },
            "runtime_identity": {
                "source_revision": source_revision,
                "authority_commit": source_revision,
                "oci_image_revision": source_revision,
                "revision_agreement_verified": True,
            },
            "execution_inputs": {
                "schema": "ea.manfred_candidate_execution_inputs.v1",
                "compose_sha256": str(execution_inputs["compose_sha256"]),
                "compose_size_bytes": int(execution_inputs["compose_size_bytes"]),
                "environment_sha256": str(execution_inputs["environment_sha256"]),
                "environment_size_bytes": int(
                    execution_inputs["environment_size_bytes"]
                ),
                "compose_image_id": image_id,
                "sealed": True,
            },
            "runtime_posture": {
                "schema": "ea.manfred_candidate_api_runtime_posture.v1",
                "environment_sha256": str(
                    runtime_api_posture["environment_sha256"]
                ),
                "mount_count": len(list(runtime_api_posture["mounts"])),
                "network": f"{candidate_project}_backend",
                "hardened": True,
            },
            "registry_recovery": {
                "state_before_launch": str(
                    registry_recovery["state_before_launch"]
                ),
                "safe": True,
            },
            "spatial_handoff": {
                "slug": spatial_slug,
                "route_count": 8,
                "html_json_viewer_200": True,
                "proof_only_404": True,
                "release_verifier_pass": True,
                "browser_schema": "ea.manfred_spatial_candidate_browser.v4",
                "browser_pass": True,
                "identity_bound": True,
                "package_sha256": spatial_package_sha256,
            },
            "live_ea": {
                "snapshot_sha256": _canonical_json_sha256(live_before),
                "api_sha256": _canonical_json_sha256(live_api_rows[0]),
                "container_count": len(live_containers),
                "network_count": len(live_networks),
                "volume_count": len(live_volumes),
                "unchanged": True,
            },
            "openapi": {
                "live": live_openapi_before,
                "candidate": candidate_openapi,
                "retirement_policy_id": OPENAPI_RETIREMENT_POLICY_ID,
                "retirement_allowed_operations": list(
                    OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                ),
                "retired_operations": list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
                "retired_operation_count": len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
                "retirement_policy_exact_match": True,
                "compatible_evolution_policy_id": (
                    OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID
                ),
                "compatible_evolution_allowed_operations": list(
                    OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS
                ),
                "compatible_evolved_operations": list(
                    openapi["compatible_evolved_operations"]
                ),
                "compatible_evolved_operation_count": int(
                    openapi["compatible_evolved_operation_count"]
                ),
                "compatible_evolution_policy_exact_match": True,
                "candidate_public_openapi_retired": True,
                "candidate_preserves_live_contract": True,
                "missing_or_changed_operation_count": 0,
                "missing_or_changed_schema_count": 0,
                "missing_or_changed_security_scheme_count": 0,
            },
            "browser": {
                "status": "pass",
                "automatic_provider_requests": 0,
                "automatic_websockets": 0,
                "external_requests": 0,
                "failed_requests": 0,
                "page_errors": 0,
                "http_errors": 0,
            },
        }
        self.receipt["candidate_promotion_evidence"] = evidence
        self._record_check("candidate_promotion_evidence", "pass")
        return evidence

    def _release_source_metadata(self) -> dict[str, str]:
        self.durable_root_check(self.root)
        branch_result = self._run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], check=False
        )
        branch = branch_result.stdout.strip()
        if branch_result.returncode != 0 or not branch or branch == "HEAD":
            raise DeployError("release_branch_detached")
        upstream_result = self._run(
            [
                "git",
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            ],
            check=False,
        )
        upstream = upstream_result.stdout.strip()
        if upstream_result.returncode != 0 or not upstream or upstream == "HEAD":
            raise DeployError("release_branch_upstream_missing")
        source_revision = self._git_head()
        metadata = {
            "branch": branch,
            "upstream": upstream,
            "source_revision": source_revision,
            "release_root": str(self.root),
        }
        self.receipt["release_source"] = metadata
        self._write_receipt()
        return metadata

    @staticmethod
    def _sanitized_previous_api(previous: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value for key, value in previous.items() if key != "mount_identities"
        }

    def _verify_forward_api(
        self,
        *,
        candidate: Mapping[str, Any],
        source_revision: str,
        expected_mounts: Sequence[Mapping[str, object]],
        expected_projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        inspection = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            inspection, service=API_SERVICE, reason_prefix="deployed_api"
        )
        topology = self._compose_topology(inspection, reason_prefix="deployed_api")
        expected_files = [
            str((self.root / filename).resolve())
            for filename in self.target_compose_files
        ]
        if topology["working_dir"] != str(self.root):
            raise DeployError("deployed_api_working_dir_mismatch")
        if topology["compose_config_files"] != expected_files:
            raise DeployError("deployed_api_compose_topology_mismatch")
        image_id = str(inspection.get("Image") or "").strip()
        if image_id != str(candidate.get("image_id") or ""):
            raise DeployError("deployed_api_image_mismatch")
        config = dict(inspection.get("Config") or {})
        if str(config.get("Image") or "").strip() != str(
            candidate.get("reference") or ""
        ):
            raise DeployError("deployed_api_image_reference_mismatch")
        container_env = {
            str(item).split("=", 1)[0]: str(item).split("=", 1)[1]
            for item in list(config.get("Env") or [])
            if "=" in str(item)
        }
        if container_env.get("EA_SOURCE_REVISION") != source_revision:
            raise DeployError("deployed_api_source_revision_env_mismatch")
        mount_identities = _mount_identities(inspection)
        normalized_expected_mounts = [dict(item) for item in expected_mounts]
        if not normalized_expected_mounts:
            raise DeployError("deployed_api_expected_mounts_missing")
        if mount_identities != normalized_expected_mounts:
            raise DeployError("deployed_api_source_mounts_mismatch")
        memorial_data_root = self._configured_memorial_data_root()
        source_mount_destinations: list[str] = []
        for item in normalized_expected_mounts:
            if str(item["type"]) != "bind":
                continue
            source = Path(str(item["source"])).resolve()
            if (
                source == memorial_data_root
                or source == self.root
                or self.root in source.parents
            ):
                source_mount_destinations.append(str(item["destination"]))
        mounted_projection = self._mounted_projection_digest(expected_projection)
        if mounted_projection != {
            "projection_sha256": str(
                expected_projection.get("projection_sha256") or ""
            ),
            "file_count": expected_projection.get("file_count"),
            "projection_bytes": expected_projection.get("projection_bytes"),
        }:
            raise DeployError("deployed_api_projection_digest_mismatch")
        return {
            "image_id": image_id,
            "image_reference": str(candidate.get("reference") or ""),
            "working_dir": topology["working_dir"],
            "compose_config_files": topology["compose_config_files"],
            "mount_identity_sha256": _identity_digest(mount_identities),
            "mount_identity_count": len(mount_identities),
            "matches_rendered_compose_mounts": True,
            "source_mount_destinations": sorted(source_mount_destinations),
            "source_revision": source_revision,
            "mounted_projection": mounted_projection,
            **_container_runtime_config_digests(inspection),
        }

    def _mounted_projection_digest(
        self, expected_projection: Mapping[str, Any]
    ) -> dict[str, Any]:
        expected_file_count = expected_projection.get("file_count")
        expected_projection_bytes = expected_projection.get("projection_bytes")
        if (
            type(expected_file_count) is not int
            or int(expected_file_count) < 0
            or type(expected_projection_bytes) is not int
            or int(expected_projection_bytes) < 0
        ):
            raise DeployError("deployed_api_projection_expectation_invalid")
        completed = self._run(
            [
                "/usr/bin/timeout",
                "--signal=KILL",
                "30s",
                "docker",
                "exec",
                API_SERVICE,
                "python3",
                "-c",
                CONTAINER_PROJECTION_DIGEST_SCRIPT,
                "/data/memorial_data",
                str(expected_file_count),
                str(expected_projection_bytes),
            ],
            check=False,
        )
        if completed.returncode != 0:
            verifier_failures = {
                10: "root_invalid",
                11: "directory_mode_invalid",
                12: "entry_invalid",
                13: "file_mode_invalid",
                14: "tree_changed",
                15: "file_links_invalid",
                16: "budget_exceeded",
                17: "expectation_mismatch",
                18: "deadline_exceeded",
                124: "host_timeout",
                137: "host_timeout",
            }
            reason = verifier_failures.get(completed.returncode, "command_failed")
            raise DeployError(f"deployed_api_projection_verifier_failed:{reason}")
        payload = _json_object(
            completed.stdout,
            reason="deployed_api_projection_digest_invalid",
        )
        if (
            set(payload) != {"projection_sha256", "file_count", "projection_bytes"}
            or SHA256_HEX_PATTERN.fullmatch(str(payload.get("projection_sha256") or ""))
            is None
            or type(payload.get("file_count")) is not int
            or int(payload["file_count"]) < 0
            or type(payload.get("projection_bytes")) is not int
            or int(payload["projection_bytes"]) < 0
        ):
            raise DeployError("deployed_api_projection_digest_invalid")
        return payload

    def _previous_api(self) -> dict[str, Any]:
        inspection = self._inspect_container(API_SERVICE)
        config = dict(inspection.get("Config") or {})
        self._require_compose_identity(
            inspection, service=API_SERVICE, reason_prefix="prior_api"
        )
        image_id = str(inspection.get("Image") or "").strip()
        if not IMAGE_ID_PATTERN.fullmatch(image_id):
            raise DeployError("prior_api_image_missing")
        image_reference = _safe_tagged_image_reference(
            str(config.get("Image") or ""),
            reason="prior_api_image_reference_unrestorable",
        )
        state = dict(inspection.get("State") or {})
        health = str(dict(state.get("Health") or {}).get("Status") or "")
        if (
            not bool(state.get("Running"))
            or bool(state.get("Restarting"))
            or health != "healthy"
        ):
            raise DeployError("prior_api_not_healthy")
        topology = self._compose_topology(inspection, reason_prefix="prior_api")
        working_dir = Path(str(topology["working_dir"]))
        env_path = working_dir / ".env"
        if not env_path.is_file():
            raise DeployError(f"prior_api_rollback_input_missing:{env_path}")
        mount_identities = _mount_identities(inspection)
        runtime_config = _container_runtime_config_digests(inspection)
        return {
            "container_id": str(inspection.get("Id") or ""),
            "created_at": str(inspection.get("Created") or ""),
            "image_id": image_id,
            "image_reference": image_reference,
            "working_dir": str(working_dir),
            "compose_config_files": topology["compose_config_files"],
            "mount_identities": mount_identities,
            "mount_identity_sha256": _identity_digest(mount_identities),
            "mount_identity_count": len(mount_identities),
            **runtime_config,
            "state": {
                "running": bool(state.get("Running")),
                "restarting": bool(state.get("Restarting")),
                "started_at": str(state.get("StartedAt") or ""),
                "health": health,
            },
        }

    def _container_ready(
        self, name: str, *, require_health: bool
    ) -> tuple[bool, dict[str, str]]:
        inspection = self._inspect_container(name)
        state = dict(inspection.get("State") or {})
        health = dict(state.get("Health") or {})
        detail = {
            "running": str(bool(state.get("Running"))).lower(),
            "restarting": str(bool(state.get("Restarting"))).lower(),
            "health": str(health.get("Status") or ""),
            "image_id": str(inspection.get("Image") or ""),
        }
        ready = bool(state.get("Running")) and not bool(state.get("Restarting"))
        if require_health:
            ready = ready and detail["health"] == "healthy"
        elif detail["health"]:
            ready = ready and detail["health"] == "healthy"
        return ready, detail

    def _wait_container(self, name: str, *, require_health: bool) -> dict[str, str]:
        deadline = self.monotonic() + self.wait_seconds
        last_detail: dict[str, str] = {}
        while True:
            try:
                ready, last_detail = self._container_ready(
                    name, require_health=require_health
                )
                if ready:
                    return last_detail
            except DeployError as exc:
                last_detail = {"error": str(exc)}
            if self.monotonic() >= deadline:
                raise DeployError(
                    f"container_not_ready:{name}:{json.dumps(last_detail, sort_keys=True)}"
                )
            self.sleep(self.poll_seconds)

    def _ensure_redis(self) -> None:
        inspection = self._inspect_container_optional(REDIS_SERVICE)
        action = "already_healthy"
        if inspection is None:
            action = "created_missing"
            self._run(
                self._target_compose(
                    "up", "-d", "--no-build", "--no-deps", REDIS_SERVICE
                )
            )
        else:
            self._require_compose_identity(
                inspection, service=REDIS_SERVICE, reason_prefix="redis"
            )
            state = dict(inspection.get("State") or {})
            health = str(dict(state.get("Health") or {}).get("Status") or "")
            running = bool(state.get("Running"))
            restarting = bool(state.get("Restarting"))
            if running and not restarting and health == "healthy":
                self._record_check("redis", "pass", action=action, health=health)
                return
            if not running and not restarting:
                action = "started_existing"
                self._run(["docker", "start", REDIS_SERVICE])
            else:
                action = "waited_for_existing"
        detail = self._wait_container(REDIS_SERVICE, require_health=True)
        final_inspection = self._inspect_container(REDIS_SERVICE)
        self._require_compose_identity(
            final_inspection, service=REDIS_SERVICE, reason_prefix="redis"
        )
        self._record_check("redis", "pass", action=action, **detail)

    def _git_head(self) -> str:
        head = self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise DeployError("git_head_invalid")
        return head

    def _bind_source_revision(self, source_revision: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
            raise DeployError("git_head_invalid")
        self.release_env["EA_SOURCE_REVISION"] = source_revision
        self.receipt["source_revision"] = source_revision
        self._write_receipt()
        return source_revision

    def _protect_previous_image(self, previous: Mapping[str, Any]) -> str:
        rollback_tag = _safe_rollback_tag(self.deployment_id)
        self._run(["docker", "image", "tag", str(previous["image_id"]), rollback_tag])
        protected = self._inspect_image(rollback_tag)
        if protected["image_id"] != str(previous["image_id"]):
            raise DeployError("rollback_image_protection_mismatch")
        return rollback_tag

    def _recreate_api(self) -> None:
        self._run(
            self._target_compose(
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                API_SERVICE,
            )
        )

    def _local_origin(self) -> str:
        host_port = _first_nonempty(
            self.env.get("EA_HOST_PORT"),
            self.env_file_values.get("EA_HOST_PORT"),
            "8090",
        )
        if not host_port.isdigit() or not 1 <= int(host_port) <= 65535:
            raise DeployError("ea_host_port_invalid")
        return f"http://127.0.0.1:{host_port}"

    def _wait_http(
        self, url: str, *, kind: str, expected_source_revision: str = ""
    ) -> dict[str, Any]:
        deadline = self.monotonic() + self.wait_seconds
        last_error = ""
        while True:
            try:
                response = self.http_get(url, self.request_timeout_seconds)
                if response.status != 200:
                    raise DeployError(f"http_status_invalid:{url}:{response.status}")
                if (
                    expected_source_revision
                    and response.source_revision != expected_source_revision
                ):
                    raise DeployError(f"source_revision_mismatch:{url}")
                if kind == "html":
                    lowered = response.body.lower()
                    decoded = response.body.decode("utf-8", errors="replace").casefold()
                    if b"manfred" not in lowered or not (
                        "text/html" in response.content_type.lower()
                        or b"<html" in lowered
                        or b"<!doctype html" in lowered
                    ):
                        raise DeployError(f"memorial_html_contract_invalid:{url}")
                    if (
                        "ist nicht manfred" not in decoded
                        or "spricht nicht für ihn" not in decoded
                    ):
                        raise DeployError(f"memorial_transparency_marker_missing:{url}")
                    if "ich bin manfred" in decoded:
                        raise DeployError(
                            f"memorial_impersonation_marker_present:{url}"
                        )
                elif kind == "control_html":
                    lowered = response.body.lower()
                    if not (
                        "text/html" in response.content_type.lower()
                        or b"<html" in lowered
                        or b"<!doctype html" in lowered
                    ):
                        raise DeployError(f"control_html_contract_invalid:{url}")
                elif kind == "json":
                    manifest = _json_object(
                        response.body.decode("utf-8"),
                        reason=f"memorial_json_invalid:{url}",
                    )
                    if str(manifest.get("slug") or "") != MEMORIAL_SLUG:
                        raise DeployError(f"memorial_json_slug_mismatch:{url}")
                    combined_disclosure = " ".join(
                        str(manifest.get(key) or "") for key in ("intro", "disclosure")
                    ).casefold()
                    if (
                        "ist nicht manfred" not in combined_disclosure
                        or "spricht nicht für ihn" not in combined_disclosure
                    ):
                        raise DeployError(f"memorial_transparency_marker_missing:{url}")
                    if "ich bin manfred" in combined_disclosure:
                        raise DeployError(
                            f"memorial_impersonation_marker_present:{url}"
                        )
                return {
                    "url": url,
                    "status_code": response.status,
                    "content_type": response.content_type,
                    "body_bytes": len(response.body),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "source_revision": response.source_revision,
                }
            except DeployError as exc:
                last_error = str(exc)
            if self.monotonic() >= deadline:
                raise DeployError(f"http_probe_exhausted:{url}:{last_error}")
            self.sleep(self.poll_seconds)

    def _verify_singular_memorial_alias(self, origin: str) -> dict[str, Any]:
        query = "from=ea-launch-verifier"
        url = f"{origin}/memorial/{MEMORIAL_SLUG}?{query}"
        expected_location = f"/memorials/{MEMORIAL_SLUG}?{query}"
        expected_headers = {
            "cache-control": "no-store",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
            "x-robots-tag": "noindex, nofollow",
        }
        methods: list[dict[str, Any]] = []
        for method in ("GET", "HEAD"):
            response = self.http_no_redirect(
                url,
                self.request_timeout_seconds,
                method,
            )
            headers = {
                str(name).strip().casefold(): str(value).strip()
                for name, value in dict(response.headers or {}).items()
            }
            if response.status != 308:
                raise DeployError("memorial_alias_status_invalid")
            if headers.get("location") != expected_location:
                raise DeployError("memorial_alias_location_invalid")
            if any(
                headers.get(name, "").casefold() != value
                for name, value in expected_headers.items()
            ):
                raise DeployError("memorial_alias_headers_invalid")
            if method == "HEAD" and response.body:
                raise DeployError("memorial_alias_head_body_invalid")
            methods.append(
                {
                    "method": method,
                    "status_code": response.status,
                    "location": expected_location,
                    "headers": dict(expected_headers),
                    "body_bytes": len(response.body),
                }
            )
        return {
            "origin": origin,
            "alias_path": f"/memorial/{MEMORIAL_SLUG}",
            "canonical_path": f"/memorials/{MEMORIAL_SLUG}",
            "query_preserved": True,
            "methods": methods,
        }

    def _wait_json_control(self, url: str) -> tuple[dict[str, Any], dict[str, Any]]:
        deadline = self.monotonic() + self.wait_seconds
        last_error = ""
        while True:
            try:
                response = self.http_get(url, self.request_timeout_seconds)
                if response.status != 200:
                    raise DeployError(f"http_status_invalid:{url}:{response.status}")
                if len(response.body) > MAX_HTTP_BODY_BYTES:
                    raise DeployError(f"http_body_too_large:{url}")
                payload = _json_object(
                    response.body.decode("utf-8"),
                    reason=f"control_json_invalid:{url}",
                )
                return payload, {
                    "url": url,
                    "status_code": 200,
                    "content_type": str(response.content_type or "")[
                        :MAX_RECEIPT_CONTENT_TYPE_CHARS
                    ],
                    "body_bytes": len(response.body),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "canonical_json_sha256": _canonical_json_sha256(payload),
                }
            except (DeployError, UnicodeDecodeError) as exc:
                last_error = str(exc)
            if self.monotonic() >= deadline:
                raise DeployError(f"http_probe_exhausted:{url}:{last_error}")
            self.sleep(self.poll_seconds)

    def _capture_openapi_control(self) -> dict[str, Any]:
        url = f"{self._local_origin()}/openapi.json"
        payload, probe = self._wait_json_control(url)
        contract = _canonical_openapi_contract(payload)
        return {
            **_openapi_control_evidence(contract=contract, probe=probe),
            "_contract": contract,
        }

    @staticmethod
    def _sanitized_openapi_control(control: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in control.items() if key != "_contract"}

    @staticmethod
    def _sanitized_tour_control(control: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in control.items() if key != "_json_payload"}

    def _capture_non_memorial_controls(self) -> dict[str, Any]:
        controls: dict[str, Any] = {"openapi": self._capture_openapi_control()}
        predeploy_operations = dict(
            dict(controls["openapi"].get("_contract") or {}).get("operations") or {}
        )
        if not set(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS) <= set(predeploy_operations):
            raise DeployError("predeploy_openapi_retirement_operations_missing")
        if self.control_tour_slug:
            base = f"{self._local_origin()}/tours/{self.control_tour_slug}"
            html = self._wait_http(base, kind="control_html")
            payload, tour_json = self._wait_json_control(f"{base}.json")
            controls["tour"] = {
                "slug": self.control_tour_slug,
                "html": html,
                "json": tour_json,
                "_json_payload": payload,
            }
        receipt_controls: dict[str, Any] = {
            "openapi": self._sanitized_openapi_control(controls["openapi"]),
        }
        if "tour" in controls:
            receipt_controls["tour"] = self._sanitized_tour_control(controls["tour"])
        receipt_controls["openapi"]["retirement_policy_id"] = (
            OPENAPI_RETIREMENT_POLICY_ID
        )
        receipt_controls["openapi"]["retirement_allowed_operations"] = list(
            OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
        )
        self.receipt["predeploy_non_memorial_controls"] = receipt_controls
        self._record_check(
            "predeploy_non_memorial_controls",
            "pass",
            openapi_path_count=controls["openapi"]["path_count"],
            tour_slug=self.control_tour_slug or None,
        )
        return controls

    def _verify_non_memorial_controls(self, baseline: Mapping[str, Any]) -> None:
        prior_openapi = dict(baseline.get("openapi") or {})
        prior_contract_value = prior_openapi.get("_contract")
        prior_contract = (
            dict(prior_contract_value) if isinstance(prior_contract_value, dict) else {}
        )
        prior_operations = dict(prior_contract.get("operations") or {})
        prior_schemas = dict(prior_contract.get("schemas") or {})
        prior_security = dict(prior_contract.get("security_schemes") or {})
        if not prior_operations:
            raise DeployError("predeploy_openapi_contract_invalid")
        current_openapi = self._capture_openapi_control()
        current_contract = dict(current_openapi.get("_contract") or {})
        current_operations = dict(current_contract.get("operations") or {})
        current_schemas = dict(current_contract.get("schemas") or {})
        current_security = dict(current_contract.get("security_schemes") or {})
        missing_operations = sorted(set(prior_operations) - set(current_operations))
        if missing_operations != list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS):
            raise DeployError("postdeploy_openapi_operation_retirement_mismatch")
        missing_or_changed_schemas = sorted(
            name
            for name, value in prior_schemas.items()
            if name not in current_schemas or current_schemas[name] != value
        )
        if missing_or_changed_schemas:
            raise DeployError("postdeploy_openapi_schema_regression")
        missing_or_changed_security = sorted(
            name
            for name, value in prior_security.items()
            if name not in current_security or current_security[name] != value
        )
        if missing_or_changed_security:
            raise DeployError("postdeploy_openapi_security_regression")
        changed_operations = sorted(
            name
            for name, value in prior_operations.items()
            if name in current_operations and current_operations[name] != value
        )
        if changed_operations:
            raise DeployError("postdeploy_openapi_operation_changed")

        evidence: dict[str, Any] = {
            "openapi": {
                **self._sanitized_openapi_control(current_openapi),
                "baseline_path_count": int(prior_openapi.get("path_count") or 0),
                "baseline_operation_count": len(prior_operations),
                "added_path_count": len(
                    set(current_openapi.get("paths") or [])
                    - set(prior_openapi.get("paths") or [])
                ),
                "added_operation_count": len(
                    set(current_operations) - set(prior_operations)
                ),
                "retirement_policy_id": OPENAPI_RETIREMENT_POLICY_ID,
                "retirement_allowed_operations": list(
                    OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                ),
                "retired_operations": missing_operations,
                "retired_operation_count": len(missing_operations),
                "retirement_policy_exact_match": True,
                "changed_operation_count": 0,
                "missing_or_changed_schema_count": 0,
                "missing_or_changed_security_scheme_count": 0,
            }
        }
        prior_tour = baseline.get("tour")
        if prior_tour is not None:
            prior_tour = dict(prior_tour)
            slug = str(prior_tour.get("slug") or "")
            if (
                slug != self.control_tour_slug
                or not CONTROL_TOUR_SLUG_PATTERN.fullmatch(slug)
            ):
                raise DeployError("predeploy_control_tour_invalid")
            base = f"{self._local_origin()}/tours/{slug}"
            html = self._wait_http(base, kind="control_html")
            payload, tour_json = self._wait_json_control(f"{base}.json")
            prior_json = dict(prior_tour.get("json") or {})
            prior_payload = prior_tour.get("_json_payload")
            if (
                not isinstance(prior_payload, dict)
                or payload != prior_payload
                or tour_json["canonical_json_sha256"]
                != prior_json.get("canonical_json_sha256")
            ):
                raise DeployError("postdeploy_control_tour_json_changed")
            evidence["tour"] = {"slug": slug, "html": html, "json": tour_json}

        self.receipt["postdeploy_non_memorial_controls"] = evidence
        self._record_check(
            "postdeploy_non_memorial_controls",
            "pass",
            openapi_path_count=current_openapi["path_count"],
            tour_slug=self.control_tour_slug or None,
        )

    def _verify_deployed_surface(
        self, public_origin: str, *, source_revision: str
    ) -> None:
        local = self._local_origin()
        probes = [
            self._wait_http(f"{local}/health", kind="health"),
            self._wait_http(
                f"{local}/memorials/{MEMORIAL_SLUG}",
                kind="html",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{local}/memorials/{MEMORIAL_SLUG}.json",
                kind="json",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{public_origin}/memorials/{MEMORIAL_SLUG}",
                kind="html",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{public_origin}/memorials/{MEMORIAL_SLUG}.json",
                kind="json",
                expected_source_revision=source_revision,
            ),
        ]
        alias_probes = [
            self._verify_singular_memorial_alias(local),
            self._verify_singular_memorial_alias(public_origin),
        ]
        if probes[2]["body_sha256"] != probes[4]["body_sha256"]:
            raise DeployError("public_memorial_manifest_differs_from_local")
        self.receipt["probes"] = probes
        self.receipt["alias_probes"] = alias_probes
        self._record_check(
            "local_and_public_memorial",
            "pass",
            alias_method_probes=sum(
                len(list(item.get("methods") or [])) for item in alias_probes
            ),
        )

    def _verify_candidate_origin(
        self, *, label: str, base_url: str, public_origin: str
    ) -> dict[str, Any]:
        payload = self._run_json_script(
            "scripts/verify_manfred_memorial_candidate.py",
            "--base-url",
            base_url,
            "--public-origin",
            public_origin,
            "--wait-seconds",
            str(max(1, min(600, int(self.wait_seconds or 1)))),
            "--browser-audit",
            origin=label,
        )
        required_checks = {
            "archive_publication_gate",
            "singular_memorial_alias",
            "source_grounded_narrator_boundary",
            "voice_provider_boundary_blocked",
            "browser_provider_websocket_boundary",
        }
        checks = {
            str(item).strip()
            for item in list(payload.get("checks") or [])
            if str(item).strip()
        }
        browser = dict(payload.get("browser_audit") or {})
        if (
            str(payload.get("schema") or "") != "ea.manfred_memorial_candidate_smoke.v1"
            or str(payload.get("status") or "").lower() != "pass"
            or not required_checks <= checks
            or payload.get("provider_calls_performed") is not False
            or payload.get("page_get_performed") is not True
            or str(browser.get("status") or "").lower() != "pass"
            or not _has_exact_zero_browser_counts(browser)
        ):
            self._record_check(
                "candidate_verifier_origin",
                "fail",
                origin=label,
                error_code="candidate_verifier_contract_failed",
            )
            raise DeployError(f"candidate_verifier_contract_failed:{label}")
        return {
            "origin": label,
            "status": "pass",
            "checks": sorted(required_checks),
            "provider_calls_performed": False,
            "browser": {
                "automatic_provider_requests": 0,
                "automatic_websockets": 0,
                "external_requests": 0,
                "failed_requests": 0,
                "page_errors": 0,
                "http_errors": 0,
            },
        }

    def _verify_candidate_origins(self, public_origin: str) -> None:
        evidence = [
            self._verify_candidate_origin(
                label="local",
                base_url=self._local_origin(),
                public_origin=public_origin,
            )
        ]
        self.receipt["candidate_verifier"] = list(evidence)
        self._record_check("candidate_verifier_origin", "pass", origin="local")

        evidence.append(
            self._verify_candidate_origin(
                label="public",
                base_url=public_origin,
                public_origin=public_origin,
            )
        )
        self.receipt["candidate_verifier"] = evidence
        self._record_check("candidate_verifier_origin", "pass", origin="public")
        self._record_check("local_and_public_candidate_verifier", "pass")

    def _rollback(
        self,
        previous: Mapping[str, Any],
        rollback_tag: str,
        baseline: Mapping[str, Any],
        deployment_input_seal: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> dict[str, Any]:
        self._require_deployment_input_seal(deployment_input_seal, scope="rollback")
        prior_openapi_value = baseline.get("openapi")
        prior_openapi = (
            dict(prior_openapi_value) if isinstance(prior_openapi_value, dict) else {}
        )
        prior_contract_value = prior_openapi.get("_contract")
        prior_contract = (
            dict(prior_contract_value) if isinstance(prior_contract_value, dict) else {}
        )
        prior_operations = dict(prior_contract.get("operations") or {})
        if not prior_operations or not set(
            OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
        ) <= set(prior_operations):
            raise DeployError("rollback_openapi_baseline_invalid")
        rollback_root = Path(str(previous["working_dir"])).resolve()
        rollback_files = [
            str(item).strip()
            for item in list(previous.get("compose_config_files") or [])
            if str(item).strip()
        ]
        if not rollback_files:
            raise DeployError("rollback_compose_config_files_missing")
        protected = self._inspect_image(rollback_tag)
        if protected["image_id"] != str(previous["image_id"]):
            raise DeployError("rollback_protected_image_mismatch")
        prior_reference = _safe_tagged_image_reference(
            str(previous.get("image_reference") or ""),
            reason="rollback_image_reference_unrestorable",
        )
        rollback_env = self._rollback_environment()
        self._run(
            ["docker", "image", "tag", str(previous["image_id"]), prior_reference],
            env=rollback_env,
        )
        self._require_deployment_input_seal(deployment_input_seal, scope="rollback")
        self._run(
            self._rollback_compose(
                rollback_root,
                rollback_files,
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                API_SERVICE,
            ),
            cwd=rollback_root,
            env=rollback_env,
        )
        ready = self._wait_container(API_SERVICE, require_health=True)
        current = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            current, service=API_SERVICE, reason_prefix="rollback_api"
        )
        topology = self._compose_topology(current, reason_prefix="rollback_api")
        restored_image_id = str(current.get("Image") or "")
        if restored_image_id != str(previous["image_id"]):
            raise DeployError("rollback_image_mismatch")
        restored_reference = str(
            dict(current.get("Config") or {}).get("Image") or ""
        ).strip()
        if restored_reference != prior_reference:
            raise DeployError("rollback_image_reference_mismatch")
        if topology["working_dir"] != str(rollback_root):
            raise DeployError("rollback_working_dir_mismatch")
        if topology["compose_config_files"] != rollback_files:
            raise DeployError("rollback_compose_topology_mismatch")
        restored_mounts = _mount_identities(current)
        restored_mount_digest = _identity_digest(restored_mounts)
        if restored_mount_digest != str(previous.get("mount_identity_sha256") or ""):
            raise DeployError("rollback_mount_identity_mismatch")
        restored_runtime_config = _container_runtime_config_digests(current)
        if restored_runtime_config["environment_sha256"] != previous.get(
            "environment_sha256"
        ):
            raise DeployError("rollback_environment_identity_mismatch")
        if restored_runtime_config["environment_count"] != previous.get(
            "environment_count"
        ):
            raise DeployError("rollback_environment_identity_mismatch")
        if restored_runtime_config["process_config_sha256"] != previous.get(
            "process_config_sha256"
        ):
            raise DeployError("rollback_process_config_identity_mismatch")
        health_probe = self._wait_http(f"{self._local_origin()}/health", kind="health")
        restored_openapi = self._capture_openapi_control()
        restored_contract = dict(restored_openapi.get("_contract") or {})
        if restored_contract != prior_contract:
            raise DeployError("rollback_openapi_contract_mismatch")
        bounded_openapi_evidence = {
            key: restored_openapi[key]
            for key in (
                "path_count",
                "operation_count",
                "schema_count",
                "security_scheme_count",
                "path_set_sha256",
                "contract_sha256",
                "probe",
            )
        }
        return {
            "status": "pass",
            "completed_at": _utc_now(),
            "restored_image_id": restored_image_id,
            "working_dir": str(rollback_root),
            "compose_config_files": rollback_files,
            "image_reference": restored_reference,
            "mount_identity_sha256": restored_mount_digest,
            "mount_identity_count": len(restored_mounts),
            **restored_runtime_config,
            "container": ready,
            "health_probe": health_probe,
            "openapi": {
                **bounded_openapi_evidence,
                "matches_predeploy_contract": True,
                "retirement_policy_id": OPENAPI_RETIREMENT_POLICY_ID,
                "restored_retirement_operations": list(
                    OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                ),
            },
        }

    def preflight(self) -> dict[str, Any]:
        self._write_receipt()
        if not (self.root / ".env").is_file():
            raise DeployError("env_file_missing")
        if self.control_tour_slug != REQUIRED_CONTROL_TOUR_SLUG:
            raise DeployError("memorial_control_tour_slug_required")
        self._require_vexp_certification_token_coverage("preflight_entry")
        release_source = self._release_source_metadata()
        source_state = source_worktree_metadata(self.root, dirty_path_limit=10000)
        if bool(source_state.get("source_worktree_dirty")):
            raise DeployError("source_worktree_dirty")
        self.receipt["source_worktree"] = source_state
        self._write_receipt()
        self._detect_compose()
        previous = self._previous_api()
        self._configure_forward_topology(previous)
        rollback_render = self._verify_rollback_renderability(previous)
        source_revision = self._bind_source_revision(
            str(release_source["source_revision"])
        )
        candidate = self._resolve_candidate_image(source_revision)
        candidate_promotion = self._validate_candidate_promotion_receipt(
            candidate=candidate,
            source_revision=source_revision,
        )
        deployment_input_seal = self._capture_deployment_input_seal(previous)
        authority = self._materialize_and_verify_release_evidence(
            deployment_input_seal=deployment_input_seal
        )
        self._require_deployment_input_seal(deployment_input_seal)
        target_mounts = self._validate_compose(candidate=candidate)
        self._require_deployment_input_seal(deployment_input_seal)
        public_origin = _validate_public_origin(
            str(authority.get("public_origin") or ""),
            allowed_hosts=self.allowed_public_hosts,
        )
        non_memorial_controls = self._capture_non_memorial_controls()
        self.receipt.update(
            {
                "status": "preflight_pass",
                "source_revision": source_revision,
                "public_origin": public_origin,
                "previous_api": self._sanitized_previous_api(previous),
                "rollback_compose_files": previous["compose_config_files"],
                "rollback": {
                    "status": "available",
                    "working_dir": previous["working_dir"],
                    "image_id": previous["image_id"],
                },
            }
        )
        self._write_receipt()
        return {
            "authority": authority,
            "previous": previous,
            "rollback_render": rollback_render,
            "source_revision": source_revision,
            "public_origin": public_origin,
            "candidate": candidate,
            "candidate_promotion": candidate_promotion,
            "deployment_input_seal": deployment_input_seal,
            "non_memorial_controls": non_memorial_controls,
            "target_mounts": target_mounts,
        }

    def deploy(self, *, preflight_only: bool = False) -> dict[str, Any]:
        mutation_started = False
        rollback_tag = ""
        previous: dict[str, Any] = {}
        non_memorial_controls: dict[str, Any] = {}
        self._acquire_lock()
        try:
            context = self.preflight()
            previous = dict(context["previous"])
            non_memorial_controls = dict(context["non_memorial_controls"])
            if preflight_only:
                self.receipt["status"] = "preflight_only_pass"
                self.receipt["completed_at"] = _utc_now()
                self._write_receipt()
                return self.receipt

            self._require_deployment_input_seal(context["deployment_input_seal"])
            self._require_vexp_certification_token_coverage(
                "before_redis_mutation"
            )
            self._ensure_redis()
            self._require_vexp_certification_token_coverage(
                "before_rollback_protection"
            )
            rollback_tag = self._protect_previous_image(previous)
            self.receipt["rollback"] = {
                "status": "available",
                "working_dir": previous["working_dir"],
                "image_id": previous["image_id"],
                "image_tag": rollback_tag,
            }
            self.receipt["status"] = "changing_api"
            self._write_receipt()

            self._require_deployment_input_seal(context["deployment_input_seal"])
            self._require_vexp_certification_token_coverage(
                "immediately_before_api_mutation"
            )
            mutation_started = True
            self._recreate_api()
            api_detail = self._wait_container(API_SERVICE, require_health=True)
            api_identity = self._verify_forward_api(
                candidate=dict(context["candidate"]),
                source_revision=str(context["source_revision"]),
                expected_mounts=list(context["target_mounts"]),
                expected_projection=dict(
                    dict(context["candidate_promotion"]).get("projection") or {}
                ),
            )
            self._record_check(
                "api_container", "pass", **api_detail, identity=api_identity
            )
            self._verify_deployed_surface(
                str(context["public_origin"]),
                source_revision=str(context["source_revision"]),
            )
            self._verify_candidate_origins(str(context["public_origin"]))
            self._verify_non_memorial_controls(non_memorial_controls)

            # Rebuild the public-access projection in private release evidence only
            # after both edge probes pass. Any failure here enters rollback.
            self._require_vexp_certification_token_coverage(
                "before_postdeploy_evidence"
            )
            self._materialize_and_verify_release_evidence(
                phase="postdeploy",
                deployment_input_seal=context["deployment_input_seal"],
                expected_public_origin=str(context["public_origin"]),
                expected_authority_posture=str(
                    dict(context["authority"]).get("authority_posture") or ""
                ),
            )

            self._require_vexp_certification_token_coverage(
                "before_promotion_success"
            )

            self.receipt["status"] = "pass"
            self.receipt["completed_at"] = _utc_now()
            self.receipt["rollback"]["status"] = "available"
            self._write_receipt()
            return self.receipt
        except (Exception, KeyboardInterrupt) as exc:
            original_error = str(exc) or type(exc).__name__
            self.receipt["failure"] = {
                "at": _utc_now(),
                "reason": original_error,
                "type": type(exc).__name__,
            }
            if mutation_started and previous and rollback_tag:
                try:
                    rollback = self._rollback(
                        previous,
                        rollback_tag,
                        non_memorial_controls,
                        context["deployment_input_seal"],
                    )
                    self.receipt["status"] = "failed_rolled_back"
                    self.receipt["rollback"] = rollback
                    self.receipt["completed_at"] = _utc_now()
                    self._write_receipt()
                    raise DeployError(
                        f"deployment_failed_rolled_back:{original_error}"
                    ) from exc
                except DeployError as rollback_exc:
                    if str(rollback_exc).startswith("deployment_failed_rolled_back:"):
                        raise
                    self.receipt["status"] = "rollback_failed"
                    self.receipt["rollback"] = {
                        "status": "fail",
                        "failed_at": _utc_now(),
                        "reason": str(rollback_exc),
                    }
                    self.receipt["completed_at"] = _utc_now()
                    self._write_receipt()
                    raise DeployError(
                        f"deployment_and_rollback_failed:{original_error}:{rollback_exc}"
                    ) from rollback_exc
            self.receipt["status"] = "preflight_failed"
            self.receipt["completed_at"] = _utc_now()
            self._write_receipt()
            if isinstance(exc, DeployError):
                raise
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise DeployError(original_error) from exc
        finally:
            self._release_lock()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy only ea-api for the governed public Manfred memorial lane."
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run evidence, Compose, rollback-input, and origin checks without Docker mutations.",
    )
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--receipt-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        lane = MemorialDeployLane(
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            receipt_dir=args.receipt_dir,
        )
        receipt = lane.deploy(preflight_only=bool(args.preflight_only))
    except KeyboardInterrupt:
        print("memorial deploy interrupted", file=sys.stderr)
        return 130
    except DeployError as exc:
        print(f"memorial deploy failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
