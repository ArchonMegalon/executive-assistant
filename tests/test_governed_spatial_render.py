from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import stat

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.governed_spatial_render import (
    BUILD_RECEIPT_CONTRACT_NAME,
    CAPABILITY_INDEX_CONTRACT_NAME,
    COMPOSITION_RECEIPT_CONTRACT_NAME,
    DESIGN_AUTHORITY_STATUS,
    Ed25519KeyRecord,
    Ed25519KeyRegistry,
    GovernedSpatialRenderReceiptStore,
    GovernedSpatialRenderService,
    PRODUCT_PROJECTION_CONTRACT_NAME,
    REQUEST_CONTRACT_NAME,
    SOURCE_PACKET_CONTRACT_NAME,
    sign_receipt_for_test,
)


OBSERVED_AT = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
SIGNING_SECRET = "test-only-governed-spatial-secret"
SIGNING_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
ROOT = Path(__file__).resolve().parents[1]


def _room(room_id: str, room_type: str, *, walkable: bool = True) -> dict[str, object]:
    room: dict[str, object] = {
        "room_id": room_id,
        "room_type": room_type,
        "walkable": walkable,
        "boundary_ref": f"geometry:boundary:{room_id}",
        "ceiling_height_m": 2.7,
        "geometry_anchor_ref": f"geometry:anchor:{room_id}",
        "texture_anchor_refs": [f"texture:anchor:{room_id}:walls"],
    }
    if room_type in {"balcony", "terrace"}:
        room["exterior_classification"] = room_type
        room["accessible"] = walkable
    return room


def _source_packet() -> dict[str, object]:
    return {
        "contract_name": SOURCE_PACKET_CONTRACT_NAME,
        "source_packet_ref": "packet:property:example-1:v1",
        "source_digest": "a" * 64,
        "normalized_floorplan_ref": "artifact:floorplan:example-1:v1",
        "room_graph_ref": "geometry:room-graph:example-1:v1",
        "walkable_mesh_ref": "geometry:walkable-mesh:example-1:v1",
        "portal_graph_ref": "geometry:portal-graph:example-1:v1",
        "scale_m_per_unit": 1.0,
        "orientation_degrees": 90.0,
        "source_retrieved_at": "2026-07-11T08:00:00Z",
        "license_provenance_refs": ["license:first-party:example-1"],
        "source_media_assignments": [],
        "inaccessible_rooms": [],
        "route_exclusions": [],
        "rooms": [
            _room("living", "living"),
            _room("bathroom", "bathroom"),
        ],
        "portals": [
            {
                "portal_id": "door-living-bathroom",
                "from_room_id": "living",
                "to_room_id": "bathroom",
                "walkable": True,
            }
        ],
        "route_room_ids": ["living", "bathroom"],
        "existing_artifacts": {
            "interactive_tour": {
                "artifact_ref": "artifact:tour:example-1:v1",
                "sha256": "b" * 64,
                "proof_ref": "proof:browser:example-1:v1",
            }
        },
    }


def _request(
    *,
    product: str = "propertyquarry",
    artifact_kind: str = "interactive_tour",
    style_pack_id: str | None = None,
) -> dict[str, object]:
    resolved_style = style_pack_id or (
        "botanical_maximalist_decorated_v1" if product == "propertyquarry" else "corporate_arcology_v1"
    )
    return {
        "contract_name": REQUEST_CONTRACT_NAME,
        "request_id": "3d0dfa6e-27bb-48d1-b00b-7675ae02416f",
        "idempotency_key": f"{product}-{artifact_kind}-example-1-v1",
        "consumer": {
            "product": product,
            "tenant_ref": f"tenant:{product}:example",
            "subject_ref": f"subject:{product}:example-1",
        },
        "artifact": {
            "kind": artifact_kind,
            "purpose": "encounter_preview" if product == "chummer" else "walkthrough",
            "locale": "en-AT",
        },
        "source_packet_ref": "packet:property:example-1:v1",
        "truth_refs": [f"truth:{product}:example-1"],
        "evidence_refs": ["proof:first-party:example-1"],
        "spatial_plan": {
            "room_graph_ref": "geometry:room-graph:example-1:v1",
            "walkable_mesh_ref": "geometry:walkable-mesh:example-1:v1",
            "portal_graph_ref": "geometry:portal-graph:example-1:v1",
            "required_room_ids": ["living", "bathroom"],
            "route_policy": "continuous_all_walkable_rooms",
            "allow_revisit": False,
        },
        "style": {
            "style_pack_id": resolved_style,
            "room_overrides": {},
            "asset_license_policy": "verified_reuse_only",
            "brand_claim_policy": "truthful_no_affiliation_claim",
        },
        "scene_overlays": [],
        "camera": {
            "height_m": 1.62,
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
            "interactive_package": True,
            "poster_frame": True,
            "contact_sheet": True,
        },
        "content_policy": {
            "rating": "general",
            "graphic_injury": False,
            "real_person_likeness": False,
            "minor_combatants": False,
        },
        "quota": {
            "consume_quota": False,
            "maximum_provider_attempts": 0,
        },
        "callback": {"product_event_ref": f"event:{product}:example-1"},
    }


