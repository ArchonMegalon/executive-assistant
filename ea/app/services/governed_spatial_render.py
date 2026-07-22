from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Literal, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from pydantic import BaseModel, ConfigDict, ValidationError

from app.services.governed_spatial_contract import (
    BUILD_AUTHORIZATION_SCHEMA,
    REQUEST_CONTRACT_NAME as CONTRACT_REQUEST_NAME,
    SOURCE_PACKET_CONTRACT_NAME as CONTRACT_SOURCE_NAME,
    GovernedSpatialBuildAuthorization,
    GovernedSpatialRenderRequestV1,
    GovernedSpatialSourcePacketV1,
    bounded_sha256,
    normalized_request_material,
    normalize_compatibility_numbers,
    parse_raw_json,
    validate_capability_quota_evidence_semantics,
)
from app.services.governed_spatial_crypto import (
    Ed25519EnvelopeSigner,
    Ed25519KeyRecord as CanonicalEd25519KeyRecord,
    Ed25519KeyRegistry as CanonicalEd25519KeyRegistry,
    SignatureVerificationError,
    SpatialCryptoError,
    decode_ed25519_signature,
    encode_ed25519_signature,
    public_key_fingerprint,
    sign_envelope,
    verify_signed_envelope,
)
from app.services.governed_spatial_execution import (
    GovernedSpatialAssetBindingV1,
    GovernedSpatialExecutionMaterialV1,
    GovernedSpatialStyleSnapshotV1,
    SpatialExecutionContractError,
    SpatialExecutionMaterialStore,
    fixed_material_retention_expiry,
    material_digest as execution_material_digest,
    validate_style_snapshot_time,
)
from app.services.governed_spatial_prebuild import (
    PropertyArtifactEvidenceVerifier,
    PropertyOutputAllocationPlanner,
    PropertyPrebuildCoordinator,
    PropertyPrebuildReconciliationStore,
    validate_property_prebuild_material,
    validate_property_prebuild_receipt_material,
)
from app.services.governed_spatial_state import (
    AUDIT_ONLY_STATE,
    GENERIC_BLOCKED_STATE,
    DurableSpatialLedger,
    SpatialIdempotencyConflict,
    SpatialPrivacyError,
    SpatialStateError,
    SpatialTransitionError,
    authorization_binding_digest,
    payload_digest,
    utc_iso,
)


REQUEST_CONTRACT_NAME = CONTRACT_REQUEST_NAME
SOURCE_PACKET_CONTRACT_NAME = CONTRACT_SOURCE_NAME
COMPOSITION_RECEIPT_CONTRACT_NAME = "ea.governed_spatial_render_composition.v1"
BUILD_RECEIPT_CONTRACT_NAME = "ea.governed_spatial_render_build_receipt.v1"
PRODUCT_PROJECTION_CONTRACT_NAME = "ea.governed_spatial_render_product_projection.v1"
CAPABILITY_INDEX_CONTRACT_NAME = "ea.governed_spatial_capability_index.v1"
DESIGN_AUTHORITY_STATUS = "accepted"
ORCHESTRATION_LANE = "ea_governed_render"
PROPERTY_COMPOSITION_RECEIPT_CONTRACT_NAME = "ea.governed_spatial_property_composition.v1"
PROPERTY_COMPOSITION_RECEIPT_CONTRACT_VERSION = "1.0.0"
PROPERTY_POLICY_EVIDENCE_CONTRACT_NAME = (
    "propertyquarry.governed_spatial_retention_policy_evidence.v1"
)
PROPERTY_ARTIFACT_FAMILY = "propertyquarry_continuous_walkthrough"
PROPERTY_CONTENT_PROFILE = "spatial_orientation_no_encounter_fields"
PROPERTY_AUTHORIZATION_OWNER = "propertyquarry.app.product.property_tour_hosting"
PROPERTY_POLICY_ID = "propertyquarry-spatial-media-retention-v1"
PROPERTY_POLICY_PATH = (
    "/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_MEDIA_RETENTION_POLICY_V1.json"
)
PROPERTY_POLICY_DIGEST = (
    "sha256:d3b22a668f42b6073a3b5199fb6adf629f8f59bd408ebe1dff08e0028bdeac95"
)
PROPERTY_AUTHORITY_ACCEPTANCE_DIGEST = (
    "sha256:c60f63ea2791c7b9f614b72a14f0a9699572daf7030243301879830d133f0631"
)

