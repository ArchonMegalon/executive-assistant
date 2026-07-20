from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cleanup_manfred_memorial_candidates as retention
from scripts import manfred_candidate_registry as registry


REVISION = "a" * 40
IMAGE_ID = f"sha256:{'b' * 64}"
PROJECT = "ea-manfred-candidate-abcdef12"
OBSERVED_AT = "2026-07-20T00:10:00Z"


def _image_build_binding() -> dict[str, object]:
    return {
        "receipt_schema": "ea.manfred_memorial_image_build.v3",
        "receipt_path": "/var/lib/ea/manfred-image-build.json",
        "receipt_sha256": "5" * 64,
        "image_tag": f"ea-runtime:manfred-{REVISION}",
        "image_id": IMAGE_ID,
        "runtime_source_revision": REVISION,
        "producer_sha256": "6" * 64,
        "image_reused": False,
        "authority": {},
    }


def _authority_row(*, phase: str, boundary: str) -> dict[str, object]:
    return {
        "status": "pass",
        "phase": phase,
        "boundary": boundary,
        "contract_name": registry.CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME,
        "version": registry.CANDIDATE_VEXP_MUTATION_PERMIT_VERSION,
        "epoch_started_ms": 1_753_000_000_000,
        "qualified_at": "2026-07-20T00:00:00Z",
        "terminal_identity_sha256": "c" * 64,
        "qualification_certificate_schema": (
            registry.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
        ),
        "qualification_certificate_sha256": "d" * 64,
        "qualification_certificate_identity": f"sha256:{'e' * 64}",
        "qualification_certificate_event_hash": "f" * 64,
        "permit_sha256": "1" * 64,
        "permit_commit": {
            "contract_name": registry.VEXP_MUTATION_PERMIT_COMMIT_CONTRACT_NAME,
            "version": registry.VEXP_MUTATION_PERMIT_COMMIT_VERSION,
            "status": "committed",
            "sha256": "2" * 64,
        },
        "epoch_void_ledger": {
            "root": str(registry.VEXP_EPOCH_VOID_LEDGER_ROOT),
            "entry": str(
                registry.VEXP_EPOCH_VOID_LEDGER_ROOT / "1753000000000.json"
            ),
            "entry_present": False,
            "root_trusted": True,
        },
        "permit_issued_at": "2026-07-20T00:00:00Z",
        "permit_expires_at": "2026-07-20T00:30:00Z",
    }


def _authority_envelope() -> dict[str, object]:
    return {
        "entry": _authority_row(phase="entry", boundary="candidate_entry"),
        "mutations": [
            _authority_row(phase="pre_mutation", boundary=boundary)
            for boundary in registry.CANDIDATE_VEXP_MUTATION_SEQUENCE
        ],
        "finalization": _authority_row(
            phase="finalization",
            boundary="candidate_receipt_publication",
        ),
        "cleanup_requires_positive_authority": True,
        "retention_timer_only_authority_free_cleanup": True,
    }


def _runtime_payload(*, schema: str = registry.RUNTIME_SCHEMA_V6) -> dict[str, object]:
    api_container = "3" * 64
    gateway_container = "4" * 64
    containers = {
        "api": {"container_id": api_container, "image_id": IMAGE_ID},
        "gateway": {"container_id": gateway_container, "image_id": IMAGE_ID},
        "prepared_image_id": IMAGE_ID,
        "revision_label": REVISION,
        "all_match_prepared_image": True,
    }
    return {
        "schema": schema,
        "status": "pass",
        "compose_project": PROJECT,
        "observed_at": OBSERVED_AT,
        "image": f"ea-runtime:manfred-{REVISION}",
        "image_id": IMAGE_ID,
        "image_source_revision": REVISION,
        "runtime_source_revision": REVISION,
        "runtime_authority_commit": REVISION,
        "candidate_port": 18091,
        "candidate_left_running_for_soak": True,
        "live_ea_api_unchanged": True,
        "promotion_authority": False,
        "provider_credentials_present": False,
        "provider_calls_performed": False,
        "gateway_has_runtime_secrets": False,
        "image_locator_evidence": {
            "locator": f"ea-runtime:manfred-{REVISION}",
            "resolved_image_id": IMAGE_ID,
            "revision_label": REVISION,
            "used_for_attestation_only": True,
            "consumed_by_compose": False,
        },
        "compose_uses_immutable_image_id": True,
        "runtime_version_identity": {
            "path": "/version",
            "status": 200,
            "commit_sha": REVISION,
            "body_commit_sha": REVISION,
            "source_revision_header": REVISION,
            "expected_commit_sha": REVISION,
            "oci_image_revision": REVISION,
            "repository": "EA",
            "role": "api",
            "release_authority_state": "clear",
            "release_authority_posture": "authoritative_runtime",
            "release_authority_source": "published_status_artifact",
            "commit_observed_over_http": True,
            "revision_agreement_verified": True,
        },
        "candidate_container_images": containers,
        "candidate_container_images_initial": containers,
        "candidate_container_images_final": containers,
        "candidate_container_image_identity_stable": True,
        "candidate_api_container_id": api_container,
        "image_build_authority_binding": _image_build_binding(),
        "vexp_candidate_mutation_authority": _authority_envelope(),
        "memorial_surface": registry.MEMORIAL_SURFACE,
        "spatial_scope": registry.SPATIAL_SCOPE,
        "public_property_tours_packaged": False,
        "public_property_tours_tested": False,
        "memorial_spatial_receipt_generated": False,
        "projection_files": [],
        "browser_surface": {
            "memorial_surface": registry.MEMORIAL_SURFACE,
            "spatial_scope": registry.SPATIAL_SCOPE,
        },
        "first_smoke_checks": ["conversation_only_public_surface"],
        "second_smoke_checks": ["conversation_only_public_surface"],
    }