def _provider_receipt(path: Path, *, generated_at: datetime) -> Path:
    check_names = [
        "3dvista_control_page_ok",
        "3dvista_no_browser_console_blockers",
        "3dvista_no_request_failures",
        "3dvista_no_bad_http_assets",
        "3dvista_rendered_viewer",
        "3dvista_accessible_shell",
        "3dvista_responsive_touch_shell",
        "3dvista_reduced_motion_shell",
        "3dvista_offline_recovery_visible",
        "3dvista_retry_restores_viewer",
        "3dvista_browser_render_proof_persisted",
    ]
    checks: list[dict[str, object]] = [{"name": name, "ok": True} for name in check_names]
    rendered = next(row for row in checks if row["name"] == "3dvista_rendered_viewer")
    rendered["state"] = {"same_origin_frame_inspected": True, "visible_canvas_count": 2}
    path.write_text(
        json.dumps(
            {
                "contract_name": "propertyquarry.3d_browser_gate.v1",
                "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
                "status": "pass",
                "providers": ["matterport", "3dvista"],
                "checks": checks,
            }
        ),
        encoding="utf-8",
    )
    return path


def _service(
    tmp_path: Path,
    *,
    current_provider_receipt: bool = True,
    persisted: bool = False,
    build_enabled: bool = False,
    signing_secret: str = SIGNING_SECRET,
    telemetry_sink: object = None,
    verification_key_registry: object = None,
    evidence_schema_path: Path | None = None,
) -> GovernedSpatialRenderService:
    evidence_paths: dict[str, Path] = {}
    if current_provider_receipt:
        evidence_paths["3dvista"] = _provider_receipt(
            tmp_path / "3dvista-browser.json",
            generated_at=OBSERVED_AT - timedelta(hours=2),
        )
    store = GovernedSpatialRenderReceiptStore(tmp_path / "private-receipts" if persisted else None)
    return GovernedSpatialRenderService(
        provider_evidence_paths=evidence_paths,
        receipt_store=store,
        signing_private_key=SIGNING_PRIVATE_KEY if signing_secret else None,
        signing_key_ref="key:test:governed-spatial:1" if signing_secret else "",
        telemetry_sink=telemetry_sink if callable(telemetry_sink) else None,
        verification_key_registry=verification_key_registry,
        evidence_schema_path=evidence_schema_path,
        evidence_schema_sha256=(
            "f86e6f737ba3333f7e84d8196481cda4c4cc34dc08d6b5aff5a7465af303546f"
            if evidence_schema_path is not None
            else ""
        ),
        build_enabled=build_enabled,
    )


def _compose(
    service: GovernedSpatialRenderService,
    request: dict[str, object] | None = None,
    source_packet: dict[str, object] | None = None,
) -> dict[str, object]:
    return service.compose(
        request or _request(),
        source_packet=source_packet or _source_packet(),
        observed_at=OBSERVED_AT,
    )


def _build(
    service: GovernedSpatialRenderService,
    composition: dict[str, object],
    *,
    build_key: str = "build-example-1-v1",
    consume_quota: bool = True,
    maximum_provider_attempts: int = 1,
    evidence_envelope: dict[str, object] | None = None,
) -> dict[str, object]:
    return service.build(
        composition_digest=str(composition["composition_digest"]),
        composition_signature=str(composition["composition_signature"]),
        build_idempotency_key=build_key,
        consume_quota=consume_quota,
        maximum_provider_attempts=maximum_provider_attempts,
        quota_authorization_ref="quota:propertyquarry:example-1:v1",
        audit_event_ref="audit:propertyquarry:example-1:v1",
        evidence_envelope=evidence_envelope,
        observed_at=OBSERVED_AT,
    )


