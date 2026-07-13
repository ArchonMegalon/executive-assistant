#!/usr/bin/env python3
"""Materialize a bounded, non-authoritative observation of Chummer owner receipts.

This observer reads already-published filesystem evidence.  It never calls a
provider, opens a network connection, invokes Docker, changes an owner source,
or makes a release/blocker decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path(".codex-studio/published/EA_CHUMMER_LIVED_SYSTEM_OBSERVATION.generated.json")
DEFAULT_CANONICAL_PRODUCT_ROOT = Path(
    os.environ.get("EA_CHUMMER_DESIGN_PRODUCT_ROOT")
    or "/docker/chummercomplete/chummer-design/products/chummer"
)
DEFAULT_FLEET_ROOT = Path(os.environ.get("EA_CHUMMER_FLEET_ROOT") or "/docker/fleet")
DEFAULT_CHUMMER_ROOT = Path(os.environ.get("EA_CHUMMER_ROOT") or "/docker/chummercomplete")

ALLOWED_STATUSES = frozenset({"consistent", "attention_required", "invalid_inputs"})
PASS_VALUES = frozenset(
    {
        "clear",
        "consistent",
        "gold_ready",
        "pass",
        "passed",
        "published",
        "ready",
        "release_ready",
    }
)

MIRRORED_FILES = (
    ("readme", "README.md", "markdown"),
    ("group_blockers", "GROUP_BLOCKERS.md", "markdown"),
    ("closeout", "CAMPAIGN_OS_FLAGSHIP_CLOSEOUT.md", "markdown"),
    ("scorecard", "CAMPAIGN_OPERABILITY_SCORECARD.generated.json", "json"),
    ("final_gold_graph", "FINAL_GOLD_GRAPH.generated.json", "json"),
    ("weekly_pulse", "WEEKLY_PRODUCT_PULSE.generated.json", "json"),
)

CHECK_KEYS = (
    "input_integrity",
    "mirror_canonical_alignment",
    "canonical_blk010_narrative_alignment",
    "campaign_operability_scorecard_freshness",
    "final_gold_graph_freshness",
    "desktop_proof_posture",
    "release_ready_posture",
    "release_channel_projection_alignment",
    "fleet_journey_context",
)


@dataclass(frozen=True)
class InputSpec:
    key: str
    owner: str
    path: Path
    media_type: str


@dataclass(frozen=True)
class ObservationPaths:
    ea_mirror_product_root: Path
    canonical_product_root: Path
    fleet_flagship_readiness: Path
    fleet_journey_gates: Path
    desktop_executable_exit_gate: Path
    windows_desktop_exit_gate: Path
    windows_installer_visual_audit: Path
    release_ready: Path
    registry_release_channel: Path
    portal_release_channel: Path

    @classmethod
    def defaults(cls, *, ea_root: Path = ROOT) -> "ObservationPaths":
        return cls(
            ea_mirror_product_root=ea_root / ".codex-design" / "product",
            canonical_product_root=DEFAULT_CANONICAL_PRODUCT_ROOT,
            fleet_flagship_readiness=(
                DEFAULT_FLEET_ROOT
                / ".codex-studio"
                / "published"
                / "FLAGSHIP_PRODUCT_READINESS.generated.json"
            ),
            fleet_journey_gates=(
                DEFAULT_FLEET_ROOT / ".codex-studio" / "published" / "JOURNEY_GATES.generated.json"
            ),
            desktop_executable_exit_gate=(
                DEFAULT_CHUMMER_ROOT
                / "chummer6-ui"
                / ".codex-studio"
                / "published"
                / "DESKTOP_EXECUTABLE_EXIT_GATE.generated.json"
            ),
            windows_desktop_exit_gate=(
                DEFAULT_CHUMMER_ROOT
                / "chummer6-ui"
                / ".codex-studio"
                / "published"
                / "UI_WINDOWS_DESKTOP_EXIT_GATE.generated.json"
            ),
            windows_installer_visual_audit=(
                DEFAULT_CHUMMER_ROOT
                / "chummer.run-services"
                / ".codex-studio"
                / "published"
                / "WINDOWS_INSTALLER_VISUAL_AUDIT.generated.json"
            ),
            release_ready=(
                DEFAULT_CHUMMER_ROOT
                / "chummer.run-services"
                / ".codex-studio"
                / "published"
                / "RELEASE_READY.generated.json"
            ),
            registry_release_channel=(
                DEFAULT_CHUMMER_ROOT
                / "chummer-hub-registry"
                / ".codex-studio"
                / "published"
                / "RELEASE_CHANNEL.generated.json"
            ),
            portal_release_channel=(
                DEFAULT_CHUMMER_ROOT
                / "chummer.run-services"
                / "Chummer.Portal"
                / "downloads"
                / "RELEASE_CHANNEL.generated.json"
            ),
        )

    def specs(self) -> list[InputSpec]:
        specs: list[InputSpec] = []
        for short_key, filename, media_type in MIRRORED_FILES:
            specs.append(
                InputSpec(
                    key=f"mirror_{short_key}",
                    owner="ea_design_mirror",
                    path=self.ea_mirror_product_root / filename,
                    media_type=media_type,
                )
            )
            specs.append(
                InputSpec(
                    key=f"canonical_{short_key}",
                    owner="chummer6_design",
                    path=self.canonical_product_root / filename,
                    media_type=media_type,
                )
            )
        specs.extend(
            [
                InputSpec(
                    "fleet_flagship_readiness",
                    "fleet",
                    self.fleet_flagship_readiness,
                    "json",
                ),
                InputSpec("fleet_journey_gates", "fleet", self.fleet_journey_gates, "json"),
                InputSpec(
                    "desktop_executable_exit_gate",
                    "chummer6_ui",
                    self.desktop_executable_exit_gate,
                    "json",
                ),
                InputSpec(
                    "windows_desktop_exit_gate",
                    "chummer6_ui",
                    self.windows_desktop_exit_gate,
                    "json",
                ),
                InputSpec(
                    "windows_installer_visual_audit",
                    "chummer_run_services",
                    self.windows_installer_visual_audit,
                    "json",
                ),
                InputSpec("release_ready", "chummer_run_services", self.release_ready, "json"),
                InputSpec(
                    "registry_release_channel",
                    "chummer6_hub_registry",
                    self.registry_release_channel,
                    "json",
                ),
                InputSpec(
                    "portal_release_channel",
                    "chummer_run_services",
                    self.portal_release_channel,
                    "json",
                ),
            ]
        )
        return specs


def required_input_keys() -> tuple[str, ...]:
    """Return the stable input-key contract without depending on host paths."""
    return tuple(spec.key for spec in ObservationPaths.defaults().specs())


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _generated_at(payload: dict[str, Any]) -> str | None:
    for key in ("generated_at_utc", "generated_at", "generatedAt", "as_of"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_pass(value: Any) -> bool:
    return _normalized(value) in PASS_VALUES


def _read_inputs(
    specs: list[InputSpec],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, str], list[str]]:
    bindings: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    errors: list[str] = []

    for spec in specs:
        path = spec.path.expanduser().resolve(strict=False)
        binding: dict[str, Any] = {
            "key": spec.key,
            "owner": spec.owner,
            "path": path.as_posix(),
            "media_type": spec.media_type,
            "sha256": None,
            "size_bytes": None,
            "observed_contract_name": None,
            "observed_generated_at_utc": None,
        }
        try:
            raw = path.read_bytes()
        except OSError as exc:
            error = f"{spec.key}: unreadable input ({exc.__class__.__name__})"
            binding["error"] = error
            errors.append(error)
            bindings.append(binding)
            continue

        binding["sha256"] = hashlib.sha256(raw).hexdigest()
        binding["size_bytes"] = len(raw)
        if spec.media_type == "json":
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                error = f"{spec.key}: invalid JSON ({exc.__class__.__name__})"
                binding["error"] = error
                errors.append(error)
            else:
                if not isinstance(value, dict):
                    error = f"{spec.key}: JSON root must be an object"
                    binding["error"] = error
                    errors.append(error)
                else:
                    payloads[spec.key] = value
                    binding["observed_contract_name"] = str(value.get("contract_name") or "") or None
                    binding["observed_generated_at_utc"] = _generated_at(value)
        else:
            try:
                texts[spec.key] = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                error = f"{spec.key}: invalid UTF-8 ({exc.__class__.__name__})"
                binding["error"] = error
                errors.append(error)
        bindings.append(binding)

    return bindings, payloads, texts, errors


def _check(key: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"unsupported observation status: {status}")
    value: dict[str, Any] = {"key": key, "status": status, "message": message}
    if details:
        value["details"] = details
    return value


def _posture_for_blk010(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower())
    active = bool(
        re.search(
            r"blk-010.{0,220}(?:remain active|remains active|is active|still active)",
            normalized,
        )
    )
    cleared = bool(
        re.search(
            r"blk-010.{0,220}(?:is cleared|cleared\s+20\d\d|proof is cleared)",
            normalized,
        )
    )
    if active and cleared:
        return "contradictory_within_document"
    if active:
        return "active"
    if cleared:
        return "cleared"
    return "unspecified"


def _attention_signal(key: str, payload: dict[str, Any]) -> bool:
    if key == "canonical_weekly_pulse":
        readiness = payload.get("flagship_readiness")
        release_health = payload.get("release_health")
        decisions = payload.get("governor_decisions")
        readiness = readiness if isinstance(readiness, dict) else {}
        release_health = release_health if isinstance(release_health, dict) else {}
        decisions = decisions if isinstance(decisions, list) else []
        return (
            not _is_pass(readiness.get("proof_status"))
            or _normalized(release_health.get("state")) in {"needs_attention", "watch", "fail", "failed"}
            or any(
                isinstance(item, dict) and _normalized(item.get("action")) == "freeze_launch"
                for item in decisions
            )
        )
    if key == "fleet_flagship_readiness":
        return not _is_pass(payload.get("status")) or not _is_pass(payload.get("scoped_status"))
    if key in {
        "desktop_executable_exit_gate",
        "windows_desktop_exit_gate",
        "windows_installer_visual_audit",
    }:
        return not _is_pass(payload.get("status"))
    if key == "release_ready":
        return not _is_pass(payload.get("status")) or _normalized(payload.get("verdict")).startswith("not_")
    return False


def _claim_freshness_check(
    *,
    check_key: str,
    claim_key: str,
    payloads: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    required = (
        claim_key,
        "canonical_weekly_pulse",
        "fleet_flagship_readiness",
        "desktop_executable_exit_gate",
        "windows_desktop_exit_gate",
        "windows_installer_visual_audit",
        "release_ready",
    )
    missing = [key for key in required if key not in payloads]
    if missing:
        return (
            _check(
                check_key,
                "invalid_inputs",
                "Freshness cannot be observed because required owner receipts are invalid.",
                missing_input_keys=missing,
            ),
            None,
        )

    claim = payloads[claim_key]
    claim_generated_at = _generated_at(claim)
    claim_timestamp = _parse_timestamp(claim_generated_at)
    if claim_timestamp is None:
        return (
            _check(
                check_key,
                "invalid_inputs",
                "The claimed readiness receipt has no valid generation timestamp.",
                claim_input_key=claim_key,
                observed_generated_at_utc=claim_generated_at,
            ),
            None,
        )

    claim_value = claim.get("verdict") or claim.get("status")
    positive_claim = _is_pass(claim.get("status")) or _is_pass(claim.get("verdict"))
    newer_attention_inputs: list[dict[str, Any]] = []
    timestamp_errors: list[str] = []
    for source_key in required[1:]:
        source = payloads[source_key]
        source_generated_at = _generated_at(source)
        source_timestamp = _parse_timestamp(source_generated_at)
        if source_timestamp is None:
            timestamp_errors.append(source_key)
            continue
        if _attention_signal(source_key, source) and source_timestamp > claim_timestamp:
            newer_attention_inputs.append(
                {
                    "input_key": source_key,
                    "observed_generated_at_utc": source_generated_at,
                }
            )

    if timestamp_errors:
        return (
            _check(
                check_key,
                "invalid_inputs",
                "Freshness cannot be ordered because an owner receipt timestamp is invalid.",
                invalid_timestamp_input_keys=timestamp_errors,
            ),
            None,
        )

    if positive_claim and newer_attention_inputs:
        finding = {
            "code": f"{check_key}_superseded",
            "message": "A positive generated claim predates newer owner receipts that require attention.",
            "evidence_keys": [claim_key]
            + [str(item["input_key"]) for item in newer_attention_inputs],
            "owner_action": "The canonical design owner should regenerate and reconcile this claim from current owner evidence.",
        }
        return (
            _check(
                check_key,
                "attention_required",
                "The generated claim is superseded by newer owner evidence.",
                claim_input_key=claim_key,
                claim_observed_value=str(claim_value or ""),
                claim_generated_at_utc=claim_generated_at,
                newer_attention_inputs=newer_attention_inputs,
            ),
            finding,
        )

    return (
        _check(
            check_key,
            "consistent",
            "No newer attention receipt supersedes the generated claim.",
            claim_input_key=claim_key,
            claim_observed_value=str(claim_value or ""),
            claim_generated_at_utc=claim_generated_at,
        ),
        None,
    )


def _channel_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts_value = payload.get("artifacts")
    artifacts = artifacts_value if isinstance(artifacts_value, list) else []
    artifact_signatures: list[dict[str, str]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        artifact_signatures.append(
            {
                "artifact_id": str(item.get("artifactId") or item.get("id") or ""),
                "file_name": str(item.get("fileName") or ""),
                "platform": str(item.get("platform") or ""),
                "kind": str(item.get("kind") or ""),
                "sha256": str(item.get("sha256") or ""),
            }
        )
    artifact_signatures.sort(
        key=lambda item: (
            item["artifact_id"],
            item["file_name"],
            item["platform"],
            item["kind"],
            item["sha256"],
        )
    )
    first_artifact = artifacts[0] if artifacts and isinstance(artifacts[0], dict) else {}
    return {
        "observed_state": str(payload.get("status") or ""),
        "channel": str(payload.get("channel") or payload.get("channelId") or ""),
        "version": str(
            payload.get("version")
            or payload.get("releaseVersion")
            or first_artifact.get("version")
            or first_artifact.get("releaseVersion")
            or ""
        ),
        "supportability": str(payload.get("supportability") or ""),
        "rollout": str(payload.get("rollout") or payload.get("rolloutState") or ""),
        "artifacts": artifact_signatures,
    }


def build_observation(
    paths: ObservationPaths,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    bindings, payloads, texts, errors = _read_inputs(paths.specs())
    binding_by_key = {str(item["key"]): item for item in bindings}
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    if errors:
        checks.append(
            _check(
                "input_integrity",
                "invalid_inputs",
                "One or more required owner inputs are unreadable or invalid.",
                errors=errors,
            )
        )
    else:
        checks.append(
            _check(
                "input_integrity",
                "consistent",
                "All required owner inputs were read and hash-bound.",
                input_count=len(bindings),
            )
        )

    drift_pairs: list[dict[str, Any]] = []
    mirror_missing: list[str] = []
    for short_key, _filename, _media_type in MIRRORED_FILES:
        mirror_key = f"mirror_{short_key}"
        canonical_key = f"canonical_{short_key}"
        mirror_binding = binding_by_key.get(mirror_key, {})
        canonical_binding = binding_by_key.get(canonical_key, {})
        mirror_hash = mirror_binding.get("sha256")
        canonical_hash = canonical_binding.get("sha256")
        if not mirror_hash or not canonical_hash:
            mirror_missing.extend([key for key, digest in ((mirror_key, mirror_hash), (canonical_key, canonical_hash)) if not digest])
        elif mirror_hash != canonical_hash:
            drift_pairs.append(
                {
                    "mirror_input_key": mirror_key,
                    "canonical_input_key": canonical_key,
                    "mirror_sha256": mirror_hash,
                    "canonical_sha256": canonical_hash,
                }
            )
    if mirror_missing:
        checks.append(
            _check(
                "mirror_canonical_alignment",
                "invalid_inputs",
                "Mirror alignment cannot be observed because required inputs are invalid.",
                missing_digest_input_keys=sorted(set(mirror_missing)),
            )
        )
    elif drift_pairs:
        checks.append(
            _check(
                "mirror_canonical_alignment",
                "attention_required",
                "EA mirror content differs from canonical design content.",
                drift_pairs=drift_pairs,
            )
        )
        findings.append(
            {
                "code": "mirror_canonical_drift",
                "message": "One or more EA design-mirror files do not match their canonical counterparts.",
                "evidence_keys": [
                    key
                    for pair in drift_pairs
                    for key in (pair["mirror_input_key"], pair["canonical_input_key"])
                ],
                "owner_action": "The EA mirror maintainer should refresh from canonical design truth without editing canonical sources.",
            }
        )
    else:
        checks.append(
            _check(
                "mirror_canonical_alignment",
                "consistent",
                "All observed EA mirror files match canonical content by SHA-256.",
                compared_pair_count=len(MIRRORED_FILES),
            )
        )

    narrative_keys = (
        "canonical_readme",
        "canonical_group_blockers",
        "canonical_closeout",
    )
    if any(key not in texts for key in narrative_keys):
        checks.append(
            _check(
                "canonical_blk010_narrative_alignment",
                "invalid_inputs",
                "BLK-010 narrative posture cannot be observed from invalid canonical inputs.",
                missing_input_keys=[key for key in narrative_keys if key not in texts],
            )
        )
    else:
        postures = {key: _posture_for_blk010(texts[key]) for key in narrative_keys}
        explicit = {value for value in postures.values() if value in {"active", "cleared"}}
        invalid_postures = [key for key, value in postures.items() if value == "unspecified"]
        internal_contradictions = [
            key for key, value in postures.items() if value == "contradictory_within_document"
        ]
        if invalid_postures:
            checks.append(
                _check(
                    "canonical_blk010_narrative_alignment",
                    "invalid_inputs",
                    "A required canonical document does not expose a recognizable BLK-010 posture.",
                    observed_postures=postures,
                    unspecified_input_keys=invalid_postures,
                )
            )
        elif len(explicit) > 1 or internal_contradictions:
            checks.append(
                _check(
                    "canonical_blk010_narrative_alignment",
                    "attention_required",
                    "Canonical design documents disagree about BLK-010 posture.",
                    observed_postures=postures,
                )
            )
            findings.append(
                {
                    "code": "canonical_blk010_narrative_contradiction",
                    "message": "Canonical README/blocker/closeout narratives do not state one BLK-010 posture.",
                    "evidence_keys": list(narrative_keys),
                    "owner_action": "The chummer6-design owner should reconcile the canonical narrative; EA cannot clear or reopen BLK-010.",
                }
            )
        else:
            checks.append(
                _check(
                    "canonical_blk010_narrative_alignment",
                    "consistent",
                    "Canonical design documents expose one BLK-010 posture.",
                    observed_postures=postures,
                )
            )

    scorecard_check, scorecard_finding = _claim_freshness_check(
        check_key="campaign_operability_scorecard_freshness",
        claim_key="canonical_scorecard",
        payloads=payloads,
    )
    checks.append(scorecard_check)
    if scorecard_finding:
        findings.append(scorecard_finding)

    gold_check, gold_finding = _claim_freshness_check(
        check_key="final_gold_graph_freshness",
        claim_key="canonical_final_gold_graph",
        payloads=payloads,
    )
    checks.append(gold_check)
    if gold_finding:
        findings.append(gold_finding)

    desktop_keys = (
        "fleet_flagship_readiness",
        "desktop_executable_exit_gate",
        "windows_desktop_exit_gate",
        "windows_installer_visual_audit",
    )
    if any(key not in payloads for key in desktop_keys):
        checks.append(
            _check(
                "desktop_proof_posture",
                "invalid_inputs",
                "Desktop proof posture cannot be observed from invalid owner receipts.",
                missing_input_keys=[key for key in desktop_keys if key not in payloads],
            )
        )
    else:
        observed = {
            key: str(payloads[key].get("status") or "")
            for key in desktop_keys
        }
        observed["fleet_flagship_scoped"] = str(
            payloads["fleet_flagship_readiness"].get("scoped_status") or ""
        )
        invalid_values = [key for key, value in observed.items() if not value.strip()]
        attention_values = [key for key, value in observed.items() if value.strip() and not _is_pass(value)]
        if invalid_values:
            checks.append(
                _check(
                    "desktop_proof_posture",
                    "invalid_inputs",
                    "A desktop owner receipt has no observable posture value.",
                    observed_values=observed,
                    missing_value_keys=invalid_values,
                )
            )
        elif attention_values:
            checks.append(
                _check(
                    "desktop_proof_posture",
                    "attention_required",
                    "One or more owner desktop proof receipts are not green.",
                    observed_values=observed,
                    attention_input_keys=attention_values,
                )
            )
            findings.append(
                {
                    "code": "desktop_proof_not_green",
                    "message": "Current Fleet/UI/Windows proof does not expose one green desktop posture.",
                    "evidence_keys": list(desktop_keys),
                    "owner_action": "Fleet, UI, and release owners should publish current promoted-artifact desktop proof.",
                }
            )
        else:
            checks.append(
                _check(
                    "desktop_proof_posture",
                    "consistent",
                    "Fleet and desktop owner receipts expose green posture.",
                    observed_values=observed,
                )
            )

    release_payload = payloads.get("release_ready")
    if release_payload is None:
        checks.append(
            _check(
                "release_ready_posture",
                "invalid_inputs",
                "Release readiness posture cannot be observed from an invalid owner receipt.",
                missing_input_keys=["release_ready"],
            )
        )
    else:
        observed_state = str(release_payload.get("status") or "")
        observed_verdict = str(release_payload.get("verdict") or "")
        failures = release_payload.get("failures")
        failure_count = len(failures) if isinstance(failures, list) else 0
        if not observed_state:
            checks.append(
                _check(
                    "release_ready_posture",
                    "invalid_inputs",
                    "The release owner receipt has no observable posture value.",
                    observed_value=observed_state,
                    observed_verdict=observed_verdict,
                )
            )
        elif not _is_pass(observed_state) or _normalized(observed_verdict).startswith("not_"):
            checks.append(
                _check(
                    "release_ready_posture",
                    "attention_required",
                    "The current release-owner receipt requires attention.",
                    observed_value=observed_state,
                    observed_verdict=observed_verdict,
                    owner_failure_count=failure_count,
                )
            )
            findings.append(
                {
                    "code": "release_ready_not_green",
                    "message": "The current owner-produced RELEASE_READY receipt is not green.",
                    "evidence_keys": ["release_ready"],
                    "owner_action": "The Chummer release owners should resolve and republish owner-controlled release evidence.",
                }
            )
        else:
            checks.append(
                _check(
                    "release_ready_posture",
                    "consistent",
                    "The current release-owner receipt exposes green posture.",
                    observed_value=observed_state,
                    observed_verdict=observed_verdict,
                    owner_failure_count=failure_count,
                )
            )

    registry_payload = payloads.get("registry_release_channel")
    portal_payload = payloads.get("portal_release_channel")
    if registry_payload is None or portal_payload is None:
        checks.append(
            _check(
                "release_channel_projection_alignment",
                "invalid_inputs",
                "Release-channel alignment cannot be observed from invalid inputs.",
                missing_input_keys=[
                    key
                    for key, value in (
                        ("registry_release_channel", registry_payload),
                        ("portal_release_channel", portal_payload),
                    )
                    if value is None
                ],
            )
        )
    else:
        registry_snapshot = _channel_snapshot(registry_payload)
        portal_snapshot = _channel_snapshot(portal_payload)
        if registry_snapshot != portal_snapshot:
            checks.append(
                _check(
                    "release_channel_projection_alignment",
                    "attention_required",
                    "Registry and Portal release-channel projections disagree.",
                    registry_snapshot=registry_snapshot,
                    portal_snapshot=portal_snapshot,
                )
            )
            findings.append(
                {
                    "code": "release_channel_split_brain",
                    "message": "The owner registry and workspace Portal publish different release-channel tuples.",
                    "evidence_keys": ["registry_release_channel", "portal_release_channel"],
                    "owner_action": "Registry and Portal owners should reconcile the authoritative channel and its projection.",
                }
            )
        else:
            checks.append(
                _check(
                    "release_channel_projection_alignment",
                    "consistent",
                    "Registry and Portal release-channel projections agree semantically.",
                    registry_snapshot=registry_snapshot,
                    portal_snapshot=portal_snapshot,
                )
            )

    journey_payload = payloads.get("fleet_journey_gates")
    if journey_payload is None:
        checks.append(
            _check(
                "fleet_journey_context",
                "invalid_inputs",
                "Fleet journey context cannot be observed from an invalid receipt.",
                missing_input_keys=["fleet_journey_gates"],
            )
        )
    else:
        summary = journey_payload.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        observed_state = str(summary.get("overall_state") or "")
        if not observed_state:
            checks.append(
                _check(
                    "fleet_journey_context",
                    "invalid_inputs",
                    "The Fleet journey receipt has no overall-state observation.",
                )
            )
        elif _normalized(observed_state) != "ready":
            checks.append(
                _check(
                    "fleet_journey_context",
                    "attention_required",
                    "Fleet journey gates are not currently ready.",
                    observed_value=observed_state,
                    blocked_count=int(summary.get("blocked_count") or 0),
                    warning_count=int(summary.get("warning_count") or 0),
                )
            )
            findings.append(
                {
                    "code": "fleet_journey_context_not_ready",
                    "message": "The owner Fleet journey receipt is not currently ready.",
                    "evidence_keys": ["fleet_journey_gates"],
                    "owner_action": "Fleet should refresh journey evidence; EA does not alter journey-gate truth.",
                }
            )
        else:
            checks.append(
                _check(
                    "fleet_journey_context",
                    "consistent",
                    "Fleet journey gates are ready on the observed owner receipt.",
                    observed_value=observed_state,
                    ready_count=int(summary.get("ready_count") or 0),
                    total_journey_count=int(summary.get("total_journey_count") or 0),
                )
            )

    check_statuses = [str(item["status"]) for item in checks]
    if "invalid_inputs" in check_statuses:
        overall_status = "invalid_inputs"
    elif "attention_required" in check_statuses:
        overall_status = "attention_required"
    else:
        overall_status = "consistent"

    return {
        "contract_name": "ea.chummer_lived_system_observation",
        "contract_version": "1.0.0",
        "generated_at_utc": generated_at or _utcnow_iso(),
        "status": overall_status,
        "authoritative": False,
        "release_decision": None,
        "scope": {
            "observation_only": True,
            "description": "Hash-bound EA observation of Chummer owner evidence.",
            "does_not_clear_or_reopen_blockers": True,
            "does_not_publish_or_promote_releases": True,
        },
        "execution_policy": {
            "filesystem_input_mode": "read_only",
            "output_write_mode": "atomic_receipt_only",
            "network_actions": 0,
            "provider_actions": 0,
            "docker_actions": 0,
            "source_mutations": 0,
        },
        "authority_boundaries": {
            "canonical_design_owner": "chummer6_design",
            "release_channel_owner": "chummer6_hub_registry",
            "release_execution_owners": ["fleet", "chummer6_ui", "chummer_run_services"],
            "ea_is_release_authority": False,
            "ea_is_blocker_authority": False,
        },
        "summary": {
            "input_count": len(bindings),
            "check_count": len(checks),
            "consistent_check_count": check_statuses.count("consistent"),
            "attention_required_check_count": check_statuses.count("attention_required"),
            "invalid_input_check_count": check_statuses.count("invalid_inputs"),
            "finding_count": len(findings),
        },
        "input_bindings": bindings,
        "checks": checks,
        "findings": findings,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main() -> int:
    defaults = ObservationPaths.defaults()
    parser = argparse.ArgumentParser(
        description="Materialize a non-authoritative Chummer lived-system observation."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="EA repository root for relative paths.")
    parser.add_argument(
        "--ea-mirror-product-root",
        type=Path,
        default=defaults.ea_mirror_product_root,
    )
    parser.add_argument(
        "--canonical-product-root",
        type=Path,
        default=defaults.canonical_product_root,
    )
    parser.add_argument("--fleet-flagship-readiness", type=Path, default=defaults.fleet_flagship_readiness)
    parser.add_argument("--fleet-journey-gates", type=Path, default=defaults.fleet_journey_gates)
    parser.add_argument(
        "--desktop-executable-exit-gate",
        type=Path,
        default=defaults.desktop_executable_exit_gate,
    )
    parser.add_argument(
        "--windows-desktop-exit-gate",
        type=Path,
        default=defaults.windows_desktop_exit_gate,
    )
    parser.add_argument(
        "--windows-installer-visual-audit",
        type=Path,
        default=defaults.windows_installer_visual_audit,
    )
    parser.add_argument("--release-ready", type=Path, default=defaults.release_ready)
    parser.add_argument(
        "--registry-release-channel",
        type=Path,
        default=defaults.registry_release_channel,
    )
    parser.add_argument(
        "--portal-release-channel",
        type=Path,
        default=defaults.portal_release_channel,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", help="Optional deterministic UTC timestamp for tests/replay.")
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    paths = ObservationPaths(
        ea_mirror_product_root=_resolve(root, args.ea_mirror_product_root),
        canonical_product_root=_resolve(root, args.canonical_product_root),
        fleet_flagship_readiness=_resolve(root, args.fleet_flagship_readiness),
        fleet_journey_gates=_resolve(root, args.fleet_journey_gates),
        desktop_executable_exit_gate=_resolve(root, args.desktop_executable_exit_gate),
        windows_desktop_exit_gate=_resolve(root, args.windows_desktop_exit_gate),
        windows_installer_visual_audit=_resolve(root, args.windows_installer_visual_audit),
        release_ready=_resolve(root, args.release_ready),
        registry_release_channel=_resolve(root, args.registry_release_channel),
        portal_release_channel=_resolve(root, args.portal_release_channel),
    )
    receipt = build_observation(paths, generated_at=args.generated_at)
    output_path = _resolve(root, args.output)
    _atomic_write_json(output_path, receipt)
    if args.stdout:
        print(json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "output": output_path.as_posix(),
                    "contract_name": receipt["contract_name"],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
