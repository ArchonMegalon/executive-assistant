from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import queue
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

import app.services.governed_spatial_execution as execution_module
from app.services.governed_spatial_execution import (
    CANONICALIZATION,
    GovernedSpatialAssetBindingV1,
    GovernedSpatialExecutionMaterialEnvelopeV1,
    GovernedSpatialExecutionMaterialV1,
    GovernedSpatialExecutionRequestV1,
    GovernedSpatialExecutionResultV1,
    GovernedSpatialOperationReconciliationV1,
    GovernedSpatialRenderSpecV1,
    GovernedSpatialStyleSnapshotV1,
    PropertyDeletionEvidenceProjectionV1,
    SpatialExecutionMaterialStore,
    SpatialExecutionContractError,
    SpatialMaterialKeyRecord,
    SpatialMaterialKeyRegistry,
    SpatialMaterialStoreError,
    SpatialMaterialStoreSecurityError,
    canonical_material_bytes,
    envelope_aad_bytes,
    fixed_material_retention_expiry,
    key_fingerprint,
    material_digest,
    parse_execution_material,
    parse_execution_request,
    parse_property_response,
    reconciliation_digest,
    validate_execution_ref,
    validate_execution_gate_versions,
    validate_execution_request_material_binding,
    validate_reconciliation_freshness,
    validate_reconciliation_transition,
    validate_style_snapshot_time,
)
from app.services.governed_spatial_contract import (
    GovernedSpatialSourcePacketV1,
    bounded_jcs,
    normalize_compatibility_numbers,
)
from app.services.governed_spatial_state import DurableSpatialLedger, SpatialStateError


NOW = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


class credential_secret_material_ref_ABC:
    pass


def _artifact(*, purpose: str = "walkthrough") -> dict[str, object]:
    return {"kind": "continuous_walkthrough", "purpose": purpose, "locale": "en-AT"}


def _camera() -> dict[str, object]:
    return {
        "height_m": "1.6",
        "target_delivery_fps": 60,
        "minimum_effective_motion_fps": 30,
        "motion_profile": "slow_inspection",
        "cuts_allowed": False,
        "teleports_allowed": False,
        "collision_avoidance": True,
        "rotation_smoothing": True,
    }


def _output() -> dict[str, object]:
    return {
        "desktop": True,
        "mobile": True,
        "video_codec": "h264",
        "interactive_package": False,
        "poster_frame": True,
        "contact_sheet": True,
    }


def _content(*, encounter: bool = False) -> dict[str, object]:
    return {
        "rating": "teen_fictional_combat" if encounter else "general_spatial_orientation",
        "graphic_injury": False,
        "real_person_likeness": False,
        "minor_combatants": False,
    }


def _overlay() -> dict[str, object]:
    return {
        "overlay_id": "overlay-1",
        "kind": "fictional_combat_choreography",
        "gameplay_truth_ref": "truth:encounter:v1",
        "location_anchor": "anchor:living:v1",
        "start_time_s": "1",
        "end_time_s": "2",
        "participants": [
            {"actor_ref": "actor:one", "role": "runner", "minor": False, "real_person": False}
        ],
        "beats": [{"at_s": "1.5", "action": "move", "actor_ref": "actor:one"}],
        "provided_outcome": None,
        "provided_outcome_ref": "outcome:fixture:v1",
        "camera_policy": "continuous_witness_path",
        "graphic_injury": False,
    }


def _render_spec(
    *, product: str = "propertyquarry", purpose: str = "walkthrough", revisit: bool = True
) -> dict[str, object]:
    route = ["living", "hall", "bath", "hall"] if revisit else ["living", "hall", "bath"]
    return {
        "contract_name": "ea.governed_spatial_render_spec.v1",
        "contract_version": "1.0.0",
        "product": product,
        "artifact": _artifact(purpose=purpose),
        "normalized_floorplan_ref": "floorplan:fixture:v1",
        "room_graph_ref": "room-graph:fixture:v1",
        "walkable_mesh_ref": "mesh:fixture:v1",
        "portal_graph_ref": "portal-graph:fixture:v1",
        "scale_m_per_unit": "1",
        "orientation_degrees": "0",
        "rooms": [
            {
                "room_id": room_id,
                "room_type": "any",
                "walkable": True,
                "boundary_ref": f"boundary:{room_id}",
                "ceiling_height_m": "2.5",
                "geometry_anchor_ref": f"geometry:{room_id}",
                "texture_anchor_refs": [f"texture:{room_id}"],
            }
            for room_id in ("living", "hall", "bath")
        ],
        "portals": [
            {"portal_id": "p1", "from_room_id": "living", "to_room_id": "hall", "walkable": True},
            {"portal_id": "p2", "from_room_id": "hall", "to_room_id": "bath", "walkable": True},
        ],
        "required_room_ids": ["living", "hall", "bath"],
        "route_room_ids": route,
        "allow_revisit": revisit,
        "camera": _camera(),
        "output": _output(),
        "content_policy": _content(encounter=purpose == "encounter_preview"),
        "scene_overlays": [_overlay()] if purpose == "encounter_preview" else [],
    }


def _style(*, product: str = "propertyquarry", brand: bool = False) -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_style_snapshot.v1",
        "contract_version": "1.0.0",
        "style_pack_id": "style-pack-v1",
        "registry_contract": "style-registry-v1",
        "registry_version": "1.0.0",
        "registry_digest": DIGEST,
        "consumer_products": [product],
        "status": "accepted",
        "room_types": ["any"],
        "room_rules": {"any": ["preserve-topology"]},
        "composition_rules": ["single-scene"],
        "palette": ["neutral"],
        "materials": ["verified"],
        "catalog_families": ["catalog"] if brand else [],
        "furniture_catalog_refs": ["catalog:item-1"] if brand else [],
        "negative_constraints": ["no-layout-copy"],
        "asset_license_policy": "verified_reuse_only",
        "brand_claim_policy": "truthful_no_affiliation_claim",
        "adapter_profile_ref": "adapter-profile:deterministic:v1",
        "external_asset_refs": [],
        "provenance_status": "verified",
        "provenance_refs": ["provenance:fixture:v1"],
        "source_retrieved_at": "2026-07-12T09:00:00Z",
        "visual_direction_refs": [],
        "visual_regression_refs": [],
        "acceptance_contact_sheet_refs": [],
    }


def _asset(
    *, ref: str = "geometry:asset-1", purpose: str = "source_geometry",
    media_type: str | None = None, license_ref: str = "license:fixture:v1",
) -> dict[str, object]:
    default_media = {
        "source_geometry": "model/gltf-binary",
        "source_texture": "image/png",
        "style_asset": "model/gltf-binary",
        "brand_reuse_proof": "application/json",
        "visual_direction": "image/png",
        "verification_reference": "video/mp4",
    }[purpose]
    return {
        "asset_ref": ref,
        "sha256": DIGEST,
        "size_bytes": 10,
        "media_type": media_type or default_media,
        "purpose": purpose,
        "license_provenance_ref": license_ref,
        "source_owner_ref": "owner:fixture:v1",
    }


def _source_assets() -> list[dict[str, object]]:
    geometry_refs = [
        "floorplan:fixture:v1", "room-graph:fixture:v1", "mesh:fixture:v1",
        "portal-graph:fixture:v1",
        *(f"boundary:{room_id}" for room_id in ("living", "hall", "bath")),
        *(f"geometry:{room_id}" for room_id in ("living", "hall", "bath")),
    ]
    return [
        *[_asset(ref=ref, purpose="source_geometry", media_type="application/json") for ref in geometry_refs],
        *[_asset(ref=f"texture:{room_id}", purpose="source_texture") for room_id in ("living", "hall", "bath")],
    ]


def _execution_request(
    *, product: str = "propertyquarry", purpose: str = "walkthrough", brand: bool = False
) -> dict[str, object]:
    family = {
        ("propertyquarry", "walkthrough"): "propertyquarry_continuous_walkthrough",
        ("chummer", "walkthrough"): "runsite_continuous_walkthrough",
        ("chummer", "encounter_preview"): "runsite_private_encounter_preview",
    }[(product, purpose)]
    profile = (
        "private_fictional_non_graphic_encounter"
        if purpose == "encounter_preview"
        else "spatial_orientation_no_encounter_fields"
    )
    assets = _source_assets()
    if brand:
        assets.extend(
            [
                _asset(ref="catalog:item-1", purpose="style_asset", license_ref="proof:item-1"),
                _asset(ref="proof:item-1", purpose="brand_reuse_proof"),
            ]
        )
    return {
        "contract_name": "ea.governed_spatial_execution_request.v1",
        "contract_version": "1.0.0",
        "build_request_digest": DIGEST,
        "composition_digest": DIGEST,
        "request_digest": DIGEST,
        "source_packet_digest": DIGEST,
        "style_snapshot_digest": DIGEST,
        "output_contract_digest": DIGEST,
        "material_digest": DIGEST,
        "execution_target_digest": DIGEST,
        "attempt_number": 1,
        "mutation_token_digest": DIGEST,
        "operation_intent_digest": DIGEST,
        "artifact_family": family,
        "content_profile": profile,
        "environment": "test",
        "provider_route_digest": DIGEST,
        "gate_versions": {
            "compose": "1",
            "quota": "1",
            **({"property_policy": "1"} if product == "propertyquarry" else {}),
        },
        "render_spec": _render_spec(product=product, purpose=purpose),
        "style_snapshot": _style(product=product, brand=brand),
        "asset_bindings": assets,
        "output_allocation_ref": "output-allocation:fixture:v1",
    }


def _normalized_request() -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_render_request.v1",
        "idempotency_key": "consumer-tour-demo-v1",
        "consumer": {
            "product": "propertyquarry",
            "tenant_ref": "tenant:demo",
            "subject_ref": "subject:demo-flat",
        },
        "artifact": _artifact(),
        "source_packet_ref": "source-packet:demo-flat-v1",
        "truth_refs": ["truth:demo-flat"],
        "evidence_refs": ["evidence:room-graph-v1"],
        "spatial_plan": {
            "room_graph_ref": "room-graph:fixture:v1",
            "walkable_mesh_ref": "mesh:fixture:v1",
            "portal_graph_ref": "portal-graph:fixture:v1",
            "required_room_ids": ["living", "hall", "bath"],
            "route_room_ids": ["living", "hall", "bath", "hall"],
            "portal_edges": [
                {"from_room_id": "living", "to_room_id": "hall"},
                {"from_room_id": "hall", "to_room_id": "bath"},
            ],
            "route_policy": "continuous_all_walkable_rooms",
            "allow_revisit": True,
            "start_anchor": None,
            "end_anchor": None,
        },
        "style": {
            "style_pack_id": "style-pack-v1",
            "room_overrides": {},
            "asset_license_policy": "verified_reuse_only",
            "brand_claim_policy": "truthful_no_affiliation_claim",
            "real_product_claim": False,
            "asset_reuse_proof_refs": [],
        },
        "scene_overlays": [],
        "camera": {
            "height_m": "1.6",
            "target_delivery_fps": 60,
            "minimum_effective_motion_fps": 30,
            "motion_profile": "slow_inspection",
            "cuts_allowed": False,
            "teleports_allowed": False,
            "collision_avoidance": True,
            "rotation_smoothing": True,
        },
        "output": _output(),
        "content_policy": {
            "rating": "general_spatial_orientation",
            "graphic_injury": False,
            "real_person_likeness": False,
            "minor_combatants": False,
        },
        "quota": {"consume_quota": False, "maximum_provider_attempts": 0},
        "callback": {"product_event_ref": "event:render-complete"},
    }


def _normalized_source_packet() -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_source_packet.v1",
        "source_packet_ref": "source-packet:demo-flat-v1",
        "source_digest": "b" * 64,
        "source_retrieved_at": "2026-07-12T08:00:00Z",
        "source_packet_created_at": "2026-07-12T08:30:00Z",
        "normalized_floorplan_ref": "floorplan:fixture:v1",
        "room_graph_ref": "room-graph:fixture:v1",
        "walkable_mesh_ref": "mesh:fixture:v1",
        "portal_graph_ref": "portal-graph:fixture:v1",
        "scale_m_per_unit": 1,
        "orientation_degrees": 0,
        "license_provenance_refs": ["license:first-party:v1"],
        "source_media_assignments": [],
        "inaccessible_rooms": [],
        "route_exclusions": [],
        "rooms": [
            {
                "room_id": room_id,
                "room_type": "any",
                "walkable": True,
                "boundary_ref": f"boundary:{room_id}",
                "ceiling_height_m": "2.5",
                "geometry_anchor_ref": f"geometry:{room_id}",
                "texture_anchor_refs": [f"texture:{room_id}"],
                "exterior_classification": None,
                "accessible": None,
            }
            for room_id in ("living", "hall", "bath")
        ],
        "portals": [
            {"portal_id": "p1", "from_room_id": "living", "to_room_id": "hall", "walkable": True},
            {"portal_id": "p2", "from_room_id": "hall", "to_room_id": "bath", "walkable": True},
        ],
        "route_room_ids": ["living", "hall", "bath", "hall"],
        "existing_artifacts": {},
    }


def _source_packet_digest(packet: dict[str, object]) -> str:
    parsed = GovernedSpatialSourcePacketV1.model_validate(packet)
    normalized = normalize_compatibility_numbers(parsed.model_dump(mode="json"))
    return "sha256:" + hashlib.sha256(bounded_jcs(normalized)).hexdigest()


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(bounded_jcs(value)).hexdigest()


def _refresh_material_lineage(payload: dict[str, object]) -> None:
    payload["request_digest"] = _digest(payload["normalized_request"])
    payload["source_packet_digest"] = _source_packet_digest(payload["normalized_source_packet"])  # type: ignore[arg-type]
    payload["style_snapshot_digest"] = _digest(payload["style_snapshot"])
    payload["output_contract_digest"] = _digest(payload["normalized_request"]["output"])  # type: ignore[index]


def _material() -> dict[str, object]:
    request = _execution_request()
    normalized_request = _normalized_request()
    source_packet = _normalized_source_packet()
    style = request["style_snapshot"]
    return {
        "contract_name": "ea.governed_spatial_execution_material.v1",
        "contract_version": "1.0.0",
        "composition_digest": DIGEST,
        "request_digest": _digest(normalized_request),
        "source_packet_digest": _source_packet_digest(source_packet),
        "style_snapshot_digest": _digest(style),
        "output_contract_digest": _digest(normalized_request["output"]),
        "execution_target_digest": DIGEST,
        "normalized_request": normalized_request,
        "normalized_source_packet": source_packet,
        "style_snapshot": style,
        "asset_bindings": request["asset_bindings"],
        "source_packet_created_at": "2026-07-12T08:30:00Z",
        "compose_created_at": "2026-07-12T09:00:00Z",
        "retention_expires_at": "2026-07-20T09:00:00Z",
    }


def _bound_execution_request() -> dict[str, object]:
    material_payload = _material()
    material = GovernedSpatialExecutionMaterialV1.model_validate(material_payload)
    request = _execution_request()
    for field in (
        "composition_digest", "request_digest", "source_packet_digest", "style_snapshot_digest",
        "output_contract_digest", "execution_target_digest",
    ):
        request[field] = material_payload[field]
    request["material_digest"] = material_digest(material)
    return request


def _envelope() -> dict[str, object]:
    payload = {
        "contract_name": "ea.governed_spatial_execution_material_envelope.v1",
        "contract_version": "1.0.0",
        "environment": "test",
        "material_identity": "material:fixture:v1",
        "material_digest": DIGEST,
        "composition_digest": DIGEST,
        "request_digest": DIGEST,
        "source_packet_digest": DIGEST,
        "style_snapshot_digest": DIGEST,
        "output_contract_digest": DIGEST,
        "execution_target_digest": DIGEST,
        "created_at": "2026-07-12T09:00:00Z",
        "retention_expires_at": "2026-07-20T09:00:00Z",
        "key_ref": "key:fixture:v1",
        "key_epoch": 1,
        "key_fingerprint": DIGEST,
        "algorithm": "aes-256-gcm",
        "nonce_encoding": "base64url_no_padding",
        "nonce": base64.urlsafe_b64encode(b"n" * 12).decode().rstrip("="),
        "ciphertext_encoding": "base64url_no_padding",
        "ciphertext": base64.urlsafe_b64encode(b"ciphertext" + b"t" * 16).decode().rstrip("="),
        "canonicalization": CANONICALIZATION,
        "aad_digest": DIGEST,
    }
    aad = dict(payload)
    aad.pop("ciphertext")
    aad.pop("aad_digest")
    payload["aad_digest"] = "sha256:" + hashlib.sha256(
        __import__("app.services.governed_spatial_contract", fromlist=["bounded_jcs"]).bounded_jcs(aad)
    ).hexdigest()
    return payload


def _signature() -> dict[str, object]:
    return {
        "algorithm": "ed25519",
        "encoding": "base64url_no_padding",
        "signature_value": "A" * 86,
        "key_ref": "key:adapter:v1",
        "key_fingerprint": DIGEST,
        "key_epoch": 1,
        "canonicalization": "rfc8785_jcs",
        "signed_payload_scope": "entire_receipt_excluding_signature_value_and_signed_payload_digest",
        "signed_payload_digest": DIGEST,
    }


def _reconciliation(
    *, sequence: int = 1, state: str = "in_progress", outcome: str | None = None,
    prior: str | None = None
) -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_operation_reconciliation.v1",
        "contract_version": "1.0.0",
        "adapter_identity_digest": DIGEST,
        "environment": "test",
        "operation_id": "operation:fixture:v1",
        "operation": "execute",
        "build_request_digest": DIGEST,
        "attempt_number": 1,
        "observed_at": "2026-07-12T09:59:00Z",
        "issued_at": "2026-07-12T10:00:00Z",
        "expires_at": "2026-07-12T10:05:00Z",
        "adapter_sequence": sequence,
        "state": state,
        "outcome_digest": outcome,
        "prior_reconciliation_digest": prior,
        "signature": _signature(),
    }


@pytest.mark.parametrize(
    "value",
    ["../asset", "folder/asset", "folder\\asset", "https://host/x", "file:secret", "a b", "asset;rm", "provider:task:1", "x\nref"],
)
def test_execution_refs_reject_paths_uris_shell_whitespace_and_provider_private_forms(value: str) -> None:
    with pytest.raises(ValueError):
        validate_execution_ref(value)


def test_execution_ref_uses_exact_512_character_domain() -> None:
    assert validate_execution_ref("r" * 512) == "r" * 512
    with pytest.raises(ValueError, match="execution_ref_shape_invalid"):
        validate_execution_ref("r" * 513)


def test_asset_binding_is_exact_strict_and_bounded() -> None:
    assert GovernedSpatialAssetBindingV1.model_validate(_asset()).size_bytes == 10
    for field, value in (("size_bytes", True), ("size_bytes", 9_007_199_254_740_992), ("sha256", "a" * 64)):
        payload = _asset()
        payload[field] = value
        with pytest.raises(ValidationError):
            GovernedSpatialAssetBindingV1.model_validate(payload)
    payload = _asset()
    payload["unknown"] = "leak"
    with pytest.raises(ValidationError):
        GovernedSpatialAssetBindingV1.model_validate(payload)