def _signed_build_evidence(composition_digest: str) -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    issued_at = "2026-07-11T11:59:00Z"
    expires_at = "2026-07-11T12:04:00Z"
    envelope: dict[str, object] = {
        "schema_version": "governed_spatial_render_capability_quota_evidence_v1",
        "contract_name": "governed_spatial_render_v1",
        "receipt_id": "receipt:test:build:0001",
        "issuer": "chummer6-media-factory",
        "issued_at": issued_at,
        "expires_at": expires_at,
        "artifact_family": "runsite_continuous_walkthrough",
        "content_profile": "spatial_orientation_no_encounter_fields",
        "provider_route_digest": digest,
        "environment": "test",
        "gate_versions": {"compose": "v1"},
        "evidence_refs": [
            {
                "ref": f"evidence:{family}",
                "sha256": str(index) * 64,
                "evidence_family": family,
                "gate_version": "v1",
                "issued_at": issued_at,
                "expires_at": expires_at,
            }
            for index, family in enumerate(
                (
                    "provider_capability",
                    "canonical_compose_validator_exact_version",
                    "quota_snapshot",
                    "kill_switch",
                ),
                start=1,
            )
        ],
        "revocation": {"state": "active", "epoch": 1, "revoked_at": None, "reason_ref": None},
        "capability_state": "verified",
        "readiness_projection": "blocked",
        "quota_posture": "build_allowed",
        "compose_audit": {
            "authoritative_owner": "chummer6-media-factory",
            "zero_burn": True,
            "provider_job_enqueued": False,
            "reservation_mutated": False,
            "consumption_mutated": False,
            "readiness_allowed": False,
            "ea_assistance_authority": "non_authoritative_synthetic_only",
        },
        "authorization": {
            "owner": "chummer6-hub",
            "state": "valid",
            "authorization_ref": "quota:propertyquarry:example-1:v1",
            "issued_at": issued_at,
            "expires_at": expires_at,
            "maximum_provider_attempts": 1,
            "quota_limit_digest": digest,
        },
        "quota": {
            "state": "authorization_verified",
            "reservation_owner": "chummer6-media-factory",
            "consumption_owner": "chummer6-media-factory",
            "retry_owner": "chummer6-media-factory",
            "cancellation_owner": "chummer6-media-factory",
            "compensation_owner": "chummer6-media-factory",
            "fleet_authority": "execution_budget_gate_and_landing_control_only",
            "product_governor_authority": "freeze_and_reroute_only",
            "ea_authority": "read_only_none",
            "snapshot_issued_at": issued_at,
            "snapshot_expires_at": expires_at,
            "reservation_ref_digest": None,
            "reservation_expires_at": None,
            "attempt_number": 0,
            "mutation_token_digest": None,
            "consumption_receipt_digest": None,
            "compensation_receipt_digest": None,
        },
        "idempotency": {
            "ledger_owner": "chummer6-media-factory",
            "scope_digest": digest,
            "key_digest": "sha256:" + "6" * 64,
            "normalized_request_digest": "sha256:" + "7" * 64,
            "composition_digest": "sha256:" + composition_digest,
            "authorization_binding_digest": "sha256:" + "9" * 64,
            "same_key_same_digest": "return_existing_state",
            "same_key_different_digest": "reject_conflict",
            "concurrent_duplicate": "one_job_one_reservation_one_attempt",
            "retry_token_scope": "job_id_and_attempt_number",
        },
        "kill_switch": {
            "owner": "chummer6-media-factory",
            "state": "route_allowed",
            "epoch": 1,
            "issued_at": issued_at,
            "expires_at": expires_at,
        },
    }
    return sign_receipt_for_test(
        envelope,
        private_key=SIGNING_PRIVATE_KEY,
        key_ref="key:test:build-evidence:1",
        key_epoch=7,
    )


def test_capability_index_uses_current_3dvista_receipt_without_promoting_matterport(tmp_path: Path) -> None:
    service = _service(tmp_path)

    index = service.capability_index(observed_at=OBSERVED_AT)

    assert index["contract_name"] == CAPABILITY_INDEX_CONTRACT_NAME
    assert index["design_authority_status"] == DESIGN_AUTHORITY_STATUS
    providers = {row["provider_key"]: row for row in index["providers"]}
    assert providers["3dvista"]["status"] == "verified"
    assert providers["3dvista"]["quota_posture"] == "audit_only"
    assert "matterport" not in providers
    capabilities = {row["capability_id"]: row for row in index["capabilities"]}
    assert capabilities["3dvista_interactive_tour_intake"]["status"] == "verified"


def test_preacceptance_provider_posture_stays_audit_only_even_when_build_flag_is_set(tmp_path: Path) -> None:
    index = _service(tmp_path, build_enabled=True).capability_index(observed_at=OBSERVED_AT)

    provider = next(row for row in index["providers"] if row["provider_key"] == "3dvista")
    capability = next(
        row for row in index["capabilities"] if row["capability_id"] == "3dvista_interactive_tour_intake"
    )
    assert provider["status"] == "verified"
    assert provider["quota_posture"] == "audit_only"
    assert capability["quota_posture"] == "audit_only"
    assert index["design_authority_status"] == DESIGN_AUTHORITY_STATUS


def test_stale_3dvista_receipt_degrades_capability(tmp_path: Path) -> None:
    evidence = _provider_receipt(
        tmp_path / "stale-3dvista-browser.json",
        generated_at=OBSERVED_AT - timedelta(hours=49),
    )
    service = GovernedSpatialRenderService(
        provider_evidence_paths={"3dvista": evidence},
        signing_private_key=SIGNING_PRIVATE_KEY,
        signing_key_ref="key:test:governed-spatial:1",
    )

    index = service.capability_index(observed_at=OBSERVED_AT)

    provider = next(row for row in index["providers"] if row["provider_key"] == "3dvista")
    assert provider["status"] == "degraded"
    assert provider["status_reason"] == "3dvista_browser_receipt_stale"
    assert provider["quota_posture"] == "audit_only"


