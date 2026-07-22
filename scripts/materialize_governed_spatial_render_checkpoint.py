from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.governed_spatial_render import (  # noqa: E402
    REQUEST_CONTRACT_NAME,
    SOURCE_PACKET_CONTRACT_NAME,
    GovernedSpatialRenderReceiptStore,
    GovernedSpatialRenderService,
)
from scripts.materialize_governed_spatial_render_design_review import (  # noqa: E402
    CANONICAL_REVIEW_STATUS,
    DEFAULT_OUTPUT as DEFAULT_DESIGN_REVIEW_OUTPUT,
    build_design_review_receipt,
    verify_design_review_receipt_payload,
)


DEFAULT_OUTPUT = ROOT / "_completion" / "governed-spatial-render" / "EA_GOVERNED_SPATIAL_RENDER_CHECKPOINT.generated.json"
DEFAULT_PRIVATE_ROOT = ROOT / "_completion" / "governed-spatial-render" / "private-v2"
DEFAULT_3DVISTA_RECEIPT = Path(
    "/docker/property/_completion/smoke/propertyquarry-candidate-ux-20260710/3d-browser-gate-native60.json"
)
ETA_TELEGRAM_RECEIPT = ROOT / "_completion" / "governed-spatial-render" / "ETA_TELEGRAM_DELIVERY.generated.json"
PROPERTYQUARRY_DIORAMA = Path(
    "/docker/property/ea/app/static/property/research/d907fa5b6b5d7308-diorama.png"
)
BOTANICAL_SEED = Path(
    "/home/tibor/.codex/generated_images/019f4a48-e37e-7ed1-a5c8-74a061f76c86/"
    "exec-d2205e5a-b0cd-4f1e-943a-84e2b786dea8.png"
)
SCANDINAVIAN_INTERIM_SEED = Path(
    "/home/tibor/.codex/generated_images/019f4a48-e37e-7ed1-a5c8-74a061f76c86/"
    "exec-1ee445ee-bbb7-4d79-96f5-8008cb1bdb35.png"
)

CANONICAL_SOURCE_VALIDATION_BLOCKED = "canonical_review_source_validation_blocked"
CANONICAL_AUTHORITY_BLOCKER_CONTRACT = "ea.governed_spatial_render_authority_blocker.v1"
CANONICAL_AUTHORITY_SOURCE = "chummer_design:governed_spatial_render_authority"
CANONICAL_AUTHORITY_NEXT_ACTION = "obtain_new_hash_bound_canonical_authority_receipt"
CANONICAL_AUTHORITY_FOLLOW_UP = (
    "obtain_new_hash_bound_canonical_authority_receipt:"
    "ea-governed-spatial-render-contract-v1"
)
_CANONICAL_VALIDATION_REASON_PREFIXES = (
    "canonical_design_review_invalid",
    "canonical_input_hash_drift",
    "canonical_input_missing",
    "decision_authority_marker_missing",
    "decision_canonical_binding_missing",
    "decision_evidence_binding_missing",
    "decision_hash_drift",
    "decision_heading_invalid",
    "decision_metadata_invalid",
    "decision_missing",
    "handoff_hash_drift",
    "handoff_missing",
    "petition_hash_drift",
    "petition_missing",
)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime:
    if not value:
        return _utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_validation_reason(error: ValueError) -> str | None:
    raw = str(error).strip()
    return next(
        (reason for reason in _CANONICAL_VALIDATION_REASON_PREFIXES if raw.startswith(reason)),
        None,
    )


def _canonical_authority_blocker(error: ValueError, *, observed_at: datetime) -> dict[str, object]:
    reason = _canonical_validation_reason(error)
    if reason is None:
        raise error
    body: dict[str, object] = {
        "contract_name": CANONICAL_AUTHORITY_BLOCKER_CONTRACT,
        "generated_at": _utc_iso(observed_at),
        "status": "blocked",
        "reason": reason,
        "authority_source": CANONICAL_AUTHORITY_SOURCE,
        "failure_fingerprint": _sha256_text(str(error).strip()),
        "next_action": CANONICAL_AUTHORITY_NEXT_ACTION,
        "implementation_authorized": False,
        "provider_execution_authorized": False,
        "quota_authorized": False,
        "publication_authorized": False,
        "serving_authorized": False,
        "launch_ready_allowed": False,
        "raw_failure_detail_exposed": False,
    }
    return {**body, "receipt_digest": _sha256_json(body)}