def _stub_deep_runtime_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        registry,
        "_image_build_authority_binding",
        lambda _path, *, commit, image, image_id: {
            **_image_build_binding(),
            "runtime_source_revision": commit,
            "image_tag": image,
            "image_id": image_id,
        },
    )
    monkeypatch.setattr(
        registry,
        "_validated_execution_inputs",
        lambda _payload, *, revision: {"revision": revision},
    )
    monkeypatch.setattr(
        registry,
        "_validated_runtime_projection",
        lambda _payload: {"status": "pass"},
    )
    monkeypatch.setattr(
        registry,
        "_validated_runtime_posture",
        lambda _payload, *, project, image_id, execution_inputs: {
            "project": project,
            "image_id": image_id,
            "execution_inputs": execution_inputs,
        },
    )


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def test_registry_registers_only_v6_and_marks_it_retention_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_deep_runtime_validators(monkeypatch)
    receipt = tmp_path / "candidate-v6.json"
    registry_path = tmp_path / "registry.json"
    _write_private_json(receipt, _runtime_payload())

    result = registry.register_candidate_receipt(
        receipt,
        registry_path=registry_path,
    )
    postures = registry.registered_candidate_receipt_postures(
        registry_path=registry_path
    )

    assert result["registered"] is True
    assert postures[0]["runtime_schema"] == registry.RUNTIME_SCHEMA_V6
    assert postures[0]["legacy"] is False
    assert postures[0]["retention_eligible"] is True
    assert postures[0]["quarantined"] is False

    legacy_receipt = tmp_path / "candidate-v5.json"
    _write_private_json(
        legacy_receipt,
        _runtime_payload(schema=registry.RUNTIME_SCHEMA_V5),
    )
    with pytest.raises(RuntimeError, match="legacy_receipt_forbidden"):
        registry.register_candidate_receipt(
            legacy_receipt,
            registry_path=registry_path,
        )


def test_registry_rejects_reordered_v6_mutation_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_deep_runtime_validators(monkeypatch)
    payload = _runtime_payload()
    authority = dict(payload["vexp_candidate_mutation_authority"])
    mutations = list(authority["mutations"])
    mutations[0], mutations[1] = mutations[1], mutations[0]
    authority["mutations"] = mutations
    payload["vexp_candidate_mutation_authority"] = authority

    with pytest.raises(RuntimeError, match="vexp_authority_invalid"):
        registry._runtime_identity(payload)


def test_registry_rejects_image_build_binding_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_deep_runtime_validators(monkeypatch)
    payload = _runtime_payload()
    binding = dict(payload["image_build_authority_binding"])
    binding["receipt_sha256"] = "7" * 64
    payload["image_build_authority_binding"] = binding

    with pytest.raises(RuntimeError, match="image_build_authority_invalid"):
        registry._runtime_identity(payload)


def test_registry_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    receipt = tmp_path / "duplicate.json"
    receipt.write_text('{"schema":"one","schema":"two"}\n', encoding="utf-8")
    receipt.chmod(0o600)

    with pytest.raises(RuntimeError, match="registry_json_invalid"):
        registry._read_private_json(receipt)


def test_retention_quarantines_v4_without_runtime_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory_calls = 0

    def empty_inventory() -> tuple[dict[str, object], ...]:
        nonlocal inventory_calls
        inventory_calls += 1
        return ()

    monkeypatch.setattr(retention, "_container_inventory", empty_inventory)
    report = retention._evaluate_locked(
        postures=[
            {
                "project": PROJECT,
                "runtime_schema": registry.RUNTIME_SCHEMA_V4,
                "legacy": True,
            }
        ],
        apply=False,
        sample_spacing_seconds=1.0,
        sleep=lambda _seconds: None,
        lock_evidence={"status": "pass"},
    )

    assert inventory_calls == 2
    assert report["candidates"] == [
        {
            "project": PROJECT,
            "runtime_schema": registry.RUNTIME_SCHEMA_V4,
            "qualification": "ineligible",
            "quarantined": True,
            "quarantine_reason": "legacy_runtime_receipt_v4",
            "automatic_retirement_authorized": False,
        }
    ]