def test_compose_is_signed_deterministic_and_zero_burn(tmp_path: Path) -> None:
    service = _service(tmp_path)

    receipt = _compose(service)
    replay = _compose(service)

    assert receipt["contract_name"] == COMPOSITION_RECEIPT_CONTRACT_NAME
    assert receipt["status"] == "accepted"
    assert receipt["signature_status"] == "signed"
    assert len(str(receipt["composition_signature"])) == 86
    assert receipt["signature_algorithm"] == "ed25519"
    assert receipt["signature_encoding"] == "base64url_no_padding"
    assert receipt["signing_key_ref"] == "key:test:governed-spatial:1"
    assert str(receipt["signing_key_fingerprint"]).startswith("sha256:")
    assert receipt["quota"] == {"consume_quota": False, "provider_attempts": 0, "credits_consumed": 0}
    assert receipt["composition_digest"] == replay["composition_digest"]
    assert replay["idempotent_replay"] is True
    assert "style_visual_acceptance_pending" in receipt["warnings"]
    for field in ("request_digest", "source_digest", "source_packet_digest", "style_digest"):
        assert len(str(receipt[field])) == 64


def test_composition_binds_complete_source_packet_to_idempotency_key(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request()
    _compose(service, request, _source_packet())
    changed_source = _source_packet()
    changed_source["orientation_degrees"] = 180.0

    with pytest.raises(ValueError, match="idempotency_key_payload_conflict"):
        _compose(service, request, changed_source)


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda request, source: request.update({"truth_refs": []}), "truth_refs"),
        (
            lambda request, source: request["style"].update(  # type: ignore[union-attr]
                {"provider_url": "https://vendor.invalid/task/123"}
            ),
            "sensitive_field:style.provider_url",
        ),
        (
            lambda request, source: source.update({"provider_name": "3dvista"}),
            "sensitive_field:source_packet.provider_name",
        ),
        (
            lambda request, source: request["quota"].update(  # type: ignore[union-attr]
                {"maximum_provider_attempts": "invalid"}
            ),
            "compose_provider_attempts_must_be_zero",
        ),
    ],
)
def test_compose_rejects_missing_or_sensitive_product_truth(
    tmp_path: Path,
    mutator: object,
    reason: str,
) -> None:
    request = _request()
    source = _source_packet()
    assert callable(mutator)
    mutator(request, source)

    receipt = _compose(_service(tmp_path), request, source)

    assert receipt["status"] == "blocked"
    assert reason in receipt["blocked_reasons"]
    assert receipt["quota"]["credits_consumed"] == 0


def test_continuous_route_requires_coverage_and_declared_portal_transitions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request(artifact_kind="continuous_walkthrough")
    source = _source_packet()
    source["portals"] = []

    receipt = _compose(service, request, source)

    assert receipt["status"] == "blocked"
    assert "route_portal_transition_invalid" in receipt["blocked_reasons"]
    assert "required_room_graph_disconnected" in receipt["blocked_reasons"]
    quality = receipt["quality_contract"]
    assert quality["room_coverage_percent"] == 100.0
    assert quality["cut_count"] == 1
    assert quality["teleport_count"] == 1

    request["idempotency_key"] = "continuous-missing-coverage-v1"
    source = _source_packet()
    source["route_room_ids"] = ["living"]
    missing_coverage = _compose(service, request, source)
    assert "required_room_coverage" in missing_coverage["blocked_reasons"]
    assert missing_coverage["quality_contract"]["room_coverage_percent"] == 50.0