_PROPERTY_COMPOSITION_RECEIPT_MEMBERS = frozenset(
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
_PROPERTY_RETENTION_DEADLINE_FIELDS = frozenset(
    {"rights", "consent", "takedown", "privacy"}
)

_APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPABILITY_REGISTRY_PATH = _APP_ROOT / "data" / "governed_spatial_capabilities.v1.json"
DEFAULT_STYLE_REGISTRY_PATH = _APP_ROOT / "data" / "governed_spatial_style_packs.v1.json"

_ALLOWED_ARTIFACT_KINDS = {
    "rendered_diorama",
    "interactive_tour",
    "continuous_walkthrough",
    "onboarding_vignette",
}
_ALLOWED_PURPOSES = {"inspection", "walkthrough", "encounter_preview", "first_use_gimmick"}
_ALLOWED_RATINGS = {"general", "teen_fictional_combat"}
_ALLOWED_OVERLAY_ACTIONS = {
    "advance",
    "hold_position",
    "move",
    "non_graphic_exchange",
    "retreat",
    "take_cover",
}
_ALLOWED_OVERLAY_FIELDS = {
    "beats",
    "camera_policy",
    "end_time_s",
    "gameplay_truth_ref",
    "graphic_injury",
    "kind",
    "location_anchor",
    "overlay_id",
    "participants",
    "provided_outcome",
    "start_time_s",
}
_ALLOWED_PARTICIPANT_FIELDS = {
    "actor_ref",
    "equipment_ref",
    "handedness",
    "identity_ref",
    "minor",
    "real_person",
    "role",
    "transform_track_ref",
    "wardrobe_ref",
}
_ALLOWED_BEAT_FIELDS = {
    "action",
    "actor_ref",
    "at_s",
    "location_anchor",
    "target_ref",
    "transform_ref",
}
_FORBIDDEN_OVERLAY_RULE_FIELDS = {
    "action_pool",
    "armor",
    "damage",
    "damage_track",
    "dice",
    "effect",
    "initiative",
    "initiative_order",
    "rules_result",
    "successes",
}
_SENSITIVE_KEY_PARTS = {
    "account_id",
    "api_key",
    "credential",
    "password",
    "private_url",
    "provider_name",
    "provider_task",
    "provider_url",
    "secret",
    "session_cookie",
}
_STABLE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PropertyRetentionPolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_name: Literal[
        "propertyquarry.governed_spatial_retention_policy_evidence.v1"
    ]
    policy_id: str
    approval_ref: str
    policy_digest: str
    verifier_ref: str
    verification_receipt_digest: str
    approved_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class PropertyRetentionPolicyVerification:
    policy_path: str
    policy_id: str
    policy_digest: str
    policy_mode: int
    policy_expires_at: datetime
    source_retention_days: int
    approval_ref: str
    verifier_ref: str
    verification_receipt_digest: str
    evidence_digest: str
    independent_acceptance_digest: str
    independent_acceptance_mode: int
    regular_file: bool
    independent_acceptance_regular_file: bool
    state: str = "verified"


class PropertyRetentionPolicyVerifier(Protocol):
    def __call__(
        self,
        *,
        evidence: Mapping[str, object],
        observed_at: datetime,
    ) -> PropertyRetentionPolicyVerification: ...


@dataclass(frozen=True, slots=True)
class PropertyExecutionInputAuthorityVerification:
    state: str
    request_digest: str
    source_packet_digest: str
    source_packet_created_at: datetime
    source_authority_receipt_digest: str
    style_snapshot_digest: str
    style_registry_receipt_digest: str
    asset_bindings_digest: str
    asset_authority_receipt_digest: str
    verified_at: datetime
    expires_at: datetime


class PropertyExecutionInputAuthorityVerifier(Protocol):
    def __call__(
        self,
        *,
        normalized_request: Mapping[str, object],
        normalized_source_packet: Mapping[str, object],
        style_snapshot: GovernedSpatialStyleSnapshotV1,
        asset_bindings: tuple[GovernedSpatialAssetBindingV1, ...],
        observed_at: datetime,
    ) -> PropertyExecutionInputAuthorityVerification: ...


@dataclass(frozen=True)
class Ed25519KeyRecord:
    key_ref: str
    issuer: str
    key_epoch: int
    public_key: object
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None = None
    environment: str = "test"

    def canonical(self) -> CanonicalEd25519KeyRecord:
        public_bytes = self.public_key.public_bytes_raw()
        reason_digest = payload_digest("legacy-facade-revocation") if self.revoked_at is not None else None
        return CanonicalEd25519KeyRecord(
            issuer=self.issuer,
            environment=self.environment,
            key_ref=self.key_ref,
            key_epoch=self.key_epoch,
            public_key_bytes=public_bytes,
            not_before=utc_iso(self.valid_from),
            not_after=utc_iso(self.valid_until),
            state="revoked" if self.revoked_at is not None else "active",
            revoked_at=utc_iso(self.revoked_at) if self.revoked_at is not None else None,
            revocation_reason_digest=reason_digest,
        )


class Ed25519KeyRegistry:
    def __init__(self, records: list[Ed25519KeyRecord]) -> None:
        self.canonical_registry = CanonicalEd25519KeyRegistry(record.canonical() for record in records)

    def verify(
        self,
        receipt: Mapping[str, object],
        *,
        observed_at: datetime,
        maximum_age_seconds: int,
    ) -> CanonicalEd25519KeyRecord:
        verification = verify_signed_envelope(
            receipt,
            self.canonical_registry,
            observed_at=observed_at,
            maximum_receipt_age=timedelta(seconds=maximum_age_seconds),
        )
        return self.canonical_registry.resolve(*verification.key_identity)


def sign_receipt_for_test(
    receipt: Mapping[str, object],
    *,
    private_key: object,
    key_ref: str,
    key_epoch: int,
) -> dict[str, object]:
    issued_at = _parse_iso(receipt.get("issued_at"))
    expires_at = _parse_iso(receipt.get("expires_at"))
    if issued_at is None or expires_at is None or issued_at >= expires_at:
        raise ValueError("test_receipt_chronology_invalid")
    signer = Ed25519EnvelopeSigner.from_seed(
        private_key.private_bytes_raw(),
        issuer=_clean(receipt.get("issuer")),
        environment=_clean(receipt.get("environment")),
        key_ref=key_ref,
        key_epoch=key_epoch,
        not_before=utc_iso(issued_at - timedelta(seconds=1)),
        not_after=utc_iso(expires_at + timedelta(seconds=1)),
    )
    return sign_envelope(receipt, signer)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _utc_iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_iso_strict(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[dict[str, object]]:
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [_clean(item) for item in value if _clean(item)] if isinstance(value, list) else []


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_text(value: object) -> str:
    return hashlib.sha256(_clean(value).encode("utf-8")).hexdigest()


def _stable_token(value: object) -> bool:
    return bool(_STABLE_TOKEN_RE.fullmatch(_clean(value)))


def _safe_ref(value: object) -> bool:
    normalized = _clean(value)
    return bool(normalized and " " not in normalized and "://" not in normalized and _stable_token(normalized))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _finite_number(value: object, *, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and minimum <= parsed <= maximum else None


def _exact_integer(value: object, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        return None
    return value


def _contains_sensitive_shape(value: object, *, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = _clean(key).lower()
            nested_path = f"{path}.{normalized_key}" if path else normalized_key
            if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                issues.append(f"sensitive_field:{nested_path}")
            issues.extend(_contains_sensitive_shape(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            issues.extend(_contains_sensitive_shape(nested, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        normalized = value.strip().lower()
        if "://" in normalized:
            issues.append(f"provider_or_external_url:{path or 'value'}")
    return issues


def _forbidden_rule_field_paths(value: object, *, path: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = _clean(key).lower()
            nested_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in _FORBIDDEN_OVERLAY_RULE_FIELDS:
                paths.append(nested_path)
            paths.extend(_forbidden_rule_field_paths(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_rule_field_paths(nested, path=f"{path}[{index}]"))
    return paths


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


@dataclass(frozen=True)
class ProviderPosture:
    provider_key: str
    status: str
    status_reason: str
    last_verified_at: str = ""
    proof_refs: tuple[str, ...] = ()
    quota_posture: str = "blocked"

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_key": self.provider_key,
            "status": self.status,
            "status_reason": self.status_reason,
            "last_verified_at": self.last_verified_at,
            "proof_refs": list(self.proof_refs),
            "quota_posture": self.quota_posture,
        }


class GovernedSpatialRenderReceiptStore(DurableSpatialLedger):
    pass


class GovernedSpatialRenderService:
    def __init__(
        self,
        *,
        capability_registry_path: Path = DEFAULT_CAPABILITY_REGISTRY_PATH,
        style_registry_path: Path = DEFAULT_STYLE_REGISTRY_PATH,
        provider_evidence_paths: Mapping[str, Path] | None = None,
        receipt_store: GovernedSpatialRenderReceiptStore | None = None,
        signing_private_key: object | None = None,
        signing_key_ref: str = "",
        verification_key_registry: Ed25519KeyRegistry | CanonicalEd25519KeyRegistry | None = None,
        evidence_schema_path: Path | None = None,
        evidence_schema_sha256: str = "",
        telemetry_sink: Callable[[dict[str, object]], None] | None = None,
        build_enabled: bool = False,
        evidence_max_age_hours: int = 48,
    ) -> None:
        self._capability_registry = _read_json(capability_registry_path)
        self._style_registry = _read_json(style_registry_path)
        self._provider_evidence_paths = {
            _clean(key).lower(): Path(path).resolve()
            for key, path in dict(provider_evidence_paths or {}).items()
            if _clean(key) and Path(path).is_file()
        }
        self._store = receipt_store or GovernedSpatialRenderReceiptStore()
        self._signing_private_key = signing_private_key
        self._signing_public_key = signing_private_key.public_key() if signing_private_key is not None else None
        self._signing_key_ref = _clean(signing_key_ref)
        self._verification_key_registry = verification_key_registry
        self._evidence_schema: dict[str, object] | None = None
        if evidence_schema_path is not None:
            schema_path = evidence_schema_path.resolve()
            raw_schema = schema_path.read_bytes()
            if not re.fullmatch(r"[a-f0-9]{64}", evidence_schema_sha256):
                raise ValueError("evidence_schema_expected_sha256_required")
            if hashlib.sha256(raw_schema).hexdigest() != evidence_schema_sha256:
                raise ValueError("evidence_schema_sha256_mismatch")
            import yaml

            parsed_schema = yaml.safe_load(raw_schema)
            if not isinstance(parsed_schema, dict):
                raise ValueError("evidence_schema_object_required")
            self._evidence_schema = parsed_schema
        self._telemetry_sink = telemetry_sink
        self._build_enabled = bool(build_enabled)
        self._evidence_max_age_hours = max(1, int(evidence_max_age_hours))

    def _provider_key_for_artifact(self, artifact_kind: str) -> str:
        candidates: list[str] = []
        for capability in _rows(self._capability_registry.get("capabilities")):
            if artifact_kind not in {_clean(value) for value in _strings(capability.get("artifact_kinds"))}:
                continue
            candidates.extend(_strings(capability.get("provider_candidates")))
        return next(iter(_unique(candidates)), "")

    def _emit(self, event_type: str, **fields: object) -> None:
        if self._telemetry_sink is None:
            return
        event = {
            "contract_name": "ea.governed_spatial_render_telemetry.v1",
            "event_type": event_type,
            "orchestration_lane": ORCHESTRATION_LANE,
            **fields,
        }
        if _contains_sensitive_shape(event):
            raise ValueError("telemetry_sensitive_shape_rejected")
        self._telemetry_sink(deepcopy(event))

    def verify_build_evidence(
        self,
        evidence: Mapping[str, object],
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        if self._verification_key_registry is None:
            raise ValueError("verification_key_registry_required")
        if self._evidence_schema is None:
            raise ValueError("canonical_evidence_schema_required")
        from jsonschema import Draft202012Validator, FormatChecker

        normalized = deepcopy(dict(evidence))
        errors = sorted(
            Draft202012Validator(self._evidence_schema, format_checker=FormatChecker()).iter_errors(normalized),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            path = ".".join(str(part) for part in errors[0].absolute_path) or "$"
            raise ValueError(f"signed_build_evidence_schema_invalid:{path}")
        validate_capability_quota_evidence_semantics(normalized)
        canonical_registry = getattr(
            self._verification_key_registry,
            "canonical_registry",
            self._verification_key_registry,
        )
        try:
            verify_signed_envelope(
                normalized,
                canonical_registry,
                observed_at=observed_at or _utc_now(),
                maximum_receipt_age=timedelta(hours=24),
            )
        except SignatureVerificationError as exc:
            reason = "signed_payload_digest_invalid" if exc.code == "signed_payload_digest_mismatch" else exc.code
            raise ValueError(reason) from exc
        if normalized.get("quota_posture") != "build_allowed":
            raise ValueError("signed_build_evidence_not_build_allowed")
        if _dict(normalized.get("revocation")).get("state") != "active":
            raise ValueError("signed_build_evidence_revoked")
        if _dict(normalized.get("kill_switch")).get("state") != "route_allowed":
            raise ValueError("signed_build_evidence_kill_switch_blocked")
        return normalized

    def _provider_postures(self, *, observed_at: datetime | None = None) -> dict[str, ProviderPosture]:
        now = (observed_at or _utc_now()).astimezone(UTC)
        capabilities = _rows(self._capability_registry.get("capabilities"))
        postures: dict[str, ProviderPosture] = {}
        for provider in _rows(self._capability_registry.get("providers")):
            key = _clean(provider.get("provider_key")).lower()
            if not key:
                continue
            related = [
                capability
                for capability in capabilities
                if key in {_clean(value).lower() for value in _strings(capability.get("provider_candidates"))}
            ]
            baseline = related[0] if related else {}
            postures[key] = ProviderPosture(
                key,
                _clean(baseline.get("base_status")) or "unverified",
                _clean(baseline.get("base_status_reason")) or "current_capability_evidence_missing",
                quota_posture=_clean(baseline.get("quota_posture")) or "blocked",
            )

        for key, path in self._provider_evidence_paths.items():
            if key not in postures:
                continue
            try:
                receipt = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            generated_at = _parse_iso(receipt.get("generated_at") or receipt.get("generated_at_utc"))
            age_hours = ((now - generated_at).total_seconds() / 3600.0) if generated_at is not None else None
            checks = _rows(receipt.get("checks"))
            rendered_states = [_dict(row.get("state")) for row in checks]
            rendered = next(
                (state for state in rendered_states if state.get("same_origin_frame_inspected") is True),
                {},
            )
            valid = (
                _clean(receipt.get("status")).lower() == "pass"
                and key in {_clean(item).lower() for item in _strings(receipt.get("providers"))}
                and bool(checks)
                and all(row.get("ok") is True for row in checks)
                and rendered.get("same_origin_frame_inspected") is True
                and _exact_integer(rendered.get("visible_canvas_count"), minimum=1, maximum=1_000_000) is not None
                and age_hours is not None
                and 0 <= age_hours <= self._evidence_max_age_hours
            )
            if valid:
                postures[key] = ProviderPosture(
                    key,
                    "verified",
                    f"{key}_browser_receipt_passed",
                    _utc_iso(generated_at),
                    (str(path),),
                    "audit_only",
                )
            else:
                reason = f"{key}_browser_receipt_invalid"
                if age_hours is None:
                    reason = f"{key}_browser_receipt_timestamp_missing"
                elif age_hours < 0 or age_hours > self._evidence_max_age_hours:
                    reason = f"{key}_browser_receipt_stale"
                postures[key] = ProviderPosture(
                    key,
                    "degraded",
                    reason,
                    _utc_iso(generated_at) if generated_at else "",
                    (str(path),),
                    "audit_only",
                )
        return postures

    def capability_index(self, *, observed_at: datetime | None = None) -> dict[str, object]:
        postures = self._provider_postures(observed_at=observed_at)
        capabilities: list[dict[str, object]] = []
        for source in _rows(self._capability_registry.get("capabilities")):
            row = deepcopy(source)
            candidates = [_clean(item).lower() for item in _strings(row.get("provider_candidates"))]
            candidate_postures = [postures[key] for key in candidates if key in postures]
            status = _clean(row.pop("base_status", "unverified")) or "unverified"
            reason = _clean(row.pop("base_status_reason", ""))
            last_verified_at = ""
            proof_refs: list[str] = []
            quota_posture = _clean(row.get("quota_posture")) or "blocked"
            verified = next((posture for posture in candidate_postures if posture.status == "verified"), None)
            degraded = next((posture for posture in candidate_postures if posture.status == "degraded"), None)
            if verified:
                status = verified.status
                reason = verified.status_reason
                last_verified_at = verified.last_verified_at
                proof_refs = list(verified.proof_refs)
                quota_posture = verified.quota_posture
            elif degraded:
                status = degraded.status
                reason = degraded.status_reason
                last_verified_at = degraded.last_verified_at
                proof_refs = list(degraded.proof_refs)
                quota_posture = "blocked"
            row.update(
                {
                    "orchestration_lane": ORCHESTRATION_LANE,
                    "status": status,
                    "status_reason": reason,
                    "last_verified_at": last_verified_at,
                    "proof_refs": proof_refs,
                    "quota_posture": quota_posture,
                }
            )
            capabilities.append(row)
        return {
            "contract_name": CAPABILITY_INDEX_CONTRACT_NAME,
            "contract_version": "2026-07-11-draft",
            "generated_at": _utc_iso(observed_at),
            "design_authority_status": DESIGN_AUTHORITY_STATUS,
            "orchestration_lane": ORCHESTRATION_LANE,
            "build_enabled": self._build_enabled,
            "capabilities": capabilities,
            "providers": [posture.as_dict() for posture in postures.values()],
        }

    def _style_pack(self, style_pack_id: str, product: str) -> dict[str, object] | None:
        for row in _rows(self._style_registry.get("style_packs")):
            if _clean(row.get("style_pack_id")) == style_pack_id:
                consumers = {_clean(item).lower() for item in _strings(row.get("consumer_products"))}
                return row if product in consumers else None
        return None

    @staticmethod
    def _validate_source_packet(
        request: dict[str, object],
        source_packet: dict[str, object],
        issues: list[str],
    ) -> dict[str, object]:
        if _clean(source_packet.get("contract_name")) != SOURCE_PACKET_CONTRACT_NAME:
            issues.append("source_packet_contract")
        if _clean(source_packet.get("source_packet_ref")) != _clean(request.get("source_packet_ref")):
            issues.append("source_packet_ref_mismatch")
        source_digest = _clean(source_packet.get("source_digest")).lower()
        if not _SHA256_RE.fullmatch(source_digest):
            issues.append("source_packet_digest")
        provenance_refs = _strings(source_packet.get("license_provenance_refs"))
        if not provenance_refs or not all(_safe_ref(value) for value in provenance_refs):
            issues.append("source_license_provenance")
        if _parse_iso(source_packet.get("source_retrieved_at")) is None:
            issues.append("source_retrieved_at")
        for field in ("normalized_floorplan_ref", "room_graph_ref", "walkable_mesh_ref", "portal_graph_ref"):
            if not _safe_ref(source_packet.get(field)):
                issues.append(f"source_{field}")
        scale = _finite_number(source_packet.get("scale_m_per_unit"), minimum=0.000001, maximum=1_000_000.0)
        orientation = _finite_number(source_packet.get("orientation_degrees"), minimum=0.0, maximum=359.999999)
        if scale is None:
            issues.append("source_scale")
        if orientation is None:
            issues.append("source_orientation")

        room_rows = _rows(source_packet.get("rooms"))
        room_ids = [_clean(room.get("room_id")) for room in room_rows]
        if not room_ids or any(not _stable_token(room_id) for room_id in room_ids) or len(room_ids) != len(set(room_ids)):
            issues.append("source_room_inventory")
        known_room_ids = set(room_ids)
        walkable_room_ids: set[str] = set()
        room_types: dict[str, str] = {}
        for room in room_rows:
            room_id = _clean(room.get("room_id"))
            room_type = _clean(room.get("room_type")).lower()
            room_types[room_id] = room_type
            if room.get("walkable") is True:
                walkable_room_ids.add(room_id)
            if not _stable_token(room_type):
                issues.append(f"source_room_type:{room_id}")
            for field in ("boundary_ref", "geometry_anchor_ref"):
                if not _safe_ref(room.get(field)):
                    issues.append(f"source_room_{field}:{room_id}")
            texture_refs = _strings(room.get("texture_anchor_refs"))
            if not texture_refs or not all(_safe_ref(value) for value in texture_refs):
                issues.append(f"source_room_texture_anchors:{room_id}")
            ceiling_height = _finite_number(room.get("ceiling_height_m"), minimum=1.8, maximum=10.0)
            if ceiling_height is None:
                issues.append(f"source_room_ceiling_height:{room_id}")
            if room_type in {"balcony", "terrace"}:
                if _clean(room.get("exterior_classification")) != room_type:
                    issues.append(f"source_exterior_classification:{room_id}")
                if not isinstance(room.get("accessible"), bool):
                    issues.append(f"source_exterior_accessibility:{room_id}")

        raw_assignments = source_packet.get("source_media_assignments")
        assignments = _rows(raw_assignments)
        if not isinstance(raw_assignments, list) or len(assignments) != len(raw_assignments):
            issues.append("source_media_assignments")
        for index, assignment in enumerate(assignments):
            if not _safe_ref(assignment.get("media_ref")):
                issues.append(f"source_media_assignment_ref:{index}")
            if _clean(assignment.get("room_id")) not in set(room_ids):
                issues.append(f"source_media_assignment_room:{index}")
            confidence = _finite_number(assignment.get("confidence"), minimum=0.0, maximum=1.0)
            if confidence is None:
                issues.append(f"source_media_assignment_confidence:{index}")

        raw_inaccessible_rooms = source_packet.get("inaccessible_rooms")
        inaccessible_rooms = _rows(raw_inaccessible_rooms)
        if not isinstance(raw_inaccessible_rooms, list) or len(inaccessible_rooms) != len(raw_inaccessible_rooms):
            issues.append("source_inaccessible_rooms")
        inaccessible_room_ids: list[str] = []
        for index, inaccessible in enumerate(inaccessible_rooms):
            room_id = _clean(inaccessible.get("room_id"))
            inaccessible_room_ids.append(room_id)
            if not _stable_token(inaccessible.get("reason")):
                issues.append(f"source_inaccessible_reason:{index}")
            if not _safe_ref(inaccessible.get("provenance_ref")):
                issues.append(f"source_inaccessible_provenance:{index}")
        expected_inaccessible = {
            _clean(room.get("room_id")) for room in room_rows if room.get("walkable") is not True
        }
        if len(inaccessible_room_ids) != len(set(inaccessible_room_ids)) or set(inaccessible_room_ids) != expected_inaccessible:
            issues.append("source_inaccessible_room_inventory")

        raw_route_exclusions = source_packet.get("route_exclusions")
        route_exclusions = _rows(raw_route_exclusions)
        if not isinstance(raw_route_exclusions, list) or len(route_exclusions) != len(raw_route_exclusions):
            issues.append("source_route_exclusions")
        declared_route_exclusions: set[str] = set()
        for index, exclusion in enumerate(route_exclusions):
            room_id = _clean(exclusion.get("room_id"))
            if room_id not in walkable_room_ids or room_id in declared_route_exclusions:
                issues.append(f"source_route_exclusion_room:{index}")
            if not _stable_token(exclusion.get("reason")):
                issues.append(f"source_route_exclusion_reason:{index}")
            if not _safe_ref(exclusion.get("authorization_ref")):
                issues.append(f"source_route_exclusion_authorization:{index}")
            declared_route_exclusions.add(room_id)

        graph: dict[str, set[str]] = {room_id: set() for room_id in walkable_room_ids}
        portal_ids: set[str] = set()
        portal_edges: set[tuple[str, str]] = set()
        for portal in _rows(source_packet.get("portals")):
            portal_id = _clean(portal.get("portal_id"))
            left = _clean(portal.get("from_room_id"))
            right = _clean(portal.get("to_room_id"))
            if not _stable_token(portal_id) or portal_id in portal_ids:
                issues.append("source_portal_inventory")
                continue
            portal_ids.add(portal_id)
            if left == right:
                issues.append("source_portal_self_edge")
                continue
            if left not in known_room_ids or right not in known_room_ids or portal.get("walkable") is not True:
                issues.append(f"source_portal_invalid:{portal_id}")
                continue
            if left in walkable_room_ids and right in walkable_room_ids:
                graph[left].add(right)
                graph[right].add(left)
                portal_edges.add(tuple(sorted((left, right))))

        raw_source_route = source_packet.get("route_room_ids")
        source_route = _strings(raw_source_route)
        if not isinstance(raw_source_route, list) or len(source_route) != len(raw_source_route):
            issues.append("source_route_room_ids_shape")
        if not source_route or set(source_route) != walkable_room_ids:
            issues.append("source_route_rooms_not_full_walkable_set")
        if len(source_route) > 2 * len(walkable_room_ids) - 1:
            issues.append("source_route_visit_count_exceeds_2n_minus_1")
        if any(left == right for left, right in zip(source_route, source_route[1:])):
            issues.append("source_route_consecutive_duplicate")
        if any(tuple(sorted((left, right))) not in portal_edges for left, right in zip(source_route, source_route[1:])):
            issues.append("source_route_transition_not_in_portal_truth")
        return {
            "source_digest": source_digest,
            "room_ids": room_ids,
            "room_types": room_types,
            "walkable_room_ids": sorted(walkable_room_ids),
            "declared_route_exclusion_ids": sorted(declared_route_exclusions),
            "graph": graph,
            "portal_edges": portal_edges,
            "route_room_ids": source_route,
            "existing_artifacts": _dict(source_packet.get("existing_artifacts")),
        }

    @staticmethod
    def _validate_continuous_route(
        spatial_plan: dict[str, object],
        source_context: dict[str, object],
        issues: list[str],
    ) -> dict[str, object]:
        raw_required = spatial_plan.get("required_room_ids")
        raw_request_route = spatial_plan.get("route_room_ids")
        required = _strings(raw_required)
        source_route = _strings(source_context.get("route_room_ids"))
        request_route_declared = "route_room_ids" in spatial_plan
        request_route = _strings(raw_request_route) if request_route_declared else list(source_route)
        walkable = set(_strings(source_context.get("walkable_room_ids")))
        declared_exclusions = set(_strings(source_context.get("declared_route_exclusion_ids")))
        if (
            not isinstance(raw_required, list)
            or len(required) != len(raw_required)
            or not required
            or len(required) != len(set(required))
        ):
            issues.append("required_room_ids")
        if set(required) != walkable:
            issues.append("required_room_inventory_mismatch")
        if declared_exclusions:
            issues.append("flagship_route_exclusions_not_allowed")
        if any(room_id not in walkable for room_id in required):
            issues.append("required_room_not_walkable")
        if (
            (request_route_declared and not isinstance(raw_request_route, list))
            or (request_route_declared and len(request_route) != len(raw_request_route))
            or not request_route
            or any(room_id not in walkable for room_id in request_route)
        ):
            issues.append("route_room_ids")
        if set(request_route) != set(required):
            issues.append("request_route_rooms_not_required_room_set")
        if set(required).difference(request_route):
            issues.append("required_room_coverage")
        if request_route_declared and request_route != source_route:
            issues.append("request_source_route_sequence_mismatch")
        if len(request_route) > 2 * len(required) - 1:
            issues.append("route_visit_count_exceeds_2n_minus_1")
        if any(left == right for left, right in zip(request_route, request_route[1:])):
            issues.append("route_consecutive_duplicate")
        if _clean(spatial_plan.get("route_policy")) != "continuous_all_walkable_rooms":
            issues.append("continuous_route_policy")
        route_revisit_count = len(request_route) - len(set(request_route))
        if spatial_plan.get("allow_revisit") is not (route_revisit_count > 0):
            issues.append("route_revisit_flag_mismatch")

        source_portals = source_context.get("portal_edges")
        source_portal_edges = source_portals if isinstance(source_portals, set) else set()
        raw_request_portals = spatial_plan.get("portal_edges")
        request_portals_declared = "portal_edges" in spatial_plan
        request_portal_rows = _rows(raw_request_portals) if request_portals_declared else []
        if request_portals_declared and (
            not isinstance(raw_request_portals, list) or len(request_portal_rows) != len(raw_request_portals)
        ):
            issues.append("request_portal_inventory")
        request_portal_edges: set[tuple[str, str]] = (
            set() if request_portals_declared else set(source_portal_edges)
        )
        for edge in request_portal_rows:
            left = _clean(edge.get("from_room_id"))
            right = _clean(edge.get("to_room_id"))
            identity = tuple(sorted((left, right)))
            if (
                not _stable_token(left)
                or not _stable_token(right)
                or left == right
                or left not in walkable
                or right not in walkable
                or identity in request_portal_edges
            ):
                issues.append("request_portal_inventory")
                continue
            request_portal_edges.add(identity)
            if identity not in source_portal_edges:
                issues.append("request_portal_not_in_source_truth")
        if request_portals_declared and any(
            tuple(sorted((left, right))) not in request_portal_edges
            for left, right in zip(request_route, request_route[1:])
        ):
            issues.append("route_portal_transition_not_declared")

        graph = source_context.get("graph")
        invalid_transition_count = 0
        if isinstance(graph, dict):
            for left, right in zip(request_route, request_route[1:]):
                if right not in graph.get(left, set()):
                    invalid_transition_count += 1
            if invalid_transition_count:
                issues.append("route_portal_transition_invalid")
            if required:
                start = request_route[0] if request_route else required[0]
                visited: set[str] = set()
                pending: deque[str] = deque([start])
                while pending:
                    current = pending.popleft()
                    if current in visited:
                        continue
                    visited.add(current)
                    pending.extend(value for value in graph.get(current, set()) if value not in visited)
                if set(required).difference(visited):
                    issues.append("required_room_graph_disconnected")
        covered = len(set(required).intersection(request_route))
        return {
            "required_room_count": len(required),
            "covered_room_count": covered,
            "room_coverage_percent": round((covered / len(required) * 100.0) if required else 0.0, 3),
            "route_visit_count": len(request_route),
            "route_revisit_count": route_revisit_count,
            "route_transition_count": max(0, len(request_route) - 1),
            "portal_valid_transition_count": max(0, len(request_route) - 1 - invalid_transition_count),
            "invalid_route_transition_count": invalid_transition_count,
            "cut_count": invalid_transition_count,
            "teleport_count": invalid_transition_count,
        }

    @staticmethod
    def _validate_overlays(
        overlays: list[dict[str, object]],
        *,
        product: str,
        content_policy: dict[str, object],
        issues: list[str],
    ) -> dict[str, object]:
        overlay_ids: set[str] = set()
        for overlay in overlays:
            overlay_id = _clean(overlay.get("overlay_id"))
            if not _stable_token(overlay_id) or overlay_id in overlay_ids:
                issues.append("scene_overlay_id")
            overlay_ids.add(overlay_id)
            if _clean(overlay.get("kind")) != "fictional_combat_choreography":
                issues.append(f"scene_overlay_kind:{overlay_id}")
            for path in _forbidden_rule_field_paths(overlay):
                issues.append(f"scene_overlay_rules_truth_forbidden:{overlay_id}:{path}")
            for field in sorted(set(overlay).difference(_ALLOWED_OVERLAY_FIELDS)):
                issues.append(f"scene_overlay_field_not_allowed:{overlay_id}:{_clean(field)}")
            for field in ("gameplay_truth_ref", "provided_outcome", "location_anchor"):
                if not _safe_ref(overlay.get(field)):
                    issues.append(f"scene_overlay_{field}:{overlay_id}")
            if overlay.get("graphic_injury") is not False:
                issues.append(f"scene_overlay_graphic_injury:{overlay_id}")
            if _clean(overlay.get("camera_policy")) != "continuous_witness_path":
                issues.append(f"scene_overlay_camera_policy:{overlay_id}")

            participants = _rows(overlay.get("participants"))
            raw_participants = overlay.get("participants")
            if (
                not isinstance(raw_participants, list)
                or len(participants) != len(raw_participants)
                or not participants
                or any(not _safe_ref(row.get("actor_ref")) for row in participants)
            ):
                issues.append(f"scene_overlay_participants:{overlay_id}")
            if any(row.get("minor") is True or row.get("real_person") is True for row in participants):
                issues.append(f"scene_overlay_participant_policy:{overlay_id}")
            for index, participant in enumerate(participants):
                for field in sorted(set(participant).difference(_ALLOWED_PARTICIPANT_FIELDS)):
                    issues.append(
                        f"scene_overlay_participant_field_not_allowed:{overlay_id}:participants[{index}].{_clean(field)}"
                    )
                for field in ("identity_ref", "wardrobe_ref", "equipment_ref", "transform_track_ref"):
                    if field in participant and not _safe_ref(participant.get(field)):
                        issues.append(
                            f"scene_overlay_participant_ref_invalid:{overlay_id}:participants[{index}].{field}"
                        )
                for field in ("role", "handedness"):
                    if field in participant and not _stable_token(participant.get(field)):
                        issues.append(
                            f"scene_overlay_participant_value_invalid:{overlay_id}:participants[{index}].{field}"
                        )
            participant_refs = {_clean(row.get("actor_ref")) for row in participants}
            start_time = _finite_number(overlay.get("start_time_s"), minimum=0.0, maximum=86_400.0)
            end_time = _finite_number(overlay.get("end_time_s"), minimum=0.0, maximum=86_400.0)
            if start_time is None or end_time is None or end_time <= start_time:
                issues.append(f"scene_overlay_window:{overlay_id}")
                start_time = -1.0
                end_time = -1.0

            beats = _rows(overlay.get("beats"))
            raw_beats = overlay.get("beats")
            if not isinstance(raw_beats, list) or len(beats) != len(raw_beats) or not beats:
                issues.append(f"scene_overlay_beats:{overlay_id}")
            previous_time = -1.0
            for index, beat in enumerate(beats):
                for field in sorted(set(beat).difference(_ALLOWED_BEAT_FIELDS)):
                    issues.append(f"scene_overlay_beat_field_not_allowed:{overlay_id}:beats[{index}].{_clean(field)}")
                for field in ("location_anchor", "target_ref", "transform_ref"):
                    if field in beat and not _safe_ref(beat.get(field)):
                        issues.append(f"scene_overlay_beat_ref_invalid:{overlay_id}:beats[{index}].{field}")
                if _clean(beat.get("action")) not in _ALLOWED_OVERLAY_ACTIONS:
                    issues.append(f"scene_overlay_action:{overlay_id}")
                actor_ref = _clean(beat.get("actor_ref"))
                if not _safe_ref(actor_ref):
                    issues.append(f"scene_overlay_actor_ref:{overlay_id}")
                elif actor_ref not in participant_refs:
                    issues.append(f"scene_overlay_actor_not_participant:{overlay_id}")
                at_seconds = _finite_number(beat.get("at_s"), minimum=0.0, maximum=86_400.0)
                if at_seconds is None:
                    at_seconds = -1.0
                if at_seconds < start_time or at_seconds > end_time or at_seconds < previous_time:
                    issues.append(f"scene_overlay_timing:{overlay_id}")
                previous_time = at_seconds
        if overlays:
            if _clean(content_policy.get("rating")) != "teen_fictional_combat":
                issues.append("scene_overlay_content_rating")
            if content_policy.get("graphic_injury") is not False:
                issues.append("content_policy_graphic_injury")
            if content_policy.get("real_person_likeness") is not False:
                issues.append("content_policy_real_person_likeness")
            if content_policy.get("minor_combatants") is not False:
                issues.append("content_policy_minor_combatants")
        return {
            "overlay_count": len(overlays),
            "combat_overlay_count": sum(
                1 for overlay in overlays if _clean(overlay.get("kind")) == "fictional_combat_choreography"
            ),
        }

    def _validate_request(
        self,
        request: dict[str, object],
        source_packet: dict[str, object],
    ) -> tuple[dict[str, object], list[str], list[str], dict[str, object]]:
        normalized = deepcopy(request)
        issues: list[str] = []
        warnings: list[str] = []
        if _clean(normalized.get("contract_name")) != REQUEST_CONTRACT_NAME:
            issues.append("request_contract")
        try:
            UUID(_clean(normalized.get("request_id")))
        except (TypeError, ValueError):
            issues.append("request_id")
        if not _stable_token(normalized.get("idempotency_key")):
            issues.append("idempotency_key")

        consumer = _dict(normalized.get("consumer"))
        product = _clean(consumer.get("product")).lower()
        if not _stable_token(product):
            issues.append("consumer_product")
        for field in ("tenant_ref", "subject_ref"):
            if not _safe_ref(consumer.get(field)):
                issues.append(f"consumer_{field}")

        artifact = _dict(normalized.get("artifact"))
        artifact_kind = _clean(artifact.get("kind")).lower()
        if artifact_kind not in _ALLOWED_ARTIFACT_KINDS:
            issues.append("artifact_kind")
        if _clean(artifact.get("purpose")).lower() not in _ALLOWED_PURPOSES:
            issues.append("artifact_purpose")
        if not _LOCALE_RE.fullmatch(_clean(artifact.get("locale"))):
            issues.append("artifact_locale")
        if not _safe_ref(normalized.get("source_packet_ref")):
            issues.append("source_packet_ref")
        truth_refs = _strings(normalized.get("truth_refs"))
        evidence_refs = _strings(normalized.get("evidence_refs"))
        if not truth_refs or not all(_safe_ref(value) for value in truth_refs):
            issues.append("truth_refs")
        if not evidence_refs or not all(_safe_ref(value) for value in evidence_refs):
            issues.append("evidence_refs")

        product_truth = {
            "consumer": consumer,
            "source_packet_ref": normalized.get("source_packet_ref"),
            "truth_refs": truth_refs,
            "evidence_refs": evidence_refs,
            "spatial_plan": normalized.get("spatial_plan"),
            "style": normalized.get("style"),
            "scene_overlays": normalized.get("scene_overlays"),
            "callback": normalized.get("callback"),
        }
        issues.extend(_contains_sensitive_shape(product_truth))
        issues.extend(_contains_sensitive_shape(source_packet, path="source_packet"))
        source_context = self._validate_source_packet(normalized, source_packet, issues)

        spatial_plan = _dict(normalized.get("spatial_plan"))
        for field in ("room_graph_ref", "walkable_mesh_ref", "portal_graph_ref"):
            if not _safe_ref(spatial_plan.get(field)):
                issues.append(f"spatial_plan_{field}")
            if _clean(spatial_plan.get(field)) != _clean(source_packet.get(field)):
                issues.append(f"spatial_plan_{field}_mismatch")
        route_metrics: dict[str, object] = {
            "required_room_count": len(_strings(spatial_plan.get("required_room_ids"))),
            "covered_room_count": 0,
            "room_coverage_percent": 0.0,
            "cut_count": 0,
            "teleport_count": 0,
        }
        if artifact_kind == "continuous_walkthrough":
            route_metrics = self._validate_continuous_route(spatial_plan, source_context, issues)

        style = _dict(normalized.get("style"))
        style_pack_id = _clean(style.get("style_pack_id"))
        style_pack = self._style_pack(style_pack_id, product)
        if style_pack is None:
            issues.append("style_pack")
        else:
            style_status = _clean(style_pack.get("status"))
            if style_status.startswith("blocked"):
                issues.append(f"style_pack_{style_status}")
            elif style_status == DESIGN_AUTHORITY_STATUS:
                warnings.append(DESIGN_AUTHORITY_STATUS)
            supported = {_clean(value).lower() for value in _strings(style_pack.get("room_types"))}
            room_rules = _dict(style_pack.get("room_rules"))
            source_types = {
                _clean(value).lower()
                for value in _dict(source_context.get("room_types")).values()
                if _clean(value)
            }
            if "any" not in supported and source_types.difference(supported):
                issues.append("style_room_type_coverage")
            if any(room_type not in room_rules and "any" not in room_rules for room_type in source_types):
                issues.append("style_room_rule_coverage")
            if any(not _strings(rules) for rules in room_rules.values()):
                issues.append("style_room_rules")
            if not _safe_ref(style_pack.get("adapter_profile_ref")):
                issues.append("style_adapter_profile_ref")
            provenance_refs = _strings(style_pack.get("provenance_refs"))
            if not provenance_refs or not all(_safe_ref(value) for value in provenance_refs):
                issues.append("style_pack_provenance")
            external_asset_refs = _strings(style_pack.get("external_asset_refs"))
            if not all(_safe_ref(value) for value in external_asset_refs):
                issues.append("style_pack_external_assets")
            if not style_status.startswith("blocked") and _parse_iso(style_pack.get("source_retrieved_at")) is None:
                issues.append("style_source_retrieved_at")
            if not _strings(style_pack.get("acceptance_contact_sheet_refs")):
                warnings.append("style_visual_acceptance_pending")
        if _clean(style.get("asset_license_policy")) != "verified_reuse_only":
            issues.append("style_asset_license_policy")
        if _clean(style.get("brand_claim_policy")) != "truthful_no_affiliation_claim":
            issues.append("style_brand_claim_policy")
        if any(room_id not in set(_strings(source_context.get("room_ids"))) for room_id in _dict(style.get("room_overrides"))):
            issues.append("style_room_overrides")
        if style.get("real_product_claim") is True:
            proof_refs = _strings(style.get("asset_reuse_proof_refs"))
            if not proof_refs or not all(_safe_ref(value) for value in proof_refs):
                issues.append("style_real_product_reuse_proof")

        camera = _dict(normalized.get("camera"))
        if camera.get("cuts_allowed") is not False:
            issues.append("camera_cuts_allowed")
        if camera.get("teleports_allowed") is not False:
            issues.append("camera_teleports_allowed")
        if camera.get("collision_avoidance") is not True:
            issues.append("camera_collision_avoidance")
        if camera.get("rotation_smoothing") is not True:
            issues.append("camera_rotation_smoothing")
        target_fps_value = _exact_integer(camera.get("target_delivery_fps"), minimum=60, maximum=240)
        effective_fps_value = _exact_integer(camera.get("minimum_effective_motion_fps"), minimum=30, maximum=240)
        camera_height_value = _finite_number(camera.get("height_m"), minimum=0.8, maximum=2.2)
        target_fps = target_fps_value or 0
        effective_fps = effective_fps_value or 0
        camera_height = camera_height_value or 0.0
        if target_fps_value is None:
            issues.append("camera_target_delivery_fps")
        if effective_fps_value is None or (target_fps_value is not None and effective_fps > target_fps):
            issues.append("camera_minimum_effective_motion_fps")
        if camera_height_value is None:
            issues.append("camera_height")

        output = _dict(normalized.get("output"))
        if output.get("desktop") is not True or output.get("mobile") is not True:
            issues.append("output_device_coverage")
        if _clean(output.get("video_codec")).lower() != "h264":
            issues.append("output_video_codec")
        if output.get("poster_frame") is not True or output.get("contact_sheet") is not True:
            issues.append("output_review_assets")
        if artifact_kind == "interactive_tour" and output.get("interactive_package") is not True:
            issues.append("output_interactive_package")

        content_policy = _dict(normalized.get("content_policy"))
        if _clean(content_policy.get("rating")) not in _ALLOWED_RATINGS:
            issues.append("content_policy_rating")
        if content_policy.get("graphic_injury") is not False:
            issues.append("content_policy_graphic_injury")
        if content_policy.get("real_person_likeness") is not False:
            issues.append("content_policy_real_person_likeness")
        if content_policy.get("minor_combatants") is not False:
            issues.append("content_policy_minor_combatants")
        raw_overlays = normalized.get("scene_overlays")
        overlays = _rows(raw_overlays)
        if not isinstance(raw_overlays, list) or len(overlays) != len(raw_overlays):
            issues.append("scene_overlays_shape")
        for path in _forbidden_rule_field_paths(raw_overlays, path="scene_overlays"):
            issues.append(f"scene_overlay_rules_truth_forbidden:request:{path}")
        overlay_metrics = self._validate_overlays(
            overlays,
            product=product,
            content_policy=content_policy,
            issues=issues,
        )

        quota = _dict(normalized.get("quota"))
        if quota.get("consume_quota") is not False:
            issues.append("compose_quota_must_be_false")
        compose_attempts = _exact_integer(quota.get("maximum_provider_attempts"), minimum=0, maximum=0)
        if compose_attempts is None:
            issues.append("compose_provider_attempts_must_be_zero")
        if not _safe_ref(_dict(normalized.get("callback")).get("product_event_ref")):
            issues.append("callback_product_event_ref")

        metrics = {
            **route_metrics,
            **overlay_metrics,
            "target_delivery_fps": target_fps,
            "minimum_effective_motion_fps": effective_fps,
            "spatial_drift_status": "not_measured",
            "rotation_status": "not_measured",
        }
        return normalized, _unique(issues), _unique(warnings), {
            "product": product,
            "artifact_kind": artifact_kind,
            "style_pack_id": style_pack_id,
            "style_pack": deepcopy(style_pack) if style_pack else {},
            "source_context": source_context,
            "metrics": metrics,
        }

    def _sign(self, digest: str) -> str:
        if self._signing_private_key is None:
            return ""
        return encode_ed25519_signature(self._signing_private_key.sign(digest.encode("ascii")))

    def _signature_valid(self, digest: str, signature: str) -> bool:
        if self._signing_public_key is None or not signature:
            return False
        try:
            decoded = decode_ed25519_signature(signature)
            self._signing_public_key.verify(decoded, digest.encode("ascii"))
        except (InvalidSignature, SignatureVerificationError, ValueError):
            return False
        return True

    def compose(
        self,
        request: Mapping[str, object],
        *,
        source_packet: Mapping[str, object],
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        normalized, issues, warnings, context = self._validate_request(dict(request), dict(source_packet))
        request_digest = _sha256_json(normalized)
        source_context = _dict(context.get("source_context"))
        source_digest = _clean(source_context.get("source_digest"))
        source_packet_digest = _sha256_json(source_packet)
        style_digest = _sha256_json(
            {
                "style_pack": _dict(context.get("style_pack")),
                "requested_style": _dict(normalized.get("style")),
            }
        )
        composition_digest = _sha256_json(
            {
                "request_digest": request_digest,
                "source_digest": source_digest,
                "source_packet_digest": source_packet_digest,
                "style_digest": style_digest,
                "contract_name": REQUEST_CONTRACT_NAME,
                "design_authority_status": DESIGN_AUTHORITY_STATUS,
            }
        )
        idempotency_key = _clean(normalized.get("idempotency_key"))
        existing = self._store.find_composition_by_key(idempotency_key)
        if existing is not None:
            if _clean(existing.get("composition_digest")) != composition_digest:
                self._emit(
                    "composition_conflicted",
                    request_digest=request_digest,
                    consumer_product=_clean(context.get("product")),
                )
                raise ValueError("idempotency_key_payload_conflict")
            existing["idempotent_replay"] = True
            self._emit(
                "composition_replayed",
                request_digest=request_digest,
                composition_digest=composition_digest,
                consumer_product=_clean(context.get("product")),
            )
            return existing
        if self._signing_private_key is None or not _safe_ref(self._signing_key_ref):
            issues.append("composition_signing_key_missing")

        artifact_kind = _clean(context.get("artifact_kind"))
        provider_key = self._provider_key_for_artifact(artifact_kind)
        provider_posture = self._provider_postures(observed_at=observed_at).get(provider_key)
        status = "accepted" if not issues else "blocked"
        receipt = {
            "contract_name": COMPOSITION_RECEIPT_CONTRACT_NAME,
            "contract_version": "2026-07-11-draft",
            "generated_at": _utc_iso(observed_at),
            "status": status,
            "design_authority_status": DESIGN_AUTHORITY_STATUS,
            "orchestration_lane": ORCHESTRATION_LANE,
            "request_id": _clean(normalized.get("request_id")),
            "idempotency_key": idempotency_key,
            "request_digest": request_digest,
            "source_digest": source_digest,
            "source_packet_digest": source_packet_digest,
            "style_digest": style_digest,
            "composition_digest": composition_digest,
            "composition_signature": self._sign(composition_digest),
            "signature_status": "signed" if self._signing_private_key is not None else "blocked_missing_key",
            "signature_algorithm": "ed25519" if self._signing_private_key is not None else "",
            "signature_encoding": "base64url_no_padding" if self._signing_private_key is not None else "",
            "signing_key_ref": self._signing_key_ref if self._signing_private_key is not None else "",
            "signing_key_fingerprint": (
                public_key_fingerprint(self._signing_public_key) if self._signing_public_key is not None else ""
            ),
            "consumer_product": context.get("product"),
            "artifact_kind": artifact_kind,
            "style_pack_id": context.get("style_pack_id"),
            "blocked_reasons": _unique(issues),
            "warnings": warnings,
            "provider_resolution": {
                "status": provider_posture.status if provider_posture else "unverified",
                "status_reason": provider_posture.status_reason if provider_posture else "provider_posture_missing",
                "selected_provider_private": provider_key,
                "provider_sensitive_fields_public": False,
            },
            "quota": {"consume_quota": False, "provider_attempts": 0, "credits_consumed": 0},
            "estimate": {
                "status": "bounded" if artifact_kind == "interactive_tour" else "unavailable_until_provider_verified",
                "eta_seconds_min": 0 if artifact_kind == "interactive_tour" else None,
                "eta_seconds_max": 900 if artifact_kind == "interactive_tour" else None,
                "provider_credits_min": 0,
                "provider_credits_max": 0 if artifact_kind == "interactive_tour" else None,
            },
            "quality_contract": context.get("metrics"),
            "source_packet_private": {
                "source_packet_ref_sha256": _sha256_text(normalized.get("source_packet_ref")),
                "room_graph_ref_sha256": _sha256_text(_dict(normalized.get("spatial_plan")).get("room_graph_ref")),
                "walkable_mesh_ref_sha256": _sha256_text(
                    _dict(normalized.get("spatial_plan")).get("walkable_mesh_ref")
                ),
                "portal_graph_ref_sha256": _sha256_text(_dict(normalized.get("spatial_plan")).get("portal_graph_ref")),
                "existing_artifacts": deepcopy(_dict(source_context.get("existing_artifacts"))),
            },
            "raw_provider_urls_exposed": False,
            "raw_provider_account_ids_exposed": False,
            "raw_provider_task_ids_exposed": False,
            "idempotent_replay": False,
        }
        saved = self._store.save_composition(receipt)
        self._emit(
            "composition_created" if status == "accepted" else "composition_rejected",
            request_digest=request_digest,
            composition_digest=composition_digest,
            consumer_product=_clean(context.get("product")),
            artifact_kind=artifact_kind,
            status=status,
            blocked_reason_codes=list(saved.get("blocked_reasons") or []),
            provider_actions=0,
            quota_actions=0,
        )
        return saved

    @staticmethod
    def _product_projection(
        *,
        composition: dict[str, object],
        state: str,
        reason: str,
        artifact_ref: str = "",
    ) -> dict[str, object]:
        return {
            "contract_name": PRODUCT_PROJECTION_CONTRACT_NAME,
            "request_id": _clean(composition.get("request_id")),
            "artifact_kind": _clean(composition.get("artifact_kind")),
            "label": _clean(composition.get("artifact_kind")).replace("_", " ").title(),
            "state": state,
            "progress_percent": 100 if state == "ready" else 0,
            "eta_seconds": 0 if state == "ready" else None,
            "artifact_ref": artifact_ref if state == "ready" else "",
            "reason": reason,
            "retry_posture": "not_required" if state == "ready" else "operator_export_intake_required",
            "provider_details_exposed": False,
        }

    def build(
        self,
        *,
        composition_digest: str,
        composition_signature: str,
        build_idempotency_key: str,
        consume_quota: bool,
        maximum_provider_attempts: int,
        quota_authorization_ref: str,
        audit_event_ref: str,
        evidence_envelope: Mapping[str, object] | None = None,
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        normalized_key = _clean(build_idempotency_key)
        if not _stable_token(normalized_key):
            raise ValueError("build_idempotency_key_required")
        if type(consume_quota) is not bool:
            raise ValueError("consume_quota_boolean_required")
        if _exact_integer(maximum_provider_attempts, minimum=0, maximum=3) is None:
            raise ValueError("maximum_provider_attempts_exact_integer_required")
        verified_evidence: dict[str, object] | None = None
        if evidence_envelope is not None:
            verified_evidence = self.verify_build_evidence(evidence_envelope, observed_at=observed_at)
        evidence_digest = bounded_sha256(verified_evidence, prefixed=True) if verified_evidence is not None else ""
        build_request_digest = _sha256_json(
            {
                "composition_digest": _clean(composition_digest),
                "composition_signature": _clean(composition_signature),
                "build_idempotency_key": normalized_key,
                "consume_quota": consume_quota,
                "maximum_provider_attempts": maximum_provider_attempts,
                "quota_authorization_ref_sha256": _sha256_text(quota_authorization_ref),
                "audit_event_ref_sha256": _sha256_text(audit_event_ref),
                "evidence_digest": evidence_digest,
            }
        )
        existing = self._store.find_build(normalized_key)
        if existing is not None:
            if _clean(existing.get("build_request_digest")) != build_request_digest:
                self._emit("build_conflicted", build_request_digest=build_request_digest)
                raise ValueError("build_idempotency_key_payload_conflict")
            existing["idempotent_replay"] = True
            self._emit(
                "build_replayed",
                build_request_digest=build_request_digest,
                composition_digest=_clean(composition_digest),
                provider_actions=0,
                quota_actions=0,
            )
            return existing

        composition = self._store.find_composition(composition_digest)
        if composition is None:
            raise ValueError("accepted_composition_not_found")
        blocked: list[str] = []
        if _clean(composition.get("status")) != "accepted":
            blocked.append("composition_not_accepted")
        if not self._signature_valid(composition_digest, composition_signature):
            blocked.append("composition_signature_invalid")
        if composition_signature != _clean(composition.get("composition_signature")):
            blocked.append("composition_signature_mismatch")
        if not consume_quota:
            blocked.append("explicit_quota_authorization_required")
        if maximum_provider_attempts < 1 or maximum_provider_attempts > 3:
            blocked.append("bounded_provider_attempts_required")
        if not _safe_ref(quota_authorization_ref):
            blocked.append("product_quota_authorization_ref_required")
        if not _safe_ref(audit_event_ref):
            blocked.append("product_audit_event_ref_required")
        if verified_evidence is None:
            blocked.append("signed_build_evidence_required")
        else:
            evidence_authorization = _dict(verified_evidence.get("authorization"))
            evidence_idempotency = _dict(verified_evidence.get("idempotency"))
            if evidence_idempotency.get("composition_digest") != f"sha256:{_clean(composition_digest)}":
                blocked.append("signed_build_evidence_composition_mismatch")
            if _clean(evidence_authorization.get("authorization_ref")) != _clean(quota_authorization_ref):
                blocked.append("signed_build_evidence_authorization_mismatch")
            if evidence_authorization.get("maximum_provider_attempts") != maximum_provider_attempts:
                blocked.append("signed_build_evidence_attempt_ceiling_mismatch")
        if not self._build_enabled:
            blocked.append("governed_spatial_build_disabled")
        if DESIGN_AUTHORITY_STATUS != "accepted":
            blocked.append("design_acceptance_required")

        artifact_kind = _clean(composition.get("artifact_kind"))
        provider_key = self._provider_key_for_artifact(artifact_kind)
        provider_posture = self._provider_postures(observed_at=observed_at).get(provider_key)
        if provider_posture is None or provider_posture.status != "verified":
            blocked.append("verified_provider_required")

        existing_artifacts = _dict(_dict(composition.get("source_packet_private")).get("existing_artifacts"))
        artifact = _dict(existing_artifacts.get(artifact_kind))
        artifact_ref = _clean(artifact.get("artifact_ref"))
        artifact_sha256 = _clean(artifact.get("sha256")).lower()
        artifact_proof_ref = _clean(artifact.get("proof_ref"))
        candidate_shape_valid = (
            _safe_ref(artifact_ref)
            and bool(_SHA256_RE.fullmatch(artifact_sha256))
            and _safe_ref(artifact_proof_ref)
        )
        if not candidate_shape_valid:
            blocked.append("existing_artifact_candidate_invalid")
        trusted_artifact_verified = False
        blocked.append("trusted_immutable_artifact_verification_unavailable")

        # The local petition permits receipt-shape validation only. No adapter is invoked here.
        state = "blocked" if blocked else "ready"
        reason = blocked[0] if blocked else "trusted_existing_artifact_verified"
        build_material = {
            "composition_digest": composition_digest,
            "build_idempotency_key": normalized_key,
            "build_request_digest": build_request_digest,
        }
        receipt = {
            "contract_name": BUILD_RECEIPT_CONTRACT_NAME,
            "contract_version": "2026-07-11-draft",
            "generated_at": _utc_iso(observed_at),
            "status": state,
            "design_authority_status": DESIGN_AUTHORITY_STATUS,
            "build_id": f"spatial-build-{_sha256_json(build_material)[:20]}",
            "build_idempotency_key": normalized_key,
            "build_request_digest": build_request_digest,
            "composition_digest": composition_digest,
            "parent_request_digest": _clean(composition.get("request_digest")),
            "source_digest": _clean(composition.get("source_digest")),
            "source_packet_digest": _clean(composition.get("source_packet_digest")),
            "style_digest": _clean(composition.get("style_digest")),
            "output_digest": artifact_sha256 if state == "ready" else "",
            "blocked_reasons": _unique(blocked),
            "provider_private": {
                "provider_key": provider_key,
                "provider_posture": provider_posture.as_dict() if provider_posture else {},
                "provider_jobs_attempted": 0,
                "provider_task_parentage": [],
                "provider_credits_consumed": 0,
                "existing_artifact_candidate_shape_valid": candidate_shape_valid,
                "trusted_artifact_verified": trusted_artifact_verified,
                "existing_artifact_reused": False,
            },
            "quota": {
                "consume_quota_authorized": consume_quota,
                "quota_authorization_ref_sha256": _sha256_text(quota_authorization_ref),
                "maximum_provider_attempts": maximum_provider_attempts,
                "provider_attempts": 0,
                "provider_credits_consumed": 0,
            },
            "audit": {
                "audit_event_ref_sha256": _sha256_text(audit_event_ref),
                "provider_job_enqueued": False,
                "signed_evidence_digest": evidence_digest,
            },
            "quality_metrics": deepcopy(composition.get("quality_contract")),
            "product_projection": self._product_projection(
                composition=composition,
                state=state,
                reason=reason,
                artifact_ref=artifact_ref,
            ),
            "raw_provider_urls_exposed": False,
            "raw_provider_account_ids_exposed": False,
            "raw_provider_task_ids_exposed": False,
            "idempotent_replay": False,
        }
        saved = self._store.save_build(normalized_key, receipt)
        self._emit(
            "build_state_changed",
            build_request_digest=build_request_digest,
            composition_digest=_clean(composition_digest),
            status=state,
            blocked_reason_codes=list(saved.get("blocked_reasons") or []),
            provider_execution_suppressed=True,
            provider_actions=0,
            quota_actions=0,
        )
        return saved


class GovernedQuotaAdapter(Protocol):
    def reserve(self, request: Mapping[str, object]) -> Mapping[str, object]: ...

    def commit_attempt(self, request: Mapping[str, object]) -> Mapping[str, object]: ...

    def release(self, request: Mapping[str, object]) -> Mapping[str, object]: ...

    def consume(self, request: Mapping[str, object]) -> Mapping[str, object]: ...

    def compensate(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


class GovernedExecutionAdapter(Protocol):
    def execution_target_binding(self) -> Mapping[str, object]: ...

    def execute(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


class GovernedQualityGate(Protocol):
    def __call__(self, output_digest: str, metrics: Mapping[str, object]) -> Mapping[str, object]: ...


class GovernedSpatialOrchestrator:
    """Provider-neutral orchestration over injected, deterministic boundaries."""

    def __init__(
        self,
        *,
        ledger: DurableSpatialLedger,
        signer: Ed25519EnvelopeSigner,
        quota_adapter: GovernedQuotaAdapter | None = None,
        execution_adapter: GovernedExecutionAdapter | None = None,
        execution_target: Mapping[str, object] | None = None,
        quality_gate: GovernedQualityGate | None = None,
        telemetry_sink: Callable[[dict[str, object]], None] | None = None,
        now: Callable[[], datetime] = _utc_now,
        material_store: SpatialExecutionMaterialStore | None = None,
        composition_verification_registry: CanonicalEd25519KeyRegistry | None = None,
        property_policy_verifier: PropertyRetentionPolicyVerifier | None = None,
        property_input_authority_verifier: PropertyExecutionInputAuthorityVerifier | None = None,
    ) -> None:
        self._ledger = ledger
        self._signer = signer
        self._quota_adapter = quota_adapter
        self._execution_adapter = execution_adapter
        self._execution_target = self._normalize_execution_target(execution_target)
        if (
            self._execution_target is not None
            and self._execution_target["environment"] != signer.key_record.environment
        ):
            raise SpatialStateError("execution_target_signing_environment_mismatch")
        self._quality_gate = quality_gate
        self._telemetry_sink = telemetry_sink
        self._now = now
        self._material_store = material_store
        self._composition_verification_registry = composition_verification_registry
        self._property_policy_verifier = property_policy_verifier
        self._property_input_authority_verifier = property_input_authority_verifier

    @staticmethod
    def _prefixed(value: object) -> str:
        normalized = _clean(value).removeprefix("sha256:")
        if not _SHA256_RE.fullmatch(normalized):
            raise SpatialStateError("sha256_digest_required")
        return f"sha256:{normalized}"

    def _observed(self, value: datetime | None) -> datetime:
        observed = value or self._now()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise SpatialStateError("observed_at_offset_required")
        return observed.astimezone(UTC).replace(microsecond=0)

    def _emit(self, event_type: str, **fields: object) -> None:
        if self._telemetry_sink is None:
            return
        route_visit_count = fields.get("route_visit_count", 0)
        route_revisit_count = fields.get("route_revisit_count", 0)
        if (
            type(route_visit_count) is not int
            or type(route_revisit_count) is not int
            or route_visit_count < 0
            or route_revisit_count < 0
            or route_revisit_count > route_visit_count
        ):
            raise SpatialStateError("telemetry_route_count_invalid")
        allowed = {
            "event_type": event_type,
            "state": fields.get("state"),
            "request_digest": fields.get("request_digest"),
            "composition_digest": fields.get("composition_digest"),
            "build_request_digest": fields.get("build_request_digest"),
            "attempt_number": fields.get("attempt_number", 0),
            "reason_codes": list(fields.get("reason_codes") or []),
            "quota_actions": fields.get("quota_actions", 0),
            "execution_actions": fields.get("execution_actions", 0),
            "route_visit_count": route_visit_count,
            "route_revisit_count": route_revisit_count,
        }
        if _contains_sensitive_shape(allowed):
            raise SpatialStateError("telemetry_redaction_failed")
        self._telemetry_sink(deepcopy(allowed))

    @staticmethod
    def _normalize_execution_target(value: Mapping[str, object] | None) -> dict[str, object] | None:
        if value is None:
            return None
        target = dict(value)
        expected_fields = {
            "artifact_family",
            "content_profile",
            "environment",
            "provider_route_digest",
            "gate_versions",
        }
        if set(target) != expected_fields:
            raise SpatialStateError("execution_target_members_invalid")
        if target.get("artifact_family") not in {
            PROPERTY_ARTIFACT_FAMILY,
            "runsite_continuous_walkthrough",
            "runsite_private_encounter_preview",
        }:
            raise SpatialStateError("execution_target_artifact_family_invalid")
        if target.get("content_profile") not in {
            "spatial_orientation_no_encounter_fields",
            "private_fictional_non_graphic_encounter",
        }:
            raise SpatialStateError("execution_target_content_profile_invalid")
        environment = target.get("environment")
        if not isinstance(environment, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", environment):
            raise SpatialStateError("execution_target_environment_invalid")
        route_digest = target.get("provider_route_digest")
        if not isinstance(route_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", route_digest):
            raise SpatialStateError("execution_target_route_digest_invalid")
        gate_versions = target.get("gate_versions")
        if not isinstance(gate_versions, Mapping) or not gate_versions:
            raise SpatialStateError("execution_target_gate_versions_required")
        normalized_gates: dict[str, str] = {}
        for key, version in gate_versions.items():
            if (
                not isinstance(key, str)
                or not isinstance(version, str)
                or not key
                or not version
                or len(key) > 128
                or len(version) > 128
            ):
                raise SpatialStateError("execution_target_gate_version_invalid")
            normalized_gates[key] = version
        return {
            "artifact_family": target["artifact_family"],
            "content_profile": target["content_profile"],
            "environment": environment,
            "provider_route_digest": route_digest,
            "gate_versions": dict(sorted(normalized_gates.items())),
        }

    @staticmethod
    def _artifact_profile(request: GovernedSpatialRenderRequestV1) -> tuple[str | None, str | None]:
        if request.artifact.kind != "continuous_walkthrough":
            return None, None
        private_encounter = (
            request.artifact.purpose == "encounter_preview"
            or bool(request.scene_overlays)
            or request.content_policy.rating == "teen_fictional_combat"
        )
        if private_encounter:
            return "runsite_private_encounter_preview", "private_fictional_non_graphic_encounter"
        return "runsite_continuous_walkthrough", "spatial_orientation_no_encounter_fields"

    @staticmethod
    def _validate_cross_source(
        request: GovernedSpatialRenderRequestV1,
        source: GovernedSpatialSourcePacketV1,
    ) -> None:
        mismatches: list[str] = []
        if _parse_iso_strict(source.source_retrieved_at) is None:
            mismatches.append("source_retrieved_at_offset_required")
        if request.source_packet_ref != source.source_packet_ref:
            mismatches.append("source_packet_ref_mismatch")
        for field in ("room_graph_ref", "walkable_mesh_ref", "portal_graph_ref"):
            if getattr(request.spatial_plan, field) != getattr(source, field):
                mismatches.append(f"{field}_mismatch")

        source_room_ids = {room.room_id for room in source.rooms}
        walkable_room_ids = {room.room_id for room in source.rooms if room.walkable}
        inaccessible_room_ids = {
            str(row.get("room_id"))
            for row in source.inaccessible_rooms
            if isinstance(row, Mapping) and isinstance(row.get("room_id"), str)
        }
        if len(inaccessible_room_ids) != len(source.inaccessible_rooms):
            mismatches.append("inaccessible_room_identity_invalid")
        if inaccessible_room_ids & walkable_room_ids:
            mismatches.append("inaccessible_room_classified_walkable")
        if source.route_exclusions:
            mismatches.append("route_exclusions_forbidden_for_full_walkable_route")

        request_required = set(request.spatial_plan.required_room_ids)
        request_route_sequence = list(request.spatial_plan.route_room_ids)
        source_route_sequence = list(source.route_room_ids)
        request_route = set(request_route_sequence)
        source_route = set(source_route_sequence)
        if request_required != walkable_room_ids:
            mismatches.append("request_required_rooms_not_full_walkable_set")
        if request_route != walkable_room_ids:
            mismatches.append("request_route_rooms_not_full_walkable_set")
        if source_route != walkable_room_ids:
            mismatches.append("source_route_rooms_not_full_walkable_set")
        if request_route_sequence != source_route_sequence:
            mismatches.append("request_source_route_sequence_mismatch")
        route_has_revisit = len(request_route_sequence) != len(request_route)
        if request.spatial_plan.allow_revisit is not route_has_revisit:
            mismatches.append("request_route_revisit_flag_mismatch")
        if not walkable_room_ids or not walkable_room_ids <= source_room_ids:
            mismatches.append("walkable_room_inventory_invalid")

        source_portals = {
            tuple(sorted((portal.from_room_id, portal.to_room_id)))
            for portal in source.portals
            if portal.walkable
            and portal.from_room_id in walkable_room_ids
            and portal.to_room_id in walkable_room_ids
        }
        request_portals: set[tuple[str, str]] = set()
        for edge in request.spatial_plan.portal_edges:
            if edge.from_room_id not in walkable_room_ids or edge.to_room_id not in walkable_room_ids:
                mismatches.append("request_portal_room_not_walkable")
            request_portals.add(tuple(sorted((edge.from_room_id, edge.to_room_id))))
        if not request_portals <= source_portals:
            mismatches.append("request_portal_not_in_source_truth")
        route_transitions = {
            tuple(sorted((left, right)))
            for left, right in zip(request_route_sequence, request_route_sequence[1:])
        }
        if not route_transitions <= source_portals:
            mismatches.append("request_route_transition_not_in_source_truth")
        if mismatches:
            raise SpatialStateError("cross_source_validation_failed:" + ";".join(dict.fromkeys(mismatches)))

    def _privacy_tombstone(self, receipt: Mapping[str, object]) -> dict[str, object] | None:
        try:
            scope_digest = self._prefixed(receipt.get("composition_digest"))
        except SpatialStateError:
            return None
        return self._ledger.privacy_status(scope_digest)

    def _public_projection(self, receipt: Mapping[str, object]) -> dict[str, object]:
        state = _clean(receipt.get("state") or receipt.get("status"))
        privacy_tombstone = self._privacy_tombstone(receipt)
        blocked = (
            state in {GENERIC_BLOCKED_STATE, "compensation_failed_blocked"}
            or receipt.get("quota_posture") == "blocked"
            or receipt.get("reconciliation_required") is True
            or privacy_tombstone is not None
        )
        complete = state == "closed_consumed"
        return {
            "contract_name": PRODUCT_PROJECTION_CONTRACT_NAME,
            "state": "unavailable" if privacy_tombstone is not None else (
                "blocked" if blocked else ("complete_internal" if complete else "processing")
            ),
            "reason": (
                "privacy_tombstone_active"
                if privacy_tombstone is not None
                else next(iter(receipt.get("blocked_reasons") or []), "") if blocked else ""
            ),
            "progress_percent": 0 if privacy_tombstone is not None else (100 if complete else 0),
            "output_manifest_ref": "",
            "artifact_ref": "",
            "publication_allowed": False,
            "serving_allowed": False,
            "privacy_tombstone_active": privacy_tombstone is not None,
            "provider_details_exposed": False,
            "quota_details_exposed": False,
        }

    @staticmethod
    def _property_policy_evidence(
        value: Mapping[str, object] | None,
    ) -> tuple[dict[str, object], datetime, datetime]:
        if value is None:
            raise SpatialStateError("property_policy_evidence_required")
        if not isinstance(value, Mapping):
            raise SpatialStateError("property_policy_evidence_invalid")
        try:
            parsed = PropertyRetentionPolicyEvidence.model_validate(dict(value))
        except ValidationError:
            raise SpatialStateError("property_policy_evidence_invalid") from None
        payload = parsed.model_dump(mode="json")
        if parsed.policy_id != PROPERTY_POLICY_ID:
            raise SpatialStateError("property_policy_identity_mismatch")
        if parsed.policy_digest != PROPERTY_POLICY_DIGEST:
            raise SpatialStateError("property_policy_digest_mismatch")
        if not _safe_ref(parsed.approval_ref) or not _safe_ref(parsed.verifier_ref):
            raise SpatialStateError("property_policy_evidence_invalid")
        for digest in (parsed.policy_digest, parsed.verification_receipt_digest):
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise SpatialStateError("property_policy_evidence_invalid")
        approved = _parse_iso_strict(parsed.approved_at)
        expires = _parse_iso_strict(parsed.expires_at)
        if (
            approved is None
            or expires is None
            or utc_iso(approved) != parsed.approved_at
            or utc_iso(expires) != parsed.expires_at
            or approved >= expires
        ):
            raise SpatialStateError("property_policy_evidence_chronology_invalid")
        return payload, approved, expires

    def verify_property_execution_authority(
        self,
        policy_evidence: Mapping[str, object] | None,
        *,
        observed_at: datetime | None = None,
    ) -> PropertyRetentionPolicyVerification:
        observed = self._observed(observed_at)
        evidence, approved, evidence_expires = self._property_policy_evidence(policy_evidence)
        if approved > observed:
            raise SpatialStateError("property_policy_evidence_not_current")
        if observed - approved > timedelta(hours=24):
            raise SpatialStateError("property_policy_evidence_stale")
        if evidence_expires <= observed:
            raise SpatialStateError("property_policy_evidence_expired")
        if evidence_expires - approved > timedelta(hours=24):
            raise SpatialStateError("property_policy_evidence_freshness_window_invalid")
        if self._property_policy_verifier is None:
            raise SpatialStateError("property_policy_verifier_unavailable")
        try:
            verification = self._property_policy_verifier(
                evidence=deepcopy(evidence), observed_at=observed
            )
        except Exception:
            raise SpatialStateError("property_policy_unverifiable") from None
        if not isinstance(verification, PropertyRetentionPolicyVerification):
            raise SpatialStateError("property_policy_unverifiable")
        blocked_states = {
            "missing": "property_policy_missing",
            "stale": "property_policy_stale",
            "digest_mismatched": "property_policy_digest_mismatched",
            "mode_mismatched": "property_policy_mode_mismatched",
            "expired": "property_policy_expired",
            "revoked": "property_policy_revoked",
            "unverifiable": "property_policy_unverifiable",
        }
        if verification.state in blocked_states:
            raise SpatialStateError(blocked_states[verification.state])
        if verification.state != "verified":
            raise SpatialStateError("property_policy_unverifiable")
        if not isinstance(verification.policy_expires_at, datetime):
            raise SpatialStateError("property_policy_unverifiable")
        policy_expires = verification.policy_expires_at
        if policy_expires.tzinfo is None or policy_expires.utcoffset() is None:
            raise SpatialStateError("property_policy_unverifiable")
        policy_expires = policy_expires.astimezone(UTC).replace(microsecond=0)
        expected = {
            "policy_path": PROPERTY_POLICY_PATH,
            "policy_id": PROPERTY_POLICY_ID,
            "policy_digest": PROPERTY_POLICY_DIGEST,
            "policy_mode": 0o600,
            "source_retention_days": 30,
            "approval_ref": evidence["approval_ref"],
            "verifier_ref": evidence["verifier_ref"],
            "verification_receipt_digest": evidence["verification_receipt_digest"],
            "evidence_digest": payload_digest(evidence),
            "independent_acceptance_digest": PROPERTY_AUTHORITY_ACCEPTANCE_DIGEST,
            "independent_acceptance_mode": 0o600,
            "regular_file": True,
            "independent_acceptance_regular_file": True,
        }
        for field, expected_value in expected.items():
            if getattr(verification, field) != expected_value:
                reason = (
                    "property_policy_mode_mismatch"
                    if field in {"policy_mode", "regular_file"}
                    else "property_policy_independent_acceptance_invalid"
                    if field.startswith("independent_acceptance")
                    else "property_policy_verification_mismatch"
                )
                raise SpatialStateError(reason)
        if policy_expires <= observed:
            raise SpatialStateError("property_policy_expired")
        if evidence_expires > policy_expires:
            raise SpatialStateError("property_policy_evidence_outlives_policy")
        return verification

    @staticmethod
    def _normalize_property_retention_deadlines(
        value: Mapping[str, object] | None,
    ) -> tuple[dict[str, list[str]], tuple[datetime, ...]]:
        supplied = {} if value is None else dict(value)
        if set(supplied) - _PROPERTY_RETENTION_DEADLINE_FIELDS:
            raise SpatialStateError("property_retention_deadline_members_invalid")
        normalized: dict[str, list[str]] = {}
        instants: list[datetime] = []
        for field in sorted(_PROPERTY_RETENTION_DEADLINE_FIELDS):
            raw_values = supplied.get(field, [])
            if not isinstance(raw_values, list) or len(raw_values) > 100:
                raise SpatialStateError("property_retention_deadline_invalid")
            rendered: list[str] = []
            for raw in raw_values:
                parsed = _parse_iso_strict(raw)
                if parsed is None or utc_iso(parsed) != raw:
                    raise SpatialStateError("property_retention_deadline_invalid")
                rendered.append(raw)
                instants.append(parsed)
            if len(rendered) != len(set(rendered)):
                raise SpatialStateError("property_retention_deadline_duplicate")
            normalized[field] = rendered
        return normalized, tuple(instants)

    def _property_material_inputs(
        self,
        request: GovernedSpatialRenderRequestV1 | Mapping[str, object],
        source_packet: GovernedSpatialSourcePacketV1 | Mapping[str, object],
        style_snapshot: GovernedSpatialStyleSnapshotV1 | Mapping[str, object],
        asset_bindings: list[GovernedSpatialAssetBindingV1 | Mapping[str, object]],
        *,
        observed: datetime,
    ) -> dict[str, object]:
        try:
            parsed_request = (
                request
                if isinstance(request, GovernedSpatialRenderRequestV1)
                else GovernedSpatialRenderRequestV1.model_validate(dict(request))
            )
            parsed_source = (
                source_packet
                if isinstance(source_packet, GovernedSpatialSourcePacketV1)
                else GovernedSpatialSourcePacketV1.model_validate(dict(source_packet))
            )
            parsed_style = (
                style_snapshot
                if isinstance(style_snapshot, GovernedSpatialStyleSnapshotV1)
                else GovernedSpatialStyleSnapshotV1.model_validate(dict(style_snapshot))
            )
            if not isinstance(asset_bindings, list):
                raise ValueError("asset_bindings_list_required")
            parsed_assets = [
                binding
                if isinstance(binding, GovernedSpatialAssetBindingV1)
                else GovernedSpatialAssetBindingV1.model_validate(dict(binding))
                for binding in asset_bindings
            ]
            self._validate_cross_source(parsed_request, parsed_source)
            validate_style_snapshot_time(parsed_style, now=observed)
            request_material = normalized_request_material(parsed_request)
            source_material = normalize_compatibility_numbers(
                parsed_source.model_dump(mode="json")
            )
            if not isinstance(source_material, dict):
                raise ValueError("normalized_source_packet_object_required")
        except (ValidationError, ValueError, TypeError, SpatialExecutionContractError):
            raise SpatialStateError("property_execution_inputs_invalid") from None

        if (
            parsed_request.consumer.product != "propertyquarry"
            or parsed_request.artifact.kind != "continuous_walkthrough"
            or parsed_request.artifact.purpose != "walkthrough"
            or parsed_request.scene_overlays
            or parsed_request.content_policy.rating != "general_spatial_orientation"
        ):
            raise SpatialStateError("property_execution_profile_invalid")
        if self._execution_target is None:
            raise SpatialStateError("property_execution_target_required")
        if (
            self._execution_target["artifact_family"] != PROPERTY_ARTIFACT_FAMILY
            or self._execution_target["content_profile"] != PROPERTY_CONTENT_PROFILE
            or "property_policy" not in self._execution_target["gate_versions"]
        ):
            raise SpatialStateError("property_execution_target_mismatch")
        if "propertyquarry" not in parsed_style.consumer_products:
            raise SpatialStateError("property_style_product_mismatch")
        style_retrieved = _parse_iso_strict(parsed_style.source_retrieved_at)
        if style_retrieved is None or utc_iso(style_retrieved) != parsed_style.source_retrieved_at:
            raise SpatialStateError("property_style_timestamp_noncanonical")
        source_room_types = {room.room_type for room in parsed_source.rooms}
        if "any" not in parsed_style.room_types and not source_room_types <= set(parsed_style.room_types):
            raise SpatialStateError("property_style_room_type_mismatch")
        packet_created = _parse_iso_strict(parsed_source.source_packet_created_at)
        if packet_created is None or packet_created > observed:
            raise SpatialStateError("property_source_packet_created_at_invalid")
        style_payload = parsed_style.model_dump(mode="json")
        assets_payload = [asset.model_dump(mode="json") for asset in parsed_assets]
        return {
            "request": parsed_request,
            "request_material": request_material,
            "source_material": source_material,
            "style": parsed_style,
            "style_payload": style_payload,
            "assets": parsed_assets,
            "assets_payload": assets_payload,
            "packet_created": packet_created,
            "request_digest": payload_digest(request_material),
            "source_packet_digest": payload_digest(source_material),
            "style_snapshot_digest": payload_digest(style_payload),
            "asset_bindings_digest": payload_digest(assets_payload),
            "output_contract_digest": payload_digest(request_material["output"]),
        }

    def _verify_property_input_authority(
        self,
        inputs: Mapping[str, object],
        *,
        observed_at: datetime,
    ) -> dict[str, object]:
        if self._property_input_authority_verifier is None:
            raise SpatialStateError("property_input_authority_verifier_unavailable")
        style = inputs.get("style")
        assets = inputs.get("assets")
        request_material = inputs.get("request_material")
        source_material = inputs.get("source_material")
        if (
            not isinstance(style, GovernedSpatialStyleSnapshotV1)
            or not isinstance(assets, list)
            or any(not isinstance(asset, GovernedSpatialAssetBindingV1) for asset in assets)
            or not isinstance(request_material, Mapping)
            or not isinstance(source_material, Mapping)
        ):
            raise SpatialStateError("property_execution_inputs_invalid")
        try:
            style_copy = GovernedSpatialStyleSnapshotV1.model_validate(
                deepcopy(style.model_dump(mode="json"))
            )
            asset_copies = tuple(
                GovernedSpatialAssetBindingV1.model_validate(
                    deepcopy(asset.model_dump(mode="json"))
                )
                for asset in assets
            )
            verification = self._property_input_authority_verifier(
                normalized_request=deepcopy(dict(request_material)),
                normalized_source_packet=deepcopy(dict(source_material)),
                style_snapshot=style_copy,
                asset_bindings=asset_copies,
                observed_at=observed_at,
            )
        except Exception:
            raise SpatialStateError("property_input_authority_unverifiable") from None
        if type(verification) is not PropertyExecutionInputAuthorityVerification:
            raise SpatialStateError("property_input_authority_unverifiable")
        blocked_states = {
            "missing": "property_input_authority_missing",
            "stale": "property_input_authority_stale",
            "expired": "property_input_authority_expired",
            "revoked": "property_input_authority_revoked",
            "unverifiable": "property_input_authority_unverifiable",
        }
        if verification.state in blocked_states:
            raise SpatialStateError(blocked_states[verification.state])
        if verification.state != "verified":
            raise SpatialStateError("property_input_authority_unverifiable")

        digest_fields = (
            "request_digest",
            "source_packet_digest",
            "source_authority_receipt_digest",
            "style_snapshot_digest",
            "style_registry_receipt_digest",
            "asset_bindings_digest",
            "asset_authority_receipt_digest",
        )
        if any(
            not isinstance(getattr(verification, field), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", getattr(verification, field))
            for field in digest_fields
        ):
            raise SpatialStateError("property_input_authority_projection_invalid")

        def canonical_instant(value: object) -> datetime:
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() != timedelta(0)
                or value.microsecond != 0
            ):
                raise SpatialStateError("property_input_authority_chronology_invalid")
            return value.astimezone(UTC)

        verified_at = canonical_instant(verification.verified_at)
        expires_at = canonical_instant(verification.expires_at)
        source_created = canonical_instant(verification.source_packet_created_at)
        if (
            verified_at > observed_at
            or observed_at >= expires_at
            or expires_at <= verified_at
            or expires_at - verified_at > timedelta(hours=24)
        ):
            raise SpatialStateError("property_input_authority_chronology_invalid")
        expected_bindings = {
            "request_digest": inputs.get("request_digest"),
            "source_packet_digest": inputs.get("source_packet_digest"),
            "style_snapshot_digest": inputs.get("style_snapshot_digest"),
            "asset_bindings_digest": inputs.get("asset_bindings_digest"),
        }
        mismatch_reasons = {
            "request_digest": "property_input_authority_request_digest_mismatch",
            "source_packet_digest": "property_input_authority_source_digest_mismatch",
            "style_snapshot_digest": "property_input_authority_style_digest_mismatch",
            "asset_bindings_digest": "property_input_authority_asset_digest_mismatch",
        }
        for field, expected in expected_bindings.items():
            if getattr(verification, field) != expected:
                raise SpatialStateError(mismatch_reasons[field])
        packet_created = inputs.get("packet_created")
        if not isinstance(packet_created, datetime) or source_created != packet_created:
            raise SpatialStateError("property_input_authority_source_timestamp_mismatch")

        projection = {
            "contract_name": "ea.governed_spatial_property_input_authority.v1",
            "contract_version": "1.0.0",
            "state": "verified",
            "request_digest": verification.request_digest,
            "source_packet_digest": verification.source_packet_digest,
            "source_packet_created_at": utc_iso(source_created),
            "source_authority_receipt_digest": verification.source_authority_receipt_digest,
            "style_snapshot_digest": verification.style_snapshot_digest,
            "style_registry_receipt_digest": verification.style_registry_receipt_digest,
            "asset_bindings_digest": verification.asset_bindings_digest,
            "asset_authority_receipt_digest": verification.asset_authority_receipt_digest,
            "verified_at": utc_iso(verified_at),
            "expires_at": utc_iso(expires_at),
        }
        return {
            **projection,
            "input_authority_digest": payload_digest(projection),
        }

    def _build_property_material(
        self,
        inputs: Mapping[str, object],
        verification: PropertyRetentionPolicyVerification,
        evidence: Mapping[str, object],
        deadlines: Mapping[str, list[str]],
        deadline_instants: tuple[datetime, ...],
        input_authority: Mapping[str, object],
        *,
        compose_at: datetime,
    ) -> dict[str, object]:
        packet_created = inputs["packet_created"]
        if not isinstance(packet_created, datetime):
            raise SpatialStateError("property_source_packet_created_at_invalid")
        policy_expires = verification.policy_expires_at.astimezone(UTC).replace(microsecond=0)
        try:
            retention_expires = fixed_material_retention_expiry(
                source_packet_created_at=packet_created,
                compose_acceptance_at=compose_at,
                source_retention_days=verification.source_retention_days,
                policy_expires_at=policy_expires,
                shorter_deadlines=deadline_instants,
            )
        except ValueError:
            raise SpatialStateError("property_retention_resolution_failed") from None
        retention_anchor = min(packet_created, compose_at)
        evidence_digest = payload_digest(evidence)
        deadlines_digest = payload_digest(deadlines)
        target_binding = {
            "execution_target": deepcopy(self._execution_target),
            "authorization_owner": PROPERTY_AUTHORIZATION_OWNER,
            "policy_id": PROPERTY_POLICY_ID,
            "policy_digest": PROPERTY_POLICY_DIGEST,
            "policy_evidence_digest": evidence_digest,
            "retention_deadlines_digest": deadlines_digest,
            "input_authority_digest": input_authority["input_authority_digest"],
            "input_authority_verified_at": input_authority["verified_at"],
            "input_authority_expires_at": input_authority["expires_at"],
            "source_authority_receipt_digest": input_authority[
                "source_authority_receipt_digest"
            ],
            "style_registry_receipt_digest": input_authority[
                "style_registry_receipt_digest"
            ],
            "asset_authority_receipt_digest": input_authority[
                "asset_authority_receipt_digest"
            ],
        }
        execution_target_digest = payload_digest(target_binding)
        request = inputs["request"]
        if not isinstance(request, GovernedSpatialRenderRequestV1):
            raise SpatialStateError("property_execution_inputs_invalid")
        identity_material = {
            "contract_name": "ea.governed_spatial_property_composition_identity.v1",
            "contract_version": "1.0.0",
            "request_id": str(request.request_id),
            "idempotency_key": request.idempotency_key,
            "request_digest": inputs["request_digest"],
            "source_packet_digest": inputs["source_packet_digest"],
            "style_snapshot_digest": inputs["style_snapshot_digest"],
            "asset_bindings_digest": inputs["asset_bindings_digest"],
            "output_contract_digest": inputs["output_contract_digest"],
            "execution_target_digest": execution_target_digest,
            "retention_anchor": utc_iso(retention_anchor),
            "retention_expires_at": utc_iso(retention_expires),
            "input_authority_digest": input_authority["input_authority_digest"],
            "input_authority_verified_at": input_authority["verified_at"],
            "input_authority_expires_at": input_authority["expires_at"],
            "source_authority_receipt_digest": input_authority[
                "source_authority_receipt_digest"
            ],
            "style_registry_receipt_digest": input_authority[
                "style_registry_receipt_digest"
            ],
            "asset_authority_receipt_digest": input_authority[
                "asset_authority_receipt_digest"
            ],
        }
        composition_digest = payload_digest(identity_material)
        try:
            material = GovernedSpatialExecutionMaterialV1.model_validate(
                {
                    "contract_name": "ea.governed_spatial_execution_material.v1",
                    "contract_version": "1.0.0",
                    "composition_digest": composition_digest,
                    "request_digest": inputs["request_digest"],
                    "source_packet_digest": inputs["source_packet_digest"],
                    "style_snapshot_digest": inputs["style_snapshot_digest"],
                    "output_contract_digest": inputs["output_contract_digest"],
                    "execution_target_digest": execution_target_digest,
                    "normalized_request": inputs["request_material"],
                    "normalized_source_packet": inputs["source_material"],
                    "style_snapshot": inputs["style_payload"],
                    "asset_bindings": inputs["assets_payload"],
                    "source_packet_created_at": utc_iso(packet_created),
                    "compose_created_at": utc_iso(compose_at),
                    "retention_expires_at": utc_iso(retention_expires),
                }
            )
        except (ValidationError, ValueError, SpatialExecutionContractError):
            raise SpatialStateError("property_execution_material_invalid") from None
        validate_property_prebuild_material(material)
        digest = execution_material_digest(material)
        return {
            "material": material,
            "material_digest": digest,
            "material_identity": SpatialExecutionMaterialStore.material_identity(composition_digest),
            "composition_digest": composition_digest,
            "execution_target_digest": execution_target_digest,
            "retention_anchor": utc_iso(retention_anchor),
            "retention_expires_at": utc_iso(retention_expires),
            "retention_deadlines_digest": deadlines_digest,
            "policy_evidence_digest": evidence_digest,
        }

    def _property_receipt_bindings(
        self,
        inputs: Mapping[str, object],
        material: Mapping[str, object],
        evidence: Mapping[str, object],
        input_authority: Mapping[str, object],
        *,
        compose_at: datetime,
    ) -> dict[str, object]:
        request = inputs["request"]
        if not isinstance(request, GovernedSpatialRenderRequestV1):
            raise SpatialStateError("property_execution_inputs_invalid")
        return {
            "authorization_owner": PROPERTY_AUTHORIZATION_OWNER,
            "artifact_family": PROPERTY_ARTIFACT_FAMILY,
            "content_profile": PROPERTY_CONTENT_PROFILE,
            "request_id": str(request.request_id),
            "idempotency_key": request.idempotency_key,
            "composition_digest": material["composition_digest"],
            "material_identity": material["material_identity"],
            "material_digest": material["material_digest"],
            "request_digest": inputs["request_digest"],
            "source_packet_digest": inputs["source_packet_digest"],
            "style_snapshot_digest": inputs["style_snapshot_digest"],
            "asset_bindings_digest": inputs["asset_bindings_digest"],
            "output_contract_digest": inputs["output_contract_digest"],
            "execution_target_digest": material["execution_target_digest"],
            "source_packet_created_at": utc_iso(inputs["packet_created"]),  # type: ignore[arg-type]
            "compose_acceptance_at": utc_iso(compose_at),
            "retention_anchor": material["retention_anchor"],
            "retention_expires_at": material["retention_expires_at"],
            "retention_deadlines_digest": material["retention_deadlines_digest"],
            "policy_id": evidence["policy_id"],
            "policy_digest": evidence["policy_digest"],
            "policy_evidence_digest": material["policy_evidence_digest"],
            "policy_approval_ref": evidence["approval_ref"],
            "policy_verifier_ref": evidence["verifier_ref"],
            "policy_verification_receipt_digest": evidence["verification_receipt_digest"],
            "policy_approved_at": evidence["approved_at"],
            "policy_evidence_expires_at": evidence["expires_at"],
            "input_authority_digest": input_authority["input_authority_digest"],
            "input_authority_verified_at": input_authority["verified_at"],
            "input_authority_expires_at": input_authority["expires_at"],
            "source_authority_receipt_digest": input_authority[
                "source_authority_receipt_digest"
            ],
            "style_registry_receipt_digest": input_authority[
                "style_registry_receipt_digest"
            ],
            "asset_authority_receipt_digest": input_authority[
                "asset_authority_receipt_digest"
            ],
        }

    @staticmethod
    def _property_receipt_expiry(
        *,
        compose_at: datetime,
        key_not_after: datetime,
        evidence_expires_at: datetime,
        policy_expires_at: datetime,
        retention_expires_at: datetime,
        input_authority_expires_at: datetime,
    ) -> datetime:
        expiry = min(
            compose_at + timedelta(hours=24),
            key_not_after,
            evidence_expires_at,
            policy_expires_at,
            retention_expires_at,
            input_authority_expires_at,
        )
        if expiry <= compose_at:
            raise SpatialStateError("property_composition_signing_window_insufficient")
        return expiry

    def _verify_property_composition_receipt(
        self,
        receipt: Mapping[str, object],
        *,
        observed_at: datetime,
    ) -> tuple[dict[str, object], datetime]:
        if self._composition_verification_registry is None:
            raise SpatialStateError("property_composition_verification_registry_unavailable")
        try:
            verification = verify_signed_envelope(
                receipt,
                self._composition_verification_registry,
                observed_at=observed_at,
                maximum_receipt_age=timedelta(hours=24),
            )
            key_record = self._composition_verification_registry.resolve(
                *verification.key_identity
            )
        except SpatialCryptoError:
            raise SpatialStateError("property_composition_receipt_unverifiable") from None
        trusted = deepcopy(dict(receipt))
        if set(trusted) != _PROPERTY_COMPOSITION_RECEIPT_MEMBERS:
            raise SpatialStateError("property_composition_receipt_invalid")
        if (
            trusted.get("contract_name") != PROPERTY_COMPOSITION_RECEIPT_CONTRACT_NAME
            or trusted.get("contract_version") != PROPERTY_COMPOSITION_RECEIPT_CONTRACT_VERSION
            or trusted.get("issuer") != self._signer.key_record.issuer
            or trusted.get("environment") != self._signer.key_record.environment
        ):
            raise SpatialStateError("property_composition_receipt_invalid")
        key_not_after = _parse_iso_strict(key_record.not_after)
        if key_not_after is None:
            raise SpatialStateError("property_composition_receipt_unverifiable")
        return trusted, key_not_after

    def _assert_property_receipt_bindings(
        self,
        receipt: Mapping[str, object],
        bindings: Mapping[str, object],
        *,
        compose_at: datetime,
        expected_expires_at: datetime,
    ) -> None:
        expected = {
            "contract_name": PROPERTY_COMPOSITION_RECEIPT_CONTRACT_NAME,
            "contract_version": PROPERTY_COMPOSITION_RECEIPT_CONTRACT_VERSION,
            "issuer": self._signer.key_record.issuer,
            "environment": self._signer.key_record.environment,
            "issued_at": utc_iso(compose_at),
            "expires_at": utc_iso(expected_expires_at),
            **dict(bindings),
        }
        if any(receipt.get(field) != value for field, value in expected.items()):
            raise SpatialIdempotencyConflict("property_composition_replay_conflict")

    def compose_property_execution_material(
        self,
        request: GovernedSpatialRenderRequestV1 | Mapping[str, object],
        *,
        source_packet: GovernedSpatialSourcePacketV1 | Mapping[str, object],
        style_snapshot: GovernedSpatialStyleSnapshotV1 | Mapping[str, object],
        asset_bindings: list[GovernedSpatialAssetBindingV1 | Mapping[str, object]],
        policy_evidence: Mapping[str, object] | None,
        retention_deadlines: Mapping[str, object] | None = None,
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        observed = self._observed(observed_at)
        if self._ledger.root is None:
            raise SpatialStateError("property_persistent_ledger_required")
        try:
            ledger_integrity = self._ledger.integrity_summary()
        except (SpatialStateError, OSError, TypeError, ValueError):
            raise SpatialStateError("property_persistent_ledger_unavailable") from None
        if (
            ledger_integrity.get("status") != "pass"
            or ledger_integrity.get("persistent") is not True
        ):
            raise SpatialStateError("property_persistent_ledger_required")
        if self._material_store is None:
            raise SpatialStateError("property_material_store_unavailable")
        if not self._material_store.authority_guarded_recovery:
            raise SpatialStateError("property_material_store_guarded_recovery_required")
        if self._composition_verification_registry is None:
            raise SpatialStateError("property_composition_verification_registry_unavailable")
        if self._material_store.environment != self._signer.key_record.environment:
            raise SpatialStateError("property_material_store_environment_mismatch")
        if (
            self._material_store.lifecycle_authority
            is not self._ledger.lifecycle_authority
        ):
            raise SpatialStateError(
                "property_material_store_lifecycle_authority_mismatch"
            )
        try:
            request_identity = (
                request
                if isinstance(request, GovernedSpatialRenderRequestV1)
                else GovernedSpatialRenderRequestV1.model_validate(dict(request))
            )
        except (ValidationError, TypeError, ValueError):
            raise SpatialStateError("property_execution_inputs_invalid") from None
        early_existing = self._ledger.find_composition_by_key(
            request_identity.idempotency_key
        )
        if early_existing is not None:
            try:
                early_composition_digest = self._prefixed(
                    early_existing.get("composition_digest")
                )
                early_material_digest = self._prefixed(
                    early_existing.get("material_digest")
                )
            except SpatialStateError:
                raise SpatialStateError("property_composition_receipt_invalid") from None
            with self._ledger.composition_privacy_lifecycle_guard(
                early_composition_digest
            ) as early_lifecycle_guard:
                if early_lifecycle_guard.privacy_status is not None:
                    self._material_store.preemptive_tombstone(
                        early_composition_digest,
                        early_material_digest,
                        lifecycle_guard=early_lifecycle_guard,
                    )
                    raise SpatialPrivacyError("property_privacy_tombstone_active")
            self._verify_property_composition_receipt(
                early_existing,
                observed_at=observed,
            )
        if self._property_input_authority_verifier is None:
            raise SpatialStateError("property_input_authority_verifier_unavailable")
        first_verification = self.verify_property_execution_authority(
            policy_evidence, observed_at=observed
        )
        evidence, _, evidence_expires = self._property_policy_evidence(policy_evidence)
        deadlines, deadline_instants = self._normalize_property_retention_deadlines(
            retention_deadlines
        )
        inputs = self._property_material_inputs(
            request,
            source_packet,
            style_snapshot,
            asset_bindings,
            observed=observed,
        )
        first_input_authority = self._verify_property_input_authority(
            inputs,
            observed_at=observed,
        )
        input_authority_expires_at = _parse_iso_strict(
            first_input_authority.get("expires_at")
        )
        if input_authority_expires_at is None:
            raise SpatialStateError("property_input_authority_chronology_invalid")
        parsed_request = inputs["request"]
        if not isinstance(parsed_request, GovernedSpatialRenderRequestV1):
            raise SpatialStateError("property_execution_inputs_invalid")
        existing = self._ledger.find_composition_by_key(parsed_request.idempotency_key)
        idempotent_replay = existing is not None

        if existing is not None:
            trusted, signing_key_not_after = self._verify_property_composition_receipt(
                existing, observed_at=observed
            )
            compose_at = _parse_iso_strict(trusted.get("compose_acceptance_at"))
            if compose_at is None or compose_at > observed:
                raise SpatialStateError("property_composition_receipt_invalid")
            resolved = self._build_property_material(
                inputs,
                first_verification,
                evidence,
                deadlines,
                deadline_instants,
                first_input_authority,
                compose_at=compose_at,
            )
            bindings = self._property_receipt_bindings(
                inputs,
                resolved,
                evidence,
                first_input_authority,
                compose_at=compose_at,
            )
            receipt_expiry = self._property_receipt_expiry(
                compose_at=compose_at,
                key_not_after=signing_key_not_after,
                evidence_expires_at=evidence_expires,
                policy_expires_at=first_verification.policy_expires_at,
                retention_expires_at=_parse_iso_strict(resolved["retention_expires_at"]),  # type: ignore[arg-type]
                input_authority_expires_at=input_authority_expires_at,
            )
            self._assert_property_receipt_bindings(
                trusted,
                bindings,
                compose_at=compose_at,
                expected_expires_at=receipt_expiry,
            )
            receipt = trusted
            expected_receipt_expiry = receipt_expiry
        else:
            compose_at = observed
            resolved = self._build_property_material(
                inputs,
                first_verification,
                evidence,
                deadlines,
                deadline_instants,
                first_input_authority,
                compose_at=compose_at,
            )
            collision = self._ledger.find_composition(resolved["composition_digest"])  # type: ignore[arg-type]
            if collision is not None and collision.get("idempotency_key") != parsed_request.idempotency_key:
                raise SpatialIdempotencyConflict("property_composition_identity_collision")
            bindings = self._property_receipt_bindings(
                inputs,
                resolved,
                evidence,
                first_input_authority,
                compose_at=compose_at,
            )
            signer_not_before = _parse_iso_strict(self._signer.key_record.not_before)
            signer_not_after = _parse_iso_strict(self._signer.key_record.not_after)
            if (
                signer_not_before is None
                or signer_not_after is None
                or compose_at < signer_not_before
            ):
                raise SpatialStateError("property_composition_signing_window_invalid")
            receipt_expiry = self._property_receipt_expiry(
                compose_at=compose_at,
                key_not_after=signer_not_after,
                evidence_expires_at=evidence_expires,
                policy_expires_at=first_verification.policy_expires_at,
                retention_expires_at=_parse_iso_strict(resolved["retention_expires_at"]),  # type: ignore[arg-type]
                input_authority_expires_at=input_authority_expires_at,
            )
            candidate = sign_envelope(
                {
                    "contract_name": PROPERTY_COMPOSITION_RECEIPT_CONTRACT_NAME,
                    "contract_version": PROPERTY_COMPOSITION_RECEIPT_CONTRACT_VERSION,
                    "issuer": self._signer.key_record.issuer,
                    "environment": self._signer.key_record.environment,
                    "issued_at": utc_iso(compose_at),
                    "expires_at": utc_iso(receipt_expiry),
                    **bindings,
                },
                self._signer,
            )
            trusted_candidate, candidate_key_not_after = self._verify_property_composition_receipt(
                candidate, observed_at=observed
            )
            candidate_expiry = self._property_receipt_expiry(
                compose_at=compose_at,
                key_not_after=candidate_key_not_after,
                evidence_expires_at=evidence_expires,
                policy_expires_at=first_verification.policy_expires_at,
                retention_expires_at=_parse_iso_strict(resolved["retention_expires_at"]),  # type: ignore[arg-type]
                input_authority_expires_at=input_authority_expires_at,
            )
            self._assert_property_receipt_bindings(
                trusted_candidate,
                bindings,
                compose_at=compose_at,
                expected_expires_at=candidate_expiry,
            )
            saved = self._ledger.save_composition(trusted_candidate)
            receipt, saved_key_not_after = self._verify_property_composition_receipt(
                saved, observed_at=observed
            )
            saved_expiry = self._property_receipt_expiry(
                compose_at=compose_at,
                key_not_after=saved_key_not_after,
                evidence_expires_at=evidence_expires,
                policy_expires_at=first_verification.policy_expires_at,
                retention_expires_at=_parse_iso_strict(resolved["retention_expires_at"]),  # type: ignore[arg-type]
                input_authority_expires_at=input_authority_expires_at,
            )
            self._assert_property_receipt_bindings(
                receipt,
                bindings,
                compose_at=compose_at,
                expected_expires_at=saved_expiry,
            )
            expected_receipt_expiry = saved_expiry

        material = resolved["material"]
        if not isinstance(material, GovernedSpatialExecutionMaterialV1):
            raise SpatialStateError("property_execution_material_invalid")
        composition_digest = resolved["composition_digest"]
        if not isinstance(composition_digest, str):
            raise SpatialStateError("property_execution_material_invalid")
        with self._ledger.composition_privacy_lifecycle_guard(
            composition_digest
        ) as lifecycle_guard:
            if lifecycle_guard.privacy_status is not None:
                self._material_store.preemptive_tombstone(
                    composition_digest,
                    resolved["material_digest"],  # type: ignore[arg-type]
                    lifecycle_guard=lifecycle_guard,
                )
                raise SpatialPrivacyError("property_privacy_tombstone_active")
            seal_observed = self._observed(None)
            trusted_at_seal, _ = self._verify_property_composition_receipt(
                receipt,
                observed_at=seal_observed,
            )
            self._assert_property_receipt_bindings(
                trusted_at_seal,
                bindings,
                compose_at=compose_at,
                expected_expires_at=expected_receipt_expiry,
            )
            try:
                material = GovernedSpatialExecutionMaterialV1.model_validate(
                    material.model_dump(mode="json")
                )
            except ValidationError:
                raise SpatialStateError("property_execution_material_invalid") from None
            second_verification = self.verify_property_execution_authority(
                policy_evidence, observed_at=seal_observed
            )
            if second_verification != first_verification:
                raise SpatialStateError("property_policy_changed_before_seal")
            second_input_authority = self._verify_property_input_authority(
                inputs,
                observed_at=seal_observed,
            )
            if second_input_authority != first_input_authority:
                raise SpatialStateError("property_input_authority_changed_before_seal")
            self._material_store.recover_pending_intent(
                material,
                lifecycle_guard=lifecycle_guard,
            )
            self._material_store.seal(
                material,
                lifecycle_guard=lifecycle_guard,
            )
            loaded = self._material_store.load(
                composition_digest,
                lifecycle_guard=lifecycle_guard,
            )
            if (
                execution_material_digest(loaded) != resolved["material_digest"]
                or loaded.model_dump(mode="json") != material.model_dump(mode="json")
            ):
                raise SpatialStateError("property_sealed_material_verification_failed")
            validate_property_prebuild_receipt_material(receipt, loaded)
        return {
            "composition_digest": resolved["composition_digest"],
            "material_identity": resolved["material_identity"],
            "material_digest": resolved["material_digest"],
            "retention_anchor": resolved["retention_anchor"],
            "retention_expires_at": resolved["retention_expires_at"],
            "composition_receipt_digest": payload_digest(receipt),
            "idempotent_replay": idempotent_replay,
        }

    def property_prebuild_coordinator(
        self,
        *,
        output_allocation_planner: PropertyOutputAllocationPlanner | None = None,
        artifact_verifier: PropertyArtifactEvidenceVerifier | None = None,
        reconciliation_store: PropertyPrebuildReconciliationStore | None = None,
        telemetry_sink: Callable[[Mapping[str, object]], None] | None = None,
    ) -> PropertyPrebuildCoordinator:
        if self._material_store is None:
            raise SpatialStateError("property_material_store_unavailable")

        def verify_receipt(
            receipt: Mapping[str, object], *, observed_at: datetime
        ) -> Mapping[str, object]:
            trusted, _ = self._verify_property_composition_receipt(
                receipt, observed_at=observed_at
            )
            return trusted

        def verify_policy(
            evidence: Mapping[str, object] | None, *, observed_at: datetime
        ) -> Mapping[str, object]:
            verification = self.verify_property_execution_authority(
                evidence, observed_at=observed_at
            )
            return {
                "state": verification.state,
                "policy_path": verification.policy_path,
                "policy_id": verification.policy_id,
                "policy_digest": verification.policy_digest,
                "policy_mode": verification.policy_mode,
                "policy_expires_at": verification.policy_expires_at,
                "source_retention_days": verification.source_retention_days,
                "approval_ref": verification.approval_ref,
                "verifier_ref": verification.verifier_ref,
                "verification_receipt_digest": verification.verification_receipt_digest,
                "evidence_digest": verification.evidence_digest,
                "independent_acceptance_digest": verification.independent_acceptance_digest,
                "independent_acceptance_mode": verification.independent_acceptance_mode,
                "regular_file": verification.regular_file,
                "independent_acceptance_regular_file": (
                    verification.independent_acceptance_regular_file
                ),
            }

        def verify_input_authority(
            material: GovernedSpatialExecutionMaterialV1, *, observed_at: datetime
        ) -> Mapping[str, object]:
            packet_created = _parse_iso_strict(material.source_packet_created_at)
            if packet_created is None:
                raise SpatialStateError("property_source_packet_created_at_invalid")
            assets_payload = [
                asset.model_dump(mode="json") for asset in material.asset_bindings
            ]
            inputs = {
                "request_material": deepcopy(material.normalized_request),
                "source_material": deepcopy(material.normalized_source_packet),
                "style": material.style_snapshot,
                "assets": list(material.asset_bindings),
                "packet_created": packet_created,
                "request_digest": material.request_digest,
                "source_packet_digest": material.source_packet_digest,
                "style_snapshot_digest": material.style_snapshot_digest,
                "asset_bindings_digest": payload_digest(assets_payload),
                "output_contract_digest": material.output_contract_digest,
            }
            return self._verify_property_input_authority(
                inputs, observed_at=observed_at
            )

        return PropertyPrebuildCoordinator(
            ledger=self._ledger,
            material_store=self._material_store,
            receipt_verifier=verify_receipt,
            policy_verifier=verify_policy,
            input_authority_verifier=verify_input_authority,
            output_allocation_planner=output_allocation_planner,
            artifact_verifier=artifact_verifier,
            reconciliation_store=reconciliation_store,
            telemetry_sink=telemetry_sink,
            now=self._now,
        )

    def compose_audit(
        self,
        request: GovernedSpatialRenderRequestV1 | Mapping[str, object],
        *,
        source_packet: GovernedSpatialSourcePacketV1 | Mapping[str, object],
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        observed = self._observed(observed_at)
        parsed_request = (
            request
            if isinstance(request, GovernedSpatialRenderRequestV1)
            else GovernedSpatialRenderRequestV1.model_validate(dict(request))
        )
        parsed_source = (
            source_packet
            if isinstance(source_packet, GovernedSpatialSourcePacketV1)
            else GovernedSpatialSourcePacketV1.model_validate(dict(source_packet))
        )
        self._validate_cross_source(parsed_request, parsed_source)
        route_visit_count = len(parsed_request.spatial_plan.route_room_ids)
        route_revisit_count = route_visit_count - len(set(parsed_request.spatial_plan.route_room_ids))
        artifact_family, content_profile = self._artifact_profile(parsed_request)
        if self._execution_target is not None:
            if self._execution_target["artifact_family"] != artifact_family:
                raise SpatialStateError("execution_target_artifact_family_mismatch")
            if self._execution_target["content_profile"] != content_profile:
                raise SpatialStateError("execution_target_content_profile_mismatch")
            execution_target = deepcopy(self._execution_target)
            execution_target["binding_state"] = "bound"
        else:
            execution_target = {
                "artifact_family": artifact_family,
                "content_profile": content_profile,
                "environment": self._signer.key_record.environment,
                "provider_route_digest": None,
                "gate_versions": {},
                "binding_state": "unbound",
            }
        execution_target_digest = payload_digest(execution_target)
        request_material = normalized_request_material(parsed_request)
        source_material = normalize_compatibility_numbers(parsed_source.model_dump(mode="json"))
        request_digest = payload_digest(request_material)
        source_packet_digest = payload_digest(source_material)
        source_digest = self._prefixed(parsed_source.source_digest)
        style_digest = payload_digest(request_material["style"])
        output_digest = payload_digest(
            {
                "camera": request_material["camera"],
                "output": request_material["output"],
                "artifact": request_material["artifact"],
            }
        )
        composition_digest = payload_digest(
            {
                "request_digest": request_digest,
                "source_digest": source_digest,
                "source_packet_digest": source_packet_digest,
                "style_digest": style_digest,
                "output_contract_digest": output_digest,
                "execution_target_digest": execution_target_digest,
            }
        )
        material_digest = payload_digest(
            {
                "idempotency_key": parsed_request.idempotency_key,
                "composition_digest": composition_digest,
            }
        )
        existing = self._ledger.find_composition_by_key(parsed_request.idempotency_key)
        if existing is not None:
            if existing.get("material_digest") != material_digest:
                self._emit(
                    "composition_conflicted",
                    request_digest=request_digest,
                    composition_digest=composition_digest,
                    reason_codes=["idempotency_conflict"],
                    route_visit_count=route_visit_count,
                    route_revisit_count=route_revisit_count,
                )
                raise SpatialIdempotencyConflict("idempotency_key_payload_conflict")
            replay = deepcopy(existing)
            replay["idempotent_replay"] = True
            self._emit(
                "composition_replayed",
                request_digest=request_digest,
                composition_digest=composition_digest,
                route_visit_count=route_visit_count,
                route_revisit_count=route_revisit_count,
            )
            return replay

        issued_at = utc_iso(observed)
        expires_at = utc_iso(observed + timedelta(hours=1))
        receipt = sign_envelope(
            {
                "contract_name": COMPOSITION_RECEIPT_CONTRACT_NAME,
                "contract_version": "r10-route-semantics-v1",
                "issuer": self._signer.key_record.issuer,
                "environment": self._signer.key_record.environment,
                "issued_at": issued_at,
                "expires_at": expires_at,
                "state": AUDIT_ONLY_STATE,
                "status": "accepted",
                "request_id": str(parsed_request.request_id),
                "idempotency_key": parsed_request.idempotency_key,
                "material_digest": material_digest,
                "request_digest": request_digest,
                "source_digest": source_digest,
                "source_packet_digest": source_packet_digest,
                "style_digest": style_digest,
                "output_contract_digest": output_digest,
                "execution_target": execution_target,
                "execution_target_digest": execution_target_digest,
                "composition_digest": composition_digest,
                "parentage": {
                    "request_digest": request_digest,
                    "source_digest": source_digest,
                    "source_packet_digest": source_packet_digest,
                    "style_digest": style_digest,
                },
                "authorization": {
                    "state": "not_present_audit_only",
                    "owner": None,
                    "authorization_ref": None,
                    "issued_at": None,
                    "expires_at": None,
                    "maximum_provider_attempts": 0,
                    "quota_limit_digest": None,
                },
                "idempotency": {
                    "scope_digest": payload_digest(parsed_request.consumer.model_dump(mode="json")),
                    "key_digest": None,
                    "normalized_request_digest": None,
                    "composition_digest": None,
                    "authorization_binding_digest": None,
                },
                "quota": {
                    "state": AUDIT_ONLY_STATE,
                    "reservation_ref_digest": None,
                    "reservation_expires_at": None,
                    "attempt_number": 0,
                    "mutation_token_digest": None,
                    "consumption_receipt_digest": None,
                    "compensation_receipt_digest": None,
                },
                "quota_posture": "audit_only",
                "readiness_projection": "unverified",
                "route_state": "blocked",
                "audit_only": True,
                "provider_job_enqueued": False,
                "quota_mutated": False,
                "idempotent_replay": False,
            },
            self._signer,
        )
        saved = self._ledger.save_composition(receipt)
        self._emit(
            "composition_created",
            state=AUDIT_ONLY_STATE,
            request_digest=request_digest,
            composition_digest=composition_digest,
            quota_actions=0,
            execution_actions=0,
            route_visit_count=route_visit_count,
            route_revisit_count=route_revisit_count,
        )
        return saved

    @staticmethod
    def _authorization_material(
        authorization: GovernedSpatialBuildAuthorization,
        *,
        observed: datetime,
    ) -> dict[str, object]:
        if not authorization.issued_at or not authorization.expires_at or not authorization.quota_limit_digest:
            raise SpatialStateError("complete_build_authorization_required")
        issued = _parse_iso_strict(authorization.issued_at)
        expires = _parse_iso_strict(authorization.expires_at)
        if issued is None or expires is None or issued >= expires:
            raise SpatialStateError("build_authorization_chronology_invalid")
        if not issued <= observed <= expires:
            raise SpatialStateError("build_authorization_not_current")
        return {
            "owner": authorization.requested_by_ref,
            "state": "valid",
            "authorization_ref": authorization.authorization_ref,
            "issued_at": utc_iso(issued),
            "expires_at": utc_iso(expires),
            "maximum_provider_attempts": authorization.maximum_provider_attempts,
            "quota_limit_digest": GovernedSpatialOrchestrator._prefixed(authorization.quota_limit_digest),
        }

    @staticmethod
    def _empty_quota(state: str) -> dict[str, object]:
        return {
            "state": state,
            "reservation_ref_digest": None,
            "reservation_expires_at": None,
            "attempt_number": 0,
            "mutation_token_digest": None,
            "consumption_receipt_digest": None,
            "compensation_receipt_digest": None,
        }

    def _generic_blocked_receipt(
        self,
        *,
        key: str,
        build_request_digest: str,
        composition: Mapping[str, object] | None,
        reasons: list[str],
        observed: datetime,
    ) -> dict[str, object]:
        parentage = {
            "request_digest": composition.get("request_digest") if composition else None,
            "source_digest": composition.get("source_digest") if composition else None,
            "source_packet_digest": composition.get("source_packet_digest") if composition else None,
            "style_digest": composition.get("style_digest") if composition else None,
        }
        return {
            "contract_name": BUILD_RECEIPT_CONTRACT_NAME,
            "contract_version": "r9-v1",
            "generated_at": utc_iso(observed),
            "status": GENERIC_BLOCKED_STATE,
            "state": GENERIC_BLOCKED_STATE,
            "build_id": f"build-{build_request_digest[7:27]}",
            "build_idempotency_key": key,
            "build_request_digest": build_request_digest,
            "composition_digest": composition.get("composition_digest") if composition else "",
            "parentage": parentage,
            "authorization": {
                "state": "blocked",
                "owner": None,
                "authorization_ref": None,
                "issued_at": None,
                "expires_at": None,
                "maximum_provider_attempts": 0,
                "quota_limit_digest": None,
            },
            "idempotency": {
                "scope_digest": payload_digest("generic-blocked"),
                "key_digest": None,
                "normalized_request_digest": None,
                "composition_digest": None,
                "authorization_binding_digest": None,
            },
            "quota": self._empty_quota(GENERIC_BLOCKED_STATE),
            "quota_posture": "blocked",
            "readiness_projection": "blocked",
            "route_state": "blocked",
            "blocked_reasons": _unique(reasons),
            "output_digest": None,
            "output_manifest_ref": None,
            "product_projection": {
                "state": "blocked",
                "reason": reasons[0] if reasons else "blocked",
                "artifact_ref": "",
                "provider_details_exposed": False,
            },
        }

    def _transition(
        self,
        key: str,
        prior: Mapping[str, object],
        state: str,
        *,
        observed: datetime,
        quota_updates: Mapping[str, object] | None = None,
        **updates: object,
    ) -> dict[str, object]:
        receipt = deepcopy(dict(prior))
        receipt.pop("transition_sequence", None)
        receipt.pop("prior_receipt_digest", None)
        receipt["state"] = state
        receipt["status"] = state
        receipt["generated_at"] = utc_iso(observed)
        quota = _dict(receipt.get("quota"))
        quota["state"] = state
        quota.update(dict(quota_updates or {}))
        receipt["quota"] = quota
        receipt.update(updates)
        receipt["product_projection"] = self._public_projection(receipt)
        return self._ledger.append_build_transition(key, receipt)

    @staticmethod
    def _operation_intent(
        operation: str,
        *,
        build_request_digest: str,
        attempt_number: int,
    ) -> dict[str, object]:
        material = {
            "operation": operation,
            "build_request_digest": build_request_digest,
            "attempt_number": attempt_number,
        }
        return {
            "operation": operation,
            "attempt_number": attempt_number,
            "intent_digest": payload_digest(material),
            "outcome": "pending_or_unknown",
        }

    @staticmethod
    def _operation_failure_evidence(
        operation: str,
        *,
        build_request_digest: str,
        attempt_number: int,
        observed: datetime,
        error: Exception,
    ) -> dict[str, object]:
        material = {
            "operation": operation,
            "build_request_digest": build_request_digest,
            "attempt_number": attempt_number,
            "observed_at": utc_iso(observed),
            "error_class": type(error).__name__,
        }
        return {
            **material,
            "outcome": "unknown",
            "evidence_digest": payload_digest(material),
        }

    @staticmethod
    def _require_adapter_digest(result: Mapping[str, object], field: str) -> str:
        value = _clean(result.get(field))
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise SpatialStateError(f"adapter_{field}_invalid")
        return value

    @staticmethod
    def _runtime_evidence_errors(
        evidence: Mapping[str, object],
        *,
        observed: datetime,
        execution_target: Mapping[str, object],
    ) -> list[str]:
        errors: list[str] = []

        def timestamp(value: object, path: str) -> datetime | None:
            parsed = _parse_iso_strict(value)
            if parsed is None:
                errors.append(f"timestamp_offset_required:{path}")
            return parsed

        def current_window(
            issued: datetime | None,
            expires: datetime | None,
            path: str,
            *,
            maximum_age: timedelta | None = None,
        ) -> None:
            if issued is None or expires is None:
                return
            if issued >= expires:
                errors.append(f"chronology_invalid:{path}")
                return
            if not issued <= observed <= expires:
                errors.append(f"not_current:{path}")
            if maximum_age is not None and observed - issued > maximum_age:
                errors.append(f"maximum_age_exceeded:{path}")

        def scan_timestamps(value: object, path: str = "receipt") -> None:
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    nested_path = f"{path}.{key}"
                    if str(key).endswith("_at") and nested is not None and _parse_iso_strict(nested) is None:
                        errors.append(f"timestamp_offset_required:{nested_path}")
                    scan_timestamps(nested, nested_path)
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    scan_timestamps(nested, f"{path}[{index}]")

        scan_timestamps(evidence)
        artifact_family = evidence.get("artifact_family")
        family_maximums = {
            "runsite_continuous_walkthrough": timedelta(hours=24),
            "runsite_private_encounter_preview": timedelta(hours=12),
        }
        family_maximum = family_maximums.get(str(artifact_family))
        if family_maximum is None:
            errors.append("artifact_family_unsupported")
        issued_at = timestamp(evidence.get("issued_at"), "receipt.issued_at")
        expires_at = timestamp(evidence.get("expires_at"), "receipt.expires_at")
        current_window(
            issued_at,
            expires_at,
            "artifact_receipt",
            maximum_age=family_maximum,
        )
        if issued_at is not None and expires_at is not None and family_maximum is not None:
            if expires_at - issued_at > family_maximum:
                errors.append("artifact_receipt_duration_exceeded")

        for field in ("artifact_family", "content_profile", "environment", "provider_route_digest"):
            if evidence.get(field) != execution_target.get(field):
                errors.append(f"execution_target_mismatch:{field}")
        if _dict(evidence.get("gate_versions")) != _dict(execution_target.get("gate_versions")):
            errors.append("execution_target_mismatch:gate_versions")

        target_gates = _dict(execution_target.get("gate_versions"))
        gate_key_by_family = {
            "canonical_compose_validator_exact_version": "compose",
            "quota_snapshot": "quota",
            "kill_switch": "quota",
        }
        evidence_refs = evidence.get("evidence_refs")
        if not isinstance(evidence_refs, list):
            errors.append("evidence_refs_required")
            evidence_refs = []
        for index, raw_row in enumerate(evidence_refs):
            if not isinstance(raw_row, Mapping):
                errors.append(f"evidence_ref_invalid:{index}")
                continue
            row = dict(raw_row)
            family = _clean(row.get("evidence_family"))
            ref_issued = timestamp(row.get("issued_at"), f"evidence_refs[{index}].issued_at")
            ref_expires = timestamp(row.get("expires_at"), f"evidence_refs[{index}].expires_at")
            maximum_age = None
            if family == "canonical_compose_validator_exact_version":
                maximum_age = timedelta(hours=720)
            elif family == "browser_mobile_accessibility":
                maximum_age = timedelta(hours=168)
            elif family in {"quota_snapshot", "kill_switch"}:
                maximum_age = timedelta(minutes=5)
            current_window(ref_issued, ref_expires, f"evidence_ref:{family or index}", maximum_age=maximum_age)
            if expires_at is not None and ref_expires is not None and expires_at > ref_expires:
                errors.append(f"top_level_expiry_exceeds:evidence_ref:{family or index}")
            gate_key = gate_key_by_family.get(family)
            if gate_key is not None and row.get("gate_version") != target_gates.get(gate_key):
                errors.append(f"evidence_gate_version_mismatch:{family}")

        quota = _dict(evidence.get("quota"))
        snapshot_issued = timestamp(quota.get("snapshot_issued_at"), "quota.snapshot_issued_at")
        snapshot_expires = timestamp(quota.get("snapshot_expires_at"), "quota.snapshot_expires_at")
        current_window(
            snapshot_issued,
            snapshot_expires,
            "quota_snapshot",
            maximum_age=timedelta(minutes=5),
        )
        if expires_at is not None and snapshot_expires is not None and expires_at > snapshot_expires:
            errors.append("top_level_expiry_exceeds:quota_snapshot")

        kill_switch = _dict(evidence.get("kill_switch"))
        kill_issued = timestamp(kill_switch.get("issued_at"), "kill_switch.issued_at")
        kill_expires = timestamp(kill_switch.get("expires_at"), "kill_switch.expires_at")
        current_window(
            kill_issued,
            kill_expires,
            "kill_switch",
            maximum_age=timedelta(minutes=5),
        )
        if expires_at is not None and kill_expires is not None and expires_at > kill_expires:
            errors.append("top_level_expiry_exceeds:kill_switch")

        authorization = _dict(evidence.get("authorization"))
        authorization_issued = timestamp(authorization.get("issued_at"), "authorization.issued_at")
        authorization_expires = timestamp(authorization.get("expires_at"), "authorization.expires_at")
        current_window(
            authorization_issued,
            authorization_expires,
            "consumer_authorization",
            maximum_age=timedelta(minutes=15),
        )
        if expires_at is not None and authorization_expires is not None and expires_at > authorization_expires:
            errors.append("top_level_expiry_exceeds:consumer_authorization")

        reservation_ref = quota.get("reservation_ref_digest")
        reservation_expires_raw = quota.get("reservation_expires_at")
        if reservation_ref is not None or reservation_expires_raw is not None:
            reservation_expires = timestamp(reservation_expires_raw, "quota.reservation_expires_at")
            if reservation_expires is not None:
                if reservation_expires <= observed:
                    errors.append("reservation_not_current")
                if snapshot_issued is None or reservation_expires <= snapshot_issued:
                    errors.append("reservation_chronology_invalid")
                elif reservation_expires - snapshot_issued > timedelta(minutes=30):
                    errors.append("reservation_lease_exceeds_30_minutes")
                if expires_at is not None and expires_at > reservation_expires:
                    errors.append("top_level_expiry_exceeds:reservation")
        return list(dict.fromkeys(errors))

    def _composition_execution_target(
        self,
        composition: Mapping[str, object] | None,
    ) -> tuple[dict[str, object] | None, list[str]]:
        if composition is None:
            return None, []
        raw_target = _dict(composition.get("execution_target"))
        if raw_target.get("binding_state") != "bound":
            return None, ["execution_target_not_bound"]
        target_material = dict(raw_target)
        target_material.pop("binding_state", None)
        try:
            target = self._normalize_execution_target(target_material)
        except SpatialStateError as exc:
            return None, [str(exc)]
        if target is None:
            return None, ["execution_target_not_bound"]
        if composition.get("execution_target_digest") != payload_digest(raw_target):
            return None, ["execution_target_digest_mismatch"]
        if composition.get("environment") != target.get("environment"):
            return None, ["composition_execution_environment_mismatch"]
        return target, []

    def _adapter_execution_target_errors(
        self,
        expected: Mapping[str, object] | None,
    ) -> list[str]:
        if expected is None or self._execution_adapter is None:
            return []
        resolver = getattr(self._execution_adapter, "execution_target_binding", None)
        if not callable(resolver):
            return ["execution_adapter_target_binding_missing"]
        try:
            actual = self._normalize_execution_target(resolver())
        except Exception:
            return ["execution_adapter_target_binding_invalid"]
        if actual != dict(expected):
            return ["execution_adapter_target_binding_mismatch"]
        return []

    def build(
        self,
        authorization: GovernedSpatialBuildAuthorization | Mapping[str, object],
        *,
        evidence_envelope: Mapping[str, object] | None,
        evidence_registry: CanonicalEd25519KeyRegistry | None,
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        observed = self._observed(observed_at)
        parsed = (
            authorization
            if isinstance(authorization, GovernedSpatialBuildAuthorization)
            else GovernedSpatialBuildAuthorization.model_validate(dict(authorization))
        )
        composition_digest = parsed.accepted_composition_digest.removeprefix("sha256:")
        composition = self._ledger.find_composition(f"sha256:{composition_digest}") or self._ledger.find_composition(
            composition_digest
        )
        build_request_digest = payload_digest(
            {
                "authorization": normalize_compatibility_numbers(parsed.model_dump(mode="json")),
                "evidence_digest": payload_digest(evidence_envelope) if evidence_envelope is not None else None,
            }
        )
        existing = self._ledger.find_build(parsed.idempotency_key)
        if existing is not None:
            if existing.get("build_request_digest") != build_request_digest:
                raise SpatialIdempotencyConflict("build_idempotency_key_payload_conflict")
            replay = deepcopy(existing)
            replay["idempotent_replay"] = True
            replay["product_projection"] = self._public_projection(replay)
            replay_privacy_blocked = replay["product_projection"].get("privacy_tombstone_active") is True
            self._emit(
                "build_replayed",
                state=existing.get("state"),
                build_request_digest=build_request_digest,
                reason_codes=["privacy_tombstone_active"] if replay_privacy_blocked else [],
            )
            return replay

        blocked: list[str] = []
        authorization_material: dict[str, object] | None = None
        if composition is None or composition.get("status") != "accepted":
            blocked.append("accepted_composition_required")
        execution_target, execution_target_errors = self._composition_execution_target(composition)
        blocked.extend(execution_target_errors)
        try:
            authorization_material = self._authorization_material(parsed, observed=observed)
        except SpatialStateError as exc:
            blocked.append(str(exc))
        scope_digest: str | None = None
        if composition is not None:
            try:
                scope_digest = self._prefixed(composition.get("composition_digest"))
            except SpatialStateError:
                blocked.append("accepted_composition_lineage_invalid")
        if scope_digest is not None and self._ledger.privacy_status(scope_digest) is not None:
            blocked.append("privacy_tombstone_active")

        expected_idempotency: dict[str, object] | None = None
        if composition is not None and authorization_material is not None:
            try:
                expected_idempotency = {
                    "scope_digest": payload_digest(
                        {
                            "composition_digest": f"sha256:{composition_digest}",
                            "authorization_ref": parsed.authorization_ref,
                        }
                    ),
                    "key_digest": payload_digest(parsed.idempotency_key),
                    "normalized_request_digest": self._prefixed(composition.get("request_digest")),
                    "composition_digest": f"sha256:{composition_digest}",
                    "authorization_binding_digest": authorization_binding_digest(authorization_material),
                }
            except SpatialStateError:
                blocked.append("accepted_composition_lineage_invalid")

        verified_evidence: Mapping[str, object] | None = None
        if evidence_envelope is None or evidence_registry is None:
            blocked.append("signed_build_evidence_required")
        else:
            try:
                artifact_family = evidence_envelope.get("artifact_family")
                maximum_receipt_age = {
                    "runsite_continuous_walkthrough": timedelta(hours=24),
                    "runsite_private_encounter_preview": timedelta(hours=12),
                }.get(str(artifact_family))
                if maximum_receipt_age is None:
                    raise SpatialStateError("signed_build_evidence_artifact_family_unsupported")
                verify_signed_envelope(
                    evidence_envelope,
                    evidence_registry,
                    observed_at=observed,
                    maximum_receipt_age=maximum_receipt_age,
                )
                validate_capability_quota_evidence_semantics(evidence_envelope)
                if execution_target is None:
                    raise SpatialStateError("execution_target_not_bound")
                runtime_errors = self._runtime_evidence_errors(
                    evidence_envelope,
                    observed=observed,
                    execution_target=execution_target,
                )
                if runtime_errors:
                    raise SpatialStateError("runtime_evidence_invalid:" + ";".join(runtime_errors))
                verified_evidence = evidence_envelope
            except (ValueError, SpatialCryptoError) as exc:
                code = getattr(exc, "code", str(exc) or type(exc).__name__)
                blocked.append(f"signed_build_evidence_invalid:{code}")
        if verified_evidence is not None:
            evidence_idempotency = _dict(verified_evidence.get("idempotency"))
            evidence_authorization = _dict(verified_evidence.get("authorization"))
            if authorization_material is None or expected_idempotency is None:
                blocked.append("signed_build_evidence_binding_unavailable")
            else:
                for field in (
                    "state",
                    "owner",
                    "authorization_ref",
                    "issued_at",
                    "expires_at",
                    "maximum_provider_attempts",
                    "quota_limit_digest",
                ):
                    if evidence_authorization.get(field) != authorization_material.get(field):
                        blocked.append(f"signed_build_evidence_authorization_mismatch:{field}")
                for field in (
                    "scope_digest",
                    "key_digest",
                    "normalized_request_digest",
                    "composition_digest",
                    "authorization_binding_digest",
                ):
                    if evidence_idempotency.get(field) != expected_idempotency.get(field):
                        blocked.append(f"signed_build_evidence_idempotency_mismatch:{field}")
            if verified_evidence.get("capability_state") != "verified":
                blocked.append("signed_build_evidence_capability_unverified")
            if verified_evidence.get("quota_posture") != "build_allowed":
                blocked.append("signed_build_evidence_quota_blocked")
            if _dict(verified_evidence.get("kill_switch")).get("state") != "route_allowed":
                blocked.append("signed_build_evidence_route_blocked")
        if self._quota_adapter is None or self._execution_adapter is None:
            blocked.append("execution_boundaries_disabled")
        blocked.extend(self._adapter_execution_target_errors(execution_target))

        if blocked:
            receipt = self._generic_blocked_receipt(
                key=parsed.idempotency_key,
                build_request_digest=build_request_digest,
                composition=composition,
                reasons=blocked,
                observed=observed,
            )
            receipt["product_projection"] = self._public_projection(receipt)
            saved = self._ledger.save_build(parsed.idempotency_key, receipt)
            self._emit(
                "build_blocked",
                state=GENERIC_BLOCKED_STATE,
                build_request_digest=build_request_digest,
                reason_codes=blocked,
                quota_actions=0,
                execution_actions=0,
            )
            saved["product_projection"] = self._public_projection(saved)
            return saved

        if (
            authorization_material is None
            or expected_idempotency is None
            or composition is None
            or execution_target is None
        ):
            raise SpatialStateError("validated_build_lineage_unavailable")
        idempotency = expected_idempotency
        parentage = {
            "request_digest": self._prefixed(composition.get("request_digest")),
            "source_digest": self._prefixed(composition.get("source_digest")),
            "source_packet_digest": self._prefixed(composition.get("source_packet_digest")),
            "style_digest": self._prefixed(composition.get("style_digest")),
        }
        initial = {
            "contract_name": BUILD_RECEIPT_CONTRACT_NAME,
            "contract_version": "r9-v1",
            "generated_at": utc_iso(observed),
            "status": "authorization_verified",
            "state": "authorization_verified",
            "build_id": f"build-{build_request_digest[7:27]}",
            "build_idempotency_key": parsed.idempotency_key,
            "build_request_digest": build_request_digest,
            "composition_digest": f"sha256:{composition_digest}",
            "execution_target_digest": composition["execution_target_digest"],
            "parentage": parentage,
            "authorization": authorization_material,
            "idempotency": idempotency,
            "quota": self._empty_quota("authorization_verified"),
            "quota_posture": "build_allowed",
            "readiness_projection": "unverified",
            "route_state": "route_allowed",
            "blocked_reasons": [],
            "output_digest": None,
            "output_manifest_ref": None,
            "idempotent_replay": False,
            "pending_operation": self._operation_intent(
                "reserve",
                build_request_digest=build_request_digest,
                attempt_number=0,
            ),
            "reconciliation_required": True,
            "automatic_retry_allowed": False,
        }
        initial["product_projection"] = self._public_projection(initial)
        try:
            latest = self._ledger.append_build_transition(parsed.idempotency_key, initial)
        except SpatialTransitionError:
            concurrent = self._ledger.find_build(parsed.idempotency_key)
            if concurrent is not None and concurrent.get("build_request_digest") == build_request_digest:
                replay = deepcopy(concurrent)
                replay["idempotent_replay"] = True
                replay["product_projection"] = self._public_projection(replay)
                return replay
            raise
        try:
            reservation = self._quota_adapter.reserve(
                {
                    "build_request_digest": build_request_digest,
                    "authorization_binding_digest": idempotency["authorization_binding_digest"],
                    "execution_target_digest": composition["execution_target_digest"],
                    "operation_intent_digest": _dict(latest.get("pending_operation")).get("intent_digest"),
                }
            )
            reservation_digest = self._require_adapter_digest(reservation, "reservation_ref_digest")
            reservation_expires = _clean(reservation.get("reservation_expires_at"))
            parsed_reservation_expiry = _parse_iso_strict(reservation_expires)
            if parsed_reservation_expiry is None or parsed_reservation_expiry <= observed:
                raise SpatialStateError("adapter_reservation_expires_at_invalid")
        except Exception as exc:
            return self._transition(
                parsed.idempotency_key,
                latest,
                "authorization_verified",
                observed=observed,
                blocked_reasons=["reservation_outcome_unknown"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=None,
                operation_failure_evidence=self._operation_failure_evidence(
                    "reserve",
                    build_request_digest=build_request_digest,
                    attempt_number=0,
                    observed=observed,
                    error=exc,
                ),
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )

        attempt = 1
        latest = self._transition(
            parsed.idempotency_key,
            latest,
            "reservation_held",
            observed=observed,
            quota_updates={
                "reservation_ref_digest": reservation_digest,
                "reservation_expires_at": reservation_expires,
            },
            pending_operation=self._operation_intent(
                "commit_attempt",
                build_request_digest=build_request_digest,
                attempt_number=attempt,
            ),
            reconciliation_required=True,
            automatic_retry_allowed=False,
        )

        try:
            committed = self._quota_adapter.commit_attempt(
                {
                    "build_request_digest": build_request_digest,
                    "attempt_number": attempt,
                    "reservation_ref_digest": reservation_digest,
                    "execution_target_digest": composition["execution_target_digest"],
                    "operation_intent_digest": _dict(latest.get("pending_operation")).get("intent_digest"),
                }
            )
            mutation_digest = self._require_adapter_digest(committed, "mutation_token_digest")
        except Exception as exc:
            return self._transition(
                parsed.idempotency_key,
                latest,
                "reservation_held",
                observed=observed,
                blocked_reasons=["attempt_commit_outcome_unknown"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=None,
                operation_failure_evidence=self._operation_failure_evidence(
                    "commit_attempt",
                    build_request_digest=build_request_digest,
                    attempt_number=attempt,
                    observed=observed,
                    error=exc,
                ),
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )
        latest = self._transition(
            parsed.idempotency_key,
            latest,
            "attempt_committed",
            observed=observed,
            quota_updates={"attempt_number": attempt, "mutation_token_digest": mutation_digest},
            pending_operation=self._operation_intent(
                "execute",
                build_request_digest=build_request_digest,
                attempt_number=attempt,
            ),
            reconciliation_required=True,
            automatic_retry_allowed=False,
        )
        try:
            execution = self._execution_adapter.execute(
                {
                    "composition_digest": f"sha256:{composition_digest}",
                    "build_request_digest": build_request_digest,
                    "attempt_number": attempt,
                    "mutation_token_digest": mutation_digest,
                    "artifact_family": execution_target["artifact_family"],
                    "content_profile": execution_target["content_profile"],
                    "environment": execution_target["environment"],
                    "provider_route_digest": execution_target["provider_route_digest"],
                    "gate_versions": deepcopy(execution_target["gate_versions"]),
                    "execution_target_digest": composition["execution_target_digest"],
                    "operation_intent_digest": _dict(latest.get("pending_operation")).get("intent_digest"),
                }
            )
            if not isinstance(execution, Mapping):
                raise SpatialStateError("adapter_execution_result_invalid")
            execution_state = _clean(execution.get("state"))
        except Exception as exc:
            latest = self._transition(
                parsed.idempotency_key,
                latest,
                "cancelled_reconciliation_pending",
                observed=observed,
                blocked_reasons=["execution_outcome_unknown"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=None,
                operation_failure_evidence=self._operation_failure_evidence(
                    "execute",
                    build_request_digest=build_request_digest,
                    attempt_number=attempt,
                    observed=observed,
                    error=exc,
                ),
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )
            self._emit(
                "build_reconciliation_pending",
                state=latest["state"],
                build_request_digest=build_request_digest,
                attempt_number=attempt,
                quota_actions=2,
                execution_actions=1,
            )
            return latest

        if execution_state in {"retryable_no_charge", "cancelled_no_charge"}:
            return self._transition(
                parsed.idempotency_key,
                latest,
                "cancelled_reconciliation_pending",
                observed=observed,
                blocked_reasons=["attempt_committed_requires_reconciliation_proof"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=None,
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )
        if execution_state != "succeeded":
            return self._transition(
                parsed.idempotency_key,
                latest,
                "cancelled_reconciliation_pending",
                observed=observed,
                blocked_reasons=["execution_charge_unresolved"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=None,
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )

        try:
            output_digest = self._require_adapter_digest(execution, "output_digest")
            output_manifest_ref = _clean(execution.get("output_manifest_ref"))
            if not _safe_ref(output_manifest_ref):
                raise SpatialStateError("adapter_output_manifest_ref_invalid")
        except Exception as exc:
            return self._transition(
                parsed.idempotency_key,
                latest,
                "cancelled_reconciliation_pending",
                observed=observed,
                blocked_reasons=["execution_result_evidence_invalid"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=None,
                operation_failure_evidence=self._operation_failure_evidence(
                    "execute_result_validation",
                    build_request_digest=build_request_digest,
                    attempt_number=attempt,
                    observed=observed,
                    error=exc,
                ),
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )

        latest = self._transition(
            parsed.idempotency_key,
            latest,
            "charge_pending",
            observed=observed,
            pending_operation=self._operation_intent(
                "consume",
                build_request_digest=build_request_digest,
                attempt_number=attempt,
            ),
            reconciliation_required=True,
            automatic_retry_allowed=False,
        )
        try:
            consumption = self._quota_adapter.consume(
                {
                    "build_request_digest": build_request_digest,
                    "attempt_number": attempt,
                    "mutation_token_digest": mutation_digest,
                    "output_digest": output_digest,
                    "operation_intent_digest": _dict(latest.get("pending_operation")).get("intent_digest"),
                }
            )
            consumption_digest = self._require_adapter_digest(consumption, "consumption_receipt_digest")
        except Exception as exc:
            return self._transition(
                parsed.idempotency_key,
                latest,
                "cancelled_reconciliation_pending",
                observed=observed,
                blocked_reasons=["consumption_outcome_unknown"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=None,
                operation_failure_evidence=self._operation_failure_evidence(
                    "consume",
                    build_request_digest=build_request_digest,
                    attempt_number=attempt,
                    observed=observed,
                    error=exc,
                ),
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )

        latest = self._transition(
            parsed.idempotency_key,
            latest,
            "consumed",
            observed=observed,
            quota_updates={"consumption_receipt_digest": consumption_digest},
            output_digest=output_digest,
            output_manifest_ref=output_manifest_ref,
            pending_operation=self._operation_intent(
                "quality_gate",
                build_request_digest=build_request_digest,
                attempt_number=attempt,
            ),
            reconciliation_required=True,
            automatic_retry_allowed=False,
        )
        quality_failure_evidence: dict[str, object] | None = None
        try:
            gate = (
                self._quality_gate(output_digest, _dict(execution.get("quality_metrics")))
                if self._quality_gate is not None
                else {"passed": False, "issues": ["quality_gate_missing"]}
            )
            if not isinstance(gate, Mapping):
                raise SpatialStateError("quality_gate_result_invalid")
            gate = dict(gate)
        except Exception as exc:
            quality_failure_evidence = self._operation_failure_evidence(
                "quality_gate",
                build_request_digest=build_request_digest,
                attempt_number=attempt,
                observed=observed,
                error=exc,
            )
            gate = {"passed": False, "issues": ["quality_gate_outcome_invalid"]}

        if gate.get("passed") is True:
            latest = self._transition(
                parsed.idempotency_key,
                latest,
                "closed_consumed",
                observed=observed,
                quota_posture="closed",
                quality_gate=deepcopy(gate),
                pending_operation=None,
                reconciliation_required=False,
                automatic_retry_allowed=False,
            )
            self._emit(
                "build_closed_consumed",
                state=latest["state"],
                build_request_digest=build_request_digest,
                attempt_number=attempt,
                quota_actions=3,
                execution_actions=1,
            )
            return latest

        latest = self._transition(
            parsed.idempotency_key,
            latest,
            "compensation_pending",
            observed=observed,
            output_digest=None,
            output_manifest_ref=None,
            blocked_reasons=list(gate.get("issues") or ["quality_gate_failed"]),
            quota_posture="blocked",
            readiness_projection="blocked",
            route_state="blocked",
            quality_gate=deepcopy(gate),
            quality_failure_evidence=quality_failure_evidence,
            pending_operation=self._operation_intent(
                "compensate",
                build_request_digest=build_request_digest,
                attempt_number=attempt,
            ),
            reconciliation_required=True,
            automatic_retry_allowed=False,
        )
        compensation_failure_evidence: dict[str, object] | None = None
        try:
            compensation = self._quota_adapter.compensate(
                {
                    "build_request_digest": build_request_digest,
                    "consumption_receipt_digest": consumption_digest,
                    "reason_codes": latest["blocked_reasons"],
                    "operation_intent_digest": _dict(latest.get("pending_operation")).get("intent_digest"),
                }
            )
            compensation_digest = self._require_adapter_digest(
                compensation,
                "compensation_receipt_digest",
            )
            final_state = "compensated" if compensation.get("state") == "compensated" else "compensation_failed_blocked"
        except Exception as exc:
            compensation_failure_evidence = self._operation_failure_evidence(
                "compensate",
                build_request_digest=build_request_digest,
                attempt_number=attempt,
                observed=observed,
                error=exc,
            )
            compensation_digest = str(compensation_failure_evidence["evidence_digest"])
            final_state = "compensation_failed_blocked"
        return self._transition(
            parsed.idempotency_key,
            latest,
            final_state,
            observed=observed,
            quota_updates={"compensation_receipt_digest": compensation_digest},
            output_digest=None,
            output_manifest_ref=None,
            quota_posture="blocked",
            readiness_projection="blocked",
            route_state="blocked",
            compensation_failure_evidence=compensation_failure_evidence,
            pending_operation=None,
            reconciliation_required=False if final_state == "compensated" else True,
            automatic_retry_allowed=False,
        )

    def cancel(self, build_idempotency_key: str, *, observed_at: datetime | None = None) -> dict[str, object]:
        observed = self._observed(observed_at)
        latest = self._ledger.find_build(build_idempotency_key)
        if latest is None:
            raise SpatialStateError("build_not_found")
        state = _clean(latest.get("state"))
        if state in {GENERIC_BLOCKED_STATE, "released", "compensated", "compensation_failed_blocked"}:
            replay = deepcopy(latest)
            replay["product_projection"] = self._public_projection(replay)
            return replay
        if latest.get("reconciliation_required") is True and latest.get("automatic_retry_allowed") is False:
            replay = deepcopy(latest)
            replay["product_projection"] = self._public_projection(replay)
            return replay
        if state == "reservation_held" and self._quota_adapter is not None:
            latest = self._transition(
                build_idempotency_key,
                latest,
                "reservation_held",
                observed=observed,
                blocked_reasons=["release_requested"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
                pending_operation=self._operation_intent(
                    "release",
                    build_request_digest=_clean(latest.get("build_request_digest")),
                    attempt_number=0,
                ),
                reconciliation_required=True,
                automatic_retry_allowed=False,
            )
            try:
                release = self._quota_adapter.release(
                    {
                        "build_request_digest": latest.get("build_request_digest"),
                        "reservation_ref_digest": _dict(latest.get("quota")).get("reservation_ref_digest"),
                        "attempt_number": 0,
                        "operation_intent_digest": _dict(latest.get("pending_operation")).get("intent_digest"),
                    }
                )
                release_receipt_digest = self._require_adapter_digest(release, "release_receipt_digest")
            except Exception as exc:
                return self._transition(
                    build_idempotency_key,
                    latest,
                    "reservation_held",
                    observed=observed,
                    blocked_reasons=["release_outcome_unknown"],
                    quota_posture="blocked",
                    readiness_projection="blocked",
                    route_state="blocked",
                    pending_operation=None,
                    operation_failure_evidence=self._operation_failure_evidence(
                        "release",
                        build_request_digest=_clean(latest.get("build_request_digest")),
                        attempt_number=0,
                        observed=observed,
                        error=exc,
                    ),
                    reconciliation_required=True,
                    automatic_retry_allowed=False,
                )
            return self._transition(
                build_idempotency_key,
                latest,
                "released",
                observed=observed,
                blocked_reasons=["cancelled_before_attempt"],
                quota_posture="blocked",
                release_receipt_digest=release_receipt_digest,
                pending_operation=None,
                reconciliation_required=False,
                automatic_retry_allowed=False,
            )
        if state in {"attempt_committed", "charge_pending"}:
            return self._transition(
                build_idempotency_key,
                latest,
                "cancelled_reconciliation_pending",
                observed=observed,
                blocked_reasons=["cancelled_after_attempt_requires_reconciliation"],
                quota_posture="blocked",
                readiness_projection="blocked",
                route_state="blocked",
            )
        raise SpatialStateError("build_cancellation_requires_explicit_compensation_flow")

    def record_privacy_action(self, **kwargs: object) -> dict[str, object]:
        return self._ledger.record_privacy_action(**kwargs)  # type: ignore[arg-type]

    def restore_privacy_scope(self, scope_digest: str) -> None:
        self._ledger.restore_privacy_scope(scope_digest)


class _FacadeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GovernedCapabilityPosture(_FacadeModel):
    status: str
    quota_posture: str


class GovernedCompositionPrivateReceipt(_FacadeModel):
    contract_name: str
    idempotency_key: str
    material_digest: str
    composition_digest: str
    audit_only: bool
    quota_consumed: bool
    provider_job_enqueued: bool
    capability_posture: GovernedCapabilityPosture


class GovernedCompositionProductProjection(_FacadeModel):
    state: str
    capability_status: str
    build_eligible: bool
    quota_consumed: bool
    provider_details_exposed: bool


@dataclass(frozen=True)
class GovernedCompositionResult:
    private_receipt: GovernedCompositionPrivateReceipt
    product_safe_projection: GovernedCompositionProductProjection
    reused: bool


class GovernedSpatialRenderComposer:
    """Legacy compose shape backed by the authoritative zero-burn ledger."""

    def __init__(
        self,
        *,
        store: DurableSpatialLedger | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store or DurableSpatialLedger()
        self._now = now

    def compose_audit(
        self,
        request: GovernedSpatialRenderRequestV1 | Mapping[str, object],
        *,
        capability_evidence: list[Mapping[str, object]] | None = None,
    ) -> GovernedCompositionResult:
        parsed = GovernedSpatialRenderRequestV1.model_validate(
            request.model_dump(mode="json")
            if isinstance(request, GovernedSpatialRenderRequestV1)
            else dict(request)
        )
        normalized = normalized_request_material(parsed)
        material_digest = payload_digest(normalized)
        composition_digest = payload_digest(
            {
                "material_digest": material_digest,
                "orchestration_lane": ORCHESTRATION_LANE,
            }
        )
        existing = self._store.find_composition_by_key(parsed.idempotency_key)
        if existing is not None:
            if existing.get("material_digest") != material_digest:
                raise SpatialIdempotencyConflict("idempotency_key_payload_conflict")
            return self._result(existing, reused=True)
        now = self._now()
        verified = False
        for evidence in capability_evidence or []:
            observed = _parse_iso(evidence.get("observed_at"))
            valid_until = _parse_iso(evidence.get("valid_until"))
            if (
                evidence.get("status") == "verified"
                and evidence.get("quota_posture") == "build_allowed"
                and observed is not None
                and valid_until is not None
                and observed <= now <= valid_until
                and not _contains_sensitive_shape(evidence)
            ):
                verified = True
                break
        receipt = {
            "contract_name": COMPOSITION_RECEIPT_CONTRACT_NAME,
            "status": "accepted",
            "idempotency_key": parsed.idempotency_key,
            "material_digest": material_digest,
            "request_digest": material_digest,
            "source_packet_digest": payload_digest(parsed.source_packet_ref),
            "style_digest": payload_digest(parsed.style.model_dump(mode="json")),
            "composition_digest": composition_digest,
            "audit_only": True,
            "quota_consumed": False,
            "provider_job_enqueued": False,
            "capability_posture": {
                "status": "verified" if verified else "unverified",
                "quota_posture": "build_allowed" if verified else "audit_only",
            },
        }
        saved = self._store.save_composition(receipt)
        return self._result(saved, reused=False)

    @staticmethod
    def _result(receipt: Mapping[str, object], *, reused: bool) -> GovernedCompositionResult:
        private = GovernedCompositionPrivateReceipt.model_validate(
            {
                key: receipt[key]
                for key in (
                    "contract_name",
                    "idempotency_key",
                    "material_digest",
                    "composition_digest",
                    "audit_only",
                    "quota_consumed",
                    "provider_job_enqueued",
                    "capability_posture",
                )
            }
        )
        posture = private.capability_posture
        projection = GovernedCompositionProductProjection(
            state="blocked",
            capability_status=posture.status,
            build_eligible=posture.status == "verified" and posture.quota_posture == "build_allowed",
            quota_consumed=False,
            provider_details_exposed=False,
        )
        return GovernedCompositionResult(private, projection, reused)


SpatialRenderIdempotencyConflict = SpatialIdempotencyConflict
SpatialRenderValidationError = SpatialStateError
SpatialCompositionReceiptStore = DurableSpatialLedger


def build_governed_spatial_render_service() -> GovernedSpatialRenderService:
    evidence_paths: dict[str, Path] = {}
    evidence_paths_raw = _clean(os.getenv("GOVERNED_SPATIAL_EVIDENCE_PATHS_JSON"))
    if evidence_paths_raw:
        try:
            configured_paths = json.loads(evidence_paths_raw)
        except json.JSONDecodeError:
            configured_paths = {}
        if isinstance(configured_paths, dict):
            evidence_paths = {
                _clean(key).lower(): Path(value)
                for key, value in configured_paths.items()
                if _clean(key) and isinstance(value, str) and Path(value).is_file()
            }
    receipt_root_raw = _clean(os.getenv("GOVERNED_SPATIAL_RECEIPT_ROOT"))
    receipt_root = Path(receipt_root_raw).expanduser() if receipt_root_raw else None
    registry_path_raw = _clean(os.getenv("GOVERNED_SPATIAL_KEY_REGISTRY_PATH"))
    verification_registry = (
        CanonicalEd25519KeyRegistry(path=Path(registry_path_raw))
        if registry_path_raw
        else None
    )
    evidence_schema_path_raw = _clean(os.getenv("GOVERNED_SPATIAL_EVIDENCE_SCHEMA_PATH"))
    return GovernedSpatialRenderService(
        provider_evidence_paths=evidence_paths,
        receipt_store=GovernedSpatialRenderReceiptStore(receipt_root),
        verification_key_registry=verification_registry,
        evidence_schema_path=Path(evidence_schema_path_raw) if evidence_schema_path_raw else None,
        evidence_schema_sha256=_clean(os.getenv("GOVERNED_SPATIAL_EVIDENCE_SCHEMA_SHA256")).lower(),
        build_enabled=_clean(os.getenv("GOVERNED_SPATIAL_BUILD_ENABLED")).lower() in {"1", "true", "yes", "on"},
    )