@pytest.mark.parametrize(
    "media_type",
    ["application/x-shellscript", "application/javascript", "application/zip", "text/html"],
)
def test_asset_binding_rejects_executable_script_and_archive_media(media_type: str) -> None:
    payload = _asset()
    payload["media_type"] = media_type
    with pytest.raises(ValidationError, match="media_type_not_allowlisted"):
        GovernedSpatialAssetBindingV1.model_validate(payload)


@pytest.mark.parametrize(
    ("purpose", "media_type"),
    [
        ("source_geometry", "application/pdf"),
        ("source_geometry", "video/mp4"),
        ("source_texture", "text/plain"),
        ("source_texture", "model/gltf-binary"),
        ("style_asset", "application/pdf"),
        ("brand_reuse_proof", "model/gltf-binary"),
        ("brand_reuse_proof", "video/mp4"),
        ("visual_direction", "model/obj"),
        ("visual_direction", "video/mp4"),
        ("verification_reference", "model/gltf+json"),
        ("source_geometry", "application/pdf"),
        ("source_texture", "application/pdf"),
        ("style_asset", "application/pdf"),
        ("brand_reuse_proof", "application/pdf"),
        ("visual_direction", "application/pdf"),
        ("verification_reference", "application/pdf"),
    ],
)
def test_asset_media_type_is_bound_to_exact_purpose(purpose: str, media_type: str) -> None:
    with pytest.raises(ValidationError, match="media_type_not_allowlisted_for_purpose"):
        GovernedSpatialAssetBindingV1.model_validate(
            _asset(purpose=purpose, media_type=media_type)
        )


def test_style_snapshot_rejects_unknown_nested_rules_duplicates_and_future_time() -> None:
    snapshot = GovernedSpatialStyleSnapshotV1.model_validate(_style())
    assert snapshot.status == "accepted"
    validate_style_snapshot_time(snapshot, now=NOW)
    future = _style()
    future["source_retrieved_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(SpatialExecutionContractError, match="style_source_timestamp_in_future"):
        validate_style_snapshot_time(GovernedSpatialStyleSnapshotV1.model_validate(future), now=NOW)
    for mutate in (
        lambda value: value.update({"unknown": 1}),
        lambda value: value.update({"room_rules": {"any": ["same", "same"]}}),
        lambda value: value.update({"asset_license_policy": "generated_ok"}),
    ):
        payload = _style()
        mutate(payload)
        with pytest.raises(ValidationError):
            GovernedSpatialStyleSnapshotV1.model_validate(payload)


def test_room_rule_lists_accept_1000_unique_tokens_and_reject_1001() -> None:
    accepted = _style()
    accepted["room_rules"] = {"any": [f"rule-{index}" for index in range(1000)]}
    assert len(GovernedSpatialStyleSnapshotV1.model_validate(accepted).room_rules["any"]) == 1000

    rejected = _style()
    rejected["room_rules"] = {"any": [f"rule-{index}" for index in range(1001)]}
    with pytest.raises(ValidationError, match="room_rule_list_cardinality_invalid"):
        GovernedSpatialStyleSnapshotV1.model_validate(rejected)


def test_render_spec_preserves_revisit_route_and_rejects_geometry_route_attacks() -> None:
    parsed = GovernedSpatialRenderSpecV1.model_validate(_render_spec())
    assert parsed.route_room_ids == ["living", "hall", "bath", "hall"]
    assert parsed.allow_revisit is True
    for field, value in (
        ("allow_revisit", False),
        ("route_room_ids", ["living", "bath", "hall"]),
        ("scale_m_per_unit", 1.0),
        ("allow_revisit", 1),
    ):
        payload = _render_spec()
        payload[field] = value
        with pytest.raises(ValidationError):
            GovernedSpatialRenderSpecV1.model_validate(payload)


def test_render_spec_preserves_parallel_portals_but_rejects_duplicate_ids_and_missing_route_edges() -> None:
    parallel = _render_spec()
    parallel["portals"].append(  # type: ignore[union-attr]
        {"portal_id": "p3", "from_room_id": "hall", "to_room_id": "living", "walkable": True}
    )
    parsed = GovernedSpatialRenderSpecV1.model_validate(parallel)
    assert [portal.portal_id for portal in parsed.portals] == ["p1", "p2", "p3"]

    duplicate_id = deepcopy(parallel)
    duplicate_id["portals"][2]["portal_id"] = "p1"  # type: ignore[index]
    with pytest.raises(ValidationError, match="render_portal_ids_must_be_unique"):
        GovernedSpatialRenderSpecV1.model_validate(duplicate_id)

    missing_route_edge = deepcopy(parallel)
    missing_route_edge["route_room_ids"] = ["living", "bath", "hall"]
    missing_route_edge["allow_revisit"] = False
    with pytest.raises(ValidationError, match="route_transition_has_no_portal"):
        GovernedSpatialRenderSpecV1.model_validate(missing_route_edge)


@pytest.mark.parametrize(
    "value",
    ["1.0", "0.0", "00", "01", "1.", "-0", "-0.1", "1.0000000000000000000", "1234567890123456789012345"],
)
def test_decimal_strings_reject_noncanonical_or_unbounded_spellings(value: str) -> None:
    payload = _render_spec()
    payload["scale_m_per_unit"] = value
    with pytest.raises(ValidationError):
        GovernedSpatialRenderSpecV1.model_validate(payload)


@pytest.mark.parametrize("value", ["-0", "-0.0", "-90.0", "-90.10", "-0.1", "1.0000000000000000000"])
def test_orientation_rejects_noncanonical_signed_decimal_spellings(value: str) -> None:
    payload = _render_spec()
    payload["orientation_degrees"] = value
    with pytest.raises(ValidationError):
        GovernedSpatialRenderSpecV1.model_validate(payload)


def test_negative_orientation_is_preserved_from_material_to_render_spec() -> None:
    payload = _material()
    source = payload["normalized_source_packet"]
    source["orientation_degrees"] = -90  # type: ignore[index]
    payload["source_packet_digest"] = _source_packet_digest(source)  # type: ignore[arg-type]
    material = GovernedSpatialExecutionMaterialV1.model_validate(payload)
    request_payload = _bound_execution_request()
    request_payload["source_packet_digest"] = material.source_packet_digest
    request_payload["material_digest"] = material_digest(material)
    request_payload["render_spec"]["orientation_degrees"] = "-90"  # type: ignore[index]
    validate_execution_request_material_binding(
        GovernedSpatialExecutionRequestV1.model_validate(request_payload), material
    )


def test_decimal_comparisons_remain_exact_beyond_binary_float_precision() -> None:
    payload = _render_spec(product="chummer", purpose="encounter_preview")
    overlay = payload["scene_overlays"][0]  # type: ignore[index]
    overlay["start_time_s"] = "1.0000000000000001"  # type: ignore[index]
    overlay["end_time_s"] = "1.0000000000000002"  # type: ignore[index]
    overlay["beats"][0]["at_s"] = "1.0000000000000003"  # type: ignore[index]
    with pytest.raises(ValidationError, match="beat_outside_overlay_window"):
        GovernedSpatialRenderSpecV1.model_validate(payload)

    payload = _render_spec()
    payload["camera"]["height_m"] = "2.200000000000000001"  # type: ignore[index]
    with pytest.raises(ValidationError, match="plausible_camera_height_required"):
        GovernedSpatialRenderSpecV1.model_validate(payload)


def test_property_render_spec_rejects_encounter_overlay() -> None:
    payload = _render_spec(product="propertyquarry")
    payload["scene_overlays"] = [_overlay()]
    with pytest.raises(ValidationError, match="propertyquarry_scene_overlays_forbidden"):
        GovernedSpatialRenderSpecV1.model_validate(payload)


@pytest.mark.parametrize(
    ("product", "purpose"),
    [("propertyquarry", "walkthrough"), ("chummer", "walkthrough"), ("chummer", "encounter_preview")],
)
def test_execution_request_accepts_only_exact_product_family_profile_overlay_bindings(
    product: str, purpose: str
) -> None:
    GovernedSpatialExecutionRequestV1.model_validate(_execution_request(product=product, purpose=purpose))


def test_execution_request_rejects_property_as_runsite_and_style_product_mismatch() -> None:
    payload = _execution_request()
    payload["artifact_family"] = "runsite_continuous_walkthrough"
    with pytest.raises(ValidationError, match="product_family_profile_purpose_mismatch"):
        GovernedSpatialExecutionRequestV1.model_validate(payload)
    payload = _execution_request()
    payload["style_snapshot"] = _style(product="chummer")
    with pytest.raises(ValidationError, match="style_consumer_product_mismatch"):
        GovernedSpatialExecutionRequestV1.model_validate(payload)


def test_property_policy_gate_is_required_for_property_and_forbidden_for_chummer() -> None:
    payload = _execution_request()
    payload["gate_versions"].pop("property_policy")
    with pytest.raises(ValidationError, match="property_policy_gate_family_presence_invalid"):
        GovernedSpatialExecutionRequestV1.model_validate(payload)
    payload = _execution_request(product="chummer")
    payload["gate_versions"]["property_policy"] = "1"
    with pytest.raises(ValidationError, match="property_policy_gate_family_presence_invalid"):
        GovernedSpatialExecutionRequestV1.model_validate(payload)


def test_gate_versions_accept_schema_valid_non_fixed_values_and_bind_exact_verified_projection() -> None:
    payload = _execution_request()
    payload["gate_versions"] = {"compose": "2026.07-r3", "quota": "beta-7", "property_policy": "rev-42"}
    request = GovernedSpatialExecutionRequestV1.model_validate(payload)
    verified = {"artifact_family": request.artifact_family, "gate_versions": dict(request.gate_versions)}
    validate_execution_gate_versions(request, verified)
    for mutate in (
        lambda gates: gates.pop("compose"),
        lambda gates: gates.update({"unknown": "current"}),
        lambda gates: gates.update({"quota": "substituted"}),
    ):
        substituted = deepcopy(verified)
        mutate(substituted["gate_versions"])
        with pytest.raises(SpatialExecutionContractError, match="gate_versions_verified_projection_mismatch"):
            validate_execution_gate_versions(request, substituted)
    with pytest.raises(SpatialExecutionContractError, match="verified_gate_projection_invalid"):
        validate_execution_gate_versions(request, {"artifact_family": "runsite_continuous_walkthrough", "gate_versions": request.gate_versions})


def test_real_catalog_claim_requires_matching_brand_proof_binding() -> None:
    GovernedSpatialExecutionRequestV1.model_validate(_execution_request(brand=True))
    payload = _execution_request(brand=True)
    payload["asset_bindings"] = payload["asset_bindings"][:-1]
    with pytest.raises(ValidationError, match="catalog_brand_reuse_proof_binding_required"):
        GovernedSpatialExecutionRequestV1.model_validate(payload)


def test_catalog_claim_rejects_missing_product_family_only_and_self_proof() -> None:
    family_only = _style()
    family_only["catalog_families"] = ["retailer-current"]
    with pytest.raises(ValidationError, match="catalog_families_and_product_refs_must_be_jointly_present"):
        GovernedSpatialStyleSnapshotV1.model_validate(family_only)
    no_family = _style()
    no_family["furniture_catalog_refs"] = ["catalog:item-1"]
    with pytest.raises(ValidationError, match="catalog_families_and_product_refs_must_be_jointly_present"):
        GovernedSpatialStyleSnapshotV1.model_validate(no_family)
    self_proof = _execution_request(brand=True)
    catalog = next(
        binding for binding in self_proof["asset_bindings"] if binding["asset_ref"] == "catalog:item-1"
    )
    catalog["license_provenance_ref"] = "catalog:item-1"
    with pytest.raises(ValidationError, match="catalog_asset_self_proof_forbidden"):
        GovernedSpatialExecutionRequestV1.model_validate(self_proof)


def test_duplicate_assets_are_rejected() -> None:
    payload = _execution_request()
    payload["asset_bindings"] = [deepcopy(payload["asset_bindings"][0]), deepcopy(payload["asset_bindings"][0])]
    with pytest.raises(ValidationError, match="asset_refs_must_be_unique"):
        GovernedSpatialExecutionRequestV1.model_validate(payload)


def test_execution_material_is_no_float_canonical_and_has_external_digest() -> None:
    material = GovernedSpatialExecutionMaterialV1.model_validate(_material())
    canonical = canonical_material_bytes(material)
    assert b"material_digest" not in canonical
    assert material_digest(material).startswith("sha256:")
    assert canonical == canonical_material_bytes(json.loads(canonical))
    payload = _material()
    payload["normalized_request"]["provider_url"] = "https://secret.invalid/task/1"
    with pytest.raises(ValidationError):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda payload: payload["normalized_request"].__setitem__(  # type: ignore[union-attr]
                "source_packet_ref", "source-packet:different:v1"
            ),
            "request_source_packet_ref_mismatch",
        ),
        (
            lambda payload: payload["normalized_request"]["spatial_plan"].__setitem__(  # type: ignore[index]
                "room_graph_ref", "room-graph:different:v1"
            ),
            "request_source_room_graph_ref_mismatch",
        ),
        (
            lambda payload: payload["normalized_source_packet"].__setitem__(  # type: ignore[union-attr]
                "route_room_ids", ["bath", "hall", "living", "hall"]
            ),
            "request_route_source_mismatch",
        ),
        (
            lambda payload: payload["normalized_request"]["spatial_plan"].__setitem__(  # type: ignore[index]
                "portal_graph_ref", "portal-graph:different:v1"
            ),
            "request_source_portal_graph_ref_mismatch",
        ),
    ],
)
def test_material_rejects_valid_but_mixed_source_identity_route_and_graphs(
    mutation: object, reason: str
) -> None:
    payload = _material()
    mutation(payload)
    _refresh_material_lineage(payload)
    with pytest.raises(ValidationError, match=reason):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


def test_material_accepts_reversed_portal_edge_spelling_as_same_undirected_truth() -> None:
    payload = _material()
    edges = payload["normalized_request"]["spatial_plan"]["portal_edges"]  # type: ignore[index]
    for edge in edges:
        edge["from_room_id"], edge["to_room_id"] = edge["to_room_id"], edge["from_room_id"]
    _refresh_material_lineage(payload)
    GovernedSpatialExecutionMaterialV1.model_validate(payload)


def test_material_and_request_preserve_two_distinct_parallel_portals() -> None:
    payload = _material()
    parallel = {"portal_id": "p3", "from_room_id": "hall", "to_room_id": "living", "walkable": True}
    payload["normalized_source_packet"]["portals"].append(parallel)  # type: ignore[index]
    _refresh_material_lineage(payload)
    material = GovernedSpatialExecutionMaterialV1.model_validate(payload)

    request_payload = _execution_request()
    for field in (
        "composition_digest", "request_digest", "source_packet_digest", "style_snapshot_digest",
        "output_contract_digest", "execution_target_digest",
    ):
        request_payload[field] = getattr(material, field)
    request_payload["material_digest"] = material_digest(material)
    request_payload["render_spec"]["portals"].append(parallel)  # type: ignore[index]
    request = GovernedSpatialExecutionRequestV1.model_validate(request_payload)

    validate_execution_request_material_binding(request, material)
    assert [portal.portal_id for portal in request.render_spec.portals] == ["p1", "p2", "p3"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda payload: payload["normalized_request"]["style"].__setitem__(  # type: ignore[index]
                "style_pack_id", "style-pack-different"
            ),
            "request_style_style_pack_id_mismatch",
        ),
        (
            lambda payload: payload["normalized_request"]["style"].__setitem__(  # type: ignore[index]
                "real_product_claim", True
            ),
            "request_real_product_claim_mismatch",
        ),
    ],
)
def test_material_rejects_style_selection_and_real_product_claim_mixtures(
    mutation: object, reason: str
) -> None:
    payload = _material()
    mutation(payload)
    _refresh_material_lineage(payload)
    with pytest.raises(ValidationError, match=reason):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


def test_snapshot_cannot_introduce_unrequested_real_products() -> None:
    payload = _material()
    payload["style_snapshot"] = _style(brand=True)
    payload["asset_bindings"].extend(  # type: ignore[union-attr]
        [
            _asset(ref="catalog:item-1", purpose="style_asset", license_ref="proof:item-1"),
            _asset(ref="proof:item-1", purpose="brand_reuse_proof"),
        ]
    )
    _refresh_material_lineage(payload)
    with pytest.raises(ValidationError, match="request_real_product_claim_mismatch"):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


def test_material_accepts_exact_real_product_and_distinct_proof_binding() -> None:
    payload = _material()
    payload["style_snapshot"] = _style(brand=True)
    request_style = payload["normalized_request"]["style"]  # type: ignore[index]
    request_style["real_product_claim"] = True
    request_style["asset_reuse_proof_refs"] = ["proof:item-1"]
    payload["asset_bindings"].extend(  # type: ignore[union-attr]
        [
            _asset(ref="catalog:item-1", purpose="style_asset", license_ref="proof:item-1"),
            _asset(ref="proof:item-1", purpose="brand_reuse_proof"),
        ]
    )
    _refresh_material_lineage(payload)
    GovernedSpatialExecutionMaterialV1.model_validate(payload)


@pytest.mark.parametrize(
    "missing_ref",
    [
        "floorplan:fixture:v1", "room-graph:fixture:v1", "mesh:fixture:v1",
        "portal-graph:fixture:v1", "boundary:living", "geometry:hall", "texture:bath",
    ],
)
def test_material_requires_complete_source_asset_inventory(missing_ref: str) -> None:
    payload = _material()
    payload["asset_bindings"] = [
        binding for binding in payload["asset_bindings"] if binding["asset_ref"] != missing_ref  # type: ignore[index]
    ]
    with pytest.raises(ValidationError, match="asset_binding_inventory_mismatch"):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


def test_material_source_media_assignments_use_exact_typed_members_and_inventory() -> None:
    assigned_ref = "assigned:geometry:v1"
    accepted = _material()
    accepted["normalized_source_packet"]["source_media_assignments"] = [  # type: ignore[index]
        {"room_id": "living", "geometry_ref": assigned_ref}
    ]
    accepted["asset_bindings"].append(  # type: ignore[union-attr]
        _asset(ref=assigned_ref, purpose="source_geometry", media_type="application/json")
    )
    _refresh_material_lineage(accepted)
    GovernedSpatialExecutionMaterialV1.model_validate(accepted)

    missing = deepcopy(accepted)
    missing["asset_bindings"] = [
        binding for binding in missing["asset_bindings"] if binding["asset_ref"] != assigned_ref  # type: ignore[index]
    ]
    with pytest.raises(ValidationError, match="asset_binding_inventory_mismatch"):
        GovernedSpatialExecutionMaterialV1.model_validate(missing)


@pytest.mark.parametrize(
    "assignment",
    [
        {"geometry_ref": "assigned:geometry:v1", "video_ref": "undeclared:video:v1"},
        {"geometry_ref": "assigned:geometry:v1", "metadata": {"video_ref": "undeclared:video:v1"}},
        {"geometry_ref": "assigned:geometry:v1", "room_id": {"nested": "living"}},
        {"geometry_refs": [{"nested_ref": "undeclared:geometry:v1"}]},
        {"geometry_ref": "assigned:geometry:v1", "texture_ref": None},
        {"geometry_ref": "assigned:geometry:v1", "room_id": "unknown"},
    ],
)
def test_material_rejects_mixed_unsupported_or_nested_source_assignment_members(
    assignment: dict[str, object],
) -> None:
    payload = _material()
    payload["normalized_source_packet"]["source_media_assignments"] = [assignment]  # type: ignore[index]
    payload["asset_bindings"].append(  # type: ignore[union-attr]
        _asset(ref="assigned:geometry:v1", purpose="source_geometry", media_type="application/json")
    )
    _refresh_material_lineage(payload)
    with pytest.raises(ValidationError):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