def _blocked_design_review(
    blocker: dict[str, object],
    *,
    observed_at: datetime,
) -> dict[str, object]:
    body: dict[str, object] = {
        "contract_name": "ea.governed_spatial_render_design_review_unavailable.v1",
        "generated_at": _utc_iso(observed_at),
        "status": "source_validation_blocked",
        "review_applicable": True,
        "decision": {
            "disposition": "unverified",
            "implementation_state": "blocked",
            "independent_review": False,
        },
        "authority_source": CANONICAL_AUTHORITY_SOURCE,
        "authority_blocker_digest": blocker["receipt_digest"],
        "implementation_authorized": False,
        "provider_execution_authorized": False,
        "quota_authorized": False,
        "product_bridge_registration_authorized": False,
        "live_change_authorized": False,
        "independent_re_review_required": True,
        "launch_recommendation": "no",
    }
    return {**body, "receipt_digest": _sha256_json(body)}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _asset_row(label: str, path: Path, *, provenance_ref: str, accepted: bool) -> dict[str, object]:
    exists = path.is_file()
    return {
        "label": label,
        "path": str(path),
        "exists": exists,
        "sha256": _file_sha256(path) if exists else "",
        "provenance_ref": provenance_ref,
        "accepted_artifact": accepted,
    }


def _load_or_create_fixture_signing_key(private_root: Path) -> str:
    private_root.mkdir(parents=True, exist_ok=True)
    private_root.chmod(0o700)
    path = private_root / "fixture-signing.key"
    if path.is_file():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("fixture_signing_key_permissions_or_link_invalid")
        value = path.read_text(encoding="ascii").strip()
        if len(value) < 64:
            raise ValueError("fixture_signing_key_invalid")
        return value
    value = secrets.token_hex(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return value


def _fixture_source_packet() -> dict[str, object]:
    return {
        "contract_name": SOURCE_PACKET_CONTRACT_NAME,
        "source_packet_ref": "fixture:spatial-source:property-example:v1",
        "source_digest": "1" * 64,
        "source_retrieved_at": "2026-07-11T00:00:00Z",
        "normalized_floorplan_ref": "fixture:floorplan:property-example:v1",
        "room_graph_ref": "fixture:room-graph:property-example:v1",
        "walkable_mesh_ref": "fixture:walkable-mesh:property-example:v1",
        "portal_graph_ref": "fixture:portal-graph:property-example:v1",
        "scale_m_per_unit": 1.0,
        "orientation_degrees": 0.0,
        "license_provenance_refs": ["fixture:license:first-party:v1"],
        "source_media_assignments": [],
        "inaccessible_rooms": [],
        "route_exclusions": [],
        "rooms": [
            {
                "room_id": "living",
                "room_type": "living",
                "walkable": True,
                "boundary_ref": "fixture:boundary:living:v1",
                "ceiling_height_m": 2.7,
                "geometry_anchor_ref": "fixture:geometry:living:v1",
                "texture_anchor_refs": ["fixture:texture:living:v1"],
            },
            {
                "room_id": "bathroom",
                "room_type": "bathroom",
                "walkable": True,
                "boundary_ref": "fixture:boundary:bathroom:v1",
                "ceiling_height_m": 2.7,
                "geometry_anchor_ref": "fixture:geometry:bathroom:v1",
                "texture_anchor_refs": ["fixture:texture:bathroom:v1"],
            },
        ],
        "portals": [
            {
                "portal_id": "fixture-door-living-bathroom",
                "from_room_id": "living",
                "to_room_id": "bathroom",
                "walkable": True,
            }
        ],
        "route_room_ids": ["living", "bathroom"],
        "existing_artifacts": {
            "continuous_walkthrough": {
                "artifact_ref": "fixture:artifact:continuous-walkthrough:v1",
                "sha256": "2" * 64,
                "proof_ref": "fixture:proof:continuous-walkthrough:v1",
            }
        },
    }


def _fixture_request() -> dict[str, object]:
    return {
        "contract_name": REQUEST_CONTRACT_NAME,
        "request_id": "26dd43ba-3a3b-44ae-bda2-e105aa3f7d91",
        "idempotency_key": "section18-spatial-compose-continuous-fixture-v1",
        "consumer": {
            "product": "propertyquarry",
            "tenant_ref": "fixture:tenant:propertyquarry",
            "subject_ref": "fixture:subject:property-example",
        },
        "artifact": {"kind": "continuous_walkthrough", "purpose": "walkthrough", "locale": "en-AT"},
        "source_packet_ref": "fixture:spatial-source:property-example:v1",
        "truth_refs": ["fixture:truth:property-example:v1"],
        "evidence_refs": ["fixture:evidence:property-example:v1"],
        "spatial_plan": {
            "room_graph_ref": "fixture:room-graph:property-example:v1",
            "walkable_mesh_ref": "fixture:walkable-mesh:property-example:v1",
            "portal_graph_ref": "fixture:portal-graph:property-example:v1",
            "required_room_ids": ["living", "bathroom"],
            "route_policy": "continuous_all_walkable_rooms",
            "allow_revisit": False,
        },
        "style": {
            "style_pack_id": "botanical_maximalist_decorated_v1",
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
        "quota": {"consume_quota": False, "maximum_provider_attempts": 0},
        "callback": {"product_event_ref": "fixture:event:property-example:v1"},
    }


def build_checkpoint(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    private_root: Path = DEFAULT_PRIVATE_ROOT,
    evidence_path: Path = DEFAULT_3DVISTA_RECEIPT,
    design_review_output_path: Path = DEFAULT_DESIGN_REVIEW_OUTPUT,
    observed_at: datetime | None = None,
    focused_tests_passed: int = 0,
) -> dict[str, object]:
    now = (observed_at or _utc_now()).astimezone(UTC)
    authority_blocker: dict[str, object] | None = None
    try:
        design_review = build_design_review_receipt(
            output_path=design_review_output_path,
            observed_at=now,
        )
        review_verification = verify_design_review_receipt_payload(design_review)
        if review_verification["status"] != "pass":
            raise ValueError(
                "canonical_design_review_invalid:"
                + ",".join(str(issue) for issue in review_verification["issues"])
            )
        design_authority_status = CANONICAL_REVIEW_STATUS
        design_review_disposition = "revise"
        required_design_follow_up = (
            "complete_10_amendments_and_propertyquarry_authority_then_independent_re_review:"
            "ea-governed-spatial-render-contract-v1"
        )
    except ValueError as exc:
        authority_blocker = _canonical_authority_blocker(exc, observed_at=now)
        design_review = _blocked_design_review(authority_blocker, observed_at=now)
        design_authority_status = CANONICAL_SOURCE_VALIDATION_BLOCKED
        design_review_disposition = "unverified"
        required_design_follow_up = CANONICAL_AUTHORITY_FOLLOW_UP
    evidence_paths = {"3dvista": evidence_path} if evidence_path.is_file() else {}
    signing_key = _load_or_create_fixture_signing_key(private_root)
    store = GovernedSpatialRenderReceiptStore(private_root / "receipts")
    service = GovernedSpatialRenderService(
        provider_evidence_paths=evidence_paths,
        receipt_store=store,
        signing_private_key=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(signing_key)),
        signing_key_ref="key:fixture:governed-spatial-checkpoint:v1",
        build_enabled=False,
    )
    composition = service.compose(
        _fixture_request(),
        source_packet=_fixture_source_packet(),
        observed_at=now,
    )
    build = service.build(
        composition_digest=str(composition["composition_digest"]),
        composition_signature=str(composition["composition_signature"]),
        build_idempotency_key="section18-spatial-build-continuous-fixture-v1",
        consume_quota=False,
        maximum_provider_attempts=0,
        quota_authorization_ref="fixture:quota-authorization:not-granted",
        audit_event_ref="fixture:audit:spatial-build:v1",
        observed_at=now,
    )
    capability_index = service.capability_index(observed_at=now)
    capability_index["design_authority_status"] = design_authority_status
    capability_index["design_review_disposition"] = design_review_disposition
    eta_delivery_receipt = _json_object(ETA_TELEGRAM_RECEIPT)
    scope_completed = [
        "local_design_petition",
        "canonical_design_petition_routed",
        "draft_provider_neutral_contract_and_source_schemas",
        "receipt_derived_capability_index",
        "zero_burn_signed_composition_fixture",
        "preacceptance_blocked_build_fixture",
        "persistent_idempotency_and_integrity_store",
        "continuous_all_walkable_room_validation",
        "recursive_chummer_overlay_boundary",
        "draft_style_pack_registry",
        "local_quality_contract_verifiers",
    ]
    if authority_blocker is None:
        scope_completed.insert(2, "independent_design_review_revise_decision_hash_bound")
    else:
        scope_completed.insert(2, "canonical_design_source_drift_detected_fail_closed")
    body: dict[str, Any] = {
        "contract_name": "ea.governed_spatial_render_section18_checkpoint.v1",
        "generated_at": _utc_iso(now),
        "status": "intermediate_blocked",
        "scope_completed": scope_completed,
        "scope_not_completed": [
            "canonical_revision_amendments",
            "propertyquarry_hash_bound_authority_decision",
            "independent_design_re_review_acceptance",
            "provider_execution_adapters",
            "product_bridge_registration",
            "trusted_immutable_artifact_verifier",
            "accepted_propertyquarry_style_walkthroughs",
            "accepted_chummer_runsite_walkthroughs",
            "post_ea_integration_desktop_mobile_browser_performance_gate",
            "telegram_style_video_delivery",
            "isolated_candidate_deployment",
            "48_hour_canary",
        ],
        "files_changed_by_repo": {
            "ea": [
                "EA_GOVERNED_SPATIAL_RENDER_DESIGN_PETITION.md",
                "ea/app/data/governed_spatial_capabilities.v1.json",
                "ea/app/data/governed_spatial_render_request.schema.v1.json",
                "ea/app/data/governed_spatial_source_packet.schema.v1.json",
                "ea/app/data/governed_spatial_style_packs.v1.json",
                "ea/app/services/governed_spatial_render.py",
                "ea/app/services/governed_spatial_quality.py",
                "scripts/materialize_governed_spatial_render_checkpoint.py",
                "scripts/materialize_governed_spatial_render_design_review.py",
                "scripts/verify_governed_spatial_render_checkpoint.py",
                "tests/test_governed_spatial_render.py",
                "tests/test_governed_spatial_quality.py",
                "tests/test_governed_spatial_render_checkpoint.py",
                "tests/test_governed_spatial_render_design_review.py",
                "_completion/governed-spatial-render/EA_GOVERNED_SPATIAL_RENDER_CHECKPOINT.generated.json",
                "_completion/governed-spatial-render/GOVERNED_SPATIAL_RENDER_DESIGN_REVIEW_RECEIPT.generated.json",
                "_completion/governed-spatial-render/ETA_TELEGRAM_DELIVERY.generated.json"
            ],
            "propertyquarry": [],
            "chummer": [
                "chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_PETITION_DECISION.md"
            ],
        },
        "design_authority_status": design_authority_status,
        "design_authority_blocker": authority_blocker,
        "canonical_design_review": design_review,
        "capability_index": capability_index,
        "contract_version": "2026-07-11-draft",
        "example_compose_receipt": composition,
        "example_build_receipt": build,
        "receipt_store_integrity": store.integrity_summary(),
        "provider_execution": {
            "jobs_attempted": 0,
            "credits_consumed": 0,
            "quota_authorized": False,
        },
        "artifacts": [
            _asset_row(
                "PropertyQuarry curated diorama candidate",
                PROPERTYQUARRY_DIORAMA,
                provenance_ref="propertyquarry:source-listing:846238136:candidate:d907fa5b6b5d7308",
                accepted=False,
            ),
            _asset_row(
                "Botanical style visual direction seed",
                BOTANICAL_SEED,
                provenance_ref="generated-image:botanical-direction:2026-07-11",
                accepted=False,
            ),
            _asset_row(
                "Scandinavian interim KALLAX visual direction seed",
                SCANDINAVIAN_INTERIM_SEED,
                provenance_ref="generated-image:scandinavian-interim-kallax:2026-07-11",
                accepted=False,
            ),
        ],
        "quality_metrics": {
            "product_walkthrough_artifact_accepted": False,
            "room_coverage_percent": None,
            "cut_count": None,
            "teleport_or_jump_count": None,
            "delivery_fps": None,
            "effective_motion_fps": None,
            "rotation_status": "not_measured_on_accepted_product_artifact",
            "spatial_drift_status": "not_measured_on_accepted_product_artifact",
            "fixture_contract_room_coverage_percent": composition["quality_contract"]["room_coverage_percent"],
            "fixture_contract_cut_count": composition["quality_contract"]["cut_count"],
            "fixture_contract_teleport_count": composition["quality_contract"]["teleport_count"],
        },
        "browser_receipts": {
            "pre_ea_3dvista_receipt_path": str(evidence_path),
            "pre_ea_3dvista_receipt_exists": evidence_path.is_file(),
            "pre_ea_3dvista_receipt_sha256": _file_sha256(evidence_path) if evidence_path.is_file() else "",
            "post_ea_desktop_receipt": "not_run",
            "post_ea_mobile_receipt": "not_run",
            "performance_baseline_receipt": "missing",
        },
        "tests": {
            "focused_passed": focused_tests_passed,
            "focused_failed": 0,
            "cross_repo_tests_run": False,
            "browser_tests_run_after_ea_integration": False,
        },
        "style_videos": [],
        "telegram_delivery_receipts": [],
        "eta_telegram_delivery_receipts": [eta_delivery_receipt] if eta_delivery_receipt is not None else [],
        "canary": {"status": "not_started", "start": "", "end": "", "incidents": []},
        "assumptions_and_risks": [
            (
                "Canonical authority inputs drifted; current acceptance cannot be verified and implementation remains blocked."
                if authority_blocker is not None
                else "Canonical design authority returned revise; implementation remains blocked."
            ),
            "The ten canonical amendments and PropertyQuarry authority decision are incomplete.",
            "No trusted immutable artifact verifier exists, so ready projection is impossible.",
            "Current 3DVista evidence predates EA bridge integration and lacks the full baseline FPS profile.",
            "MagicFit and OMagic/MagicAI remain degraded or unverified for the requested artifact families.",
            "No accepted flagship walkthrough or style video exists.",
        ],
        "required_design_follow_up": required_design_follow_up,
        "live_untouched": True,
        "propertyquarry_live_untouched": True,
        "chummer_live_untouched": True,
        "launch_recommendation": "no",
    }
    receipt = {**body, "receipt_digest": _sha256_json(body)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    output_path.chmod(0o600)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize the fail-closed governed spatial-render checkpoint.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_3DVISTA_RECEIPT)
    parser.add_argument("--design-review-output", type=Path, default=DEFAULT_DESIGN_REVIEW_OUTPUT)
    parser.add_argument("--observed-at")
    parser.add_argument("--focused-tests-passed", type=int, default=0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    receipt = build_checkpoint(
        output_path=args.output,
        private_root=args.private_root,
        evidence_path=args.evidence,
        design_review_output_path=args.design_review_output,
        observed_at=_parse_time(args.observed_at),
        focused_tests_passed=max(0, args.focused_tests_passed),
    )
    print(json.dumps({"status": receipt["status"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
