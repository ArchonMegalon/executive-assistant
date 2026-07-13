#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from materialize_ea_browser_workflow_proof import (
    DEPENDENCY_NAMES as BROWSER_DEPENDENCY_NAMES,
    MAX_JUNIT_BYTES as BROWSER_MAX_JUNIT_BYTES,
    _environment_policy as _expected_lane_environment_policy,
    _normalized_argv_template as _expected_lane_argv_template,
    _parse_junit_xml as _reparse_embedded_junit_xml,
    _parse_terminal_summary as _reparse_terminal_summary,
)
from verify_full_design_mirror_parity import inspect_manifest
from verify_release_authority import validate_release_authority


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PULSE = (
    ROOT / ".codex-design" / "product" / "WEEKLY_PRODUCT_PULSE.generated.json"
)
DEFAULT_FLAGSHIP_RECEIPT = (
    ROOT / ".codex-design" / "product" / "EA_FLAGSHIP_RELEASE_GATE.generated.json"
)
DEFAULT_BROWSER_PROOF = (
    ROOT / ".codex-studio" / "published" / "EA_BROWSER_WORKFLOW_PROOF.generated.json"
)
DEFAULT_JOURNEY_GATES = Path(
    os.environ.get("EA_FLEET_JOURNEY_GATES_PATH")
    or ROOT / "ea" / "_completion" / "fleet" / "JOURNEY_GATES.generated.json"
)
DEFAULT_IMPLEMENTATION_SCOPE = (
    ROOT / ".codex-design" / "repo" / "IMPLEMENTATION_SCOPE.md"
)
DEFAULT_RELEASE_MANIFEST = (
    ROOT / ".codex-studio" / "published" / "release_manifest.generated.json"
)
DEFAULT_PROJECT_MODES = (
    ROOT / ".codex-design" / "product" / "PROJECT_MODES.generated.json"
)
DEFAULT_DESIGN_MIRROR_MANIFEST = (
    ROOT / ".codex-design" / "repo" / "DESIGN_MIRROR_MANIFEST.yaml"
)
CANONICAL_CHUMMER_PULSE_SOURCE = Path(
    "/docker/chummercomplete/chummer-design/products/chummer/WEEKLY_PRODUCT_PULSE.generated.json"
)

PULSE_MIRROR_BINDING_KEY = "weekly_product_pulse"
PULSE_CONTRACT_NAME = "chummer.weekly_product_pulse"
PULSE_CONTRACT_VERSION = 3
PULSE_SCORECARD_SOURCE = "products/chummer/PRODUCT_HEALTH_SCORECARD.yaml"
PULSE_PROGRESS_REPORT_SOURCE = "products/chummer/PROGRESS_REPORT.generated.json"
PULSE_PROGRESS_HISTORY_SOURCE = "products/chummer/PROGRESS_HISTORY.generated.json"
PULSE_READY_RELEASE_STATE = "green_or_explained"
PULSE_READY_FLAGSHIP_STATE = "ready"
PULSE_READY_JOURNEY_STATE = "ready"
PULSE_READY_LAUNCH_ACTION = "launch_expand"
PULSE_MAX_AGE = timedelta(days=8)
PULSE_MAX_FUTURE_SKEW = timedelta(minutes=5)
PULSE_MAX_BYTES = 1024 * 1024
BROWSER_PROOF_CONTRACT_NAME = "ea.browser_workflow_proof"
BROWSER_PROOF_CONTRACT_VERSION = 3
BROWSER_PROOF_PRODUCT = "executive-assistant"
BROWSER_PROOF_SURFACE = "browser_workflow_proof"
BROWSER_PROOF_KIND = "proof_receipt"
BROWSER_PROOF_GENERATED_BY = "scripts/materialize_ea_browser_workflow_proof.py"
BROWSER_PROOF_TRUST_MODEL = "local_unsigned_process_evidence"
BROWSER_PROOF_SEED_SOURCE = ".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json"
BROWSER_PROOF_RELEASE_CLAIM_SUMMARY = (
    "EA can only claim flagship-grade release truth when release authority, "
    "browser workflow proof, and release asset verification agree with this gate seed."
)
BROWSER_PROOF_EXPECTED_SIGNALS = [
    "/register leads with email-first workspace setup, workspace shape, Google connection, and first brief setup",
    "/app/today renders Morning Memo, Send board materials, and Approve reply to Sofia N.",
    "/app/queue renders decisions, drafts, and commitments tied to workspace objects",
    "/app/people renders stakeholder memory, open loops, and recent evidence",
    "/app/settings keeps memo timing, approvals, and workspace rules visible without leading with operator noise",
]
BROWSER_ENVIRONMENT_POLICY_NAME = "ea.browser_workflow_proof.hermetic"
BROWSER_ENVIRONMENT_POLICY_VERSION = 1
BROWSER_PROOF_MAX_AGE = timedelta(days=1)
BROWSER_PROOF_MAX_FUTURE_SKEW = timedelta(minutes=5)
BROWSER_SOURCE_BACKED_TEST_FILE = "tests/test_product_browser_journeys.py"
BROWSER_REAL_TEST_FILE = "tests/e2e/test_product_workflows.py"
BROWSER_SOURCE_BACKED_CASES = [
    "test_workspace_pages_render_seeded_product_objects",
    "test_browser_journey_updates_after_approval_and_commitment_closure",
    "test_browser_action_routes_match_rendered_forms",
    "test_browser_handoff_and_people_memory_actions_work",
]
BROWSER_REAL_CASES = [
    "test_activation_and_memo_flow_in_real_browser",
    "test_draft_and_commitment_workflows_in_real_browser",
]
BROWSER_SOURCE_STATE_STAGES = [
    "before_tests",
    "after_source",
    "after_browser",
    "before_publish",
]
BROWSER_SNAPSHOT_SEAL_ALGORITHM = "sha256-content-posix-stat-v1"
BROWSER_SNAPSHOT_SEAL_STAGES = ["before_source", "after_source", "after_browser"]
BROWSER_SNAPSHOT_READ_ONLY_ENFORCEMENT = (
    "owner_mode_bits_plus_content_stat_seal_and_inotify_watch"
)
BROWSER_SNAPSHOT_MUTATION_WATCH_ALGORITHM = "linux-inotify-v1"
BROWSER_SNAPSHOT_MUTATION_WATCH_STAGES = ["after_source", "after_browser"]
BROWSER_RUNNER_ROOT_KIND = "committed_mode_read_only_mutation_watched_snapshot"
BROWSER_PROOF_KEYS = {
    "contract_name",
    "product",
    "surface",
    "version",
    "kind",
    "generated_at",
    "generated_by",
    "run_id",
    "trust_model",
    "environment_policy",
    "source_revision",
    "source_tree",
    "source_worktree_dirty",
    "source_state_samples",
    "snapshot",
    "status",
    "operator_summary",
    "seed_source",
    "release_claim_summary",
    "expected_browser_signals",
    "source_backed_journey_proof",
    "real_browser_e2e_proof",
    "blocking_reasons",
    "current_limitations",
}
BROWSER_LANE_KEYS = {
    "status",
    "run_id",
    "trust_model",
    "source_revision",
    "source_tree",
    "test_file",
    "cases",
    "selection_mode",
    "node_ids",
    "runner_root_kind",
    "snapshot_read_only",
    "environment_policy",
    "argv_template",
    "python_identity",
    "browser_identity",
    "exit_code",
    "duration_seconds",
    "output_excerpt",
    "terminal_summary",
    "report_format",
    "junit_xml",
    "junit_xml_sha256",
    "limitations",
    "blocking_reasons",
    "executed_count",
    "passed_count",
    "failed_count",
    "error_count",
    "skipped_count",
    "xfail_count",
    "xpass_count",
    "executed_cases",
    "passed_cases",
    "junit_declared_tests_count",
    "junit_declared_failure_count",
    "junit_declared_error_count",
    "junit_declared_skipped_count",
    "junit_totals_consistent",
    "terminal_passed_count",
    "terminal_xfail_count",
    "terminal_xpass_count",
}

