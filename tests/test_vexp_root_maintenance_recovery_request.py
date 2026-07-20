from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Callable

import pytest

from scripts import vexp_root_maintenance_recovery_request as recovery
from scripts.vexp_root_maintenance_recovery_request import (
    RecoveryRequestError,
    build_request,
    canonical_sha256,
    load_and_validate_request,
    validate_request,
    write_new_private_json,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SOURCE = ROOT / recovery.DEFAULT_MANIFEST_PATH


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(
    tmp_path: Path,
    *,
    mutate_manifest: Callable[[dict[str, object]], None] | None = None,
    raw_manifest: bytes | None = None,
) -> tuple[Path, str]:
    root = tmp_path / "reviewed-repo"
    root.mkdir()
    manifest = json.loads(MANIFEST_SOURCE.read_text(encoding="utf-8"))
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    for relative in manifest["reviewed_blob_paths"]:
        target = root / str(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / str(relative)
        target.write_bytes(source.read_bytes())
    manifest_target = root / recovery.DEFAULT_MANIFEST_PATH
    manifest_target.write_bytes(
        raw_manifest
        if raw_manifest is not None
        else (
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    _run_git(root, "init", "-q")
    _run_git(root, "config", "user.email", "test@example.invalid")
    _run_git(root, "config", "user.name", "Recovery Request Test")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-q", "-m", "reviewed recovery request")
    return root, _run_git(root, "rev-parse", "HEAD")


def _authorization(
    tmp_path: Path,
    commit: str,
    reference: str,
) -> Path:
    path = tmp_path / "operator-authorization.txt"
    path.write_text(
        json.dumps(
            {
                "authorization_id": reference,
                "contract_name": (
                    recovery.OPERATOR_AUTHORIZATION_CONTRACT
                ),
                "external_root_receipt_required": True,
                "manifest_path": recovery.DEFAULT_MANIFEST_PATH,
                "reviewed_commit": commit,
                "root_execution_authority": False,
                "scope": "schema_v6_qualification_plumbing_recovery",
                "source_request_only": True,
                "version": 1,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _operator_state_snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "sentinel-state.json"
    path.write_text(
        json.dumps(
            {
                "certification_blockers": [
                    "qualification_finalizer_plumbing_incompatible"
                ],
                "certification_deferments": [],
                "current_resources_healthy": True,
                "epoch_started_at": "2026-07-13T09:43:56.206Z",
                "epoch_started_ms": 1783935836206,
                "predicate_contract": "v6",
                "predicate_contract_sha256": "3" * 64,
                "probes_passed": 42,
                "qualification_earliest_completion_at": (
                    "2026-07-20T09:43:56.206Z"
                ),
                "qualification_phase": "enforced_soak",
                "qualified_at": None,
                "updated_at": "2026-07-20T09:59:00.000Z",
                "version": 6,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _request(
    tmp_path: Path,
) -> tuple[Path, str, Path, dict[str, object]]:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-001"
    state = _operator_state_snapshot(tmp_path)
    payload = build_request(
        repo_root=repo,
        reviewed_commit=commit,
        operator_authorization_path=_authorization(tmp_path, commit, reference),
        operator_authorization_reference=reference,
        operator_state_snapshot_path=state,
    )
    return repo, commit, state, payload


def _reseal(payload: dict[str, object]) -> None:
    payload.pop("request_identity", None)
    payload["request_identity"] = f"sha256:{canonical_sha256(payload)}"


def test_materialized_request_binds_exact_commit_and_every_reviewed_blob(
    tmp_path: Path,
) -> None:
    repo, commit, state, payload = _request(tmp_path)

    result = validate_request(payload, repo_root=repo)

    assert payload["reviewed_commit"] == commit
    assert payload["status"] == "blocked_external_root_receipt_required"
    assert result["status"] == "valid_non_authoritative_request"
    assert result["authority"] is False
    assert payload["authority"] == recovery.AUTHORITY_DENIAL
    assert set(payload["authority"].values()) == {False}
    for row in payload["reviewed_blobs"]:
        raw = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "cat-file",
                "blob",
                f"{commit}:{row['path']}",
            ],
            check=True,
            capture_output=True,
        ).stdout
        assert row["sha256"] == hashlib.sha256(raw).hexdigest()
        assert row["size_bytes"] == len(raw)
    state_raw = state.read_bytes()
    binding = payload["operator_state_snapshot"]
    assert binding["snapshot_sha256"] == hashlib.sha256(state_raw).hexdigest()
    assert binding["snapshot_size_bytes"] == len(state_raw)
    assert binding["snapshot_content_included"] is False
    assert binding["trust_model"] == "untrusted_operator_supplied_snapshot"
    assert binding["live_state_truth_established"] is False
    assert binding["state_version"] == 6
    assert binding["epoch_started_ms"] == 1783935836206
    assert binding["qualification_phase"] == "enforced_soak"
    assert binding["qualification_floor_valid"] is True
    assert binding["schema_observation_codes"] == []
    assert binding["certification_blocker_count"] == 1
    assert "qualification_finalizer_plumbing_incompatible" not in json.dumps(
        payload
    )


def test_request_requires_durable_pre_change_void_and_new_full_soak(
    tmp_path: Path,
) -> None:
    _repo_root, _commit, _state_path, payload = _request(tmp_path)

    void = payload["pre_change_epoch_void"]
    assert void == recovery._expected_pre_change_void()
    assert void["must_precede_first_guarded_change"] is True
    assert void["durable_root_owned_receipt_required"] is True
    assert void["active_epoch_and_derived_authority_irrevocably_void"] is True
    assert void["atomic_root_actor_pre_change_state_capture_required"] is True
    assert void[
        "actual_state_owner_must_match_trusted_sentinel_owner"
    ] is True
    assert void["stable_no_follow_actual_state_read_required"] is True
    assert void["must_bind_atomic_pre_change_state_sha256"] is True
    assert void[
        "must_match_operator_snapshot_epoch_identity_sha256"
    ] is True
    qualification = payload["post_recovery_qualification"]
    assert qualification["state_version"] == 6
    assert qualification["strictly_newer_epoch_required"] is True
    assert qualification["minimum_wall_duration_ms"] == 604_800_000
    assert qualification["minimum_monotonic_duration_ms"] == 604_800_000
    assert qualification["certification_blockers"] == []
    assert qualification["certification_deferments"] == []
    assert qualification["current_resources_healthy"] is True


def test_ea_emits_external_finalizer_handoff_instead_of_claiming_authority(
    tmp_path: Path,
) -> None:
    _repo_root, _commit, _state_path, payload = _request(tmp_path)

    handoff = payload["external_owner_handoff"]
    assert handoff["required"] is True
    assert handoff["external_pre_change_authorization_required"] is True
    assert handoff["request_grants_root_execution_authority"] is False
    assert handoff["root_receipt_is_post_execution_evidence"] is True
    assert handoff["owner_plane"] == "fleet"
    assert handoff["finalizer_implementation_location"] == (
        "external_owner_required"
    )
    root_receipt = handoff["required_root_receipt"]
    assert root_receipt["must_be_root_owned"] is True
    assert root_receipt["must_be_signed"] is True
    assert root_receipt["signature_algorithm"] == "ed25519"
    assert root_receipt["must_bind_pre_change_void_receipt_sha256"] is True
    assert root_receipt["must_bind_atomic_pre_change_state_sha256"] is True
    assert root_receipt[
        "must_bind_operator_snapshot_epoch_identity_sha256"
    ] is True
    assert payload["execution_observations"]["external_root_receipt_present"] is False
    scope = (ROOT / ".codex-design/repo/IMPLEMENTATION_SCOPE.md").read_text(
        encoding="utf-8"
    )
    assert "* a release authority" in scope
    assert "* a hidden contract package owner" in scope


def test_only_guarded_components_and_actions_are_requestable(
    tmp_path: Path,
) -> None:
    _repo_root, _commit, _state_path, payload = _request(tmp_path)

    guarded = {
        row["component"]: tuple(row["allowed_actions"])
        for row in payload["guarded_plumbing"]
    }
    assert guarded == recovery.ALLOWED_COMPONENT_ACTIONS
    assert {
        "current_predicate_attestor",
        "candidate_boundary_attestor",
    }.issubset(guarded)
    assert all(
        "restore_manifest_bound_pre_change_artifact_after_failure" in actions
        for actions in guarded.values()
    )
    assert payload["prohibited_effects"] == list(recovery.PROHIBITED_EFFECTS)
    assert "docker_or_compose_mutation" in payload["prohibited_effects"]
    assert "certificate_issuance" in payload["prohibited_effects"]
    assert "permit_issuance" in payload["prohibited_effects"]
    assert "authority_restoring_rollback" in payload["prohibited_effects"]
    assert "rollback" not in payload["prohibited_effects"]
    failure_policy = payload["guarded_plumbing_failure_policy"]
    assert failure_policy["plumbing_rollback_allowed_after_durable_void"] is True
    assert failure_policy["epoch_void_remains_permanent"] is True
    assert failure_policy["authority_restoration_forbidden"] is True
    assert failure_policy["rollback_scope"] == "guarded_plumbing_only"


def test_memorial_source_gate_includes_root_recovery_contract() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("verify-manfred-memorial-source-gate:", 1)[1].split(
        "\ntest-all:", 1
    )[0]
    assert "tests/test_vexp_root_maintenance_recovery_request.py" in target


@pytest.mark.parametrize(
    "field",
    [
        "authority",
        "execution_observations",
        "operator_state_snapshot",
        "guarded_plumbing_failure_policy",
        "guarded_plumbing",
        "post_recovery_qualification",
        "pre_change_epoch_void",
        "prohibited_effects",
        "external_owner_handoff",
    ],
)
def test_semantic_request_tampering_fails_even_when_identity_is_resealed(
    tmp_path: Path,
    field: str,
) -> None:
    repo, _commit, state, payload = _request(tmp_path)
    tampered = json.loads(json.dumps(payload))
    if field == "authority":
        tampered[field]["root_maintenance_execution"] = True
    elif field == "execution_observations":
        tampered[field]["systemd_calls_performed"] = True
    elif field == "operator_state_snapshot":
        tampered[field]["epoch_identity_sha256"] = "0" * 64
    elif field == "guarded_plumbing_failure_policy":
        tampered[field]["authority_restoration_forbidden"] = False
    elif field == "guarded_plumbing":
        tampered[field][0]["allowed_actions"].append("stop_named_unit")
    elif field == "post_recovery_qualification":
        tampered[field]["minimum_monotonic_duration_ms"] -= 1
    elif field == "pre_change_epoch_void":
        tampered[field]["must_precede_first_guarded_change"] = False
    elif field == "prohibited_effects":
        tampered[field].remove("live_ea_mutation")
    else:
        tampered[field]["finalizer_implementation_location"] = "ea"
    _reseal(tampered)

    with pytest.raises(RecoveryRequestError):
        validate_request(tampered, repo_root=repo)


def test_source_manifest_rejects_unknown_action_before_request_materialization(
    tmp_path: Path,
) -> None:
    def mutate(manifest: dict[str, object]) -> None:
        guarded = manifest["guarded_plumbing"]
        guarded[0]["allowed_actions"].append("docker_compose_up")

    repo, commit = _repo(tmp_path, mutate_manifest=mutate)
    reference = "operator-approval/recovery-002"

    with pytest.raises(
        RecoveryRequestError, match="recovery_manifest_guarded_plumbing_invalid"
    ):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=_authorization(tmp_path, commit, reference),
            operator_authorization_reference=reference,
            operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
        )


def test_source_manifest_duplicate_keys_fail_closed(tmp_path: Path) -> None:
    manifest = MANIFEST_SOURCE.read_bytes()
    duplicated = manifest.replace(
        b'{\n  "authority": false,',
        b'{\n  "authority": false,\n  "authority": false,',
        1,
    )
    repo, commit = _repo(tmp_path, raw_manifest=duplicated)
    reference = "operator-approval/recovery-003"

    with pytest.raises(
        RecoveryRequestError, match="recovery_manifest_json_invalid"
    ):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=_authorization(tmp_path, commit, reference),
            operator_authorization_reference=reference,
            operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
        )


def test_reviewed_commit_must_be_exact_full_commit(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-004"

    with pytest.raises(RecoveryRequestError, match="reviewed_commit_invalid"):
        build_request(
            repo_root=repo,
            reviewed_commit=commit[:12],
            operator_authorization_path=_authorization(tmp_path, commit, reference),
            operator_authorization_reference=reference,
            operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
        )


def test_private_request_write_is_no_replace_and_round_trips(tmp_path: Path) -> None:
    repo, _commit, state, payload = _request(tmp_path)
    output_dir = tmp_path / "private"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "request.json"

    write_new_private_json(output, payload)
    loaded, result = load_and_validate_request(output, repo_root=repo)

    assert loaded == payload
    assert result["authority"] is False
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(RecoveryRequestError, match="output_write_failed"):
        write_new_private_json(output, payload)


def test_cli_materialize_and_verify_remain_non_authoritative(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-005"
    authorization = _authorization(tmp_path, commit, reference)
    state = _operator_state_snapshot(tmp_path)
    output_dir = tmp_path / "cli-private"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "request.json"
    materialized = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_vexp_root_maintenance_recovery_request.py",
            "--repo-root",
            str(repo),
            "--reviewed-commit",
            commit,
            "--operator-authorization",
            str(authorization),
            "--operator-authorization-reference",
            reference,
            "--operator-state-snapshot",
            str(state),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert materialized.returncode == 0, materialized.stdout
    materialized_payload = json.loads(materialized.stdout)
    assert materialized_payload["authority"] is False
    assert materialized_payload["external_root_receipt_required"] is True
    verified = subprocess.run(
        [
            sys.executable,
            "scripts/verify_vexp_root_maintenance_recovery_request.py",
            "--repo-root",
            str(repo),
            "--request",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stdout
    verified_payload = json.loads(verified.stdout)
    assert verified_payload["status"] == "valid_non_authoritative_request"
    assert verified_payload["authority"] is False
    assert verified_payload["external_root_receipt_present"] is False


def test_request_verification_is_stable_across_same_epoch_state_rewrites(
    tmp_path: Path,
) -> None:
    repo, _commit, state, payload = _request(tmp_path)
    changed = json.loads(state.read_text(encoding="utf-8"))
    changed["updated_at"] = "2026-07-20T10:00:00.000Z"
    state.write_text(
        json.dumps(changed, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state.chmod(0o600)

    result = validate_request(payload, repo_root=repo)

    assert result["status"] == "valid_non_authoritative_request"
    assert result["live_state_truth_established"] is False
    assert result["operator_snapshot_epoch_identity_sha256"] == payload[
        "operator_state_snapshot"
    ]["epoch_identity_sha256"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("version", 5, "state_version_invalid"),
        ("qualification_phase", "watch", "state_phase_invalid"),
        ("epoch_started_ms", 1783935836205, "state_epoch_invalid"),
    ],
)
def test_operator_snapshot_epoch_schema_fails_closed(
    tmp_path: Path,
    field: str,
    value: object,
    reason: str,
) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-state-invalid"
    state = _operator_state_snapshot(tmp_path)
    changed = json.loads(state.read_text(encoding="utf-8"))
    changed[field] = value
    state.write_text(json.dumps(changed) + "\n", encoding="utf-8")
    state.chmod(0o600)

    with pytest.raises(RecoveryRequestError, match=reason):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=_authorization(
                tmp_path, commit, reference
            ),
            operator_authorization_reference=reference,
            operator_state_snapshot_path=state,
        )


def test_operator_snapshot_records_broken_floor_and_nullable_v6_fields(
    tmp_path: Path,
) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-broken-state"
    state = _operator_state_snapshot(tmp_path)
    changed = json.loads(state.read_text(encoding="utf-8"))
    changed["qualification_earliest_completion_at"] = (
        "2026-07-20T09:43:56.205Z"
    )
    changed["certification_deferments"] = None
    changed["predicate_contract"] = None
    changed["predicate_contract_sha256"] = None
    state.write_text(
        json.dumps(changed, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state.chmod(0o600)

    request = build_request(
        repo_root=repo,
        reviewed_commit=commit,
        operator_authorization_path=_authorization(tmp_path, commit, reference),
        operator_authorization_reference=reference,
        operator_state_snapshot_path=state,
    )
    result = validate_request(request, repo_root=repo)
    snapshot = request["operator_state_snapshot"]

    assert result["authority"] is False
    assert snapshot["qualification_floor_valid"] is False
    assert snapshot["certification_deferment_count"] is None
    assert snapshot["predicate_contract"] is None
    assert snapshot["predicate_contract_sha256"] is None
    assert snapshot["schema_observation_codes"] == [
        "qualification_floor_below_seven_days",
        "certification_deferments_missing_or_invalid",
        "predicate_contract_missing_or_invalid",
        "predicate_contract_sha256_missing_or_invalid",
    ]
    assert request["post_recovery_qualification"][
        "minimum_wall_duration_ms"
    ] == 604_800_000
    assert request["post_recovery_qualification"][
        "certification_deferments"
    ] == []


def test_operator_snapshot_symlink_and_untrusted_mode_fail_closed(
    tmp_path: Path,
) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-state-file"
    authorization = _authorization(tmp_path, commit, reference)
    state = _operator_state_snapshot(tmp_path)
    state_link = tmp_path / "sentinel-state-link.json"
    state_link.symlink_to(state)

    with pytest.raises(
        RecoveryRequestError, match="recovery_operator_state_snapshot_unavailable"
    ):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=authorization,
            operator_authorization_reference=reference,
            operator_state_snapshot_path=state_link,
        )

    state.chmod(0o644)
    with pytest.raises(
        RecoveryRequestError, match="recovery_operator_state_snapshot_untrusted"
    ):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=authorization,
            operator_authorization_reference=reference,
            operator_state_snapshot_path=state,
        )


def test_request_materialization_executes_only_read_only_git_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, commit = _repo(tmp_path)
    real_run = recovery.subprocess.run
    commands: list[tuple[str, ...]] = []

    def record_run(command, **kwargs):
        commands.append(tuple(str(item) for item in command))
        return real_run(command, **kwargs)

    monkeypatch.setattr(recovery.subprocess, "run", record_run)
    reference = "operator-approval/recovery-006"
    payload = build_request(
        repo_root=repo,
        reviewed_commit=commit,
        operator_authorization_path=_authorization(tmp_path, commit, reference),
        operator_authorization_reference=reference,
        operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
    )

    assert payload["execution_observations"] == recovery.EXECUTION_OBSERVATIONS
    assert commands
    assert {command[0] for command in commands} == {"git"}
    assert all("cat-file" in command or "rev-parse" in command for command in commands)
    assert not any(
        token in {"docker", "compose", "systemctl", "sudo"}
        for command in commands
        for token in command
    )


def test_operator_authorization_content_is_digest_bound_but_not_embedded(
    tmp_path: Path,
) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-007"
    authorization = _authorization(tmp_path, commit, reference)
    raw = authorization.read_bytes()

    payload = build_request(
        repo_root=repo,
        reviewed_commit=commit,
        operator_authorization_path=authorization,
        operator_authorization_reference=reference,
        operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
    )

    binding = payload["operator_authorization"]
    assert binding["sha256"] == hashlib.sha256(raw).hexdigest()
    assert binding["content_included"] is False
    assert raw.decode("utf-8") not in json.dumps(payload)


def test_operator_authorization_must_be_exact_source_only_recovery_contract(
    tmp_path: Path,
) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-008"
    authorization = _authorization(tmp_path, commit, reference)
    payload = json.loads(authorization.read_text(encoding="utf-8"))
    payload["root_execution_authority"] = True
    authorization.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(
        RecoveryRequestError, match="operator_authorization_binding_invalid"
    ):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=authorization,
            operator_authorization_reference=reference,
            operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
        )


def test_operator_authorization_symlink_fails_closed(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-009"
    authorization = _authorization(tmp_path, commit, reference)
    link = tmp_path / "authorization-link.json"
    link.symlink_to(authorization)

    with pytest.raises(
        RecoveryRequestError, match="recovery_operator_authorization_unavailable"
    ):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=link,
            operator_authorization_reference=reference,
            operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
        )


def test_operator_authorization_untrusted_mode_fails_closed(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    reference = "operator-approval/recovery-mode-invalid"
    authorization = _authorization(tmp_path, commit, reference)
    authorization.chmod(0o644)

    with pytest.raises(
        RecoveryRequestError, match="recovery_operator_authorization_untrusted"
    ):
        build_request(
            repo_root=repo,
            reviewed_commit=commit,
            operator_authorization_path=authorization,
            operator_authorization_reference=reference,
            operator_state_snapshot_path=_operator_state_snapshot(tmp_path),
        )


def test_untrusted_request_mode_is_rejected(tmp_path: Path) -> None:
    repo, _commit, state, payload = _request(tmp_path)
    output = tmp_path / "request.json"
    output.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    output.chmod(0o644)

    with pytest.raises(RecoveryRequestError, match="recovery_request_untrusted"):
        load_and_validate_request(output, repo_root=repo)


def test_manifest_file_is_canonical_source_only_and_non_authoritative() -> None:
    manifest = json.loads(MANIFEST_SOURCE.read_text(encoding="utf-8"))

    recovery.validate_source_manifest(manifest)
    assert manifest["authority"] is False
    assert manifest["scope"] == "source_only_external_root_handoff"
    assert manifest["external_owner_handoff"]["owner_plane"] == "fleet"
    assert not any(
        "finalizer" in path and path.endswith((".py", ".mjs", ".sh"))
        for path in manifest["reviewed_blob_paths"]
    )
