from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import build_manfred_memorial_image as image_builder
from scripts import deploy_ea_memorial as deploy
from scripts import prepare_manfred_memorial_candidate as candidate
from scripts import run_manfred_memorial_candidate as candidate_runner


BLOCKER = "credential_exposure_remediation_unverified"
PROJECT = "ea-manfred-candidate-credential-guard-a1b2c3d4"


def _bomb(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("credential exposure guard boundary was crossed")


@pytest.mark.parametrize("rotate_secrets", [False, True])
def test_candidate_guard_precedes_lock_reads_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rotate_secrets: bool,
) -> None:
    deploy_root = tmp_path / "candidate"
    monkeypatch.setattr(candidate, "hold_candidate_fleet_lock", _bomb)
    monkeypatch.setattr(candidate, "_commit", _bomb)
    monkeypatch.setattr(candidate, "_image_revision", _bomb)
    monkeypatch.setenv("EA_CREDENTIAL_EXPOSURE_REMEDIATION_VERIFIED", "1")
    monkeypatch.setenv("EA_CREDENTIAL_EXPOSURE_REMEDIATION_STATUS", "closed")

    with pytest.raises(ValueError, match=f"^{BLOCKER}$"):
        candidate.prepare_candidate(
            source_root=tmp_path / "source",
            ref="HEAD",
            image="ea-runtime:memorial-placeholder",
            image_build_receipt=tmp_path / "image-build.json",
            deploy_root=deploy_root,
            public_base_url="https://myexternalbrain.com",
            host_port=18090,
            project_name=PROJECT,
            rotate_secrets=rotate_secrets,
        )

    assert not deploy_root.exists()


def test_candidate_image_guard_precedes_producer_authority_lock_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = tmp_path / "image-build.json"
    monkeypatch.setattr(image_builder, "_producer_sha256", _bomb)
    monkeypatch.setattr(image_builder, "candidate_vexp_authority", _bomb)
    monkeypatch.setattr(image_builder, "_exclusive_build_lock", _bomb)
    monkeypatch.setenv("EA_CREDENTIAL_EXPOSURE_REMEDIATION_VERIFIED", "1")

    with pytest.raises(RuntimeError, match=f"^{BLOCKER}$"):
        image_builder.build_image(
            source_root=tmp_path / "source",
            ref="HEAD",
            tag="",
            receipt_path=receipt_path,
            vexp_state_path=tmp_path / "sentinel.json",
            vexp_state_owner_uid=1000,
        )

    assert not receipt_path.exists()


def test_candidate_runtime_guard_precedes_env_authority_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = tmp_path / "candidate-runtime.json"
    monkeypatch.setattr(candidate_runner, "_read_private_output", _bomb)
    monkeypatch.setattr(candidate_runner, "candidate_vexp_authority", _bomb)
    monkeypatch.setattr(candidate_runner, "hold_candidate_fleet_lock", _bomb)
    monkeypatch.setattr(candidate_runner, "_run", _bomb)
    monkeypatch.setenv("EA_CREDENTIAL_EXPOSURE_REMEDIATION_VERIFIED", "1")

    with pytest.raises(RuntimeError, match=f"^{BLOCKER}$"):
        candidate_runner.prove_candidate(
            env_file=tmp_path / "candidate.env",
            compose_file=tmp_path / "candidate.yml",
            receipt_path=receipt_path,
            wait_seconds=60,
            vexp_state_path=tmp_path / "sentinel.json",
            vexp_state_owner_uid=1000,
        )

    assert not receipt_path.exists()


def _lane(tmp_path: Path) -> deploy.MemorialDeployLane:
    return deploy.MemorialDeployLane(
        root=tmp_path,
        env={
            "EA_DEPLOYMENT_ID": "credential-exposure-guard-test",
            "EA_CREDENTIAL_EXPOSURE_REMEDIATION_VERIFIED": "1",
            "EA_CREDENTIAL_EXPOSURE_REMEDIATION_STATUS": "closed",
        },
        runner=Mock(),
        http_get=Mock(),
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "deploy.lock",
        durable_root_check=lambda _root: None,
    )


