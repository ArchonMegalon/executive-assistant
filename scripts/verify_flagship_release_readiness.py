#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

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
            content.decode("utf-8"), object_pairs_hook=_unique_json_object
        )
    except _DuplicateJSONKey:
        return {}, ["weekly product pulse contains duplicate JSON keys"]
    except (UnicodeDecodeError, json.JSONDecodeError):
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
    browser_status = (
        str(browser.get("status") or browser.get("receipt_status") or "")
        .strip()
        .lower()
    )
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
    if browser_status != "pass":
        issues.append(
            f"browser workflow proof is {browser_status or 'missing'}, expected pass"
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
