from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import stat
import threading
from typing import Mapping

import pytest

from app.services.governed_spatial_contract import (
    BUILD_AUTHORIZATION_SCHEMA,
    REQUEST_CONTRACT_NAME,
    SOURCE_PACKET_CONTRACT_NAME,
    GovernedSpatialBuildAuthorization,
    GovernedSpatialRenderRequestV1,
    GovernedSpatialSourcePacketV1,
    normalize_compatibility_numbers,
    normalized_request_material,
)
from app.services.governed_spatial_crypto import (
    Ed25519EnvelopeSigner,
    Ed25519KeyRegistry,
    sign_envelope,
    verify_signed_envelope,
)
from app.services.governed_spatial_execution import (
    GovernedSpatialAssetBindingV1,
    GovernedSpatialExecutionMaterialV1,
    GovernedSpatialStyleSnapshotV1,
    SpatialExecutionMaterialStore,
    SpatialMaterialKeyRecord,
    SpatialMaterialKeyRegistry,
    SpatialMaterialStoreError,
    key_fingerprint,
    material_digest as execution_material_digest,
)
from app.services.governed_spatial_quality import GovernedSpatialQualityService
from app.services.governed_spatial_render import (
    PROPERTY_ARTIFACT_FAMILY,
    PROPERTY_AUTHORITY_ACCEPTANCE_DIGEST,
    PROPERTY_AUTHORIZATION_OWNER,
    PROPERTY_COMPOSITION_RECEIPT_CONTRACT_NAME,
    PROPERTY_CONTENT_PROFILE,
    PROPERTY_POLICY_DIGEST,
    PROPERTY_POLICY_ID,
    PROPERTY_POLICY_PATH,
    GovernedSpatialOrchestrator,
    PropertyExecutionInputAuthorityVerification,
    PropertyRetentionPolicyVerification,
)
from app.services.governed_spatial_state import (
    AUDIT_ONLY_STATE,
    BUILD_STATES,
    GENERIC_BLOCKED_STATE,
    DurableSpatialLedger,
    SpatialIdempotencyConflict,
    SpatialPrivacyError,
    SpatialStateError,
    SpatialStateIntegrityError,
    SpatialTransitionError,
    authorization_binding_digest,
    payload_digest,
    utc_iso,
    validate_build_state_receipt,
)


NOW = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
_DEFAULT_TARGET = object()
_DEFAULT_PROPERTY_EVIDENCE = object()
_DEFAULT_PROPERTY_INPUT_VERIFIER = object()


def _digest(value: str) -> str:
    return payload_digest(value)


def _execution_target(*, private_encounter: bool = False) -> dict[str, object]:
    return {
        "artifact_family": (
            "runsite_private_encounter_preview"
            if private_encounter
            else "runsite_continuous_walkthrough"
        ),
        "content_profile": (
            "private_fictional_non_graphic_encounter"
            if private_encounter
            else "spatial_orientation_no_encounter_fields"
        ),
        "environment": "test",
        "provider_route_digest": _digest("execution-route"),
        "gate_versions": {"compose": "1", "quota": "1"},
    }


def _signer(
    *,
    environment: str = "test",
    seed: bytes = bytes(range(32)),
    not_after: str = "2026-08-01T00:00:00Z",
) -> Ed25519EnvelopeSigner:
    return Ed25519EnvelopeSigner.from_seed(
        seed,
        issuer="fixture-authority",
        environment=environment,
        key_ref="fixture-key-v1",
        key_epoch=1,
        not_before="2026-07-01T00:00:00Z",
        not_after=not_after,
    )


def _request_payload(*, key: str = "consumer-tour-demo-v1", style: str = "style-pack-v1") -> dict[str, object]:
    return {
        "contract_name": REQUEST_CONTRACT_NAME,
        "request_id": "74bc092f-c6d8-44ec-990a-5738cc0987ac",
        "idempotency_key": key,
        "consumer": {
            "product": "consumer_alpha",
            "tenant_ref": "tenant:fixture",
            "subject_ref": "subject:fixture",
        },
        "artifact": {
            "kind": "continuous_walkthrough",
            "purpose": "walkthrough",
            "locale": "en-AT",
        },
        "source_packet_ref": "source-packet:fixture:v1",
        "truth_refs": ["truth:fixture:v1"],
        "evidence_refs": ["evidence:source:v1"],
        "spatial_plan": {
            "room_graph_ref": "room-graph:fixture:v1",
            "walkable_mesh_ref": "mesh:fixture:v1",
            "portal_graph_ref": "portals:fixture:v1",
            "required_room_ids": ["living", "bathroom"],
            "route_room_ids": ["living", "bathroom"],
            "portal_edges": [{"from_room_id": "living", "to_room_id": "bathroom"}],
            "route_policy": "continuous_all_walkable_rooms",
            "allow_revisit": False,
        },
        "style": {"style_pack_id": style, "room_overrides": {}},
        "scene_overlays": [],
        "camera": {
            "height_m": 1.6,
            "target_delivery_fps": 60,
            "minimum_effective_motion_fps": 30,
            "motion_profile": "slow_inspection",
            "cuts_allowed": False,
            "teleports_allowed": False,
            "collision_avoidance": True,
            "rotation_smoothing": True,
        },
        "output": {
            "desktop": True,
            "mobile": True,
            "video_codec": "h264",
            "interactive_package": False,
            "poster_frame": True,
            "contact_sheet": True,
        },
        "content_policy": {
            "rating": "general",
            "graphic_injury": False,
            "real_person_likeness": False,
            "minor_combatants": False,
        },
        "quota": {"consume_quota": False, "maximum_provider_attempts": 0},
        "callback": {"product_event_ref": "event:render-complete"},
    }


def _source_payload() -> dict[str, object]:
    return {
        "contract_name": SOURCE_PACKET_CONTRACT_NAME,
        "source_packet_ref": "source-packet:fixture:v1",
        "source_digest": "b" * 64,
        "source_retrieved_at": "2026-07-11T09:00:00Z",
        "normalized_floorplan_ref": "floorplan:fixture:v1",
        "room_graph_ref": "room-graph:fixture:v1",
        "walkable_mesh_ref": "mesh:fixture:v1",
        "portal_graph_ref": "portals:fixture:v1",
        "scale_m_per_unit": 1,
        "orientation_degrees": 90,
        "license_provenance_refs": ["license:first-party:v1"],
        "source_media_assignments": [],
        "inaccessible_rooms": [],
        "route_exclusions": [],
        "rooms": [
            {
                "room_id": "living",
                "room_type": "living",
                "walkable": True,
                "boundary_ref": "boundary:living",
                "ceiling_height_m": 3,
                "geometry_anchor_ref": "anchor:living",
                "texture_anchor_refs": ["texture:living"],
            },
            {
                "room_id": "bathroom",
                "room_type": "bathroom",
                "walkable": True,
                "boundary_ref": "boundary:bathroom",
                "ceiling_height_m": 3,
                "geometry_anchor_ref": "anchor:bathroom",
                "texture_anchor_refs": ["texture:bathroom"],
            },
        ],
        "portals": [
            {
                "portal_id": "portal:living-bathroom",
                "from_room_id": "living",
                "to_room_id": "bathroom",
                "walkable": True,
            }
        ],
        "route_room_ids": ["living", "bathroom"],
        "existing_artifacts": {},
    }


PROPERTY_STORE_KEY = b"P" * 32


def _property_execution_target() -> dict[str, object]:
    return {
        "artifact_family": PROPERTY_ARTIFACT_FAMILY,
        "content_profile": PROPERTY_CONTENT_PROFILE,
        "environment": "test",
        "provider_route_digest": _digest("property-execution-route"),
        "gate_versions": {"compose": "r11", "property_policy": "v1"},
    }


def _property_request_payload(
    *, key: str = "property-tour-r11-v1", request_id: str = "74bc092f-c6d8-44ec-990a-5738cc0987ac",
) -> dict[str, object]:
    request = _request_payload(key=key)
    request["request_id"] = request_id
    request["consumer"] = {
        "product": "propertyquarry",
        "tenant_ref": "tenant:property-fixture",
        "subject_ref": "subject:property-fixture",
    }
    request["content_policy"] = {
        "rating": "general_spatial_orientation",
        "graphic_injury": False,
        "real_person_likeness": False,
        "minor_combatants": False,
    }
    return request


def _property_source_payload() -> dict[str, object]:
    source = _source_payload()
    source["source_packet_created_at"] = "2026-07-11T09:30:00Z"
    return source


def _property_style_snapshot() -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_style_snapshot.v1",
        "contract_version": "1.0.0",
        "style_pack_id": "style-pack-v1",
        "registry_contract": "property-style-registry-v1",
        "registry_version": "1.0.0",
        "registry_digest": _digest("property-style-registry"),
        "consumer_products": ["propertyquarry"],
        "status": "accepted",
        "room_types": ["any"],
        "room_rules": {"any": ["preserve-source-topology"]},
        "composition_rules": ["single-stable-scene"],
        "palette": ["neutral"],
        "materials": ["verified"],
        "catalog_families": [],
        "furniture_catalog_refs": [],
        "negative_constraints": ["no-layout-copy"],
        "asset_license_policy": "verified_reuse_only",
        "brand_claim_policy": "truthful_no_affiliation_claim",
        "adapter_profile_ref": "adapter-profile:property-deterministic:v1",
        "external_asset_refs": [],
        "provenance_status": "verified",
        "provenance_refs": ["provenance:property-style:v1"],
        "source_retrieved_at": "2026-07-11T09:00:00Z",
        "visual_direction_refs": [],
        "visual_regression_refs": [],
        "acceptance_contact_sheet_refs": [],
    }


def _property_asset(
    asset_ref: str, *, purpose: str, media_type: str,
) -> dict[str, object]:
    return {
        "asset_ref": asset_ref,
        "sha256": _digest(f"bytes:{asset_ref}"),
        "size_bytes": 128,
        "media_type": media_type,
        "purpose": purpose,
        "license_provenance_ref": "license:property-source:v1",
        "source_owner_ref": "owner:property-source:v1",
    }


def _property_asset_bindings() -> list[dict[str, object]]:
    source = _property_source_payload()
    geometry_refs = [
        source["normalized_floorplan_ref"],
        source["room_graph_ref"],
        source["walkable_mesh_ref"],
        source["portal_graph_ref"],
    ]
    texture_refs: list[str] = []
    for room in source["rooms"]:  # type: ignore[union-attr]
        geometry_refs.extend([room["boundary_ref"], room["geometry_anchor_ref"]])
        texture_refs.extend(room["texture_anchor_refs"])
    return [
        *[
            _property_asset(str(ref), purpose="source_geometry", media_type="application/json")
            for ref in geometry_refs
        ],
        *[
            _property_asset(ref, purpose="source_texture", media_type="image/png")
            for ref in texture_refs
        ],
    ]


def _property_policy_evidence(
    *, approved_at: datetime = NOW - timedelta(hours=1),
    expires_at: datetime = NOW + timedelta(hours=12),
    policy_digest: str = PROPERTY_POLICY_DIGEST,
    verification_receipt_digest: str | None = None,
) -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.governed_spatial_retention_policy_evidence.v1",
        "policy_id": PROPERTY_POLICY_ID,
        "approval_ref": "approval:property-policy:v1",
        "policy_digest": policy_digest,
        "verifier_ref": "verifier:property-policy:v1",
        "verification_receipt_digest": (
            verification_receipt_digest or _digest("property-policy-verification")
        ),
        "approved_at": utc_iso(approved_at),
        "expires_at": utc_iso(expires_at),
    }


def _property_policy_verification(
    evidence: Mapping[str, object],
    **changes: object,
) -> PropertyRetentionPolicyVerification:
    values: dict[str, object] = {
        "policy_path": PROPERTY_POLICY_PATH,
        "policy_id": PROPERTY_POLICY_ID,
        "policy_digest": PROPERTY_POLICY_DIGEST,
        "policy_mode": 0o600,
        "policy_expires_at": datetime(2027, 7, 11, tzinfo=UTC),
        "source_retention_days": 30,
        "approval_ref": evidence["approval_ref"],
        "verifier_ref": evidence["verifier_ref"],
        "verification_receipt_digest": evidence["verification_receipt_digest"],
        "evidence_digest": payload_digest(dict(evidence)),
        "independent_acceptance_digest": PROPERTY_AUTHORITY_ACCEPTANCE_DIGEST,
        "independent_acceptance_mode": 0o600,
        "regular_file": True,
        "independent_acceptance_regular_file": True,
        "state": "verified",
    }
    values.update(changes)
    return PropertyRetentionPolicyVerification(**values)  # type: ignore[arg-type]


class FakePropertyPolicyVerifier:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    def __call__(
        self, *, evidence: Mapping[str, object], observed_at: datetime,
    ) -> PropertyRetentionPolicyVerification:
        self.calls.append({"evidence": deepcopy(dict(evidence)), "observed_at": observed_at})
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]


def _property_input_authority_verification(
    *,
    normalized_request: Mapping[str, object] | None = None,
    normalized_source_packet: Mapping[str, object] | None = None,
    style_snapshot: GovernedSpatialStyleSnapshotV1 | None = None,
    asset_bindings: tuple[GovernedSpatialAssetBindingV1, ...] | None = None,
    **changes: object,
) -> PropertyExecutionInputAuthorityVerification:
    request_material = normalized_request or normalized_request_material(
        GovernedSpatialRenderRequestV1.model_validate(_property_request_payload())
    )
    source_material = normalized_source_packet or normalize_compatibility_numbers(
        GovernedSpatialSourcePacketV1.model_validate(
            _property_source_payload()
        ).model_dump(mode="json")
    )
    assert isinstance(source_material, Mapping)
    selected_style = style_snapshot or GovernedSpatialStyleSnapshotV1.model_validate(
        _property_style_snapshot()
    )
    selected_assets = asset_bindings or tuple(
        GovernedSpatialAssetBindingV1.model_validate(asset)
        for asset in _property_asset_bindings()
    )
    source_created = datetime.fromisoformat(
        str(source_material["source_packet_created_at"]).replace("Z", "+00:00")
    )
    values: dict[str, object] = {
        "state": "verified",
        "request_digest": payload_digest(dict(request_material)),
        "source_packet_digest": payload_digest(dict(source_material)),
        "source_packet_created_at": source_created,
        "source_authority_receipt_digest": _digest("property-source-authority-receipt"),
        "style_snapshot_digest": payload_digest(
            selected_style.model_dump(mode="json")
        ),
        "style_registry_receipt_digest": _digest("property-style-registry-receipt"),
        "asset_bindings_digest": payload_digest(
            [asset.model_dump(mode="json") for asset in selected_assets]
        ),
        "asset_authority_receipt_digest": _digest("property-asset-authority-receipt"),
        "verified_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(hours=12),
    }
    values.update(changes)
    return PropertyExecutionInputAuthorityVerification(**values)  # type: ignore[arg-type]


def _property_input_authority_projection(
    verification: PropertyExecutionInputAuthorityVerification,
) -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_property_input_authority.v1",
        "contract_version": "1.0.0",
        "state": "verified",
        "request_digest": verification.request_digest,
        "source_packet_digest": verification.source_packet_digest,
        "source_packet_created_at": utc_iso(verification.source_packet_created_at),
        "source_authority_receipt_digest": verification.source_authority_receipt_digest,
        "style_snapshot_digest": verification.style_snapshot_digest,
        "style_registry_receipt_digest": verification.style_registry_receipt_digest,
        "asset_bindings_digest": verification.asset_bindings_digest,
        "asset_authority_receipt_digest": verification.asset_authority_receipt_digest,
        "verified_at": utc_iso(verification.verified_at),
        "expires_at": utc_iso(verification.expires_at),
    }