@pytest.mark.parametrize(
    ("style_field", "purpose"),
    [
        ("external_asset_refs", "style_asset"),
        ("visual_direction_refs", "visual_direction"),
        ("visual_regression_refs", "verification_reference"),
        ("acceptance_contact_sheet_refs", "verification_reference"),
    ],
)
def test_material_requires_every_declared_style_byte_asset(style_field: str, purpose: str) -> None:
    payload = _material()
    payload["style_snapshot"][style_field] = [f"style-byte:{style_field}"]  # type: ignore[index]
    _refresh_material_lineage(payload)
    with pytest.raises(ValidationError, match="asset_binding_inventory_mismatch"):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)

    payload["asset_bindings"].append(  # type: ignore[union-attr]
        _asset(ref=f"style-byte:{style_field}", purpose=purpose)
    )
    GovernedSpatialExecutionMaterialV1.model_validate(payload)


def test_execution_material_rejects_every_noncanonical_request_or_source_form() -> None:
    cases = []
    request_id = _material()
    request_id["normalized_request"]["request_id"] = "74bc092f-c6d8-44ec-990a-5738cc0987ac"
    cases.append(request_id)
    request_float = _material()
    request_float["normalized_request"]["camera"]["height_m"] = 1.6
    cases.append(request_float)
    source_float = _material()
    source_float["normalized_source_packet"]["rooms"][0]["ceiling_height_m"] = 2.5
    cases.append(source_float)
    source_prefixed_digest = _material()
    source_prefixed_digest["normalized_source_packet"]["source_digest"] = "sha256:" + "b" * 64
    cases.append(source_prefixed_digest)
    source_omission = _material()
    source_omission["normalized_source_packet"]["rooms"][0].pop("accessible")
    cases.append(source_omission)
    request_omission = _material()
    request_omission["normalized_request"]["style"].pop("asset_reuse_proof_refs")
    cases.append(request_omission)
    for payload in cases:
        with pytest.raises(ValidationError, match="canonical_form_required|request_id_forbidden|float_forbidden"):
            GovernedSpatialExecutionMaterialV1.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("request_digest", "request_digest_mismatch"),
        ("source_packet_digest", "source_packet_digest_mismatch"),
        ("style_snapshot_digest", "style_snapshot_digest_mismatch"),
        ("output_contract_digest", "output_contract_digest_mismatch"),
    ],
)
def test_execution_material_recomputes_all_nested_lineage_digests(field: str, reason: str) -> None:
    payload = _material()
    payload[field] = DIGEST
    if payload[field] == _material()[field]:
        payload[field] = "sha256:" + "c" * 64
    with pytest.raises(ValidationError, match=reason):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


def test_execution_request_is_bound_to_exact_material_before_action() -> None:
    material = GovernedSpatialExecutionMaterialV1.model_validate(_material())
    request = GovernedSpatialExecutionRequestV1.model_validate(_bound_execution_request())
    validate_execution_request_material_binding(request, material)
    for field in (
        "composition_digest", "request_digest", "source_packet_digest", "style_snapshot_digest",
        "output_contract_digest", "execution_target_digest", "material_digest",
    ):
        payload = _bound_execution_request()
        payload[field] = "sha256:" + "c" * 64
        substituted = GovernedSpatialExecutionRequestV1.model_validate(payload)
        with pytest.raises(SpatialExecutionContractError, match="mismatch"):
            validate_execution_request_material_binding(substituted, material)

    style = _bound_execution_request()
    style["style_snapshot"]["palette"] = ["substituted"]
    style["style_snapshot_digest"] = material.style_snapshot_digest
    with pytest.raises(SpatialExecutionContractError, match="style_snapshot_mismatch"):
        validate_execution_request_material_binding(
            GovernedSpatialExecutionRequestV1.model_validate(style), material
        )

    asset = _bound_execution_request()
    asset["asset_bindings"][0]["sha256"] = "sha256:" + "c" * 64
    with pytest.raises(SpatialExecutionContractError, match="asset_bindings_mismatch"):
        validate_execution_request_material_binding(
            GovernedSpatialExecutionRequestV1.model_validate(asset), material
        )

    output = _bound_execution_request()
    output["render_spec"]["output"]["video_codec"] = "av1"
    with pytest.raises(SpatialExecutionContractError, match="render_spec_mismatch"):
        validate_execution_request_material_binding(
            GovernedSpatialExecutionRequestV1.model_validate(output), material
        )


def test_execution_request_material_binding_preserves_asset_order() -> None:
    material_payload = _material()
    material = GovernedSpatialExecutionMaterialV1.model_validate(material_payload)
    request_payload = _bound_execution_request()
    request_payload["asset_bindings"] = deepcopy(material_payload["asset_bindings"])
    request_payload["material_digest"] = material_digest(material)
    request = GovernedSpatialExecutionRequestV1.model_validate(request_payload)
    validate_execution_request_material_binding(request, material)
    reversed_payload = deepcopy(request_payload)
    reversed_payload["asset_bindings"].reverse()
    with pytest.raises(SpatialExecutionContractError, match="asset_bindings_mismatch"):
        validate_execution_request_material_binding(
            GovernedSpatialExecutionRequestV1.model_validate(reversed_payload), material
        )
    payload = _material()
    payload["normalized_source_packet"]["credential"] = "secret-value"
    with pytest.raises(ValidationError):
        GovernedSpatialExecutionMaterialV1.model_validate(payload)


@pytest.mark.parametrize("attack", ["nested_dict", "nested_list", "model_internal"])
def test_public_material_helpers_revalidate_untrusted_parsed_instances(attack: str) -> None:
    material = parse_execution_material(_material())
    request = parse_execution_request(_bound_execution_request())
    if attack == "nested_dict":
        material.normalized_request["provider_url"] = "https://attacker.invalid/credential"
        material.__dict__["request_digest"] = _digest(material.normalized_request)
        request.__dict__["request_digest"] = material.request_digest
    elif attack == "nested_list":
        material.asset_bindings.append(material.asset_bindings[0].model_copy())
    else:
        material.style_snapshot.__dict__["style_pack_id"] = "https://attacker.invalid/credential"
        material.__dict__["style_snapshot_digest"] = _digest(material.style_snapshot.model_dump(mode="json"))
        request.__dict__["style_snapshot_digest"] = material.style_snapshot_digest
    request.__dict__["material_digest"] = _digest(material.model_dump(mode="json"))

    with pytest.raises(SpatialExecutionContractError, match="execution_material_validation_failed"):
        canonical_material_bytes(material)
    with pytest.raises(SpatialExecutionContractError, match="execution_material_validation_failed"):
        validate_execution_request_material_binding(request, material)


def test_public_request_helpers_revalidate_untrusted_parsed_instances() -> None:
    request = parse_execution_request(_bound_execution_request())
    request.render_spec.rooms[0].texture_anchor_refs.append("https://attacker.invalid/credential")
    request.__dict__["material_digest"] = DIGEST
    with pytest.raises(SpatialExecutionContractError, match="execution_request_validation_failed"):
        validate_execution_request_material_binding(request, parse_execution_material(_material()))
    with pytest.raises(SpatialExecutionContractError, match="execution_request_validation_failed"):
        validate_execution_gate_versions(
            request,
            {"artifact_family": request.artifact_family, "gate_versions": dict(request.gate_versions)},
        )


def test_affected_typed_helpers_redact_nonserializable_mutation_names() -> None:
    attack_name = "credential_secret_material_ref_ABC"

    def mutated_material() -> GovernedSpatialExecutionMaterialV1:
        material = parse_execution_material(_material())
        material.normalized_request["callback"]["product_event_ref"] = (  # type: ignore[index]
            credential_secret_material_ref_ABC()
        )
        return material

    material_helpers = (
        lambda: canonical_material_bytes(mutated_material()),
        lambda: material_digest(mutated_material()),
        lambda: validate_execution_request_material_binding(
            parse_execution_request(_bound_execution_request()), mutated_material()
        ),
    )
    for helper in material_helpers:
        with pytest.raises(SpatialExecutionContractError) as failure:
            helper()
        assert str(failure.value) == "execution_material_validation_failed"
        assert attack_name not in str(failure.value)

    def mutated_request() -> GovernedSpatialExecutionRequestV1:
        request = parse_execution_request(_bound_execution_request())
        request.render_spec.__dict__["normalized_floorplan_ref"] = credential_secret_material_ref_ABC()
        return request

    request_helpers = (
        lambda: validate_execution_request_material_binding(
            mutated_request(), parse_execution_material(_material())
        ),
        lambda: validate_execution_gate_versions(
            mutated_request(),
            {
                "artifact_family": "propertyquarry_continuous_walkthrough",
                "gate_versions": {"compose": "1", "quota": "1", "property_policy": "1"},
            },
        ),
    )
    for helper in request_helpers:
        with pytest.raises(SpatialExecutionContractError) as failure:
            helper()
        assert str(failure.value) == "execution_request_validation_failed"
        assert attack_name not in str(failure.value)


def test_other_public_action_and_canonical_helpers_revalidate_typed_instances() -> None:
    envelope = GovernedSpatialExecutionMaterialEnvelopeV1.model_validate(_envelope())
    envelope.__dict__["key_ref"] = "https://attacker.invalid/credential"
    with pytest.raises(SpatialExecutionContractError, match="execution_envelope_validation_failed"):
        envelope_aad_bytes(envelope)

    receipt = GovernedSpatialOperationReconciliationV1.model_validate(_reconciliation())
    receipt.signature.__dict__["key_ref"] = "https://attacker.invalid/credential"
    for helper in (
        lambda: reconciliation_digest(receipt),
        lambda: validate_reconciliation_freshness(receipt, now=NOW),
        lambda: validate_reconciliation_transition(None, receipt),
    ):
        with pytest.raises(SpatialExecutionContractError, match="reconciliation.*validation_failed"):
            helper()

    snapshot = GovernedSpatialStyleSnapshotV1.model_validate(_style())
    snapshot.__dict__["style_pack_id"] = "https://attacker.invalid/credential"
    with pytest.raises(SpatialExecutionContractError, match="style_snapshot_validation_failed"):
        validate_style_snapshot_time(snapshot, now=NOW)


def test_execution_material_binds_packet_timestamp_chronology_and_digest() -> None:
    for mutate, reason in (
        (
            lambda payload: payload.__setitem__("source_packet_created_at", "2026-07-12T08:31:00Z"),
            "source_packet_created_at_binding_mismatch",
        ),
        (
            lambda payload: payload["normalized_source_packet"].__setitem__(  # type: ignore[union-attr]
                "source_packet_created_at", "2026-07-12T09:01:00Z"
            ),
            "source_packet_created_at_binding_mismatch",
        ),
        (
            lambda payload: payload.__setitem__("source_packet_digest", DIGEST),
            "source_packet_digest_mismatch",
        ),
    ):
        payload = _material()
        mutate(payload)
        with pytest.raises(ValidationError, match=reason):
            GovernedSpatialExecutionMaterialV1.model_validate(payload)

    omitted = _material()
    omitted["normalized_source_packet"].pop("source_packet_created_at")  # type: ignore[union-attr]
    omitted["source_packet_digest"] = _source_packet_digest(omitted["normalized_source_packet"])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="normalized_source_packet_canonical_form_required"):
        GovernedSpatialExecutionMaterialV1.model_validate(omitted)

    after_compose = _material()
    packet = after_compose["normalized_source_packet"]
    packet["source_packet_created_at"] = "2026-07-12T09:01:00Z"  # type: ignore[index]
    after_compose["source_packet_created_at"] = "2026-07-12T09:01:00Z"
    after_compose["source_packet_digest"] = _source_packet_digest(packet)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="material_timestamp_chronology_invalid"):
        GovernedSpatialExecutionMaterialV1.model_validate(after_compose)


def test_envelope_validates_exact_aad_nonce_tag_and_unknown_fields() -> None:
    envelope = GovernedSpatialExecutionMaterialEnvelopeV1.model_validate(_envelope())
    assert envelope_aad_bytes(envelope) == envelope_aad_bytes(_envelope())
    for field, value in (
        ("nonce", "AA"),
        ("ciphertext", base64.urlsafe_b64encode(b"short").decode().rstrip("=")),
        ("aad_digest", DIGEST),
        ("key_epoch", True),
    ):
        payload = _envelope()
        payload[field] = value
        with pytest.raises(ValidationError):
            GovernedSpatialExecutionMaterialEnvelopeV1.model_validate(payload)
    payload = _envelope()
    payload["path"] = "/tmp/leak"
    with pytest.raises(ValidationError):
        GovernedSpatialExecutionMaterialEnvelopeV1.model_validate(payload)


@pytest.mark.parametrize(
    ("state", "count", "outputs", "valid"),
    [
        ("succeeded", 1, True, True),
        ("succeeded", 0, True, False),
        ("failed_final", 1, False, True),
        ("unknown", 0, False, True),
        ("failed_final", 0, True, False),
    ],
)
def test_adapter_result_success_failure_nullable_rules(
    state: str, count: int, outputs: bool, valid: bool
) -> None:
    payload = {
        "contract_name": "ea.governed_spatial_execution_result.v1",
        "contract_version": "1.0.0",
        "operation_id": "operation:fixture:v1",
        "state": state,
        "output_digest": DIGEST if outputs else None,
        "output_manifest_ref": "manifest:fixture:v1" if outputs else None,
        "private_execution_receipt_digest": DIGEST if outputs else None,
        "provider_action_count": count,
    }
    if valid:
        GovernedSpatialExecutionResultV1.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            GovernedSpatialExecutionResultV1.model_validate(payload)
    payload["provider_action_count"] = True
    with pytest.raises(ValidationError):
        GovernedSpatialExecutionResultV1.model_validate(payload)


def test_reconciliation_shapes_freshness_and_monotonic_terminal_restatement() -> None:
    first = GovernedSpatialOperationReconciliationV1.model_validate(_reconciliation())
    validate_reconciliation_freshness(first, now=NOW)
    terminal_payload = _reconciliation(
        sequence=2, state="succeeded", outcome=DIGEST, prior=reconciliation_digest(first)
    )
    terminal = GovernedSpatialOperationReconciliationV1.model_validate(terminal_payload)
    validate_reconciliation_transition(first, terminal)
    restated = GovernedSpatialOperationReconciliationV1.model_validate(
        _reconciliation(sequence=3, state="succeeded", outcome=DIGEST, prior=reconciliation_digest(terminal))
    )
    validate_reconciliation_transition(terminal, restated)
    changed = restated.model_copy(update={"state": "failed_final"})
    with pytest.raises(SpatialExecutionContractError, match="terminal_restatement_mismatch"):
        validate_reconciliation_transition(terminal, changed)
    with pytest.raises(SpatialExecutionContractError, match="stale"):
        validate_reconciliation_freshness(first, now=NOW + timedelta(minutes=6))


def test_reconciliation_rejects_stale_observation_future_times_and_time_regression() -> None:
    stale = _reconciliation()
    stale["observed_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValidationError, match="reconciliation_timestamp_window_invalid"):
        GovernedSpatialOperationReconciliationV1.model_validate(stale)

    for field, reason in (
        ("observed_at", "reconciliation_observed_in_future"),
        ("issued_at", "reconciliation_issued_in_future"),
    ):
        future = _reconciliation()
        future[field] = "2026-07-12T10:00:01Z"
        if field == "observed_at":
            future["issued_at"] = "2026-07-12T10:00:02Z"
            future["expires_at"] = "2026-07-12T10:05:02Z"
        parsed = GovernedSpatialOperationReconciliationV1.model_validate(future)
        with pytest.raises(SpatialExecutionContractError, match=reason):
            validate_reconciliation_freshness(parsed, now=NOW)

    for field, reason in (
        ("observed_at", "reconciliation_observed_at_regression"),
        ("issued_at", "reconciliation_issued_at_regression"),
    ):
        previous_payload = _reconciliation()
        if field == "issued_at":
            previous_payload["observed_at"] = "2026-07-12T09:57:00Z"
        previous = GovernedSpatialOperationReconciliationV1.model_validate(previous_payload)
        current_payload = _reconciliation(sequence=2, prior=reconciliation_digest(previous))
        current_payload[field] = "2026-07-12T09:58:00Z"
        if field == "observed_at":
            current_payload["issued_at"] = "2026-07-12T10:00:00Z"
        else:
            current_payload["observed_at"] = "2026-07-12T09:57:30Z"
            current_payload["expires_at"] = "2026-07-12T10:03:00Z"
        current = GovernedSpatialOperationReconciliationV1.model_validate(current_payload)
        with pytest.raises(SpatialExecutionContractError, match=reason):
            validate_reconciliation_transition(previous, current)


def test_reconciliation_not_started_and_transition_regressions_fail() -> None:
    not_started = GovernedSpatialOperationReconciliationV1.model_validate(
        _reconciliation(state="not_started")
    )
    validate_reconciliation_transition(None, not_started)
    payload = _reconciliation(sequence=2, state="not_started", prior=DIGEST)
    with pytest.raises(ValidationError, match="not_started_shape_invalid"):
        GovernedSpatialOperationReconciliationV1.model_validate(payload)
    first = GovernedSpatialOperationReconciliationV1.model_validate(_reconciliation())
    current = GovernedSpatialOperationReconciliationV1.model_validate(
        _reconciliation(sequence=2, prior=DIGEST)
    )
    with pytest.raises(SpatialExecutionContractError, match="prior_digest_mismatch"):
        validate_reconciliation_transition(first, current)


def _normal_projection() -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.governed_spatial_execution_projection.v1",
        "contract_version": "1.0.0",
        "state": "blocked",
        "reason_code": "policy_unavailable",
        "composition_digest": DIGEST,
        "output_digest": None,
        "verification_digest": None,
        "artifact_ref": None,
        "privacy_deletion_status": "not_requested",
        "idempotent_replay_state": "new",
    }


def _deletion_projection() -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.governed_spatial_deletion_evidence_projection.v1",
        "contract_version": "1.0.0",
        "scope_digest": DIGEST,
        "tombstone_digest": DIGEST,
        "deletion_evidence_digest": DIGEST,
        "requested_at": "2026-07-12T08:00:00Z",
        "tombstoned_at": "2026-07-12T08:01:00Z",
        "ciphertext_deleted_at": "2026-07-12T08:02:00Z",
        "derivative_coverage": "complete",
        "provider_deletion_state": "not_applicable",
        "retry_state": "not_required",
        "next_retry_at": None,
    }


