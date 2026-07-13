#!/usr/bin/env python3
"""Materialize the fail-closed EA flagship cross-release receipt.

The materializer is deliberately read-only apart from its single atomic output.
It projects a small, secret-free set of facts from already-created owner evidence;
it does not invoke Docker, contact a provider, mutate an owner source, or promote a
release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_NAME = "ea.flagship.cross_release_launch_readiness.v2"
LEGACY_CONTRACT_NAME = "ea.flagship.cross_release_launch_readiness.v1"
OUTPUT_NAME = "flagship-cross-release-v2.json"
MAX_INPUT_BYTES = 8 * 1024 * 1024

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PROJECT_RE = re.compile(r"^ea-core-candidate-[a-z0-9][a-z0-9-]{2,79}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)


class EvidenceValidationError(ValueError):
    """Raised with bounded codes only; source values and paths are never included."""

    def __init__(self, *codes: str) -> None:
        normalized = tuple(sorted({str(code) for code in codes if str(code)}))
        super().__init__(",".join(normalized) or "evidence_invalid")
        self.codes = normalized or ("evidence_invalid",)


@dataclass(frozen=True)
class EvidenceSpec:
    key: str
    identity_field: str
    identity_value: str
    private: bool = True


@dataclass(frozen=True)
class LoadedEvidence:
    spec: EvidenceSpec
    payload: dict[str, Any]
    sha256: str
    size_bytes: int
    mode: int
    source_name: str

    def binding(self) -> dict[str, object]:
        return {
            "key": self.spec.key,
            "source_name": self.source_name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "mode_octal": f"{self.mode:04o}",
            "identity_field": self.spec.identity_field,
            "identity_value": self.spec.identity_value,
            "observed_status": _first_text(
                self.payload.get("status"),
                self.payload.get("state"),
                self.payload.get("verdict"),
            ),
        }


EVIDENCE_SPECS = (
    EvidenceSpec("manfred_runtime", "schema", "ea.manfred_memorial_candidate_runtime.v3"),
    EvidenceSpec("manfred_release", "schema", "ea.flagship.manfred_memorial_release.v1"),
    EvidenceSpec(
        "manfred_transport",
        "schema",
        "ea.manfred_memorial_transport_adversarial.v1",
    ),
    EvidenceSpec(
        "manfred_live_boundary",
        "schema",
        "ea.manfred_memorial_post_retention_boundary.v2",
    ),
    EvidenceSpec(
        "property_3d_interaction",
        "schema",
        "propertyquarry.generated_reconstruction.browser_proof.v2",
    ),
    EvidenceSpec("property_3d_release", "schema", "ea.flagship.property_3d_release.v1"),
    EvidenceSpec("ea_operator_readiness", "contract_name", "ea.operator_readiness.v1"),
    EvidenceSpec(
        "localization_projection",
        "contract_name",
        "ea.chummer_localization_projection.v1",
    ),
    EvidenceSpec(
        "lived_system_observation",
        "contract_name",
        "ea.chummer_lived_system_observation",
    ),
    EvidenceSpec(
        "chummer_flagship_readiness",
        "contract_name",
        "fleet.flagship_product_readiness",
        private=False,
    ),
    EvidenceSpec(
        "chummer_weekly_pulse",
        "contract_name",
        "chummer.weekly_product_pulse",
        private=False,
    ),
    EvidenceSpec(
        "chummer_journey_gates",
        "contract_name",
        "fleet.journey_gates",
        private=False,
    ),
    EvidenceSpec(
        "chummer_release_ready",
        "contract_name",
        "chummer.release_ready",
        private=False,
    ),
    EvidenceSpec(
        "ea_core_runtime",
        "contract_name",
        "ea.core_candidate_runtime_verification.v1",
    ),
    EvidenceSpec(
        "ea_release_authority",
        "contract_name",
        "ea.release_authority_status.v1",
    ),
)


def _first_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _items(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _is_pass(value: object) -> bool:
    return str(value or "").strip().lower() in {
        "clear",
        "consistent",
        "pass",
        "passed",
        "ready",
        "release_ready",
    }


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceValidationError(code)


def _read_regular_json(path: Path, spec: EvidenceSpec) -> LoadedEvidence:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise EvidenceValidationError(f"{spec.key}_unreadable") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceValidationError(f"{spec.key}_not_regular")
        mode = stat.S_IMODE(metadata.st_mode)
        if spec.private:
            if mode != 0o600:
                raise EvidenceValidationError(f"{spec.key}_mode_not_0600")
        elif mode & 0o113:
            # Owner execution or any world write/execute bit is never valid evidence.
            raise EvidenceValidationError(f"{spec.key}_mode_unsafe")
        if metadata.st_size <= 1 or metadata.st_size > MAX_INPUT_BYTES:
            raise EvidenceValidationError(f"{spec.key}_size_invalid")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_INPUT_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_INPUT_BYTES:
                raise EvidenceValidationError(f"{spec.key}_size_invalid")
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EvidenceValidationError(f"{spec.key}_json_invalid") from None
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"{spec.key}_json_root_not_object")
    if value.get(spec.identity_field) != spec.identity_value:
        raise EvidenceValidationError(f"{spec.key}_identity_invalid")
    return LoadedEvidence(
        spec=spec,
        payload=value,
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        mode=mode,
        source_name=path.name,
    )


def _parse_utc(value: str) -> tuple[str, datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceValidationError("generated_at_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise EvidenceValidationError("generated_at_not_utc")
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return parsed.isoformat().replace("+00:00", "Z"), parsed


def _git_tree(*, repository: Path, commit: str, expected_tree: str) -> None:
    _require(repository.is_dir(), "ea_repository_invalid")
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(repository), "show", "-s", "--format=%T", commit],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8.0,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise EvidenceValidationError("ea_git_binding_unreadable") from None
    observed = result.stdout.strip()
    _require(result.returncode == 0 and observed == expected_tree, "ea_git_tree_mismatch")


def _all_checks_true(value: object) -> bool:
    checks = _mapping(value)
    return bool(checks) and all(item is True for item in checks.values())


def _add_blocker(
    blockers: list[dict[str, str]],
    *,
    code: str,
    owner: str,
    detail: str,
) -> None:
    if any(item["code"] == code for item in blockers):
        return
    blockers.append({"code": code, "owner": owner, "detail": detail})


def _secret_values(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)) and isinstance(item, str) and len(item) >= 8:
                found.add(item)
            found.update(_secret_values(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_secret_values(item))
    return found


def _assert_secret_free(payload: Mapping[str, object], evidence: Mapping[str, LoadedEvidence]) -> None:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    for item in evidence.values():
        for secret in _secret_values(item.payload):
            if secret in serialized:
                raise EvidenceValidationError("secret_value_projection_detected")


def _validate_manfred(
    evidence: Mapping[str, LoadedEvidence],
    *,
    generated_at: datetime,
    blockers: list[dict[str, str]],
) -> dict[str, object]:
    runtime = evidence["manfred_runtime"].payload
    release = evidence["manfred_release"].payload
    transport = evidence["manfred_transport"].payload
    boundary = evidence["manfred_live_boundary"].payload
    for key, payload in (
        ("runtime", runtime),
        ("release", release),
        ("transport", transport),
        ("boundary", boundary),
    ):
        _require(payload.get("status") in {"pass", "fail"}, f"manfred_{key}_status_invalid")

    source = _mapping(release.get("source"))
    artifact = _mapping(release.get("artifact"))
    candidate = _mapping(release.get("candidate"))
    publication = _mapping(release.get("publication_boundary"))
    live_candidate = _mapping(boundary.get("candidate"))
    guard = _mapping(boundary.get("guard"))
    commit = _first_text(source.get("commit"))
    tree = _first_text(source.get("tree"))
    image_id = _first_text(artifact.get("image_id"))
    project = _first_text(candidate.get("compose_project"))
    _require(bool(GIT_OBJECT_RE.fullmatch(commit)), "manfred_commit_invalid")
    _require(bool(GIT_OBJECT_RE.fullmatch(tree)), "manfred_tree_invalid")
    _require(bool(IMAGE_ID_RE.fullmatch(image_id)), "manfred_image_id_invalid")
    _require(source.get("worktree_clean") is True, "manfred_worktree_not_clean")
    _require(runtime.get("image_source_revision") == commit, "manfred_runtime_commit_mismatch")
    _require(runtime.get("runtime_source_revision") == commit, "manfred_runtime_revision_mismatch")
    _require(runtime.get("image_id") == image_id, "manfred_runtime_image_mismatch")
    _require(runtime.get("compose_project") == project, "manfred_runtime_project_mismatch")
    _require(transport.get("commit") == commit, "manfred_transport_commit_mismatch")
    _require(transport.get("image_id") == image_id, "manfred_transport_image_mismatch")
    _require(transport.get("compose_project") == project, "manfred_transport_project_mismatch")
    _require(live_candidate.get("commit") == commit, "manfred_boundary_commit_mismatch")
    _require(live_candidate.get("image_id") == image_id, "manfred_boundary_image_mismatch")
    _require(live_candidate.get("compose_project") == project, "manfred_boundary_project_mismatch")
    _require(
        candidate.get("runtime_receipt_sha256") == evidence["manfred_runtime"].sha256,
        "manfred_runtime_hash_binding_mismatch",
    )
    _require(
        _mapping(release.get("transport")).get("receipt_sha256")
        == evidence["manfred_transport"].sha256,
        "manfred_transport_hash_binding_mismatch",
    )
    _require(artifact.get("private_memorial_context_baked") is False, "manfred_private_context_baked")
    _require(artifact.get("provider_credentials_baked") is False, "manfred_provider_credentials_baked")
    _require(release.get("secrets_included") is False, "manfred_release_secret_flag_invalid")
    _require(boundary.get("secrets_included") is False, "manfred_boundary_secret_flag_invalid")
    _require(runtime.get("promotion_authority") is False, "manfred_runtime_authority_invalid")
    _require(transport.get("promotion_authority") is False, "manfred_transport_authority_invalid")
    _require(boundary.get("promotion_authority") is False, "manfred_boundary_authority_invalid")
    _require(boundary.get("live_mutation_performed") is False, "manfred_live_mutation_invalid")

    release_guard_values = (
        publication.get("soak_qualification_reset_at"),
        publication.get("earliest_no_reset_soak_end"),
        publication.get("fresh_activation_token_required"),
        publication.get("real_deployment_id_required"),
    )
    boundary_guard_values = (
        guard.get("soak_qualification_reset_at"),
        guard.get("earliest_no_reset_soak_end"),
        guard.get("fresh_activation_token_required"),
        guard.get("real_deployment_id_required"),
    )
    _require(release_guard_values == boundary_guard_values, "manfred_guard_binding_mismatch")
    deadline_text = _first_text(guard.get("earliest_no_reset_soak_end"))
    deadline_normalized, deadline = _parse_utc(deadline_text)
    if generated_at < deadline:
        _add_blocker(
            blockers,
            code="manfred_uninterrupted_soak_incomplete",
            owner="ea_release_operator",
            detail=f"The guarded no-reset soak is incomplete through {deadline_normalized}.",
        )
    if guard.get("fresh_activation_token_required") is True:
        _add_blocker(
            blockers,
            code="manfred_fresh_activation_token_required",
            owner="ea_release_operator",
            detail="A fresh activation token is required at the governed promotion boundary.",
        )
    if guard.get("real_deployment_id_required") is True:
        _add_blocker(
            blockers,
            code="manfred_real_deployment_id_required",
            owner="ea_release_operator",
            detail="A real deployment-system ID is required at activation time.",
        )
    guard_active = guard.get("active_state") == "active" and guard.get("sub_state") == "running"
    if not guard_active:
        _add_blocker(
            blockers,
            code="manfred_promotion_guard_not_active",
            owner="ea_release_operator",
            detail="The user-scoped Manfred promotion guard is not active and running.",
        )

    routes = _mapping(boundary.get("public_routes"))
    plural = _mapping(routes.get("https://myexternalbrain.com/memorials/manfred"))
    singular = _mapping(routes.get("https://myexternalbrain.com/memorial/manfred"))
    routes_activated = (
        plural.get("status") == 200
        and singular.get("status") in {200, 308}
        and plural.get("tls_verified") is True
        and singular.get("tls_verified") is True
    )
    if not routes_activated:
        _add_blocker(
            blockers,
            code="manfred_public_routes_not_activated",
            owner="ea_release_operator",
            detail="The live singular and plural Manfred memorial routes are not activated.",
        )

    browser = _mapping(release.get("browser"))
    acceptance = _mapping(release.get("acceptance"))
    candidate_ready = all(
        (
            runtime.get("status") == "pass",
            release.get("status") == "pass",
            transport.get("status") == "pass",
            boundary.get("status") == "pass",
            candidate.get("healthy") is True,
            live_candidate.get("services_healthy") == 4,
            live_candidate.get("container_restarts") == 0,
            live_candidate.get("oom_kills") == 0,
            browser.get("status") == "pass",
            browser.get("external_requests") == 0,
            browser.get("provider_requests") == 0,
            browser.get("page_errors") == 0,
            _mapping(acceptance.get("memorial_security_contracts")).get("status") == "pass",
            _mapping(acceptance.get("deployment_and_builder_contracts")).get("status") == "pass",
        )
    )
    if not candidate_ready:
        _add_blocker(
            blockers,
            code="manfred_candidate_not_ready",
            owner="ea_memorial_release_owner",
            detail="One or more Manfred candidate runtime, security, browser, or health checks are not green.",
        )
    return {
        "candidate_launch_ready": candidate_ready,
        "source_commit": commit,
        "source_tree": tree,
        "image_id": image_id,
        "compose_project": project,
        "runtime_receipt_sha256": evidence["manfred_runtime"].sha256,
        "release_receipt_sha256": evidence["manfred_release"].sha256,
        "transport_receipt_sha256": evidence["manfred_transport"].sha256,
        "live_boundary_receipt_sha256": evidence["manfred_live_boundary"].sha256,
        "guard_active": guard_active,
        "earliest_no_reset_soak_end": deadline_normalized,
        "live_routes_activated": routes_activated,
        "promotion_authority": boundary.get("promotion_authority") is True,
        "live_mutation_performed": boundary.get("live_mutation_performed") is True,
    }


def _validate_property(
    evidence: Mapping[str, LoadedEvidence],
    *,
    blockers: list[dict[str, str]],
) -> dict[str, object]:
    interaction = evidence["property_3d_interaction"].payload
    release = evidence["property_3d_release"].payload
    _require(interaction.get("status") in {"pass", "fail"}, "property_interaction_status_invalid")
    _require(release.get("status") in {"pass", "fail"}, "property_release_status_invalid")
    source = _mapping(release.get("source"))
    truth = _mapping(release.get("truth"))
    interaction_truth = _mapping(interaction.get("truth"))
    browser_evidence = _mapping(release.get("browser_evidence"))
    _require(
        browser_evidence.get("receipt_sha256") == evidence["property_3d_interaction"].sha256,
        "property_interaction_hash_binding_mismatch",
    )
    _require(source.get("worktree_clean") is True, "property_worktree_not_clean")
    _require(bool(GIT_OBJECT_RE.fullmatch(_first_text(source.get("commit")))), "property_commit_invalid")
    _require(bool(GIT_OBJECT_RE.fullmatch(_first_text(source.get("tree")))), "property_tree_invalid")
    _require(release.get("secrets_included") is False, "property_release_secret_flag_invalid")
    _require(truth.get("scope") == "offline_loopback_candidate_only", "property_release_scope_invalid")
    _require(
        truth.get("provider") == "propertyquarry_generated_reconstruction",
        "property_release_provider_identity_invalid",
    )
    _require(
        interaction.get("scope") == "offline_loopback_candidate_only",
        "property_interaction_scope_invalid",
    )
    _require(
        interaction_truth.get("provider") == "propertyquarry_generated_reconstruction",
        "property_interaction_provider_identity_invalid",
    )
    for key in (
        "verified_provider_capture",
        "satisfies_verified_tour_gate",
        "provider_calls_performed",
        "provider_credits_consumed",
        "live_publish_performed",
    ):
        _require(truth.get(key) is False, f"property_release_truth_{key}_invalid")
    for key in ("verified_provider_capture", "satisfies_verified_tour_gate"):
        _require(interaction_truth.get(key) is False, f"property_interaction_truth_{key}_invalid")
    _require(interaction.get("live_publish_performed") is False, "property_interaction_live_publish_invalid")

    viewer = _mapping(release.get("viewer"))
    browsers = _mapping(interaction.get("browser_proof"))
    desktop = _mapping(browsers.get("desktop"))
    mobile = _mapping(browsers.get("mobile"))
    vendor = _mapping(interaction.get("vendor_compliance"))
    polished = all(
        (
            release.get("status") == "pass",
            interaction.get("status") == "pass",
            truth.get("preview_kind") == "approximate_layout",
            truth.get("floorplan_only_disclosure_present") is True,
            interaction_truth.get("preview_kind_marker") == "approximate-layout",
            desktop.get("status") == "pass",
            mobile.get("status") == "pass",
            _all_checks_true(desktop.get("checks")),
            _all_checks_true(mobile.get("checks")),
            vendor.get("status") == "pass",
            all(
                viewer.get(key) is True
                for key in ("webgl", "orbit", "dollhouse", "room_view", "guided_route", "self_hosted_three")
            ),
            viewer.get("vendor_license_and_integrity") == "pass",
            browser_evidence.get("external_request_count") == 0,
            browser_evidence.get("browser_error_count") == 0,
        )
    )
    if not polished:
        _add_blocker(
            blockers,
            code="property_floorplan_reconstruction_not_polished",
            owner="propertyquarry_3d_owner",
            detail="The floorplan-derived 3D candidate does not have a fully green interaction and integrity proof.",
        )
    _add_blocker(
        blockers,
        code="property_verified_provider_capture_missing",
        owner="propertyquarry_spatial_provider_owner",
        detail="The polished candidate is an approximate floorplan-derived reconstruction, not a verified provider capture.",
    )
    return {
        "classification": "polished_floorplan_derived_approximate_reconstruction",
        "polished_reconstruction_ready": polished,
        "verified_provider_capture": False,
        "satisfies_verified_provider_tour_gate": False,
        "provider_tour_gate": "blocked",
        "provider_calls_performed": False,
        "provider_credits_consumed": False,
        "live_publish_performed": False,
        "floorplan_only_disclosure_present": True,
        "source_commit": source.get("commit"),
        "source_tree": source.get("tree"),
        "desktop_status": desktop.get("status"),
        "mobile_status": mobile.get("status"),
        "desktop_screenshot_sha256": browser_evidence.get("desktop_screenshot_sha256"),
        "mobile_screenshot_sha256": browser_evidence.get("mobile_screenshot_sha256"),
        "interaction_receipt_sha256": evidence["property_3d_interaction"].sha256,
        "release_receipt_sha256": evidence["property_3d_release"].sha256,
    }


def _validate_ea_core(
    evidence: Mapping[str, LoadedEvidence],
    *,
    commit: str,
    tree: str,
    image_id: str,
    project: str,
    deployment_id: str,
    blockers: list[dict[str, str]],
) -> dict[str, object]:
    runtime = evidence["ea_core_runtime"].payload
    authority = evidence["ea_release_authority"].payload
    _require(runtime.get("status") in {"pass", "fail"}, "ea_core_runtime_status_invalid")
    request = _mapping(runtime.get("request"))
    _require(request.get("compose_project") == project, "ea_core_runtime_project_mismatch")
    _require(request.get("expected_image_id") == image_id, "ea_core_runtime_image_mismatch")
    _require(request.get("expected_source_revision") == commit, "ea_core_runtime_commit_mismatch")
    scope = _mapping(runtime.get("scope"))
    privacy = _mapping(runtime.get("privacy"))
    _require(scope.get("inspection_only") is True, "ea_core_runtime_scope_invalid")
    _require(scope.get("runtime_mutations") is False, "ea_core_runtime_mutation_flag_invalid")
    for key in (
        "environment_values_emitted",
        "secret_values_emitted",
        "raw_http_bodies_emitted",
        "raw_subprocess_output_emitted",
    ):
        _require(privacy.get(key) is False, f"ea_core_runtime_privacy_{key}_invalid")

    _require(authority.get("state") in {"clear", "watch", "missing"}, "ea_authority_state_invalid")
    _require(authority.get("commit_sha") == commit, "ea_authority_commit_mismatch")
    _require(authority.get("deployment_id") == deployment_id, "ea_authority_deployment_mismatch")
    gate = _mapping(authority.get("gate"))
    deploy_gate = _mapping(authority.get("deploy_context_gate"))
    _require(gate.get("contract_name") == "ea.release_authority_gate.v1", "ea_authority_gate_identity_invalid")
    _require(deploy_gate.get("contract_name") == "ea.deploy_context_gate.v1", "ea_deploy_gate_identity_invalid")
    _require(gate.get("commit_sha") == commit, "ea_authority_gate_commit_mismatch")
    _require(gate.get("deployment_id") == deployment_id, "ea_authority_gate_deployment_mismatch")
    _require(deploy_gate.get("commit_sha") == commit, "ea_deploy_gate_commit_mismatch")
    _require(deploy_gate.get("deployment_id") == deployment_id, "ea_deploy_gate_deployment_mismatch")

    runtime_ready = runtime.get("status") == "pass" and runtime.get("issues") == []
    authority_ready = all(
        (
            authority.get("state") == "clear",
            authority.get("authority_posture") == "authoritative_runtime",
            authority.get("issues") == [],
            authority.get("source_worktree_dirty") is False,
            authority.get("source_dirty_count") == 0,
            authority.get("deployment_id_source") != "local_fallback",
            gate.get("status") == "pass",
            gate.get("authority_posture") == "authoritative_runtime",
            gate.get("issues") == [],
            deploy_gate.get("status") == "pass",
            deploy_gate.get("issues") == [],
        )
    )
    if not runtime_ready:
        _add_blocker(
            blockers,
            code="ea_core_candidate_runtime_not_green",
            owner="ea_core_release_owner",
            detail="The final EA Core candidate runtime verification is not green.",
        )
    if not authority_ready:
        _add_blocker(
            blockers,
            code="ea_core_release_authority_not_green",
            owner="ea_core_release_owner",
            detail="EA Core release authority is not bound to a clean authoritative runtime deployment.",
        )
    return {
        "candidate_runtime_ready": runtime_ready,
        "release_authority_ready": authority_ready,
        "source_commit": commit,
        "source_tree": tree,
        "image_id": image_id,
        "compose_project": project,
        "deployment_id": deployment_id,
        "runtime_receipt_sha256": evidence["ea_core_runtime"].sha256,
        "release_authority_receipt_sha256": evidence["ea_release_authority"].sha256,
        "release_authority_posture": authority.get("authority_posture"),
    }


def _validate_owner_evidence(
    evidence: Mapping[str, LoadedEvidence],
    *,
    blockers: list[dict[str, str]],
) -> dict[str, object]:
    operator = evidence["ea_operator_readiness"].payload
    localization = evidence["localization_projection"].payload
    lived = evidence["lived_system_observation"].payload
    flagship = evidence["chummer_flagship_readiness"].payload
    weekly = evidence["chummer_weekly_pulse"].payload
    journeys = evidence["chummer_journey_gates"].payload
    release_ready = evidence["chummer_release_ready"].payload

    _require(localization.get("contract_version") == 1, "localization_contract_version_invalid")
    _require(lived.get("contract_version") == "1.0.0", "lived_contract_version_invalid")
    _require(localization.get("blocker_mutation_allowed") is False, "localization_authority_boundary_invalid")
    _require(lived.get("authoritative") is False, "lived_authority_boundary_invalid")
    _require(lived.get("release_decision") is None, "lived_release_decision_invalid")

    operator_ready = all(
        (
            operator.get("status") == "ready",
            operator.get("ready") is True,
            operator.get("attention_required_count") == 0,
            operator.get("blocked_count") == 0,
            operator.get("probe_failed_count") == 0,
        )
    )
    if not operator_ready:
        _add_blocker(
            blockers,
            code="ea_operator_readiness_not_green",
            owner="ea_live_ops_owner",
            detail="EA operator readiness has a primary attention, blocked, or probe-failed component.",
        )

    localization_ready = localization.get("status") == "pass_consistent" and localization.get("petition_required") is False
    if not localization_ready:
        _add_blocker(
            blockers,
            code="chummer_localization_projection_blocked",
            owner="chummer6_design_and_ui_localization_owners",
            detail="Canonical localization declarations and structural UI proof are not consistent.",
        )
    lived_ready = lived.get("status") == "consistent"
    if not lived_ready:
        _add_blocker(
            blockers,
            code="chummer_lived_system_observation_requires_attention",
            owner="chummer6_design_and_release_owners",
            detail="The non-authoritative lived-system observation still reports owner-evidence contradictions or stale proof.",
        )

    flagship_ready = _is_pass(flagship.get("status")) and _is_pass(flagship.get("scoped_status"))
    if not flagship_ready:
        _add_blocker(
            blockers,
            code="chummer_flagship_readiness_not_green",
            owner="fleet_and_chummer_release_owners",
            detail="The canonical Fleet flagship readiness receipt is not green.",
        )
    weekly_readiness = _mapping(weekly.get("flagship_readiness"))
    weekly_health = _mapping(weekly.get("release_health"))
    decisions = [_mapping(item) for item in _items(weekly.get("governor_decisions"))]
    weekly_ready = (
        _is_pass(weekly_readiness.get("proof_status"))
        and _is_pass(weekly_health.get("state"))
        and not any(item.get("action") == "freeze_launch" for item in decisions)
    )
    if not weekly_ready:
        _add_blocker(
            blockers,
            code="chummer_weekly_launch_freeze",
            owner="chummer6_design_governance",
            detail="The canonical weekly pulse keeps launch expansion frozen.",
        )
    journey_summary = _mapping(journeys.get("summary"))
    journey_ready = all(
        (
            journey_summary.get("overall_state") == "ready",
            isinstance(journey_summary.get("total_journey_count"), int),
            journey_summary.get("ready_count") == journey_summary.get("total_journey_count"),
            journey_summary.get("warning_count") == 0,
            journey_summary.get("blocked_count") == 0,
        )
    )
    if not journey_ready:
        _add_blocker(
            blockers,
            code="chummer_journey_gates_not_ready",
            owner="fleet_journey_owner",
            detail="One or more canonical journey gates are not ready.",
        )
    release_ready_green = _is_pass(release_ready.get("status")) and release_ready.get("verdict") == "RELEASE_READY"
    if not release_ready_green:
        _add_blocker(
            blockers,
            code="chummer_release_ready_not_green",
            owner="chummer_run_services_release_owner",
            detail="The canonical RELEASE_READY verdict is not green.",
        )

    return {
        "ea_operator_readiness": {
            "ready": operator_ready,
            "status": operator.get("status"),
            "receipt_sha256": evidence["ea_operator_readiness"].sha256,
        },
        "localization_projection": {
            "ready": localization_ready,
            "status": localization.get("status"),
            "petition_required": localization.get("petition_required"),
            "receipt_sha256": evidence["localization_projection"].sha256,
        },
        "lived_system_observation": {
            "ready": lived_ready,
            "status": lived.get("status"),
            "authoritative": False,
            "receipt_sha256": evidence["lived_system_observation"].sha256,
        },
        "canonical_chummer": {
            "flagship_readiness_status": flagship.get("status"),
            "flagship_readiness_scoped_status": flagship.get("scoped_status"),
            "weekly_release_health_state": weekly_health.get("state"),
            "weekly_flagship_proof_status": weekly_readiness.get("proof_status"),
            "weekly_launch_frozen": any(item.get("action") == "freeze_launch" for item in decisions),
            "journey_gates_ready": journey_ready,
            "journey_ready_count": journey_summary.get("ready_count"),
            "journey_total_count": journey_summary.get("total_journey_count"),
            "release_ready_status": release_ready.get("status"),
            "release_ready_verdict": release_ready.get("verdict"),
            "receipt_sha256s": {
                "flagship_readiness": evidence["chummer_flagship_readiness"].sha256,
                "weekly_pulse": evidence["chummer_weekly_pulse"].sha256,
                "journey_gates": evidence["chummer_journey_gates"].sha256,
                "release_ready": evidence["chummer_release_ready"].sha256,
            },
        },
    }


def build_receipt(
    *,
    paths: Mapping[str, Path],
    generated_at: str,
    ea_commit: str,
    ea_tree: str,
    ea_image_id: str,
    ea_compose_project: str,
    ea_deployment_id: str,
    ea_repository: Path = ROOT,
) -> dict[str, object]:
    generated_at_normalized, generated_at_value = _parse_utc(generated_at)
    _require(bool(GIT_OBJECT_RE.fullmatch(ea_commit)), "ea_commit_invalid")
    _require(bool(GIT_OBJECT_RE.fullmatch(ea_tree)), "ea_tree_invalid")
    _require(bool(IMAGE_ID_RE.fullmatch(ea_image_id)), "ea_image_id_invalid")
    _require(bool(PROJECT_RE.fullmatch(ea_compose_project)), "ea_compose_project_invalid")
    _require(bool(DEPLOYMENT_ID_RE.fullmatch(ea_deployment_id)), "ea_deployment_id_invalid")
    _git_tree(repository=ea_repository, commit=ea_commit, expected_tree=ea_tree)

    expected_keys = tuple(spec.key for spec in EVIDENCE_SPECS)
    _require(tuple(paths.keys()) == expected_keys, "evidence_path_keys_invalid")
    loaded = {
        spec.key: _read_regular_json(Path(paths[spec.key]), spec)
        for spec in EVIDENCE_SPECS
    }
    blockers: list[dict[str, str]] = []
    manfred = _validate_manfred(loaded, generated_at=generated_at_value, blockers=blockers)
    property_3d = _validate_property(loaded, blockers=blockers)
    ea_core = _validate_ea_core(
        loaded,
        commit=ea_commit,
        tree=ea_tree,
        image_id=ea_image_id,
        project=ea_compose_project,
        deployment_id=ea_deployment_id,
        blockers=blockers,
    )
    owner_projection = _validate_owner_evidence(loaded, blockers=blockers)
    candidate_planes_ready = all(
        (
            manfred["candidate_launch_ready"] is True,
            property_3d["polished_reconstruction_ready"] is True,
            ea_core["candidate_runtime_ready"] is True,
            ea_core["release_authority_ready"] is True,
            _mapping(owner_projection.get("ea_operator_readiness")).get("ready") is True,
        )
    )
    safe_to_promote = not blockers
    launch_state = (
        "promotion_ready"
        if safe_to_promote
        else "candidate_launch_ready_promotion_guarded"
        if candidate_planes_ready
        else "candidate_not_ready"
    )
    payload: dict[str, object] = {
        "schema": CONTRACT_NAME,
        "status": "ready" if safe_to_promote else "blocked",
        "generated_at": generated_at_normalized,
        "launch_state": launch_state,
        "safe_to_promote_now": safe_to_promote,
        "long_running_goal": {
            "active": not safe_to_promote,
            "objective": (
                "Deliver EA and Manfred Memorial as flagship-grade production-launch-ready products across all supported surfaces, "
                "including a super-polished 3D tour lane whose floorplan reconstruction and verified provider-capture claims remain explicit, "
                "and promote only after every owner-controlled, soak, authority, deployment, and provider-tour gate is green."
            ),
            "production_promotion_complete": safe_to_promote,
        },
        "evidence_validation": {
            "status": "pass",
            "input_count": len(loaded),
            "regular_files_only": True,
            "json_object_roots_only": True,
            "schema_identities_exact": True,
            "sha256_and_mode_bound": True,
            "cross_receipt_identity_bindings_exact": True,
            "ea_git_commit_tree_binding_exact": True,
        },
        "input_bindings": [loaded[spec.key].binding() for spec in EVIDENCE_SPECS],
        "ea_core": ea_core,
        "manfred_memorial": manfred,
        "property_3d_tour_generation": property_3d,
        **owner_projection,
        "launch_gate": {
            "safe_to_promote_now": safe_to_promote,
            "blocker_count": len(blockers),
            "blockers": blockers,
            "owner_count": len({item["owner"] for item in blockers}),
            "next_action": (
                "Promote only after every listed owner publishes green, hash-bound replacement evidence and the guarded activation checks are rerun."
                if blockers
                else "Execute the separately authorized governed promotion and post-promotion verification workflow."
            ),
        },
        "execution_policy": {
            "filesystem_inputs": "read_only",
            "git_actions": "read_only_tree_binding",
            "docker_actions": 0,
            "network_actions": 0,
            "provider_actions": 0,
            "production_mutations": 0,
            "output_write": "single_atomic_mode_0600_receipt",
        },
        "privacy": {
            "input_payloads_embedded": False,
            "absolute_input_paths_emitted": False,
            "secret_values_emitted": False,
            "credentials_emitted": False,
        },
        "secrets_included": False,
    }
    _assert_secret_free(payload, loaded)
    return payload


def write_receipt(path: Path, payload: Mapping[str, object]) -> None:
    destination = path.expanduser().absolute()
    if destination.name != OUTPUT_NAME:
        raise EvidenceValidationError("output_name_must_be_v2")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_stat = destination.lstat()
    except FileNotFoundError:
        existing_stat = None
    if existing_stat is not None:
        if not stat.S_ISREG(existing_stat.st_mode):
            raise EvidenceValidationError("output_existing_not_regular")
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise EvidenceValidationError("output_existing_invalid") from None
        if not isinstance(existing, dict) or existing.get("schema") != CONTRACT_NAME:
            raise EvidenceValidationError("output_refuses_non_v2_overwrite")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _paths_from_args(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "manfred_runtime": args.manfred_runtime,
        "manfred_release": args.manfred_release,
        "manfred_transport": args.manfred_transport,
        "manfred_live_boundary": args.manfred_live_boundary,
        "property_3d_interaction": args.property_3d_interaction,
        "property_3d_release": args.property_3d_release,
        "ea_operator_readiness": args.ea_operator_readiness,
        "localization_projection": args.localization_projection,
        "lived_system_observation": args.lived_system_observation,
        "chummer_flagship_readiness": args.chummer_flagship_readiness,
        "chummer_weekly_pulse": args.chummer_weekly_pulse,
        "chummer_journey_gates": args.chummer_journey_gates,
        "chummer_release_ready": args.chummer_release_ready,
        "ea_core_runtime": args.ea_core_runtime,
        "ea_release_authority": args.ea_release_authority,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "manfred-runtime",
        "manfred-release",
        "manfred-transport",
        "manfred-live-boundary",
        "property-3d-interaction",
        "property-3d-release",
        "ea-operator-readiness",
        "localization-projection",
        "lived-system-observation",
        "chummer-flagship-readiness",
        "chummer-weekly-pulse",
        "chummer-journey-gates",
        "chummer-release-ready",
        "ea-core-runtime",
        "ea-release-authority",
    ):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--ea-commit", required=True)
    parser.add_argument("--ea-tree", required=True)
    parser.add_argument("--ea-image-id", required=True)
    parser.add_argument("--ea-compose-project", required=True)
    parser.add_argument("--ea-deployment-id", required=True)
    parser.add_argument("--ea-repository", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_receipt(
            paths=_paths_from_args(args),
            generated_at=args.generated_at,
            ea_commit=args.ea_commit,
            ea_tree=args.ea_tree,
            ea_image_id=args.ea_image_id,
            ea_compose_project=args.ea_compose_project,
            ea_deployment_id=args.ea_deployment_id,
            ea_repository=args.ea_repository,
        )
        write_receipt(args.output, receipt)
    except EvidenceValidationError as exc:
        print(
            json.dumps(
                {"schema": CONTRACT_NAME, "status": "invalid_inputs", "error_codes": list(exc.codes)},
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=os.sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "schema": CONTRACT_NAME,
                "status": receipt["status"],
                "safe_to_promote_now": receipt["safe_to_promote_now"],
                "blocker_count": _mapping(receipt.get("launch_gate")).get("blocker_count"),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if receipt["safe_to_promote_now"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
