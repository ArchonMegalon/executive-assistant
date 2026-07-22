from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator, model_validator

from app.services.governed_spatial_contract import (
    bounded_domain_errors,
    bounded_jcs,
    parse_raw_json,
)
from app.services.governed_spatial_execution import (
    GovernedSpatialAssetBindingV1,
    GovernedSpatialExecutionMaterialV1,
    GovernedSpatialRenderSpecV1,
    GovernedSpatialStyleSnapshotV1,
    SpatialExecutionMaterialStore,
    SpatialMaterialStoreError,
    material_digest as execution_material_digest,
    parse_execution_material,
    validate_execution_ref,
)
from app.services.governed_spatial_crypto import (
    Ed25519KeyRegistry as CanonicalEd25519KeyRegistry,
    SpatialCryptoError,
    verify_signed_envelope,
)
from app.services.governed_spatial_state import (
    DurableSpatialLedger,
    SpatialCompositionLifecycleGuard,
    SpatialLifecycleAuthority,
    SpatialPrivacyError,
    SpatialStateError,
    payload_digest,
    utc_iso,
)


PROPERTY_PREBUILD_SELECTION_CONTRACT = "propertyquarry.governed_spatial_prebuild_selection.v1"
PROPERTY_PREBUILD_PLAN_CONTRACT = "propertyquarry.governed_spatial_prebuild_plan.v1"
PROPERTY_OUTPUT_ALLOCATION_CONTRACT = "propertyquarry.governed_spatial_output_allocation_plan.v1"
PROPERTY_EXECUTION_BOUNDARY_CONTRACT = "propertyquarry.governed_spatial_execution_boundary.v1"
PROPERTY_EXECUTION_EVIDENCE_CONTRACT = "propertyquarry.governed_spatial_execution_evidence.v1"
PROPERTY_ARTIFACT_CANDIDATE_CONTRACT = "propertyquarry.governed_spatial_artifact_candidate.v1"
PROPERTY_ARTIFACT_VERIFICATION_CONTRACT = (
    "propertyquarry.governed_spatial_artifact_verification_evidence.v1"
)
PROPERTY_RECONCILIATION_CONTRACT = "propertyquarry.governed_spatial_prebuild_reconciliation.v1"

PROPERTY_ARTIFACT_FAMILY = "propertyquarry_continuous_walkthrough"
PROPERTY_CONTENT_PROFILE = "spatial_orientation_no_encounter_fields"
PROPERTY_POLICY_PATH = (
    "/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_MEDIA_RETENTION_POLICY_V1.json"
)
PROPERTY_POLICY_ID = "propertyquarry-spatial-media-retention-v1"
PROPERTY_POLICY_DIGEST = (
    "sha256:d3b22a668f42b6073a3b5199fb6adf629f8f59bd408ebe1dff08e0028bdeac95"
)
PROPERTY_AUTHORITY_ACCEPTANCE_DIGEST = (
    "sha256:c60f63ea2791c7b9f614b72a14f0a9699572daf7030243301879830d133f0631"
)
PROPERTY_AUTHORITY_ACCEPTANCE_MODE = 0o600
PROPERTY_EXECUTION_AUTHORITY_CONTRACT = (
    "propertyquarry.governed_spatial_execution_evidence_authority.v1"
)
PROPERTY_ARTIFACT_AUTHORITY_CONTRACT = (
    "propertyquarry.governed_spatial_artifact_verification_authority.v1"
)

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_URI_RE = re.compile(r"^(?:https?|file|ftp|s3|gs|ssh|data|javascript):", re.IGNORECASE)
_MAX_CANONICAL_BYTES = 2 * 1024 * 1024
_MAX_JOURNAL_BYTES = 32 * 1024 * 1024
_MAX_JOURNAL_RECORD_BYTES = 64 * 1024
_JOURNAL_NAME = "property-prebuild-reconciliation.v1.jsonl"
_LOCK_NAME = ".property-prebuild-reconciliation.lock"
_GATE_MARKER = object()
_MAX_CALLBACK_ITEMS = 50_000

_EXECUTION_AUTHORITY_MEMBERS = frozenset(
    {
        "contract_name",
        "contract_version",
        "issuer",
        "environment",
        "issued_at",
        "expires_at",
        "authority_identity_digest",
        "authority_receipt_digest",
        "ledger_scope_digest",
        "composition_digest",
        "plan_digest",
        "allocation_digest",
        "execution_boundary_digest",
        "execution_identity_digest",
        "adapter_identity_digest",
        "execution_evidence_digest",
        "output_digest",
        "operation_id",
        "observed_at",
        "signature",
    }
)

_ARTIFACT_AUTHORITY_MEMBERS = frozenset(
    {
        "contract_name",
        "contract_version",
        "issuer",
        "environment",
        "issued_at",
        "expires_at",
        "authority_identity_digest",
        "authority_receipt_digest",
        "ledger_scope_digest",
        "composition_digest",
        "plan_digest",
        "allocation_digest",
        "execution_boundary_digest",
        "execution_identity_digest",
        "execution_evidence_digest",
        "execution_authority_receipt_digest",
        "execution_output_digest",
        "candidate_digest",
        "allocation_slot_ref",
        "artifact_identity_digest",
        "artifact_digest",
        "verification_profile_digest",
        "verification_evidence_digest",
        "decision",
        "observed_at",
        "signature",
    }
)

_RECEIPT_MEMBERS = frozenset(
    {
        "contract_name",
        "contract_version",
        "issuer",
        "environment",
        "issued_at",
        "expires_at",
        "authorization_owner",
        "artifact_family",
        "content_profile",
        "request_id",
        "idempotency_key",
        "composition_digest",
        "material_identity",
        "material_digest",
        "request_digest",
        "source_packet_digest",
        "style_snapshot_digest",
        "asset_bindings_digest",
        "output_contract_digest",
        "execution_target_digest",
        "source_packet_created_at",
        "compose_acceptance_at",
        "retention_anchor",
        "retention_expires_at",
        "retention_deadlines_digest",
        "policy_id",
        "policy_digest",
        "policy_evidence_digest",
        "policy_approval_ref",
        "policy_verifier_ref",
        "policy_verification_receipt_digest",
        "policy_approved_at",
        "policy_evidence_expires_at",
        "input_authority_digest",
        "input_authority_verified_at",
        "input_authority_expires_at",
        "source_authority_receipt_digest",
        "style_registry_receipt_digest",
        "asset_authority_receipt_digest",
        "signature",
    }
)

_POLICY_PROJECTION_MEMBERS = frozenset(
    {
        "state",
        "policy_path",
        "policy_id",
        "policy_digest",
        "policy_mode",
        "policy_expires_at",
        "source_retention_days",
        "approval_ref",
        "verifier_ref",
        "verification_receipt_digest",
        "evidence_digest",
        "independent_acceptance_digest",
        "independent_acceptance_mode",
        "regular_file",
        "independent_acceptance_regular_file",
    }
)

_INPUT_AUTHORITY_MEMBERS = frozenset(
    {
        "contract_name",
        "contract_version",
        "state",
        "request_digest",
        "source_packet_digest",
        "source_packet_created_at",
        "source_authority_receipt_digest",
        "style_snapshot_digest",
        "style_registry_receipt_digest",
        "asset_bindings_digest",
        "asset_authority_receipt_digest",
        "verified_at",
        "expires_at",
        "input_authority_digest",
    }
)

_FORBIDDEN_KEYS = frozenset(
    {
        "absolute_path",
        "account_id",
        "api_key",
        "availability",
        "credential",
        "password",
        "provider_id",
        "provider_name",
        "provider_task_id",
        "provider_url",
        "readiness",
        "secret",
        "signed_url",
    }
)