def test_property_response_parser_is_disjoint_and_rejects_mixing_unknown_and_leaks() -> None:
    assert parse_property_response(_normal_projection()).state == "blocked"
    assert isinstance(parse_property_response(json.dumps(_deletion_projection())), PropertyDeletionEvidenceProjectionV1)
    for payload in (
        {**_normal_projection(), "tombstone_digest": DIGEST},
        {**_deletion_projection(), "artifact_ref": "artifact:first-party:v1"},
        {**_normal_projection(), "provider_url": "https://provider.invalid"},
        {**_normal_projection(), "contract_name": "propertyquarry.unknown.v1"},
    ):
        with pytest.raises((ValidationError, SpatialExecutionContractError)):
            parse_property_response(payload)


def test_property_projection_enforces_exact_state_reason_and_output_coherence() -> None:
    succeeded = _normal_projection()
    succeeded.update(
        {
            "state": "succeeded", "reason_code": "none", "output_digest": DIGEST,
            "verification_digest": DIGEST, "artifact_ref": "artifact:first-party:v1",
        }
    )
    assert parse_property_response(succeeded).state == "succeeded"
    contradictory = [
        {**succeeded, "output_digest": None},
        {**succeeded, "reason_code": "execution_failed"},
        {**_normal_projection(), "reason_code": "none"},
        {**_normal_projection(), "output_digest": DIGEST},
        {**_normal_projection(), "state": "pending", "reason_code": "policy_unavailable"},
        {**_normal_projection(), "state": "failed_final", "reason_code": "reconciliation_pending"},
    ]
    for payload in contradictory:
        with pytest.raises(SpatialExecutionContractError, match="property_response_validation_failed"):
            parse_property_response(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "provider_task_complete"),
        ("reason_code", "provider.task.credential"),
        ("privacy_deletion_status", "account_deleted"),
        ("idempotent_replay_state", "provider_job_replayed"),
    ],
)
def test_property_projection_allowed_fields_cannot_leak_private_values(field: str, value: str) -> None:
    payload = _normal_projection()
    payload[field] = value
    with pytest.raises(SpatialExecutionContractError) as exc_info:
        parse_property_response(payload)
    rendered = str(exc_info.value)
    assert rendered == "property_response_validation_failed"
    assert value not in rendered


def test_property_raw_json_failures_are_static_and_redacted() -> None:
    raw = b'{"contract_name":"propertyquarry.governed_spatial_execution_projection.v1","credential":"first","credential":"secret-material-ref-ABC"}'
    with pytest.raises(SpatialExecutionContractError) as exc_info:
        parse_property_response(raw)
    assert str(exc_info.value) == "property_response_duplicate_member"
    assert "credential" not in str(exc_info.value)
    assert "secret-material-ref-ABC" not in str(exc_info.value)


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize(
    ("parser", "payload_factory", "member", "nested"),
    [
        (parse_property_response, _normal_projection, "credential-secret-material-ref-ABC", False),
        (parse_property_response, _normal_projection, "provider_url", False),
        (parse_execution_material, _material, "credential-secret-material-ref-ABC", True),
        (parse_execution_request, _bound_execution_request, "provider_url", True),
    ],
)
def test_public_boundary_parsers_never_reflect_unknown_sensitive_member_names(
    as_json: bool, parser: object, payload_factory: object, member: str, nested: bool
) -> None:
    payload = payload_factory()
    target = payload["normalized_source_packet"] if nested and parser is parse_execution_material else payload
    if nested and parser is parse_execution_request:
        target = payload["style_snapshot"]
    target[member] = "opaque"
    supplied = json.dumps(payload) if as_json else payload
    with pytest.raises(SpatialExecutionContractError) as exc_info:
        parser(supplied)
    rendered = str(exc_info.value)
    assert member not in rendered
    assert "credential" not in rendered
    assert "provider_url" not in rendered


def test_all_top_level_models_forbid_unknown_members_and_wrong_identifiers() -> None:
    cases = [
        (GovernedSpatialRenderSpecV1, _render_spec()),
        (GovernedSpatialStyleSnapshotV1, _style()),
        (GovernedSpatialExecutionMaterialV1, _material()),
        (GovernedSpatialExecutionRequestV1, _execution_request()),
        (GovernedSpatialExecutionMaterialEnvelopeV1, _envelope()),
    ]
    for model, valid in cases:
        unknown = deepcopy(valid)
        unknown["raw_trace"] = "leak"
        with pytest.raises(ValidationError):
            model.model_validate(unknown)
        wrong = deepcopy(valid)
        wrong["contract_version"] = "2.0.0"
        with pytest.raises(ValidationError):
            model.model_validate(wrong)


def test_environment_enum_and_validation_errors_are_provider_redacted() -> None:
    payload = _execution_request()
    payload["environment"] = "customer-production-west"
    with pytest.raises(ValidationError):
        GovernedSpatialExecutionRequestV1.model_validate(payload)
    asset = _asset(ref="https://sensitive.invalid/account/123")
    with pytest.raises(ValidationError) as exc_info:
        GovernedSpatialAssetBindingV1.model_validate(asset)
    rendered = str(exc_info.value)
    assert "sensitive.invalid" not in rendered
    assert "account/123" not in rendered


STORE_NOW = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
STORE_KEY = b"K" * 32
_DEFAULT_RETENTION_RESOLVER = object()
FIXED_VECTOR_KEY_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
FIXED_VECTOR_NONCE_HEX = "000102030405060708090a0b"
FIXED_VECTOR_PLAINTEXT_B64 = "eyJjb250cmFjdCI6ImZpeGVkLXZlY3RvciIsInZhbHVlIjoxfQ=="
FIXED_VECTOR_AAD_B64 = (
    "eyJhbGdvcml0aG0iOiJhZXMtMjU2LWdjbSIsImNhbm9uaWNhbGl6YXRpb24iOiJyZmM4Nzg1X2pjc19ib3VuZGVkX25vX2Zsb2F0X3YxIiwiY2lwaGVydGV4dF9lbmNvZGluZyI6ImJhc2U2NHVybF9ub19wYWRkaW5nIiwiY29tcG9zaXRpb25fZGlnZXN0Ijoic2hhMjU2OmFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWEiLCJjb250cmFjdF9uYW1lIjoiZWEuZ292ZXJuZWRfc3BhdGlhbF9leGVjdXRpb25fbWF0ZXJpYWxfZW52ZWxvcGUudjEiLCJjb250cmFjdF92ZXJzaW9uIjoiMS4wLjAiLCJjcmVhdGVkX2F0IjoiMjAyNi0wNy0xMlQwOTowMDowMFoiLCJlbnZpcm9ubWVudCI6InRlc3QiLCJleGVjdXRpb25fdGFyZ2V0X2RpZ2VzdCI6InNoYTI1NjpmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmIiwia2V5X2Vwb2NoIjo3LCJrZXlfZmluZ2VycHJpbnQiOiJzaGEyNTY6NjMwZGNkMjk2NmM0MzM2NjkxMTI1NDQ4YmJiMjViNGZmNDEyYTQ5YzczMmRiMmM4YWJjMWI4NTgxYmQ3MTBkZCIsImtleV9yZWYiOiJtYXRlcmlhbC1rZXk6dmVjdG9yOnYxIiwibWF0ZXJpYWxfZGlnZXN0Ijoic2hhMjU2OjIxOTBkNTUzOGRlODdjYTA3YzdkZmZjNDNmYmI3ZWU0MWM4M2UxZTYwNjUwMjE3ZGY3YmIxNjQ5M2U3YjQ4ZTciLCJtYXRlcmlhbF9pZGVudGl0eSI6Im1hdGVyaWFsOmFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWEiLCJub25jZSI6IkFBRUNBd1FGQmdjSUNRb0wiLCJub25jZV9lbmNvZGluZyI6ImJhc2U2NHVybF9ub19wYWRkaW5nIiwib3V0cHV0X2NvbnRyYWN0X2RpZ2VzdCI6InNoYTI1NjplZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlIiwicmVxdWVzdF9kaWdlc3QiOiJzaGEyNTY6YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYiIsInJldGVudGlvbl9leHBpcmVzX2F0IjoiMjAyNi0wNy0yMFQwOTowMDowMFoiLCJzb3VyY2VfcGFja2V0X2RpZ2VzdCI6InNoYTI1NjpjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjIiwic3R5bGVfc25hcHNob3RfZGlnZXN0Ijoic2hhMjU2OmRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGQifQ=="
)
FIXED_VECTOR_AAD_DIGEST = "sha256:6f4763b6c69e6b7cee9e34e1bc3b92a0b3e527af4e7d07874d7fdefe8828c89a"
FIXED_VECTOR_MATERIAL_DIGEST = "sha256:2190d5538de87ca07c7dffc43fbb7ee41c83e1e60650217df7bb16493e7b48e7"
FIXED_VECTOR_CIPHERTEXT_TAG_B64 = "PCC1dKuRsHruNbWxk48RFeayqkKVGCsTSkXJp2sIbMdkMpTN0pg5XBCPd/lCe+PyayiMMPk="
FIXED_VECTOR_FULL_ENVELOPE_B64 = (
    "eyJhYWRfZGlnZXN0Ijoic2hhMjU2OjZmNDc2M2I2YzY5ZTZiN2NlZTllMzRlMWJjM2I5MmEwYjNlNTI3YWY0ZTdkMDc4NzRkN2ZkZWZlODgyOGM4OWEiLCJhbGdvcml0aG0iOiJhZXMtMjU2LWdjbSIsImNhbm9uaWNhbGl6YXRpb24iOiJyZmM4Nzg1X2pjc19ib3VuZGVkX25vX2Zsb2F0X3YxIiwiY2lwaGVydGV4dCI6IlBDQzFkS3VSc0hydU5iV3hrNDhSRmVheXFrS1ZHQ3NUU2tYSnAyc0liTWRrTXBUTjBwZzVYQkNQZF9sQ2UtUHlheWlNTVBrIiwiY2lwaGVydGV4dF9lbmNvZGluZyI6ImJhc2U2NHVybF9ub19wYWRkaW5nIiwiY29tcG9zaXRpb25fZGlnZXN0Ijoic2hhMjU2OmFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWEiLCJjb250cmFjdF9uYW1lIjoiZWEuZ292ZXJuZWRfc3BhdGlhbF9leGVjdXRpb25fbWF0ZXJpYWxfZW52ZWxvcGUudjEiLCJjb250cmFjdF92ZXJzaW9uIjoiMS4wLjAiLCJjcmVhdGVkX2F0IjoiMjAyNi0wNy0xMlQwOTowMDowMFoiLCJlbnZpcm9ubWVudCI6InRlc3QiLCJleGVjdXRpb25fdGFyZ2V0X2RpZ2VzdCI6InNoYTI1NjpmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmIiwia2V5X2Vwb2NoIjo3LCJrZXlfZmluZ2VycHJpbnQiOiJzaGEyNTY6NjMwZGNkMjk2NmM0MzM2NjkxMTI1NDQ4YmJiMjViNGZmNDEyYTQ5YzczMmRiMmM4YWJjMWI4NTgxYmQ3MTBkZCIsImtleV9yZWYiOiJtYXRlcmlhbC1rZXk6dmVjdG9yOnYxIiwibWF0ZXJpYWxfZGlnZXN0Ijoic2hhMjU2OjIxOTBkNTUzOGRlODdjYTA3YzdkZmZjNDNmYmI3ZWU0MWM4M2UxZTYwNjUwMjE3ZGY3YmIxNjQ5M2U3YjQ4ZTciLCJtYXRlcmlhbF9pZGVudGl0eSI6Im1hdGVyaWFsOmFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWEiLCJub25jZSI6IkFBRUNBd1FGQmdjSUNRb0wiLCJub25jZV9lbmNvZGluZyI6ImJhc2U2NHVybF9ub19wYWRkaW5nIiwib3V0cHV0X2NvbnRyYWN0X2RpZ2VzdCI6InNoYTI1NjplZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlIiwicmVxdWVzdF9kaWdlc3QiOiJzaGEyNTY6YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYiIsInJldGVudGlvbl9leHBpcmVzX2F0IjoiMjAyNi0wNy0yMFQwOTowMDowMFoiLCJzb3VyY2VfcGFja2V0X2RpZ2VzdCI6InNoYTI1NjpjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjIiwic3R5bGVfc25hcHNob3RfZGlnZXN0Ijoic2hhMjU2OmRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGRkZGQifQ=="
)


def _key_record(
    *, key: bytes = STORE_KEY, state: str = "active_encrypt_decrypt", epoch: int = 1,
    key_ref: str = "material-key:test:v1", not_before: datetime | None = None,
    decrypt_until: datetime | None = None, environment: str = "test",
) -> SpatialMaterialKeyRecord:
    return SpatialMaterialKeyRecord(
        environment=environment,
        key_ref=key_ref,
        key_epoch=epoch,
        key_fingerprint=key_fingerprint(key),
        key_bytes=key,
        state=state,  # type: ignore[arg-type]
        not_before=not_before or datetime(2026, 7, 1, tzinfo=UTC),
        decrypt_until=decrypt_until or datetime(2026, 8, 1, tzinfo=UTC),
    )


def _store(
    root: Path, *, records: list[SpatialMaterialKeyRecord] | None = None,
    now: list[datetime] | None = None, crash_hook: object | None = None,
    randomness: object | None = None, journal_write: object | None = None,
    retention_resolver: object = _DEFAULT_RETENTION_RESOLVER,
    authority_guarded_recovery: bool = False,
    lifecycle_authority: object | None = None,
) -> SpatialExecutionMaterialStore:
    current = now or [STORE_NOW]
    resolver = retention_resolver
    if resolver is _DEFAULT_RETENTION_RESOLVER:
        resolver = lambda material: datetime.fromisoformat(
            material.retention_expires_at.replace("Z", "+00:00")
        )
    return SpatialExecutionMaterialStore(
        root,
        environment="test",
        keys=SpatialMaterialKeyRegistry([_key_record()] if records is None else records),
        clock=lambda: current[0],
        crash_hook=crash_hook,  # type: ignore[arg-type]
        randomness=randomness,  # type: ignore[arg-type]
        journal_write=journal_write,  # type: ignore[arg-type]
        retention_resolver=resolver,  # type: ignore[arg-type]
        authority_guarded_recovery=authority_guarded_recovery,
        lifecycle_authority=lifecycle_authority,  # type: ignore[arg-type]
    )


def _envelope_path(root: Path, material: dict[str, object] | None = None) -> Path:
    composition = (material or _material())["composition_digest"]
    return root / f"{str(composition)[7:]}.envelope.json"


def _temporary_envelope_path(root: Path, material: dict[str, object] | None = None) -> Path:
    envelope = _envelope_path(root, material)
    return root / f".{envelope.name}.tmp"


def _material_variant(character: str) -> dict[str, object]:
    payload = _material()
    payload["composition_digest"] = "sha256:" + character * 64
    return payload


def _first_use_process(root: str, queue: object) -> None:
    try:
        store = _store(Path(root))
        store.seal(_material())
        queue.put("ok")  # type: ignore[attr-defined]
    except Exception as exc:
        queue.put(f"{type(exc).__name__}:{exc}")  # type: ignore[attr-defined]


def _lifecycle_guard_process(
    root: str, scope_digest: str, started: object, acquired: object,
) -> None:
    started.put("started")  # type: ignore[attr-defined]
    ledger = DurableSpatialLedger(Path(root))
    with ledger.composition_privacy_lifecycle_guard(scope_digest):
        acquired.put("acquired")  # type: ignore[attr-defined]


class _ShortThenErrorJournalWriter:
    def __init__(self, state: str) -> None:
        self._needle = f'"state":"{state}"'.encode()
        self._partial = False

    def __call__(self, fd: int, payload: bytes) -> int:
        if self._partial:
            raise OSError("private journal device path")
        if self._needle in payload:
            self._partial = True
            return os.write(fd, payload[:13])
        return os.write(fd, payload)


def _journal_records(root: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (root / "material.journal.jsonl").read_text().splitlines()]


def test_material_store_aes_gcm_roundtrip_exact_aad_tag_and_random_nonce(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = _store(first_root)
    second = _store(second_root)
    material = parse_execution_material(_material())
    envelope_one = first.seal(material)
    envelope_two = second.seal(material)
    assert envelope_one.nonce != envelope_two.nonce
    assert first.load(material.composition_digest) == material

    ciphertext = GovernedSpatialExecutionMaterialEnvelopeV1._decode(
        envelope_one.ciphertext, "ciphertext_shape_invalid"
    )
    assert len(ciphertext) == len(canonical_material_bytes(material)) + 16
    assert ciphertext[-16:] != b"\x00" * 16
    aad = envelope_aad_bytes(envelope_one)
    assert envelope_one.aad_digest == "sha256:" + hashlib.sha256(aad).hexdigest()
    nonce = GovernedSpatialExecutionMaterialEnvelopeV1._decode(envelope_one.nonce, "nonce_shape_invalid")
    assert AESGCM(STORE_KEY).decrypt(nonce, ciphertext, aad) == canonical_material_bytes(material)
    with pytest.raises(InvalidTag):
        AESGCM(STORE_KEY).decrypt(nonce, ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]), aad)


def _fixed_vector_payload() -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_execution_material_envelope.v1",
        "contract_version": "1.0.0",
        "environment": "test",
        "material_identity": "material:" + "a" * 64,
        "material_digest": FIXED_VECTOR_MATERIAL_DIGEST,
        "composition_digest": "sha256:" + "a" * 64,
        "request_digest": "sha256:" + "b" * 64,
        "source_packet_digest": "sha256:" + "c" * 64,
        "style_snapshot_digest": "sha256:" + "d" * 64,
        "output_contract_digest": "sha256:" + "e" * 64,
        "execution_target_digest": "sha256:" + "f" * 64,
        "created_at": "2026-07-12T09:00:00Z",
        "retention_expires_at": "2026-07-20T09:00:00Z",
        "key_ref": "material-key:vector:v1",
        "key_epoch": 7,
        "key_fingerprint": "sha256:630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd",
        "algorithm": "aes-256-gcm",
        "nonce_encoding": "base64url_no_padding",
        "nonce": "AAECAwQFBgcICQoL",
        "ciphertext_encoding": "base64url_no_padding",
        "ciphertext": "",
        "canonicalization": CANONICALIZATION,
        "aad_digest": "",
    }


