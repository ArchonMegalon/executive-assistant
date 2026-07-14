from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import materialize_flagship_cross_release_receipt as materialize


GENERATED_AT = "2026-07-14T00:00:00Z"
MANFRED_COMMIT = "3" * 40
MANFRED_TREE = "4" * 40
MANFRED_IMAGE = "sha256:" + "5" * 64
MANFRED_PROJECT = "ea-manfred-candidate-34bda8ef-205440"
EA_IMAGE = "sha256:" + "6" * 64
EA_PROJECT = "ea-core-candidate-72281ba6-20260714"
EA_DEPLOYMENT = "deploy-20260714-ea-core-72281ba6"
SECRET = "fixture-secret-that-must-never-be-projected"


def _write_json(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    path.chmod(mode)
    return hashlib.sha256(raw).hexdigest()


def _git_repo(path: Path) -> tuple[str, str]:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", os.fspath(path)], check=True)
    subprocess.run(["git", "-C", os.fspath(path), "config", "user.name", "Fixture"], check=True)
    subprocess.run(
        ["git", "-C", os.fspath(path), "config", "user.email", "fixture@example.invalid"],
        check=True,
    )
    (path / "source.txt").write_text("bound source\n", encoding="utf-8")
    subprocess.run(["git", "-C", os.fspath(path), "add", "source.txt"], check=True)
    subprocess.run(["git", "-C", os.fspath(path), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(
        ["git", "-C", os.fspath(path), "rev-parse", "HEAD"], text=True
    ).strip()
    subprocess.run(
        [
            "git",
            "-C",
            os.fspath(path),
            "update-ref",
            "refs/remotes/origin/main",
            commit,
        ],
        check=True,
    )
    tree = subprocess.check_output(
        ["git", "-C", os.fspath(path), "show", "-s", "--format=%T", "HEAD"], text=True
    ).strip()
    return commit, tree


def _fixture(tmp_path: Path) -> dict[str, Any]:
    evidence_root = tmp_path / "evidence"
    repository = tmp_path / "repo"
    ea_commit, ea_tree = _git_repo(repository)
    paths = {
        spec.key: evidence_root / f"{spec.key}.json"
        for spec in materialize.EVIDENCE_SPECS
    }

    runtime_hash = _write_json(
        paths["manfred_runtime"],
        {
            "schema": "ea.manfred_memorial_candidate_runtime.v3",
            "status": "pass",
            "image_source_revision": MANFRED_COMMIT,
            "runtime_source_revision": MANFRED_COMMIT,
            "image_id": MANFRED_IMAGE,
            "compose_project": MANFRED_PROJECT,
            "promotion_authority": False,
            "api_token": SECRET,
        },
    )
    transport_hash = _write_json(
        paths["manfred_transport"],
        {
            "schema": "ea.manfred_memorial_transport_adversarial.v1",
            "status": "pass",
            "commit": MANFRED_COMMIT,
            "image_id": MANFRED_IMAGE,
            "compose_project": MANFRED_PROJECT,
            "promotion_authority": False,
        },
    )
    _write_json(
        paths["manfred_release"],
        {
            "schema": "ea.flagship.manfred_memorial_release.v1",
            "status": "pass",
            "source": {
                "commit": MANFRED_COMMIT,
                "tree": MANFRED_TREE,
                "worktree_clean": True,
            },
            "artifact": {
                "image_id": MANFRED_IMAGE,
                "private_memorial_context_baked": False,
                "provider_credentials_baked": False,
            },
            "candidate": {
                "compose_project": MANFRED_PROJECT,
                "healthy": True,
                "runtime_receipt_sha256": runtime_hash,
            },
            "publication_boundary": {
                "soak_qualification_reset_at": "2026-07-13T18:33:33Z",
                "earliest_no_reset_soak_end": "2026-07-20T18:33:33Z",
                "fresh_activation_token_required": True,
                "real_deployment_id_required": True,
            },
            "transport": {"receipt_sha256": transport_hash},
            "browser": {
                "status": "pass",
                "external_requests": 0,
                "provider_requests": 0,
                "page_errors": 0,
            },
            "acceptance": {
                "memorial_security_contracts": {"status": "pass"},
                "deployment_and_builder_contracts": {"status": "pass"},
            },
            "secrets_included": False,
        },
    )
    _write_json(
        paths["manfred_live_boundary"],
        {
            "schema": "ea.manfred_memorial_post_retention_boundary.v2",
            "status": "pass",
            "candidate": {
                "commit": MANFRED_COMMIT,
                "image_id": MANFRED_IMAGE,
                "compose_project": MANFRED_PROJECT,
                "services_healthy": 4,
                "container_restarts": 0,
                "oom_kills": 0,
            },
            "guard": {
                "active_state": "active",
                "sub_state": "running",
                "soak_qualification_reset_at": "2026-07-13T18:33:33Z",
                "earliest_no_reset_soak_end": "2026-07-20T18:33:33Z",
                "fresh_activation_token_required": True,
                "real_deployment_id_required": True,
            },
            "public_routes": {
                "https://myexternalbrain.com/memorials/manfred": {
                    "status": 404,
                    "tls_verified": True,
                },
                "https://myexternalbrain.com/memorial/manfred": {
                    "status": 404,
                    "tls_verified": True,
                },
            },
            "promotion_authority": False,
            "live_mutation_performed": False,
            "secrets_included": False,
        },
    )

    browser_checks = {
        "navigation_http_200": True,
        "webgl_context_present": True,
        "orbit_interaction_moves_camera": True,
        "dollhouse_mode_polished": True,
        "room_view_works": True,
        "guided_route_works": True,
        "no_external_requests": True,
        "no_http_or_browser_errors": True,
    }
    interaction_hash = _write_json(
        paths["property_3d_interaction"],
        {
            "schema": "propertyquarry.generated_reconstruction.browser_proof.v2",
            "status": "pass",
            "scope": "offline_loopback_candidate_only",
            "truth": {
                "provider": "propertyquarry_generated_reconstruction",
                "verified_provider_capture": False,
                "satisfies_verified_tour_gate": False,
                "preview_kind_marker": "approximate-layout",
            },
            "browser_proof": {
                "desktop": {"status": "pass", "checks": browser_checks},
                "mobile": {"status": "pass", "checks": browser_checks},
            },
            "vendor_compliance": {"status": "pass"},
            "live_publish_performed": False,
        },
    )
    _write_json(
        paths["property_3d_release"],
        {
            "schema": "ea.flagship.property_3d_release.v1",
            "status": "pass",
            "source": {"commit": "7" * 40, "tree": "8" * 40, "worktree_clean": True},
            "truth": {
                "scope": "offline_loopback_candidate_only",
                "provider": "propertyquarry_generated_reconstruction",
                "preview_kind": "approximate_layout",
                "floorplan_only_disclosure_present": True,
                "verified_provider_capture": False,
                "satisfies_verified_tour_gate": False,
                "provider_calls_performed": False,
                "provider_credits_consumed": False,
                "live_publish_performed": False,
            },
            "viewer": {
                "webgl": True,
                "orbit": True,
                "dollhouse": True,
                "room_view": True,
                "guided_route": True,
                "self_hosted_three": True,
                "vendor_license_and_integrity": "pass",
            },
            "browser_evidence": {
                "receipt_sha256": interaction_hash,
                "external_request_count": 0,
                "browser_error_count": 0,
                "desktop_screenshot_sha256": "9" * 64,
                "mobile_screenshot_sha256": "a" * 64,
            },
            "secrets_included": False,
        },
    )

    _write_json(
        paths["ea_operator_readiness"],
        {
            "contract_name": "ea.operator_readiness.v1",
            "status": "ready",
            "ready": True,
            "attention_required_count": 0,
            "blocked_count": 0,
            "probe_failed_count": 0,
        },
    )
    _write_json(
        paths["localization_projection"],
        {
            "contract_name": "ea.chummer_localization_projection.v1",
            "contract_version": 1,
            "status": "blocked_contradictory_evidence",
            "petition_required": True,
            "blocker_mutation_allowed": False,
        },
    )
    _write_json(
        paths["lived_system_observation"],
        {
            "contract_name": "ea.chummer_lived_system_observation",
            "contract_version": "1.0.0",
            "status": "attention_required",
            "authoritative": False,
            "release_decision": None,
        },
    )
    _write_json(
        paths["chummer_flagship_readiness"],
        {
            "contract_name": "fleet.flagship_product_readiness",
            "status": "fail",
            "scoped_status": "fail",
        },
        mode=0o664,
    )
    _write_json(
        paths["chummer_weekly_pulse"],
        {
            "contract_name": "chummer.weekly_product_pulse",
            "flagship_readiness": {"proof_status": "fail"},
            "release_health": {"state": "needs_attention"},
            "governor_decisions": [{"action": "freeze_launch"}],
        },
        mode=0o644,
    )
    _write_json(
        paths["chummer_journey_gates"],
        {
            "contract_name": "fleet.journey_gates",
            "summary": {
                "overall_state": "ready",
                "total_journey_count": 6,
                "ready_count": 6,
                "warning_count": 0,
                "blocked_count": 0,
            },
        },
        mode=0o600,
    )
    _write_json(
        paths["chummer_release_ready"],
        {
            "contract_name": "chummer.release_ready",
            "status": "fail",
            "verdict": "NOT_RELEASE_READY",
        },
        mode=0o664,
    )

    _write_json(
        paths["ea_core_runtime"],
        {
            "contract_name": "ea.core_candidate_runtime_verification.v1",
            "status": "pass",
            "issues": [],
            "request": {
                "compose_project": EA_PROJECT,
                "expected_image_ref": "ea-runtime:core-bound",
                "expected_image_id": EA_IMAGE,
                "expected_source_revision": ea_commit,
            },
            "scope": {"inspection_only": True, "runtime_mutations": False},
            "privacy": {
                "environment_values_emitted": False,
                "secret_values_emitted": False,
                "raw_http_bodies_emitted": False,
                "raw_subprocess_output_emitted": False,
            },
        },
    )
    _write_json(
        paths["ea_release_authority"],
        {
            "contract_name": "ea.release_authority_status.v1",
            "state": "clear",
            "authority_posture": "authoritative_runtime",
            "issues": [],
            "commit_sha": ea_commit,
            "tracking_branch": "origin/main",
            "source_remote_ref": "refs/remotes/origin/main",
            "source_remote_ref_commit_sha": ea_commit,
            "source_remote_ref_evidence": "local_remote_tracking_ref",
            "source_commit_reachable_from_remote_ref": True,
            "deployment_id": EA_DEPLOYMENT,
            "deployment_id_source": "deployment_system",
            "source_worktree_dirty": False,
            "source_dirty_count": 0,
            "gate": {
                "contract_name": "ea.release_authority_gate.v1",
                "status": "pass",
                "authority_posture": "authoritative_runtime",
                "issues": [],
                "commit_sha": ea_commit,
                "source_remote_ref": "refs/remotes/origin/main",
                "source_remote_ref_commit_sha": ea_commit,
                "source_remote_ref_evidence": "local_remote_tracking_ref",
                "source_commit_reachable_from_remote_ref": True,
                "deployment_id": EA_DEPLOYMENT,
            },
            "deploy_context_gate": {
                "contract_name": "ea.deploy_context_gate.v1",
                "status": "pass",
                "issues": [],
                "commit_sha": ea_commit,
                "deployment_id": EA_DEPLOYMENT,
            },
        },
    )
    return {
        "paths": paths,
        "repository": repository,
        "ea_commit": ea_commit,
        "ea_tree": ea_tree,
    }


def _build(fixture: dict[str, Any]) -> dict[str, object]:
    return materialize.build_receipt(
        paths=fixture["paths"],
        generated_at=GENERATED_AT,
        ea_commit=fixture["ea_commit"],
        ea_tree=fixture["ea_tree"],
        ea_image_id=EA_IMAGE,
        ea_compose_project=EA_PROJECT,
        ea_deployment_id=EA_DEPLOYMENT,
        ea_repository=fixture["repository"],
    )


def test_current_valid_evidence_is_deterministic_honest_and_secret_free(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    first = _build(fixture)
    second = _build(fixture)

    assert first == second
    assert first["schema"] == materialize.CONTRACT_NAME
    assert first["status"] == "blocked"
    assert first["safe_to_promote_now"] is False
    assert first["launch_state"] == "candidate_launch_ready_promotion_guarded"
    assert first["evidence_validation"] == {
        "status": "pass",
        "input_count": 15,
        "regular_files_only": True,
        "json_object_roots_only": True,
        "schema_identities_exact": True,
        "sha256_and_mode_bound": True,
        "cross_receipt_identity_bindings_exact": True,
        "ea_git_commit_tree_binding_exact": True,
        "ea_source_remote_ref_binding_exact": True,
    }
    property_projection = first["property_3d_tour_generation"]
    assert property_projection["polished_reconstruction_ready"] is True
    assert property_projection["classification"] == "polished_floorplan_derived_approximate_reconstruction"
    assert property_projection["verified_provider_capture"] is False
    assert property_projection["satisfies_verified_provider_tour_gate"] is False
    blocker_codes = {item["code"] for item in first["launch_gate"]["blockers"]}
    assert {
        "manfred_uninterrupted_soak_incomplete",
        "manfred_fresh_activation_token_required",
        "manfred_real_deployment_id_required",
        "manfred_public_routes_not_activated",
        "property_verified_provider_capture_missing",
        "chummer_localization_projection_blocked",
        "chummer_lived_system_observation_requires_attention",
        "chummer_flagship_readiness_not_green",
        "chummer_weekly_launch_freeze",
        "chummer_release_ready_not_green",
    } <= blocker_codes
    rendered = json.dumps(first, sort_keys=True)
    assert SECRET not in rendered
    assert os.fspath(tmp_path) not in rendered
    assert all(
        materialize.SHA256_RE.fullmatch(str(binding["sha256"]))
        for binding in first["input_bindings"]
    )


def test_atomic_v2_write_is_mode_0600_and_never_touches_v1(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    receipt = _build(fixture)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir()
    v1 = output_dir / "flagship-cross-release-v1.json"
    v1_bytes = b'{"schema":"ea.flagship.cross_release_launch_readiness.v1"}\n'
    v1.write_bytes(v1_bytes)
    v2 = output_dir / materialize.OUTPUT_NAME

    materialize.write_receipt(v2, receipt)
    first_bytes = v2.read_bytes()
    materialize.write_receipt(v2, receipt)

    assert v2.read_bytes() == first_bytes
    assert stat.S_IMODE(v2.stat().st_mode) == 0o600
    assert v1.read_bytes() == v1_bytes
    with pytest.raises(materialize.EvidenceValidationError) as exc:
        materialize.write_receipt(v1, receipt)
    assert "output_name_must_be_v2" in exc.value.codes


def test_refuses_to_replace_legacy_schema_even_under_v2_filename(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    receipt = _build(fixture)
    output = tmp_path / materialize.OUTPUT_NAME
    _write_json(output, {"schema": materialize.LEGACY_CONTRACT_NAME})

    with pytest.raises(materialize.EvidenceValidationError) as exc:
        materialize.write_receipt(output, receipt)

    assert "output_refuses_non_v2_overwrite" in exc.value.codes


@pytest.mark.parametrize(
    ("key", "mutation", "expected_code"),
    (
        (
            "property_3d_interaction",
            "mode",
            "property_3d_interaction_mode_not_0600",
        ),
        (
            "chummer_weekly_pulse",
            "unsafe_mode",
            "chummer_weekly_pulse_mode_unsafe",
        ),
        (
            "manfred_transport",
            "identity",
            "manfred_transport_identity_invalid",
        ),
    ),
)
def test_invalid_mode_or_schema_fails_closed(
    tmp_path: Path,
    key: str,
    mutation: str,
    expected_code: str,
) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["paths"][key]
    if mutation == "mode":
        path.chmod(0o644)
    elif mutation == "unsafe_mode":
        path.chmod(0o666)
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema"] = "unexpected.contract"
        _write_json(path, payload)

    with pytest.raises(materialize.EvidenceValidationError) as exc:
        _build(fixture)

    assert expected_code in exc.value.codes


def test_symlinked_input_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["paths"]["ea_operator_readiness"]
    target = path.with_suffix(".target.json")
    path.rename(target)
    path.symlink_to(target)

    with pytest.raises(materialize.EvidenceValidationError) as exc:
        _build(fixture)

    assert "ea_operator_readiness_unreadable" in exc.value.codes


def test_cross_receipt_hash_mismatch_is_invalid_not_a_soft_blocker(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    release_path = fixture["paths"]["property_3d_release"]
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["browser_evidence"]["receipt_sha256"] = "0" * 64
    _write_json(release_path, release)

    with pytest.raises(materialize.EvidenceValidationError) as exc:
        _build(fixture)

    assert "property_interaction_hash_binding_mismatch" in exc.value.codes


def test_ea_git_tree_and_runtime_authority_bindings_are_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(materialize.EvidenceValidationError) as tree_error:
        materialize.build_receipt(
            paths=fixture["paths"],
            generated_at=GENERATED_AT,
            ea_commit=fixture["ea_commit"],
            ea_tree="f" * 40,
            ea_image_id=EA_IMAGE,
            ea_compose_project=EA_PROJECT,
            ea_deployment_id=EA_DEPLOYMENT,
            ea_repository=fixture["repository"],
        )
    assert "ea_git_tree_mismatch" in tree_error.value.codes

    authority_path = fixture["paths"]["ea_release_authority"]
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["deployment_id"] = "different-deployment-id"
    _write_json(authority_path, authority)
    with pytest.raises(materialize.EvidenceValidationError) as authority_error:
        _build(fixture)
    assert "ea_authority_deployment_mismatch" in authority_error.value.codes


def test_ea_remote_ref_binding_blocks_unpublished_candidate_offline(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    unrelated_commit = subprocess.check_output(
        [
            "git",
            "-C",
            os.fspath(fixture["repository"]),
            "commit-tree",
            fixture["ea_tree"],
        ],
        input="unrelated remote tip\n",
        text=True,
    ).strip()
    subprocess.run(
        [
            "git",
            "-C",
            os.fspath(fixture["repository"]),
            "update-ref",
            "refs/remotes/origin/main",
            unrelated_commit,
        ],
        check=True,
    )
    authority_path = fixture["paths"]["ea_release_authority"]
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority.update(
        {
            "state": "watch",
            "authority_posture": "source_not_remote",
            "issues": ["source_commit_not_reachable_from_remote_ref"],
            "source_remote_ref_commit_sha": unrelated_commit,
            "source_commit_reachable_from_remote_ref": False,
        }
    )
    authority["gate"].update(
        {
            "status": "fail",
            "authority_posture": "source_not_remote",
            "issues": ["source_commit_not_reachable_from_remote_ref"],
            "source_remote_ref_commit_sha": unrelated_commit,
            "source_commit_reachable_from_remote_ref": False,
        }
    )
    _write_json(authority_path, authority)

    receipt = _build(fixture)

    assert receipt["safe_to_promote_now"] is False
    assert receipt["ea_core"]["release_authority_ready"] is False
    assert receipt["ea_core"]["source_commit_reachable_from_remote_ref"] is False
    assert "ea_core_release_authority_not_green" in {
        item["code"] for item in receipt["launch_gate"]["blockers"]
    }


def test_ea_remote_ref_binding_rejects_fabricated_reachability(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    unrelated_commit = subprocess.check_output(
        [
            "git",
            "-C",
            os.fspath(fixture["repository"]),
            "commit-tree",
            fixture["ea_tree"],
        ],
        input="unrelated remote tip\n",
        text=True,
    ).strip()
    subprocess.run(
        [
            "git",
            "-C",
            os.fspath(fixture["repository"]),
            "update-ref",
            "refs/remotes/origin/main",
            unrelated_commit,
        ],
        check=True,
    )
    authority_path = fixture["paths"]["ea_release_authority"]
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["source_remote_ref_commit_sha"] = unrelated_commit
    authority["gate"]["source_remote_ref_commit_sha"] = unrelated_commit
    _write_json(authority_path, authority)

    with pytest.raises(materialize.EvidenceValidationError) as exc:
        _build(fixture)

    assert "ea_source_remote_reachability_mismatch" in exc.value.codes


def test_cli_writes_valid_blocked_receipt_and_returns_gate_failure(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / materialize.OUTPUT_NAME
    option_by_key = {
        "manfred_runtime": "--manfred-runtime",
        "manfred_release": "--manfred-release",
        "manfred_transport": "--manfred-transport",
        "manfred_live_boundary": "--manfred-live-boundary",
        "property_3d_interaction": "--property-3d-interaction",
        "property_3d_release": "--property-3d-release",
        "ea_operator_readiness": "--ea-operator-readiness",
        "localization_projection": "--localization-projection",
        "lived_system_observation": "--lived-system-observation",
        "chummer_flagship_readiness": "--chummer-flagship-readiness",
        "chummer_weekly_pulse": "--chummer-weekly-pulse",
        "chummer_journey_gates": "--chummer-journey-gates",
        "chummer_release_ready": "--chummer-release-ready",
        "ea_core_runtime": "--ea-core-runtime",
        "ea_release_authority": "--ea-release-authority",
    }
    args: list[str] = []
    for spec in materialize.EVIDENCE_SPECS:
        args.extend([option_by_key[spec.key], os.fspath(fixture["paths"][spec.key])])
    args.extend(
        [
            "--generated-at",
            GENERATED_AT,
            "--ea-commit",
            fixture["ea_commit"],
            "--ea-tree",
            fixture["ea_tree"],
            "--ea-image-id",
            EA_IMAGE,
            "--ea-compose-project",
            EA_PROJECT,
            "--ea-deployment-id",
            EA_DEPLOYMENT,
            "--ea-repository",
            os.fspath(fixture["repository"]),
            "--output",
            os.fspath(output),
        ]
    )

    assert materialize.main(args) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["safe_to_promote_now"] is False
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