def test_continuous_route_required_inventory_equals_every_walkable_source_room_without_exclusions(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    source = _source_packet()
    source["rooms"].append(_room("bedroom", "bedroom"))  # type: ignore[union-attr]
    source["portals"].append(  # type: ignore[union-attr]
        {
            "portal_id": "door-bathroom-bedroom",
            "from_room_id": "bathroom",
            "to_room_id": "bedroom",
            "walkable": True,
        }
    )
    source["route_room_ids"] = ["living", "bathroom", "bedroom"]
    request = _request(artifact_kind="continuous_walkthrough")
    request["idempotency_key"] = "continuous-omitted-walkable-room-v1"

    omitted = _compose(service, request, source)

    assert omitted["status"] == "blocked"
    assert "required_room_inventory_mismatch" in omitted["blocked_reasons"]

    request["idempotency_key"] = "continuous-authorized-room-exclusion-v1"
    source["route_exclusions"] = [
        {
            "room_id": "bedroom",
            "reason": "source_authorized_maintenance_exclusion",
            "authorization_ref": "authorization:property:example-1:bedroom:v1",
        }
    ]
    source["route_room_ids"] = ["living", "bathroom"]
    excluded_but_still_walkable = _compose(service, request, source)
    assert excluded_but_still_walkable["status"] == "blocked"
    assert "required_room_inventory_mismatch" in excluded_but_still_walkable["blocked_reasons"]
    assert "flagship_route_exclusions_not_allowed" in excluded_but_still_walkable["blocked_reasons"]


def test_provenanced_nonwalkable_room_is_not_required_by_flagship_route(tmp_path: Path) -> None:
    source = _source_packet()
    source["rooms"].append(_room("service-space", "bedroom", walkable=False))  # type: ignore[union-attr]
    source["inaccessible_rooms"] = [
        {
            "room_id": "service-space",
            "reason": "source_verified_no_walkable_access",
            "provenance_ref": "provenance:property:example-1:service-space:v1",
        }
    ]
    request = _request(artifact_kind="continuous_walkthrough")
    request["idempotency_key"] = "continuous-provenanced-nonwalkable-v1"

    receipt = _compose(_service(tmp_path), request, source)

    assert receipt["status"] == "accepted"
    assert receipt["quality_contract"]["required_room_count"] == 2
    assert receipt["quality_contract"]["room_coverage_percent"] == 100.0


def test_continuous_route_enforces_no_cut_no_teleport_camera_contract(tmp_path: Path) -> None:
    request = _request(artifact_kind="continuous_walkthrough")
    request["camera"]["cuts_allowed"] = True  # type: ignore[index]
    request["camera"]["teleports_allowed"] = True  # type: ignore[index]

    receipt = _compose(_service(tmp_path), request)

    assert receipt["status"] == "blocked"
    assert "camera_cuts_allowed" in receipt["blocked_reasons"]
    assert "camera_teleports_allowed" in receipt["blocked_reasons"]
    assert receipt["quota"]["provider_attempts"] == 0


def test_style_pack_must_cover_source_rooms_and_real_product_claim_needs_proof(tmp_path: Path) -> None:
    source = _source_packet()
    source["rooms"] = [_room("garage", "garage")]
    source["portals"] = []
    source["route_room_ids"] = ["garage"]
    request = _request()
    request["spatial_plan"]["required_room_ids"] = ["garage"]  # type: ignore[index]

    unsupported_room = _compose(_service(tmp_path), request, source)
    assert "style_room_type_coverage" in unsupported_room["blocked_reasons"]

    request = _request(style_pack_id="scandinavian_ikea_at_2026_v1")
    request["idempotency_key"] = "scandinavian-real-product-v1"
    request["style"]["real_product_claim"] = True  # type: ignore[index]
    unlicensed_claim = _compose(_service(tmp_path), request)
    assert "style_pack_blocked_asset_reuse_proof_required" in unlicensed_claim["blocked_reasons"]
    assert "style_real_product_reuse_proof" in unlicensed_claim["blocked_reasons"]


def test_every_draft_chummer_style_swaps_without_route_or_provider_changes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    style_ids = [
        "corporate_arcology_v1",
        "abandoned_industrial_site_v1",
        "neon_street_market_v1",
        "high_security_laboratory_v1",
        "occult_interior_v1",
        "derelict_residential_block_v1",
    ]
    digests: set[str] = set()
    for style_id in style_ids:
        request = _request(
            product="chummer",
            artifact_kind="continuous_walkthrough",
            style_pack_id=style_id,
        )
        request["idempotency_key"] = f"chummer-style-{style_id}"
        receipt = _compose(service, request)
        assert receipt["status"] == "accepted", (style_id, receipt["blocked_reasons"])
        assert receipt["quality_contract"]["room_coverage_percent"] == 100.0
        assert receipt["provider_resolution"]["selected_provider_private"] == "magicfit"
        digests.add(str(receipt["style_digest"]))
    assert len(digests) == len(style_ids)


def test_draft_schemas_and_style_registry_preserve_strict_boundaries() -> None:
    request_schema = json.loads(
        (ROOT / "ea/app/data/governed_spatial_render_request.schema.v1.json").read_text(encoding="utf-8")
    )
    source_schema = json.loads(
        (ROOT / "ea/app/data/governed_spatial_source_packet.schema.v1.json").read_text(encoding="utf-8")
    )
    style_registry = json.loads(
        (ROOT / "ea/app/data/governed_spatial_style_packs.v1.json").read_text(encoding="utf-8")
    )

    assert request_schema["x-design-authority-status"] == "draft_pending_design_acceptance"
    assert request_schema["additionalProperties"] is False
    for definition in ("overlay", "participant", "beat"):
        assert request_schema["$defs"][definition]["additionalProperties"] is False
    assert "damage" not in request_schema["$defs"]["beat"]["properties"]
    assert source_schema["x-design-authority-status"] == "draft_pending_design_acceptance"
    assert source_schema["properties"]["route_exclusions"]["maxItems"] == 0

    assert style_registry["design_authority_status"] == "draft_pending_design_acceptance"
    for pack in style_registry["style_packs"]:
        assert pack["room_rules"]
        assert pack["adapter_profile_ref"].startswith("adapter-profile:")
        assert pack["provenance_refs"]
        assert pack["visual_regression_refs"] == []
        assert pack["acceptance_contact_sheet_refs"] == []
        assert "prompt" not in pack


def _combat_overlay() -> dict[str, object]:
    return {
        "overlay_id": "encounter-beat-01",
        "kind": "fictional_combat_choreography",
        "gameplay_truth_ref": "truth:chummer:encounter-01",
        "location_anchor": "route-anchor:living",
        "start_time_s": 18.0,
        "end_time_s": 29.0,
        "participants": [
            {"actor_ref": "actor:runner-01", "role": "runner", "minor": False, "real_person": False},
            {"actor_ref": "actor:opposition-01", "role": "opposition", "minor": False, "real_person": False},
        ],
        "beats": [
            {"at_s": 18.0, "action": "take_cover", "actor_ref": "actor:runner-01"},
            {"at_s": 21.0, "action": "non_graphic_exchange", "actor_ref": "actor:opposition-01"},
            {"at_s": 26.0, "action": "advance", "actor_ref": "actor:runner-01"},
        ],
        "provided_outcome": "outcome:chummer:encounter-01",
        "camera_policy": "continuous_witness_path",
        "graphic_injury": False,
    }


def test_chummer_noncombat_and_reference_only_combat_overlays_compose(tmp_path: Path) -> None:
    service = _service(tmp_path)
    noncombat_request = _request(product="chummer", artifact_kind="continuous_walkthrough")
    noncombat = _compose(service, noncombat_request)
    assert noncombat["status"] == "accepted"
    assert noncombat["quality_contract"]["overlay_count"] == 0

    combat_request = _request(product="chummer", artifact_kind="continuous_walkthrough")
    combat_request["idempotency_key"] = "chummer-combat-example-1-v1"
    combat_request["scene_overlays"] = [_combat_overlay()]
    combat_request["content_policy"]["rating"] = "teen_fictional_combat"  # type: ignore[index]
    combat = _compose(service, combat_request)
    assert combat["status"] == "accepted"
    assert combat["quality_contract"]["combat_overlay_count"] == 1
    assert combat["quality_contract"]["room_coverage_percent"] == 100.0


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda overlay: overlay.pop("gameplay_truth_ref"), "scene_overlay_gameplay_truth_ref:encounter-beat-01"),
        (lambda overlay: overlay.pop("provided_outcome"), "scene_overlay_provided_outcome:encounter-beat-01"),
        (
            lambda overlay: overlay.update({"initiative": 17}),
            "scene_overlay_rules_truth_forbidden:encounter-beat-01:initiative",
        ),
        (
            lambda overlay: overlay["participants"][0].update({"minor": True}),  # type: ignore[index,union-attr]
            "scene_overlay_participant_policy:encounter-beat-01",
        ),
    ],
)
def test_chummer_overlay_policy_fails_before_quota_burn(
    tmp_path: Path,
    mutation: object,
    reason: str,
) -> None:
    request = _request(product="chummer", artifact_kind="continuous_walkthrough")
    overlay = _combat_overlay()
    assert callable(mutation)
    mutation(overlay)
    request["scene_overlays"] = [overlay]
    request["content_policy"]["rating"] = "teen_fictional_combat"  # type: ignore[index]

    receipt = _compose(_service(tmp_path), request)

    assert receipt["status"] == "blocked"
    assert reason in receipt["blocked_reasons"]
    assert receipt["quota"]["credits_consumed"] == 0