def test_independent_fixed_aes_jcs_envelope_vector_matches_production_bytes() -> None:
    key = bytes.fromhex(FIXED_VECTOR_KEY_HEX)
    nonce = bytes.fromhex(FIXED_VECTOR_NONCE_HEX)
    plaintext = base64.b64decode(FIXED_VECTOR_PLAINTEXT_B64)
    expected_aad = base64.b64decode(FIXED_VECTOR_AAD_B64)
    expected_ciphertext = base64.b64decode(FIXED_VECTOR_CIPHERTEXT_TAG_B64)
    expected_envelope = base64.b64decode(FIXED_VECTOR_FULL_ENVELOPE_B64)
    assert plaintext == b'{"contract":"fixed-vector","value":1}'
    assert hashlib.sha256(plaintext).hexdigest() == FIXED_VECTOR_MATERIAL_DIGEST[7:]
    assert nonce == bytes(range(12))

    envelope, encoded = execution_module._seal_envelope_payload(
        _fixed_vector_payload(), plaintext=plaintext, key_bytes=key
    )

    assert envelope_aad_bytes(envelope) == expected_aad
    assert envelope.aad_digest == FIXED_VECTOR_AAD_DIGEST
    assert GovernedSpatialExecutionMaterialEnvelopeV1._decode(
        envelope.ciphertext, "ciphertext_shape_invalid"
    ) == expected_ciphertext
    assert encoded == expected_envelope


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_name", "ea.governed_spatial_execution_material_envelope.v2"),
        ("contract_version", "1.0.1"),
        ("environment", "candidate"),
        ("material_identity", "material:" + "b" * 64),
        ("material_digest", "sha256:" + "0" * 64),
        ("composition_digest", "sha256:" + "0" * 64),
        ("request_digest", "sha256:" + "0" * 64),
        ("source_packet_digest", "sha256:" + "0" * 64),
        ("style_snapshot_digest", "sha256:" + "0" * 64),
        ("output_contract_digest", "sha256:" + "0" * 64),
        ("execution_target_digest", "sha256:" + "0" * 64),
        ("created_at", "2026-07-12T09:00:01Z"),
        ("retention_expires_at", "2026-07-20T09:00:01Z"),
        ("key_ref", "material-key:vector:v2"),
        ("key_epoch", 8),
        ("key_fingerprint", "sha256:" + "0" * 64),
        ("algorithm", "aes-256-gcm-v2"),
        ("nonce_encoding", "base64url-no-padding"),
        ("nonce", "CwoJCAcGBQQDAgEA"),
        ("ciphertext_encoding", "base64url-no-padding"),
        ("canonicalization", "rfc8785_jcs_bounded_no_float_v2"),
    ],
)
def test_fixed_vector_each_authenticated_envelope_member_rejects_shape_valid_mutation(
    field: str, value: object,
) -> None:
    key = bytes.fromhex(FIXED_VECTOR_KEY_HEX)
    ciphertext = base64.b64decode(FIXED_VECTOR_CIPHERTEXT_TAG_B64)
    envelope = json.loads(base64.b64decode(FIXED_VECTOR_FULL_ENVELOPE_B64))
    envelope[field] = value
    aad_payload = {
        name: member for name, member in envelope.items()
        if name not in {"ciphertext", "aad_digest"}
    }
    changed_aad = bounded_jcs(aad_payload)
    changed_nonce = base64.urlsafe_b64decode(
        envelope["nonce"] + "=" * (-len(envelope["nonce"]) % 4)
    )
    with pytest.raises(InvalidTag):
        AESGCM(key).decrypt(changed_nonce, ciphertext, changed_aad)


def test_key_registry_exact_tuple_states_validity_rotation_and_redaction(tmp_path: Path) -> None:
    with pytest.raises(SpatialMaterialStoreError, match="material_key_length_invalid"):
        _key_record(key=b"short")
    with pytest.raises(SpatialMaterialStoreError, match="material_key_fingerprint_mismatch") as failure:
        SpatialMaterialKeyRecord(
            environment="test", key_ref="material-key:test:v1", key_epoch=1,
            key_fingerprint=key_fingerprint(b"Z" * 32), key_bytes=STORE_KEY,
            state="active_encrypt_decrypt", not_before=datetime(2026, 7, 1, tzinfo=UTC),
            decrypt_until=datetime(2026, 8, 1, tzinfo=UTC),
        )
    assert STORE_KEY.hex() not in str(failure.value)
    with pytest.raises(SpatialMaterialStoreError, match="material_encrypt_key_not_unique"):
        SpatialMaterialKeyRegistry([_key_record(), _key_record(key=b"L" * 32, epoch=2)])
    for record, reason in (
        (_key_record(state="decrypt_only"), "material_encrypt_key_unavailable"),
        (_key_record(state="revoked"), "material_encrypt_key_unavailable"),
        (_key_record(not_before=STORE_NOW + timedelta(seconds=1)), "material_key_not_yet_valid"),
        (_key_record(not_before=datetime(2026, 3, 1, tzinfo=UTC)), "material_encrypt_key_rotation_overdue"),
        (_key_record(decrypt_until=datetime(2026, 7, 15, tzinfo=UTC)), "material_key_decrypt_horizon_insufficient"),
    ):
        with pytest.raises(SpatialMaterialStoreError, match=reason):
            _store(tmp_path / reason, records=[record]).seal(_material())

    root = tmp_path / "rotation"
    old_active = _key_record()
    _store(root, records=[old_active]).seal(_material())
    old_decrypt = _key_record(state="decrypt_only")
    new_active = _key_record(key=b"N" * 32, epoch=2, key_ref="material-key:test:v2")
    rotated = _store(root, records=[old_decrypt, new_active])
    assert rotated.load(DIGEST).composition_digest == DIGEST
    for records, reason in (
        ([new_active], "material_decrypt_key_unknown"),
        ([_key_record(state="revoked"), new_active], "material_decrypt_key_revoked"),
        ([_key_record(state="decrypt_only", decrypt_until=STORE_NOW - timedelta(seconds=1)), new_active],
         "material_key_decrypt_horizon_elapsed"),
    ):
        with pytest.raises(SpatialMaterialStoreError, match=reason):
            _store(root, records=records).load(DIGEST)


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "aad_digest", "request_digest", "algorithm"])
def test_material_store_rejects_envelope_ciphertext_nonce_tag_aad_and_metadata_tamper(
    tmp_path: Path, field: str,
) -> None:
    root = tmp_path / field
    store = _store(root)
    store.seal(_material())
    path = _envelope_path(root)
    payload = json.loads(path.read_text())
    if field == "ciphertext":
        raw = base64.urlsafe_b64decode(payload[field] + "=" * (-len(payload[field]) % 4))
        payload[field] = base64.urlsafe_b64encode(raw[:-1] + bytes([raw[-1] ^ 1])).decode().rstrip("=")
    elif field == "nonce":
        payload[field] = base64.urlsafe_b64encode(b"X" * 12).decode().rstrip("=")
    elif field == "aad_digest":
        payload[field] = DIGEST
    elif field == "request_digest":
        payload[field] = "sha256:" + "b" * 64
    else:
        payload[field] = "aes-128-gcm"
    path.write_bytes(bounded_jcs(payload))
    with pytest.raises(SpatialMaterialStoreError):
        store.load(DIGEST)


def test_material_store_wrong_environment_and_key_tuple_fail_before_plaintext(tmp_path: Path) -> None:
    root = tmp_path / "wrong-key"
    store = _store(root)
    store.seal(_material())
    path = _envelope_path(root)
    payload = json.loads(path.read_text())
    for field, value, reason in (
        ("environment", "candidate", "material_envelope_environment_mismatch"),
        ("key_epoch", 99, "material_decrypt_key_unknown"),
        ("key_fingerprint", key_fingerprint(b"Z" * 32), "material_decrypt_key_unknown"),
    ):
        changed = deepcopy(payload)
        changed[field] = value
        aad_payload = {key: item for key, item in changed.items() if key not in {"ciphertext", "aad_digest"}}
        changed["aad_digest"] = "sha256:" + hashlib.sha256(bounded_jcs(aad_payload)).hexdigest()
        path.write_bytes(bounded_jcs(changed))
        with pytest.raises(SpatialMaterialStoreError, match=reason):
            store.load(DIGEST)
        path.write_bytes(bounded_jcs(payload))


def test_retention_tamper_is_bound_before_durable_expiry_action(tmp_path: Path) -> None:
    root = tmp_path / "retention-tamper"
    store = _store(root)
    store.seal(_material())
    path = _envelope_path(root)
    journal = root / "material.journal.jsonl"
    payload = json.loads(path.read_text())
    payload["retention_expires_at"] = "2026-07-12T09:30:00Z"
    aad_payload = {
        key: value for key, value in payload.items() if key not in {"ciphertext", "aad_digest"}
    }
    payload["aad_digest"] = "sha256:" + hashlib.sha256(bounded_jcs(aad_payload)).hexdigest()
    tampered = bounded_jcs(payload)
    journal_before = journal.read_bytes()
    path.write_bytes(tampered)

    with pytest.raises(SpatialMaterialStoreError, match="material_envelope_substituted"):
        store.load(DIGEST)

    assert journal.read_bytes() == journal_before
    assert path.read_bytes() == tampered
    assert path.exists()
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent", "sealed"]


@pytest.mark.parametrize("key_state", ["unavailable", "revoked"])
def test_legitimate_expiry_deletes_without_decryption_key(tmp_path: Path, key_state: str) -> None:
    root = tmp_path / key_state
    _store(root).seal(_material())
    now = [datetime(2026, 7, 20, 9, 0, tzinfo=UTC)]
    records = [] if key_state == "unavailable" else [_key_record(state="revoked")]
    expired_store = SpatialExecutionMaterialStore(
        root,
        environment="test",
        keys=SpatialMaterialKeyRegistry(records),
        clock=lambda: now[0],
    )

    with pytest.raises(SpatialMaterialStoreError, match="material_retention_expired"):
        expired_store.load(DIGEST)

    assert [record["state"] for record in _journal_records(root)][-2:] == [
        "delete_tombstone", "deleted"
    ]
    assert not _envelope_path(root).exists()
    assert not _temporary_envelope_path(root).exists()


def test_store_modes_traversal_symlink_hardlink_replacement_and_permissions(tmp_path: Path) -> None:
    with pytest.raises(SpatialMaterialStoreSecurityError, match="root_invalid"):
        _store(tmp_path / "safe" / ".." / "unsafe")
    root = tmp_path / "secure"
    store = _store(root)
    store.seal(_material())
    envelope = _envelope_path(root)
    journal = root / "material.journal.jsonl"
    assert stat_mode(root) == 0o700
    assert stat_mode(envelope) == stat_mode(journal) == 0o600

    os.chmod(root, 0o755)
    with pytest.raises(SpatialMaterialStoreSecurityError, match="root_insecure"):
        store.load(DIGEST)
    os.chmod(root, 0o700)
    hardlink = root / "hardlink"
    os.link(envelope, hardlink)
    with pytest.raises(SpatialMaterialStoreSecurityError, match="file_insecure"):
        store.load(DIGEST)
    hardlink.unlink()
    original = envelope.read_bytes()
    envelope.unlink()
    envelope.symlink_to(journal.name)
    with pytest.raises(SpatialMaterialStoreSecurityError):
        store.load(DIGEST)
    envelope.unlink()
    envelope.write_bytes(original)
    os.chmod(envelope, 0o600)
    store._owner += 1
    with pytest.raises(SpatialMaterialStoreSecurityError):
        store.load(DIGEST)


def test_store_rejects_unsafe_existing_journal_mode_and_valid_envelope_substitution(tmp_path: Path) -> None:
    insecure_root = tmp_path / "insecure-journal"
    insecure_root.mkdir(mode=0o700)
    journal = insecure_root / "material.journal.jsonl"
    journal.write_bytes(b"")
    os.chmod(journal, 0o644)
    with pytest.raises(SpatialMaterialStoreSecurityError, match="file_insecure"):
        _store(insecure_root)
    assert stat_mode(journal) == 0o644

    first_root = tmp_path / "substitution-first"
    second_root = tmp_path / "substitution-second"
    first = _store(first_root)
    second = _store(second_root)
    first.seal(_material())
    second.seal(_material())
    replacement = _envelope_path(second_root).read_bytes()
    target = _envelope_path(first_root)
    target.write_bytes(replacement)
    os.chmod(target, 0o600)
    with pytest.raises(SpatialMaterialStoreError, match="envelope_substituted"):
        first.load(DIGEST)


def test_store_root_requires_canonical_absolute_path_and_rejects_symlink_ancestor(tmp_path: Path) -> None:
    with pytest.raises(SpatialMaterialStoreSecurityError, match="root_invalid"):
        _store(Path("relative-private-store"))
    with pytest.raises(SpatialMaterialStoreSecurityError, match="root_invalid"):
        _store(Path("//tmp/noncanonical-private-store"))

    physical = tmp_path / "physical"
    physical.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    with pytest.raises(SpatialMaterialStoreSecurityError, match="root_ancestor_invalid"):
        _store(alias / "store")
    assert not (physical / "store").exists()