class PropertyPrebuildError(ValueError):
    """Static, provider-redacted PropertyQuarry pre-build failure."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


def _required_digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError("sha256_digest_required")
    return value


def _required_ref(value: str) -> str:
    try:
        return validate_execution_ref(value)
    except (ValueError, SpatialStateError):
        raise ValueError("opaque_ref_required") from None


def _canonical_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 40:
        raise ValueError("canonical_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("canonical_timestamp_required") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("canonical_timestamp_required")
    canonical = utc_iso(parsed)
    if canonical != value:
        raise ValueError("canonical_timestamp_required")
    return value


def _as_datetime(value: object, reason: str = "prebuild_timestamp_invalid") -> datetime:
    if not isinstance(value, str):
        raise PropertyPrebuildError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PropertyPrebuildError(reason) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None or utc_iso(parsed) != value:
        raise PropertyPrebuildError(reason)
    return parsed.astimezone(UTC).replace(microsecond=0)


def _observed(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PropertyPrebuildError("property_prebuild_observed_at_invalid")
    return value.astimezone(UTC).replace(microsecond=0)


def _snapshot_mapping(
    value: object,
    *,
    reason: str,
    allow_datetime: bool = False,
) -> dict[str, object]:
    count = 0

    def snapshot(item: object, depth: int) -> object:
        nonlocal count
        count += 1
        if count > _MAX_CALLBACK_ITEMS or depth > 64:
            raise ValueError("bounded_mapping_required")
        if isinstance(item, Mapping):
            copied: dict[str, object] = {}
            for key, nested in item.items():
                if not isinstance(key, str) or key in copied:
                    raise ValueError("string_mapping_key_required")
                copied[key] = snapshot(nested, depth + 1)
            return copied
        if isinstance(item, (list, tuple)):
            return [snapshot(nested, depth + 1) for nested in item]
        if item is None or type(item) in {str, int, float, bool}:
            return item
        if allow_datetime and isinstance(item, datetime):
            return _observed(item)
        raise ValueError("mapping_value_type_invalid")

    try:
        if not isinstance(value, Mapping):
            raise ValueError("mapping_required")
        result = snapshot(value, 0)
    except Exception:
        raise PropertyPrebuildError(reason) from None
    if not isinstance(result, dict):
        raise PropertyPrebuildError(reason)
    return result


def _canonical_signed_receipt_bytes(value: object, *, reason: str) -> bytes:
    try:
        if isinstance(value, (bytes, bytearray, memoryview, str)):
            raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
            parsed = parse_raw_json(raw)
            canonical = _canonical_bytes(parsed)
            if raw != canonical:
                raise ValueError("noncanonical")
            return canonical
        snapshot = _snapshot_mapping(value, reason=reason)
        return _canonical_bytes(snapshot)
    except PropertyPrebuildError:
        raise
    except Exception:
        raise PropertyPrebuildError(reason) from None


def _canonical_bytes(value: object) -> bytes:
    errors = bounded_domain_errors(value)
    if errors:
        raise PropertyPrebuildError("property_prebuild_canonical_value_invalid")
    encoded = bounded_jcs(value)
    if len(encoded) > _MAX_CANONICAL_BYTES:
        raise PropertyPrebuildError("property_prebuild_canonical_value_too_large")
    return encoded


def _domain_digest(domain: str, value: object | bytes) -> str:
    encoded = value if isinstance(value, bytes) else _canonical_bytes(value)
    return "sha256:" + hashlib.sha256(domain.encode("ascii") + b"\x00" + encoded).hexdigest()


def _contains_forbidden_material(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_KEYS:
                return True
            if _contains_forbidden_material(nested):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_material(item) for item in value)
    if isinstance(value, str):
        normalized = value.strip()
        return (
            normalized.startswith(("/", "\\"))
            or "://" in normalized
            or bool(_URI_RE.match(normalized))
            or "../" in normalized
            or "..\\" in normalized
        )
    return False


def _load_contract(
    value: Mapping[str, object] | bytes | bytearray | memoryview | str,
    model: type[_StrictModel],
    *,
    reason: str,
) -> bytes:
    raw: bytes | None = None
    if isinstance(value, str):
        raw = value.encode("utf-8")
        try:
            payload = parse_raw_json(value)
        except Exception:
            raise PropertyPrebuildError(f"{reason}_json_invalid") from None
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        try:
            payload = parse_raw_json(raw)
        except Exception:
            raise PropertyPrebuildError(f"{reason}_json_invalid") from None
    elif isinstance(value, Mapping):
        payload = _snapshot_mapping(value, reason=f"{reason}_invalid")
    else:
        raise PropertyPrebuildError(f"{reason}_object_required")
    try:
        parsed = model.model_validate(payload)
        normalized = parsed.model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise PropertyPrebuildError(f"{reason}_invalid") from None
    if _contains_forbidden_material(normalized):
        raise PropertyPrebuildError(f"{reason}_sensitive_material_forbidden")
    canonical = _canonical_bytes(normalized)
    if raw is not None and raw != canonical:
        raise PropertyPrebuildError(f"{reason}_noncanonical")
    return canonical


class _SelectionModel(_StrictModel):
    contract_name: Literal["propertyquarry.governed_spatial_prebuild_selection.v1"]
    contract_version: Literal["1.0.0"]
    request_id: str
    idempotency_key: str
    composition_digest: str
    composition_receipt_digest: str
    material_identity: str
    material_digest: str

    _digests = field_validator(
        "composition_digest", "composition_receipt_digest", "material_digest"
    )(_required_digest)
    _refs = field_validator("idempotency_key", "material_identity")(_required_ref)

    @field_validator("request_id")
    @classmethod
    def request_id_is_canonical(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (TypeError, ValueError):
            raise ValueError("request_id_invalid") from None
        if str(parsed) != value:
            raise ValueError("request_id_noncanonical")
        return value


class _PlanModel(_StrictModel):
    contract_name: Literal["propertyquarry.governed_spatial_prebuild_plan.v1"]
    contract_version: Literal["1.0.0"]
    request_id: str
    idempotency_key: str
    composition_digest: str
    composition_receipt_digest: str
    material_identity: str
    material_digest: str
    request_digest: str
    source_packet_digest: str
    style_snapshot_digest: str
    asset_bindings_digest: str
    output_contract_digest: str
    execution_target_digest: str
    source_packet_created_at: str
    compose_acceptance_at: str
    retention_anchor: str
    retention_expires_at: str
    retention_deadlines_digest: str
    policy_id: Literal["propertyquarry-spatial-media-retention-v1"]
    policy_digest: str
    policy_evidence_digest: str
    policy_verification_receipt_digest: str
    input_authority_digest: str
    source_authority_receipt_digest: str
    style_registry_receipt_digest: str
    asset_authority_receipt_digest: str
    artifact_family: Literal["propertyquarry_continuous_walkthrough"]
    content_profile: Literal["spatial_orientation_no_encounter_fields"]
    render_spec: GovernedSpatialRenderSpecV1
    style_snapshot: GovernedSpatialStyleSnapshotV1
    ordered_asset_bindings: list[GovernedSpatialAssetBindingV1] = Field(min_length=1, max_length=10000)

    _digests = field_validator(
        "composition_digest",
        "composition_receipt_digest",
        "material_digest",
        "request_digest",
        "source_packet_digest",
        "style_snapshot_digest",
        "asset_bindings_digest",
        "output_contract_digest",
        "execution_target_digest",
        "retention_deadlines_digest",
        "policy_digest",
        "policy_evidence_digest",
        "policy_verification_receipt_digest",
        "input_authority_digest",
        "source_authority_receipt_digest",
        "style_registry_receipt_digest",
        "asset_authority_receipt_digest",
    )(_required_digest)
    _refs = field_validator("idempotency_key", "material_identity")(_required_ref)
    _timestamps = field_validator(
        "source_packet_created_at",
        "compose_acceptance_at",
        "retention_anchor",
        "retention_expires_at",
    )(_canonical_timestamp)

    @field_validator("request_id")
    @classmethod
    def request_id_is_canonical(cls, value: str) -> str:
        return _SelectionModel.request_id_is_canonical(value)

    @model_validator(mode="after")
    def chronology_and_profile_are_exact(self) -> _PlanModel:
        source = _as_datetime(self.source_packet_created_at)
        compose = _as_datetime(self.compose_acceptance_at)
        anchor = _as_datetime(self.retention_anchor)
        expiry = _as_datetime(self.retention_expires_at)
        if anchor != min(source, compose) or not anchor < expiry:
            raise ValueError("prebuild_retention_binding_invalid")
        if self.render_spec.product != "propertyquarry":
            raise ValueError("prebuild_product_invalid")
        if (
            self.render_spec.artifact.kind != "continuous_walkthrough"
            or self.render_spec.artifact.purpose != "walkthrough"
            or self.render_spec.scene_overlays
        ):
            raise ValueError("prebuild_artifact_profile_invalid")
        if "propertyquarry" not in self.style_snapshot.consumer_products:
            raise ValueError("prebuild_style_product_invalid")
        refs = [binding.asset_ref for binding in self.ordered_asset_bindings]
        if len(refs) != len(set(refs)):
            raise ValueError("prebuild_ordered_assets_duplicate")
        return self


class _AllocationSlotModel(_StrictModel):
    slot_ref: str
    role: Literal["walkthrough_video", "poster_frame", "contact_sheet", "interactive_package"]
    media_type: Literal["video/mp4", "image/png", "application/zip"]

    _slot = field_validator("slot_ref")(_required_ref)

    @model_validator(mode="after")
    def media_matches_role(self) -> _AllocationSlotModel:
        expected = {
            "walkthrough_video": "video/mp4",
            "poster_frame": "image/png",
            "contact_sheet": "image/png",
            "interactive_package": "application/zip",
        }
        if self.media_type != expected[self.role]:
            raise ValueError("allocation_slot_media_type_invalid")
        return self


class _AllocationModel(_StrictModel):
    contract_name: Literal["propertyquarry.governed_spatial_output_allocation_plan.v1"]
    contract_version: Literal["1.0.0"]
    allocation_ref: str
    plan_digest: str
    composition_digest: str
    material_digest: str
    output_contract_digest: str
    slots: list[_AllocationSlotModel] = Field(min_length=3, max_length=4)
    filesystem_actions: Literal[0]
    quota_actions: Literal[0]
    adapter_actions: Literal[0]
    provider_actions: Literal[0]

    _refs = field_validator("allocation_ref")(_required_ref)
    _digests = field_validator(
        "plan_digest", "composition_digest", "material_digest", "output_contract_digest"
    )(_required_digest)

    @model_validator(mode="after")
    def slots_are_unique(self) -> _AllocationModel:
        refs = [slot.slot_ref for slot in self.slots]
        roles = [slot.role for slot in self.slots]
        if len(refs) != len(set(refs)) or len(roles) != len(set(roles)):
            raise ValueError("allocation_slots_duplicate")
        return self


class _ExecutionBoundaryModel(_StrictModel):
    contract_name: Literal["propertyquarry.governed_spatial_execution_boundary.v1"]
    contract_version: Literal["1.0.0"]
    execution_identity_digest: str
    plan_digest: str
    allocation_digest: str
    allocation_ref: str
    composition_digest: str
    material_digest: str
    execution_target_digest: str
    artifact_family: Literal["propertyquarry_continuous_walkthrough"]
    content_profile: Literal["spatial_orientation_no_encounter_fields"]
    adapter_invoked: Literal[False]
    provider_actions: Literal[0]
    render_actions: Literal[0]

    _digests = field_validator(
        "execution_identity_digest",
        "plan_digest",
        "allocation_digest",
        "composition_digest",
        "material_digest",
        "execution_target_digest",
    )(_required_digest)
    _allocation = field_validator("allocation_ref")(_required_ref)


class _ExecutionEvidenceModel(_StrictModel):
    contract_name: Literal["propertyquarry.governed_spatial_execution_evidence.v1"]
    contract_version: Literal["1.0.0"]
    execution_identity_digest: str
    execution_boundary_digest: str
    plan_digest: str
    allocation_digest: str
    adapter_identity_digest: str
    operation_id: str
    state: Literal["succeeded", "failed_final", "unknown"]
    output_digest: str | None
    output_manifest_ref: str | None
    private_execution_receipt_digest: str | None
    provider_action_count: StrictInt = Field(ge=0, le=1)

    _digests = field_validator(
        "execution_identity_digest",
        "execution_boundary_digest",
        "plan_digest",
        "allocation_digest",
        "adapter_identity_digest",
    )(_required_digest)
    _optional_digests = field_validator("output_digest", "private_execution_receipt_digest")(
        lambda value: _required_digest(value) if value is not None else None
    )
    _refs = field_validator("operation_id")(_required_ref)
    _manifest = field_validator("output_manifest_ref")(
        lambda value: _required_ref(value) if value is not None else None
    )

    @model_validator(mode="after")
    def outcome_shape_is_exact(self) -> _ExecutionEvidenceModel:
        outputs = (self.output_digest, self.output_manifest_ref, self.private_execution_receipt_digest)
        if self.state == "succeeded":
            if any(value is None for value in outputs) or self.provider_action_count != 1:
                raise ValueError("execution_success_evidence_invalid")
        elif any(value is not None for value in outputs):
            raise ValueError("execution_non_success_outputs_forbidden")
        return self


class _ArtifactCandidateModel(_StrictModel):
    contract_name: Literal["propertyquarry.governed_spatial_artifact_candidate.v1"]
    contract_version: Literal["1.0.0"]
    plan_digest: str
    allocation_digest: str
    execution_identity_digest: str
    execution_evidence_digest: str
    allocation_slot_ref: str
    artifact_ref: str
    artifact_digest: str
    artifact_identity_digest: str
    verification_profile_digest: str

    _digests = field_validator(
        "plan_digest",
        "allocation_digest",
        "execution_identity_digest",
        "execution_evidence_digest",
        "artifact_digest",
        "artifact_identity_digest",
        "verification_profile_digest",
    )(_required_digest)
    _refs = field_validator("allocation_slot_ref", "artifact_ref")(_required_ref)


class _ArtifactVerificationModel(_StrictModel):
    contract_name: Literal[
        "propertyquarry.governed_spatial_artifact_verification_evidence.v1"
    ]
    contract_version: Literal["1.0.0"]
    plan_digest: str
    allocation_digest: str
    execution_identity_digest: str
    execution_evidence_digest: str
    artifact_identity_digest: str
    artifact_digest: str
    verifier_identity_digest: str
    verification_profile_digest: str
    outcome_evidence_digest: str
    state: Literal["verified", "rejected"]
    verified_at: str

    _digests = field_validator(
        "plan_digest",
        "allocation_digest",
        "execution_identity_digest",
        "execution_evidence_digest",
        "artifact_identity_digest",
        "artifact_digest",
        "verifier_identity_digest",
        "verification_profile_digest",
        "outcome_evidence_digest",
    )(_required_digest)
    _timestamp = field_validator("verified_at")(_canonical_timestamp)


ReconciliationState = Literal[
    "planned",
    "allocation_planned",
    "execution_pending",
    "execution_succeeded",
    "artifact_verified",
    "blocked_final",
    "failed_final",
]


class _ReconciliationModel(_StrictModel):
    contract_name: Literal["propertyquarry.governed_spatial_prebuild_reconciliation.v1"]
    contract_version: Literal["1.0.0"]
    reconciliation_key: str
    reconciliation_identity_digest: str
    sequence: StrictInt = Field(ge=1, le=9_007_199_254_740_991)
    prior_record_digest: str | None
    record_digest: str
    lock_identity_digest: str
    ledger_scope_digest: str
    composition_digest: str
    plan_digest: str
    allocation_digest: str
    execution_boundary_digest: str
    execution_identity_digest: str
    execution_authority_receipt_digest: str | None
    artifact_authority_receipt_digest: str | None
    artifact_identity_digest: str | None
    verification_digest: str | None
    state: ReconciliationState
    outcome_digest: str | None
    recorded_at: str
    retention_anchor: str
    retention_expires_at: str

    _ref = field_validator("reconciliation_key")(_required_ref)
    _digests = field_validator(
        "record_digest",
        "lock_identity_digest",
        "reconciliation_identity_digest",
        "ledger_scope_digest",
        "composition_digest",
        "plan_digest",
        "allocation_digest",
        "execution_boundary_digest",
        "execution_identity_digest",
    )(_required_digest)
    _optional_digests = field_validator(
        "prior_record_digest",
        "execution_authority_receipt_digest",
        "artifact_authority_receipt_digest",
        "artifact_identity_digest",
        "verification_digest",
        "outcome_digest",
    )(lambda value: _required_digest(value) if value is not None else None)
    _timestamps = field_validator("recorded_at", "retention_anchor", "retention_expires_at")(
        _canonical_timestamp
    )

    @model_validator(mode="after")
    def state_shape_is_exact(self) -> _ReconciliationModel:
        terminal_or_evidenced = {
            "execution_succeeded",
            "artifact_verified",
            "blocked_final",
            "failed_final",
        }
        if (self.state in terminal_or_evidenced) is not (self.outcome_digest is not None):
            raise ValueError("reconciliation_outcome_shape_invalid")
        if self.state == "artifact_verified":
            if (
                self.execution_authority_receipt_digest is None
                or self.artifact_authority_receipt_digest is None
                or self.artifact_identity_digest is None
                or self.verification_digest is None
            ):
                raise ValueError("reconciliation_artifact_evidence_required")
        elif self.state == "execution_succeeded":
            if (
                self.execution_authority_receipt_digest is None
                or self.artifact_authority_receipt_digest is not None
                or self.artifact_identity_digest is not None
                or self.verification_digest is not None
            ):
                raise ValueError("reconciliation_execution_authority_required")
        elif self.state == "failed_final":
            if (
                self.artifact_authority_receipt_digest is not None
                or self.artifact_identity_digest is not None
            ):
                raise ValueError("reconciliation_artifact_authority_forbidden")
            if self.verification_digest is not None:
                raise ValueError("reconciliation_verification_digest_forbidden")
        elif self.verification_digest is not None:
            raise ValueError("reconciliation_verification_digest_forbidden")
        elif (
            self.execution_authority_receipt_digest is not None
            or self.artifact_authority_receipt_digest is not None
            or self.artifact_identity_digest is not None
        ):
            raise ValueError("reconciliation_authority_digest_forbidden")
        if _as_datetime(self.retention_anchor) >= _as_datetime(self.retention_expires_at):
            raise ValueError("reconciliation_retention_invalid")
        if not (
            _as_datetime(self.retention_anchor)
            <= _as_datetime(self.recorded_at)
            < _as_datetime(self.retention_expires_at)
        ):
            raise ValueError("reconciliation_recorded_at_outside_retention")
        return self


@dataclass(frozen=True, slots=True, repr=False)
class _CanonicalContract:
    _canonical: bytes
    _digest: str

    _MODEL: ClassVar[type[_StrictModel]]
    _DOMAIN: ClassVar[str]
    _REASON: ClassVar[str]

    def __post_init__(self) -> None:
        canonical = _load_contract(self._canonical, self._MODEL, reason=self._REASON)
        expected = _domain_digest(self._DOMAIN, canonical)
        if canonical != self._canonical or expected != self._digest:
            raise PropertyPrebuildError(f"{self._REASON}_identity_invalid")

    @classmethod
    def parse(
        cls,
        value: Mapping[str, object] | bytes | bytearray | memoryview | str | _CanonicalContract,
    ) -> Any:
        if isinstance(value, cls):
            return cls(value._canonical, value._digest)
        canonical = _load_contract(value, cls._MODEL, reason=cls._REASON)
        return cls(canonical, _domain_digest(cls._DOMAIN, canonical))

    @property
    def digest(self) -> str:
        return self._digest

    def canonical_bytes(self) -> bytes:
        return bytes(self._canonical)

    def as_dict(self) -> dict[str, object]:
        payload = json.loads(self._canonical)
        if not isinstance(payload, dict):
            raise PropertyPrebuildError(f"{self._REASON}_invalid")
        return payload

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.as_dict().get(key, default)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(digest={self._digest!r})"


class PropertyPrebuildSelection(_CanonicalContract):
    _MODEL = _SelectionModel
    _DOMAIN = "propertyquarry.prebuild.selection.v1"
    _REASON = "property_prebuild_selection"


class PropertyPrebuildPlan(_CanonicalContract):
    _MODEL = _PlanModel
    _DOMAIN = "propertyquarry.prebuild.plan.v1"
    _REASON = "property_prebuild_plan"


class PropertyOutputAllocation(_CanonicalContract):
    _MODEL = _AllocationModel
    _DOMAIN = "propertyquarry.prebuild.output_allocation.v1"
    _REASON = "property_output_allocation"


class PropertyExecutionBoundary(_CanonicalContract):
    _MODEL = _ExecutionBoundaryModel
    _DOMAIN = "propertyquarry.prebuild.execution_boundary.v1"
    _REASON = "property_execution_boundary"


class PropertyExecutionEvidence(_CanonicalContract):
    _MODEL = _ExecutionEvidenceModel
    _DOMAIN = "propertyquarry.prebuild.execution_evidence.v1"
    _REASON = "property_execution_evidence"


class PropertyArtifactCandidate(_CanonicalContract):
    _MODEL = _ArtifactCandidateModel
    _DOMAIN = "propertyquarry.prebuild.artifact_candidate.v1"
    _REASON = "property_artifact_candidate"


class PropertyArtifactVerificationEvidence(_CanonicalContract):
    _MODEL = _ArtifactVerificationModel
    _DOMAIN = "propertyquarry.prebuild.artifact_verification.v1"
    _REASON = "property_artifact_verification"


class PropertyReconciliationRecord(_CanonicalContract):
    _MODEL = _ReconciliationModel
    _DOMAIN = "propertyquarry.prebuild.reconciliation_record.v1"
    _REASON = "property_reconciliation_record"

    @classmethod
    def parse(
        cls,
        value: Mapping[str, object] | bytes | bytearray | memoryview | str | _CanonicalContract,
    ) -> PropertyReconciliationRecord:
        record = super().parse(value)
        payload = record.as_dict()
        if payload.get("record_digest") != _record_digest(payload):
            raise PropertyPrebuildError("property_reconciliation_record_digest_invalid")
        return record

    @property
    def record_digest(self) -> str:
        value = self.as_dict().get("record_digest")
        if not isinstance(value, str):
            raise PropertyPrebuildError("property_reconciliation_record_invalid")
        return value


@dataclass(frozen=True, slots=True)
class PropertyEvidenceAuthority:
    authority_kind: Literal["execution", "artifact_verification"]
    issuer: str
    environment: str
    key_ref: str
    key_epoch: int
    identity_digest: str
    authority_receipt_digest: str
    maximum_age_seconds: int = 300

    def __post_init__(self) -> None:
        try:
            _required_ref(self.issuer)
            _required_ref(self.environment)
            _required_ref(self.key_ref)
            _required_digest(self.identity_digest)
            _required_digest(self.authority_receipt_digest)
        except (ValueError, PropertyPrebuildError):
            raise PropertyPrebuildError("property_evidence_authority_invalid") from None
        if (
            isinstance(self.key_epoch, bool)
            or not isinstance(self.key_epoch, int)
            or self.key_epoch < 0
            or isinstance(self.maximum_age_seconds, bool)
            or not isinstance(self.maximum_age_seconds, int)
            or not 1 <= self.maximum_age_seconds <= 300
        ):
            raise PropertyPrebuildError("property_evidence_authority_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class PropertyAuthenticatedExecutionEvidence:
    evidence: PropertyExecutionEvidence
    _authority_receipt: bytes

    def __post_init__(self) -> None:
        if (
            type(self.evidence) is not PropertyExecutionEvidence
            or type(self._authority_receipt) is not bytes
        ):
            raise PropertyPrebuildError(
                "property_execution_authority_receipt_invalid"
            )
        if self._authority_receipt != _canonical_signed_receipt_bytes(
            self._authority_receipt,
            reason="property_execution_authority_receipt_invalid",
        ):
            raise PropertyPrebuildError(
                "property_execution_authority_receipt_invalid"
            )

    @classmethod
    def bind(
        cls,
        evidence: PropertyExecutionEvidence | Mapping[str, object],
        authority_receipt: Mapping[str, object] | bytes | str,
    ) -> PropertyAuthenticatedExecutionEvidence:
        try:
            parsed = PropertyExecutionEvidence.parse(evidence)
            receipt = _canonical_signed_receipt_bytes(
                authority_receipt,
                reason="property_execution_authority_receipt_invalid",
            )
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError(
                "property_execution_authority_receipt_invalid"
            ) from None
        return cls(parsed, receipt)

    def authority_receipt(self) -> dict[str, object]:
        payload = json.loads(self._authority_receipt)
        if not isinstance(payload, dict):
            raise PropertyPrebuildError("property_execution_authority_receipt_invalid")
        return payload


@dataclass(frozen=True, slots=True, repr=False)
class PropertyAuthenticatedArtifactVerification:
    evidence: PropertyArtifactVerificationEvidence
    _authority_receipt: bytes

    def __post_init__(self) -> None:
        if (
            type(self.evidence) is not PropertyArtifactVerificationEvidence
            or type(self._authority_receipt) is not bytes
        ):
            raise PropertyPrebuildError(
                "property_artifact_authority_receipt_invalid"
            )
        if self._authority_receipt != _canonical_signed_receipt_bytes(
            self._authority_receipt,
            reason="property_artifact_authority_receipt_invalid",
        ):
            raise PropertyPrebuildError(
                "property_artifact_authority_receipt_invalid"
            )

    @classmethod
    def bind(
        cls,
        evidence: PropertyArtifactVerificationEvidence | Mapping[str, object],
        authority_receipt: Mapping[str, object] | bytes | str,
    ) -> PropertyAuthenticatedArtifactVerification:
        try:
            parsed = PropertyArtifactVerificationEvidence.parse(evidence)
            receipt = _canonical_signed_receipt_bytes(
                authority_receipt,
                reason="property_artifact_authority_receipt_invalid",
            )
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError(
                "property_artifact_authority_receipt_invalid"
            ) from None
        return cls(parsed, receipt)

    def authority_receipt(self) -> dict[str, object]:
        payload = json.loads(self._authority_receipt)
        if not isinstance(payload, dict):
            raise PropertyPrebuildError("property_artifact_authority_receipt_invalid")
        return payload


class PropertyOutputAllocationPlanner(Protocol):
    def __call__(self, plan: PropertyPrebuildPlan) -> PropertyOutputAllocation: ...


class PropertyExecutionAdapter(Protocol):
    """Future explicit adapter boundary; this milestone provides no implementation."""

    def execute(self, request: PropertyExecutionBoundary) -> PropertyExecutionEvidence: ...


class PropertyArtifactEvidenceVerifier(Protocol):
    def __call__(
        self, candidate: PropertyArtifactCandidate, *, observed_at: datetime
    ) -> PropertyAuthenticatedArtifactVerification: ...


class PropertyComposeReceiptVerifier(Protocol):
    def __call__(
        self, receipt: Mapping[str, object], *, observed_at: datetime
    ) -> Mapping[str, object]: ...


class PropertyCurrentPolicyVerifier(Protocol):
    def __call__(
        self, evidence: Mapping[str, object] | None, *, observed_at: datetime
    ) -> Mapping[str, object]: ...


class PropertyCurrentInputAuthorityVerifier(Protocol):
    def __call__(
        self, material: GovernedSpatialExecutionMaterialV1, *, observed_at: datetime
    ) -> Mapping[str, object]: ...


def _render_spec_from_material(
    material: GovernedSpatialExecutionMaterialV1,
) -> GovernedSpatialRenderSpecV1:
    request = material.normalized_request
    source = material.normalized_source_packet
    spatial_plan = request.get("spatial_plan")
    if not isinstance(spatial_plan, Mapping):
        raise PropertyPrebuildError("property_prebuild_material_invalid")
    source_rooms = source.get("rooms")
    if not isinstance(source_rooms, list):
        raise PropertyPrebuildError("property_prebuild_material_invalid")
    rooms: list[dict[str, object]] = []
    for source_room in source_rooms:
        if not isinstance(source_room, Mapping):
            raise PropertyPrebuildError("property_prebuild_material_invalid")
        room = dict(source_room)
        room["ceiling_height_m"] = str(room.get("ceiling_height_m"))
        rooms.append(room)
    payload = {
        "contract_name": "ea.governed_spatial_render_spec.v1",
        "contract_version": "1.0.0",
        "product": request.get("consumer", {}).get("product")
        if isinstance(request.get("consumer"), Mapping)
        else None,
        "artifact": request.get("artifact"),
        "normalized_floorplan_ref": source.get("normalized_floorplan_ref"),
        "room_graph_ref": source.get("room_graph_ref"),
        "walkable_mesh_ref": source.get("walkable_mesh_ref"),
        "portal_graph_ref": source.get("portal_graph_ref"),
        "scale_m_per_unit": str(source.get("scale_m_per_unit")),
        "orientation_degrees": str(source.get("orientation_degrees")),
        "rooms": rooms,
        "portals": source.get("portals"),
        "required_room_ids": spatial_plan.get("required_room_ids"),
        "route_room_ids": spatial_plan.get("route_room_ids"),
        "allow_revisit": spatial_plan.get("allow_revisit"),
        "camera": request.get("camera"),
        "output": request.get("output"),
        "content_policy": request.get("content_policy"),
        "scene_overlays": request.get("scene_overlays"),
    }
    try:
        return GovernedSpatialRenderSpecV1.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        raise PropertyPrebuildError("property_prebuild_material_invalid") from None


def validate_property_prebuild_material(
    material: GovernedSpatialExecutionMaterialV1 | Mapping[str, object],
) -> GovernedSpatialExecutionMaterialV1:
    try:
        parsed = parse_execution_material(
            material.model_dump(mode="json")
            if isinstance(material, GovernedSpatialExecutionMaterialV1)
            else material
        )
    except Exception:
        raise PropertyPrebuildError("property_prebuild_material_invalid") from None
    render_spec = _render_spec_from_material(parsed)
    if (
        render_spec.product != "propertyquarry"
        or render_spec.artifact.kind != "continuous_walkthrough"
        or render_spec.artifact.purpose != "walkthrough"
        or render_spec.scene_overlays
        or "propertyquarry" not in parsed.style_snapshot.consumer_products
    ):
        raise PropertyPrebuildError("property_prebuild_material_profile_invalid")
    if _contains_forbidden_material(render_spec.model_dump(mode="json")):
        raise PropertyPrebuildError("property_prebuild_material_sensitive_material_forbidden")
    return parsed


def _assert_receipt_material_binding(
    receipt: Mapping[str, object],
    material: GovernedSpatialExecutionMaterialV1,
    selection: PropertyPrebuildSelection | None = None,
) -> None:
    if set(receipt) != _RECEIPT_MEMBERS:
        raise PropertyPrebuildError("property_prebuild_receipt_invalid")
    expected = {
        "contract_name": "ea.governed_spatial_property_composition.v1",
        "contract_version": "1.0.0",
        "artifact_family": PROPERTY_ARTIFACT_FAMILY,
        "content_profile": PROPERTY_CONTENT_PROFILE,
        "composition_digest": material.composition_digest,
        "material_identity": SpatialExecutionMaterialStore.material_identity(
            material.composition_digest
        ),
        "material_digest": execution_material_digest(material),
        "request_digest": material.request_digest,
        "source_packet_digest": material.source_packet_digest,
        "style_snapshot_digest": material.style_snapshot_digest,
        "output_contract_digest": material.output_contract_digest,
        "execution_target_digest": material.execution_target_digest,
        "source_packet_created_at": material.source_packet_created_at,
        "compose_acceptance_at": material.compose_created_at,
        "retention_expires_at": material.retention_expires_at,
        "policy_id": PROPERTY_POLICY_ID,
        "policy_digest": PROPERTY_POLICY_DIGEST,
    }
    assets_digest = payload_digest(
        [binding.model_dump(mode="json") for binding in material.asset_bindings]
    )
    expected["asset_bindings_digest"] = assets_digest
    source = _as_datetime(material.source_packet_created_at)
    compose = _as_datetime(material.compose_created_at)
    expected["retention_anchor"] = utc_iso(min(source, compose))
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise PropertyPrebuildError("property_prebuild_receipt_material_mismatch")
    if selection is not None:
        selected = selection.as_dict()
        selection_expected = {
            "request_id": receipt.get("request_id"),
            "idempotency_key": receipt.get("idempotency_key"),
            "composition_digest": receipt.get("composition_digest"),
            "material_identity": receipt.get("material_identity"),
            "material_digest": receipt.get("material_digest"),
        }
        if any(selected.get(field) != value for field, value in selection_expected.items()):
            raise PropertyPrebuildError("property_prebuild_selection_binding_mismatch")


def validate_property_prebuild_receipt_material(
    receipt: Mapping[str, object],
    material: GovernedSpatialExecutionMaterialV1 | Mapping[str, object],
) -> None:
    parsed = validate_property_prebuild_material(material)
    _assert_receipt_material_binding(dict(receipt), parsed)


def build_property_prebuild_plan(
    selection: PropertyPrebuildSelection | Mapping[str, object],
    receipt: Mapping[str, object],
    material: GovernedSpatialExecutionMaterialV1 | Mapping[str, object],
) -> PropertyPrebuildPlan:
    selected = PropertyPrebuildSelection.parse(selection)
    parsed = validate_property_prebuild_material(material)
    trusted = dict(receipt)
    _assert_receipt_material_binding(trusted, parsed, selected)
    render_spec = _render_spec_from_material(parsed)
    payload = {
        "contract_name": PROPERTY_PREBUILD_PLAN_CONTRACT,
        "contract_version": "1.0.0",
        "request_id": trusted["request_id"],
        "idempotency_key": trusted["idempotency_key"],
        "composition_digest": trusted["composition_digest"],
        "composition_receipt_digest": selected["composition_receipt_digest"],
        "material_identity": trusted["material_identity"],
        "material_digest": trusted["material_digest"],
        "request_digest": trusted["request_digest"],
        "source_packet_digest": trusted["source_packet_digest"],
        "style_snapshot_digest": trusted["style_snapshot_digest"],
        "asset_bindings_digest": trusted["asset_bindings_digest"],
        "output_contract_digest": trusted["output_contract_digest"],
        "execution_target_digest": trusted["execution_target_digest"],
        "source_packet_created_at": trusted["source_packet_created_at"],
        "compose_acceptance_at": trusted["compose_acceptance_at"],
        "retention_anchor": trusted["retention_anchor"],
        "retention_expires_at": trusted["retention_expires_at"],
        "retention_deadlines_digest": trusted["retention_deadlines_digest"],
        "policy_id": trusted["policy_id"],
        "policy_digest": trusted["policy_digest"],
        "policy_evidence_digest": trusted["policy_evidence_digest"],
        "policy_verification_receipt_digest": trusted[
            "policy_verification_receipt_digest"
        ],
        "input_authority_digest": trusted["input_authority_digest"],
        "source_authority_receipt_digest": trusted[
            "source_authority_receipt_digest"
        ],
        "style_registry_receipt_digest": trusted[
            "style_registry_receipt_digest"
        ],
        "asset_authority_receipt_digest": trusted[
            "asset_authority_receipt_digest"
        ],
        "artifact_family": PROPERTY_ARTIFACT_FAMILY,
        "content_profile": PROPERTY_CONTENT_PROFILE,
        "render_spec": render_spec.model_dump(mode="json"),
        "style_snapshot": parsed.style_snapshot.model_dump(mode="json"),
        "ordered_asset_bindings": [
            binding.model_dump(mode="json") for binding in parsed.asset_bindings
        ],
    }
    return PropertyPrebuildPlan.parse(payload)


def _allocation_payload(plan: PropertyPrebuildPlan) -> dict[str, object]:
    plan_payload = plan.as_dict()
    render_spec = plan_payload.get("render_spec")
    if not isinstance(render_spec, Mapping) or not isinstance(render_spec.get("output"), Mapping):
        raise PropertyPrebuildError("property_prebuild_plan_invalid")
    output = render_spec["output"]
    roles: list[tuple[str, str]] = [
        ("walkthrough_video", "video/mp4"),
        ("poster_frame", "image/png"),
        ("contact_sheet", "image/png"),
    ]
    if output.get("interactive_package") is True:
        roles.append(("interactive_package", "application/zip"))
    allocation_seed = {
        "plan_digest": plan.digest,
        "output_contract_digest": plan_payload["output_contract_digest"],
        "roles": [role for role, _ in roles],
    }
    allocation_identity = _domain_digest(
        "propertyquarry.prebuild.output_allocation_identity.v1", allocation_seed
    )
    slots = []
    for role, media_type in roles:
        slot_digest = _domain_digest(
            "propertyquarry.prebuild.output_slot.v1",
            {"allocation_identity": allocation_identity, "role": role},
        )
        slots.append(
            {
                "slot_ref": f"allocation-slot:{slot_digest[7:]}",
                "role": role,
                "media_type": media_type,
            }
        )
    return {
        "contract_name": PROPERTY_OUTPUT_ALLOCATION_CONTRACT,
        "contract_version": "1.0.0",
        "allocation_ref": f"output-allocation:{allocation_identity[7:]}",
        "plan_digest": plan.digest,
        "composition_digest": plan_payload["composition_digest"],
        "material_digest": plan_payload["material_digest"],
        "output_contract_digest": plan_payload["output_contract_digest"],
        "slots": slots,
        "filesystem_actions": 0,
        "quota_actions": 0,
        "adapter_actions": 0,
        "provider_actions": 0,
    }


class DeterministicPropertyOutputAllocationPlanner:
    """Pure allocation planning; it never creates directories, files, quota, or jobs."""

    def __call__(self, plan: PropertyPrebuildPlan) -> PropertyOutputAllocation:
        return PropertyOutputAllocation.parse(_allocation_payload(plan))


def build_property_execution_boundary(
    plan: PropertyPrebuildPlan | Mapping[str, object],
    allocation: PropertyOutputAllocation | Mapping[str, object],
) -> PropertyExecutionBoundary:
    parsed_plan = PropertyPrebuildPlan.parse(plan)
    parsed_allocation = PropertyOutputAllocation.parse(allocation)
    expected_allocation = PropertyOutputAllocation.parse(_allocation_payload(parsed_plan))
    if parsed_allocation.canonical_bytes() != expected_allocation.canonical_bytes():
        raise PropertyPrebuildError("property_output_allocation_binding_mismatch")
    plan_payload = parsed_plan.as_dict()
    allocation_payload = parsed_allocation.as_dict()
    execution_identity = _domain_digest(
        "propertyquarry.prebuild.execution_identity.v1",
        {
            "plan_digest": parsed_plan.digest,
            "allocation_digest": parsed_allocation.digest,
            "composition_digest": plan_payload["composition_digest"],
            "material_digest": plan_payload["material_digest"],
            "execution_target_digest": plan_payload["execution_target_digest"],
        },
    )
    return PropertyExecutionBoundary.parse(
        {
            "contract_name": PROPERTY_EXECUTION_BOUNDARY_CONTRACT,
            "contract_version": "1.0.0",
            "execution_identity_digest": execution_identity,
            "plan_digest": parsed_plan.digest,
            "allocation_digest": parsed_allocation.digest,
            "allocation_ref": allocation_payload["allocation_ref"],
            "composition_digest": plan_payload["composition_digest"],
            "material_digest": plan_payload["material_digest"],
            "execution_target_digest": plan_payload["execution_target_digest"],
            "artifact_family": PROPERTY_ARTIFACT_FAMILY,
            "content_profile": PROPERTY_CONTENT_PROFILE,
            "adapter_invoked": False,
            "provider_actions": 0,
            "render_actions": 0,
        }
    )


def build_property_artifact_candidate(
    *,
    boundary: PropertyExecutionBoundary | Mapping[str, object],
    execution_evidence: PropertyExecutionEvidence | Mapping[str, object],
    allocation_slot_ref: str,
    artifact_ref: str,
    artifact_digest: str,
    verification_profile_digest: str,
) -> PropertyArtifactCandidate:
    parsed_boundary = PropertyExecutionBoundary.parse(boundary)
    evidence = PropertyExecutionEvidence.parse(execution_evidence)
    boundary_payload = parsed_boundary.as_dict()
    evidence_payload = evidence.as_dict()
    if (
        evidence_payload["state"] != "succeeded"
        or evidence_payload["execution_identity_digest"]
        != boundary_payload["execution_identity_digest"]
        or evidence_payload["execution_boundary_digest"] != parsed_boundary.digest
        or evidence_payload["plan_digest"] != boundary_payload["plan_digest"]
        or evidence_payload["allocation_digest"] != boundary_payload["allocation_digest"]
        or evidence_payload["output_digest"] != artifact_digest
    ):
        raise PropertyPrebuildError("property_execution_evidence_binding_mismatch")
    _required_ref(allocation_slot_ref)
    _required_ref(artifact_ref)
    _required_digest(artifact_digest)
    _required_digest(verification_profile_digest)
    artifact_identity = _domain_digest(
        "propertyquarry.prebuild.artifact_identity.v1",
        {
            "allocation_slot_ref": allocation_slot_ref,
            "artifact_ref": artifact_ref,
            "artifact_digest": artifact_digest,
            "execution_evidence_digest": evidence.digest,
        },
    )
    return PropertyArtifactCandidate.parse(
        {
            "contract_name": PROPERTY_ARTIFACT_CANDIDATE_CONTRACT,
            "contract_version": "1.0.0",
            "plan_digest": boundary_payload["plan_digest"],
            "allocation_digest": boundary_payload["allocation_digest"],
            "execution_identity_digest": boundary_payload["execution_identity_digest"],
            "execution_evidence_digest": evidence.digest,
            "allocation_slot_ref": allocation_slot_ref,
            "artifact_ref": artifact_ref,
            "artifact_digest": artifact_digest,
            "artifact_identity_digest": artifact_identity,
            "verification_profile_digest": verification_profile_digest,
        }
    )


class _ActiveGate:
    __slots__ = (
        "scope_digest",
        "_authority",
        "_lifecycle_guard",
        "_revalidate",
        "_active",
        "_owner",
    )

    def __init__(
        self,
        scope_digest: str,
        authority: SpatialLifecycleAuthority,
        lifecycle_guard: SpatialCompositionLifecycleGuard,
        revalidate: Callable[[], datetime],
        *,
        marker: object,
    ) -> None:
        if marker is not _GATE_MARKER:
            raise PropertyPrebuildError("property_prebuild_gate_invalid")
        self.scope_digest = scope_digest
        self._authority = authority
        self._lifecycle_guard = lifecycle_guard
        self._revalidate = revalidate
        self._active = True
        self._owner = threading.get_ident()

    def assert_active(
        self, scope_digest: str, authority: SpatialLifecycleAuthority
    ) -> None:
        if (
            not self._active
            or self._owner != threading.get_ident()
            or self.scope_digest != scope_digest
            or self._authority is not authority
        ):
            raise PropertyPrebuildError("property_prebuild_gate_invalid")
        self._revalidate()

    def close(self) -> None:
        self._active = False


@dataclass(frozen=True, slots=True)
class PropertyReconciliationAppendResult:
    record: PropertyReconciliationRecord
    idempotent_replay: bool


def _record_digest(payload: Mapping[str, object]) -> str:
    material = dict(payload)
    material.pop("record_digest", None)
    return _domain_digest("propertyquarry.prebuild.reconciliation_chain.v1", material)


_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"planned"}),
    "planned": frozenset({"allocation_planned", "blocked_final", "failed_final"}),
    "allocation_planned": frozenset(
        {"execution_pending", "blocked_final", "failed_final"}
    ),
    "execution_pending": frozenset(
        {"execution_succeeded", "blocked_final", "failed_final"}
    ),
    "execution_succeeded": frozenset({"artifact_verified", "failed_final"}),
    "artifact_verified": frozenset(),
    "blocked_final": frozenset(),
    "failed_final": frozenset(),
}


class PropertyPrebuildReconciliationStore:
    """Descriptor-relative append-only journal under one pinned local root."""

    @dataclass(slots=True)
    class _RootHandle:
        parent_fd: int
        root_fd: int
        root_name: str
        identity: tuple[int, int]

        def close(self) -> None:
            os.close(self.root_fd)
            os.close(self.parent_fd)

    def __init__(self, root: Path, *, lifecycle_authority: SpatialLifecycleAuthority) -> None:
        rendered = os.fspath(root) if isinstance(root, Path) else ""
        if (
            not isinstance(root, Path)
            or not root.is_absolute()
            or root == Path("/")
            or rendered != os.path.normpath(rendered)
            or ".." in root.parts
            or not isinstance(lifecycle_authority, SpatialLifecycleAuthority)
        ):
            raise PropertyPrebuildError("property_reconciliation_store_configuration_invalid")
        self.root = root
        self.lifecycle_authority = lifecycle_authority
        self._thread_lock = threading.RLock()
        self._owner = os.geteuid()
        self._root_identity: tuple[int, int] | None = None
        self._file_identities: dict[str, tuple[int, int]] = {}
        self._root_anchor_fd: int | None = None
        self._root_parent_anchor_fd: int | None = None
        self._lock_anchor_fd: int | None = None
        self._journal_anchor_fd: int | None = None
        self._lock_generation_digest: str | None = None
        self._closed = False

    def close(self) -> None:
        with self._thread_lock:
            self._closed = True
            for attribute in (
                "_journal_anchor_fd",
                "_lock_anchor_fd",
                "_root_anchor_fd",
                "_root_parent_anchor_fd",
            ):
                descriptor = getattr(self, attribute)
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                    setattr(self, attribute, None)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _directory_flags() -> int:
        return (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )

    @staticmethod
    def _identity(details: os.stat_result) -> tuple[int, int]:
        return (details.st_dev, details.st_ino)

    def _validate_directory_fd(self, descriptor: int, *, root: bool) -> os.stat_result:
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise PropertyPrebuildError("property_reconciliation_store_ancestor_invalid")
        if root and (
            details.st_uid != self._owner or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise PropertyPrebuildError("property_reconciliation_store_root_insecure")
        return details

    def _pin_root(self, identity: tuple[int, int]) -> None:
        if self._root_identity is None:
            self._root_identity = identity
        elif self._root_identity != identity:
            raise PropertyPrebuildError("property_reconciliation_store_root_substituted")

    def _pin_root_descriptors(self, parent_fd: int, root_fd: int) -> None:
        if self._root_anchor_fd is None:
            try:
                self._root_parent_anchor_fd = os.dup(parent_fd)
                self._root_anchor_fd = os.dup(root_fd)
            except Exception:
                self.close()
                raise PropertyPrebuildError(
                    "property_reconciliation_store_unavailable"
                ) from None
        try:
            anchor_details = self._validate_directory_fd(
                self._root_anchor_fd, root=True
            )
        except Exception:
            raise PropertyPrebuildError(
                "property_reconciliation_store_root_substituted"
            ) from None
        if self._identity(anchor_details) != self._root_identity:
            raise PropertyPrebuildError(
                "property_reconciliation_store_root_substituted"
            )

    def _open_root(self, *, create: bool) -> _RootHandle | None:
        if self._closed:
            raise PropertyPrebuildError("property_reconciliation_store_unavailable")
        descriptors: list[int] = []
        try:
            current = os.open("/", self._directory_flags())
            descriptors.append(current)
            self._validate_directory_fd(current, root=False)
            components = self.root.parts[1:]
            for component in components[:-1]:
                child = os.open(component, self._directory_flags(), dir_fd=current)
                descriptors.append(child)
                self._validate_directory_fd(child, root=False)
                current = child
            parent_fd = descriptors.pop()
            root_name = components[-1]
            created = False
            try:
                root_fd = os.open(root_name, self._directory_flags(), dir_fd=parent_fd)
            except FileNotFoundError:
                if not create:
                    os.close(parent_fd)
                    return None
                try:
                    os.mkdir(root_name, 0o700, dir_fd=parent_fd)
                    created = True
                    os.fsync(parent_fd)
                except FileExistsError:
                    created = False
                root_fd = os.open(root_name, self._directory_flags(), dir_fd=parent_fd)
            root_details = self._validate_directory_fd(root_fd, root=True)
            path_details = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
            identity = self._identity(root_details)
            if not stat.S_ISDIR(path_details.st_mode) or self._identity(path_details) != identity:
                os.close(root_fd)
                os.close(parent_fd)
                raise PropertyPrebuildError("property_reconciliation_store_root_substituted")
            self._pin_root(identity)
            self._pin_root_descriptors(parent_fd, root_fd)
            if created:
                os.fsync(root_fd)
            return self._RootHandle(parent_fd, root_fd, root_name, identity)
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError("property_reconciliation_store_unavailable") from None
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _validate_root_binding(self, root: _RootHandle) -> None:
        try:
            descriptor_details = self._validate_directory_fd(root.root_fd, root=True)
            path_details = os.stat(
                root.root_name, dir_fd=root.parent_fd, follow_symlinks=False
            )
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError("property_reconciliation_store_root_substituted") from None
        if (
            self._identity(descriptor_details) != root.identity
            or not stat.S_ISDIR(path_details.st_mode)
            or self._identity(path_details) != root.identity
            or self._root_identity != root.identity
        ):
            raise PropertyPrebuildError("property_reconciliation_store_root_substituted")
        if self._root_anchor_fd is None:
            raise PropertyPrebuildError("property_reconciliation_store_root_substituted")
        try:
            anchor_details = os.fstat(self._root_anchor_fd)
        except Exception:
            raise PropertyPrebuildError(
                "property_reconciliation_store_root_substituted"
            ) from None
        if self._identity(anchor_details) != root.identity:
            raise PropertyPrebuildError("property_reconciliation_store_root_substituted")

    def _validate_file_fd(
        self, root: _RootHandle, name: str, descriptor: int
    ) -> os.stat_result:
        try:
            details = os.fstat(descriptor)
            path_details = os.stat(name, dir_fd=root.root_fd, follow_symlinks=False)
        except Exception:
            raise PropertyPrebuildError("property_reconciliation_store_file_substituted") from None
        identity = self._identity(details)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != self._owner
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_nlink != 1
            or not stat.S_ISREG(path_details.st_mode)
            or self._identity(path_details) != identity
            or path_details.st_nlink != 1
        ):
            raise PropertyPrebuildError("property_reconciliation_store_file_insecure")
        pinned = self._file_identities.get(name)
        if pinned is None:
            self._file_identities[name] = identity
        elif pinned != identity:
            raise PropertyPrebuildError("property_reconciliation_store_file_substituted")
        if name == _LOCK_NAME:
            self._validate_lock_generation(descriptor)
        return details

    @staticmethod
    def _anchor_attribute(name: str) -> str:
        if name == _LOCK_NAME:
            return "_lock_anchor_fd"
        if name == _JOURNAL_NAME:
            return "_journal_anchor_fd"
        raise PropertyPrebuildError("property_reconciliation_store_file_invalid")

    def _read_lock_generation(self, descriptor: int) -> str | None:
        try:
            details = os.fstat(descriptor)
            if details.st_size == 0:
                return None
            if details.st_size != 72:
                raise PropertyPrebuildError(
                    "property_reconciliation_store_lock_invalid"
                )
            raw = os.pread(descriptor, details.st_size, 0)
            if len(raw) != details.st_size or not raw.endswith(b"\n"):
                raise PropertyPrebuildError(
                    "property_reconciliation_store_lock_invalid"
                )
            generation = raw[:-1].decode("ascii")
            _required_digest(generation)
            return generation
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError(
                "property_reconciliation_store_lock_invalid"
            ) from None

    def _initialize_lock_generation(
        self, root: _RootHandle, descriptor: int
    ) -> str:
        try:
            if os.fstat(descriptor).st_size != 0:
                raise PropertyPrebuildError(
                    "property_reconciliation_store_lock_invalid"
                )
            generation = _domain_digest(
                "propertyquarry.prebuild.reconciliation_lock_generation.v1",
                {
                    "root_device": root.identity[0],
                    "root_inode": root.identity[1],
                    "nonce": os.urandom(32).hex(),
                },
            )
            encoded = generation.encode("ascii") + b"\n"
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    raise PropertyPrebuildError(
                        "property_reconciliation_store_lock_invalid"
                    )
                offset += written
            os.fsync(descriptor)
            os.fsync(root.root_fd)
            return generation
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError(
                "property_reconciliation_store_unavailable"
            ) from None

    def _validate_lock_generation(self, descriptor: int) -> str:
        generation = self._read_lock_generation(descriptor)
        if generation is None:
            raise PropertyPrebuildError(
                "property_reconciliation_store_lock_invalid"
            )
        if self._lock_generation_digest is None:
            self._lock_generation_digest = generation
        elif self._lock_generation_digest != generation:
            raise PropertyPrebuildError(
                "property_reconciliation_store_lock_substituted"
            )
        return generation

    def _open_file(
        self, root: _RootHandle, name: str, *, create: bool
    ) -> tuple[int, bool]:
        flags = (
            os.O_RDWR
            | os.O_APPEND
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        anchor_attribute = self._anchor_attribute(name)
        anchor = getattr(self, anchor_attribute)
        if anchor is not None:
            try:
                descriptor = os.dup(anchor)
                self._validate_file_fd(root, name, descriptor)
                return descriptor, False
            except PropertyPrebuildError:
                try:
                    os.close(descriptor)
                except (OSError, UnboundLocalError):
                    pass
                raise
            except Exception:
                raise PropertyPrebuildError(
                    "property_reconciliation_store_unavailable"
                ) from None

        attempts = 100 if name == _LOCK_NAME and create else 1
        for attempt in range(attempts):
            descriptor: int | None = None
            created = False
            try:
                if create:
                    try:
                        descriptor = os.open(
                            name,
                            flags | os.O_CREAT | os.O_EXCL,
                            0o600,
                            dir_fd=root.root_fd,
                        )
                        created = True
                    except FileExistsError:
                        descriptor = os.open(name, flags, dir_fd=root.root_fd)
                else:
                    descriptor = os.open(name, flags, dir_fd=root.root_fd)
                if name == _LOCK_NAME:
                    generation = (
                        self._initialize_lock_generation(root, descriptor)
                        if created
                        else self._read_lock_generation(descriptor)
                    )
                    if generation is None:
                        os.close(descriptor)
                        descriptor = None
                        if attempt + 1 < attempts:
                            time.sleep(0.001)
                            continue
                        try:
                            journal_details = os.stat(
                                _JOURNAL_NAME,
                                dir_fd=root.root_fd,
                                follow_symlinks=False,
                            )
                        except FileNotFoundError:
                            journal_details = None
                        except Exception:
                            raise PropertyPrebuildError(
                                "property_reconciliation_store_unavailable"
                            ) from None
                        reason = (
                            "property_reconciliation_lock_substituted"
                            if journal_details is not None
                            else "property_reconciliation_store_lock_invalid"
                        )
                        raise PropertyPrebuildError(reason)
                    if self._lock_generation_digest is None:
                        self._lock_generation_digest = generation
                    elif self._lock_generation_digest != generation:
                        raise PropertyPrebuildError(
                            "property_reconciliation_store_lock_substituted"
                        )
                self._validate_file_fd(root, name, descriptor)
                pinned_descriptor = os.dup(descriptor)
                setattr(self, anchor_attribute, pinned_descriptor)
                try:
                    self._validate_file_fd(root, name, pinned_descriptor)
                except Exception:
                    os.close(pinned_descriptor)
                    setattr(self, anchor_attribute, None)
                    raise
                self._validate_file_fd(root, name, descriptor)
                if created:
                    os.fsync(root.root_fd)
                return descriptor, created
            except PropertyPrebuildError:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                if created:
                    try:
                        os.unlink(name, dir_fd=root.root_fd)
                        os.fsync(root.root_fd)
                    except OSError:
                        pass
                raise
            except Exception:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                raise PropertyPrebuildError(
                    "property_reconciliation_store_unavailable"
                ) from None
        raise PropertyPrebuildError("property_reconciliation_store_unavailable")

    def _lock_identity_digest(self, descriptor: int) -> str:
        details = os.fstat(descriptor)
        generation = self._validate_lock_generation(descriptor)
        return _domain_digest(
            "propertyquarry.prebuild.reconciliation_lock_identity.v1",
            {
                "device": details.st_dev,
                "inode": details.st_ino,
                "generation_digest": generation,
            },
        )

    @staticmethod
    def _parse_records(raw: bytes) -> list[PropertyReconciliationRecord]:
        if len(raw) > _MAX_JOURNAL_BYTES:
            raise PropertyPrebuildError("property_reconciliation_journal_too_large")
        if any(
            separator in raw
            for separator in (b"\r", b"\xc2\x85", b"\xe2\x80\xa8", b"\xe2\x80\xa9")
        ):
            raise PropertyPrebuildError("property_reconciliation_journal_frame_invalid")
        if raw and not raw.endswith(b"\n"):
            raise PropertyPrebuildError("property_reconciliation_journal_truncated")
        records: list[PropertyReconciliationRecord] = []
        latest: dict[str, PropertyReconciliationRecord] = {}
        frames = raw[:-1].split(b"\n") if raw else []
        for frame in frames:
            if not frame or len(frame) > _MAX_JOURNAL_RECORD_BYTES:
                raise PropertyPrebuildError("property_reconciliation_journal_frame_invalid")
            record = PropertyReconciliationRecord.parse(frame)
            payload = record.as_dict()
            if payload["record_digest"] != _record_digest(payload):
                raise PropertyPrebuildError("property_reconciliation_record_digest_invalid")
            key = str(payload["reconciliation_key"])
            expected_identity = _domain_digest(
                "propertyquarry.prebuild.reconciliation_identity.v1",
                {
                    "reconciliation_key": key,
                    "ledger_scope_digest": payload["ledger_scope_digest"],
                    "composition_digest": payload["composition_digest"],
                    "plan_digest": payload["plan_digest"],
                },
            )
            if payload["reconciliation_identity_digest"] != expected_identity:
                raise PropertyPrebuildError("property_reconciliation_identity_invalid")
            identity = str(payload["reconciliation_identity_digest"])
            prior = latest.get(identity)
            if prior is None:
                if payload["sequence"] != 1 or payload["prior_record_digest"] is not None:
                    raise PropertyPrebuildError("property_reconciliation_chain_invalid")
            else:
                prior_payload = prior.as_dict()
                if (
                    payload["sequence"] != prior_payload["sequence"] + 1
                    or payload["prior_record_digest"] != prior.record_digest
                ):
                    raise PropertyPrebuildError("property_reconciliation_chain_invalid")
                immutable = (
                    "reconciliation_identity_digest",
                    "ledger_scope_digest",
                    "composition_digest",
                    "plan_digest",
                    "allocation_digest",
                    "execution_boundary_digest",
                    "execution_identity_digest",
                    "retention_anchor",
                    "retention_expires_at",
                    "lock_identity_digest",
                )
                if any(payload[field] != prior_payload[field] for field in immutable):
                    raise PropertyPrebuildError("property_reconciliation_binding_changed")
                if payload["state"] not in _TRANSITIONS[str(prior_payload["state"])]:
                    raise PropertyPrebuildError("property_reconciliation_transition_invalid")
                if _as_datetime(payload["recorded_at"]) < _as_datetime(
                    prior_payload["recorded_at"]
                ):
                    raise PropertyPrebuildError("property_reconciliation_clock_rollback")
                prior_execution_authority = prior_payload[
                    "execution_authority_receipt_digest"
                ]
                current_execution_authority = payload[
                    "execution_authority_receipt_digest"
                ]
                if prior_execution_authority is not None and (
                    current_execution_authority != prior_execution_authority
                ):
                    raise PropertyPrebuildError("property_reconciliation_authority_changed")
            latest[identity] = record
            records.append(record)
        return records

    def _validate_lock_lineage(
        self,
        records: list[PropertyReconciliationRecord],
        lock_descriptor: int,
    ) -> None:
        expected = self._lock_identity_digest(lock_descriptor)
        if any(
            record.as_dict()["lock_identity_digest"] != expected
            for record in records
        ):
            raise PropertyPrebuildError("property_reconciliation_lock_substituted")

    def _read_locked(self, descriptor: int) -> list[PropertyReconciliationRecord]:
        details = os.fstat(descriptor)
        if details.st_size > _MAX_JOURNAL_BYTES:
            raise PropertyPrebuildError("property_reconciliation_journal_too_large")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise PropertyPrebuildError("property_reconciliation_journal_truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        return self._parse_records(b"".join(chunks))

    def _history_without_effects(
        self,
        *,
        gate: _ActiveGate,
        key: str,
        ledger_scope_digest: str,
        composition_digest: str,
        plan_digest: str,
    ) -> tuple[PropertyReconciliationRecord, ...]:
        try:
            gate.assert_active(composition_digest, self.lifecycle_authority)
            _required_ref(key)
            for digest in (ledger_scope_digest, composition_digest, plan_digest):
                _required_digest(digest)
            with self._thread_lock:
                root = self._open_root(create=False)
                if root is None:
                    return ()
                try:
                    try:
                        lock_fd, _ = self._open_file(root, _LOCK_NAME, create=False)
                    except PropertyPrebuildError as exc:
                        if str(exc) == "property_reconciliation_store_unavailable":
                            return ()
                        raise
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX)
                        self._validate_root_binding(root)
                        self._validate_file_fd(root, _LOCK_NAME, lock_fd)
                        try:
                            journal_fd, _ = self._open_file(
                                root, _JOURNAL_NAME, create=False
                            )
                        except PropertyPrebuildError as exc:
                            if str(exc) == "property_reconciliation_store_unavailable":
                                raise PropertyPrebuildError(
                                    "property_reconciliation_store_incomplete"
                                ) from None
                            raise
                        try:
                            records = self._read_locked(journal_fd)
                            self._validate_lock_lineage(records, lock_fd)
                            self._validate_file_fd(root, _JOURNAL_NAME, journal_fd)
                            self._validate_file_fd(root, _LOCK_NAME, lock_fd)
                            self._validate_root_binding(root)
                        finally:
                            os.close(journal_fd)
                    finally:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        os.close(lock_fd)
                finally:
                    root.close()
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError("property_reconciliation_store_unavailable") from None
        selected: list[PropertyReconciliationRecord] = []
        for record in records:
            payload = record.as_dict()
            if payload["reconciliation_key"] != key:
                continue
            if (
                payload["ledger_scope_digest"] == ledger_scope_digest
                and payload["composition_digest"] == composition_digest
                and payload["plan_digest"] == plan_digest
            ):
                selected.append(record)
        return tuple(selected)

    @staticmethod
    def _prevalidate_append(
        *,
        reconciliation_key: str,
        bindings: Mapping[str, object],
        state: object,
        outcome_digest: object,
        artifact_identity_digest: object,
        verification_digest: object,
        execution_authority_receipt_digest: object,
        artifact_authority_receipt_digest: object,
        recorded_at: datetime,
    ) -> dict[str, object]:
        try:
            _required_ref(reconciliation_key)
            if state not in _TRANSITIONS:
                raise ValueError("state")
            required = {
                "ledger_scope_digest",
                "composition_digest",
                "plan_digest",
                "allocation_digest",
                "execution_boundary_digest",
                "execution_identity_digest",
                "retention_anchor",
                "retention_expires_at",
            }
            supplied = _snapshot_mapping(
                bindings, reason="property_reconciliation_binding_invalid"
            )
            if set(supplied) != required:
                raise ValueError("bindings")
            for field in required - {"retention_anchor", "retention_expires_at"}:
                _required_digest(supplied[field])  # type: ignore[arg-type]
            _canonical_timestamp(supplied["retention_anchor"])  # type: ignore[arg-type]
            _canonical_timestamp(supplied["retention_expires_at"])  # type: ignore[arg-type]
            current = _observed(recorded_at)
            reconciliation_identity = _domain_digest(
                "propertyquarry.prebuild.reconciliation_identity.v1",
                {
                    "reconciliation_key": reconciliation_key,
                    "ledger_scope_digest": supplied["ledger_scope_digest"],
                    "composition_digest": supplied["composition_digest"],
                    "plan_digest": supplied["plan_digest"],
                },
            )
            prospective: dict[str, object] = {
                "contract_name": PROPERTY_RECONCILIATION_CONTRACT,
                "contract_version": "1.0.0",
                "reconciliation_key": reconciliation_key,
                "reconciliation_identity_digest": reconciliation_identity,
                "sequence": 1,
                "prior_record_digest": None,
                "record_digest": "sha256:" + "0" * 64,
                "lock_identity_digest": "sha256:" + "0" * 64,
                **supplied,
                "execution_authority_receipt_digest": execution_authority_receipt_digest,
                "artifact_authority_receipt_digest": artifact_authority_receipt_digest,
                "artifact_identity_digest": artifact_identity_digest,
                "verification_digest": verification_digest,
                "state": state,
                "outcome_digest": outcome_digest,
                "recorded_at": utc_iso(current),
            }
            prospective["record_digest"] = _record_digest(prospective)
            PropertyReconciliationRecord.parse(prospective)
            return prospective
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError("property_reconciliation_request_invalid") from None

    def append_guarded(
        self,
        *,
        gate: _ActiveGate,
        scope_digest: str,
        reconciliation_key: str,
        bindings: Mapping[str, object],
        state: ReconciliationState,
        outcome_digest: str | None,
        artifact_identity_digest: str | None,
        verification_digest: str | None,
        execution_authority_receipt_digest: str | None,
        artifact_authority_receipt_digest: str | None,
        recorded_at: datetime,
    ) -> PropertyReconciliationAppendResult:
        prospective = self._prevalidate_append(
            reconciliation_key=reconciliation_key,
            bindings=bindings,
            state=state,
            outcome_digest=outcome_digest,
            artifact_identity_digest=artifact_identity_digest,
            verification_digest=verification_digest,
            execution_authority_receipt_digest=execution_authority_receipt_digest,
            artifact_authority_receipt_digest=artifact_authority_receipt_digest,
            recorded_at=recorded_at,
        )
        current = _observed(recorded_at)
        composition_digest = str(prospective["composition_digest"])
        if composition_digest != scope_digest:
            raise PropertyPrebuildError("property_reconciliation_scope_mismatch")
        gate.assert_active(scope_digest, self.lifecycle_authority)
        with self._thread_lock:
            root_probe = self._open_root(create=False)
            if root_probe is None and state != "planned":
                raise PropertyPrebuildError(
                    "property_reconciliation_initial_state_invalid"
                )
            if root_probe is not None:
                root_probe.close()
        try:
            with self._thread_lock:
                root = self._open_root(create=True)
                if root is None:
                    raise PropertyPrebuildError("property_reconciliation_store_unavailable")
                try:
                    lock_fd, _ = self._open_file(root, _LOCK_NAME, create=True)
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX)
                        self._validate_root_binding(root)
                        self._validate_file_fd(root, _LOCK_NAME, lock_fd)
                        lock_identity_digest = self._lock_identity_digest(lock_fd)
                        try:
                            journal_fd, journal_created = self._open_file(
                                root, _JOURNAL_NAME, create=False
                            )
                        except PropertyPrebuildError as exc:
                            if str(exc) != "property_reconciliation_store_unavailable":
                                raise
                            if state != "planned":
                                raise PropertyPrebuildError(
                                    "property_reconciliation_initial_state_invalid"
                                ) from None
                            journal_fd, journal_created = self._open_file(
                                root, _JOURNAL_NAME, create=True
                            )
                        try:
                            records = self._read_locked(journal_fd)
                            self._validate_lock_lineage(records, lock_fd)
                            reconciliation_identity = prospective[
                                "reconciliation_identity_digest"
                            ]
                            history = [
                                record
                                for record in records
                                if record.as_dict()[
                                    "reconciliation_identity_digest"
                                ]
                                == reconciliation_identity
                            ]
                            prior = history[-1] if history else None
                            immutable = {
                                "reconciliation_identity_digest": prospective[
                                    "reconciliation_identity_digest"
                                ],
                                "ledger_scope_digest": prospective[
                                    "ledger_scope_digest"
                                ],
                                "composition_digest": prospective[
                                    "composition_digest"
                                ],
                                "plan_digest": bindings["plan_digest"],
                                "allocation_digest": bindings["allocation_digest"],
                                "execution_boundary_digest": bindings[
                                    "execution_boundary_digest"
                                ],
                                "execution_identity_digest": bindings[
                                    "execution_identity_digest"
                                ],
                                "retention_anchor": bindings["retention_anchor"],
                                "retention_expires_at": bindings[
                                    "retention_expires_at"
                                ],
                                "lock_identity_digest": lock_identity_digest,
                            }
                            requested = {
                                **immutable,
                                "state": state,
                                "outcome_digest": outcome_digest,
                                "artifact_identity_digest": artifact_identity_digest,
                                "verification_digest": verification_digest,
                                "execution_authority_receipt_digest": (
                                    execution_authority_receipt_digest
                                ),
                                "artifact_authority_receipt_digest": (
                                    artifact_authority_receipt_digest
                                ),
                            }
                            if prior is not None:
                                prior_payload = prior.as_dict()
                                if (
                                    state == "failed_final"
                                    and execution_authority_receipt_digest is None
                                ):
                                    requested["execution_authority_receipt_digest"] = (
                                        prior_payload[
                                            "execution_authority_receipt_digest"
                                        ]
                                    )
                                if current < _as_datetime(prior_payload["recorded_at"]):
                                    raise PropertyPrebuildError(
                                        "property_reconciliation_clock_rollback"
                                    )
                                if any(
                                    prior_payload[field] != value
                                    for field, value in immutable.items()
                                ):
                                    raise PropertyPrebuildError(
                                        "property_reconciliation_idempotency_conflict"
                                    )
                                replay_fields = (
                                    "state",
                                    "outcome_digest",
                                    "artifact_identity_digest",
                                    "verification_digest",
                                    "execution_authority_receipt_digest",
                                    "artifact_authority_receipt_digest",
                                )
                                if all(
                                    prior_payload[field] == requested[field]
                                    for field in replay_fields
                                ):
                                    return PropertyReconciliationAppendResult(prior, True)
                                if state not in _TRANSITIONS[
                                    str(prior_payload["state"])
                                ]:
                                    raise PropertyPrebuildError(
                                        "property_reconciliation_transition_invalid"
                                    )
                            elif state != "planned":
                                raise PropertyPrebuildError(
                                    "property_reconciliation_initial_state_invalid"
                                )
                            payload: dict[str, object] = {
                                "contract_name": PROPERTY_RECONCILIATION_CONTRACT,
                                "contract_version": "1.0.0",
                                "reconciliation_key": reconciliation_key,
                                "reconciliation_identity_digest": prospective[
                                    "reconciliation_identity_digest"
                                ],
                                "sequence": len(history) + 1,
                                "prior_record_digest": (
                                    prior.record_digest if prior else None
                                ),
                                "record_digest": "sha256:" + "0" * 64,
                                **requested,
                                "recorded_at": utc_iso(current),
                            }
                            payload["record_digest"] = _record_digest(payload)
                            record = PropertyReconciliationRecord.parse(payload)
                            encoded = record.canonical_bytes() + b"\n"
                            if len(encoded) > _MAX_JOURNAL_RECORD_BYTES:
                                raise PropertyPrebuildError(
                                    "property_reconciliation_journal_frame_too_large"
                                )
                            current_size = os.fstat(journal_fd).st_size
                            if current_size + len(encoded) > _MAX_JOURNAL_BYTES:
                                raise PropertyPrebuildError(
                                    "property_reconciliation_journal_capacity_exceeded"
                                )
                            gate.assert_active(scope_digest, self.lifecycle_authority)
                            self._validate_root_binding(root)
                            self._validate_file_fd(root, _LOCK_NAME, lock_fd)
                            self._validate_file_fd(root, _JOURNAL_NAME, journal_fd)
                            offset = 0
                            while offset < len(encoded):
                                written = os.write(journal_fd, encoded[offset:])
                                if written <= 0:
                                    raise PropertyPrebuildError(
                                        "property_reconciliation_journal_write_failed"
                                    )
                                offset += written
                            os.fsync(journal_fd)
                            self._validate_file_fd(root, _JOURNAL_NAME, journal_fd)
                            self._validate_file_fd(root, _LOCK_NAME, lock_fd)
                            self._validate_root_binding(root)
                            if journal_created:
                                os.fsync(root.root_fd)
                            return PropertyReconciliationAppendResult(record, False)
                        finally:
                            os.close(journal_fd)
                    finally:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        os.close(lock_fd)
                finally:
                    root.close()
        except PropertyPrebuildError:
            raise
        except Exception:
            raise PropertyPrebuildError("property_reconciliation_store_unavailable") from None


@dataclass(frozen=True, slots=True)
class _GateSnapshot:
    selection: PropertyPrebuildSelection
    receipt: dict[str, object]
    material: GovernedSpatialExecutionMaterialV1
    plan: PropertyPrebuildPlan
    observed_at: datetime
    gate: _ActiveGate
    revalidate: Callable[[], datetime]


_POLICY_FAILURES = {
    "property_policy_evidence_required": "property_prebuild_policy_missing",
    "property_policy_missing": "property_prebuild_policy_missing",
    "property_policy_evidence_stale": "property_prebuild_policy_stale",
    "property_policy_stale": "property_prebuild_policy_stale",
    "property_policy_evidence_not_current": "property_prebuild_policy_stale",
    "property_policy_digest_mismatch": "property_prebuild_policy_digest_mismatched",
    "property_policy_digest_mismatched": "property_prebuild_policy_digest_mismatched",
    "property_policy_mode_mismatch": "property_prebuild_policy_mode_mismatched",
    "property_policy_mode_mismatched": "property_prebuild_policy_mode_mismatched",
    "property_policy_evidence_expired": "property_prebuild_policy_expired",
    "property_policy_expired": "property_prebuild_policy_expired",
    "property_policy_revoked": "property_prebuild_policy_revoked",
    "property_policy_unverifiable": "property_prebuild_policy_unverifiable",
    "property_policy_verifier_unavailable": "property_prebuild_policy_unverifiable",
}


class PropertyPrebuildCoordinator:
    """Third-gated PropertyQuarry pre-build planning and evidence coordinator."""

    def __init__(
        self,
        *,
        ledger: DurableSpatialLedger,
        material_store: SpatialExecutionMaterialStore,
        receipt_verifier: PropertyComposeReceiptVerifier,
        policy_verifier: PropertyCurrentPolicyVerifier,
        input_authority_verifier: PropertyCurrentInputAuthorityVerifier,
        output_allocation_planner: PropertyOutputAllocationPlanner | None = None,
        artifact_verifier: PropertyArtifactEvidenceVerifier | None = None,
        reconciliation_store: PropertyPrebuildReconciliationStore | None = None,
        telemetry_sink: Callable[[Mapping[str, object]], None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        evidence_authority_registry: CanonicalEd25519KeyRegistry | None = None,
        execution_evidence_authority: PropertyEvidenceAuthority | None = None,
        artifact_evidence_authority: PropertyEvidenceAuthority | None = None,
    ) -> None:
        if not isinstance(ledger, DurableSpatialLedger) or not isinstance(
            material_store, SpatialExecutionMaterialStore
        ):
            raise PropertyPrebuildError("property_prebuild_dependencies_invalid")
        self._ledger = ledger
        self._material_store = material_store
        self._receipt_verifier = receipt_verifier
        self._policy_verifier = policy_verifier
        self._input_authority_verifier = input_authority_verifier
        self._allocator = output_allocation_planner or DeterministicPropertyOutputAllocationPlanner()
        self._artifact_verifier = artifact_verifier
        self._reconciliation_store = reconciliation_store
        self._telemetry_sink = telemetry_sink
        self._now = now
        self._evidence_authority_registry = evidence_authority_registry
        self._execution_evidence_authority = execution_evidence_authority
        self._artifact_evidence_authority = artifact_evidence_authority
        self._clock_lock = threading.Lock()
        self._last_trusted_time: datetime | None = None
        self._entry_state = threading.local()
        required_callables = (
            receipt_verifier,
            policy_verifier,
            input_authority_verifier,
            self._allocator,
            now,
        )
        if any(not callable(dependency) for dependency in required_callables):
            raise PropertyPrebuildError("property_prebuild_dependency_posture_invalid")
        if artifact_verifier is not None and not callable(artifact_verifier):
            raise PropertyPrebuildError("property_prebuild_dependency_posture_invalid")
        if telemetry_sink is not None and not callable(telemetry_sink):
            raise PropertyPrebuildError("property_prebuild_dependency_posture_invalid")
        authority_values = (
            execution_evidence_authority,
            artifact_evidence_authority,
        )
        if any(
            authority is not None and not isinstance(authority, PropertyEvidenceAuthority)
            for authority in authority_values
        ):
            raise PropertyPrebuildError("property_evidence_authority_invalid")
        if execution_evidence_authority is not None and (
            execution_evidence_authority.authority_kind != "execution"
        ):
            raise PropertyPrebuildError("property_evidence_authority_invalid")
        if artifact_evidence_authority is not None and (
            artifact_evidence_authority.authority_kind != "artifact_verification"
        ):
            raise PropertyPrebuildError("property_evidence_authority_invalid")
        if any(authority_values) and not isinstance(
            evidence_authority_registry, CanonicalEd25519KeyRegistry
        ):
            raise PropertyPrebuildError("property_evidence_authority_registry_invalid")
        self._ledger_scope_digest = self._resolve_ledger_scope_digest()
        self._assert_authority_configuration()

    def _resolve_ledger_scope_digest(self) -> str:
        root = self._ledger.root
        if root is None:
            raise PropertyPrebuildError("property_prebuild_persistent_ledger_required")
        try:
            details = os.stat(root, follow_symlinks=False)
        except Exception:
            raise PropertyPrebuildError("property_prebuild_ledger_scope_invalid") from None
        if not stat.S_ISDIR(details.st_mode):
            raise PropertyPrebuildError("property_prebuild_ledger_scope_invalid")
        return _domain_digest(
            "propertyquarry.prebuild.ledger_scope.v1",
            {"device": details.st_dev, "inode": details.st_ino},
        )

    def _assert_authority_configuration(self) -> None:
        if self._ledger.root is None:
            raise PropertyPrebuildError("property_prebuild_persistent_ledger_required")
        if not self._material_store.authority_guarded_recovery:
            raise PropertyPrebuildError("property_prebuild_guarded_material_store_required")
        if self._material_store.lifecycle_authority is not self._ledger.lifecycle_authority:
            raise PropertyPrebuildError("property_prebuild_lifecycle_authority_mismatch")
        if (
            self._reconciliation_store is not None
            and (
                type(self._reconciliation_store)
                is not PropertyPrebuildReconciliationStore
                or self._reconciliation_store.lifecycle_authority
                is not self._ledger.lifecycle_authority
            )
        ):
            raise PropertyPrebuildError("property_prebuild_reconciliation_authority_mismatch")

    def _integrity(self) -> dict[str, object]:
        try:
            summary = _snapshot_mapping(
                self._ledger.integrity_summary(),
                reason="property_prebuild_ledger_integrity_invalid",
            )
        except Exception:
            raise PropertyPrebuildError("property_prebuild_ledger_integrity_invalid") from None
        if summary.get("status") != "pass" or summary.get("persistent") is not True:
            raise PropertyPrebuildError("property_prebuild_ledger_integrity_invalid")
        return summary

    @staticmethod
    def _policy_error(exc: Exception) -> PropertyPrebuildError:
        return PropertyPrebuildError(
            _POLICY_FAILURES.get(str(exc), "property_prebuild_policy_unverifiable")
        )

    @staticmethod
    def _validate_policy_projection(
        projection: Mapping[str, object], receipt: Mapping[str, object], observed_at: datetime
    ) -> None:
        trusted = _snapshot_mapping(
            projection,
            reason="property_prebuild_policy_unverifiable",
            allow_datetime=True,
        )
        if set(trusted) != _POLICY_PROJECTION_MEMBERS or trusted.get("state") != "verified":
            raise PropertyPrebuildError("property_prebuild_policy_unverifiable")
        exact = {
            "policy_path": PROPERTY_POLICY_PATH,
            "policy_id": receipt.get("policy_id"),
            "policy_digest": receipt.get("policy_digest"),
            "policy_mode": 0o600,
            "approval_ref": receipt.get("policy_approval_ref"),
            "verifier_ref": receipt.get("policy_verifier_ref"),
            "verification_receipt_digest": receipt.get(
                "policy_verification_receipt_digest"
            ),
            "evidence_digest": receipt.get("policy_evidence_digest"),
            "independent_acceptance_mode": 0o600,
            "independent_acceptance_digest": PROPERTY_AUTHORITY_ACCEPTANCE_DIGEST,
            "regular_file": True,
            "independent_acceptance_regular_file": True,
        }
        if any(trusted.get(field) != expected for field, expected in exact.items()):
            reason = (
                "property_prebuild_policy_mode_mismatched"
                if trusted.get("policy_mode") != 0o600 or trusted.get("regular_file") is not True
                else "property_prebuild_policy_digest_mismatched"
                if trusted.get("policy_digest") != receipt.get("policy_digest")
                else "property_prebuild_policy_authority_mismatch"
            )
            raise PropertyPrebuildError(reason)
        if trusted.get("source_retention_days") != 30:
            raise PropertyPrebuildError("property_prebuild_policy_authority_mismatch")
        policy_expiry = trusted.get("policy_expires_at")
        if not isinstance(policy_expiry, datetime) or policy_expiry.tzinfo is None:
            raise PropertyPrebuildError("property_prebuild_policy_unverifiable")
        if observed_at >= policy_expiry.astimezone(UTC):
            raise PropertyPrebuildError("property_prebuild_policy_expired")

    @staticmethod
    def _validate_input_authority(
        projection: Mapping[str, object], receipt: Mapping[str, object], material: GovernedSpatialExecutionMaterialV1,
        observed_at: datetime,
    ) -> None:
        trusted = _snapshot_mapping(
            projection,
            reason="property_prebuild_input_authority_invalid",
        )
        if set(trusted) != _INPUT_AUTHORITY_MEMBERS or trusted.get("state") != "verified":
            raise PropertyPrebuildError("property_prebuild_input_authority_invalid")
        expected = {
            "contract_name": "ea.governed_spatial_property_input_authority.v1",
            "contract_version": "1.0.0",
            "request_digest": material.request_digest,
            "source_packet_digest": material.source_packet_digest,
            "source_packet_created_at": material.source_packet_created_at,
            "style_snapshot_digest": material.style_snapshot_digest,
            "asset_bindings_digest": receipt.get("asset_bindings_digest"),
            "source_authority_receipt_digest": receipt.get(
                "source_authority_receipt_digest"
            ),
            "style_registry_receipt_digest": receipt.get(
                "style_registry_receipt_digest"
            ),
            "asset_authority_receipt_digest": receipt.get(
                "asset_authority_receipt_digest"
            ),
            "input_authority_digest": receipt.get("input_authority_digest"),
            "verified_at": receipt.get("input_authority_verified_at"),
            "expires_at": receipt.get("input_authority_expires_at"),
        }
        if any(trusted.get(field) != value for field, value in expected.items()):
            raise PropertyPrebuildError("property_prebuild_input_authority_mismatch")
        verified = _as_datetime(trusted["verified_at"])
        expires = _as_datetime(trusted["expires_at"])
        if not verified <= observed_at < expires:
            raise PropertyPrebuildError("property_prebuild_input_authority_stale")

    def _verify_authority_receipt(
        self,
        *,
        receipt: Mapping[str, object],
        expected_members: frozenset[str],
        contract_name: str,
        authority: PropertyEvidenceAuthority | None,
        expected: Mapping[str, object],
        current: datetime,
        compose_receipt: Mapping[str, object],
        reason: str,
    ) -> str:
        if authority is None or self._evidence_authority_registry is None:
            raise PropertyPrebuildError(f"{reason}_unavailable")
        trusted = _snapshot_mapping(receipt, reason=f"{reason}_invalid")
        if set(trusted) != expected_members:
            raise PropertyPrebuildError(f"{reason}_invalid")
        exact = {
            "contract_name": contract_name,
            "contract_version": "1.0.0",
            "issuer": authority.issuer,
            "environment": authority.environment,
            "authority_identity_digest": authority.identity_digest,
            "authority_receipt_digest": authority.authority_receipt_digest,
            "ledger_scope_digest": self._ledger_scope_digest,
            **dict(expected),
        }
        if any(trusted.get(field) != value for field, value in exact.items()):
            raise PropertyPrebuildError(f"{reason}_binding_mismatch")
        try:
            verification = verify_signed_envelope(
                trusted,
                self._evidence_authority_registry,
                observed_at=current,
                maximum_receipt_age=timedelta(
                    seconds=authority.maximum_age_seconds
                ),
            )
            key_record = self._evidence_authority_registry.resolve(
                *verification.key_identity
            )
        except SpatialCryptoError:
            raise PropertyPrebuildError(f"{reason}_unverifiable") from None
        except Exception:
            raise PropertyPrebuildError(f"{reason}_unverifiable") from None
        if (
            key_record.issuer != authority.issuer
            or key_record.environment != authority.environment
            or key_record.key_ref != authority.key_ref
            or key_record.key_epoch != authority.key_epoch
        ):
            raise PropertyPrebuildError(f"{reason}_signer_mismatch")
        issued = _as_datetime(trusted.get("issued_at"), f"{reason}_chronology_invalid")
        observed = _as_datetime(
            trusted.get("observed_at"), f"{reason}_chronology_invalid"
        )
        expires = _as_datetime(
            trusted.get("expires_at"), f"{reason}_chronology_invalid"
        )
        compose_expires = _as_datetime(
            compose_receipt.get("expires_at"), f"{reason}_chronology_invalid"
        )
        retention_expires = _as_datetime(
            compose_receipt.get("retention_expires_at"),
            f"{reason}_chronology_invalid",
        )
        if (
            observed != issued
            or observed > current
            or current - observed > timedelta(seconds=authority.maximum_age_seconds)
            or not current < expires <= min(compose_expires, retention_expires)
        ):
            raise PropertyPrebuildError(f"{reason}_chronology_invalid")
        return payload_digest(trusted)

    def _authenticate_execution_evidence(
        self,
        authenticated: object,
        *,
        plan: PropertyPrebuildPlan,
        allocation: PropertyOutputAllocation,
        boundary: PropertyExecutionBoundary,
        snapshot: _GateSnapshot,
    ) -> tuple[PropertyExecutionEvidence, str]:
        if type(authenticated) is not PropertyAuthenticatedExecutionEvidence:
            raise PropertyPrebuildError("property_execution_evidence_authority_required")
        evidence = PropertyExecutionEvidence.parse(authenticated.evidence)
        payload = evidence.as_dict()
        if (
            payload["state"] != "succeeded"
            or payload["output_digest"] is None
            or self._execution_evidence_authority is None
            or payload["adapter_identity_digest"]
            != self._execution_evidence_authority.identity_digest
        ):
            raise PropertyPrebuildError("property_execution_evidence_authority_invalid")
        expected = {
            "composition_digest": snapshot.material.composition_digest,
            "plan_digest": plan.digest,
            "allocation_digest": allocation.digest,
            "execution_boundary_digest": boundary.digest,
            "execution_identity_digest": boundary["execution_identity_digest"],
            "adapter_identity_digest": payload["adapter_identity_digest"],
            "execution_evidence_digest": evidence.digest,
            "output_digest": payload["output_digest"],
            "operation_id": payload["operation_id"],
        }
        authority_digest = self._verify_authority_receipt(
            receipt=authenticated.authority_receipt(),
            expected_members=_EXECUTION_AUTHORITY_MEMBERS,
            contract_name=PROPERTY_EXECUTION_AUTHORITY_CONTRACT,
            authority=self._execution_evidence_authority,
            expected=expected,
            current=snapshot.revalidate(),
            compose_receipt=snapshot.receipt,
            reason="property_execution_evidence_authority",
        )
        return evidence, authority_digest

    def _authenticate_artifact_verification(
        self,
        authenticated: object,
        *,
        execution_evidence: PropertyExecutionEvidence,
        execution_authority_digest: str,
        candidate: PropertyArtifactCandidate,
        plan: PropertyPrebuildPlan,
        allocation: PropertyOutputAllocation,
        boundary: PropertyExecutionBoundary,
        snapshot: _GateSnapshot,
        trusted_current: datetime | None = None,
    ) -> tuple[PropertyArtifactVerificationEvidence, str]:
        if type(authenticated) is not PropertyAuthenticatedArtifactVerification:
            raise PropertyPrebuildError("property_artifact_evidence_authority_required")
        evidence = PropertyArtifactVerificationEvidence.parse(authenticated.evidence)
        evidence_payload = evidence.as_dict()
        candidate_payload = candidate.as_dict()
        execution_payload = execution_evidence.as_dict()
        decision = "accepted" if evidence_payload["state"] == "verified" else "rejected"
        if (
            candidate_payload["artifact_digest"] != execution_payload["output_digest"]
            or evidence_payload["artifact_digest"] != execution_payload["output_digest"]
            or evidence_payload["verifier_identity_digest"]
            != (
                self._artifact_evidence_authority.identity_digest
                if self._artifact_evidence_authority is not None
                else None
            )
        ):
            raise PropertyPrebuildError("property_artifact_evidence_authority_mismatch")
        expected = {
            "composition_digest": snapshot.material.composition_digest,
            "plan_digest": plan.digest,
            "allocation_digest": allocation.digest,
            "execution_boundary_digest": boundary.digest,
            "execution_identity_digest": boundary["execution_identity_digest"],
            "execution_evidence_digest": execution_evidence.digest,
            "execution_authority_receipt_digest": execution_authority_digest,
            "execution_output_digest": execution_payload["output_digest"],
            "candidate_digest": candidate.digest,
            "allocation_slot_ref": candidate_payload["allocation_slot_ref"],
            "artifact_identity_digest": candidate_payload["artifact_identity_digest"],
            "artifact_digest": candidate_payload["artifact_digest"],
            "verification_profile_digest": candidate_payload[
                "verification_profile_digest"
            ],
            "verification_evidence_digest": evidence.digest,
            "decision": decision,
        }
        authority_digest = self._verify_authority_receipt(
            receipt=authenticated.authority_receipt(),
            expected_members=_ARTIFACT_AUTHORITY_MEMBERS,
            contract_name=PROPERTY_ARTIFACT_AUTHORITY_CONTRACT,
            authority=self._artifact_evidence_authority,
            expected=expected,
            current=(
                trusted_current
                if trusted_current is not None
                else snapshot.revalidate()
            ),
            compose_receipt=snapshot.receipt,
            reason="property_artifact_evidence_authority",
        )
        if execution_authority_digest == authority_digest:
            raise PropertyPrebuildError("property_artifact_evidence_authority_mismatch")
        return evidence, authority_digest

    def _emit(self, event_type: str, snapshot: _GateSnapshot, **fields: object) -> None:
        if self._telemetry_sink is None:
            return
        event = {
            "contract_name": "propertyquarry.governed_spatial_prebuild_telemetry.v1",
            "event_type": event_type,
            "composition_digest": snapshot.material.composition_digest,
            "plan_digest": snapshot.plan.digest,
            "output_allocation_actions": 0,
            "quota_actions": 0,
            "adapter_actions": 0,
            "provider_actions": 0,
            "render_actions": 0,
            **fields,
        }
        if _contains_forbidden_material(event):
            raise PropertyPrebuildError("property_prebuild_telemetry_invalid")
        callback_error = False
        try:
            self._telemetry_sink(dict(event))
        except Exception:
            callback_error = True
        snapshot.revalidate()
        if callback_error:
            raise PropertyPrebuildError("property_prebuild_telemetry_failed")

    def _sample_time(self, previous: datetime | None = None) -> datetime:
        try:
            current = _observed(self._now())
        except Exception:
            raise PropertyPrebuildError("property_prebuild_trusted_clock_invalid") from None
        with self._clock_lock:
            floors = tuple(
                candidate
                for candidate in (previous, self._last_trusted_time)
                if candidate is not None
            )
            if floors and current < max(floors):
                raise PropertyPrebuildError("property_prebuild_trusted_clock_rollback")
            self._last_trusted_time = current
        return current

    def _guarded(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None,
        effect: Callable[[_GateSnapshot], Any],
    ) -> Any:
        if getattr(self._entry_state, "active", False):
            raise PropertyPrebuildError("property_prebuild_reentrant_call_forbidden")
        self._entry_state.active = True
        try:
            return self._guarded_once(
                selection, policy_evidence, observed_at, effect
            )
        finally:
            self._entry_state.active = False

    def _guarded_once(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None,
        effect: Callable[[_GateSnapshot], Any],
    ) -> Any:
        selected = PropertyPrebuildSelection.parse(selection)
        selected_payload = selected.as_dict()
        policy_evidence_snapshot = (
            None
            if policy_evidence is None
            else _snapshot_mapping(
                policy_evidence,
                reason="property_prebuild_policy_evidence_invalid",
            )
        )
        current = self._sample_time()
        if observed_at is not None:
            try:
                supplied_observed = _observed(observed_at)
            except Exception:
                raise PropertyPrebuildError(
                    "property_prebuild_caller_time_invalid"
                ) from None
            if supplied_observed != current:
                raise PropertyPrebuildError("property_prebuild_caller_time_mismatch")
        self._assert_authority_configuration()
        self._integrity()
        composition_digest = str(selected_payload["composition_digest"])
        try:
            receipt_candidate = self._ledger.find_composition(composition_digest)
        except Exception:
            raise PropertyPrebuildError("property_prebuild_receipt_unavailable") from None
        if receipt_candidate is None:
            raise PropertyPrebuildError("property_prebuild_receipt_not_found")
        receipt = _snapshot_mapping(
            receipt_candidate,
            reason="property_prebuild_receipt_invalid",
        )
        current = self._sample_time(current)
        if payload_digest(receipt) != selected_payload["composition_receipt_digest"]:
            raise PropertyPrebuildError("property_prebuild_receipt_digest_mismatch")
        with self._ledger.composition_privacy_lifecycle_guard(
            composition_digest
        ) as lifecycle_guard:
            verified_receipt: dict[str, object] = {}
            material: GovernedSpatialExecutionMaterialV1 | None = None

            def assert_lifecycle() -> None:
                try:
                    lifecycle_guard.assert_active(
                        composition_digest,
                        authority=self._ledger.lifecycle_authority,
                        allow_privacy=True,
                    )
                except SpatialStateError:
                    raise PropertyPrebuildError(
                        "property_prebuild_lifecycle_guard_invalid"
                    ) from None
                if lifecycle_guard.privacy_status is not None:
                    raise SpatialPrivacyError(
                        "property_prebuild_privacy_tombstone_active"
                    )
                self._integrity()
                try:
                    latest_receipt = _snapshot_mapping(
                        self._ledger.find_composition(composition_digest),
                        reason="property_prebuild_receipt_changed",
                    )
                except PropertyPrebuildError:
                    raise PropertyPrebuildError("property_prebuild_receipt_changed") from None
                if _canonical_bytes(latest_receipt) != _canonical_bytes(receipt):
                    raise PropertyPrebuildError("property_prebuild_receipt_changed")
                if self._resolve_ledger_scope_digest() != self._ledger_scope_digest:
                    raise PropertyPrebuildError("property_prebuild_ledger_scope_changed")

            def advance_time() -> datetime:
                nonlocal current
                current = self._sample_time(current)
                return current

            def validate_windows(trusted_receipt: Mapping[str, object]) -> None:
                compose_at = _as_datetime(
                    trusted_receipt.get("compose_acceptance_at")
                )
                receipt_expires = _as_datetime(trusted_receipt.get("expires_at"))
                retention_expires = _as_datetime(
                    trusted_receipt.get("retention_expires_at")
                )
                if current < compose_at:
                    raise PropertyPrebuildError("property_prebuild_clock_rollback")
                if current >= receipt_expires:
                    raise PropertyPrebuildError("property_prebuild_receipt_expired")
                if current >= retention_expires:
                    raise PropertyPrebuildError("property_prebuild_material_expired")

            def stable_mapping_callback(
                callback: Callable[[datetime], object],
                *,
                reason: str,
                allow_datetime: bool = False,
                policy_errors: bool = False,
            ) -> dict[str, object]:
                nonlocal current
                for _ in range(2):
                    before = current
                    callback_error: Exception | None = None
                    raw: object = None
                    try:
                        raw = callback(before)
                    except Exception as exc:
                        callback_error = exc
                    try:
                        snap = _snapshot_mapping(
                            raw,
                            reason=reason,
                            allow_datetime=allow_datetime,
                        )
                    except PropertyPrebuildError:
                        snap = {}
                        if callback_error is None:
                            callback_error = PropertyPrebuildError(reason)
                    after = advance_time()
                    assert_lifecycle()
                    if callback_error is not None:
                        if policy_errors:
                            raise self._policy_error(callback_error) from None
                        raise PropertyPrebuildError(reason) from None
                    if after != before:
                        continue
                    return snap
                raise PropertyPrebuildError("property_prebuild_trusted_clock_unstable")

            def verify_receipt_current() -> dict[str, object]:
                trusted = stable_mapping_callback(
                    lambda observed: self._receipt_verifier(
                        dict(receipt), observed_at=observed
                    ),
                    reason="property_prebuild_receipt_unverifiable",
                )
                if (
                    set(trusted) != _RECEIPT_MEMBERS
                    or _canonical_bytes(trusted) != _canonical_bytes(receipt)
                    or payload_digest(trusted)
                    != selected_payload["composition_receipt_digest"]
                ):
                    raise PropertyPrebuildError(
                        "property_prebuild_receipt_unverifiable"
                    )
                selection_bindings = {
                    "request_id": trusted.get("request_id"),
                    "idempotency_key": trusted.get("idempotency_key"),
                    "composition_digest": trusted.get("composition_digest"),
                    "material_identity": trusted.get("material_identity"),
                    "material_digest": trusted.get("material_digest"),
                }
                if any(
                    selected_payload.get(field) != expected
                    for field, expected in selection_bindings.items()
                ):
                    raise PropertyPrebuildError(
                        "property_prebuild_selection_binding_mismatch"
                    )
                validate_windows(trusted)
                return trusted

            def verify_policy_current(
                trusted_receipt: Mapping[str, object],
            ) -> dict[str, object]:
                projection = stable_mapping_callback(
                    lambda observed: self._policy_verifier(
                        policy_evidence_snapshot, observed_at=observed
                    ),
                    reason="property_prebuild_policy_unverifiable",
                    allow_datetime=True,
                    policy_errors=True,
                )
                self._validate_policy_projection(projection, trusted_receipt, current)
                validate_windows(trusted_receipt)
                return projection

            def verify_input_current(
                trusted_receipt: Mapping[str, object],
                trusted_material: GovernedSpatialExecutionMaterialV1,
            ) -> dict[str, object]:
                projection = stable_mapping_callback(
                    lambda observed: self._input_authority_verifier(
                        trusted_material, observed_at=observed
                    ),
                    reason="property_prebuild_input_authority_unverifiable",
                )
                self._validate_input_authority(
                    projection, trusted_receipt, trusted_material, current
                )
                validate_windows(trusted_receipt)
                return projection

            def full_revalidate() -> datetime:
                nonlocal verified_receipt
                assert_lifecycle()
                advance_time()
                trusted_receipt = verify_receipt_current()
                policy_projection = verify_policy_current(trusted_receipt)
                if material is not None:
                    _assert_receipt_material_binding(
                        trusted_receipt, material, selected
                    )
                    input_projection = verify_input_current(
                        trusted_receipt, material
                    )
                    self._validate_input_authority(
                        input_projection, trusted_receipt, material, current
                    )
                self._validate_policy_projection(
                    policy_projection, trusted_receipt, current
                )
                validate_windows(trusted_receipt)
                verified_receipt = trusted_receipt
                return current

            full_revalidate()
            try:
                loaded = self._material_store.load(
                    composition_digest, lifecycle_guard=lifecycle_guard
                )
            except SpatialMaterialStoreError as exc:
                reason = (
                    "property_prebuild_material_expired"
                    if str(exc) == "material_retention_expired"
                    else "property_prebuild_material_unavailable"
                )
                raise PropertyPrebuildError(reason) from None
            advance_time()
            assert_lifecycle()
            material = validate_property_prebuild_material(loaded)
            full_revalidate()
            plan = build_property_prebuild_plan(selected, verified_receipt, material)
            active_gate = _ActiveGate(
                composition_digest,
                self._ledger.lifecycle_authority,
                lifecycle_guard,
                full_revalidate,
                marker=_GATE_MARKER,
            )
            snapshot = _GateSnapshot(
                selected,
                verified_receipt,
                material,
                plan,
                current,
                active_gate,
                full_revalidate,
            )
            try:
                try:
                    result = effect(snapshot)
                except (PropertyPrebuildError, SpatialPrivacyError):
                    full_revalidate()
                    raise
                except Exception:
                    full_revalidate()
                    raise PropertyPrebuildError("property_prebuild_effect_failed") from None
                full_revalidate()
                return result
            finally:
                active_gate.close()

    @staticmethod
    def _exact_plan(snapshot: _GateSnapshot, supplied: PropertyPrebuildPlan | Mapping[str, object]) -> PropertyPrebuildPlan:
        try:
            parsed = PropertyPrebuildPlan.parse(supplied)
        except Exception:
            snapshot.revalidate()
            raise PropertyPrebuildError("property_prebuild_plan_invalid") from None
        if type(supplied) is not PropertyPrebuildPlan:
            snapshot.revalidate()
        if parsed.canonical_bytes() != snapshot.plan.canonical_bytes():
            raise PropertyPrebuildError("property_prebuild_plan_binding_mismatch")
        return parsed

    @staticmethod
    def _parse_contract_with_revalidation(
        snapshot: _GateSnapshot,
        value: object,
        contract: type[_CanonicalContract],
        *,
        reason: str,
    ) -> Any:
        try:
            parsed = contract.parse(value)  # type: ignore[arg-type]
        except Exception:
            snapshot.revalidate()
            raise PropertyPrebuildError(reason) from None
        if type(value) is not contract:
            snapshot.revalidate()
        return parsed

    def resolve_plan(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        *,
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None = None,
    ) -> PropertyPrebuildPlan:
        def resolve(snapshot: _GateSnapshot) -> PropertyPrebuildPlan:
            self._emit("plan_resolved", snapshot)
            return snapshot.plan

        return self._guarded(selection, policy_evidence, observed_at, resolve)

    def plan_output_allocation(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        *,
        plan: PropertyPrebuildPlan | Mapping[str, object],
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None = None,
    ) -> PropertyOutputAllocation:
        def allocate(snapshot: _GateSnapshot) -> PropertyOutputAllocation:
            exact_plan = self._exact_plan(snapshot, plan)
            candidate: object = None
            callback_failed = False
            try:
                candidate = self._allocator(exact_plan)
            except Exception:
                callback_failed = True
            snapshot.revalidate()
            if callback_failed or type(candidate) is not PropertyOutputAllocation:
                raise PropertyPrebuildError("property_output_allocation_planner_failed")
            parsed = PropertyOutputAllocation.parse(candidate)
            expected = PropertyOutputAllocation.parse(_allocation_payload(exact_plan))
            if parsed.canonical_bytes() != expected.canonical_bytes():
                raise PropertyPrebuildError("property_output_allocation_conflict")
            self._emit("allocation_planned", snapshot, allocation_digest=parsed.digest)
            return parsed

        return self._guarded(selection, policy_evidence, observed_at, allocate)

    def prepare_execution_boundary(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        *,
        plan: PropertyPrebuildPlan | Mapping[str, object],
        allocation: PropertyOutputAllocation | Mapping[str, object],
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None = None,
    ) -> PropertyExecutionBoundary:
        def prepare(snapshot: _GateSnapshot) -> PropertyExecutionBoundary:
            exact_plan = self._exact_plan(snapshot, plan)
            exact_allocation = self._parse_contract_with_revalidation(
                snapshot,
                allocation,
                PropertyOutputAllocation,
                reason="property_output_allocation_invalid",
            )
            boundary = build_property_execution_boundary(exact_plan, exact_allocation)
            self._emit(
                "execution_boundary_prepared",
                snapshot,
                allocation_digest=exact_allocation.digest,
                execution_boundary_digest=boundary.digest,
            )
            return boundary

        return self._guarded(selection, policy_evidence, observed_at, prepare)

    def verify_artifact_evidence(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        *,
        plan: PropertyPrebuildPlan | Mapping[str, object],
        allocation: PropertyOutputAllocation | Mapping[str, object],
        boundary: PropertyExecutionBoundary | Mapping[str, object],
        execution_evidence: PropertyAuthenticatedExecutionEvidence,
        candidate: PropertyArtifactCandidate | Mapping[str, object],
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None = None,
    ) -> PropertyAuthenticatedArtifactVerification:
        def verify(snapshot: _GateSnapshot) -> PropertyAuthenticatedArtifactVerification:
            if self._artifact_verifier is None:
                raise PropertyPrebuildError("property_artifact_verifier_unavailable")
            exact_plan = self._exact_plan(snapshot, plan)
            exact_allocation = self._parse_contract_with_revalidation(
                snapshot,
                allocation,
                PropertyOutputAllocation,
                reason="property_output_allocation_invalid",
            )
            expected_allocation = PropertyOutputAllocation.parse(
                _allocation_payload(exact_plan)
            )
            if exact_allocation.canonical_bytes() != expected_allocation.canonical_bytes():
                raise PropertyPrebuildError("property_output_allocation_binding_mismatch")
            exact_boundary = self._parse_contract_with_revalidation(
                snapshot,
                boundary,
                PropertyExecutionBoundary,
                reason="property_execution_boundary_invalid",
            )
            expected_boundary = build_property_execution_boundary(
                exact_plan, exact_allocation
            )
            if exact_boundary.canonical_bytes() != expected_boundary.canonical_bytes():
                raise PropertyPrebuildError("property_execution_boundary_binding_mismatch")
            evidence, execution_authority_digest = self._authenticate_execution_evidence(
                execution_evidence,
                plan=exact_plan,
                allocation=exact_allocation,
                boundary=exact_boundary,
                snapshot=snapshot,
            )
            evidence_payload = evidence.as_dict()
            if (
                evidence_payload["execution_identity_digest"]
                != exact_boundary["execution_identity_digest"]
                or evidence_payload["execution_boundary_digest"] != exact_boundary.digest
                or evidence_payload["plan_digest"] != exact_plan.digest
                or evidence_payload["allocation_digest"] != exact_allocation.digest
            ):
                raise PropertyPrebuildError("property_execution_evidence_binding_mismatch")
            artifact = self._parse_contract_with_revalidation(
                snapshot,
                candidate,
                PropertyArtifactCandidate,
                reason="property_artifact_candidate_invalid",
            )
            artifact_payload = artifact.as_dict()
            allocation_slots = exact_allocation.as_dict().get("slots")
            if not isinstance(allocation_slots, list) or artifact_payload[
                "allocation_slot_ref"
            ] not in {
                slot.get("slot_ref")
                for slot in allocation_slots
                if isinstance(slot, Mapping)
            }:
                raise PropertyPrebuildError(
                    "property_artifact_candidate_allocation_slot_mismatch"
                )
            expected_candidate = build_property_artifact_candidate(
                boundary=exact_boundary,
                execution_evidence=evidence,
                allocation_slot_ref=str(artifact_payload["allocation_slot_ref"]),
                artifact_ref=str(artifact_payload["artifact_ref"]),
                artifact_digest=str(artifact_payload["artifact_digest"]),
                verification_profile_digest=str(
                    artifact_payload["verification_profile_digest"]
                ),
            )
            if artifact.canonical_bytes() != expected_candidate.canonical_bytes():
                raise PropertyPrebuildError("property_artifact_candidate_binding_mismatch")
            authenticated_result: object = None
            callback_failed = False
            verifier_observed = snapshot.revalidate()
            try:
                authenticated_result = self._artifact_verifier(
                    artifact, observed_at=verifier_observed
                )
            except Exception:
                callback_failed = True
            post_verifier_current = snapshot.revalidate()
            if callback_failed or type(authenticated_result) is not (
                PropertyAuthenticatedArtifactVerification
            ):
                raise PropertyPrebuildError("property_artifact_verifier_failed")
            result = PropertyArtifactVerificationEvidence.parse(
                authenticated_result.evidence
            )
            result_payload = result.as_dict()
            expected_bindings = {
                "plan_digest": exact_plan.digest,
                "allocation_digest": exact_allocation.digest,
                "execution_identity_digest": exact_boundary[
                    "execution_identity_digest"
                ],
                "execution_evidence_digest": evidence.digest,
                "artifact_identity_digest": artifact_payload[
                    "artifact_identity_digest"
                ],
                "artifact_digest": artifact_payload["artifact_digest"],
                "verification_profile_digest": artifact_payload[
                    "verification_profile_digest"
                ],
                "verified_at": utc_iso(verifier_observed),
            }
            if any(
                result_payload.get(field) != expected
                for field, expected in expected_bindings.items()
            ):
                raise PropertyPrebuildError("property_artifact_verifier_binding_mismatch")
            authenticated_evidence, _ = self._authenticate_artifact_verification(
                authenticated_result,
                execution_evidence=evidence,
                execution_authority_digest=execution_authority_digest,
                candidate=artifact,
                plan=exact_plan,
                allocation=exact_allocation,
                boundary=exact_boundary,
                snapshot=snapshot,
                trusted_current=post_verifier_current,
            )
            if authenticated_evidence.canonical_bytes() != result.canonical_bytes():
                raise PropertyPrebuildError("property_artifact_verifier_binding_mismatch")
            event_type = (
                "artifact_evidence_verified"
                if result_payload["state"] == "verified"
                else "artifact_evidence_rejected"
            )
            self._emit(
                event_type,
                snapshot,
                verification_digest=result.digest,
            )
            return authenticated_result

        return self._guarded(selection, policy_evidence, observed_at, verify)

    def reconcile(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        *,
        reconciliation_key: str,
        plan: PropertyPrebuildPlan | Mapping[str, object],
        allocation: PropertyOutputAllocation | Mapping[str, object],
        boundary: PropertyExecutionBoundary | Mapping[str, object],
        state: ReconciliationState,
        outcome_digest: str | None = None,
        artifact_identity_digest: str | None = None,
        verification_digest: str | None = None,
        execution_evidence: PropertyAuthenticatedExecutionEvidence | None = None,
        verification_evidence: PropertyAuthenticatedArtifactVerification | None = None,
        candidate: PropertyArtifactCandidate | Mapping[str, object] | None = None,
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None = None,
    ) -> PropertyReconciliationAppendResult:
        def append(snapshot: _GateSnapshot) -> PropertyReconciliationAppendResult:
            if self._reconciliation_store is None:
                raise PropertyPrebuildError("property_reconciliation_store_unavailable")
            exact_plan = self._exact_plan(snapshot, plan)
            exact_allocation = self._parse_contract_with_revalidation(
                snapshot,
                allocation,
                PropertyOutputAllocation,
                reason="property_output_allocation_invalid",
            )
            if exact_allocation.canonical_bytes() != PropertyOutputAllocation.parse(
                _allocation_payload(exact_plan)
            ).canonical_bytes():
                raise PropertyPrebuildError("property_output_allocation_binding_mismatch")
            exact_boundary = self._parse_contract_with_revalidation(
                snapshot,
                boundary,
                PropertyExecutionBoundary,
                reason="property_execution_boundary_invalid",
            )
            expected_boundary = build_property_execution_boundary(
                exact_plan, exact_allocation
            )
            if exact_boundary.canonical_bytes() != expected_boundary.canonical_bytes():
                raise PropertyPrebuildError("property_execution_boundary_binding_mismatch")
            resolved_outcome = outcome_digest
            resolved_artifact_identity = artifact_identity_digest
            resolved_verification_digest = verification_digest
            parsed_execution: PropertyExecutionEvidence | None = None
            execution_authority_digest: str | None = None
            artifact_authority_digest: str | None = None
            if execution_evidence is not None:
                parsed_execution, execution_authority_digest = (
                    self._authenticate_execution_evidence(
                        execution_evidence,
                        plan=exact_plan,
                        allocation=exact_allocation,
                        boundary=exact_boundary,
                        snapshot=snapshot,
                    )
                )
                execution_payload = parsed_execution.as_dict()
                if (
                    execution_payload["execution_identity_digest"]
                    != exact_boundary["execution_identity_digest"]
                    or execution_payload["execution_boundary_digest"]
                    != exact_boundary.digest
                    or execution_payload["plan_digest"] != exact_plan.digest
                    or execution_payload["allocation_digest"]
                    != exact_allocation.digest
                ):
                    raise PropertyPrebuildError(
                        "property_reconciliation_execution_evidence_mismatch"
                    )
            if state == "execution_succeeded":
                if (
                    parsed_execution is None
                    or parsed_execution["state"] != "succeeded"
                    or resolved_outcome != parsed_execution.digest
                ):
                    raise PropertyPrebuildError(
                        "property_reconciliation_execution_evidence_required"
                    )
            elif state == "artifact_verified":
                if (
                    parsed_execution is None
                    or execution_authority_digest is None
                    or verification_evidence is None
                    or candidate is None
                ):
                    raise PropertyPrebuildError(
                        "property_reconciliation_artifact_evidence_required"
                    )
                parsed_candidate = self._parse_contract_with_revalidation(
                    snapshot,
                    candidate,
                    PropertyArtifactCandidate,
                    reason="property_artifact_candidate_invalid",
                )
                candidate_payload = parsed_candidate.as_dict()
                expected_candidate = build_property_artifact_candidate(
                    boundary=exact_boundary,
                    execution_evidence=parsed_execution,
                    allocation_slot_ref=str(candidate_payload["allocation_slot_ref"]),
                    artifact_ref=str(candidate_payload["artifact_ref"]),
                    artifact_digest=str(candidate_payload["artifact_digest"]),
                    verification_profile_digest=str(
                        candidate_payload["verification_profile_digest"]
                    ),
                )
                if (
                    parsed_candidate.canonical_bytes()
                    != expected_candidate.canonical_bytes()
                ):
                    raise PropertyPrebuildError(
                        "property_reconciliation_artifact_candidate_mismatch"
                    )
                parsed_verification, artifact_authority_digest = (
                    self._authenticate_artifact_verification(
                        verification_evidence,
                        execution_evidence=parsed_execution,
                        execution_authority_digest=execution_authority_digest,
                        candidate=parsed_candidate,
                        plan=exact_plan,
                        allocation=exact_allocation,
                        boundary=exact_boundary,
                        snapshot=snapshot,
                    )
                )
                verification_payload = parsed_verification.as_dict()
                if (
                    parsed_execution["state"] != "succeeded"
                    or verification_payload["state"] != "verified"
                    or verification_payload["plan_digest"] != exact_plan.digest
                    or verification_payload["allocation_digest"]
                    != exact_allocation.digest
                    or verification_payload["execution_identity_digest"]
                    != exact_boundary["execution_identity_digest"]
                    or verification_payload["execution_evidence_digest"]
                    != parsed_execution.digest
                    or verification_payload["artifact_digest"]
                    != parsed_execution["output_digest"]
                    or verification_payload["artifact_digest"]
                    != candidate_payload["artifact_digest"]
                    or resolved_outcome != parsed_verification.digest
                    or resolved_verification_digest != parsed_verification.digest
                    or resolved_artifact_identity
                    != verification_payload["artifact_identity_digest"]
                ):
                    raise PropertyPrebuildError(
                        "property_reconciliation_artifact_evidence_mismatch"
                    )
            elif (
                execution_evidence is not None
                or verification_evidence is not None
                or candidate is not None
            ):
                raise PropertyPrebuildError(
                    "property_reconciliation_evidence_not_applicable"
                )
            plan_payload = exact_plan.as_dict()
            self._emit(
                "reconciliation_write_authorized",
                snapshot,
                reconciliation_state=state,
            )
            recorded_at = snapshot.revalidate()
            result = self._reconciliation_store.append_guarded(
                gate=snapshot.gate,
                scope_digest=snapshot.material.composition_digest,
                reconciliation_key=reconciliation_key,
                bindings={
                    "ledger_scope_digest": self._ledger_scope_digest,
                    "composition_digest": snapshot.material.composition_digest,
                    "plan_digest": exact_plan.digest,
                    "allocation_digest": exact_allocation.digest,
                    "execution_boundary_digest": exact_boundary.digest,
                    "execution_identity_digest": exact_boundary[
                        "execution_identity_digest"
                    ],
                    "retention_anchor": plan_payload["retention_anchor"],
                    "retention_expires_at": plan_payload["retention_expires_at"],
                },
                state=state,
                outcome_digest=resolved_outcome,
                artifact_identity_digest=resolved_artifact_identity,
                verification_digest=resolved_verification_digest,
                execution_authority_receipt_digest=execution_authority_digest,
                artifact_authority_receipt_digest=artifact_authority_digest,
                recorded_at=recorded_at,
            )
            return result

        return self._guarded(selection, policy_evidence, observed_at, append)

    def reconciliation_history(
        self,
        selection: PropertyPrebuildSelection | Mapping[str, object],
        *,
        reconciliation_key: str,
        policy_evidence: Mapping[str, object] | None,
        observed_at: datetime | None = None,
    ) -> tuple[PropertyReconciliationRecord, ...]:
        def read(snapshot: _GateSnapshot) -> tuple[PropertyReconciliationRecord, ...]:
            if self._reconciliation_store is None:
                raise PropertyPrebuildError("property_reconciliation_store_unavailable")
            records = self._reconciliation_store._history_without_effects(
                gate=snapshot.gate,
                key=reconciliation_key,
                ledger_scope_digest=self._ledger_scope_digest,
                composition_digest=snapshot.material.composition_digest,
                plan_digest=snapshot.plan.digest,
            )
            return records

        return self._guarded(selection, policy_evidence, observed_at, read)