class FakePropertyInputAuthorityVerifier:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = outcomes or []
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        *,
        normalized_request: Mapping[str, object],
        normalized_source_packet: Mapping[str, object],
        style_snapshot: GovernedSpatialStyleSnapshotV1,
        asset_bindings: tuple[GovernedSpatialAssetBindingV1, ...],
        observed_at: datetime,
    ) -> PropertyExecutionInputAuthorityVerification:
        self.calls.append(
            {
                "normalized_request": deepcopy(dict(normalized_request)),
                "normalized_source_packet": deepcopy(dict(normalized_source_packet)),
                "style_snapshot": deepcopy(style_snapshot.model_dump(mode="json")),
                "asset_bindings": [
                    deepcopy(asset.model_dump(mode="json")) for asset in asset_bindings
                ],
                "observed_at": observed_at,
            }
        )
        if self.outcomes:
            outcome = self.outcomes[
                min(len(self.calls) - 1, len(self.outcomes) - 1)
            ]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome  # type: ignore[return-value]
        return _property_input_authority_verification(
            normalized_request=normalized_request,
            normalized_source_packet=normalized_source_packet,
            style_snapshot=style_snapshot,
            asset_bindings=asset_bindings,
        )


class PersistentReplayOverrideLedger(DurableSpatialLedger):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.replay_override: dict[str, object] | None = None

    def find_composition_by_key(self, key: str) -> dict[str, object] | None:
        if self.replay_override is not None:
            return deepcopy(self.replay_override)
        return super().find_composition_by_key(key)


def _property_material_key_record() -> SpatialMaterialKeyRecord:
    return SpatialMaterialKeyRecord(
        environment="test",
        key_ref="material-key:property:v1",
        key_epoch=1,
        key_fingerprint=key_fingerprint(PROPERTY_STORE_KEY),
        key_bytes=PROPERTY_STORE_KEY,
        state="active_encrypt_decrypt",
        not_before=datetime(2026, 7, 1, tzinfo=UTC),
        decrypt_until=datetime(2026, 9, 30, tzinfo=UTC),
    )


def _property_material_store(
    root: Path,
    current: list[datetime],
    *,
    lifecycle_authority: object,
    crash_hook: object | None = None,
) -> SpatialExecutionMaterialStore:
    return SpatialExecutionMaterialStore(
        root,
        environment="test",
        keys=SpatialMaterialKeyRegistry([_property_material_key_record()]),
        clock=lambda: current[0],
        crash_hook=crash_hook,  # type: ignore[arg-type]
        retention_resolver=lambda material: datetime.fromisoformat(
            material.retention_expires_at.replace("Z", "+00:00")
        ),
        authority_guarded_recovery=True,
        lifecycle_authority=lifecycle_authority,  # type: ignore[arg-type]
    )


def _property_context(
    tmp_path: Path,
    *,
    evidence: dict[str, object] | None = None,
    verifier: FakePropertyPolicyVerifier | None = None,
    input_verifier: FakePropertyInputAuthorityVerifier | None | object = (
        _DEFAULT_PROPERTY_INPUT_VERIFIER
    ),
    ledger: DurableSpatialLedger | None = None,
    store: SpatialExecutionMaterialStore | None = None,
    current: list[datetime] | None = None,
    target: Mapping[str, object] | None = None,
    registry: Ed25519KeyRegistry | None = None,
) -> dict[str, object]:
    selected_evidence = evidence or _property_policy_evidence()
    selected_verifier = verifier or FakePropertyPolicyVerifier(
        [_property_policy_verification(selected_evidence)]
    )
    selected_current = current or [NOW]
    selected_ledger = ledger or DurableSpatialLedger(tmp_path / "property-ledger")
    selected_input_verifier = (
        FakePropertyInputAuthorityVerifier()
        if input_verifier is _DEFAULT_PROPERTY_INPUT_VERIFIER
        else input_verifier
    )
    selected_store = store or _property_material_store(
        tmp_path / "property-material",
        selected_current,
        lifecycle_authority=selected_ledger.lifecycle_authority,
    )
    signer = _signer()
    selected_registry = registry or Ed25519KeyRegistry([signer.key_record])
    quota = FakeQuotaAdapter()
    execution_target = dict(target or _property_execution_target())
    execution = FakeExecutionAdapter(target=execution_target)
    quality = FakeQualityGate()
    orchestrator = GovernedSpatialOrchestrator(
        ledger=selected_ledger,
        signer=signer,
        quota_adapter=quota,
        execution_adapter=execution,
        execution_target=execution_target,
        quality_gate=quality,
        now=lambda: selected_current[0],
        material_store=selected_store,
        composition_verification_registry=selected_registry,
        property_policy_verifier=selected_verifier,
        property_input_authority_verifier=selected_input_verifier,  # type: ignore[arg-type]
    )
    return {
        "evidence": selected_evidence,
        "verifier": selected_verifier,
        "input_verifier": selected_input_verifier,
        "current": selected_current,
        "ledger": selected_ledger,
        "store": selected_store,
        "signer": signer,
        "registry": selected_registry,
        "quota": quota,
        "execution": execution,
        "quality": quality,
        "orchestrator": orchestrator,
    }


def _compose_property(
    context: Mapping[str, object],
    *,
    request: Mapping[str, object] | None = None,
    source: Mapping[str, object] | None = None,
    style: Mapping[str, object] | None = None,
    assets: list[Mapping[str, object]] | None = None,
    evidence: Mapping[str, object] | None | object = _DEFAULT_PROPERTY_EVIDENCE,
    deadlines: Mapping[str, object] | None = None,
) -> dict[str, object]:
    selected_evidence = (
        context["evidence"] if evidence is _DEFAULT_PROPERTY_EVIDENCE else evidence
    )
    return context["orchestrator"].compose_property_execution_material(  # type: ignore[union-attr]
        request or _property_request_payload(),
        source_packet=source or _property_source_payload(),
        style_snapshot=style or _property_style_snapshot(),
        asset_bindings=assets or _property_asset_bindings(),
        policy_evidence=selected_evidence,  # type: ignore[arg-type]
        retention_deadlines=deadlines,
        observed_at=context["current"][0],  # type: ignore[index]
    )


def _revisit_payloads(*, key: str = "consumer-tour-revisit-v1") -> tuple[dict[str, object], dict[str, object]]:
    request = _request_payload(key=key)
    request["spatial_plan"] = {
        "room_graph_ref": "room-graph:fixture:v1",
        "walkable_mesh_ref": "mesh:fixture:v1",
        "portal_graph_ref": "portals:fixture:v1",
        "required_room_ids": ["bedroom", "hall", "bathroom"],
        "route_room_ids": ["bedroom", "hall", "bathroom", "hall", "bedroom"],
        "portal_edges": [
            {"from_room_id": "bedroom", "to_room_id": "hall"},
            {"from_room_id": "hall", "to_room_id": "bathroom"},
        ],
        "route_policy": "continuous_all_walkable_rooms",
        "allow_revisit": True,
    }
    source = _source_payload()
    source["rooms"] = [
        {
            "room_id": room_id,
            "room_type": "room",
            "walkable": True,
            "boundary_ref": f"boundary:{room_id}",
            "ceiling_height_m": 3,
            "geometry_anchor_ref": f"anchor:{room_id}",
            "texture_anchor_refs": [f"texture:{room_id}"],
        }
        for room_id in ("bedroom", "hall", "bathroom")
    ]
    source["portals"] = [
        {
            "portal_id": "portal:bedroom-hall",
            "from_room_id": "hall",
            "to_room_id": "bedroom",
            "walkable": True,
        },
        {
            "portal_id": "portal:hall-bathroom",
            "from_room_id": "bathroom",
            "to_room_id": "hall",
            "walkable": True,
        },
    ]
    source["route_room_ids"] = list(request["spatial_plan"]["route_room_ids"])  # type: ignore[index]
    return request, source