def test_store_root_detects_ancestor_replacement_during_descriptor_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "replaceable"
    ancestor.mkdir()
    moved = tmp_path / "moved"
    real_open = os.open
    replaced = False

    def racing_open(path: object, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        nonlocal replaced
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == ancestor.name and dir_fd is not None and not replaced:
            replaced = True
            ancestor.rename(moved)
            ancestor.mkdir()
        return fd

    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(SpatialMaterialStoreSecurityError):
        _store(ancestor / "store")
    assert replaced


def test_store_root_denied_component_error_is_static_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = tmp_path / "private-account-path"
    denied.mkdir()
    real_open = os.open

    def denied_open(path: object, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if path == denied.name and dir_fd is not None:
            raise PermissionError(f"denied secret path {denied}")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", denied_open)
    with pytest.raises(SpatialMaterialStoreSecurityError) as failure:
        _store(denied / "store")
    assert str(failure.value) == "material_store_root_ancestor_invalid"
    assert str(denied) not in str(failure.value)
    assert "secret" not in str(failure.value)


def test_new_root_fsyncs_root_then_parent_before_journal_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "durable-root"
    parent_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    calls: list[tuple[int, int]] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        info = os.fstat(fd)
        calls.append((info.st_dev, info.st_ino))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    store = _store(root)
    assert calls[:2] == [store._root_identity, parent_identity]
    assert calls[2] == store._root_identity


def test_concurrent_thread_and_process_first_use_is_idempotent(tmp_path: Path) -> None:
    thread_root = tmp_path / "thread-first-use"
    with ThreadPoolExecutor(max_workers=8) as pool:
        stores = list(pool.map(lambda _: _store(thread_root), range(8)))
    assert len({store._root_identity for store in stores}) == 1
    stores[0].seal(_material())

    process_root = tmp_path / "process-first-use"
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    processes = [context.Process(target=_first_use_process, args=(str(process_root), queue)) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(120)
        assert process.exitcode == 0
    assert sorted(queue.get(timeout=10) for _ in processes) == ["ok", "ok"]
    assert _store(process_root).load(DIGEST).composition_digest == DIGEST


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


@pytest.mark.parametrize("attack", ["truncate", "prior", "sequence", "extra", "state", "substitute"])
def test_material_journal_complete_chain_validation_rejects_attacks(tmp_path: Path, attack: str) -> None:
    root = tmp_path / attack
    store = _store(root)
    store.seal(_material())
    journal = root / "material.journal.jsonl"
    raw = journal.read_bytes()
    records = _journal_records(root)
    if attack == "truncate":
        journal.write_bytes(raw[:-1])
    elif attack == "substitute":
        records[0]["material_digest"] = "sha256:" + "b" * 64
        journal.write_text("\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n")
    else:
        target = records[-1]
        if attack == "prior":
            target["prior_record_digest"] = DIGEST
        elif attack == "sequence":
            target["sequence"] = 1
        elif attack == "extra":
            target["provider_ref"] = "private"
        else:
            target["state"] = "unknown" if attack == "state" else target["state"]
        journal.write_text("\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n")
    with pytest.raises(SpatialMaterialStoreError):
        _store(root)


def test_material_journal_unhashable_state_is_static_and_redacted(tmp_path: Path) -> None:
    root = tmp_path / "unhashable-state"
    store = _store(root)
    store.seal(_material())
    records = _journal_records(root)
    secret = "credential-secret-state"
    records[-1]["state"] = [secret]
    records[-1]["record_digest"] = store._journal_digest(records[-1])
    encoded = b"".join(bounded_jcs(record) + b"\n" for record in records)
    (root / "material.journal.jsonl").write_bytes(encoded)

    with pytest.raises(SpatialMaterialStoreError) as failure:
        _store(root)

    assert str(failure.value) == "material_journal_state_invalid"
    assert secret not in str(failure.value)


def _invoke_journal_state(
    root: Path, state: str, *, journal_write: object | None = None,
    crash_hook: object | None = None,
) -> None:
    if state in {"seal_intent", "sealed"}:
        _store(
            root, journal_write=journal_write, crash_hook=crash_hook
        ).seal(_material())
        return
    store = _store(root)
    store.seal(_material())
    store._journal_write = journal_write or os.write
    store._crash_hook = crash_hook or (lambda point: None)
    store.delete(DIGEST)


def _assert_journal_state_converges(root: Path, state: str) -> None:
    restarted = _store(root)
    if state in {"seal_intent", "sealed"}:
        if state == "seal_intent":
            restarted.seal(_material())
        assert restarted.load(DIGEST).composition_digest == DIGEST
        assert _envelope_path(root).exists()
    else:
        assert restarted.delete(DIGEST).derivative_coverage == "complete"
        assert not _envelope_path(root).exists()
        assert not _temporary_envelope_path(root).exists()
    assert not (root / "material.journal.pending.json").exists()
    assert _journal_records(root)[-1]["state"] == ("sealed" if state.startswith("seal") else "deleted")


@pytest.mark.parametrize("state", ["seal_intent", "sealed", "delete_tombstone", "deleted"])
def test_pending_journal_repairs_exact_short_write_then_error(tmp_path: Path, state: str) -> None:
    root = tmp_path / state
    writer = _ShortThenErrorJournalWriter(state)
    with pytest.raises(SpatialMaterialStoreSecurityError) as failure:
        _invoke_journal_state(root, state, journal_write=writer)
    assert str(failure.value) == "material_journal_write_failed"
    pending = root / "material.journal.pending.json"
    assert pending.exists() and stat_mode(pending) == 0o600
    persisted = pending.read_bytes() + (root / "material.journal.jsonl").read_bytes()
    for fragment in (b"living", b"style-pack-v1", b"source-packet:demo-flat-v1", STORE_KEY):
        assert fragment not in persisted
    _assert_journal_state_converges(root, state)


@pytest.mark.parametrize("state", ["seal_intent", "sealed", "delete_tombstone", "deleted"])
@pytest.mark.parametrize("phase", ["before_journal_record_fsync", "after_journal_record_fsync"])
def test_pending_journal_recovers_crash_before_and_after_record_fsync(
    tmp_path: Path, state: str, phase: str,
) -> None:
    root = tmp_path / f"{state}-{phase}"
    target = f"{phase}:{state}"

    def crash(point: str) -> None:
        if point == target:
            raise RuntimeError("journal-append-interruption")

    with pytest.raises(RuntimeError, match="journal-append-interruption"):
        _invoke_journal_state(root, state, crash_hook=crash)
    assert (root / "material.journal.pending.json").exists()
    _assert_journal_state_converges(root, state)


def test_unproved_journal_truncation_still_rejects_without_pending_record(tmp_path: Path) -> None:
    root = tmp_path / "unproved"
    _store(root).seal(_material())
    journal = root / "material.journal.jsonl"
    journal.write_bytes(journal.read_bytes()[:-7])
    assert not (root / "material.journal.pending.json").exists()
    with pytest.raises(SpatialMaterialStoreError, match="material_journal_truncated"):
        _store(root)


def _prepare_journal_target(
    store: SpatialExecutionMaterialStore, directory_fd: int, journal_fd: int,
    records: list[dict[str, object]], state: str,
) -> dict[str, object]:
    identity = SpatialExecutionMaterialStore.material_identity(DIGEST)
    base = {
        "identity": identity,
        "composition_digest": DIGEST,
        "digest": DIGEST,
    }
    if state != "seal_intent":
        store._append_record(
            directory_fd, journal_fd, records, state="seal_intent", **base
        )
    if state in {"delete_tombstone", "deleted"}:
        store._append_record(
            directory_fd, journal_fd, records, state="sealed",
            envelope_digest=DIGEST, **base,
        )
    if state == "deleted":
        store._append_record(
            directory_fd, journal_fd, records, state="delete_tombstone",
            envelope_digest=DIGEST, requested_at="2026-07-12T10:00:00Z",
            observed_at="2026-07-12T10:00:00Z", **base,
        )
    target: dict[str, object] = {**base, "state": state}
    if state == "sealed":
        target["envelope_digest"] = DIGEST
    elif state in {"delete_tombstone", "deleted"}:
        target.update(
            envelope_digest=DIGEST,
            requested_at="2026-07-12T10:00:00Z",
            observed_at="2026-07-12T10:00:00Z",
        )
    return target


@pytest.mark.parametrize("state", sorted(execution_module.JOURNAL_STATES))
@pytest.mark.parametrize("boundary", ["exact", "one_over"])
def test_journal_capacity_preflight_exact_boundary_and_one_byte_over_for_every_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, boundary: str,
) -> None:
    root = tmp_path / f"capacity-{state}-{boundary}"
    store = _store(root)
    with store._journal() as (directory_fd, journal_fd, records):
        target = _prepare_journal_target(store, directory_fd, journal_fd, records, state)
        record, encoded = store._build_journal_record(records, **target)
        pre_size = os.fstat(journal_fd).st_size
        records_after = [*records, record]
        exact_max = (
            pre_size + len(encoded) + execution_module._journal_reserved_bytes(records_after)
        )
        monkeypatch.setattr(
            execution_module, "_MAX_JOURNAL_BYTES",
            exact_max if boundary == "exact" else exact_max - 1,
        )
        journal_before = (root / "material.journal.jsonl").read_bytes()
        if boundary == "exact":
            store._append_record(directory_fd, journal_fd, records, **target)
            assert os.fstat(journal_fd).st_size == pre_size + len(encoded)
            assert store._read_journal(journal_fd)[-1]["state"] == state
        else:
            with pytest.raises(SpatialMaterialStoreError, match="material_journal_capacity_exceeded"):
                store._append_record(directory_fd, journal_fd, records, **target)
            assert (root / "material.journal.jsonl").read_bytes() == journal_before
            assert store._read_journal(journal_fd) == records
        assert not (root / "material.journal.pending.json").exists()


def test_dynamic_capacity_preserves_deletion_for_multiple_live_identities_and_pending_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "dynamic-multi-identity"
    sealed = _material_variant("b")
    aborted = _material_variant("c")
    intent = _material_variant("d")
    rejected = _material_variant("e")
    old_store = _store(root)
    old_store.seal(sealed)

    def crash_after_intent(point: str) -> None:
        if point == "after_seal_intent":
            raise RuntimeError("abort-intent")

    old_store._crash_hook = crash_after_intent
    with pytest.raises(RuntimeError, match="abort-intent"):
        old_store.seal(aborted)
    _store(root)

    def crash_after_final(point: str) -> None:
        if point == "after_ciphertext_temp_unlink_fsync":
            raise RuntimeError("keyless-intent")

    with pytest.raises(RuntimeError, match="keyless-intent"):
        _store(root, crash_hook=crash_after_final).seal(intent)

    latest = {
        record["material_identity"]: record["state"] for record in _journal_records(root)
    }
    assert latest == {
        SpatialExecutionMaterialStore.material_identity(sealed["composition_digest"]): "sealed",
        SpatialExecutionMaterialStore.material_identity(aborted["composition_digest"]):
            "seal_aborted_missing_ciphertext",
        SpatialExecutionMaterialStore.material_identity(intent["composition_digest"]): "seal_intent",
    }
    journal = root / "material.journal.jsonl"
    records = _journal_records(root)
    tight_limit = journal.stat().st_size + execution_module._journal_reserved_bytes(records)
    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_BYTES", tight_limit)
    new_key = _key_record(key=b"N" * 32, epoch=2, key_ref="material-key:test:v2")
    constrained = _store(root, records=[new_key])
    journal_before = journal.read_bytes()

    with pytest.raises(SpatialMaterialStoreError, match="material_journal_capacity_exceeded"):
        constrained.seal(rejected)

    assert journal.read_bytes() == journal_before
    assert not (root / "material.journal.pending.json").exists()
    assert not _envelope_path(root, rejected).exists()

    def crash_tombstone(point: str) -> None:
        if point == "before_journal_record_fsync:delete_tombstone":
            raise RuntimeError("pending-at-capacity")

    constrained._crash_hook = crash_tombstone
    with pytest.raises(RuntimeError, match="pending-at-capacity"):
        constrained.delete(sealed["composition_digest"])
    assert (root / "material.journal.pending.json").exists()

    restarted = _store(root, records=[new_key])
    assert restarted.delete(sealed["composition_digest"]).derivative_coverage == "complete"
    assert not _envelope_path(root, sealed).exists()
    restarted = _store(root, records=[new_key])
    assert restarted.delete(aborted["composition_digest"]).derivative_coverage == "complete"
    assert not _envelope_path(root, aborted).exists()
    restarted = _store(root, records=[new_key])
    assert restarted.delete(intent["composition_digest"]).derivative_coverage == "complete"
    assert not _envelope_path(root, intent).exists()
    assert not _temporary_envelope_path(root, intent).exists()

    final_store = _store(root, records=[new_key])
    final_records = _journal_records(root)
    final_latest = {
        record["material_identity"]: record["state"] for record in final_records
    }
    assert set(final_latest.values()) == {"deleted"}
    assert len(final_latest) == 3
    assert execution_module._journal_reserved_bytes(final_records) == 0
    assert journal.stat().st_size <= tight_limit
    assert not (root / "material.journal.pending.json").exists()
    assert final_store.delete(intent["composition_digest"]).derivative_coverage == "complete"
    disk = b"".join(path.read_bytes() for path in root.iterdir() if path.is_file())
    fragments = (
        b"living", b"style-pack-v1", b"source-packet:demo-flat-v1", STORE_KEY, b"N" * 32,
    )
    for fragment in fragments:
        assert fragment not in disk


def test_automatic_intent_completion_defers_at_unexpected_capacity_but_delete_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "automatic-completion-capacity"

    def crash_after_final(point: str) -> None:
        if point == "after_ciphertext_temp_unlink_fsync":
            raise RuntimeError("leave-valid-intent")

    crashed = _store(root, crash_hook=crash_after_final)
    with pytest.raises(RuntimeError, match="leave-valid-intent"):
        crashed.seal(_material())
    records = _journal_records(root)
    assert [record["state"] for record in records] == ["seal_intent"]
    latest = records[-1]
    base = {
        "identity": latest["material_identity"],
        "composition_digest": latest["composition_digest"],
        "digest": latest["material_digest"],
    }
    _, sealed_bytes = crashed._build_journal_record(
        records, state="sealed", envelope_digest=DIGEST, **base,
    )
    requested_at = "2026-07-12T10:00:00Z"
    tombstone, tombstone_bytes = crashed._build_journal_record(
        records, state="delete_tombstone", requested_at=requested_at,
        observed_at=requested_at, **base,
    )
    _, deleted_bytes = crashed._build_journal_record(
        [*records, tombstone], state="deleted", requested_at=requested_at,
        observed_at=requested_at, **base,
    )
    current_size = (root / "material.journal.jsonl").stat().st_size
    deletion_capacity = max(
        current_size + len(tombstone_bytes) + execution_module._MAX_JOURNAL_RECORD_BYTES,
        current_size + len(tombstone_bytes) + len(deleted_bytes),
    )
    assert deletion_capacity < (
        current_size + len(sealed_bytes) + 2 * execution_module._MAX_JOURNAL_RECORD_BYTES
    )
    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_BYTES", deletion_capacity)
    journal_before = (root / "material.journal.jsonl").read_bytes()

    deferred = _store(root)

    assert (root / "material.journal.jsonl").read_bytes() == journal_before
    assert _journal_records(root)[-1]["state"] == "seal_intent"
    assert deferred.delete(DIGEST).derivative_coverage == "complete"
    assert _journal_records(root)[-1]["state"] == "deleted"
    assert not _envelope_path(root).exists()
    assert not _temporary_envelope_path(root).exists()


def test_exact_reserved_capacity_completes_seal_and_privacy_terminal_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "exact-lifecycle-capacity"
    store = _store(root)
    base = {
        "identity": SpatialExecutionMaterialStore.material_identity(DIGEST),
        "composition_digest": DIGEST,
        "digest": DIGEST,
    }
    intent, intent_bytes = store._build_journal_record([], state="seal_intent", **base)
    sealed, sealed_bytes = store._build_journal_record(
        [intent], state="sealed", envelope_digest=DIGEST, **base
    )
    tombstone, tombstone_bytes = store._build_journal_record(
        [intent, sealed], state="delete_tombstone", envelope_digest=DIGEST,
        requested_at="2026-07-12T10:00:00Z", observed_at="2026-07-12T10:00:00Z", **base,
    )
    deleted, deleted_bytes = store._build_journal_record(
        [intent, sealed, tombstone], state="deleted", envelope_digest=DIGEST,
        requested_at="2026-07-12T10:00:00Z", observed_at="2026-07-12T10:00:00Z", **base,
    )
    stages = [
        ([intent], len(intent_bytes)),
        ([intent, sealed], len(intent_bytes) + len(sealed_bytes)),
        ([intent, sealed, tombstone], len(intent_bytes) + len(sealed_bytes) + len(tombstone_bytes)),
        ([intent, sealed, tombstone, deleted],
         len(intent_bytes) + len(sealed_bytes) + len(tombstone_bytes) + len(deleted_bytes)),
    ]
    exact_capacity = max(
        size + execution_module._journal_reserved_bytes(records) for records, size in stages
    )
    monkeypatch.setattr(
        execution_module, "_MAX_JOURNAL_BYTES", exact_capacity,
    )
    with store._journal() as (directory_fd, journal_fd, records):
        store._append_record(directory_fd, journal_fd, records, state="seal_intent", **base)
        store._append_record(
            directory_fd, journal_fd, records, state="sealed", envelope_digest=DIGEST, **base
        )
        store._append_record(
            directory_fd, journal_fd, records, state="delete_tombstone", envelope_digest=DIGEST,
            requested_at="2026-07-12T10:00:00Z", observed_at="2026-07-12T10:00:00Z", **base,
        )
        store._append_record(
            directory_fd, journal_fd, records, state="deleted", envelope_digest=DIGEST,
            requested_at="2026-07-12T10:00:00Z", observed_at="2026-07-12T10:00:00Z", **base,
        )
        assert os.fstat(journal_fd).st_size <= execution_module._MAX_JOURNAL_BYTES
        assert execution_module._journal_reserved_bytes(records) == 0


def test_journal_record_bound_rejects_one_byte_over_and_pending_replays_at_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_root = tmp_path / "exact-build-bound"
    exact_store = _store(exact_root)
    with exact_store._journal() as (directory_fd, journal_fd, records):
        target = _prepare_journal_target(
            exact_store, directory_fd, journal_fd, records, "seal_intent"
        )
        _, exact_encoded = exact_store._build_journal_record(records, **target)
        monkeypatch.setattr(
            execution_module, "_MAX_JOURNAL_RECORD_BYTES", len(exact_encoded)
        )
        exact_store._append_record(directory_fd, journal_fd, records, **target)
        assert os.fstat(journal_fd).st_size == len(exact_encoded)

    build_root = tmp_path / "build-bound"
    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_RECORD_BYTES", 4096)
    store = _store(build_root)
    with store._journal() as (directory_fd, journal_fd, records):
        target = _prepare_journal_target(store, directory_fd, journal_fd, records, "seal_intent")
        _, encoded = store._build_journal_record(records, **target)
        journal_before = (build_root / "material.journal.jsonl").read_bytes()
        monkeypatch.setattr(execution_module, "_MAX_JOURNAL_RECORD_BYTES", len(encoded) - 1)
        with pytest.raises(SpatialMaterialStoreError, match="material_journal_record_too_large"):
            store._append_record(directory_fd, journal_fd, records, **target)
        assert (build_root / "material.journal.jsonl").read_bytes() == journal_before
        assert not (build_root / "material.journal.pending.json").exists()

    pending_root = tmp_path / "pending-bound"

    def crash_tombstone(point: str) -> None:
        if point == "before_journal_record_fsync:delete_tombstone":
            raise RuntimeError("pending-record-bound")

    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_RECORD_BYTES", 4096)
    with pytest.raises(RuntimeError, match="pending-record-bound"):
        _invoke_journal_state(pending_root, "delete_tombstone", crash_hook=crash_tombstone)
    pending_payload = json.loads((pending_root / "material.journal.pending.json").read_text())
    pending_encoded = GovernedSpatialExecutionMaterialEnvelopeV1._decode(
        pending_payload["record_bytes"], "pending_test_encoding_invalid"
    )
    monkeypatch.setattr(
        execution_module, "_MAX_JOURNAL_RECORD_BYTES", len(pending_encoded) - 1
    )
    bytes_before = (pending_root / "material.journal.jsonl").read_bytes()
    with pytest.raises(SpatialMaterialStoreError, match="material_journal_record_too_large"):
        _store(pending_root)
    assert (pending_root / "material.journal.jsonl").read_bytes() == bytes_before
    assert (pending_root / "material.journal.pending.json").exists()

    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_RECORD_BYTES", len(pending_encoded))
    recovered = _store(pending_root)
    assert recovered.delete(DIGEST).derivative_coverage == "complete"
    assert _journal_records(pending_root)[-1]["state"] == "deleted"
    assert not (pending_root / "material.journal.pending.json").exists()


def test_direct_journal_parser_requires_exact_lf_canonical_physical_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "direct-record-frame"
    store = _store(root)
    with store._journal() as (directory_fd, journal_fd, records):
        target = _prepare_journal_target(store, directory_fd, journal_fd, records, "seal_intent")
        record, encoded = store._build_journal_record(records, **target)

    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_RECORD_BYTES", len(encoded))
    assert store._parse_journal_bytes(encoded) == [record]
    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_RECORD_BYTES", len(encoded) - 1)
    with pytest.raises(SpatialMaterialStoreError, match="material_journal_record_too_large"):
        store._parse_journal_bytes(encoded)

    monkeypatch.setattr(execution_module, "_MAX_JOURNAL_RECORD_BYTES", 4096)
    canonical_line = encoded[:-1]
    assert len(canonical_line) < 4095
    oversized_crlf = canonical_line + b" " * (4095 - len(canonical_line)) + b"\r\n"
    assert len(oversized_crlf) == 4097
    cases = (
        ("oversized-crlf", oversized_crlf, "material_journal_record_too_large"),
        ("short-crlf", canonical_line + b"\r\n", "material_journal_record_invalid"),
        ("trailing-space", canonical_line + b" \n", "material_journal_record_invalid"),
    )
    for name, raw, reason in cases:
        case_root = tmp_path / name
        _store(case_root)
        journal = case_root / "material.journal.jsonl"
        journal.write_bytes(raw)
        os.chmod(journal, 0o600)
        with pytest.raises(SpatialMaterialStoreError, match=reason):
            _store(case_root)


@pytest.mark.parametrize("point", ["after_seal_intent", "after_ciphertext_fsync", "after_sealed"])
def test_seal_crash_recovery_and_exact_replay_repair(tmp_path: Path, point: str) -> None:
    root = tmp_path / point

    def crash(current: str) -> None:
        if current == point:
            raise RuntimeError("simulated-crash")

    with pytest.raises(RuntimeError, match="simulated-crash"):
        _store(root, crash_hook=crash).seal(_material())
    restarted = _store(root)
    states = [record["state"] for record in _journal_records(root)]
    if point == "after_seal_intent":
        assert states == ["seal_intent", "seal_aborted_missing_ciphertext"]
        repaired = restarted.seal(_material())
        assert restarted.load(DIGEST).composition_digest == repaired.composition_digest
    else:
        assert states[-1] == "sealed"
        assert restarted.load(DIGEST).composition_digest == DIGEST


@pytest.mark.parametrize(
    ("point", "temp_exists", "final_exists", "link_count"),
    [
        ("after_ciphertext_temp_fsync", True, False, 1),
        ("after_ciphertext_link_fsync", True, True, 2),
        ("after_ciphertext_temp_unlink_fsync", False, True, 1),
    ],
)
def test_internal_publication_crash_windows_recover_to_one_final_link(
    tmp_path: Path, point: str, temp_exists: bool, final_exists: bool, link_count: int,
) -> None:
    root = tmp_path / point

    def crash(current: str) -> None:
        if current == point:
            raise RuntimeError("simulated-internal-publication-crash")

    with pytest.raises(RuntimeError, match="simulated-internal-publication-crash"):
        _store(root, crash_hook=crash).seal(_material())

    temporary = _temporary_envelope_path(root)
    final = _envelope_path(root)
    assert temporary.exists() is temp_exists
    assert final.exists() is final_exists
    for path in (temporary, final):
        if path.exists():
            assert stat_mode(path) == 0o600
            assert path.stat().st_nlink == link_count
    if temp_exists and final_exists:
        assert temporary.stat().st_ino == final.stat().st_ino

    restarted = _store(root)
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent", "sealed"]
    assert not temporary.exists()
    assert final.exists()
    assert stat_mode(final) == 0o600
    assert final.stat().st_nlink == 1
    assert restarted.load(DIGEST).composition_digest == DIGEST


@pytest.mark.parametrize(
    ("point", "residue"),
    [
        ("after_ciphertext_temp_fsync", "invalid"),
        ("after_ciphertext_link_fsync", "invalid"),
        ("after_ciphertext_temp_fsync", "missing"),
    ],
)
def test_internal_publication_invalid_or_missing_residue_aborts_cleanly(
    tmp_path: Path, point: str, residue: str,
) -> None:
    root = tmp_path / f"{point}-{residue}"

    def crash(current: str) -> None:
        if current == point:
            raise RuntimeError("simulated-internal-publication-crash")

    with pytest.raises(RuntimeError):
        _store(root, crash_hook=crash).seal(_material())
    temporary = _temporary_envelope_path(root)
    final = _envelope_path(root)
    if residue == "missing":
        temporary.unlink()
    else:
        target = final if final.exists() else temporary
        target.write_bytes(b"invalid-encrypted-envelope")

    _store(root)

    assert _journal_records(root)[-1]["state"] == "seal_aborted_missing_ciphertext"
    assert not temporary.exists()
    assert not final.exists()


@pytest.mark.parametrize("publication_point", ["after_ciphertext_temp_fsync", "after_ciphertext_temp_unlink_fsync"])
@pytest.mark.parametrize("key_condition", ["unknown", "revoked", "not_yet_valid", "elapsed"])
def test_keyless_intent_recovery_defers_but_explicit_delete_tombstones_and_removes(
    tmp_path: Path, publication_point: str, key_condition: str,
) -> None:
    root = tmp_path / f"{publication_point}-{key_condition}"

    def crash(point: str) -> None:
        if point == publication_point:
            raise RuntimeError("publication-crash")

    with pytest.raises(RuntimeError):
        _store(root, crash_hook=crash).seal(_material())
    key_records = {
        "unknown": [],
        "revoked": [_key_record(state="revoked")],
        "not_yet_valid": [
            _key_record(
                state="decrypt_only", not_before=datetime(2026, 7, 12, 9, 1, tzinfo=UTC),
                decrypt_until=datetime(2026, 8, 1, tzinfo=UTC),
            )
        ],
        "elapsed": [
            _key_record(
                state="decrypt_only", decrypt_until=datetime(2026, 7, 12, 9, 30, tzinfo=UTC)
            )
        ],
    }[key_condition]
    deferred = _store(root, records=key_records)
    assert _journal_records(root)[-1]["state"] == "seal_intent"
    journal_before = (root / "material.journal.jsonl").read_bytes()
    with pytest.raises(SpatialMaterialStoreError, match="material_unavailable"):
        deferred.load(DIGEST)
    with pytest.raises(SpatialMaterialStoreError, match="material_unavailable"):
        deferred.seal(_material())
    assert (root / "material.journal.jsonl").read_bytes() == journal_before

    evidence = deferred.delete(DIGEST)
    states = [record["state"] for record in _journal_records(root)]
    assert states[-2:] == ["delete_tombstone", "deleted"]
    assert evidence.derivative_coverage == "complete"
    assert not _temporary_envelope_path(root).exists()
    assert not _envelope_path(root).exists()


def test_deferred_intent_does_not_block_keyless_delete_of_different_identity(tmp_path: Path) -> None:
    root = tmp_path / "independent-identities"
    deletable = _material_variant("b")
    blocked = _material_variant("c")
    store = _store(root)
    store.seal(deletable)

    def crash(point: str) -> None:
        if point == "after_ciphertext_temp_unlink_fsync":
            raise RuntimeError("blocked-intent")

    store._crash_hook = crash
    with pytest.raises(RuntimeError):
        store.seal(blocked)

    keyless = _store(root, records=[])
    assert keyless.delete(deletable["composition_digest"]).derivative_coverage == "complete"
    assert not _envelope_path(root, deletable).exists()
    blocked_identity = SpatialExecutionMaterialStore.material_identity(blocked["composition_digest"])
    blocked_latest = next(
        record for record in reversed(_journal_records(root))
        if record["material_identity"] == blocked_identity
    )
    assert blocked_latest["state"] == "seal_intent"
    assert _envelope_path(root, blocked).exists()


@pytest.mark.parametrize("restored_names", ["final", "temporary", "both"])
def test_deleted_tombstone_reapplies_after_restore_on_restart_and_idempotent_delete(
    tmp_path: Path, restored_names: str,
) -> None:
    root = tmp_path / restored_names
    store = _store(root)
    store.seal(_material())
    saved = _envelope_path(root).read_bytes()
    first = store.delete(DIGEST)
    final = _envelope_path(root)
    temporary = _temporary_envelope_path(root)

    def restore() -> None:
        if restored_names in {"final", "both"}:
            final.write_bytes(saved)
            os.chmod(final, 0o600)
        if restored_names in {"temporary", "both"}:
            temporary.write_bytes(saved)
            os.chmod(temporary, 0o600)

    restore()
    restarted = _store(root, records=[])
    assert not final.exists() and not temporary.exists()
    restore()
    second = restarted.delete(DIGEST)
    assert not final.exists() and not temporary.exists()
    assert second == first


@pytest.mark.parametrize("attack", ["missing", "altered", "wrong_mode", "substituted"])
def test_restart_rejects_missing_or_untrusted_latest_sealed_envelope(tmp_path: Path, attack: str) -> None:
    root = tmp_path / f"sealed-{attack}"
    _store(root).seal(_material())
    final = _envelope_path(root)
    if attack == "missing":
        final.unlink()
    elif attack == "altered":
        final.write_bytes(b"altered-envelope")
    elif attack == "wrong_mode":
        os.chmod(final, 0o644)
    else:
        donor = tmp_path / "sealed-donor"
        _store(donor).seal(_material())
        final.write_bytes(_envelope_path(donor).read_bytes())
        os.chmod(final, 0o600)

    with pytest.raises(SpatialMaterialStoreError):
        _store(root, records=[], retention_resolver=None)


@pytest.mark.parametrize("key_state", ["unknown", "revoked"])
def test_restart_verifies_intact_sealed_without_key_then_allows_privacy_delete(
    tmp_path: Path, key_state: str,
) -> None:
    root = tmp_path / f"sealed-keyless-{key_state}"
    _store(root).seal(_material())
    records = [] if key_state == "unknown" else [_key_record(state="revoked")]
    restarted = _store(root, records=records, retention_resolver=None)
    assert restarted.delete(DIGEST).derivative_coverage == "complete"
    assert not _envelope_path(root).exists()
    assert not _temporary_envelope_path(root).exists()


@pytest.mark.parametrize(
    ("names", "posture"),
    [
        ("final", "regular"), ("temporary", "regular"), ("both", "regular"),
        ("final", "wrong_mode"), ("temporary", "wrong_mode"),
        ("both", "wrong_mode"),
        ("final", "symlink"), ("temporary", "symlink"), ("both", "symlink"),
    ],
)
def test_terminal_abort_removes_restored_names_then_exact_replay_converges(
    tmp_path: Path, names: str, posture: str,
) -> None:
    root = tmp_path / f"aborted-{names}-{posture}"

    def crash(point: str) -> None:
        if point == "after_seal_intent":
            raise RuntimeError("intent-only")

    with pytest.raises(RuntimeError):
        _store(root, crash_hook=crash).seal(_material())
    _store(root)
    assert _journal_records(root)[-1]["state"] == "seal_aborted_missing_ciphertext"

    donor = tmp_path / f"donor-{names}-{posture}"
    _store(donor).seal(_material())
    donor_file = _envelope_path(donor)
    final = _envelope_path(root)
    temporary = _temporary_envelope_path(root)
    targets = [final, temporary] if names == "both" else [final if names == "final" else temporary]
    for target in targets:
        if posture == "symlink":
            target.symlink_to(donor_file)
        else:
            target.write_bytes(donor_file.read_bytes())
            os.chmod(target, 0o644 if posture == "wrong_mode" else 0o600)

    restarted = _store(root, records=[], retention_resolver=lambda material: _as_test_datetime(material.retention_expires_at))
    assert donor_file.exists()
    assert not final.exists() and not temporary.exists()
    restarted.keys = SpatialMaterialKeyRegistry([_key_record()])
    repaired = restarted.seal(_material())
    assert restarted.load(DIGEST).composition_digest == repaired.composition_digest


def _as_test_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.parametrize("names", ["final", "temporary", "both"])
@pytest.mark.parametrize("posture", ["wrong_mode", "symlink", "extra_link"])
def test_deleted_tombstone_unlinks_restored_names_regardless_safe_unlink_posture(
    tmp_path: Path, names: str, posture: str,
) -> None:
    root = tmp_path / f"deleted-{names}-{posture}"
    store = _store(root)
    store.seal(_material())
    saved = _envelope_path(root).read_bytes()
    first = store.delete(DIGEST)
    final = _envelope_path(root)
    temporary = _temporary_envelope_path(root)
    donor = tmp_path / f"deleted-donor-{names}-{posture}"
    donor.write_bytes(saved)
    targets = [final, temporary] if names == "both" else [final if names == "final" else temporary]
    external_links: list[Path] = []

    def restore(phase: str) -> None:
        for index, target in enumerate(targets):
            if posture == "symlink":
                target.symlink_to(donor)
            else:
                target.write_bytes(saved)
                os.chmod(target, 0o644 if posture == "wrong_mode" else 0o600)
                if posture == "extra_link":
                    external = root / f"external-{phase}-{index}"
                    os.link(target, external)
                    external_links.append(external)

    restore("restart")
    restarted = _store(root, records=[], retention_resolver=None)
    assert donor.exists()
    assert not final.exists() and not temporary.exists()
    restore("retry")
    second = restarted.delete(DIGEST)
    assert second == first
    assert not final.exists() and not temporary.exists()
    assert all(path.exists() for path in external_links)


@pytest.mark.parametrize("name", ["final", "temporary"])
def test_terminal_absence_never_recursively_removes_expected_name_directory(
    tmp_path: Path, name: str,
) -> None:
    root = tmp_path / f"terminal-directory-{name}"
    store = _store(root)
    store.seal(_material())
    store.delete(DIGEST)
    target = _envelope_path(root) if name == "final" else _temporary_envelope_path(root)
    target.mkdir()
    marker = target / "must-remain"
    marker.write_text("private")
    with pytest.raises(SpatialMaterialStoreSecurityError, match="material_terminal_path_directory"):
        _store(root, records=[], retention_resolver=None)
    assert marker.exists()
    with pytest.raises(SpatialMaterialStoreSecurityError, match="material_terminal_path_directory"):
        store.delete(DIGEST)
    assert marker.exists()


def test_invalid_recovery_bytes_are_removed_and_aborted(tmp_path: Path) -> None:
    root = tmp_path / "invalid-recovery"

    def crash(point: str) -> None:
        if point == "after_ciphertext_fsync":
            raise RuntimeError("simulated-crash")

    with pytest.raises(RuntimeError):
        _store(root, crash_hook=crash).seal(_material())
    path = _envelope_path(root)
    path.write_bytes(b"not-an-envelope")
    _store(root)
    assert not path.exists()
    assert _journal_records(root)[-1]["state"] == "seal_aborted_missing_ciphertext"


def test_write_once_concurrency_idempotency_and_same_identity_conflict(tmp_path: Path) -> None:
    root = tmp_path / "concurrent"
    store = _store(root)
    with ThreadPoolExecutor(max_workers=8) as pool:
        envelopes = list(pool.map(lambda _: store.seal(_material()), range(16)))
    assert len({envelope.ciphertext for envelope in envelopes}) == 1
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent", "sealed"]

    changed = _material()
    changed["normalized_request"]["callback"]["product_event_ref"] = "event:changed"  # type: ignore[index]
    _refresh_material_lineage(changed)
    with pytest.raises(SpatialMaterialStoreError, match="write_conflict"):
        store.seal(changed)


@pytest.mark.parametrize("point", ["after_delete_tombstone", "after_ciphertext_unlink", "after_deleted"])
def test_delete_crash_recovery_tombstone_precedence_and_idempotency(tmp_path: Path, point: str) -> None:
    root = tmp_path / point

    def crash(current: str) -> None:
        if current == point:
            raise RuntimeError("simulated-crash")

    store = _store(root)
    store.seal(_material())
    temporary = _temporary_envelope_path(root)
    temporary.write_bytes(_envelope_path(root).read_bytes())
    os.chmod(temporary, 0o600)
    store._crash_hook = crash
    with pytest.raises(RuntimeError):
        store.delete(DIGEST)
    restarted = _store(root)
    assert _journal_records(root)[-1]["state"] == "deleted"
    assert not _envelope_path(root).exists()
    assert not temporary.exists()
    with pytest.raises(SpatialMaterialStoreError, match="tombstoned"):
        restarted.load(DIGEST)
    with pytest.raises(SpatialMaterialStoreError, match="tombstoned"):
        restarted.seal(_material())
    first = restarted.delete(DIGEST)
    second = restarted.delete(DIGEST)
    assert first == second


def test_backward_clock_is_clamped_and_idempotent_deletion_evidence_remains_stable(tmp_path: Path) -> None:
    root = tmp_path / "backward-clock"
    store = _store(root)
    store.seal(_material())
    moments = iter(
        [
            datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 12, 10, 1, tzinfo=UTC),
            datetime(2026, 7, 12, 9, 59, tzinfo=UTC),
        ]
    )
    store._clock = lambda: next(moments)
    first = store.delete(DIGEST)
    records = _journal_records(root)
    tombstone, deleted = records[-2:]
    assert deleted["observed_at"] == tombstone["observed_at"]
    assert first.ciphertext_deleted_at == first.tombstoned_at

    stable = _store(root, records=[], now=[datetime(2026, 7, 12, 10, 2, tzinfo=UTC)])
    second = stable.delete(DIGEST)
    assert second == first


def test_delete_uses_one_operation_instant_when_clock_rolls_back_before_tombstone(tmp_path: Path) -> None:
    root = tmp_path / "rollback-before-tombstone"
    store = _store(root)
    store.seal(_material())
    calls = 0

    def rollback_clock() -> datetime:
        nonlocal calls
        calls += 1
        return (
            datetime(2026, 7, 12, 11, 0, tzinfo=UTC)
            if calls == 1
            else datetime(2026, 7, 12, 9, 0, tzinfo=UTC)
        )

    store._clock = rollback_clock
    first = store.delete(DIGEST)
    assert calls == 1
    assert first.requested_at == first.tombstoned_at == first.ciphertext_deleted_at
    assert first.requested_at == "2026-07-12T11:00:00Z"

    restarted = _store(root, records=[], now=[datetime(2026, 7, 12, 11, 1, tzinfo=UTC)])
    assert restarted.delete(DIGEST) == first


def test_restart_clamps_deleted_to_tombstone_operation_instant_after_clock_rollback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rollback-between-records"
    store = _store(root)
    store.seal(_material())
    store._clock = lambda: datetime(2026, 7, 12, 11, 0, tzinfo=UTC)

    def crash(point: str) -> None:
        if point == "after_delete_tombstone":
            raise RuntimeError("after-tombstone")

    store._crash_hook = crash
    with pytest.raises(RuntimeError, match="after-tombstone"):
        store.delete(DIGEST)
    assert _journal_records(root)[-1]["state"] == "delete_tombstone"

    restarted = _store(root, records=[], now=[datetime(2026, 7, 12, 9, 0, tzinfo=UTC)])
    tombstone, deleted = _journal_records(root)[-2:]
    assert tombstone["observed_at"] == deleted["observed_at"] == "2026-07-12T11:00:00Z"
    evidence = restarted.delete(DIGEST)
    assert evidence.requested_at == evidence.tombstoned_at == evidence.ciphertext_deleted_at
    assert restarted.delete(DIGEST) == evidence


def test_journal_rejects_requested_at_after_observed_even_with_valid_hash_chain(tmp_path: Path) -> None:
    root = tmp_path / "invalid-request-chronology"
    _store(root).seal(_material())
    records = _journal_records(root)
    identity = records[-1]["material_identity"]
    record = {
        "sequence": len(records) + 1,
        "prior_record_digest": records[-1]["record_digest"],
        "record_digest": "",
        "operation_id": f"material-operation:{len(records) + 1}",
        "state": "delete_tombstone",
        "material_identity": identity,
        "composition_digest": records[-1]["composition_digest"],
        "material_digest": records[-1]["material_digest"],
        "envelope_digest": records[-1]["envelope_digest"],
        "requested_at": "2026-07-12T11:00:00Z",
        "observed_at": "2026-07-12T10:00:00Z",
    }
    record["record_digest"] = SpatialExecutionMaterialStore._journal_digest(record)
    with (root / "material.journal.jsonl").open("ab") as journal:
        journal.write(bounded_jcs(record) + b"\n")
    with pytest.raises(SpatialMaterialStoreError, match="requested_at_after_observed"):
        _store(root, records=[])


def test_deletion_projection_failure_is_static_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projection-redaction"
    store = _store(root)
    store.seal(_material())

    def fail_projection(*args: object, **kwargs: object) -> object:
        raise ValueError("credential private path")

    monkeypatch.setattr(PropertyDeletionEvidenceProjectionV1, "model_validate", fail_projection)
    with pytest.raises(SpatialMaterialStoreError) as failure:
        store.delete(DIGEST)
    assert str(failure.value) == "material_deletion_projection_invalid"
    assert "credential" not in str(failure.value)


def test_expiry_tombstones_before_unlink_and_retention_clock_is_fixed(tmp_path: Path) -> None:
    now = [STORE_NOW]
    root = tmp_path / "expiry"
    store = _store(root, now=now)
    store.seal(_material())
    temporary = _temporary_envelope_path(root)
    temporary.write_bytes(_envelope_path(root).read_bytes())
    os.chmod(temporary, 0o600)
    now[0] = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
    with pytest.raises(SpatialMaterialStoreError, match="retention_expired"):
        store.load(DIGEST)
    assert [record["state"] for record in _journal_records(root)][-2:] == ["delete_tombstone", "deleted"]
    assert not _envelope_path(root).exists()
    assert not temporary.exists()
    expiry = fixed_material_retention_expiry(
        source_packet_created_at=datetime(2026, 7, 2, tzinfo=UTC),
        compose_acceptance_at=datetime(2026, 7, 3, tzinfo=UTC),
        policy_expires_at=datetime(2026, 8, 30, tzinfo=UTC),
        shorter_deadlines=(datetime(2026, 7, 10, tzinfo=UTC),),
    )
    assert expiry == datetime(2026, 7, 10, tzinfo=UTC)


def test_new_seal_requires_verified_retention_with_zero_durable_action_when_unavailable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "unavailable-retention"
    store = _store(root, retention_resolver=None)
    journal_before = (root / "material.journal.jsonl").read_bytes()
    with pytest.raises(SpatialMaterialStoreError, match="material_retention_verifier_unavailable"):
        store.seal(_material())
    assert (root / "material.journal.jsonl").read_bytes() == journal_before == b""
    assert not _envelope_path(root).exists()
    assert not _temporary_envelope_path(root).exists()


@pytest.mark.parametrize(
    ("deadline_class", "policy_expiry", "shorter_deadline"),
    [
        ("policy", datetime(2026, 7, 25, tzinfo=UTC), None),
        ("rights", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 7, 24, tzinfo=UTC)),
        ("consent", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 7, 23, tzinfo=UTC)),
        ("takedown", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 7, 22, tzinfo=UTC)),
        ("privacy", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 7, 21, tzinfo=UTC)),
    ],
)
def test_verified_retention_binds_policy_and_every_shorter_deadline_class(
    tmp_path: Path, deadline_class: str, policy_expiry: datetime,
    shorter_deadline: datetime | None,
) -> None:
    material = _material_variant("b")
    expected = fixed_material_retention_expiry(
        source_packet_created_at=datetime(2026, 7, 12, 8, 30, tzinfo=UTC),
        compose_acceptance_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
        policy_expires_at=policy_expiry,
        shorter_deadlines=() if shorter_deadline is None else (shorter_deadline,),
    )
    material["retention_expires_at"] = expected.isoformat().replace("+00:00", "Z")
    key = _key_record(decrypt_until=datetime(2026, 10, 1, tzinfo=UTC))
    store = _store(
        tmp_path / deadline_class, records=[key], retention_resolver=lambda parsed: expected
    )
    envelope = store.seal(material)
    assert envelope.retention_expires_at == material["retention_expires_at"]