def test_chummer_overlay_rejects_nested_rules_fields_with_path_before_quota_burn(tmp_path: Path) -> None:
    request = _request(product="chummer", artifact_kind="continuous_walkthrough")
    overlay = _combat_overlay()
    overlay["beats"][0]["damage"] = 6  # type: ignore[index]
    request["scene_overlays"] = [overlay]
    request["content_policy"]["rating"] = "teen_fictional_combat"  # type: ignore[index]

    receipt = _compose(_service(tmp_path), request)

    assert receipt["status"] == "blocked"
    assert (
        "scene_overlay_rules_truth_forbidden:encounter-beat-01:beats[0].damage"
        in receipt["blocked_reasons"]
    )
    assert (
        "scene_overlay_beat_field_not_allowed:encounter-beat-01:beats[0].damage"
        in receipt["blocked_reasons"]
    )
    assert receipt["quota"] == {"consume_quota": False, "provider_attempts": 0, "credits_consumed": 0}


def test_build_remains_blocked_without_trusted_artifact_verifier_and_never_enqueues(tmp_path: Path) -> None:
    service = _service(tmp_path, build_enabled=True)
    composition = _compose(service)

    build = _build(service, composition)

    assert build["contract_name"] == BUILD_RECEIPT_CONTRACT_NAME
    assert build["status"] == "blocked"
    assert "design_acceptance_required" not in build["blocked_reasons"]
    assert "trusted_immutable_artifact_verification_unavailable" in build["blocked_reasons"]
    assert build["provider_private"]["provider_jobs_attempted"] == 0
    assert build["provider_private"]["provider_credits_consumed"] == 0
    assert build["audit"]["provider_job_enqueued"] is False
    assert build["provider_private"]["existing_artifact_candidate_shape_valid"] is True
    assert build["provider_private"]["trusted_artifact_verified"] is False
    assert build["provider_private"]["existing_artifact_reused"] is False
    projection = build["product_projection"]
    assert projection["contract_name"] == PRODUCT_PROJECTION_CONTRACT_NAME
    assert projection["state"] == "blocked"
    assert projection["artifact_ref"] == ""
    assert set(projection) == {
        "contract_name",
        "request_id",
        "artifact_kind",
        "label",
        "state",
        "progress_percent",
        "eta_seconds",
        "artifact_ref",
        "reason",
        "retry_posture",
        "provider_details_exposed",
    }
    assert "3dvista" not in json.dumps(projection).lower()