class FakeQuotaAdapter:
    def __init__(self, *, fail_at: str = "", compensation_state: str = "compensated") -> None:
        self.fail_at = fail_at
        self.compensation_state = compensation_state
        self.calls: list[str] = []

    def _call(self, operation: str) -> None:
        self.calls.append(operation)
        if self.fail_at == operation:
            raise RuntimeError(f"{operation}_fixture_failure")

    def reserve(self, request: Mapping[str, object]) -> Mapping[str, object]:
        assert str(request["operation_intent_digest"]).startswith("sha256:")
        self._call("reserve")
        return {
            "reservation_ref_digest": _digest("reservation"),
            "reservation_expires_at": "2026-07-11T10:20:00Z",
        }

    def commit_attempt(self, request: Mapping[str, object]) -> Mapping[str, object]:
        assert request["attempt_number"] == 1
        self._call("commit_attempt")
        return {"mutation_token_digest": _digest("mutation")}

    def release(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._call("release")
        return {"release_receipt_digest": _digest("release")}

    def consume(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._call("consume")
        return {"consumption_receipt_digest": _digest("consumption")}

    def compensate(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._call("compensate")
        return {
            "state": self.compensation_state,
            "compensation_receipt_digest": _digest("compensation"),
        }


class FakeExecutionAdapter:
    def __init__(
        self,
        *,
        state: str = "succeeded",
        fail: bool = False,
        target: Mapping[str, object] | None = None,
    ) -> None:
        self.state = state
        self.fail = fail
        self.target = deepcopy(dict(target or _execution_target()))
        self.calls: list[dict[str, object]] = []

    def execution_target_binding(self) -> Mapping[str, object]:
        return deepcopy(self.target)

    def execute(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append(dict(request))
        if self.fail:
            raise RuntimeError("execution_fixture_failure")
        if self.state != "succeeded":
            return {"state": self.state}
        return {
            "state": "succeeded",
            "output_digest": _digest("output"),
            "output_manifest_ref": "manifest:fixture:v1",
            "quality_metrics": {"fixture": "bounded"},
        }


class FakeQualityGate:
    def __init__(self, *, passed: bool = True, fail: bool = False) -> None:
        self.passed = passed
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, output_digest: str, metrics: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append(output_digest)
        if self.fail:
            raise RuntimeError("quality_fixture_failure")
        return {"passed": self.passed, "issues": [] if self.passed else ["quality_fixture_failed"]}


def _authorization(
    composition: Mapping[str, object],
    *,
    key: str = "build-fixture-v1",
    maximum_attempts: int = 1,
    issued_at: str = "2026-07-11T09:55:00Z",
    expires_at: str = "2026-07-11T10:30:00Z",
) -> GovernedSpatialBuildAuthorization:
    return GovernedSpatialBuildAuthorization.model_validate(
        {
            "schema_name": BUILD_AUTHORIZATION_SCHEMA,
            "accepted_composition_digest": composition["composition_digest"],
            "idempotency_key": key,
            "requested_by_ref": "authority:fixture",
            "authorization_ref": "authorization:fixture:v1",
            "audit_event_ref": "audit:fixture:v1",
            "consume_quota": True,
            "maximum_provider_attempts": maximum_attempts,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "quota_limit_digest": "a" * 64,
        }
    )


def _evidence_body(
    composition: Mapping[str, object],
    authorization: GovernedSpatialBuildAuthorization,
) -> dict[str, object]:
    composition_digest = f"sha256:{authorization.accepted_composition_digest}"
    authorization_material = {
        "state": "valid",
        "owner": authorization.requested_by_ref,
        "authorization_ref": authorization.authorization_ref,
        "issued_at": authorization.issued_at,
        "expires_at": authorization.expires_at,
        "maximum_provider_attempts": authorization.maximum_provider_attempts,
        "quota_limit_digest": f"sha256:{authorization.quota_limit_digest}",
    }
    idempotency = {
        "scope_digest": payload_digest(
            {
                "composition_digest": composition_digest,
                "authorization_ref": authorization.authorization_ref,
            }
        ),
        "key_digest": payload_digest(authorization.idempotency_key),
        "normalized_request_digest": composition["request_digest"],
        "composition_digest": composition_digest,
        "authorization_binding_digest": authorization_binding_digest(authorization_material),
    }
    execution_target = dict(composition["execution_target"])
    execution_target.pop("binding_state", None)
    evidence_rows = [
        (
            "provider_capability",
            "1",
            "2026-07-11T09:58:00Z",
            "2026-07-11T10:30:00Z",
        ),
        (
            "canonical_compose_validator_exact_version",
            "1",
            "2026-07-01T10:00:00Z",
            "2026-07-20T10:00:00Z",
        ),
        (
            "quota_snapshot",
            "1",
            "2026-07-11T09:59:00Z",
            "2026-07-11T10:05:00Z",
        ),
        (
            "kill_switch",
            "1",
            "2026-07-11T09:59:00Z",
            "2026-07-11T10:05:00Z",
        ),
    ]
    return {
        "schema_version": "governed_spatial_render_capability_quota_evidence_v1",
        "contract_name": "governed_spatial_render_v1",
        "receipt_id": "evidence-fixture-v1",
        "issuer": "fixture-authority",
        "environment": "test",
        "issued_at": "2026-07-11T09:59:00Z",
        "expires_at": "2026-07-11T10:04:00Z",
        "artifact_family": execution_target["artifact_family"],
        "content_profile": execution_target["content_profile"],
        "provider_route_digest": execution_target["provider_route_digest"],
        "gate_versions": deepcopy(execution_target["gate_versions"]),
        "state": "authorization_verified",
        "capability_state": "verified",
        "quota_posture": "build_allowed",
        "authorization": authorization_material,
        "idempotency": idempotency,
        "quota": {
            "state": "authorization_verified",
            "snapshot_issued_at": "2026-07-11T09:59:00Z",
            "snapshot_expires_at": "2026-07-11T10:05:00Z",
            "reservation_ref_digest": None,
            "reservation_expires_at": None,
            "attempt_number": 0,
            "mutation_token_digest": None,
            "consumption_receipt_digest": None,
            "compensation_receipt_digest": None,
        },
        "evidence_refs": [
            {
                "evidence_family": family,
                "ref": f"evidence:{index}:v1",
                "sha256": _digest(f"evidence-{index}").removeprefix("sha256:"),
                "gate_version": gate_version,
                "issued_at": issued_at,
                "expires_at": expires_at,
            }
            for index, (family, gate_version, issued_at, expires_at) in enumerate(evidence_rows, start=1)
        ],
        "kill_switch": {
            "state": "route_allowed",
            "epoch": 1,
            "issued_at": "2026-07-11T09:59:00Z",
            "expires_at": "2026-07-11T10:05:00Z",
        },
    }


def _evidence_row(body: Mapping[str, object], family: str) -> dict[str, object]:
    rows = body.get("evidence_refs")
    assert isinstance(rows, list)
    return next(
        row
        for row in rows
        if isinstance(row, dict) and row.get("evidence_family") == family
    )


def _private_request_payload() -> dict[str, object]:
    request = _request_payload()
    request["artifact"] = {
        "kind": "continuous_walkthrough",
        "purpose": "encounter_preview",
        "locale": "en-AT",
    }
    request["content_policy"] = {
        "rating": "teen_fictional_combat",
        "graphic_injury": False,
        "real_person_likeness": False,
        "minor_combatants": False,
    }
    return request


def _setup(
    tmp_path: Path,
    *,
    ledger: DurableSpatialLedger | None = None,
    quota: FakeQuotaAdapter | None = None,
    execution: FakeExecutionAdapter | None = None,
    quality: FakeQualityGate | None = None,
    maximum_attempts: int = 1,
    telemetry: list[dict[str, object]] | None = None,
    request_payload: Mapping[str, object] | None = None,
    execution_target: Mapping[str, object] | None | object = _DEFAULT_TARGET,
) -> dict[str, object]:
    signer = _signer()
    selected_request = deepcopy(dict(request_payload or _request_payload()))
    artifact = selected_request.get("artifact")
    private_encounter = isinstance(artifact, Mapping) and artifact.get("purpose") == "encounter_preview"
    selected_target = (
        _execution_target(private_encounter=private_encounter)
        if execution_target is _DEFAULT_TARGET
        else execution_target
    )
    selected_ledger = ledger or DurableSpatialLedger(tmp_path / "ledger")
    selected_quota = quota or FakeQuotaAdapter()
    selected_execution = execution or FakeExecutionAdapter(
        target=selected_target if isinstance(selected_target, Mapping) else None
    )
    selected_quality = quality or FakeQualityGate()
    orchestrator = GovernedSpatialOrchestrator(
        ledger=selected_ledger,
        signer=signer,
        quota_adapter=selected_quota,
        execution_adapter=selected_execution,
        execution_target=selected_target if isinstance(selected_target, Mapping) else None,
        quality_gate=selected_quality,
        telemetry_sink=telemetry.append if telemetry is not None else None,
        now=lambda: NOW,
    )
    composition = orchestrator.compose_audit(
        selected_request,
        source_packet=_source_payload(),
        observed_at=NOW,
    )
    authorization = _authorization(composition, maximum_attempts=maximum_attempts)
    registry = Ed25519KeyRegistry([signer.key_record])
    evidence = sign_envelope(_evidence_body(composition, authorization), signer)
    return {
        "signer": signer,
        "ledger": selected_ledger,
        "quota": selected_quota,
        "execution": selected_execution,
        "quality": selected_quality,
        "orchestrator": orchestrator,
        "composition": composition,
        "authorization": authorization,
        "registry": registry,
        "evidence": evidence,
    }


def _state_receipt(state: str) -> dict[str, object]:
    authorization = {
        "state": "valid",
        "owner": "authority:fixture",
        "authorization_ref": "authorization:fixture:v1",
        "issued_at": "2026-07-11T09:55:00Z",
        "expires_at": "2026-07-11T10:30:00Z",
        "maximum_provider_attempts": 2,
        "quota_limit_digest": _digest("quota-limit"),
    }
    idempotency = {
        "scope_digest": _digest("scope"),
        "key_digest": _digest("key"),
        "normalized_request_digest": _digest("request"),
        "composition_digest": _digest("composition"),
        "authorization_binding_digest": authorization_binding_digest(authorization),
    }
    quota = {
        "state": state,
        "reservation_ref_digest": None,
        "reservation_expires_at": None,
        "attempt_number": 0,
        "mutation_token_digest": None,
        "consumption_receipt_digest": None,
        "compensation_receipt_digest": None,
    }
    attempted = {
        "attempt_committed",
        "charge_pending",
        "cancelled_reconciliation_pending",
        "consumed",
        "closed_consumed",
        "compensation_pending",
        "compensated",
        "compensation_failed_blocked",
    }
    consumed = {
        "consumed",
        "closed_consumed",
        "compensation_pending",
        "compensated",
        "compensation_failed_blocked",
    }
    if state != "authorization_verified":
        quota["reservation_ref_digest"] = _digest("reservation")
        quota["reservation_expires_at"] = "2026-07-11T10:20:00Z"
    if state in attempted:
        quota["attempt_number"] = 1
        quota["mutation_token_digest"] = _digest("mutation")
    if state in consumed:
        quota["consumption_receipt_digest"] = _digest("consumption")
    if state in {"compensated", "compensation_failed_blocked"}:
        quota["compensation_receipt_digest"] = _digest("compensation")
    receipt: dict[str, object] = {
        "state": state,
        "authorization": authorization,
        "idempotency": idempotency,
        "quota": quota,
        "parentage": {
            "request_digest": _digest("request"),
            "source_digest": _digest("source"),
            "source_packet_digest": _digest("source-packet"),
            "style_digest": _digest("style"),
        },
        "quota_posture": "blocked" if state == "compensation_failed_blocked" else "build_allowed",
        "readiness_projection": "blocked" if state == "compensation_failed_blocked" else "unverified",
        "route_state": "blocked" if state == "compensation_failed_blocked" else "route_allowed",
        "output_digest": None,
        "output_manifest_ref": None,
    }
    if state == "closed_consumed":
        receipt["output_digest"] = _digest("output")
        receipt["output_manifest_ref"] = "manifest:fixture:v1"
    if state == "released":
        receipt["release_receipt_digest"] = _digest("release")
    return receipt


def _stored_state_receipt(state: str, *, key: str = "cancel-fixture-v1") -> dict[str, object]:
    receipt = _state_receipt(state)
    receipt.update(
        {
            "contract_name": "ea.governed_spatial_render_build_receipt.v1",
            "build_id": "build-cancel-fixture",
            "build_idempotency_key": key,
            "build_request_digest": _digest("cancel-build-request"),
            "composition_digest": _digest("composition"),
            "generated_at": "2026-07-11T10:00:00Z",
            "status": state,
            "blocked_reasons": [],
        }
    )
    return receipt


@pytest.mark.parametrize("state", BUILD_STATES)
def test_every_accepted_build_state_validates(state: str) -> None:
    validate_build_state_receipt(_state_receipt(state))


def test_state_validator_rejects_success_smuggling_and_lineage_mutation() -> None:
    smuggled = _state_receipt("compensated")
    smuggled["output_digest"] = _digest("smuggled")
    smuggled["output_manifest_ref"] = "manifest:smuggled:v1"
    with pytest.raises(SpatialTransitionError, match="success_fields_forbidden"):
        validate_build_state_receipt(smuggled)

    prior = _state_receipt("authorization_verified")
    changed = _state_receipt("reservation_held")
    changed["parentage"]["style_digest"] = _digest("changed-style")  # type: ignore[index]
    with pytest.raises(SpatialTransitionError, match="immutable_lineage_changed"):
        validate_build_state_receipt(changed, prior=prior)


def test_cancel_persists_release_intent_and_release_receipt_before_return(tmp_path: Path) -> None:
    key = "cancel-fixture-v1"
    ledger = DurableSpatialLedger(tmp_path / "ledger")
    ledger.append_build_transition(key, _stored_state_receipt("authorization_verified", key=key))
    ledger.append_build_transition(key, _stored_state_receipt("reservation_held", key=key))
    quota = FakeQuotaAdapter()
    service = GovernedSpatialOrchestrator(
        ledger=ledger,
        signer=_signer(),
        quota_adapter=quota,
        now=lambda: NOW,
    )
    released = service.cancel(key, observed_at=NOW)
    history = ledger.build_history(key)
    assert [row["state"] for row in history] == [
        "authorization_verified",
        "reservation_held",
        "reservation_held",
        "released",
    ]
    assert history[-2]["pending_operation"]["operation"] == "release"
    assert history[-2]["pending_operation"]["outcome"] == "pending_or_unknown"
    assert released["release_receipt_digest"] == _digest("release")
    validate_build_state_receipt(released, prior=history[-2])
    assert quota.calls == ["release"]

    fresh_quota = FakeQuotaAdapter()
    restarted = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        quota_adapter=fresh_quota,
        now=lambda: NOW,
    )
    replay = restarted.cancel(key, observed_at=NOW)
    assert replay["state"] == "released"
    assert replay["release_receipt_digest"] == _digest("release")
    assert fresh_quota.calls == []


def test_cancel_unknown_release_is_not_retried_after_restart(tmp_path: Path) -> None:
    key = "cancel-fixture-v1"
    ledger = DurableSpatialLedger(tmp_path / "ledger")
    ledger.append_build_transition(key, _stored_state_receipt("authorization_verified", key=key))
    ledger.append_build_transition(key, _stored_state_receipt("reservation_held", key=key))
    quota = FakeQuotaAdapter(fail_at="release")
    service = GovernedSpatialOrchestrator(
        ledger=ledger,
        signer=_signer(),
        quota_adapter=quota,
        now=lambda: NOW,
    )
    unknown = service.cancel(key, observed_at=NOW)
    assert unknown["state"] == "reservation_held"
    assert unknown["reconciliation_required"] is True
    assert unknown["automatic_retry_allowed"] is False
    assert unknown["operation_failure_evidence"]["operation"] == "release"
    assert quota.calls == ["release"]

    fresh_quota = FakeQuotaAdapter()
    restarted = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        quota_adapter=fresh_quota,
        now=lambda: NOW,
    )
    replay = restarted.cancel(key, observed_at=NOW)
    assert replay["state"] == "reservation_held"
    assert replay["reconciliation_required"] is True
    assert fresh_quota.calls == []


def test_compose_is_signed_audit_only_and_zero_burn(tmp_path: Path) -> None:
    telemetry: list[dict[str, object]] = []
    context = _setup(tmp_path, telemetry=telemetry)
    composition = context["composition"]
    quota = context["quota"]
    execution = context["execution"]
    quality = context["quality"]

    validate_build_state_receipt(composition)  # type: ignore[arg-type]
    verification = verify_signed_envelope(
        composition,  # type: ignore[arg-type]
        context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert verification.payload_digest.startswith("sha256:")
    assert composition["contract_version"] == "r10-route-semantics-v1"  # type: ignore[index]
    assert composition["state"] == AUDIT_ONLY_STATE  # type: ignore[index]
    assert composition["provider_job_enqueued"] is False  # type: ignore[index]
    assert composition["quota_mutated"] is False  # type: ignore[index]
    assert quota.calls == []  # type: ignore[union-attr]
    assert execution.calls == []  # type: ignore[union-attr]
    assert quality.calls == []  # type: ignore[union-attr]
    assert telemetry[-1]["quota_actions"] == 0
    assert telemetry[-1]["execution_actions"] == 0
    assert telemetry[-1]["route_visit_count"] == 2
    assert telemetry[-1]["route_revisit_count"] == 0


def test_existing_r9_composition_replay_preserves_stored_receipt_version(tmp_path: Path) -> None:
    signer = _signer()
    seed = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "seed-ledger"),
        signer=signer,
        now=lambda: NOW,
    ).compose_audit(_request_payload(), source_packet=_source_payload(), observed_at=NOW)
    existing = deepcopy(seed)
    existing["contract_version"] = "r9-v1"

    class ExistingReceiptLedger:
        def find_composition_by_key(self, _key: str) -> dict[str, object]:
            return deepcopy(existing)

    replay = GovernedSpatialOrchestrator(
        ledger=ExistingReceiptLedger(),  # type: ignore[arg-type]
        signer=signer,
        now=lambda: NOW,
    ).compose_audit(_request_payload(), source_packet=_source_payload(), observed_at=NOW)

    assert replay["contract_version"] == "r9-v1"
    assert replay["idempotent_replay"] is True


def test_revisit_compose_is_exactly_bound_and_zero_action(tmp_path: Path) -> None:
    request, source = _revisit_payloads()
    telemetry: list[dict[str, object]] = []
    quota = FakeQuotaAdapter()
    execution = FakeExecutionAdapter()
    quality = FakeQualityGate()
    orchestrator = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        quota_adapter=quota,
        execution_adapter=execution,
        execution_target=_execution_target(),
        quality_gate=quality,
        telemetry_sink=telemetry.append,
        now=lambda: NOW,
    )

    composition = orchestrator.compose_audit(request, source_packet=source, observed_at=NOW)

    assert composition["status"] == "accepted"
    assert composition["provider_job_enqueued"] is False
    assert composition["quota_mutated"] is False
    assert quota.calls == []
    assert execution.calls == []
    assert quality.calls == []
    assert telemetry[-1]["route_visit_count"] == 5
    assert telemetry[-1]["route_revisit_count"] == 2
    assert "bedroom" not in json.dumps(telemetry)
    assert "hall" not in json.dumps(telemetry)
    assert "bathroom" not in json.dumps(telemetry)


def test_compose_replay_conflict_and_restart_are_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    signer = _signer()
    first = GovernedSpatialOrchestrator(ledger=DurableSpatialLedger(root), signer=signer, now=lambda: NOW)
    composition = first.compose_audit(_request_payload(), source_packet=_source_payload(), observed_at=NOW)

    changed_request_id = _request_payload()
    changed_request_id["request_id"] = "4b5f63bf-d590-456d-b693-226aec5d403f"
    restarted = GovernedSpatialOrchestrator(ledger=DurableSpatialLedger(root), signer=signer, now=lambda: NOW)
    replay = restarted.compose_audit(changed_request_id, source_packet=_source_payload(), observed_at=NOW)
    assert replay["composition_digest"] == composition["composition_digest"]
    assert replay["idempotent_replay"] is True

    with pytest.raises(SpatialIdempotencyConflict):
        restarted.compose_audit(
            _request_payload(style="style-pack-v2"),
            source_packet=_source_payload(),
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda request, source: source.update({"source_packet_ref": "source-packet:other:v1"}),
            "source_packet_ref_mismatch",
        ),
        (
            lambda request, source: source.update({"room_graph_ref": "room-graph:other:v1"}),
            "room_graph_ref_mismatch",
        ),
        (
            lambda request, source: source.update({"route_exclusions": [{"room_id": "bathroom"}]}),
            "route_exclusions_forbidden",
        ),
        (
            lambda request, source: source.update({"inaccessible_rooms": [{"room_id": "living"}]}),
            "inaccessible_room_classified_walkable",
        ),
        (
            lambda request, source: source.update({"route_room_ids": ["bathroom", "living"]}),
            "request_source_route_sequence_mismatch",
        ),
    ],
)
def test_compose_cross_source_mismatches_fail_before_receipt(
    tmp_path: Path,
    mutation: object,
    reason: str,
) -> None:
    request = _request_payload()
    source = _source_payload()
    assert callable(mutation)
    mutation(request, source)
    ledger = DurableSpatialLedger(tmp_path / "ledger")
    service = GovernedSpatialOrchestrator(
        ledger=ledger,
        signer=_signer(),
        execution_target=_execution_target(),
        now=lambda: NOW,
    )
    with pytest.raises(SpatialStateError, match=reason):
        service.compose_audit(request, source_packet=source, observed_at=NOW)
    assert ledger.integrity_summary()["composition_count"] == 0


def test_compose_requires_full_source_classified_walkable_room_set(tmp_path: Path) -> None:
    source = _source_payload()
    source["rooms"].extend(  # type: ignore[union-attr]
        {
            "room_id": f"room-{index}",
            "room_type": "room",
            "walkable": True,
            "boundary_ref": f"boundary:room-{index}",
            "ceiling_height_m": 3,
            "geometry_anchor_ref": f"anchor:room-{index}",
            "texture_anchor_refs": [f"texture:room-{index}"],
        }
        for index in range(3)
    )
    source["route_room_ids"].extend(["room-0", "room-1", "room-2"])  # type: ignore[union-attr]
    source["portals"].extend(  # type: ignore[union-attr]
        [
            {
                "portal_id": "portal:bathroom-room-0",
                "from_room_id": "bathroom",
                "to_room_id": "room-0",
                "walkable": True,
            },
            {
                "portal_id": "portal:room-0-room-1",
                "from_room_id": "room-0",
                "to_room_id": "room-1",
                "walkable": True,
            },
            {
                "portal_id": "portal:room-1-room-2",
                "from_room_id": "room-1",
                "to_room_id": "room-2",
                "walkable": True,
            },
        ]
    )
    service = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        execution_target=_execution_target(),
        now=lambda: NOW,
    )
    with pytest.raises(SpatialStateError, match="request_required_rooms_not_full_walkable_set"):
        service.compose_audit(_request_payload(), source_packet=source, observed_at=NOW)


def test_compose_accepts_reverse_source_portal_traversal(tmp_path: Path) -> None:
    source = _source_payload()
    source["portals"] = [
        {
            "portal_id": "portal:living-bathroom",
            "from_room_id": "bathroom",
            "to_room_id": "living",
            "walkable": True,
        }
    ]
    service = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        execution_target=_execution_target(),
        now=lambda: NOW,
    )
    composition = service.compose_audit(_request_payload(), source_packet=source, observed_at=NOW)
    assert composition["status"] == "accepted"


