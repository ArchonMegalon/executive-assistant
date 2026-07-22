from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import governed_spatial_render as routes
from app.services.governed_spatial_crypto import Ed25519EnvelopeSigner


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def _signer() -> Ed25519EnvelopeSigner:
    return Ed25519EnvelopeSigner.from_seed(
        bytes(range(32)),
        issuer="api-test-issuer",
        environment="test",
        key_ref="key:api:test:1",
        key_epoch=1,
        not_before="2026-07-10T00:00:00Z",
        not_after="2026-07-13T00:00:00Z",
    )


def _source_packet() -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_source_packet.v1",
        "source_packet_ref": "packet:test:tour:1",
        "source_digest": "a" * 64,
        "source_retrieved_at": "2026-07-11T10:00:00Z",
        "normalized_floorplan_ref": "artifact:test:floorplan:1",
        "room_graph_ref": "geometry:test:rooms:1",
        "walkable_mesh_ref": "geometry:test:mesh:1",
        "portal_graph_ref": "geometry:test:portals:1",
        "scale_m_per_unit": 1.0,
        "orientation_degrees": 90.0,
        "license_provenance_refs": ["provenance:test:license:1"],
        "source_media_assignments": [],
        "inaccessible_rooms": [],
        "route_exclusions": [],
        "rooms": [
            {
                "room_id": "living",
                "room_type": "living",
                "walkable": True,
                "boundary_ref": "geometry:test:living:boundary",
                "ceiling_height_m": 2.7,
                "geometry_anchor_ref": "geometry:test:living:anchor",
                "texture_anchor_refs": ["texture:test:living:1"],
            },
            {
                "room_id": "bedroom",
                "room_type": "bedroom",
                "walkable": True,
                "boundary_ref": "geometry:test:bedroom:boundary",
                "ceiling_height_m": 2.7,
                "geometry_anchor_ref": "geometry:test:bedroom:anchor",
                "texture_anchor_refs": ["texture:test:bedroom:1"],
            },
        ],
        "portals": [
            {
                "portal_id": "door-living-bedroom",
                "from_room_id": "living",
                "to_room_id": "bedroom",
                "walkable": True,
            }
        ],
        "route_room_ids": ["living", "bedroom"],
        "existing_artifacts": {},
    }


def _render_request() -> dict[str, object]:
    return {
        "contract_name": "ea.governed_spatial_render_request.v1",
        "request_id": "3d0dfa6e-27bb-48d1-b00b-7675ae02416f",
        "idempotency_key": "api-tour-test-1",
        "consumer": {
            "product": "consumer-test",
            "tenant_ref": "tenant:test:1",
            "subject_ref": "subject:test:1",
        },
        "artifact": {
            "kind": "continuous_walkthrough",
            "purpose": "walkthrough",
            "locale": "en-AT",
        },
        "source_packet_ref": "packet:test:tour:1",
        "truth_refs": ["truth:test:tour:1"],
        "evidence_refs": ["evidence:test:tour:1"],
        "spatial_plan": {
            "room_graph_ref": "geometry:test:rooms:1",
            "walkable_mesh_ref": "geometry:test:mesh:1",
            "portal_graph_ref": "geometry:test:portals:1",
            "required_room_ids": ["living", "bedroom"],
            "route_room_ids": ["living", "bedroom"],
            "portal_edges": [{"from_room_id": "living", "to_room_id": "bedroom"}],
            "route_policy": "continuous_all_walkable_rooms",
            "allow_revisit": False,
        },
        "style": {
            "style_pack_id": "style:test:1",
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
        "callback": {"product_event_ref": "event:test:tour:1"},
    }


def _runtime(root: Path) -> routes.GovernedSpatialApiRuntime:
    return routes.build_governed_spatial_api_runtime(
        ledger_root=root,
        signer=_signer(),
        now=lambda: NOW,
    )


def _client(runtime: routes.GovernedSpatialApiRuntime | None = None) -> TestClient:
    app = FastAPI()
    if runtime is not None:
        app.state.governed_spatial_runtime_factory = lambda: runtime
    app.include_router(routes.router)
    return TestClient(app)


def _compose(client: TestClient, *, request: dict[str, object] | None = None, source: dict[str, object] | None = None):
    return client.post(
        "/v1/internal/governed-spatial-render/compose",
        json={"request": request or _render_request(), "source_packet": source or _source_packet()},
    )


def test_default_app_keeps_governed_spatial_http_operations_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "")
    from app.api.app import create_app

    operation_paths = {route.path for route in create_app().routes}

    assert "/v1/internal/governed-spatial-render/compose" not in operation_paths
    assert "/v1/internal/governed-spatial-render/build" not in operation_paths