def test_build_requires_explicit_quota_and_is_payload_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path, build_enabled=True)
    composition = _compose(service)

    blocked = _build(service, composition, consume_quota=False)
    replay = _build(service, composition, consume_quota=False)

    assert "explicit_quota_authorization_required" in blocked["blocked_reasons"]
    assert blocked["quota"]["provider_attempts"] == 0
    assert blocked["quota"]["provider_credits_consumed"] == 0
    assert replay["build_id"] == blocked["build_id"]
    assert replay["idempotent_replay"] is True
    with pytest.raises(ValueError, match="build_idempotency_key_payload_conflict"):
        _build(service, composition, consume_quota=False, maximum_provider_attempts=2)


def test_build_requires_hash_bound_schema_valid_signed_evidence_before_any_external_action(tmp_path: Path) -> None:
    registry = Ed25519KeyRegistry(
        [
            Ed25519KeyRecord(
                key_ref="key:test:build-evidence:1",
                issuer="chummer6-media-factory",
                key_epoch=7,
                public_key=SIGNING_PRIVATE_KEY.public_key(),
                valid_from=OBSERVED_AT - timedelta(days=1),
                valid_until=OBSERVED_AT + timedelta(days=1),
            )
        ]
    )
    schema_path = Path(
        "/docker/chummercomplete/chummer-design/products/chummer/"
        "GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml"
    )
    service = _service(
        tmp_path,
        build_enabled=True,
        verification_key_registry=registry,
        evidence_schema_path=schema_path,
    )
    composition = _compose(service)
    evidence = _signed_build_evidence(str(composition["composition_digest"]))

    build = _build(service, composition, evidence_envelope=evidence)

    assert build["status"] == "blocked"
    assert "signed_build_evidence_required" not in build["blocked_reasons"]
    assert "signed_build_evidence_composition_mismatch" not in build["blocked_reasons"]
    assert "trusted_immutable_artifact_verification_unavailable" in build["blocked_reasons"]
    assert str(build["audit"]["signed_evidence_digest"]).startswith("sha256:")
    assert build["provider_private"]["provider_jobs_attempted"] == 0
    assert build["quota"]["provider_credits_consumed"] == 0

    tampered = deepcopy(evidence)
    tampered["kill_switch"]["epoch"] = 2  # type: ignore[index]
    with pytest.raises(ValueError, match="signed_payload_digest_invalid"):
        _build(service, composition, build_key="tampered-evidence-build-v1", evidence_envelope=tampered)


def test_unverified_provider_cannot_project_ready(tmp_path: Path) -> None:
    service = _service(tmp_path, current_provider_receipt=False, build_enabled=True)
    composition = _compose(service)

    build = _build(service, composition)

    assert "verified_provider_required" in build["blocked_reasons"]
    assert build["product_projection"]["state"] == "blocked"
    assert build["product_projection"]["artifact_ref"] == ""


def test_private_receipts_use_owner_only_permissions(tmp_path: Path) -> None:
    service = _service(tmp_path, persisted=True, build_enabled=True)
    composition = _compose(service)
    _build(service, composition)
    receipt_root = tmp_path / "private-receipts"

    receipt_files = [
        receipt_root / "index.json",
        next((receipt_root / "compositions").iterdir()),
        next((receipt_root / "builds").iterdir()),
    ]
    assert stat.S_IMODE(receipt_root.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in receipt_files)


def test_persisted_receipts_reload_and_preserve_idempotency_across_service_restart(tmp_path: Path) -> None:
    first_service = _service(tmp_path, persisted=True, build_enabled=True)
    first_composition = _compose(first_service)
    first_build = _build(first_service, first_composition)

    restarted_service = _service(tmp_path, persisted=True, build_enabled=True)
    replayed_composition = _compose(restarted_service)
    replayed_build = _build(restarted_service, replayed_composition)

    assert replayed_composition["composition_digest"] == first_composition["composition_digest"]
    assert replayed_composition["idempotent_replay"] is True
    assert replayed_build["build_id"] == first_build["build_id"]
    assert replayed_build["idempotent_replay"] is True
    assert replayed_build["provider_private"]["provider_jobs_attempted"] == 0
    assert replayed_build["quota"]["provider_credits_consumed"] == 0

    changed_source = _source_packet()
    changed_source["orientation_degrees"] = 180.0
    with pytest.raises(ValueError, match="idempotency_key_payload_conflict"):
        _compose(restarted_service, _request(), changed_source)
    with pytest.raises(ValueError, match="build_idempotency_key_payload_conflict"):
        _build(restarted_service, replayed_composition, maximum_provider_attempts=2)


@pytest.mark.parametrize("tamper_target", ["receipt", "index"])
def test_persisted_receipt_or_index_tampering_blocks_restart(tmp_path: Path, tamper_target: str) -> None:
    service = _service(tmp_path, persisted=True)
    _compose(service)
    receipt_root = tmp_path / "private-receipts"
    if tamper_target == "receipt":
        target = next((receipt_root / "compositions").iterdir())
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["status"] = "tampered"
    else:
        target = receipt_root / "index.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["index_digest"] = "0" * 64
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    target.chmod(0o600)

    with pytest.raises(ValueError, match="integrity"):
        GovernedSpatialRenderReceiptStore(receipt_root)