def test_compose_preserves_known_inaccessible_portal_without_routing_it(tmp_path: Path) -> None:
    source = _source_payload()
    source["rooms"].append(  # type: ignore[union-attr]
        {
            "room_id": "service",
            "room_type": "service",
            "walkable": False,
            "boundary_ref": "boundary:service",
            "ceiling_height_m": 3,
            "geometry_anchor_ref": "anchor:service",
            "texture_anchor_refs": ["texture:service"],
        }
    )
    source["inaccessible_rooms"] = [{"room_id": "service"}]
    source["portals"].append(  # type: ignore[union-attr]
        {
            "portal_id": "portal:bathroom-service",
            "from_room_id": "bathroom",
            "to_room_id": "service",
            "walkable": True,
        }
    )
    service = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        execution_target=_execution_target(),
        now=lambda: NOW,
    )

    composition = service.compose_audit(_request_payload(), source_packet=source, observed_at=NOW)

    assert composition["status"] == "accepted"
    assert source["route_room_ids"] == ["living", "bathroom"]


@pytest.mark.parametrize(
    "source_route",
    [
        ["bathroom", "hall", "bedroom", "hall", "bathroom"],
        ["bedroom", "hall", "bathroom", "hall", "bathroom"],
    ],
)
def test_compose_rejects_exact_route_reorder_and_substitution_attacks(
    tmp_path: Path,
    source_route: list[str],
) -> None:
    request, source = _revisit_payloads()
    source["route_room_ids"] = source_route
    service = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        execution_target=_execution_target(),
        now=lambda: NOW,
    )
    with pytest.raises(SpatialStateError, match="request_source_route_sequence_mismatch"):
        service.compose_audit(request, source_packet=source, observed_at=NOW)


def test_changed_route_conflicts_and_restart_replay_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    signer = _signer()
    request, source = _revisit_payloads()
    first = GovernedSpatialOrchestrator(ledger=DurableSpatialLedger(root), signer=signer, now=lambda: NOW)
    composition = first.compose_audit(request, source_packet=source, observed_at=NOW)

    replay_request = deepcopy(request)
    replay_request["request_id"] = "4b5f63bf-d590-456d-b693-226aec5d403f"
    restarted = GovernedSpatialOrchestrator(ledger=DurableSpatialLedger(root), signer=signer, now=lambda: NOW)
    replay = restarted.compose_audit(replay_request, source_packet=source, observed_at=NOW)
    assert replay["composition_digest"] == composition["composition_digest"]
    assert replay["idempotent_replay"] is True

    changed_request = deepcopy(request)
    changed_source = deepcopy(source)
    changed_route = ["bathroom", "hall", "bedroom", "hall", "bathroom"]
    changed_request["spatial_plan"]["route_room_ids"] = changed_route  # type: ignore[index]
    changed_source["route_room_ids"] = changed_route
    with pytest.raises(SpatialIdempotencyConflict, match="idempotency_key_payload_conflict"):
        restarted.compose_audit(changed_request, source_packet=changed_source, observed_at=NOW)


def test_compose_rejects_naive_source_retrieval_timestamp(tmp_path: Path) -> None:
    source = _source_payload()
    source["source_retrieved_at"] = "2026-07-11T09:00:00"
    service = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=_signer(),
        execution_target=_execution_target(),
        now=lambda: NOW,
    )
    with pytest.raises(SpatialStateError, match="source_retrieved_at_offset_required"):
        service.compose_audit(_request_payload(), source_packet=source, observed_at=NOW)


def test_concurrent_compose_creates_one_private_receipt(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    signer = _signer()

    def compose_once(_: int) -> str:
        service = GovernedSpatialOrchestrator(
            ledger=DurableSpatialLedger(root),
            signer=signer,
            execution_target=_execution_target(),
            now=lambda: NOW,
        )
        receipt = service.compose_audit(_request_payload(), source_packet=_source_payload(), observed_at=NOW)
        return str(receipt["composition_digest"])

    with ThreadPoolExecutor(max_workers=6) as executor:
        digests = list(executor.map(compose_once, range(12)))
    assert len(set(digests)) == 1
    assert DurableSpatialLedger(root).integrity_summary()["composition_count"] == 1


@pytest.mark.parametrize("family", ["compositions", "builds", "privacy"])
def test_ledger_rejects_parent_component_symlink_without_escape(tmp_path: Path, family: str) -> None:
    root = tmp_path / "ledger"
    ledger = DurableSpatialLedger(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / family).symlink_to(outside, target_is_directory=True)
    service = GovernedSpatialOrchestrator(ledger=ledger, signer=_signer(), now=lambda: NOW)

    with pytest.raises(SpatialStateIntegrityError, match="directory_not_regular"):
        service.compose_audit(_request_payload(), source_packet=_source_payload(), observed_at=NOW)
    assert list(outside.iterdir()) == []


def test_ledger_private_permissions_and_restart_integrity(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    root = tmp_path / "ledger"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "index.json").stat().st_mode) == 0o600
    for family in ("compositions",):
        assert stat.S_IMODE((root / family).stat().st_mode) == 0o700
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in (root / family).iterdir())
    assert DurableSpatialLedger(root).find_composition_by_key("consumer-tour-demo-v1") == context["composition"]


def test_composition_persist_failure_rolls_back_disk_and_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "ledger"
    ledger = DurableSpatialLedger(root)
    service = GovernedSpatialOrchestrator(ledger=ledger, signer=_signer(), now=lambda: NOW)
    original = ledger._persist_index

    def fail_persist(**kwargs: object) -> None:
        raise OSError("forced_index_failure")

    monkeypatch.setattr(ledger, "_persist_index", fail_persist)
    with pytest.raises(OSError, match="forced_index_failure"):
        service.compose_audit(_request_payload(), source_packet=_source_payload(), observed_at=NOW)
    monkeypatch.setattr(ledger, "_persist_index", original)
    assert ledger.integrity_summary()["composition_count"] == 0
    assert list((root / "compositions").iterdir()) == []


def test_ledger_detects_tampered_private_receipt_on_restart(tmp_path: Path) -> None:
    _setup(tmp_path)
    receipt_path = next((tmp_path / "ledger" / "compositions").iterdir())
    receipt_path.write_text("{}\n", encoding="utf-8")
    os.chmod(receipt_path, 0o600)
    with pytest.raises(SpatialStateIntegrityError, match="receipt_digest_integrity_failed"):
        DurableSpatialLedger(tmp_path / "ledger")


def test_missing_evidence_is_generic_blocked_without_side_effects(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=None,
        evidence_registry=None,
        observed_at=NOW,
    )
    validate_build_state_receipt(result)
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert result["output_digest"] is None
    assert context["quota"].calls == []  # type: ignore[union-attr]
    assert context["execution"].calls == []  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("artifact_family", "runsite_private_encounter_preview", "artifact_family"),
        ("content_profile", "private_fictional_non_graphic_encounter", "content_profile"),
        ("provider_route_digest", _digest("unrelated-route"), "provider_route_digest"),
        ("gate_versions", {"compose": "other", "quota": "1"}, "gate_versions"),
    ],
)
def test_valid_signed_evidence_cannot_authorize_an_unrelated_execution_target(
    tmp_path: Path,
    field: str,
    replacement: object,
    reason: str,
) -> None:
    context = _setup(tmp_path)
    body = _evidence_body(context["composition"], context["authorization"])  # type: ignore[arg-type]
    body[field] = replacement
    evidence = sign_envelope(body, context["signer"])  # type: ignore[arg-type]
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert any(f"execution_target_mismatch:{reason}" in value for value in result["blocked_reasons"])
    assert context["quota"].calls == []  # type: ignore[union-attr]
    assert context["execution"].calls == []  # type: ignore[union-attr]


def test_valid_signed_evidence_environment_must_match_accepted_composition(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    body = _evidence_body(context["composition"], context["authorization"])  # type: ignore[arg-type]
    body["environment"] = "candidate"
    candidate_signer = _signer(environment="candidate", seed=bytes(reversed(range(32))))
    evidence = sign_envelope(body, candidate_signer)
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=evidence,
        evidence_registry=Ed25519KeyRegistry([candidate_signer.key_record]),
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert any("execution_target_mismatch:environment" in value for value in result["blocked_reasons"])
    assert context["quota"].calls == []  # type: ignore[union-attr]


def test_build_fails_closed_without_exact_composition_or_adapter_target_binding(tmp_path: Path) -> None:
    unbound = _setup(tmp_path / "unbound", execution_target=None)
    unbound_result = unbound["orchestrator"].build(  # type: ignore[union-attr]
        unbound["authorization"],  # type: ignore[arg-type]
        evidence_envelope=unbound["evidence"],  # type: ignore[arg-type]
        evidence_registry=unbound["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert unbound_result["state"] == GENERIC_BLOCKED_STATE
    assert "execution_target_not_bound" in unbound_result["blocked_reasons"]
    assert unbound["quota"].calls == []  # type: ignore[union-attr]

    mismatched_adapter = FakeExecutionAdapter(
        target={**_execution_target(), "provider_route_digest": _digest("adapter-other-route")}
    )
    mismatched = _setup(tmp_path / "adapter", execution=mismatched_adapter)
    mismatched_result = mismatched["orchestrator"].build(  # type: ignore[union-attr]
        mismatched["authorization"],  # type: ignore[arg-type]
        evidence_envelope=mismatched["evidence"],  # type: ignore[arg-type]
        evidence_registry=mismatched["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert mismatched_result["state"] == GENERIC_BLOCKED_STATE
    assert "execution_adapter_target_binding_mismatch" in mismatched_result["blocked_reasons"]
    assert mismatched["quota"].calls == []  # type: ignore[union-attr]
    assert mismatched_adapter.calls == []


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("authorization", "owner", "authority:other"),
        ("authorization", "authorization_ref", "authorization:other:v1"),
        ("authorization", "issued_at", "2026-07-11T09:56:00Z"),
        ("authorization", "expires_at", "2026-07-11T10:29:00Z"),
        ("authorization", "maximum_provider_attempts", 2),
        ("authorization", "quota_limit_digest", _digest("other-quota")),
        ("idempotency", "scope_digest", _digest("other-scope")),
        ("idempotency", "key_digest", _digest("other-key")),
        ("idempotency", "normalized_request_digest", _digest("other-request")),
        ("idempotency", "composition_digest", _digest("other-composition")),
        ("idempotency", "authorization_binding_digest", _digest("other-binding")),
    ],
)
def test_signed_evidence_requires_exact_authorization_and_idempotency_binding(
    tmp_path: Path,
    section: str,
    field: str,
    replacement: object,
) -> None:
    context = _setup(tmp_path)
    body = _evidence_body(context["composition"], context["authorization"])  # type: ignore[arg-type]
    body[section][field] = replacement  # type: ignore[index]
    evidence = sign_envelope(body, context["signer"])  # type: ignore[arg-type]
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert any(f"mismatch:{field}" in reason for reason in result["blocked_reasons"])
    assert context["quota"].calls == []  # type: ignore[union-attr]
    assert context["execution"].calls == []  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("naive_timestamp", "timestamp_offset_required"),
        ("naive_reservation_timestamp", "timestamp_offset_required:receipt.quota.reservation_expires_at"),
        ("quota_snapshot_old", "maximum_age_exceeded:quota_snapshot"),
        ("kill_switch_old", "maximum_age_exceeded:kill_switch"),
        ("quota_evidence_ref_old", "maximum_age_exceeded:evidence_ref:quota_snapshot"),
        ("kill_evidence_ref_old", "maximum_age_exceeded:evidence_ref:kill_switch"),
        ("compose_validator_old", "maximum_age_exceeded:evidence_ref:canonical_compose_validator_exact_version"),
        ("browser_evidence_old", "maximum_age_exceeded:evidence_ref:browser_mobile_accessibility"),
        ("reservation_too_long", "reservation_lease_exceeds_30_minutes"),
    ],
)
def test_runtime_evidence_freshness_rules_fail_closed(
    tmp_path: Path,
    case: str,
    reason: str,
) -> None:
    context = _setup(tmp_path)
    body = _evidence_body(context["composition"], context["authorization"])  # type: ignore[arg-type]
    if case == "naive_timestamp":
        _evidence_row(body, "provider_capability")["issued_at"] = "2026-07-11T09:58:00"
    elif case == "naive_reservation_timestamp":
        body["quota"].update(  # type: ignore[union-attr]
            {
                "state": "reservation_held",
                "reservation_ref_digest": _digest("evidence-reservation"),
                "reservation_expires_at": "2026-07-11T10:20:00",
            }
        )
    elif case == "quota_snapshot_old":
        body["quota"]["snapshot_issued_at"] = "2026-07-11T09:54:59Z"  # type: ignore[index]
    elif case == "kill_switch_old":
        body["kill_switch"]["issued_at"] = "2026-07-11T09:54:59Z"  # type: ignore[index]
    elif case == "quota_evidence_ref_old":
        _evidence_row(body, "quota_snapshot")["issued_at"] = "2026-07-11T09:54:59Z"
    elif case == "kill_evidence_ref_old":
        _evidence_row(body, "kill_switch")["issued_at"] = "2026-07-11T09:54:59Z"
    elif case == "compose_validator_old":
        _evidence_row(body, "canonical_compose_validator_exact_version")["issued_at"] = (
            "2026-06-01T10:00:00Z"
        )
    elif case == "browser_evidence_old":
        body["evidence_refs"].append(  # type: ignore[union-attr]
            {
                "evidence_family": "browser_mobile_accessibility",
                "ref": "evidence:browser:v1",
                "sha256": _digest("browser-evidence").removeprefix("sha256:"),
                "gate_version": "1",
                "issued_at": "2026-07-04T09:59:59Z",
                "expires_at": "2026-07-20T10:00:00Z",
            }
        )
    else:
        body["quota"].update(  # type: ignore[union-attr]
            {
                "state": "reservation_held",
                "reservation_ref_digest": _digest("evidence-reservation"),
                "reservation_expires_at": "2026-07-11T10:30:01Z",
            }
        )
    evidence = sign_envelope(body, context["signer"])  # type: ignore[arg-type]
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert any(reason in value for value in result["blocked_reasons"])
    assert context["quota"].calls == []  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("evidence_ref", "top_level_expiry_exceeds:evidence_ref:provider_capability"),
        ("quota_snapshot", "top_level_expiry_exceeds:quota_snapshot"),
        ("kill_switch", "top_level_expiry_exceeds:kill_switch"),
        ("reservation", "top_level_expiry_exceeds:reservation"),
    ],
)
def test_top_level_expiry_cannot_outlive_referenced_evidence(
    tmp_path: Path,
    case: str,
    reason: str,
) -> None:
    context = _setup(tmp_path)
    body = _evidence_body(context["composition"], context["authorization"])  # type: ignore[arg-type]
    if case == "evidence_ref":
        _evidence_row(body, "provider_capability")["expires_at"] = "2026-07-11T10:03:59Z"
    elif case == "quota_snapshot":
        body["quota"]["snapshot_expires_at"] = "2026-07-11T10:03:59Z"  # type: ignore[index]
    elif case == "kill_switch":
        body["kill_switch"]["expires_at"] = "2026-07-11T10:03:59Z"  # type: ignore[index]
    else:
        body["quota"].update(  # type: ignore[union-attr]
            {
                "state": "reservation_held",
                "reservation_ref_digest": _digest("evidence-reservation"),
                "reservation_expires_at": "2026-07-11T10:03:59Z",
            }
        )
    evidence = sign_envelope(body, context["signer"])  # type: ignore[arg-type]
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert any(reason in value for value in result["blocked_reasons"])