def test_runtime_is_explicit_and_unconfigured_route_fails_closed() -> None:
    response = _client().post(
        "/v1/internal/governed-spatial-render/compose",
        json={"request": _render_request(), "source_packet": _source_packet()},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "governed_spatial_runtime_unconfigured"}
    assert not hasattr(routes, "_SERVICE")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b'{"request":{"nested":{"same":1,"same":2}},"source_packet":{}}', "duplicate_member"),
        (b'{"request":{"text":"\\ud800"},"source_packet":{}}', "invalid_unicode"),
        (b"\xff", "invalid_utf8"),
    ],
)
def test_compose_raw_ingress_rejects_ambiguous_or_invalid_unicode_before_orchestration(
    tmp_path: Path,
    raw: bytes,
    reason: str,
) -> None:
    response = _client(_runtime(tmp_path / "ledger")).post(
        "/v1/internal/governed-spatial-render/compose",
        content=raw,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": reason}
    assert not (tmp_path / "ledger" / "compositions").exists()


def test_compose_rejects_unknown_top_level_fields(tmp_path: Path) -> None:
    response = _client(_runtime(tmp_path / "ledger")).post(
        "/v1/internal/governed-spatial-render/compose",
        json={"request": _render_request(), "source_packet": _source_packet(), "private_url": "hidden"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "unexpected_fields"}


@pytest.mark.parametrize("raw", [b"[]", b'"not-an-object"', b"null"])
def test_raw_ingress_rejects_non_object_roots(tmp_path: Path, raw: bytes) -> None:
    response = _client(_runtime(tmp_path / "ledger")).post(
        "/v1/internal/governed-spatial-render/compose",
        content=raw,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "root_object_required"}


def test_compose_uses_durable_orchestrator_and_returns_only_provider_safe_audit_projection(tmp_path: Path) -> None:
    response = _compose(_client(_runtime(tmp_path / "ledger")))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["state"] == "audit_only"
    assert payload["audit_only"] is True
    assert payload["executable"] is False
    assert payload["execution_target_binding"] == "unbound"
    assert payload["quota_mutated"] is False
    assert payload["provider_job_enqueued"] is False
    assert payload["provider_details_exposed"] is False
    assert payload["composition_digest"].startswith("sha256:")
    serialized = json.dumps(payload, sort_keys=True).lower()
    for forbidden in (
        "signature",
        "key:api:test:1",
        "packet:test:tour:1",
        "geometry:test",
        "event:test:tour:1",
        "provider_route_digest",
        "private_url",
    ):
        assert forbidden not in serialized


def test_compose_restart_replay_is_idempotent_and_changed_material_conflicts(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    first = _compose(_client(_runtime(ledger_root)))
    restarted = _compose(_client(_runtime(ledger_root)))
    changed_source = _source_packet()
    changed_source["source_digest"] = "b" * 64
    conflict = _compose(_client(_runtime(ledger_root)), source=changed_source)

    assert first.status_code == 200
    assert restarted.status_code == 200
    assert restarted.json()["idempotent_replay"] is True
    assert restarted.json()["composition_digest"] == first.json()["composition_digest"]
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "idempotency_conflict"}


def test_build_defaults_to_blocked_without_registry_or_side_effect_adapters(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "ledger")
    client = _client(runtime)
    composition = _compose(client).json()
    authorization = {
        "schema_name": "ea.governed_spatial_render_build_authorization.v1",
        "accepted_composition_digest": composition["composition_digest"],
        "idempotency_key": "api-build-test-1",
        "requested_by_ref": "owner:test:1",
        "authorization_ref": "authorization:test:1",
        "audit_event_ref": "audit:test:1",
        "consume_quota": True,
        "maximum_provider_attempts": 1,
        "issued_at": (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "quota_limit_digest": "c" * 64,
    }

    response = client.post(
        "/v1/internal/governed-spatial-render/build",
        json={"authorization": authorization, "evidence_envelope": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "blocked"
    assert payload["publication_allowed"] is False
    assert payload["serving_allowed"] is False
    assert payload["provider_details_exposed"] is False
    assert payload["quota_details_exposed"] is False
    assert payload["product_projection"]["state"] == "blocked"
    assert "output_manifest_ref" not in json.dumps(payload)
    assert "authorization:test:1" not in json.dumps(payload)


def test_build_requires_explicit_consume_quota_and_duplicate_safe_evidence(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "ledger")
    client = _client(runtime)
    composition = _compose(client).json()
    authorization = {
        "schema_name": "ea.governed_spatial_render_build_authorization.v1",
        "accepted_composition_digest": composition["composition_digest"],
        "idempotency_key": "api-build-test-2",
        "requested_by_ref": "owner:test:1",
        "authorization_ref": "authorization:test:1",
        "audit_event_ref": "audit:test:1",
        "consume_quota": False,
        "maximum_provider_attempts": 1,
        "issued_at": "2026-07-11T11:59:00Z",
        "expires_at": "2026-07-11T12:10:00Z",
        "quota_limit_digest": "d" * 64,
    }

    rejected = client.post(
        "/v1/internal/governed-spatial-render/build",
        json={"authorization": authorization, "evidence_envelope": {}},
    )
    duplicate = client.post(
        "/v1/internal/governed-spatial-render/build",
        content=b'{"authorization":{},"evidence_envelope":{"nested":{"x":1,"x":2}}}',
        headers={"content-type": "application/json"},
    )

    assert rejected.status_code == 422
    assert duplicate.status_code == 422
    assert duplicate.json() == {"detail": "duplicate_member"}


def test_projection_helpers_drop_private_artifact_and_receipt_fields() -> None:
    projection = routes._build_projection(
        {
            "state": "closed_consumed",
            "composition_digest": "sha256:" + "a" * 64,
            "output_manifest_ref": "private:manifest:1",
            "authorization": {"authorization_ref": "private:auth:1"},
            "product_projection": {
                "state": "complete_internal",
                "reason": "",
                "progress_percent": 100,
                "output_manifest_ref": "private:manifest:1",
                "artifact_ref": "private:artifact:1",
                "private_url": "https://private.invalid/task",
                "authorization": {"raw": "secret"},
                "future_nested": {
                    "provider_account": "account:private",
                    "evidence": [{"signed_payload": "private"}],
                },
                "serving_allowed": False,
            },
        }
    )

    serialized = json.dumps(projection)
    assert "private:" not in serialized
    assert "private.invalid" not in serialized
    assert "authorization" not in serialized
    assert "provider_account" not in serialized
    assert "signed_payload" not in serialized
    assert projection["publication_allowed"] is False
    assert projection["serving_allowed"] is False

    poisoned = routes._build_projection(
        {
            "state": "private_url:https://private.invalid",
            "composition_digest": "https://private.invalid/composition",
            "product_projection": {
                "state": "blocked",
                "reason": "private:url",
                "progress_percent": "100",
            },
        }
    )
    assert poisoned["state"] == "blocked"
    assert poisoned["composition_digest"] == ""
    assert poisoned["product_projection"]["reason"] == ""
    assert "private.invalid" not in json.dumps(poisoned)
