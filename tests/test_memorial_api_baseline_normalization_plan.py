from __future__ import annotations

import copy
import json
import stat
from pathlib import Path

import pytest

from scripts import plan_ea_memorial_api_baseline_normalization as planner


REVISION = "2e5b40f9fe2ef4acb7946eb7e80537fcd01ab047"
IMAGE_ID = "sha256:" + "a" * 64
IMAGE_REFERENCE = "ea-runtime:memorial-main-2e5b40f9-20260719"


def _plan(tmp_path: Path, **overrides: str) -> dict[str, object]:
    values = {
        "plan_id": "baseline-plan-001",
        "recorded_working_dir": str(tmp_path / "recorded"),
        "external_config_root": str(tmp_path / "external"),
        "trusted_environment_root": str(tmp_path / "trusted"),
        "expected_revision": REVISION,
        "expected_image_reference": IMAGE_REFERENCE,
        "expected_image_id": IMAGE_ID,
        "generated_at": "2026-07-21T12:00:00.000Z",
    }
    values.update(overrides)
    return planner.build_plan(**values)


def test_plan_is_exactly_non_authoritative_and_unverified(tmp_path: Path) -> None:
    payload = _plan(tmp_path)

    planner.validate_plan_payload(payload)
    assert payload["contract_name"] == "ea.memorial_api_baseline_normalization_plan.v2"
    assert payload["version"] == 2
    assert payload["status"] == "plan_only"
    assert payload["promotion_authority"] is False
    assert payload["mutation_authority"] is False
    assert payload["mutation_performed"] is False
    assert payload["normalization_completed"] is False
    assert payload["service_scope"] == ["ea-api"]
    assert payload["ingress_mutation_scope"] == []
    assert payload["execution"] == {
        "available": False,
        "blocker": "normalization_executor_and_recovery_journal_not_implemented",
        "docker_mutations": 0,
        "compose_invocations": 0,
        "git_mutations": 0,
        "http_requests": 0,
        "recovery_journal_written": False,
    }
    assert payload["source_requirements"]["verification_status"] == (
        "required_unverified"
    )
    assert payload["identity_requirements"]["verification_status"] == (
        "required_unverified"
    )
    assert payload["identity_requirements"]["required_equal_labels"] == [
        "com.docker.compose.config-hash"
    ]
    assert "com.docker.compose.config-hash" not in payload[
        "identity_requirements"
    ]["allowed_differences"]
    assert payload["authority"] == {
        "executor_implemented": False,
        "independent_review_required": True,
        "journal_contract_review_required": True,
    }
    assert payload["recovery_requirements"] == {
        "distinct_crash_journal_required": True,
        "normal_deploy_blocked_while_recovery_active": True,
        "retained_immutable_bundle_required": True,
        "verification_status": "required_unverified",
    }


def test_v1_plan_is_not_accepted_as_the_v2_contract(
    tmp_path: Path,
) -> None:
    payload = _plan(tmp_path)
    payload["contract_name"] = "ea.memorial_api_baseline_normalization_plan.v1"
    payload["version"] = 1

    with pytest.raises(planner.PlanError, match="plan_authority_invariant_invalid"):
        planner.validate_plan_payload(payload)