REQUIRED_RELEASE_CONTRACT_PATHS = (
    ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_TRUTH_PLANE.md",
    ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_RELEASE_GATE.json",
    ROOT / ".codex-design" / "repo" / "IMPLEMENTATION_SCOPE.md",
    ROOT / ".codex-design" / "ea" / "START_HERE.md",
    ROOT / ".codex-design" / "ea" / "SURFACE_DESIGN_SYSTEM.md",
    ROOT / ".codex-design" / "ea" / "LTD_INTEGRATION_MAP.md",
    ROOT / ".codex-design" / "product" / "EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ROOT / ".codex-design" / "product" / "PUBLIC_MEDIA_AND_GUIDE_ASSET_POLICY.md",
    ROOT / ".codex-design" / "product" / "PUBLIC_CONCIERGE_WORKFLOWS.yaml",
    ROOT / ".codex-studio" / "published" / "EA_BROWSER_WORKFLOW_PROOF.generated.json",
)


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _state(payload: dict[str, Any], key: str) -> str:
    section = payload.get(key)
    if not isinstance(section, dict):
        return ""
    return str(section.get("state") or section.get("status") or "").strip().lower()


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    section = payload.get(key)
    return dict(section) if isinstance(section, dict) else {}


def _nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso_date(value: object) -> date | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


class _DuplicateJSONKey(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise _DuplicateJSONKey(key)
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _normalized_lexical_path(path: Path) -> str | None:
    raw = os.fspath(path)
    normalized = os.path.abspath(os.path.normpath(raw))
    return normalized if raw == normalized else None


def _symlink_component(path: Path) -> Path | None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            current_stat = os.lstat(current)
        except OSError:
            return None
        if stat.S_ISLNK(current_stat.st_mode):
            return current
    return None


def _regular_file_identity(
    path: Path, *, label: str
) -> tuple[tuple[int, ...] | None, list[str]]:
    normalized = _normalized_lexical_path(path)
    if normalized is None:
        return None, [
            f"{label} path is not exact normalized absolute lexical form: {path}"
        ]
    symlink = _symlink_component(path)
    if symlink is not None:
        return None, [f"{label} path contains a symlink: {symlink}"]
    try:
        path_stat = os.lstat(path)
    except OSError:
        return None, [f"{label} is missing or unreadable: {path}"]
    if not stat.S_ISREG(path_stat.st_mode):
        return None, [f"{label} is not a regular file: {path}"]

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            descriptor_stat = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        return None, [f"{label} could not be opened without following links: {path}"]
    if not stat.S_ISREG(descriptor_stat.st_mode):
        return None, [f"{label} descriptor is not a regular file: {path}"]
    if _file_identity(path_stat) != _file_identity(descriptor_stat):
        return None, [f"{label} changed between path and descriptor inspection: {path}"]
    return _file_identity(descriptor_stat), []


def _read_bound_file(
    path: Path,
    *,
    expected_identity: tuple[int, ...],
    label: str,
) -> tuple[bytes, str, list[str]]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return b"", "", [f"{label} could not be opened safely: {path}"]
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or _file_identity(before) != expected_identity
        ):
            return b"", "", [f"{label} descriptor identity changed before read"]
        if before.st_size > PULSE_MAX_BYTES:
            return b"", "", [f"{label} exceeds the 1 MiB read bound"]
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, PULSE_MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > PULSE_MAX_BYTES:
                return b"", "", [f"{label} exceeds the 1 MiB read bound"]
        after = os.fstat(descriptor)
    except OSError:
        return b"", "", [f"{label} descriptor read failed"]
    finally:
        os.close(descriptor)

    if _file_identity(before) != _file_identity(after):
        return b"", "", [f"{label} descriptor changed during read"]
    final_identity, final_issues = _regular_file_identity(path, label=label)
    if final_issues:
        return b"", "", final_issues
    if final_identity != expected_identity:
        return b"", "", [f"{label} path changed during bound read"]

    content = b"".join(chunks)
    return content, hashlib.sha256(content).hexdigest(), []


def _parse_bound_pulse(content: bytes) -> tuple[dict[str, Any], list[str]]:
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateJSONKey:
        return {}, ["weekly product pulse contains duplicate JSON keys"]
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}, ["weekly product pulse is not valid UTF-8 JSON"]
    if not isinstance(payload, dict):
        return {}, ["weekly product pulse JSON root is not an object"]
    return dict(payload), []