def test_direct_preflight_guard_precedes_receipt_compose_and_probes(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    lane._write_receipt = Mock(side_effect=_bomb)  # type: ignore[method-assign]
    lane._detect_compose = Mock(side_effect=_bomb)  # type: ignore[method-assign]

    with pytest.raises(deploy.DeployError, match=f"^{BLOCKER}$"):
        lane.preflight()

    lane._write_receipt.assert_not_called()
    lane._detect_compose.assert_not_called()
    assert not lane.receipt_dir.exists()


@pytest.mark.parametrize("preflight_only", [False, True])
def test_deploy_guard_precedes_lock_and_preflight(
    tmp_path: Path,
    preflight_only: bool,
) -> None:
    lane = _lane(tmp_path)
    lane._acquire_lock = Mock(side_effect=_bomb)  # type: ignore[method-assign]
    lane.preflight = Mock(side_effect=_bomb)  # type: ignore[method-assign]

    with pytest.raises(deploy.DeployError, match=f"^{BLOCKER}$"):
        lane.deploy(preflight_only=preflight_only)

    lane._acquire_lock.assert_not_called()
    lane.preflight.assert_not_called()
    assert not lane.receipt_dir.exists()


@pytest.mark.parametrize("rotate_secrets", [False, True])
def test_candidate_cli_exits_nonzero_with_fixed_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rotate_secrets: bool,
) -> None:
    monkeypatch.setattr(candidate, "hold_candidate_fleet_lock", _bomb)
    argv = [
        "--source-root",
        str(tmp_path / "source"),
        "--image",
        "ea-runtime:memorial-placeholder",
        "--image-build-receipt",
        str(tmp_path / "image-build.json"),
        "--deploy-root",
        str(tmp_path / "candidate"),
        "--public-base-url",
        "https://myexternalbrain.com",
        "--project-name",
        PROJECT,
    ]
    if rotate_secrets:
        argv.append("--rotate-secrets")

    assert candidate.main(argv) == 1
    output = capsys.readouterr()
    assert BLOCKER in output.out
    assert output.err == ""
    assert not (tmp_path / "candidate").exists()


def test_candidate_image_cli_exits_nonzero_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(image_builder, "_producer_sha256", _bomb)
    receipt_path = tmp_path / "image-build.json"

    assert image_builder.main(
        [
            "--source-root",
            str(tmp_path / "source"),
            "--receipt",
            str(receipt_path),
            "--vexp-state-path",
            str(tmp_path / "sentinel.json"),
            "--vexp-state-owner-uid",
            "1000",
        ]
    ) == 1
    output = capsys.readouterr()
    assert BLOCKER in output.out
    assert output.err == ""
    assert not receipt_path.exists()


def test_candidate_runtime_cli_exits_nonzero_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(candidate_runner, "_read_private_output", _bomb)
    receipt_path = tmp_path / "candidate-runtime.json"

    assert candidate_runner.main(
        [
            "--env-file",
            str(tmp_path / "candidate.env"),
            "--compose-file",
            str(tmp_path / "candidate.yml"),
            "--receipt",
            str(receipt_path),
            "--vexp-state-path",
            str(tmp_path / "sentinel.json"),
            "--vexp-state-owner-uid",
            "1000",
        ]
    ) == 1
    output = capsys.readouterr()
    assert BLOCKER in output.out
    assert output.err == ""
    assert not receipt_path.exists()


def test_candidate_image_self_test_remains_available(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        image_builder,
        "_self_test",
        lambda: {"schema": image_builder.SELF_TEST_SCHEMA, "status": "pass"},
    )

    assert image_builder.main(["--self-test"]) == 0
    output = capsys.readouterr()
    assert '"status": "pass"' in output.out
    assert output.err == ""


def test_deploy_cli_preflight_exits_nonzero_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EA_DEPLOYMENT_ID",
        "credential-exposure-guard-cli-test",
    )
    monkeypatch.setenv("EA_CREDENTIAL_EXPOSURE_REMEDIATION_VERIFIED", "1")
    receipt_dir = tmp_path / "receipts"

    assert deploy.main(
        ["--preflight-only", "--receipt-dir", str(receipt_dir)]
    ) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.strip() == f"memorial deploy failed: {BLOCKER}"
    assert not receipt_dir.exists()