def test_verified_retention_exact_source_anchor_ceiling_and_defective_verifier_rejection(
    tmp_path: Path,
) -> None:
    ceiling = datetime(2026, 8, 11, 8, 30, tzinfo=UTC)
    exact = _material_variant("b")
    exact["retention_expires_at"] = ceiling.isoformat().replace("+00:00", "Z")
    long_key = _key_record(decrypt_until=datetime(2026, 10, 1, tzinfo=UTC))
    assert _store(
        tmp_path / "exact", records=[long_key], retention_resolver=lambda material: ceiling
    ).seal(exact).retention_expires_at == "2026-08-11T08:30:00Z"

    overlong = _material_variant("c")
    overlong_expiry = datetime(2026, 8, 11, 8, 30, 1, tzinfo=UTC)
    overlong["retention_expires_at"] = overlong_expiry.isoformat().replace("+00:00", "Z")
    rejected_root = tmp_path / "overlong"
    rejected = _store(
        rejected_root, records=[long_key], retention_resolver=lambda material: overlong_expiry
    )
    with pytest.raises(SpatialMaterialStoreError, match="material_retention_ceiling_exceeded"):
        rejected.seal(overlong)
    assert _journal_records(rejected_root) == []
    assert not _envelope_path(rejected_root, overlong).exists()