def _load_bound_pulse(
    *,
    pulse_path: Path,
    manifest_path: Path,
    canonical_source_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    tracked_paths = (
        (manifest_path, "weekly product pulse mirror manifest"),
        (pulse_path, "weekly product pulse mirror"),
        (canonical_source_path, "weekly product pulse canonical source"),
    )
    before: dict[str, tuple[int, ...]] = {}
    issues: list[str] = []
    for path, label in tracked_paths:
        identity, path_issues = _regular_file_identity(path, label=label)
        issues.extend(path_issues)
        if identity is not None:
            before[label] = identity
    if issues:
        return {}, issues

    for label in (
        "weekly product pulse mirror",
        "weekly product pulse canonical source",
    ):
        if before[label][5] > PULSE_MAX_BYTES:
            issues.append(f"{label} exceeds the 1 MiB read bound")
    if issues:
        return {}, issues

    expected_hash_paths = {
        pulse_path.as_posix(): "weekly product pulse mirror",
        canonical_source_path.as_posix(): "weekly product pulse canonical source",
    }
    inspection_issues: list[str] = []

    def bounded_inspector_hash(path: Path) -> str:
        label = expected_hash_paths.get(path.as_posix())
        if label is None:
            inspection_issues.append(
                "weekly product pulse mirror binding attempted an unexpected hash path: "
                f"{path}"
            )
            return ""
        _, digest, read_issues = _read_bound_file(
            path,
            expected_identity=before[label],
            label=label,
        )
        inspection_issues.extend(read_issues)
        return digest

    try:
        rows = inspect_manifest(
            ROOT,
            manifest_path,
            hash_file=bounded_inspector_hash,
            binding_key=PULSE_MIRROR_BINDING_KEY,
            expected_absolute_local_path=pulse_path,
        )
    except Exception:
        return {}, [
            f"weekly product pulse mirror manifest missing or invalid: {manifest_path}"
        ]
    issues.extend(inspection_issues)

    for path, label in tracked_paths:
        identity, path_issues = _regular_file_identity(path, label=label)
        issues.extend(path_issues)
        if identity is not None and before.get(label) != identity:
            issues.append(f"{label} changed during mirror parity inspection")

    bindings = [row for row in rows if row.get("key") == PULSE_MIRROR_BINDING_KEY]
    if len(bindings) != 1:
        issues.append(
            "weekly product pulse mirror binding is missing or ambiguous: "
            f"{PULSE_MIRROR_BINDING_KEY}"
        )
        return {}, issues

    row = bindings[0]
    if row.get("kind") != "file":
        issues.append("weekly product pulse mirror binding kind is not file")
    if row.get("required") is not True:
        issues.append("weekly product pulse mirror binding is not required")
    bound_local = str(row.get("local_path") or "")
    bound_source = str(row.get("source_path") or "")
    if bound_local != pulse_path.as_posix():
        issues.append(
            "weekly product pulse mirror local path is "
            f"{bound_local or 'missing'}, expected {pulse_path.as_posix()}"
        )
    if bound_source != canonical_source_path.as_posix():
        issues.append(
            "weekly product pulse mirror canonical source is "
            f"{bound_source or 'missing'}, expected {canonical_source_path.as_posix()}"
        )

    parity_status = str(row.get("status") or "missing").strip().lower()
    if parity_status != "ok":
        issues.append(
            f"weekly product pulse mirror parity is {parity_status}, expected ok"
        )
    if row.get("source_unavailable") is True:
        issues.append("weekly product pulse canonical source is unavailable")
    local_sha = str(row.get("local_sha256") or "").strip()
    source_sha = str(row.get("source_sha256") or "").strip()

    local_content, local_digest, local_read_issues = _read_bound_file(
        pulse_path,
        expected_identity=before["weekly product pulse mirror"],
        label="weekly product pulse mirror",
    )
    source_content, source_digest, source_read_issues = _read_bound_file(
        canonical_source_path,
        expected_identity=before["weekly product pulse canonical source"],
        label="weekly product pulse canonical source",
    )
    issues.extend(local_read_issues)
    issues.extend(source_read_issues)

    for path, label in tracked_paths:
        identity, path_issues = _regular_file_identity(path, label=label)
        issues.extend(path_issues)
        if identity is not None and before.get(label) != identity:
            issues.append(f"{label} changed after bound parity reads")

    exact_parity = bool(
        local_digest
        and source_digest
        and local_content == source_content
        and local_digest == source_digest
        and local_digest == local_sha
        and source_digest == source_sha
    )
    if not exact_parity:
        issues.append(
            "weekly product pulse mirror does not prove exact source hash parity"
        )

    pulse: dict[str, Any] = {}
    if not local_read_issues:
        pulse, parse_issues = _parse_bound_pulse(local_content)
        issues.extend(parse_issues)
    return pulse, issues


def _pulse_freshness_issues(
    pulse: dict[str, Any], *, observed_at: datetime | None = None
) -> list[str]:
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    issues: list[str] = []
    generated_at = _utc_datetime(pulse.get("generated_at"))
    if generated_at is None:
        issues.append("weekly product pulse generated_at is missing or invalid")
    elif generated_at > now + PULSE_MAX_FUTURE_SKEW:
        issues.append("weekly product pulse generated_at is in the future")
    elif now - generated_at > PULSE_MAX_AGE:
        issues.append("weekly product pulse generated_at is stale (older than 8 days)")

    as_of = _iso_date(pulse.get("as_of"))
    if as_of is None:
        issues.append("weekly product pulse as_of is missing or invalid")
    elif as_of > now.date():
        issues.append("weekly product pulse as_of is in the future")
    elif now.date() - as_of > timedelta(days=PULSE_MAX_AGE.days):
        issues.append("weekly product pulse as_of is stale (older than 8 days)")
    if generated_at is not None and as_of is not None and generated_at.date() != as_of:
        issues.append(
            "weekly product pulse generated_at and as_of dates are inconsistent"
        )
    return issues


def _launch_governance_action(pulse: dict[str, Any], *, as_of: date | None) -> str:
    if as_of is None:
        return ""
    decisions = pulse.get("governor_decisions")
    if not isinstance(decisions, list):
        return ""
    expected_id = f"{as_of.isoformat()}-launch-governance"
    launch_decisions = [
        row
        for row in decisions
        if isinstance(row, dict)
        and type(row.get("decision_id")) is str
        and row.get("decision_id") == expected_id
    ]
    if len(launch_decisions) != 1:
        return ""
    return str(launch_decisions[0].get("action") or "").strip().lower()


def _pulse_journey_summary_snapshot(
    pulse: dict[str, Any], path: Path
) -> dict[str, Any]:
    health = pulse.get("journey_gate_health")
    if not isinstance(health, dict):
        return {}
    supporting_signals = pulse.get("supporting_signals")
    if not isinstance(supporting_signals, dict):
        supporting_signals = {}
    source = str(
        pulse.get("journey_gate_source")
        or supporting_signals.get("journey_gate_source")
        or ""
    ).strip()
    if source != path.as_posix():
        return {}
    state = str(health.get("state") or health.get("status") or "").strip().lower()
    if not state:
        return {}
    blocked_count = _nonnegative_int(health.get("blocked_count"))
    warning_count = _nonnegative_int(health.get("warning_count"))
    if blocked_count is None or warning_count is None:
        return {}
    return {
        "overall_state": state,
        "blocked_count": blocked_count,
        "warning_count": warning_count,
        "source": "weekly_product_pulse_snapshot",
    }


def _journey_summary(path: Path, *, pulse: dict[str, Any]) -> dict[str, Any]:
    payload = _json(path)
    summary = payload.get("summary")
    if isinstance(summary, dict):
        return dict(summary)
    return _pulse_journey_summary_snapshot(pulse, path)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _exact_empty_list(value: object) -> bool:
    return type(value) is list and not value


def _is_canonical_revision(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is not None
    )


def _is_canonical_sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _browser_python_identity_issues(identity: object, *, label: str) -> list[str]:
    if not isinstance(identity, dict):
        return [f"browser workflow proof {label} python_identity is invalid"]
    issues: list[str] = []
    expected_keys = {
        "executable",
        "sha256",
        "version",
        "dependency_root",
        "dependency_versions",
    }
    if set(identity) != expected_keys:
        issues.append(
            f"browser workflow proof {label} python_identity schema is not exact"
        )
    executable = identity.get("executable")
    if (
        type(executable) is not str
        or not os.path.isabs(executable)
        or os.path.normpath(executable) != executable
    ):
        issues.append(
            f"browser workflow proof {label} python executable is not canonical absolute"
        )
    if not _is_canonical_sha256(identity.get("sha256")):
        issues.append(f"browser workflow proof {label} python sha256 is not canonical")
    if type(identity.get("version")) is not str or not identity.get("version"):
        issues.append(f"browser workflow proof {label} python version is invalid")
    dependency_root = identity.get("dependency_root")
    if (
        type(dependency_root) is not str
        or not os.path.isabs(dependency_root)
        or os.path.normpath(dependency_root) != dependency_root
    ):
        issues.append(
            f"browser workflow proof {label} dependency_root is not canonical absolute"
        )
    dependencies = identity.get("dependency_versions")
    if not isinstance(dependencies, dict) or set(dependencies) != set(
        BROWSER_DEPENDENCY_NAMES
    ):
        issues.append(
            f"browser workflow proof {label} dependency versions schema is not exact"
        )
    elif any(
        type(dependencies[name]) is not str or not dependencies[name]
        for name in BROWSER_DEPENDENCY_NAMES
    ):
        issues.append(
            f"browser workflow proof {label} dependency versions are incomplete"
        )
    return issues


def _browser_executable_identity_issues(
    identity: object, *, label: str, required: bool
) -> list[str]:
    if not required:
        return (
            []
            if identity is None
            else [f"browser workflow proof {label} browser_identity must be null"]
        )
    if not isinstance(identity, dict) or set(identity) != {"executable", "sha256"}:
        return [f"browser workflow proof {label} browser_identity is not exact"]
    executable = identity.get("executable")
    issues: list[str] = []
    if (
        type(executable) is not str
        or not os.path.isabs(executable)
        or os.path.normpath(executable) != executable
    ):
        issues.append(
            f"browser workflow proof {label} browser executable is not canonical absolute"
        )
    if not _is_canonical_sha256(identity.get("sha256")):
        issues.append(
            f"browser workflow proof {label} browser executable sha256 is not canonical"
        )
    return issues


def _browser_lane_issues(
    lane: object,
    *,
    label: str,
    expected_test_file: str,
    expected_cases: list[str],
    real_browser: bool,
    expected_run_id: object,
    expected_revision: object,
    expected_tree: object,
) -> list[str]:
    if not isinstance(lane, dict):
        return [f"browser workflow proof {label} lane is missing or invalid"]
    issues: list[str] = []
    if set(lane) != BROWSER_LANE_KEYS:
        issues.append(f"browser workflow proof {label} lane schema is not exact")
    if type(lane.get("status")) is not str or lane.get("status") != "pass":
        issues.append(f"browser workflow proof {label} lane is not pass")
    if type(lane.get("exit_code")) is not int or lane.get("exit_code") != 0:
        issues.append(
            f"browser workflow proof {label} exit_code is not exact integer 0"
        )
    if (
        type(lane.get("test_file")) is not str
        or lane.get("test_file") != expected_test_file
    ):
        issues.append(f"browser workflow proof {label} test_file is not exact")
    if type(lane.get("cases")) is not list or lane.get("cases") != expected_cases:
        issues.append(f"browser workflow proof {label} cases are not exact")
    for field, expected in (
        ("run_id", expected_run_id),
        ("source_revision", expected_revision),
        ("source_tree", expected_tree),
        ("trust_model", BROWSER_PROOF_TRUST_MODEL),
    ):
        if type(lane.get(field)) is not str or lane.get(field) != expected:
            issues.append(
                f"browser workflow proof {label} {field} linkage is not exact"
            )
    expected_node_ids = [f"{expected_test_file}::{case}" for case in expected_cases]
    if lane.get("selection_mode") != "exact_node_ids":
        issues.append(
            f"browser workflow proof {label} selection_mode is not exact_node_ids"
        )
    if (
        type(lane.get("node_ids")) is not list
        or lane.get("node_ids") != expected_node_ids
    ):
        issues.append(f"browser workflow proof {label} node_ids are not exact")
    if lane.get("report_format") != "junit_xml_embedded":
        issues.append(
            f"browser workflow proof {label} report_format is not junit_xml_embedded"
        )
    if lane.get("runner_root_kind") != BROWSER_RUNNER_ROOT_KIND:
        issues.append(
            f"browser workflow proof {label} runner root is not the committed snapshot"
        )
    if lane.get("snapshot_read_only") is not True:
        issues.append(f"browser workflow proof {label} snapshot_read_only is not true")
    expected_policy = _expected_lane_environment_policy(real_browser)
    if lane.get("environment_policy") != expected_policy:
        issues.append(f"browser workflow proof {label} environment policy is not exact")
    if lane.get("argv_template") != _expected_lane_argv_template(
        expected_test_file, expected_cases
    ):
        issues.append(f"browser workflow proof {label} argv template is not exact")
    issues.extend(
        _browser_python_identity_issues(lane.get("python_identity"), label=label)
    )
    issues.extend(
        _browser_executable_identity_issues(
            lane.get("browser_identity"),
            label=label,
            required=real_browser,
        )
    )
    duration = lane.get("duration_seconds")
    if (
        type(duration) not in {int, float}
        or not math.isfinite(float(duration))
        or duration < 0
    ):
        issues.append(
            f"browser workflow proof {label} duration_seconds is not nonnegative"
        )
    excerpt = lane.get("output_excerpt")
    if (
        type(excerpt) is not list
        or len(excerpt) > 40
        or any(type(item) is not str for item in excerpt)
    ):
        issues.append(f"browser workflow proof {label} output_excerpt is invalid")

    xml_text = lane.get("junit_xml")
    xml_sha = lane.get("junit_xml_sha256")
    if (
        type(xml_text) is not str
        or len(xml_text.encode("utf-8")) > BROWSER_MAX_JUNIT_BYTES
    ):
        issues.append(f"browser workflow proof {label} embedded JUnit XML is invalid")
        reparsed_junit: dict[str, Any] = {}
    else:
        recomputed_sha = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
        if not _is_canonical_sha256(xml_sha) or xml_sha != recomputed_sha:
            issues.append(
                f"browser workflow proof {label} embedded JUnit sha256 does not match"
            )
        reparsed_junit = _reparse_embedded_junit_xml(xml_text)
    terminal_summary = lane.get("terminal_summary")
    if type(terminal_summary) is not str or not terminal_summary:
        issues.append(f"browser workflow proof {label} terminal_summary is invalid")
        reparsed_terminal: dict[str, int] = {}
    else:
        reparsed_terminal = _reparse_terminal_summary(terminal_summary)
    if reparsed_terminal.get("terminal_xpass_count", 0) > 0:
        reparsed_junit["xpass_count"] = max(
            int(reparsed_junit.get("xpass_count", 0)),
            reparsed_terminal["terminal_xpass_count"],
        )
    for field in (
        "executed_count",
        "passed_count",
        "failed_count",
        "error_count",
        "skipped_count",
        "xfail_count",
        "xpass_count",
        "executed_cases",
        "passed_cases",
        "junit_declared_tests_count",
        "junit_declared_failure_count",
        "junit_declared_error_count",
        "junit_declared_skipped_count",
        "junit_totals_consistent",
    ):
        if lane.get(field) != reparsed_junit.get(field):
            issues.append(
                f"browser workflow proof {label} {field} does not match embedded JUnit"
            )
    for field in (
        "terminal_passed_count",
        "terminal_xfail_count",
        "terminal_xpass_count",
    ):
        if lane.get(field) != reparsed_terminal.get(field):
            issues.append(
                f"browser workflow proof {label} {field} does not match terminal_summary"
            )
    expected_count = len(expected_cases)
    for field, expected in (
        ("executed_count", expected_count),
        ("passed_count", expected_count),
        ("terminal_passed_count", expected_count),
        ("junit_declared_tests_count", expected_count),
        ("failed_count", 0),
        ("error_count", 0),
        ("skipped_count", 0),
        ("xfail_count", 0),
        ("xpass_count", 0),
        ("terminal_xfail_count", 0),
        ("terminal_xpass_count", 0),
        ("junit_declared_failure_count", 0),
        ("junit_declared_error_count", 0),
        ("junit_declared_skipped_count", 0),
    ):
        if type(lane.get(field)) is not int or lane.get(field) != expected:
            issues.append(
                f"browser workflow proof {label} {field} is not exact integer {expected}"
            )
    for field in ("executed_cases", "passed_cases"):
        if type(lane.get(field)) is not list or lane.get(field) != expected_cases:
            issues.append(f"browser workflow proof {label} {field} are not exact")
    if lane.get("junit_totals_consistent") is not True:
        issues.append(
            f"browser workflow proof {label} JUnit declared totals are not consistent"
        )
    if not _exact_empty_list(lane.get("limitations")):
        issues.append(f"browser workflow proof {label} limitations are not empty")
    if not _exact_empty_list(lane.get("blocking_reasons")):
        issues.append(f"browser workflow proof {label} blocking_reasons are not empty")
    return issues


def _browser_proof_issues(
    browser: dict[str, Any],
    *,
    release_manifest: dict[str, Any],
    observed_at: datetime | None,
) -> list[str]:
    issues: list[str] = []
    if set(browser) != BROWSER_PROOF_KEYS:
        issues.append("browser workflow proof top-level schema is not exact v3")
    exact_fields = (
        ("contract_name", BROWSER_PROOF_CONTRACT_NAME),
        ("product", BROWSER_PROOF_PRODUCT),
        ("surface", BROWSER_PROOF_SURFACE),
        ("kind", BROWSER_PROOF_KIND),
        ("generated_by", BROWSER_PROOF_GENERATED_BY),
    )
    for field, expected in exact_fields:
        if type(browser.get(field)) is not str or browser.get(field) != expected:
            issues.append(f"browser workflow proof {field} is not {expected}")
    if (
        type(browser.get("version")) is not int
        or browser.get("version") != BROWSER_PROOF_CONTRACT_VERSION
    ):
        issues.append(
            "browser workflow proof version is not exact integer "
            f"{BROWSER_PROOF_CONTRACT_VERSION}"
        )
    if type(browser.get("status")) is not str or browser.get("status") != "pass":
        issues.append("browser workflow proof top-level status is not pass")
    run_id = browser.get("run_id")
    if type(run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        issues.append("browser workflow proof run_id is not canonical")
    if browser.get("trust_model") != BROWSER_PROOF_TRUST_MODEL:
        issues.append(
            "browser workflow proof trust_model is not local_unsigned_process_evidence"
        )
    expected_top_policy = {
        "name": BROWSER_ENVIRONMENT_POLICY_NAME,
        "version": BROWSER_ENVIRONMENT_POLICY_VERSION,
    }
    if browser.get("environment_policy") != expected_top_policy:
        issues.append("browser workflow proof environment_policy is not exact")
    if browser.get("seed_source") != BROWSER_PROOF_SEED_SOURCE:
        issues.append("browser workflow proof seed_source is not exact")
    if browser.get("release_claim_summary") != BROWSER_PROOF_RELEASE_CLAIM_SUMMARY:
        issues.append("browser workflow proof release_claim_summary is not exact")
    if browser.get("expected_browser_signals") != BROWSER_PROOF_EXPECTED_SIGNALS:
        issues.append("browser workflow proof expected_browser_signals are not exact")

    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    generated_at = _utc_datetime(browser.get("generated_at"))
    if generated_at is None:
        issues.append("browser workflow proof generated_at is missing or invalid")
    elif generated_at > now + BROWSER_PROOF_MAX_FUTURE_SKEW:
        issues.append("browser workflow proof generated_at is in the future")
    elif now - generated_at > BROWSER_PROOF_MAX_AGE:
        issues.append("browser workflow proof generated_at is stale (older than 1 day)")

    for field in ("limitations", "current_limitations", "blocking_reasons"):
        if field == "limitations" and field not in browser:
            continue
        if not _exact_empty_list(browser.get(field)):
            issues.append(f"browser workflow proof {field} is not an empty list")

    release_revision = release_manifest.get("commit_sha")
    source_revision = browser.get("source_revision")
    source_tree = browser.get("source_tree")
    if not _is_canonical_revision(release_revision):
        issues.append(
            "release manifest commit_sha is not a canonical lowercase 40- or 64-hex revision"
        )
    if not _is_canonical_revision(source_revision):
        issues.append(
            "browser workflow proof source_revision is not a canonical lowercase 40- or 64-hex revision"
        )
    if source_revision != release_revision:
        issues.append(
            "browser workflow proof source_revision does not match release manifest commit_sha"
        )
    if browser.get("source_worktree_dirty") is not False:
        issues.append("browser workflow proof source_worktree_dirty is not false")
    if (
        not _is_canonical_revision(source_tree)
        or not _is_canonical_revision(source_revision)
        or len(str(source_tree)) != len(str(source_revision))
    ):
        issues.append("browser workflow proof source_tree is not canonical")

    snapshot = browser.get("snapshot")
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "archive_format",
        "read_only",
        "source_revision",
        "source_tree",
        "seal_algorithm",
        "read_only_enforcement",
        "seal_samples",
        "mutation_watch",
    }:
        issues.append("browser workflow proof snapshot schema is not exact")
    else:
        if any(
            (
                snapshot.get("archive_format") != "git_archive_tar",
                snapshot.get("read_only") is not True,
                snapshot.get("source_revision") != source_revision,
                snapshot.get("source_tree") != source_tree,
                snapshot.get("seal_algorithm") != BROWSER_SNAPSHOT_SEAL_ALGORITHM,
                snapshot.get("read_only_enforcement")
                != BROWSER_SNAPSHOT_READ_ONLY_ENFORCEMENT,
            )
        ):
            issues.append("browser workflow proof snapshot linkage is not exact")
        seal_samples = snapshot.get("seal_samples")
        if type(seal_samples) is not list or len(seal_samples) != len(
            BROWSER_SNAPSHOT_SEAL_STAGES
        ):
            issues.append("browser workflow proof snapshot seal samples are not exact")
        else:
            seal_digests: list[str] = []
            for expected_stage, seal_sample in zip(
                BROWSER_SNAPSHOT_SEAL_STAGES, seal_samples, strict=True
            ):
                if (
                    not isinstance(seal_sample, dict)
                    or set(seal_sample) != {"stage", "sha256"}
                    or seal_sample.get("stage") != expected_stage
                    or not _is_canonical_sha256(seal_sample.get("sha256"))
                ):
                    issues.append(
                        f"browser workflow proof snapshot seal sample {expected_stage} is invalid"
                    )
                    continue
                seal_digests.append(seal_sample["sha256"])
            if (
                len(seal_digests) != len(BROWSER_SNAPSHOT_SEAL_STAGES)
                or len(set(seal_digests)) != 1
            ):
                issues.append(
                    "browser workflow proof snapshot seal changed during proof"
                )
        mutation_watch = snapshot.get("mutation_watch")
        if not isinstance(mutation_watch, dict) or set(mutation_watch) != {
            "algorithm",
            "samples",
        }:
            issues.append("browser workflow proof snapshot mutation watch is not exact")
        elif (
            mutation_watch.get("algorithm") != BROWSER_SNAPSHOT_MUTATION_WATCH_ALGORITHM
        ):
            issues.append(
                "browser workflow proof snapshot mutation watch algorithm is not exact"
            )
        else:
            mutation_samples = mutation_watch.get("samples")
            if type(mutation_samples) is not list or len(mutation_samples) != len(
                BROWSER_SNAPSHOT_MUTATION_WATCH_STAGES
            ):
                issues.append(
                    "browser workflow proof snapshot mutation watch samples are not exact"
                )
            else:
                for expected_stage, mutation_sample in zip(
                    BROWSER_SNAPSHOT_MUTATION_WATCH_STAGES,
                    mutation_samples,
                    strict=True,
                ):
                    if (
                        not isinstance(mutation_sample, dict)
                        or set(mutation_sample) != {"stage", "event_count", "overflow"}
                        or mutation_sample.get("stage") != expected_stage
                        or type(mutation_sample.get("event_count")) is not int
                        or mutation_sample.get("event_count") != 0
                        or mutation_sample.get("overflow") is not False
                    ):
                        issues.append(
                            "browser workflow proof snapshot mutation watch sample "
                            f"{expected_stage} is not zero and exact"
                        )

    samples = browser.get("source_state_samples")
    if type(samples) is not list or len(samples) != len(BROWSER_SOURCE_STATE_STAGES):
        issues.append("browser workflow proof source_state_samples are not exact")
    else:
        for expected_stage, sample in zip(
            BROWSER_SOURCE_STATE_STAGES, samples, strict=True
        ):
            if not isinstance(sample, dict) or set(sample) != {
                "stage",
                "revision",
                "tree",
                "dirty",
            }:
                issues.append(
                    f"browser workflow proof source state sample {expected_stage} is invalid"
                )
                continue
            if sample.get("stage") != expected_stage:
                issues.append(
                    f"browser workflow proof source state sample stage is not {expected_stage}"
                )
            sample_revision = sample.get("revision")
            if not _is_canonical_revision(sample_revision):
                issues.append(
                    f"browser workflow proof source state sample {expected_stage} revision is not canonical"
                )
            if sample_revision != release_revision:
                issues.append(
                    f"browser workflow proof source state sample {expected_stage} revision does not match release manifest commit_sha"
                )
            sample_tree = sample.get("tree")
            if not _is_canonical_revision(sample_tree) or sample_tree != source_tree:
                issues.append(
                    f"browser workflow proof source state sample {expected_stage} tree does not match source_tree"
                )
            if sample.get("dirty") is not False:
                issues.append(
                    f"browser workflow proof source state sample {expected_stage} dirty is not false"
                )
    source_lane = browser.get("source_backed_journey_proof")
    browser_lane = browser.get("real_browser_e2e_proof")
    issues.extend(
        _browser_lane_issues(
            source_lane,
            label="source-backed",
            expected_test_file=BROWSER_SOURCE_BACKED_TEST_FILE,
            expected_cases=BROWSER_SOURCE_BACKED_CASES,
            real_browser=False,
            expected_run_id=run_id,
            expected_revision=source_revision,
            expected_tree=source_tree,
        )
    )
    issues.extend(
        _browser_lane_issues(
            browser_lane,
            label="real-browser",
            expected_test_file=BROWSER_REAL_TEST_FILE,
            expected_cases=BROWSER_REAL_CASES,
            real_browser=True,
            expected_run_id=run_id,
            expected_revision=source_revision,
            expected_tree=source_tree,
        )
    )
    if (
        isinstance(source_lane, dict)
        and isinstance(browser_lane, dict)
        and source_lane.get("python_identity") != browser_lane.get("python_identity")
    ):
        issues.append("browser workflow proof lane Python identities do not match")
    return issues


def verify(
    *,
    pulse_path: Path,
    flagship_receipt_path: Path,
    browser_proof_path: Path,
    journey_gates_path: Path,
    implementation_scope_path: Path = DEFAULT_IMPLEMENTATION_SCOPE,
    release_manifest_path: Path = DEFAULT_RELEASE_MANIFEST,
    project_modes_path: Path = DEFAULT_PROJECT_MODES,
    design_mirror_manifest_path: Path = DEFAULT_DESIGN_MIRROR_MANIFEST,
    canonical_pulse_source_path: Path = CANONICAL_CHUMMER_PULSE_SOURCE,
    observed_at: datetime | None = None,
    required_contract_paths: tuple[Path, ...] = REQUIRED_RELEASE_CONTRACT_PATHS,
) -> list[str]:
    issues: list[str] = []
    pulse, pulse_issues = _load_bound_pulse(
        pulse_path=pulse_path,
        manifest_path=design_mirror_manifest_path,
        canonical_source_path=canonical_pulse_source_path,
    )
    issues.extend(pulse_issues)
    receipt = _json(flagship_receipt_path)
    browser = _json(browser_proof_path)
    journey_summary = _journey_summary(journey_gates_path, pulse=pulse)
    implementation_scope = _text(implementation_scope_path)
    release_manifest = _json(release_manifest_path)
    project_modes = _json(project_modes_path)

    override_substitutions = {
        ROOT
        / ".codex-design"
        / "product"
        / "EA_FLAGSHIP_RELEASE_GATE.generated.json": flagship_receipt_path,
        ROOT
        / ".codex-studio"
        / "published"
        / "EA_BROWSER_WORKFLOW_PROOF.generated.json": browser_proof_path,
    }

    for path in required_contract_paths:
        replacement = override_substitutions.get(path)
        if replacement is not None and replacement != path:
            continue
        if not path.exists():
            issues.append(f"required EA release contract missing: {path}")

    if not pulse:
        issues.append(f"weekly product pulse missing or invalid: {pulse_path}")
    if not receipt:
        issues.append(
            f"flagship release receipt missing or invalid: {flagship_receipt_path}"
        )
    if not browser:
        issues.append(
            f"browser workflow proof missing or invalid: {browser_proof_path}"
        )
    if not journey_summary:
        issues.append(f"journey gates summary missing or invalid: {journey_gates_path}")
    if not release_manifest:
        issues.append(f"release manifest missing or invalid: {release_manifest_path}")
    if not project_modes:
        issues.append(
            f"project modes manifest missing or invalid: {project_modes_path}"
        )

    receipt_status = str(receipt.get("status") or "").strip().lower()
    release_health = _state(pulse, "release_health")
    flagship_readiness = _state(pulse, "flagship_readiness")
    journey_health = _state(pulse, "journey_gate_health")
    canonical_journey_health = _mapping(pulse, "journey_gate_health")
    canonical_blocked_count = _nonnegative_int(
        canonical_journey_health.get("blocked_count")
    )
    canonical_warning_count = _nonnegative_int(
        canonical_journey_health.get("warning_count")
    )
    supporting_signals = _mapping(pulse, "supporting_signals")
    raw_launch_readiness = supporting_signals.get("launch_readiness")
    launch_readiness = (
        raw_launch_readiness.strip() if type(raw_launch_readiness) is str else ""
    )
    journey_state = str(journey_summary.get("overall_state") or "").strip().lower()
    blocked_count = _nonnegative_int(journey_summary.get("blocked_count"))
    warning_count = _nonnegative_int(journey_summary.get("warning_count"))
    pulse_contract = str(pulse.get("contract_name") or "").strip()
    pulse_contract_version = pulse.get("contract_version")
    scorecard_source = str(pulse.get("scorecard_source") or "").strip()
    progress_report_source = str(pulse.get("progress_report_source") or "").strip()
    progress_history_source = str(pulse.get("progress_history_source") or "").strip()
    launch_governance_action = _launch_governance_action(
        pulse, as_of=_iso_date(pulse.get("as_of"))
    )

    issues.extend(_pulse_freshness_issues(pulse, observed_at=observed_at))

    if receipt_status != "pass":
        issues.append(
            f"flagship release receipt is {receipt_status or 'missing'}, expected pass"
        )
    issues.extend(
        _browser_proof_issues(
            browser,
            release_manifest=release_manifest,
            observed_at=observed_at,
        )
    )
    if pulse_contract != PULSE_CONTRACT_NAME:
        issues.append(
            f"weekly product pulse contract is {pulse_contract or 'missing'}, expected {PULSE_CONTRACT_NAME}"
        )
    if (
        type(pulse_contract_version) is not int
        or pulse_contract_version != PULSE_CONTRACT_VERSION
    ):
        issues.append(
            "weekly product pulse contract version is "
            f"{pulse_contract_version!r}, expected {PULSE_CONTRACT_VERSION}"
        )
    if scorecard_source != PULSE_SCORECARD_SOURCE:
        issues.append(
            "weekly product pulse scorecard source is "
            f"{scorecard_source or 'missing'}, expected {PULSE_SCORECARD_SOURCE}"
        )
    if progress_report_source != PULSE_PROGRESS_REPORT_SOURCE:
        issues.append(
            "weekly product pulse progress report source is "
            f"{progress_report_source or 'missing'}, expected {PULSE_PROGRESS_REPORT_SOURCE}"
        )
    if progress_history_source != PULSE_PROGRESS_HISTORY_SOURCE:
        issues.append(
            "weekly product pulse progress history source is "
            f"{progress_history_source or 'missing'}, expected {PULSE_PROGRESS_HISTORY_SOURCE}"
        )
    if release_health != PULSE_READY_RELEASE_STATE:
        issues.append(
            f"weekly release_health is {release_health or 'missing'}, expected {PULSE_READY_RELEASE_STATE}"
        )
    if flagship_readiness != PULSE_READY_FLAGSHIP_STATE:
        issues.append(
            f"weekly flagship_readiness is {flagship_readiness or 'missing'}, expected {PULSE_READY_FLAGSHIP_STATE}"
        )
    if journey_health != PULSE_READY_JOURNEY_STATE:
        issues.append(
            f"weekly journey_gate_health is {journey_health or 'missing'}, expected {PULSE_READY_JOURNEY_STATE}"
        )
    if canonical_blocked_count is None:
        issues.append(
            "weekly journey_gate_health blocked_count is missing or not a nonnegative integer"
        )
    elif canonical_blocked_count != 0:
        issues.append(
            f"weekly journey_gate_health still reports {canonical_blocked_count} blocked journey(s)"
        )
    if canonical_warning_count is None:
        issues.append(
            "weekly journey_gate_health warning_count is missing or not a nonnegative integer"
        )
    elif canonical_warning_count != 0:
        issues.append(
            f"weekly journey_gate_health still reports {canonical_warning_count} warning journey(s)"
        )
    if journey_state != PULSE_READY_JOURNEY_STATE:
        issues.append(
            f"fleet journey gates are {journey_state or 'missing'}, expected {PULSE_READY_JOURNEY_STATE}"
        )
    if blocked_count is None:
        issues.append("fleet journey gates blocked_count is missing or invalid")
    elif blocked_count != 0:
        issues.append(
            f"fleet journey gates still report {blocked_count} blocked journey(s)"
        )
    if warning_count is None:
        issues.append("fleet journey gates warning_count is missing or invalid")
    elif warning_count != 0:
        issues.append(
            f"fleet journey gates still report {warning_count} warning journey(s)"
        )
    if launch_governance_action != PULSE_READY_LAUNCH_ACTION:
        issues.append(
            "weekly launch-governance action is "
            f"{launch_governance_action or 'missing'}, expected {PULSE_READY_LAUNCH_ACTION}"
        )
    blocking_launch_markers = (
        "blocked",
        "freeze launch",
        "hold launch",
        "not ready",
        "waiting",
    )
    if type(raw_launch_readiness) is not str or not launch_readiness:
        issues.append("weekly launch_readiness must be a non-empty string")
    elif any(marker in launch_readiness.lower() for marker in blocking_launch_markers):
        issues.append(
            f"weekly launch_readiness still reports a blocking posture: {launch_readiness}"
        )
    if "mirrored `.codex-design/product/*`" not in implementation_scope:
        issues.append(
            "implementation scope no longer requires mirrored .codex-design/product/* canon"
        )
    if (
        "Guide/help/public projections must compile from mirrored design sources"
        not in implementation_scope
    ):
        issues.append(
            "implementation scope no longer requires mirrored design-source compilation"
        )
    if release_manifest and project_modes:
        authority_issues = validate_release_authority(
            release_manifest=release_manifest,
            project_modes=project_modes,
        )
        if authority_issues:
            issues.append(
                "release authority gate is fail: " + ",".join(authority_issues)
            )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless EA flagship release readiness is genuinely clear."
    )
    parser.add_argument("--pulse", type=Path, default=DEFAULT_PULSE)
    parser.add_argument(
        "--flagship-receipt", type=Path, default=DEFAULT_FLAGSHIP_RECEIPT
    )
    parser.add_argument("--browser-proof", type=Path, default=DEFAULT_BROWSER_PROOF)
    parser.add_argument("--journey-gates", type=Path, default=DEFAULT_JOURNEY_GATES)
    parser.add_argument(
        "--implementation-scope", type=Path, default=DEFAULT_IMPLEMENTATION_SCOPE
    )
    parser.add_argument(
        "--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST
    )
    parser.add_argument("--project-modes", type=Path, default=DEFAULT_PROJECT_MODES)
    args = parser.parse_args()

    issues = verify(
        pulse_path=args.pulse,
        flagship_receipt_path=args.flagship_receipt,
        browser_proof_path=args.browser_proof,
        journey_gates_path=args.journey_gates,
        implementation_scope_path=args.implementation_scope,
        release_manifest_path=args.release_manifest,
        project_modes_path=args.project_modes,
    )
    if issues:
        print(json.dumps({"status": "blocked", "issues": issues}, indent=2))
        return 1
    print(
        json.dumps(
            {"status": "pass", "message": "EA flagship release readiness is clear."},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