def test_consumer_authorization_age_and_expiry_are_runtime_bound(tmp_path: Path) -> None:
    context = _setup(tmp_path / "old")
    old_authorization = _authorization(
        context["composition"],  # type: ignore[arg-type]
        issued_at="2026-07-11T09:44:59Z",
    )
    old_evidence = sign_envelope(
        _evidence_body(context["composition"], old_authorization),  # type: ignore[arg-type]
        context["signer"],  # type: ignore[arg-type]
    )
    old_result = context["orchestrator"].build(  # type: ignore[union-attr]
        old_authorization,
        evidence_envelope=old_evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert old_result["state"] == GENERIC_BLOCKED_STATE
    assert any("maximum_age_exceeded:consumer_authorization" in value for value in old_result["blocked_reasons"])

    expiring = _setup(tmp_path / "expiry")
    short_authorization = _authorization(
        expiring["composition"],  # type: ignore[arg-type]
        expires_at="2026-07-11T10:03:59Z",
    )
    short_evidence = sign_envelope(
        _evidence_body(expiring["composition"], short_authorization),  # type: ignore[arg-type]
        expiring["signer"],  # type: ignore[arg-type]
    )
    short_result = expiring["orchestrator"].build(  # type: ignore[union-attr]
        short_authorization,
        evidence_envelope=short_evidence,
        evidence_registry=expiring["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert short_result["state"] == GENERIC_BLOCKED_STATE
    assert any("top_level_expiry_exceeds:consumer_authorization" in value for value in short_result["blocked_reasons"])


def test_build_rejects_naive_authorization_timestamp_before_side_effects(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    authorization = _authorization(
        context["composition"],  # type: ignore[arg-type]
        issued_at="2026-07-11T09:55:00",
    )
    evidence = sign_envelope(
        _evidence_body(context["composition"], authorization),  # type: ignore[arg-type]
        context["signer"],  # type: ignore[arg-type]
    )
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        authorization,
        evidence_envelope=evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert "build_authorization_chronology_invalid" in result["blocked_reasons"]
    assert any("timestamp_offset_required" in value for value in result["blocked_reasons"])
    assert context["quota"].calls == []  # type: ignore[union-attr]
    assert context["execution"].calls == []  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("private_encounter", "issued_at"),
    [
        (False, "2026-07-10T09:59:59Z"),
        (True, "2026-07-10T21:59:59Z"),
    ],
)
def test_artifact_family_receipt_maximum_age_is_enforced(
    tmp_path: Path,
    private_encounter: bool,
    issued_at: str,
) -> None:
    context = _setup(
        tmp_path,
        request_payload=_private_request_payload() if private_encounter else _request_payload(),
    )
    body = _evidence_body(context["composition"], context["authorization"])  # type: ignore[arg-type]
    body["issued_at"] = issued_at
    evidence = sign_envelope(body, context["signer"])  # type: ignore[arg-type]
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert any("receipt_freshness_window_exceeded" in value for value in result["blocked_reasons"])


def test_top_level_expiry_cannot_exceed_signing_key_expiry(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    body = _evidence_body(context["composition"], context["authorization"])  # type: ignore[arg-type]
    short_key_signer = _signer(
        seed=bytes(reversed(range(32))),
        not_after="2026-07-11T10:03:59Z",
    )
    evidence = sign_envelope(body, short_key_signer)
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=evidence,
        evidence_registry=Ed25519KeyRegistry([short_key_signer.key_record]),
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert any("key_or_receipt_chronology_invalid" in value for value in result["blocked_reasons"])


@pytest.mark.parametrize(
    ("issued_at", "expires_at"),
    [
        ("2026-07-11T08:00:00Z", "2026-07-11T09:59:59Z"),
        ("2026-07-11T10:00:01Z", "2026-07-11T10:30:00Z"),
    ],
)
def test_build_authorization_must_be_current(
    tmp_path: Path,
    issued_at: str,
    expires_at: str,
) -> None:
    context = _setup(tmp_path)
    authorization = _authorization(
        context["composition"],  # type: ignore[arg-type]
        issued_at=issued_at,
        expires_at=expires_at,
    )
    evidence = sign_envelope(
        _evidence_body(context["composition"], authorization),  # type: ignore[arg-type]
        context["signer"],  # type: ignore[arg-type]
    )
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        authorization,
        evidence_envelope=evidence,
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert "build_authorization_not_current" in result["blocked_reasons"]
    assert context["quota"].calls == []  # type: ignore[union-attr]


def test_successful_build_persists_exact_lineage_projection_and_idempotent_replay(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == "closed_consumed"
    assert result["product_projection"]["state"] == "complete_internal"
    assert result["product_projection"]["publication_allowed"] is False
    assert result["product_projection"]["serving_allowed"] is False
    assert result["product_projection"]["output_manifest_ref"] == ""
    assert result["product_projection"]["artifact_ref"] == ""
    assert result["output_manifest_ref"] == "manifest:fixture:v1"
    assert context["quota"].calls == ["reserve", "commit_attempt", "consume"]  # type: ignore[union-attr]
    assert len(context["execution"].calls) == 1  # type: ignore[union-attr]
    execution_request = context["execution"].calls[0]  # type: ignore[union-attr]
    target = _execution_target()
    assert execution_request["artifact_family"] == target["artifact_family"]
    assert execution_request["environment"] == target["environment"]
    assert execution_request["provider_route_digest"] == target["provider_route_digest"]
    assert execution_request["gate_versions"] == target["gate_versions"]
    history = context["ledger"].build_history("build-fixture-v1")  # type: ignore[union-attr]
    assert [row["state"] for row in history] == [
        "authorization_verified",
        "reservation_held",
        "attempt_committed",
        "charge_pending",
        "consumed",
        "closed_consumed",
    ]
    assert all(row["idempotency"] == history[0]["idempotency"] for row in history)
    assert all(row["parentage"] == history[0]["parentage"] for row in history)

    restarted_ledger = DurableSpatialLedger(tmp_path / "ledger")
    persisted = restarted_ledger.find_build("build-fixture-v1")
    assert persisted is not None
    assert persisted["product_projection"] == result["product_projection"]
    replay_quota = FakeQuotaAdapter()
    replay_execution = FakeExecutionAdapter()
    restarted = GovernedSpatialOrchestrator(
        ledger=restarted_ledger,
        signer=context["signer"],  # type: ignore[arg-type]
        quota_adapter=replay_quota,
        execution_adapter=replay_execution,
        quality_gate=FakeQualityGate(),
        now=lambda: NOW,
    )
    replay = restarted.build(
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert replay["idempotent_replay"] is True
    assert replay["product_projection"] == result["product_projection"]
    assert replay_quota.calls == []
    assert replay_execution.calls == []


def test_retryable_no_charge_requires_reconciliation_before_second_attempt(tmp_path: Path) -> None:
    execution = FakeExecutionAdapter(state="retryable_no_charge")
    context = _setup(tmp_path, execution=execution, maximum_attempts=2)
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == "cancelled_reconciliation_pending"
    assert result["quota"]["attempt_number"] == 1
    assert context["quota"].calls == ["reserve", "commit_attempt"]  # type: ignore[union-attr]
    assert len(execution.calls) == 1
    assert result["automatic_retry_allowed"] is False


def test_naive_adapter_reservation_expiry_is_unknown_and_not_executed(tmp_path: Path) -> None:
    class NaiveReservationQuota(FakeQuotaAdapter):
        def reserve(self, request: Mapping[str, object]) -> Mapping[str, object]:
            self._call("reserve")
            return {
                "reservation_ref_digest": _digest("reservation"),
                "reservation_expires_at": "2026-07-11T10:20:00",
            }

    quota = NaiveReservationQuota()
    context = _setup(tmp_path, quota=quota)
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == "authorization_verified"
    assert result["blocked_reasons"] == ["reservation_outcome_unknown"]
    assert result["reconciliation_required"] is True
    assert quota.calls == ["reserve"]
    assert context["execution"].calls == []  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("boundary", "expected_state"),
    [
        ("reserve", "authorization_verified"),
        ("commit_attempt", "reservation_held"),
        ("execute", "cancelled_reconciliation_pending"),
        ("consume", "cancelled_reconciliation_pending"),
        ("quality", "compensated"),
        ("compensate", "compensation_failed_blocked"),
    ],
)
def test_side_effect_boundary_failures_are_durable_and_never_automatically_retried(
    tmp_path: Path,
    boundary: str,
    expected_state: str,
) -> None:
    quota = FakeQuotaAdapter(fail_at=boundary if boundary in {"reserve", "commit_attempt", "consume", "compensate"} else "")
    execution = FakeExecutionAdapter(fail=boundary == "execute")
    quality = FakeQualityGate(passed=boundary not in {"quality", "compensate"}, fail=boundary == "quality")
    context = _setup(tmp_path, quota=quota, execution=execution, quality=quality)
    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == expected_state
    assert result.get("output_digest") in {None, ""}
    assert result["product_projection"]["state"] == "blocked"
    before = (list(quota.calls), len(execution.calls), list(quality.calls))
    replay = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert replay["idempotent_replay"] is True
    assert (quota.calls, len(execution.calls), quality.calls) == before


class FailingTransitionLedger(DurableSpatialLedger):
    def __init__(self, root: Path, *, fail_state: str) -> None:
        self.fail_state = fail_state
        self.armed = True
        super().__init__(root)

    def append_build_transition(self, key: str, receipt: Mapping[str, object]) -> dict[str, object]:
        if self.armed and receipt.get("state") == self.fail_state:
            self.armed = False
            raise OSError("forced_transition_persist_failure")
        return super().append_build_transition(key, receipt)


class InitialTransitionBarrierLedger(DurableSpatialLedger):
    def __init__(self, root: Path) -> None:
        self.initial_barrier = threading.Barrier(2)
        super().__init__(root)

    def append_build_transition(self, key: str, receipt: Mapping[str, object]) -> dict[str, object]:
        if (
            receipt.get("state") == "authorization_verified"
            and receipt.get("transition_sequence") is None
            and receipt.get("operation_failure_evidence") is None
        ):
            self.initial_barrier.wait(timeout=5)
        return super().append_build_transition(key, receipt)


@pytest.mark.parametrize(
    ("fail_state", "persisted_state", "expected_quota_calls"),
    [
        ("reservation_held", "authorization_verified", ["reserve"]),
        ("consumed", "charge_pending", ["reserve", "commit_attempt", "consume"]),
    ],
)
def test_write_ahead_intent_prevents_retry_after_post_side_effect_persist_failure(
    tmp_path: Path,
    fail_state: str,
    persisted_state: str,
    expected_quota_calls: list[str],
) -> None:
    root = tmp_path / "ledger"
    ledger = FailingTransitionLedger(root, fail_state=fail_state)
    context = _setup(tmp_path, ledger=ledger)
    with pytest.raises(OSError, match="forced_transition_persist_failure"):
        context["orchestrator"].build(  # type: ignore[union-attr]
            context["authorization"],  # type: ignore[arg-type]
            evidence_envelope=context["evidence"],  # type: ignore[arg-type]
            evidence_registry=context["registry"],  # type: ignore[arg-type]
            observed_at=NOW,
        )
    assert context["quota"].calls == expected_quota_calls  # type: ignore[union-attr]

    restarted_ledger = DurableSpatialLedger(root)
    persisted = restarted_ledger.find_build("build-fixture-v1")
    assert persisted is not None
    assert persisted["state"] == persisted_state
    assert persisted["pending_operation"]["outcome"] == "pending_or_unknown"
    fresh_quota = FakeQuotaAdapter()
    fresh_execution = FakeExecutionAdapter()
    restarted = GovernedSpatialOrchestrator(
        ledger=restarted_ledger,
        signer=context["signer"],  # type: ignore[arg-type]
        quota_adapter=fresh_quota,
        execution_adapter=fresh_execution,
        quality_gate=FakeQualityGate(),
        now=lambda: NOW,
    )
    replay = restarted.build(
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert replay["idempotent_replay"] is True
    assert fresh_quota.calls == []
    assert fresh_execution.calls == []


def test_concurrent_build_executes_quota_and_adapter_boundaries_once(tmp_path: Path) -> None:
    ledger = InitialTransitionBarrierLedger(tmp_path / "ledger")
    context = _setup(tmp_path, ledger=ledger)

    def build_once(_: int) -> dict[str, object]:
        return context["orchestrator"].build(  # type: ignore[union-attr]
            context["authorization"],  # type: ignore[arg-type]
            evidence_envelope=context["evidence"],  # type: ignore[arg-type]
            evidence_registry=context["registry"],  # type: ignore[arg-type]
            observed_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(build_once, range(2)))
    assert context["quota"].calls == ["reserve", "commit_attempt", "consume"]  # type: ignore[union-attr]
    assert len(context["execution"].calls) == 1  # type: ignore[union-attr]
    assert all(str(result["state"]) in BUILD_STATES for result in results)
    assert any(result["state"] == "closed_consumed" for result in results)
    assert any(result.get("idempotent_replay") is True for result in results)


def test_restart_revalidates_build_transition_chain_even_with_rehashed_index(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    root = tmp_path / "ledger"
    index_path = root / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    transition = index["builds"]["build-fixture-v1"]["transitions"][1]
    receipt_path = root / transition["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["transition_sequence"] = 99
    receipt_path.write_text(json.dumps(receipt, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(receipt_path, 0o600)
    transition["receipt_digest"] = payload_digest(receipt)
    index_material = {
        "schema_name": index["schema_name"],
        "compositions": index["compositions"],
        "builds": index["builds"],
        "privacy": index["privacy"],
    }
    index["index_digest"] = payload_digest(index_material)
    index_path.write_text(json.dumps(index, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(index_path, 0o600)

    with pytest.raises(SpatialStateIntegrityError, match="transition_chain_invalid"):
        DurableSpatialLedger(root)


def test_privacy_tombstone_is_idempotent_restart_safe_and_blocks_build(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    scope = str(context["composition"]["composition_digest"])
    reason = _digest("privacy-reason")
    cascade = [_digest("public-withdrawal"), _digest("cache-purge"), _digest("deletion-attempt")]
    first = context["orchestrator"].record_privacy_action(  # type: ignore[union-attr]
        scope_digest=scope,
        action="deleted",
        reason_digest=reason,
        observed_at=NOW,
        cascade_evidence_digests=cascade,
    )
    duplicate = context["orchestrator"].record_privacy_action(  # type: ignore[union-attr]
        scope_digest=scope,
        action="deleted",
        reason_digest=reason,
        observed_at=NOW,
        cascade_evidence_digests=cascade,
    )
    assert first == duplicate
    assert first["serving_allowed"] is False
    assert first["build_allowed"] is False
    assert first["restoration_allowed"] is False
    restarted = DurableSpatialLedger(tmp_path / "ledger")
    assert restarted.privacy_status(scope) == first
    assert len(restarted.privacy_history(scope)) == 1

    result = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert result["state"] == GENERIC_BLOCKED_STATE
    assert "privacy_tombstone_active" in result["blocked_reasons"]
    assert context["quota"].calls == []  # type: ignore[union-attr]


@pytest.mark.parametrize("action", ["revoked", "deleted"])
def test_completed_build_replay_projects_current_privacy_tombstone_without_manifest(
    tmp_path: Path,
    action: str,
) -> None:
    telemetry: list[dict[str, object]] = []
    context = _setup(tmp_path, telemetry=telemetry)
    completed = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert completed["state"] == "closed_consumed"
    assert completed["output_manifest_ref"] == "manifest:fixture:v1"
    assert completed["product_projection"]["output_manifest_ref"] == ""

    scope = str(context["composition"]["composition_digest"])
    context["orchestrator"].record_privacy_action(  # type: ignore[union-attr]
        scope_digest=scope,
        action=action,
        reason_digest=_digest(f"privacy-{action}"),
        observed_at=NOW,
        cascade_evidence_digests=[_digest("public-suppression"), _digest("cache-purge")],
    )
    replay = context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert replay["state"] == "closed_consumed"
    assert replay["output_manifest_ref"] == "manifest:fixture:v1"
    assert replay["product_projection"]["state"] == "unavailable"
    assert replay["product_projection"]["privacy_tombstone_active"] is True
    assert replay["product_projection"]["output_manifest_ref"] == ""
    assert replay["product_projection"]["artifact_ref"] == ""
    assert replay["product_projection"]["serving_allowed"] is False
    assert telemetry[-1]["reason_codes"] == ["privacy_tombstone_active"]
    assert "manifest:fixture:v1" not in json.dumps(telemetry)

    restart_quota = FakeQuotaAdapter()
    restart_execution = FakeExecutionAdapter()
    restarted = GovernedSpatialOrchestrator(
        ledger=DurableSpatialLedger(tmp_path / "ledger"),
        signer=context["signer"],  # type: ignore[arg-type]
        quota_adapter=restart_quota,
        execution_adapter=restart_execution,
        execution_target=_execution_target(),
        quality_gate=FakeQualityGate(),
        now=lambda: NOW,
    )
    restart_replay = restarted.build(
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert restart_replay["product_projection"]["state"] == "unavailable"
    assert restart_replay["product_projection"]["output_manifest_ref"] == ""
    assert restart_quota.calls == []
    assert restart_execution.calls == []


def test_legal_hold_is_evidence_only_and_invalid_hold_fails_closed(tmp_path: Path) -> None:
    ledger = DurableSpatialLedger(tmp_path / "ledger")
    scope = _digest("scope")
    valid = ledger.record_privacy_action(
        scope_digest=scope,
        action="withdrawn",
        reason_digest=_digest("reason-valid"),
        observed_at=NOW,
        legal_hold={
            "case_ref": "case:fixture:v1",
            "authority_ref": "authority:privacy:v1",
            "owner_ref": "owner:privacy:v1",
            "scope_digest": scope,
            "issued_at": "2026-07-11T09:00:00Z",
            "expires_at": "2026-08-01T09:00:00Z",
            "review_due_at": "2026-07-20T09:00:00Z",
        },
    )
    assert valid["legal_hold"]["state"] == "valid_evidence_only"
    assert valid["source_bytes_retained"] is True
    assert valid["serving_allowed"] is False

    invalid = ledger.record_privacy_action(
        scope_digest=_digest("other-scope"),
        action="revoked",
        reason_digest=_digest("reason-invalid"),
        observed_at=NOW,
        legal_hold={"case_ref": "case:incomplete"},
    )
    assert invalid["legal_hold"]["state"] == "blocked_invalid"
    assert invalid["source_bytes_retained"] is False
    assert invalid["serving_allowed"] is False

    expired_scope = _digest("expired-scope")
    expired = ledger.record_privacy_action(
        scope_digest=expired_scope,
        action="deleted",
        reason_digest=_digest("reason-expired"),
        observed_at=NOW,
        legal_hold={
            "case_ref": "case:expired:v1",
            "authority_ref": "authority:privacy:v1",
            "owner_ref": "owner:privacy:v1",
            "scope_digest": expired_scope,
            "issued_at": "2026-06-01T09:00:00Z",
            "expires_at": "2026-06-30T09:00:00Z",
            "review_due_at": "2026-06-20T09:00:00Z",
        },
    )
    assert expired["legal_hold"]["state"] == "blocked_invalid"
    assert expired["legal_hold"]["reason_code"] == "legal_hold_not_current"
    assert expired["source_bytes_retained"] is False


def test_privacy_scope_cannot_restore_itself(tmp_path: Path) -> None:
    context = _setup(tmp_path)
    with pytest.raises(SpatialPrivacyError, match="self_restoration_forbidden"):
        context["orchestrator"].restore_privacy_scope(_digest("scope"))  # type: ignore[union-attr]


def _walkthrough_metrics() -> dict[str, object]:
    return {
        "artifact_sha256": "c" * 64,
        "final_encoded_artifact": True,
        "provenance_refs": ["provenance:fixture:v1"],
        "all_frames_evaluated": True,
        "shot_count": 1,
        "cut_count": 0,
        "teleport_count": 0,
        "collision_failure_count": 0,
        "wall_or_door_clip_count": 0,
        "required_room_count": 2,
        "covered_room_count": 2,
        "stable_room_topology_percent": 100.0,
        "stable_furniture_on_revisit": True,
        "combat_overlay_count": 0,
        "stable_actor_identity": True,
        "stable_actor_transform": True,
        "black_burst_count": 0,
        "blank_burst_count": 0,
        "frozen_burst_count": 0,
        "corrupt_burst_count": 0,
        "repeated_frame_burst_count": 0,
        "container_fps": 60.0,
        "effective_motion_fps": 30.0,
        "max_duplicate_frame_run_during_motion": 2,
        "all_frame_continuity_max_delta": 18.0,
        "rotation_gate": {"status": "pass", "proof_ref": "proof:rotation:v1"},
        "spatial_drift_gate": {"status": "pass", "proof_ref": "proof:drift:v1"},
        "desktop_decode_pass": True,
        "mobile_decode_pass": True,
        "horizontal_overflow": False,
        "layout_shift_detected": False,
        "audio_present": False,
    }


def _publication_authorization() -> dict[str, object]:
    return {
        "state": "authorized",
        "lease_ref": "publication-lease:fixture:v1",
        "issued_at": "2026-07-11T09:55:00Z",
        "expires_at": "2026-07-11T10:30:00Z",
    }


def test_publication_remains_blocked_without_immutable_artifact_verifier() -> None:
    service = GovernedSpatialQualityService()
    quality = service.audit_walkthrough(_walkthrough_metrics(), observed_at=NOW)
    decision = service.evaluate_publication(
        output_digest="sha256:" + ("c" * 64),
        quality_receipt=quality,
        rights_state="verified",
        provenance_refs=["provenance:fixture:v1"],
        capability_state="verified",
        publication_authorization=_publication_authorization(),
        privacy_tombstone=None,
        observed_at=NOW,
    )
    assert decision["state"] == "blocked"
    assert decision["publication_allowed"] is False
    assert decision["ready_projection_allowed"] is False
    assert "immutable_artifact_decision_missing" in decision["issues"]


def test_publication_verifier_cannot_bypass_milestone_one_authority_ceiling() -> None:
    verifier_calls: list[dict[str, object]] = []

    def verify_decision(decision: Mapping[str, object]) -> bool:
        verifier_calls.append(dict(decision))
        return True

    service = GovernedSpatialQualityService(immutable_artifact_verifier=verify_decision)
    quality = service.audit_walkthrough(_walkthrough_metrics(), observed_at=NOW)
    immutable = {
        "state": "verified",
        "decision_ref": "artifact-decision:fixture:v1",
        "output_digest": "sha256:" + ("c" * 64),
        "quality_receipt_digest": "sha256:" + str(quality["receipt_digest"]),
    }
    verified_only = service.evaluate_publication(
        output_digest="sha256:" + ("c" * 64),
        quality_receipt=quality,
        rights_state="verified",
        provenance_refs=["provenance:fixture:v1"],
        capability_state="verified",
        publication_authorization=_publication_authorization(),
        privacy_tombstone=None,
        immutable_artifact_decision=immutable,
        observed_at=NOW,
    )
    assert verified_only["state"] == "blocked"
    assert verified_only["publication_allowed"] is False
    assert verified_only["ready_projection_allowed"] is False
    assert "milestone_1_publication_authority_absent" in verified_only["issues"]
    assert len(verifier_calls) == 1

    replayed_authority = _publication_authorization()
    replayed_authority["lease_ref"] = "publication-lease:unbound-replay:v1"
    replayed = service.evaluate_publication(
        output_digest="sha256:" + ("c" * 64),
        quality_receipt=quality,
        rights_state="verified",
        provenance_refs=["provenance:changed-but-safe:v1"],
        capability_state="verified",
        publication_authorization=replayed_authority,
        privacy_tombstone=None,
        immutable_artifact_decision=immutable,
        observed_at=NOW,
    )
    assert replayed["publication_allowed"] is False
    assert "milestone_1_publication_authority_absent" in replayed["issues"]

    tampered_quality = deepcopy(quality)
    tampered_quality["metrics_digest"] = "0" * 64
    blocked = service.evaluate_publication(
        output_digest="sha256:" + ("c" * 64),
        quality_receipt=tampered_quality,
        rights_state="verified",
        provenance_refs=["provenance:fixture:v1"],
        capability_state="verified",
        publication_authorization=_publication_authorization(),
        privacy_tombstone=None,
        immutable_artifact_decision=immutable,
        observed_at=NOW,
    )
    assert blocked["publication_allowed"] is False
    assert "quality_receipt_digest_invalid" in blocked["issues"]

    verifier_calls.clear()
    mismatched = deepcopy(immutable)
    mismatched["output_digest"] = "sha256:" + ("d" * 64)
    binding_blocked = service.evaluate_publication(
        output_digest="sha256:" + ("c" * 64),
        quality_receipt=quality,
        rights_state="verified",
        provenance_refs=["provenance:fixture:v1"],
        capability_state="verified",
        publication_authorization=_publication_authorization(),
        privacy_tombstone=None,
        immutable_artifact_decision=mismatched,
        observed_at=NOW,
    )
    assert binding_blocked["publication_allowed"] is False
    assert "immutable_artifact_output_binding_mismatch" in binding_blocked["issues"]
    assert verifier_calls == []


def test_quality_audits_reject_naive_observation_time() -> None:
    with pytest.raises(ValueError, match="observed_at_offset_required"):
        GovernedSpatialQualityService().audit_walkthrough(
            _walkthrough_metrics(),
            observed_at=datetime(2026, 7, 11, 10, 0),
        )


def test_telemetry_is_allowlisted_and_redacted(tmp_path: Path) -> None:
    telemetry: list[dict[str, object]] = []
    context = _setup(tmp_path, telemetry=telemetry)
    context["orchestrator"].build(  # type: ignore[union-attr]
        context["authorization"],  # type: ignore[arg-type]
        evidence_envelope=context["evidence"],  # type: ignore[arg-type]
        evidence_registry=context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    serialized = json.dumps(telemetry, sort_keys=True)
    assert "tenant:fixture" not in serialized
    assert "authorization:fixture:v1" not in serialized
    assert "manifest:fixture:v1" not in serialized
    assert all(
        set(event)
        == {
            "event_type",
            "state",
            "request_digest",
            "composition_digest",
            "build_request_digest",
            "attempt_number",
            "reason_codes",
            "quota_actions",
            "execution_actions",
            "route_visit_count",
            "route_revisit_count",
        }
        for event in telemetry
    )


def _assert_property_actions_zero(context: Mapping[str, object]) -> None:
    assert context["quota"].calls == []  # type: ignore[union-attr]
    assert context["execution"].calls == []  # type: ignore[union-attr]
    assert context["quality"].calls == []  # type: ignore[union-attr]


def _property_journal_states(root: Path) -> list[str]:
    journal = root / "material.journal.jsonl"
    if not journal.exists():
        return []
    return [json.loads(line)["state"] for line in journal.read_text().splitlines()]


def test_property_r11_happy_compose_persists_verified_receipt_before_guarded_seal(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path)
    ledger = context["ledger"]
    store = context["store"]
    ordering: list[str] = []

    def observe_store(point: str) -> None:
        if point == "after_seal_intent":
            receipt = ledger.find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
            assert receipt is not None
            ordering.append("receipt_before_seal_intent")

    store._crash_hook = observe_store  # type: ignore[union-attr]
    result = _compose_property(context)

    assert ordering == ["receipt_before_seal_intent"]
    assert result["idempotent_replay"] is False
    receipt = ledger.find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    assert receipt["contract_name"] == PROPERTY_COMPOSITION_RECEIPT_CONTRACT_NAME
    assert receipt["artifact_family"] == PROPERTY_ARTIFACT_FAMILY
    assert receipt["content_profile"] == PROPERTY_CONTENT_PROFILE
    assert receipt["authorization_owner"] == PROPERTY_AUTHORIZATION_OWNER
    assert receipt["material_identity"] == result["material_identity"]
    assert receipt["material_digest"] == result["material_digest"]
    assert not ({"state", "status", "sealed", "ciphertext", "availability"} & set(receipt))
    verify_signed_envelope(
        receipt,
        context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    with ledger.composition_privacy_lifecycle_guard(  # type: ignore[union-attr]
        result["composition_digest"]
    ) as lifecycle_guard:
        loaded = store.load(  # type: ignore[union-attr]
            result["composition_digest"], lifecycle_guard=lifecycle_guard
        )
    assert isinstance(loaded, GovernedSpatialExecutionMaterialV1)
    assert execution_material_digest(loaded) == result["material_digest"]
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    states = [json.loads(line)["state"] for line in journal.read_text().splitlines()]
    assert states == ["seal_intent", "sealed"]
    persisted = bytearray()
    for root in (tmp_path / "property-ledger", tmp_path / "property-material"):
        for directory, _, filenames in os.walk(root):
            for filename in filenames:
                persisted.extend((Path(directory) / filename).read_bytes())
    for fragment in (
        b"living",
        b"style-pack-v1",
        b"source-packet:fixture:v1",
        PROPERTY_STORE_KEY,
    ):
        assert fragment not in persisted
    _assert_property_actions_zero(context)


def test_property_r11_requires_persistent_ledger_before_any_authority_or_material_effect(
    tmp_path: Path,
) -> None:
    evidence = _property_policy_evidence()
    policy_verifier = FakePropertyPolicyVerifier(
        [_property_policy_verification(evidence)]
    )
    input_verifier = FakePropertyInputAuthorityVerifier()
    ledger = DurableSpatialLedger()
    context = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=policy_verifier,
        input_verifier=input_verifier,
        ledger=ledger,
    )

    with pytest.raises(SpatialStateError, match="property_persistent_ledger_required"):
        _compose_property(context)

    assert policy_verifier.calls == []
    assert input_verifier.calls == []
    assert ledger.integrity_summary()["composition_count"] == 0
    assert not (tmp_path / "property-material" / "material.journal.jsonl").exists()
    _assert_property_actions_zero(context)


def test_property_orchestrator_rejects_store_bound_to_another_ledger_before_effects(
    tmp_path: Path,
) -> None:
    ledger_a = DurableSpatialLedger(tmp_path / "bound-ledger-a")
    ledger_b = DurableSpatialLedger(tmp_path / "bound-ledger-b")
    current = [NOW]
    store = _property_material_store(
        tmp_path / "wrong-bound-material",
        current,
        lifecycle_authority=ledger_a.lifecycle_authority,
    )
    evidence = _property_policy_evidence()
    policy_verifier = FakePropertyPolicyVerifier(
        [_property_policy_verification(evidence)]
    )
    input_verifier = FakePropertyInputAuthorityVerifier()
    context = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=policy_verifier,
        input_verifier=input_verifier,
        ledger=ledger_b,
        store=store,
        current=current,
    )

    with pytest.raises(
        SpatialStateError,
        match="property_material_store_lifecycle_authority_mismatch",
    ):
        _compose_property(context)

    assert policy_verifier.calls == []
    assert input_verifier.calls == []
    assert ledger_b.integrity_summary()["composition_count"] == 0
    assert not (tmp_path / "wrong-bound-material" / "material.journal.jsonl").exists()
    _assert_property_actions_zero(context)


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        ("missing", "property_input_authority_missing"),
        ("stale", "property_input_authority_stale"),
        ("source_digest", "property_input_authority_source_digest_mismatch"),
        ("source_timestamp", "property_input_authority_source_timestamp_mismatch"),
        ("style_digest", "property_input_authority_style_digest_mismatch"),
        ("asset_digest", "property_input_authority_asset_digest_mismatch"),
        ("revoked", "property_input_authority_revoked"),
        ("unverifiable", "property_input_authority_unverifiable"),
    ],
)
def test_property_input_authority_failures_before_receipt_are_zero_effect(
    tmp_path: Path,
    condition: str,
    reason: str,
) -> None:
    valid = _property_input_authority_verification()
    bad: object
    if condition in {"missing", "stale", "revoked"}:
        bad = replace(valid, state=condition)
    elif condition == "source_digest":
        bad = replace(valid, source_packet_digest=_digest("wrong-source-authority"))
    elif condition == "source_timestamp":
        bad = replace(
            valid,
            source_packet_created_at=valid.source_packet_created_at + timedelta(minutes=1),
        )
    elif condition == "style_digest":
        bad = replace(valid, style_snapshot_digest=_digest("wrong-style-authority"))
    elif condition == "asset_digest":
        bad = replace(valid, asset_bindings_digest=_digest("wrong-asset-authority"))
    else:
        bad = RuntimeError("private input authority detail")
    input_verifier = FakePropertyInputAuthorityVerifier([bad])
    context = _property_context(tmp_path, input_verifier=input_verifier)

    with pytest.raises(SpatialStateError, match=reason):
        _compose_property(context)

    assert len(input_verifier.calls) == 1
    assert context["ledger"].integrity_summary()["composition_count"] == 0  # type: ignore[union-attr]
    assert not (tmp_path / "property-material" / "material.journal.jsonl").exists()
    _assert_property_actions_zero(context)


def test_property_input_authority_verifier_is_mandatory_before_receipt(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path, input_verifier=None)

    with pytest.raises(
        SpatialStateError, match="property_input_authority_verifier_unavailable"
    ):
        _compose_property(context)

    assert context["verifier"].calls == []  # type: ignore[union-attr]
    assert context["ledger"].integrity_summary()["composition_count"] == 0  # type: ignore[union-attr]
    assert not (tmp_path / "property-material" / "material.journal.jsonl").exists()
    _assert_property_actions_zero(context)


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        ("missing", "property_input_authority_missing"),
        ("stale", "property_input_authority_stale"),
        ("source_digest", "property_input_authority_source_digest_mismatch"),
        ("source_timestamp", "property_input_authority_source_timestamp_mismatch"),
        ("style_digest", "property_input_authority_style_digest_mismatch"),
        ("asset_digest", "property_input_authority_asset_digest_mismatch"),
        ("revoked", "property_input_authority_revoked"),
        ("unverifiable", "property_input_authority_unverifiable"),
        ("changed", "property_input_authority_changed_before_seal"),
    ],
)
def test_property_input_authority_failures_before_seal_leave_only_signed_receipt(
    tmp_path: Path,
    condition: str,
    reason: str,
) -> None:
    valid = _property_input_authority_verification()
    bad: object
    if condition in {"missing", "stale", "revoked"}:
        bad = replace(valid, state=condition)
    elif condition == "source_digest":
        bad = replace(valid, source_packet_digest=_digest("changed-source-authority"))
    elif condition == "source_timestamp":
        bad = replace(
            valid,
            source_packet_created_at=valid.source_packet_created_at + timedelta(minutes=1),
        )
    elif condition == "style_digest":
        bad = replace(valid, style_snapshot_digest=_digest("changed-style-authority"))
    elif condition == "asset_digest":
        bad = replace(valid, asset_bindings_digest=_digest("changed-asset-authority"))
    elif condition == "changed":
        bad = replace(
            valid,
            source_authority_receipt_digest=_digest("rotated-source-authority-receipt"),
        )
    else:
        bad = RuntimeError("private pre-seal input authority detail")
    input_verifier = FakePropertyInputAuthorityVerifier([valid, bad])
    context = _property_context(tmp_path, input_verifier=input_verifier)

    with pytest.raises(SpatialStateError, match=reason):
        _compose_property(context)

    receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    verify_signed_envelope(
        receipt,
        context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert len(input_verifier.calls) == 2
    assert context["ledger"].integrity_summary()["composition_count"] == 1  # type: ignore[union-attr]
    assert not (tmp_path / "property-material" / "material.journal.jsonl").exists()
    _assert_property_actions_zero(context)


def test_property_input_authority_lineage_is_signed_exact_and_stable_on_replay(
    tmp_path: Path,
) -> None:
    input_verifier = FakePropertyInputAuthorityVerifier()
    context = _property_context(tmp_path, input_verifier=input_verifier)
    first = _compose_property(context)
    receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    expected = _property_input_authority_verification()
    projection = _property_input_authority_projection(expected)
    assert receipt["input_authority_digest"] == payload_digest(projection)
    assert receipt["source_authority_receipt_digest"] == expected.source_authority_receipt_digest
    assert receipt["style_registry_receipt_digest"] == expected.style_registry_receipt_digest
    assert receipt["asset_authority_receipt_digest"] == expected.asset_authority_receipt_digest
    assert receipt["input_authority_verified_at"] == utc_iso(expected.verified_at)
    assert receipt["input_authority_expires_at"] == utc_iso(expected.expires_at)
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    journal_before = journal.read_bytes()
    receipt_before = payload_digest(receipt)

    replay = _compose_property(context)

    assert replay["idempotent_replay"] is True
    assert replay["composition_digest"] == first["composition_digest"]
    assert replay["retention_expires_at"] == first["retention_expires_at"]
    assert payload_digest(
        context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    ) == receipt_before
    assert journal.read_bytes() == journal_before
    assert len(input_verifier.calls) == 4
    _assert_property_actions_zero(context)


def test_property_replay_rejects_changed_current_input_authority_lineage(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path)
    _compose_property(context)
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    journal_before = journal.read_bytes()
    changed = replace(
        _property_input_authority_verification(),
        asset_authority_receipt_digest=_digest("changed-current-asset-authority"),
    )
    replay = _property_context(
        tmp_path,
        evidence=context["evidence"],  # type: ignore[arg-type]
        input_verifier=FakePropertyInputAuthorityVerifier([changed]),
        ledger=context["ledger"],  # type: ignore[arg-type]
        store=context["store"],  # type: ignore[arg-type]
        current=context["current"],  # type: ignore[arg-type]
    )

    with pytest.raises(
        SpatialIdempotencyConflict, match="property_composition_replay_conflict"
    ):
        _compose_property(replay)

    assert journal.read_bytes() == journal_before
    _assert_property_actions_zero(replay)


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        ("missing", "property_policy_evidence_required"),
        ("stale", "property_policy_evidence_stale"),
        ("digest_mismatched", "property_policy_digest_mismatch"),
        ("mode_mismatched", "property_policy_mode_mismatch"),
        ("expired", "property_policy_evidence_expired"),
        ("revoked", "property_policy_revoked"),
        ("unverifiable", "property_policy_unverifiable"),
        ("acceptance_mismatched", "property_policy_independent_acceptance_invalid"),
        ("evidence_outlives_policy", "property_policy_evidence_outlives_policy"),
    ],
)
def test_property_policy_failures_before_compose_have_zero_durable_or_action_effects(
    tmp_path: Path, condition: str, reason: str,
) -> None:
    evidence = _property_policy_evidence()
    outcome: object = _property_policy_verification(evidence)
    supplied: Mapping[str, object] | None = evidence
    if condition == "missing":
        supplied = None
    elif condition == "stale":
        evidence = _property_policy_evidence(
            approved_at=NOW - timedelta(hours=25),
            expires_at=NOW + timedelta(minutes=30),
        )
        supplied = evidence
        outcome = _property_policy_verification(evidence)
    elif condition == "digest_mismatched":
        evidence = _property_policy_evidence(policy_digest=_digest("wrong-policy"))
        supplied = evidence
        outcome = _property_policy_verification(evidence)
    elif condition == "mode_mismatched":
        outcome = replace(outcome, policy_mode=0o640)  # type: ignore[arg-type]
    elif condition == "expired":
        evidence = _property_policy_evidence(expires_at=NOW)
        supplied = evidence
        outcome = _property_policy_verification(evidence)
    elif condition == "revoked":
        outcome = replace(outcome, state="revoked")  # type: ignore[arg-type]
    elif condition == "unverifiable":
        outcome = RuntimeError("private policy verifier detail")
    elif condition == "acceptance_mismatched":
        outcome = replace(  # type: ignore[arg-type]
            outcome,
            independent_acceptance_digest=_digest("wrong-acceptance"),
        )
    elif condition == "evidence_outlives_policy":
        outcome = replace(  # type: ignore[arg-type]
            outcome,
            policy_expires_at=NOW + timedelta(hours=6),
        )
    verifier = FakePropertyPolicyVerifier([outcome])
    context = _property_context(tmp_path, evidence=evidence, verifier=verifier)

    with pytest.raises(SpatialStateError, match=reason):
        _compose_property(context, evidence=supplied)

    assert context["ledger"].integrity_summary()["composition_count"] == 0  # type: ignore[union-attr]
    assert not (tmp_path / "property-material" / "material.journal.jsonl").exists()
    _assert_property_actions_zero(context)


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        ("missing", "property_policy_missing"),
        ("stale", "property_policy_stale"),
        ("digest_mismatched", "property_policy_verification_mismatch"),
        ("mode_mismatched", "property_policy_mode_mismatch"),
        ("expired", "property_policy_expired"),
        ("revoked", "property_policy_revoked"),
        ("unverifiable", "property_policy_unverifiable"),
    ],
)
def test_property_policy_failures_before_seal_leave_only_signed_receipt_and_zero_actions(
    tmp_path: Path, condition: str, reason: str,
) -> None:
    evidence = _property_policy_evidence()
    valid = _property_policy_verification(evidence)
    bad: object
    if condition in {"missing", "stale", "expired", "revoked"}:
        bad = replace(valid, state=condition)
    elif condition == "digest_mismatched":
        bad = replace(valid, policy_digest=_digest("changed-policy"))
    elif condition == "mode_mismatched":
        bad = replace(valid, policy_mode=0o640)
    else:
        bad = RuntimeError("private pre-seal verifier detail")
    verifier = FakePropertyPolicyVerifier([valid, bad])
    context = _property_context(tmp_path, evidence=evidence, verifier=verifier)

    with pytest.raises(SpatialStateError, match=reason):
        _compose_property(context)

    receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    verify_signed_envelope(
        receipt,
        context["registry"],  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert context["ledger"].integrity_summary()["composition_count"] == 1  # type: ignore[union-attr]
    assert not (tmp_path / "property-material" / "material.journal.jsonl").exists()
    _assert_property_actions_zero(context)


def test_property_exact_signed_receipt_replay_repairs_missing_store_without_retention_reset(
    tmp_path: Path,
) -> None:
    evidence = _property_policy_evidence()
    valid = _property_policy_verification(evidence)
    first_verifier = FakePropertyPolicyVerifier(
        [valid, replace(valid, state="missing")]
    )
    first = _property_context(tmp_path, evidence=evidence, verifier=first_verifier)
    with pytest.raises(SpatialStateError, match="property_policy_missing"):
        _compose_property(first)
    receipt = first["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    receipt_digest = payload_digest(receipt)
    assert _property_journal_states(tmp_path / "property-material") == []

    second_verifier = FakePropertyPolicyVerifier([valid])
    second = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=second_verifier,
        ledger=first["ledger"],  # type: ignore[arg-type]
        store=first["store"],  # type: ignore[arg-type]
        current=first["current"],  # type: ignore[arg-type]
    )
    repaired = _compose_property(second)

    assert repaired["idempotent_replay"] is True
    assert repaired["retention_anchor"] == "2026-07-11T09:30:00Z"
    assert repaired["retention_expires_at"] == "2026-08-10T09:30:00Z"
    assert payload_digest(
        second["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    ) == receipt_digest
    assert _property_journal_states(tmp_path / "property-material") == [
        "seal_intent",
        "sealed",
    ]
    _assert_property_actions_zero(first)
    _assert_property_actions_zero(second)


def test_property_exact_signed_receipt_replay_repairs_aborted_store_state(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path)

    def crash(point: str) -> None:
        if point == "after_seal_intent":
            raise RuntimeError("property-intent-crash")

    context["store"]._crash_hook = crash  # type: ignore[union-attr]
    with pytest.raises(RuntimeError, match="property-intent-crash"):
        _compose_property(context)
    receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    receipt_digest = payload_digest(receipt)
    assert _property_journal_states(tmp_path / "property-material") == ["seal_intent"]

    restarted_store = _property_material_store(
        tmp_path / "property-material",
        context["current"],  # type: ignore[arg-type]
        lifecycle_authority=context["ledger"].lifecycle_authority,  # type: ignore[union-attr]
    )
    restarted = _property_context(
        tmp_path,
        evidence=context["evidence"],  # type: ignore[arg-type]
        ledger=context["ledger"],  # type: ignore[arg-type]
        store=restarted_store,
        current=context["current"],  # type: ignore[arg-type]
    )
    result = _compose_property(restarted)

    assert result["idempotent_replay"] is True
    assert result["retention_expires_at"] == receipt["retention_expires_at"]
    assert payload_digest(
        restarted["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    ) == receipt_digest
    assert _property_journal_states(tmp_path / "property-material") == [
        "seal_intent",
        "seal_aborted_missing_ciphertext",
        "seal_intent",
        "sealed",
    ]
    _assert_property_actions_zero(context)
    _assert_property_actions_zero(restarted)


@pytest.mark.parametrize(
    ("crash_point", "policy_failure", "ciphertext_exists"),
    [
        ("after_seal_intent", "revoked", False),
        ("after_ciphertext_temp_unlink_fsync", "digest_mismatched", True),
    ],
)
def test_property_guarded_restart_never_promotes_intent_after_policy_invalidates(
    tmp_path: Path, crash_point: str, policy_failure: str, ciphertext_exists: bool,
) -> None:
    context = _property_context(tmp_path)

    def crash(point: str) -> None:
        if point == crash_point:
            raise RuntimeError("property-seal-interrupted")

    context["store"]._crash_hook = crash  # type: ignore[union-attr]
    with pytest.raises(RuntimeError, match="property-seal-interrupted"):
        _compose_property(context)
    material_root = tmp_path / "property-material"
    before = (material_root / "material.journal.jsonl").read_bytes()
    receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    envelope = material_root / f"{str(receipt['composition_digest'])[7:]}.envelope.json"
    assert envelope.exists() is ciphertext_exists

    valid = _property_policy_verification(context["evidence"])  # type: ignore[arg-type]
    invalid = (
        replace(valid, state="revoked")
        if policy_failure == "revoked"
        else replace(valid, policy_digest=_digest("invalidated-policy"))
    )
    restarted_store = _property_material_store(
        material_root,
        context["current"],  # type: ignore[arg-type]
        lifecycle_authority=context["ledger"].lifecycle_authority,  # type: ignore[union-attr]
    )
    restarted = _property_context(
        tmp_path,
        evidence=context["evidence"],  # type: ignore[arg-type]
        verifier=FakePropertyPolicyVerifier([invalid]),
        ledger=context["ledger"],  # type: ignore[arg-type]
        store=restarted_store,
        current=context["current"],  # type: ignore[arg-type]
    )
    expected_reason = (
        "property_policy_revoked"
        if policy_failure == "revoked"
        else "property_policy_verification_mismatch"
    )
    with pytest.raises(SpatialStateError, match=expected_reason):
        _compose_property(restarted)

    assert (material_root / "material.journal.jsonl").read_bytes() == before
    assert _property_journal_states(material_root) == ["seal_intent"]
    assert envelope.exists() is ciphertext_exists
    _assert_property_actions_zero(context)
    _assert_property_actions_zero(restarted)


def test_property_privacy_tombstone_on_restart_preempts_valid_ciphertext_intent(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path)

    def crash(point: str) -> None:
        if point == "after_ciphertext_temp_unlink_fsync":
            raise RuntimeError("property-valid-intent")

    context["store"]._crash_hook = crash  # type: ignore[union-attr]
    with pytest.raises(RuntimeError, match="property-valid-intent"):
        _compose_property(context)
    receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    context["ledger"].record_privacy_action(  # type: ignore[union-attr]
        scope_digest=receipt["composition_digest"],
        action="deleted",
        reason_digest=_digest("property-privacy-delete"),
        observed_at=NOW,
    )

    restarted_store = _property_material_store(
        tmp_path / "property-material",
        context["current"],  # type: ignore[arg-type]
        lifecycle_authority=context["ledger"].lifecycle_authority,  # type: ignore[union-attr]
    )
    invalid_policy = replace(
        _property_policy_verification(context["evidence"]),  # type: ignore[arg-type]
        state="revoked",
    )
    privacy_verifier = FakePropertyPolicyVerifier([invalid_policy])
    restarted = _property_context(
        tmp_path,
        evidence=context["evidence"],  # type: ignore[arg-type]
        verifier=privacy_verifier,
        ledger=context["ledger"],  # type: ignore[arg-type]
        store=restarted_store,
        current=context["current"],  # type: ignore[arg-type]
    )
    with pytest.raises(SpatialPrivacyError, match="property_privacy_tombstone_active"):
        _compose_property(restarted)

    assert _property_journal_states(tmp_path / "property-material") == [
        "seal_intent",
        "delete_tombstone",
        "deleted",
    ]
    envelope = tmp_path / "property-material" / f"{str(receipt['composition_digest'])[7:]}.envelope.json"
    assert not envelope.exists()
    assert privacy_verifier.calls == []
    _assert_property_actions_zero(context)
    _assert_property_actions_zero(restarted)


def test_property_privacy_writer_linearizes_before_compose_and_prevents_any_seal_intent(
    tmp_path: Path,
) -> None:
    evidence = _property_policy_evidence()
    valid = _property_policy_verification(evidence)
    seed = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=FakePropertyPolicyVerifier(
            [valid, replace(valid, state="missing")]
        ),
    )
    with pytest.raises(SpatialStateError, match="property_policy_missing"):
        _compose_property(seed)
    receipt = seed["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    scope = receipt["composition_digest"]
    recorded = threading.Event()
    release_privacy = threading.Event()

    def privacy_first() -> None:
        with seed["ledger"].composition_privacy_lifecycle_guard(scope):  # type: ignore[union-attr]
            seed["ledger"].record_privacy_action(  # type: ignore[union-attr]
                scope_digest=scope,
                action="deleted",
                reason_digest=_digest("privacy-first"),
                observed_at=NOW,
            )
            recorded.set()
            assert release_privacy.wait(timeout=5)

    retry = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=FakePropertyPolicyVerifier([valid]),
        ledger=seed["ledger"],  # type: ignore[arg-type]
        store=seed["store"],  # type: ignore[arg-type]
        current=seed["current"],  # type: ignore[arg-type]
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        privacy_future = executor.submit(privacy_first)
        assert recorded.wait(timeout=5)
        compose_future = executor.submit(_compose_property, retry)
        assert not compose_future.done()
        assert _property_journal_states(tmp_path / "property-material") == []
        release_privacy.set()
        privacy_future.result(timeout=5)
        with pytest.raises(SpatialPrivacyError, match="property_privacy_tombstone_active"):
            compose_future.result(timeout=5)

    assert _property_journal_states(tmp_path / "property-material") == [
        "delete_tombstone",
        "deleted",
    ]
    assert not (
        tmp_path / "property-material" / f"{str(scope)[7:]}.envelope.json"
    ).exists()
    _assert_property_actions_zero(seed)
    _assert_property_actions_zero(retry)


def test_property_compose_guard_serializes_privacy_then_strict_delete_without_deadlock(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path)
    lifecycle_entered = threading.Event()
    release_compose = threading.Event()
    privacy_started = threading.Event()
    privacy_done = threading.Event()
    scope_holder: list[str] = []

    def hold_after_intent(point: str) -> None:
        if point != "after_seal_intent":
            return
        receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
        assert receipt is not None
        scope_holder.append(receipt["composition_digest"])
        lifecycle_entered.set()
        assert release_compose.wait(timeout=5)

    context["store"]._crash_hook = hold_after_intent  # type: ignore[union-attr]

    def privacy_after_compose_guard() -> dict[str, object]:
        assert lifecycle_entered.wait(timeout=5)
        privacy_started.set()
        result = context["ledger"].record_privacy_action(  # type: ignore[union-attr]
            scope_digest=scope_holder[0],
            action="deleted",
            reason_digest=_digest("privacy-after-seal"),
            observed_at=NOW,
        )
        privacy_done.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        compose_future = executor.submit(_compose_property, context)
        assert lifecycle_entered.wait(timeout=5)
        privacy_future = executor.submit(privacy_after_compose_guard)
        assert privacy_started.wait(timeout=5)
        assert not privacy_done.wait(timeout=0.2)
        release_compose.set()
        compose_result = compose_future.result(timeout=5)
        privacy_receipt = privacy_future.result(timeout=5)

    assert compose_result["composition_digest"] == scope_holder[0]
    assert privacy_receipt["scope_digest"] == scope_holder[0]
    assert _property_journal_states(tmp_path / "property-material") == [
        "seal_intent",
        "sealed",
    ]
    with context["ledger"].composition_privacy_lifecycle_guard(  # type: ignore[union-attr]
        scope_holder[0]
    ) as lifecycle_guard:
        assert lifecycle_guard.privacy_status is not None
        deletion = context["store"].preemptive_tombstone(  # type: ignore[union-attr]
            scope_holder[0],
            compose_result["material_digest"],
            lifecycle_guard=lifecycle_guard,
        )
    assert deletion.derivative_coverage == "complete"
    assert _property_journal_states(tmp_path / "property-material") == [
        "seal_intent",
        "sealed",
        "delete_tombstone",
        "deleted",
    ]
    _assert_property_actions_zero(context)


@pytest.mark.parametrize("attack", ["tampered", "key_mismatch", "expired"])
def test_property_replay_rejects_untrusted_signed_receipt_before_store_action(
    tmp_path: Path, attack: str,
) -> None:
    ledger = PersistentReplayOverrideLedger(tmp_path / "tamper-ledger")
    context = _property_context(tmp_path, ledger=ledger)
    _compose_property(context)
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    journal_before = journal.read_bytes()
    receipt = ledger.find_composition_by_key("property-tour-r11-v1")
    assert receipt is not None
    replay_registry = context["registry"]
    if attack == "tampered":
        ledger.replay_override = deepcopy(receipt)
        ledger.replay_override["request_digest"] = _digest("tampered-request")
    elif attack == "key_mismatch":
        wrong_signer = _signer(seed=b"Z" * 32)
        replay_registry = Ed25519KeyRegistry([wrong_signer.key_record])
    else:
        body = deepcopy(receipt)
        body.pop("signature")
        body["expires_at"] = utc_iso(NOW + timedelta(minutes=5))
        ledger.replay_override = sign_envelope(
            body, context["signer"]  # type: ignore[arg-type]
        )
        context["current"][0] = NOW + timedelta(minutes=11)  # type: ignore[index]
    replay = _property_context(
        tmp_path,
        evidence=context["evidence"],  # type: ignore[arg-type]
        ledger=ledger,
        store=context["store"],  # type: ignore[arg-type]
        current=context["current"],  # type: ignore[arg-type]
        registry=replay_registry,  # type: ignore[arg-type]
    )

    with pytest.raises(SpatialStateError, match="property_composition_receipt_unverifiable"):
        _compose_property(replay)

    assert journal.read_bytes() == journal_before
    _assert_property_actions_zero(replay)


@pytest.mark.parametrize(
    "conflict",
    ["request", "source", "style", "assets", "target", "policy", "deadlines"],
)
def test_property_replay_rejects_every_conflicting_authority_input_without_store_mutation(
    tmp_path: Path, conflict: str,
) -> None:
    context = _property_context(tmp_path)
    _compose_property(context)
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    journal_before = journal.read_bytes()
    request = _property_request_payload()
    source = _property_source_payload()
    style = _property_style_snapshot()
    assets = _property_asset_bindings()
    deadlines: Mapping[str, object] | None = None
    replay = context
    if conflict == "request":
        request["callback"] = {"product_event_ref": "event:changed-callback"}
    elif conflict == "source":
        source["source_digest"] = "c" * 64
    elif conflict == "style":
        style["palette"] = ["cool-neutral"]
    elif conflict == "assets":
        assets[0]["sha256"] = _digest("changed-asset")
    elif conflict == "target":
        target = _property_execution_target()
        target["provider_route_digest"] = _digest("changed-route")
        replay = _property_context(
            tmp_path,
            evidence=context["evidence"],  # type: ignore[arg-type]
            ledger=context["ledger"],  # type: ignore[arg-type]
            store=context["store"],  # type: ignore[arg-type]
            current=context["current"],  # type: ignore[arg-type]
            target=target,
        )
    elif conflict == "policy":
        changed_evidence = _property_policy_evidence(
            verification_receipt_digest=_digest("changed-verification")
        )
        replay = _property_context(
            tmp_path,
            evidence=changed_evidence,
            verifier=FakePropertyPolicyVerifier(
                [_property_policy_verification(changed_evidence)]
            ),
            ledger=context["ledger"],  # type: ignore[arg-type]
            store=context["store"],  # type: ignore[arg-type]
            current=context["current"],  # type: ignore[arg-type]
        )
    else:
        deadlines = {"privacy": ["2026-07-20T00:00:00Z"]}

    with pytest.raises(SpatialIdempotencyConflict, match="property_composition_replay_conflict"):
        _compose_property(
            replay,
            request=request,
            source=source,
            style=style,
            assets=assets,
            deadlines=deadlines,
        )

    assert journal.read_bytes() == journal_before
    _assert_property_actions_zero(replay)


def test_property_composition_identity_binds_idempotency_key_to_distinct_ledger_paths(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path)
    first = _compose_property(context)
    second = _compose_property(
        context,
        request=_property_request_payload(
            key="property-tour-r11-v2",
            request_id="4b5f63bf-d590-456d-b693-226aec5d403f",
        ),
    )

    assert first["composition_digest"] != second["composition_digest"]
    assert first["material_identity"] != second["material_identity"]
    assert context["ledger"].integrity_summary()["composition_count"] == 2  # type: ignore[union-attr]
    composition_files = list((tmp_path / "property-ledger" / "compositions").iterdir())
    assert len(composition_files) == 2
    assert len({path.name for path in composition_files}) == 2
    for key, expected in (
        ("property-tour-r11-v1", first),
        ("property-tour-r11-v2", second),
    ):
        receipt = context["ledger"].find_composition_by_key(key)  # type: ignore[union-attr]
        assert receipt is not None
        assert receipt["composition_digest"] == expected["composition_digest"]
        verify_signed_envelope(
            receipt,
            context["registry"],  # type: ignore[arg-type]
            observed_at=NOW,
        )
    _assert_property_actions_zero(context)


@pytest.mark.parametrize(
    ("retention_case", "expected_expiry"),
    [
        ("source", "2026-08-10T09:30:00Z"),
        ("policy", "2026-07-20T00:00:00Z"),
        ("deadlines", "2026-07-15T00:00:00Z"),
    ],
)
def test_property_retention_uses_earliest_verified_deadline_and_never_resets_on_replay(
    tmp_path: Path, retention_case: str, expected_expiry: str,
) -> None:
    evidence = _property_policy_evidence()
    policy_expiry = (
        datetime(2026, 7, 20, tzinfo=UTC)
        if retention_case == "policy"
        else datetime(2027, 7, 11, tzinfo=UTC)
    )
    verification = _property_policy_verification(
        evidence, policy_expires_at=policy_expiry
    )
    current = [NOW]
    context = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=FakePropertyPolicyVerifier([verification]),
        current=current,
    )
    deadlines = None
    if retention_case == "deadlines":
        deadlines = {
            "rights": ["2026-07-25T00:00:00Z"],
            "consent": ["2026-07-18T00:00:00Z"],
            "takedown": ["2026-07-16T00:00:00Z"],
            "privacy": ["2026-07-15T00:00:00Z"],
        }
    first = _compose_property(context, deadlines=deadlines)
    journal_before = (
        tmp_path / "property-material" / "material.journal.jsonl"
    ).read_bytes()
    current[0] = NOW + timedelta(hours=1)
    replay = _compose_property(context, deadlines=deadlines)

    assert first["retention_anchor"] == "2026-07-11T09:30:00Z"
    assert first["retention_expires_at"] == expected_expiry
    assert replay["retention_expires_at"] == expected_expiry
    assert replay["idempotent_replay"] is True
    assert (
        tmp_path / "property-material" / "material.journal.jsonl"
    ).read_bytes() == journal_before
    _assert_property_actions_zero(context)


@pytest.mark.parametrize("invalid_input", ["style_extra", "style_timestamp", "asset_extra", "asset_path"])
def test_property_malformed_or_noncanonical_style_and_assets_fail_before_durable_effects(
    tmp_path: Path, invalid_input: str,
) -> None:
    context = _property_context(tmp_path)
    style = _property_style_snapshot()
    assets = _property_asset_bindings()
    if invalid_input == "style_extra":
        style["mutable_availability"] = True
    elif invalid_input == "style_timestamp":
        style["source_retrieved_at"] = "2026-07-11T11:00:00+02:00"
    elif invalid_input == "asset_extra":
        assets[0]["provider_url"] = "private"
    else:
        assets[0]["asset_ref"] = "../private/asset"

    with pytest.raises(SpatialStateError):
        _compose_property(context, style=style, assets=assets)

    assert context["ledger"].integrity_summary()["composition_count"] == 0  # type: ignore[union-attr]
    assert _property_journal_states(tmp_path / "property-material") == []
    _assert_property_actions_zero(context)


@pytest.mark.parametrize("mapping_attack", ["product", "purpose", "target_family", "target_profile"])
def test_property_r11_family_profile_mapping_is_exact_and_runsite_mappings_are_not_reused(
    tmp_path: Path, mapping_attack: str,
) -> None:
    request = _property_request_payload()
    target = _property_execution_target()
    if mapping_attack == "product":
        request["consumer"] = {
            "product": "chummer",
            "tenant_ref": "tenant:property-fixture",
            "subject_ref": "subject:property-fixture",
        }
    elif mapping_attack == "purpose":
        request["artifact"] = {
            "kind": "continuous_walkthrough",
            "purpose": "inspection",
            "locale": "en-AT",
        }
    elif mapping_attack == "target_family":
        target["artifact_family"] = "runsite_continuous_walkthrough"
    else:
        target["content_profile"] = "private_fictional_non_graphic_encounter"
    context = _property_context(tmp_path, target=target)

    with pytest.raises(SpatialStateError):
        _compose_property(context, request=request)

    assert context["ledger"].integrity_summary()["composition_count"] == 0  # type: ignore[union-attr]
    assert _property_journal_states(tmp_path / "property-material") == []
    _assert_property_actions_zero(context)


def test_property_privacy_branch_preserves_ledger_request_time_during_clock_rollback(
    tmp_path: Path,
) -> None:
    evidence = _property_policy_evidence()
    valid = _property_policy_verification(evidence)
    current = [NOW]
    policy_verifier = FakePropertyPolicyVerifier(
        [valid, replace(valid, state="missing")]
    )
    input_verifier = FakePropertyInputAuthorityVerifier()
    context = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=policy_verifier,
        input_verifier=input_verifier,
        current=current,
    )
    with pytest.raises(SpatialStateError, match="property_policy_missing"):
        _compose_property(context)
    receipt = context["ledger"].find_composition_by_key("property-tour-r11-v1")  # type: ignore[union-attr]
    assert receipt is not None
    requested_at = NOW - timedelta(hours=2)
    privacy = context["ledger"].record_privacy_action(  # type: ignore[union-attr]
        scope_digest=receipt["composition_digest"],
        action="deleted",
        reason_digest=_digest("early-property-privacy-request"),
        observed_at=requested_at,
    )
    current[0] = requested_at - timedelta(hours=1)

    with pytest.raises(SpatialPrivacyError, match="property_privacy_tombstone_active"):
        _compose_property(context)

    journal_path = tmp_path / "property-material" / "material.journal.jsonl"
    records = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert [record["state"] for record in records] == [
        "delete_tombstone",
        "deleted",
    ]
    assert records[0]["requested_at"] == privacy["recorded_at"]
    assert records[1]["requested_at"] == privacy["recorded_at"]
    assert datetime.fromisoformat(
        records[0]["observed_at"].replace("Z", "+00:00")
    ) >= requested_at
    journal_before = journal_path.read_bytes()

    current[0] = requested_at - timedelta(hours=4)
    with pytest.raises(SpatialPrivacyError, match="property_privacy_tombstone_active"):
        _compose_property(context)
    assert journal_path.read_bytes() == journal_before
    assert len(policy_verifier.calls) == 2
    assert len(input_verifier.calls) == 1
    _assert_property_actions_zero(context)