def test_retention_replay_rotation_load_and_delete_never_reset_deadline(tmp_path: Path) -> None:
    root = tmp_path / "no-reset"
    material = _material_variant("b")
    expected = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
    old = _key_record()
    first = _store(root, records=[old], retention_resolver=lambda parsed: expected)
    original = first.seal(material)
    journal_before = (root / "material.journal.jsonl").read_bytes()

    rotated = _store(
        root,
        records=[
            _key_record(state="decrypt_only"),
            _key_record(key=b"N" * 32, epoch=2, key_ref="material-key:test:v2"),
        ],
        retention_resolver=None,
    )
    replay = rotated.seal(material)
    assert replay.retention_expires_at == original.retention_expires_at
    assert (root / "material.journal.jsonl").read_bytes() == journal_before
    assert rotated.load(material["composition_digest"]).retention_expires_at == material["retention_expires_at"]
    assert rotated.delete(material["composition_digest"]).derivative_coverage == "complete"


def test_private_store_recursive_disk_scan_contains_no_plaintext_or_key_and_actions_stay_zero(
    tmp_path: Path,
) -> None:
    root = tmp_path / "no-plaintext"
    actions = {
        name: 0 for name in (
            "network", "provider", "account", "quota", "runtime", "render", "browser",
            "deploy", "publication", "telegram", "credential",
        )
    }
    store = _store(root)
    store.seal(_material())
    disk = bytearray()
    for directory, _, filenames in os.walk(root):
        for filename in filenames:
            disk.extend((Path(directory) / filename).read_bytes())
    for fragment in (b"living", b"style-pack-v1", b"source-packet:demo-flat-v1", STORE_KEY):
        assert fragment not in disk
    assert all(count == 0 for count in actions.values())


@pytest.mark.parametrize("policy_condition", ["stale", "revoked", "digest_mismatched"])
def test_guarded_restart_after_intent_without_ciphertext_never_recovers_before_retention_authority(
    tmp_path: Path, policy_condition: str,
) -> None:
    root = tmp_path / f"guarded-missing-{policy_condition}"
    ledger = DurableSpatialLedger(tmp_path / f"ledger-{policy_condition}")

    def crash(point: str) -> None:
        if point == "after_seal_intent":
            raise RuntimeError("intent-only-crash")

    store = _store(
        root,
        crash_hook=crash,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(RuntimeError, match="intent-only-crash"):
            store.seal(_material(), lifecycle_guard=lifecycle_guard)
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent"]
    assert not _envelope_path(root).exists()

    verifier_calls: list[str] = []

    def blocked_retention(_material_value: object) -> datetime:
        verifier_calls.append(policy_condition)
        raise SpatialMaterialStoreError("material_retention_verification_failed")

    restarted = _store(
        root,
        records=[],
        retention_resolver=blocked_retention,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    assert verifier_calls == []
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent"]
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(
            SpatialMaterialStoreError, match="material_retention_verification_failed"
        ):
            restarted.recover_pending_intent(
                _material(), lifecycle_guard=lifecycle_guard
            )
    assert verifier_calls == [policy_condition]
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent"]
    assert not _envelope_path(root).exists()


def test_guarded_restart_with_published_ciphertext_defers_all_resolution_until_explicit_authority(
    tmp_path: Path,
) -> None:
    root = tmp_path / "guarded-published"
    ledger = DurableSpatialLedger(tmp_path / "guarded-published-ledger")

    def crash(point: str) -> None:
        if point == "after_ciphertext_temp_unlink_fsync":
            raise RuntimeError("published-intent-crash")

    store = _store(
        root,
        crash_hook=crash,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(RuntimeError, match="published-intent-crash"):
            store.seal(_material(), lifecycle_guard=lifecycle_guard)
    assert _envelope_path(root).exists()
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent"]

    verifier_calls: list[str] = []

    def blocked_retention(_material_value: object) -> datetime:
        verifier_calls.append("blocked")
        raise SpatialMaterialStoreError("material_retention_verification_failed")

    restarted = _store(
        root,
        records=[],
        retention_resolver=blocked_retention,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    assert verifier_calls == []
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent"]
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(
            SpatialMaterialStoreError, match="material_retention_verification_failed"
        ):
            restarted.recover_pending_intent(
                _material(), lifecycle_guard=lifecycle_guard
            )
    assert verifier_calls == ["blocked"]
    assert _envelope_path(root).exists()
    assert [record["state"] for record in _journal_records(root)] == ["seal_intent"]


def test_guarded_privacy_tombstone_preempts_valid_intent_without_appending_sealed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "guarded-privacy-precedence"
    ledger = DurableSpatialLedger(tmp_path / "guarded-privacy-ledger")

    def crash(point: str) -> None:
        if point == "after_ciphertext_temp_unlink_fsync":
            raise RuntimeError("leave-valid-ciphertext")

    store = _store(
        root,
        crash_hook=crash,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    material = _material()
    digest = material_digest(material)
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(RuntimeError, match="leave-valid-ciphertext"):
            store.seal(material, lifecycle_guard=lifecycle_guard)
    ledger.record_privacy_action(
        scope_digest=DIGEST,
        action="deleted",
        reason_digest=DIGEST,
        observed_at=STORE_NOW,
    )

    restarted = _store(
        root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        assert lifecycle_guard.privacy_status is not None
        evidence = restarted.preemptive_tombstone(
            DIGEST,
            digest,
            lifecycle_guard=lifecycle_guard,
        )
    assert evidence.derivative_coverage == "complete"
    assert [record["state"] for record in _journal_records(root)] == [
        "seal_intent",
        "delete_tombstone",
        "deleted",
    ]
    assert not _envelope_path(root).exists()
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_lifecycle_privacy_tombstone_active",
        ):
            restarted.recover_pending_intent(material, lifecycle_guard=lifecycle_guard)


def test_guarded_preemptive_tombstone_without_history_permanently_blocks_exact_seal_and_repair(
    tmp_path: Path,
) -> None:
    root = tmp_path / "guarded-preemptive-absent"
    ledger = DurableSpatialLedger(tmp_path / "guarded-preemptive-ledger")
    store = _store(
        root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    material = _material()
    digest = material_digest(material)

    ledger.record_privacy_action(
        scope_digest=DIGEST,
        action="deleted",
        reason_digest=DIGEST,
        observed_at=STORE_NOW,
    )

    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        evidence = store.preemptive_tombstone(
            DIGEST,
            digest,
            lifecycle_guard=lifecycle_guard,
        )
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_lifecycle_privacy_tombstone_active",
        ):
            store.seal(material, lifecycle_guard=lifecycle_guard)
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_lifecycle_privacy_tombstone_active",
        ):
            store.recover_pending_intent(material, lifecycle_guard=lifecycle_guard)
    assert evidence.derivative_coverage == "complete"
    assert [record["state"] for record in _journal_records(root)] == [
        "delete_tombstone",
        "deleted",
    ]
    assert not _envelope_path(root).exists()


def test_guarded_exact_replay_repairs_aborted_intent_without_resetting_retention(
    tmp_path: Path,
) -> None:
    root = tmp_path / "guarded-repair"
    ledger = DurableSpatialLedger(tmp_path / "guarded-repair-ledger")
    material = _material()

    def crash(point: str) -> None:
        if point == "after_seal_intent":
            raise RuntimeError("repairable-intent")

    store = _store(
        root,
        crash_hook=crash,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(RuntimeError, match="repairable-intent"):
            store.seal(material, lifecycle_guard=lifecycle_guard)

    restarted = _store(
        root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        recovery = restarted.recover_pending_intent(
            material, lifecycle_guard=lifecycle_guard
        )
        assert recovery["state"] == "seal_aborted_missing_ciphertext"
        restarted.seal(material, lifecycle_guard=lifecycle_guard)
        loaded = restarted.load(DIGEST, lifecycle_guard=lifecycle_guard)
    assert loaded.retention_expires_at == material["retention_expires_at"]
    journal_before = (root / "material.journal.jsonl").read_bytes()

    replayed = _store(
        root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        recovery = replayed.recover_pending_intent(
            material, lifecycle_guard=lifecycle_guard
        )
        assert recovery["state"] == "sealed"
        replayed.seal(material, lifecycle_guard=lifecycle_guard)
        loaded_again = replayed.load(DIGEST, lifecycle_guard=lifecycle_guard)
    assert loaded_again.retention_expires_at == material["retention_expires_at"]
    assert (root / "material.journal.jsonl").read_bytes() == journal_before


def test_guarded_store_requires_active_matching_ledger_lifecycle_guard(tmp_path: Path) -> None:
    material = _material()
    with pytest.raises(
        SpatialMaterialStoreError, match="material_lifecycle_authority_required"
    ):
        _store(tmp_path / "guard-required", authority_guarded_recovery=True)
    ledger = DurableSpatialLedger(tmp_path / "guard-required-ledger")
    store = _store(
        tmp_path / "guard-required",
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with pytest.raises(SpatialMaterialStoreError, match="material_lifecycle_guard_required"):
        store.seal(material)
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        pass
    with pytest.raises(SpatialMaterialStoreError, match="material_lifecycle_guard_invalid"):
        store.seal(material, lifecycle_guard=lifecycle_guard)


def test_lifecycle_guard_updates_for_same_thread_privacy_and_only_allows_strict_tombstone(
    tmp_path: Path,
) -> None:
    ledger = DurableSpatialLedger(tmp_path / "same-thread-privacy-ledger")
    store = _store(
        tmp_path / "same-thread-privacy-store",
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    material = _material()
    digest = material_digest(material)
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        assert lifecycle_guard.privacy_status is None
        ledger.record_privacy_action(
            scope_digest=DIGEST,
            action="deleted",
            reason_digest=DIGEST,
            observed_at=STORE_NOW,
        )
        assert lifecycle_guard.privacy_status is not None
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_lifecycle_privacy_tombstone_active",
        ):
            store.seal(material, lifecycle_guard=lifecycle_guard)
        evidence = store.preemptive_tombstone(
            DIGEST,
            digest,
            lifecycle_guard=lifecycle_guard,
        )
    assert evidence.derivative_coverage == "complete"
    assert [record["state"] for record in _journal_records(store.root)] == [
        "delete_tombstone",
        "deleted",
    ]


def test_lifecycle_guard_holds_cross_process_lock_until_scope_exit(tmp_path: Path) -> None:
    root = tmp_path / "cross-process-lifecycle-ledger"
    ledger = DurableSpatialLedger(root)
    context = multiprocessing.get_context("spawn")
    started = context.Queue()
    acquired = context.Queue()
    process = context.Process(
        target=_lifecycle_guard_process,
        args=(str(root), DIGEST, started, acquired),
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST):
        process.start()
        assert started.get(timeout=5) == "started"
        with pytest.raises(queue.Empty):
            acquired.get(timeout=0.2)
    assert acquired.get(timeout=5) == "acquired"
    process.join(timeout=5)
    assert process.exitcode == 0


def test_guarded_pending_sealed_append_is_deferred_and_privacy_discards_it_before_tombstone(
    tmp_path: Path,
) -> None:
    root = tmp_path / "guarded-pending-sealed"
    ledger = DurableSpatialLedger(tmp_path / "guarded-pending-sealed-ledger")
    material = _material()
    digest = material_digest(material)

    def crash_publication(point: str) -> None:
        if point == "after_ciphertext_temp_unlink_fsync":
            raise RuntimeError("published-intent")

    store = _store(
        root,
        crash_hook=crash_publication,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(RuntimeError, match="published-intent"):
            store.seal(material, lifecycle_guard=lifecycle_guard)

    def crash_sealed_append(point: str) -> None:
        if point == "before_journal_record_fsync:sealed":
            raise RuntimeError("sealed-append-interrupted")

    store._crash_hook = crash_sealed_append
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(RuntimeError, match="sealed-append-interrupted"):
            store.recover_pending_intent(material, lifecycle_guard=lifecycle_guard)
    assert (root / "material.journal.pending.json").exists()
    journal_before = (root / "material.journal.jsonl").read_bytes()
    pending_before = (root / "material.journal.pending.json").read_bytes()

    def blocked_retention(_material_value: object) -> datetime:
        raise SpatialMaterialStoreError("material_retention_verification_failed")

    blocked = _store(
        root,
        records=[],
        retention_resolver=blocked_retention,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_retention_verification_failed",
        ):
            blocked.recover_pending_intent(
                material,
                lifecycle_guard=lifecycle_guard,
            )
    assert (root / "material.journal.jsonl").read_bytes() == journal_before
    assert (root / "material.journal.pending.json").read_bytes() == pending_before

    restarted = _store(
        root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_journal_pending_authority_required",
        ):
            restarted.load(DIGEST, lifecycle_guard=lifecycle_guard)
    ledger.record_privacy_action(
        scope_digest=DIGEST,
        action="deleted",
        reason_digest=DIGEST,
        observed_at=STORE_NOW,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        deletion = restarted.preemptive_tombstone(
            DIGEST,
            digest,
            lifecycle_guard=lifecycle_guard,
        )
    assert deletion.derivative_coverage == "complete"
    assert not (root / "material.journal.pending.json").exists()
    assert [record["state"] for record in _journal_records(root)] == [
        "seal_intent",
        "delete_tombstone",
        "deleted",
    ]
    assert not _envelope_path(root).exists()


def test_guarded_store_rejects_wrong_ledger_authority_before_any_material_effect(
    tmp_path: Path,
) -> None:
    material_root = tmp_path / "authority-bound-store"
    ledger_root = tmp_path / "authority-ledger-a"
    ledger_a = DurableSpatialLedger(ledger_root)
    ledger_a.record_privacy_action(
        scope_digest=DIGEST,
        action="deleted",
        reason_digest=DIGEST,
        observed_at=STORE_NOW,
    )
    ledger_b = DurableSpatialLedger(tmp_path / "authority-ledger-b-empty")
    same_root_ledger = DurableSpatialLedger(ledger_root)
    store = _store(
        material_root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger_a.lifecycle_authority,
    )
    material = _material()
    digest = material_digest(material)

    with ledger_b.composition_privacy_lifecycle_guard(DIGEST) as wrong_guard:
        operations = (
            lambda: store.seal(material, lifecycle_guard=wrong_guard),
            lambda: store.load(DIGEST, lifecycle_guard=wrong_guard),
            lambda: store.recover_pending_intent(material, lifecycle_guard=wrong_guard),
            lambda: store.delete(DIGEST, lifecycle_guard=wrong_guard),
            lambda: store.preemptive_tombstone(
                DIGEST, digest, lifecycle_guard=wrong_guard
            ),
        )
        for operation in operations:
            with pytest.raises(
                SpatialMaterialStoreError, match="material_lifecycle_guard_invalid"
            ):
                operation()

    with same_root_ledger.composition_privacy_lifecycle_guard(DIGEST) as wrong_guard:
        assert wrong_guard.privacy_status is not None
        with pytest.raises(
            SpatialMaterialStoreError, match="material_lifecycle_guard_invalid"
        ):
            store.preemptive_tombstone(
                DIGEST, digest, lifecycle_guard=wrong_guard
            )

    assert ledger_a.privacy_status(DIGEST) is not None
    assert ledger_b.privacy_status(DIGEST) is None
    assert not (material_root / "material.journal.jsonl").exists()
    assert not _envelope_path(material_root).exists()


def test_guarded_preemptive_tombstone_requires_authoritative_privacy_receipt(
    tmp_path: Path,
) -> None:
    ledger = DurableSpatialLedger(tmp_path / "empty-privacy-ledger")
    root = tmp_path / "empty-privacy-store"
    store = _store(
        root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        assert lifecycle_guard.privacy_status is None
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_lifecycle_privacy_tombstone_required",
        ):
            store.preemptive_tombstone(
                DIGEST,
                material_digest(_material()),
                lifecycle_guard=lifecycle_guard,
            )
    assert not (root / "material.journal.jsonl").exists()
    assert not _envelope_path(root).exists()


@pytest.mark.parametrize(
    ("composition_digest", "material_digest_value"),
    [("not-a-digest", DIGEST), (DIGEST, "sha256:short")],
)
def test_preemptive_tombstone_malformed_digests_are_static_and_zero_effect(
    tmp_path: Path,
    composition_digest: str,
    material_digest_value: str,
) -> None:
    ledger = DurableSpatialLedger(tmp_path / "malformed-binding-ledger")
    ledger.record_privacy_action(
        scope_digest=DIGEST,
        action="deleted",
        reason_digest=DIGEST,
        observed_at=STORE_NOW,
    )
    root = tmp_path / "malformed-binding-store"
    store = _store(
        root,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(
            SpatialMaterialStoreError,
            match="^material_preemptive_tombstone_binding_invalid$",
        ):
            store.preemptive_tombstone(
                composition_digest,
                material_digest_value,
                lifecycle_guard=lifecycle_guard,
            )
    assert not (root / "material.journal.jsonl").exists()
    assert not _envelope_path(root).exists()


def test_preemptive_tombstone_preserves_privacy_recorded_at_across_clock_rollback(
    tmp_path: Path,
) -> None:
    requested_at = STORE_NOW - timedelta(hours=2)
    current = [requested_at - timedelta(hours=1)]
    ledger = DurableSpatialLedger(tmp_path / "privacy-request-anchor-ledger")
    privacy = ledger.record_privacy_action(
        scope_digest=DIGEST,
        action="deleted",
        reason_digest=DIGEST,
        observed_at=requested_at,
    )
    root = tmp_path / "privacy-request-anchor-store"
    store = _store(
        root,
        now=current,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    digest = material_digest(_material())
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        with pytest.raises(
            SpatialMaterialStoreError,
            match="material_preemptive_tombstone_request_mismatch",
        ):
            store.preemptive_tombstone(
                DIGEST,
                digest,
                lifecycle_guard=lifecycle_guard,
                requested_at=STORE_NOW,
            )
        evidence = store.preemptive_tombstone(
            DIGEST,
            digest,
            lifecycle_guard=lifecycle_guard,
        )
    assert evidence.requested_at == privacy["recorded_at"]
    assert datetime.fromisoformat(
        evidence.tombstoned_at.replace("Z", "+00:00")
    ) >= requested_at
    journal_before = (root / "material.journal.jsonl").read_bytes()

    current[0] = requested_at - timedelta(hours=4)
    restarted = _store(
        root,
        now=current,
        authority_guarded_recovery=True,
        lifecycle_authority=ledger.lifecycle_authority,
    )
    with ledger.composition_privacy_lifecycle_guard(DIGEST) as lifecycle_guard:
        replay = restarted.preemptive_tombstone(
            DIGEST,
            digest,
            lifecycle_guard=lifecycle_guard,
        )
    assert replay == evidence
    assert (root / "material.journal.jsonl").read_bytes() == journal_before