def test_missing_signing_key_blocks_composition(tmp_path: Path) -> None:
    receipt = _compose(_service(tmp_path, signing_secret=""))

    assert receipt["status"] == "blocked"
    assert "composition_signing_key_missing" in receipt["blocked_reasons"]
    assert receipt["composition_signature"] == ""


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("target_delivery_fps", 60.9, "camera_target_delivery_fps"),
        ("target_delivery_fps", float("nan"), "camera_target_delivery_fps"),
        ("minimum_effective_motion_fps", float("inf"), "camera_minimum_effective_motion_fps"),
        ("height_m", float("nan"), "camera_height"),
    ],
)
def test_compose_rejects_fractional_or_nonfinite_camera_measurements(
    tmp_path: Path,
    field: str,
    value: object,
    reason: str,
) -> None:
    request = _request()
    request["camera"][field] = value  # type: ignore[index]

    receipt = _compose(_service(tmp_path), request)

    assert receipt["status"] == "blocked"
    assert reason in receipt["blocked_reasons"]
    assert receipt["quota"]["provider_attempts"] == 0


def test_compose_rejects_fractional_attempt_count_and_nonfinite_source_geometry(tmp_path: Path) -> None:
    request = _request()
    request["quota"]["maximum_provider_attempts"] = 0.9  # type: ignore[index]
    source = _source_packet()
    source["scale_m_per_unit"] = float("inf")

    receipt = _compose(_service(tmp_path), request, source)

    assert "compose_provider_attempts_must_be_zero" in receipt["blocked_reasons"]
    assert "source_scale" in receipt["blocked_reasons"]


def test_build_rejects_fractional_attempt_count_before_state_or_quota_action(tmp_path: Path) -> None:
    service = _service(tmp_path, build_enabled=True)
    composition = _compose(service)

    with pytest.raises(ValueError, match="maximum_provider_attempts_exact_integer_required"):
        _build(service, composition, maximum_provider_attempts=0.9)  # type: ignore[arg-type]


def test_structured_telemetry_reports_replay_blocking_and_zero_external_actions(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    service = _service(tmp_path, build_enabled=True, telemetry_sink=events.append)
    composition = _compose(service)
    _compose(service)
    _build(service, composition)

    assert [event["event_type"] for event in events] == [
        "composition_created",
        "composition_replayed",
        "build_state_changed",
    ]
    build_event = events[-1]
    assert build_event["status"] == "blocked"
    assert build_event["provider_execution_suppressed"] is True
    assert build_event["provider_actions"] == 0
    assert build_event["quota_actions"] == 0
    serialized = json.dumps(events).lower()
    for forbidden in ("https://", "api_key", "authorization:propertyquarry:example-1:v1"):
        assert forbidden not in serialized


def test_shared_core_accepts_registry_authorized_future_consumer_without_product_branch(tmp_path: Path) -> None:
    registry = json.loads((ROOT / "ea/app/data/governed_spatial_style_packs.v1.json").read_text(encoding="utf-8"))
    registry["style_packs"] = [
        {
            "style_pack_id": "future_consumer_style_v1",
            "label": "Future consumer style",
            "consumer_products": ["futureconsumer"],
            "status": "accepted",
            "room_types": ["any"],
            "room_rules": {"any": ["clear_walkable_route"]},
            "composition_rules": ["clear_walkable_route"],
            "palette": ["neutral"],
            "materials": ["generic"],
            "furniture_catalog_refs": [],
            "negative_constraints": [],
            "asset_license_policy": "verified_reuse_only",
            "brand_claim_policy": "truthful_no_affiliation_claim",
            "adapter_profile_ref": "adapter-profile:future-consumer:v1",
            "external_asset_refs": [],
            "provenance_status": "first_party",
            "provenance_refs": ["provenance:futureconsumer:style:v1"],
            "source_retrieved_at": "2026-07-11T00:00:00Z",
            "visual_direction_refs": [],
            "visual_regression_refs": [],
            "acceptance_contact_sheet_refs": [],
        }
    ]
    registry_path = tmp_path / "future-style-registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    service = GovernedSpatialRenderService(
        style_registry_path=registry_path,
        signing_private_key=SIGNING_PRIVATE_KEY,
        signing_key_ref="key:test:governed-spatial:1",
    )
    request = _request()
    request["consumer"] = {
        "product": "futureconsumer",
        "tenant_ref": "tenant:futureconsumer:test",
        "subject_ref": "subject:futureconsumer:test",
    }
    request["style"]["style_pack_id"] = "future_consumer_style_v1"  # type: ignore[index]
    request["truth_refs"] = ["truth:futureconsumer:test"]
    request["callback"] = {"product_event_ref": "event:futureconsumer:test"}
    request["idempotency_key"] = "futureconsumer-interactive-test-v1"

    receipt = _compose(service, request)

    assert receipt["status"] == "accepted", receipt["blocked_reasons"]
    assert receipt["consumer_product"] == "futureconsumer"