@pytest.mark.parametrize(
    ("section", "extra_key"),
    [
        (None, "unexpected"),
        ("activation_condition", "observed_live_state"),
        ("source_requirements", "source_verified"),
        ("identity_requirements", "identity_verified"),
        ("authority", "review_complete"),
        ("execution", "command"),
        ("recovery_requirements", "journal_path"),
        ("secrecy", "environment_values"),
    ],
)
def test_plan_rejects_unknown_fields(
    tmp_path: Path, section: str | None, extra_key: str
) -> None:
    payload = copy.deepcopy(_plan(tmp_path))
    target = payload if section is None else payload[section]
    target[extra_key] = True

    with pytest.raises(planner.PlanError, match="schema_invalid"):
        planner.validate_plan_payload(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"recorded_working_dir": "relative/recorded"},
        {"external_config_root": "/tmp/not-normal/../external"},
        {"trusted_environment_root": "~/trusted"},
        {
            "recorded_working_dir": "/srv/ea/same",
            "external_config_root": "/srv/ea/same",
        },
        {
            "recorded_working_dir": "/srv/ea/same",
            "trusted_environment_root": "/srv/ea/same",
        },
        {
            "recorded_working_dir": "/srv/ea",
            "external_config_root": "/srv/ea/external",
        },
        {
            "recorded_working_dir": "/srv/ea",
            "trusted_environment_root": "/srv/ea/trusted",
        },
        {"expected_revision": "not-a-revision"},
        {"expected_image_reference": "latest"},
        {"expected_image_id": "sha256:short"},
        {"plan_id": "x"},
    ],
)
def test_plan_rejects_unbound_or_malformed_inputs(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    with pytest.raises(planner.PlanError):
        _plan(tmp_path, **overrides)


def test_plan_encodes_only_the_exact_split_label_shape(tmp_path: Path) -> None:
    payload = _plan(tmp_path)
    activation = payload["activation_condition"]
    external = tmp_path / "external"
    trusted = tmp_path / "trusted"

    assert activation == {
        "condition": "exact_split_compose_label_baseline",
        "recorded_working_dir": str(tmp_path / "recorded"),
        "recorded_environment_expectation": "missing",
        "external_config_root": str(external),
        "ordered_external_config_files": [
            str(external / "docker-compose.yml"),
            str(external / "docker-compose.memorial.yml"),
        ],
        "trusted_environment_root": str(trusted),
        "trusted_environment_files": [
            {
                "path": str(trusted / ".env"),
                "requirement": "required_no_follow_private_copy",
                "verification_status": "required_unverified",
            },
            {
                "path": str(trusted / ".env.local"),
                "requirement": "optional_no_follow_private_copy",
                "verification_status": "required_unverified_if_present",
            },
        ],
        "verification_status": "required_unverified",
    }


def test_plan_encodes_exact_colocated_legacy_environment_shape(
    tmp_path: Path,
) -> None:
    recorded = tmp_path / "recorded"
    trusted = tmp_path / "trusted"

    payload = _plan(
        tmp_path,
        recorded_working_dir=str(recorded),
        external_config_root=str(recorded),
        trusted_environment_root=str(trusted),
        baseline_layout=planner.BASELINE_LAYOUT_COLOCATED_LEGACY_ENV,
    )
    activation = payload["activation_condition"]

    assert activation["condition"] == planner.COLOCATED_LEGACY_ENV_CONDITION
    assert (
        activation["recorded_environment_expectation"]
        == "legacy_private_file_present_unread"
    )
    assert activation["recorded_working_dir"] == str(recorded)
    assert activation["external_config_root"] == str(recorded)
    assert activation["ordered_external_config_files"] == [
        str(recorded / name)
        for name in planner.COLOCATED_LEGACY_COMPOSE_FILES
    ]
    planner.validate_plan_payload(payload)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "version", False),
        (None, "generated_at", "not-a-timestampZ"),
        ("authority", "executor_implemented", True),
        ("authority", "independent_review_required", False),
        ("execution", "blocker", "ready_to_execute"),
        ("execution", "docker_mutations", False),
        ("recovery_requirements", "retained_immutable_bundle_required", False),
        (
            "identity_requirements",
            "allowed_differences",
            [
                "com.docker.compose.project.working_dir",
                "com.docker.compose.project.config_files",
                "com.docker.compose.project.environment_file",
                "com.docker.compose.config-hash",
            ],
        ),
    ],
)
def test_validator_rejects_authority_or_identity_drift(
    tmp_path: Path, section: str | None, key: str, value: object
) -> None:
    payload = copy.deepcopy(_plan(tmp_path))
    target = payload if section is None else payload[section]
    target[key] = value

    with pytest.raises(planner.PlanError, match="authority_invariant_invalid"):
        planner.validate_plan_payload(payload)


def test_plan_never_reads_environment_or_external_file_contents(
    tmp_path: Path,
) -> None:
    recorded = tmp_path / "recorded"
    external = tmp_path / "external"
    trusted = tmp_path / "trusted"
    for directory in (recorded, external, trusted):
        directory.mkdir()
    secret = "TOP_SECRET_VALUE_MUST_NOT_ENTER_PLAN"
    (trusted / ".env").write_text(f"TOKEN={secret}\n", encoding="utf-8")
    (external / "docker-compose.yml").write_text(secret, encoding="utf-8")
    (external / "docker-compose.memorial.yml").write_text(secret, encoding="utf-8")

    payload = _plan(
        tmp_path,
        recorded_working_dir=str(recorded),
        external_config_root=str(external),
        trusted_environment_root=str(trusted),
    )
    encoded = json.dumps(payload, sort_keys=True)

    assert secret not in encoded
    assert payload["secrecy"] == {
        "environment_values_included": False,
        "external_file_contents_included": False,
        "private_output_required": True,
    }


def test_private_writer_is_no_replace_and_mode_0600(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    output = private / "plan.json"
    payload = _plan(tmp_path)

    planner._write_private_plan(output, payload)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    with pytest.raises(FileExistsError):
        planner._write_private_plan(output, payload)


def test_private_writer_rejects_symlink_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-private"
    real_parent.mkdir(mode=0o700)
    real_parent.chmod(0o700)
    linked_parent = tmp_path / "linked-private"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(OSError):
        planner._write_private_plan(linked_parent / "plan.json", _plan(tmp_path))


def test_plan_contract_cannot_be_promotion_or_candidate_evidence(
    tmp_path: Path,
) -> None:
    payload = _plan(tmp_path)

    assert payload["contract_name"] not in {
        "ea.memorial_joint_api_ingress_deploy.v2",
        "ea.memorial_scoped_deploy_receipt.v2",
        "ea.manfred_memorial_candidate_runtime.v5",
        "ea.manfred_spatial_candidate_browser.v5",
    }
    assert payload["status"] != "pass"
    assert "candidate_promotion_evidence" not in payload
    assert "spatial_materializer_handoff" not in payload


def test_make_target_is_plan_only_and_has_no_deploy_dependency() -> None:
    makefile = (Path(__file__).parents[1] / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split(
        "plan-ea-memorial-api-baseline-normalization:\n", 1
    )[1].split("\n\n", 1)[0]

    assert "scripts/plan_ea_memorial_api_baseline_normalization.py" in recipe
    assert "deploy-ea-memorial" not in recipe
    assert "docker" not in recipe.lower()
    assert "compose" not in recipe.lower()
