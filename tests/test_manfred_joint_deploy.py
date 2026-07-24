from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import urllib.parse
from copy import deepcopy
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import Mock, call

import pytest

from scripts import deploy_ea_memorial as api_deploy
from scripts import deploy_ea_memorial_joint as joint
from scripts import ea_memorial_recovery_interlock as recovery_interlock
from scripts import materialize_memorial_spatial_tour_public_origin as materializer
from scripts import memorial_spatial_public_origin_contract as spatial_contract
from scripts import reconcile_ea_public_ingress as ingress
from tests.test_memorial_governed_deploy import FakeRunner as MemorialFakeRunner
from tests.test_memorial_spatial_tour_public_origin import ORIGIN, _valid_inputs


SOURCE_REVISION = "a" * 40
PRODUCTION_PREVIOUS_API_KEYS = {
    "compose_config_files",
    "container_id",
    "created_at",
    "environment_count",
    "environment_sha256",
    "functional_identity",
    "image_id",
    "image_reference",
    "mount_identities",
    "mount_identity_count",
    "mount_identity_sha256",
    "noncompose_labels",
    "process_config_sha256",
    "rollback_capsule_document",
    "source_revision",
    "state",
    "working_dir",
}
PRODUCTION_OPENAPI_CONTROL_KEYS = {
    "_contract",
    "contract_sha256",
    "operation_count",
    "path_count",
    "path_set_sha256",
    "paths",
    "probe",
    "public_endpoint",
    "schema_count",
    "security_scheme_count",
}
PRODUCTION_OPENAPI_PROBE_KEYS = {
    "container",
    "document_bytes",
    "document_sha256",
    "public_docs_config_retired",
    "source",
}
PRODUCTION_PUBLIC_OPENAPI_RETIREMENT_KEYS = {
    "body_bytes",
    "body_sha256",
    "canonical_json_sha256",
    "content_type",
    "error_code",
    "media_type",
    "method",
    "path",
    "redirect_count",
    "source_revision",
    "status_code",
}
RECOVERY_INGRESS_SUPPLEMENTAL_ENV_KEYS = {
    "EA_MEMORIAL_DATA_HOST_PATH",
    "EA_MEMORIAL_IMAGE",
    "EA_MEMORIAL_RUNTIME_HOST_PATH",
    "EA_MEMORIAL_TRUSTED_PROXY_CIDRS",
}


def _cleanup_state_directory_identity(path: Path) -> dict[str, object]:
    metadata = path.stat()
    return {
        "path": str(path),
        "dev": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "uid": int(metadata.st_uid),
        "gid": int(metadata.st_gid),
        "mode": int(stat.S_IMODE(metadata.st_mode)),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
    }


def _removed_cleanup(
    lane: joint.JointMemorialIngressDeployLane,
) -> dict[str, object]:
    return {
        "status": "removed",
        "path": str(lane.recovery_journal_path),
        "contains_secret_material": True,
        "state_directory": _cleanup_state_directory_identity(
            lane.recovery_journal_path.parent
        ),
    }


def _pending_cleanup(
    lane: joint.JointMemorialIngressDeployLane,
) -> dict[str, object]:
    return {
        "status": "pending_after_commit",
        "path": str(lane.recovery_journal_path),
        "contains_secret_material": True,
    }


class NoCommandRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        command = tuple(args)
        self.commands.append(command)
        raise AssertionError(f"unexpected command: {command}")


class RealComposeConfigRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = tuple(str(item) for item in args)
        config_index = command.index("config")
        assert command[config_index:] in {
            ("config", "--quiet"),
            ("config", "--format", "json"),
        }
        selected_environment = {str(key): str(value) for key, value in env.items()}
        self.calls.append((command, cwd, selected_environment))
        return subprocess.run(
            list(command),
            cwd=cwd,
            env=selected_environment,
            check=check,
            capture_output=True,
            text=True,
        )


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    (root / ".env").write_text("# test\n", encoding="utf-8")
    (root / ".env").chmod(0o600)
    return root


def _real_five_layer_compose_root(tmp_path: Path) -> tuple[Path, list[str]]:
    source_root = Path(__file__).resolve().parents[1]
    root = tmp_path / "real-five-layer-compose"
    root.mkdir()
    compose_files = list(api_deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER)
    assert compose_files == [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.memorial.yml",
        "docker-compose.whatsapp-web-session.yml",
        "docker-compose.cloudflared.yml",
    ]
    for filename in compose_files:
        target = root / filename
        target.write_bytes((source_root / filename).read_bytes())
        target.chmod(0o644)
    (root / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://inert:inert@ea-db:5432/ea",
                "EA_API_TOKEN=inert-api-token",
                f"EA_SOURCE_REVISION={SOURCE_REVISION}",
                "POSTGRES_PASSWORD=inert-postgres-password",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / ".env").chmod(0o600)
    runtime_env_dir = root / api_deploy.EA_RUNTIME_ENV_DIRECTORY
    runtime_env_dir.mkdir(mode=0o700)
    (runtime_env_dir / api_deploy.EA_RUNTIME_ENV_FILE).write_text(
        "# intentionally inert for recovery render compatibility\n",
        encoding="utf-8",
    )
    (runtime_env_dir / api_deploy.EA_RUNTIME_ENV_FILE).chmod(0o600)
    return root, compose_files


def _lane(
    tmp_path: Path,
    *,
    require_signed_voice_release: bool = False,
) -> tuple[joint.JointMemorialIngressDeployLane, NoCommandRunner]:
    root = _root(tmp_path)
    joint_state_dir = tmp_path / "host-state"
    joint_state_dir.mkdir(mode=0o700)
    normalization_state_dir = (
        tmp_path / recovery_interlock.NORMALIZATION_RECOVERY_STATE_DIRECTORY
    )
    normalization_state_dir.mkdir(mode=0o700)
    runner = NoCommandRunner()
    lane = joint.JointMemorialIngressDeployLane(
        root=root,
        env={
            "EA_DEPLOYMENT_ID": "joint-test-001",
            "HOME": str(tmp_path.resolve()),
        },
        runner=runner,
        receipt_dir=tmp_path / "receipts",
        ingress_receipt_dir=tmp_path / "ingress-receipts",
        global_lock_path=tmp_path / "global.lock",
        recovery_journal_path=(joint_state_dir / joint.JOINT_RECOVERY_JOURNAL_FILENAME),
        durable_root_check=lambda _path: None,
        require_signed_voice_release=require_signed_voice_release,
    )
    lane.joint_recovery_journal_path = lane.recovery_journal_path
    lane.normalization_recovery_journal_path = (
        normalization_state_dir
        / recovery_interlock.NORMALIZATION_RECOVERY_JOURNAL_FILENAME
    )
    return lane, runner


def _released_voice_candidate_state(
    lane: joint.JointMemorialIngressDeployLane,
) -> dict[str, object]:
    image_id = f"sha256:{'b' * 64}"
    voice_identity_sha256 = "c" * 64
    lane.receipt.update(
        {
            "source_revision": SOURCE_REVISION,
            "candidate_image": {"image_id": image_id},
            "candidate_promotion_evidence": {
                "source_revision": SOURCE_REVISION,
                "image_id": image_id,
                "voice_release_allowed": True,
                "voice_release_authority_revalidated": True,
                "public_evaluation_allowed": False,
                "voice_runtime_enablement_allowed": True,
                "voice_access_mode": (
                    api_deploy.VOICE_ACCESS_MODE_PUBLIC_RELEASE
                ),
                "voice_public_evaluation_authority_revalidated": False,
                "voice_authorization_authority_revalidated": True,
                "voice_identity": {
                    "voice_identity_sha256": voice_identity_sha256,
                },
            },
        }
    )
    return {
        "authorization_mode": "signed_voice_release",
        "voice_access_mode": api_deploy.VOICE_ACCESS_MODE_PUBLIC_RELEASE,
        "source_revision": SOURCE_REVISION,
        "image_id": image_id,
        "voice_identity_sha256": voice_identity_sha256,
        "voice_release_allowed": True,
        "public_evaluation_allowed": False,
        "voice_runtime_enablement_allowed": True,
        "voice_authorization_authority_revalidated": True,
    }


def _released_voice_candidate_verifier_payload(
    expectation: Mapping[str, object],
    *,
    browser_voice_release: str = "available",
    browser_voice_access: str = "public-release",
    browser_evaluation_status: str = "",
    browser_source_revision: str | None = None,
) -> dict[str, object]:
    source_revision = str(expectation["source_revision"])
    return {
        "schema": "ea.manfred_memorial_candidate_smoke.v1",
        "status": "pass",
        "checks": [
            "archive_publication_gate",
            "singular_memorial_alias",
            "source_grounded_first_person_reconstruction_boundary",
            "voice_release_authorization_verified_provider_not_called",
            "browser_provider_websocket_boundary",
        ],
        "provider_calls_performed": False,
        "page_get_performed": True,
        "voice_release_verification": {
            "mode": "signed_voice_release_authorized",
            "status_code": 400,
            "detail": "tts_text_missing",
            "authorization_proof": (
                "authorization_precedes_empty_text_validation_without_provider_call"
            ),
            "provider_calls_performed": False,
            "access_mode": expectation["voice_access_mode"],
            "source_revision": source_revision,
        },
        "browser_audit": {
            "status": "pass",
            "voice_release": browser_voice_release,
            "voice_access": browser_voice_access,
            "evaluation_status": browser_evaluation_status,
            "source_revision": browser_source_revision or source_revision,
            "conversation_action_exercised": False,
            "automatic_provider_requests": 0,
            "automatic_readiness_requests": 0,
            "automatic_microphone_requests": 0,
            "automatic_websockets": 0,
            "external_requests": 0,
            "failed_requests": 0,
            "page_errors": 0,
            "http_errors": 0,
        },
    }


def _public_evaluation_candidate_state(
    lane: joint.JointMemorialIngressDeployLane,
) -> dict[str, object]:
    image_id = f"sha256:{'b' * 64}"
    voice_identity_sha256 = "c" * 64
    lane.receipt.update(
        {
            "source_revision": SOURCE_REVISION,
            "candidate_image": {"image_id": image_id},
            "candidate_promotion_evidence": {
                "source_revision": SOURCE_REVISION,
                "image_id": image_id,
                "voice_release_allowed": False,
                "public_evaluation_allowed": True,
                "voice_runtime_enablement_allowed": True,
                "voice_access_mode": (
                    api_deploy.VOICE_ACCESS_MODE_PUBLIC_EVALUATION
                ),
                "voice_release_authority_revalidated": False,
                "voice_public_evaluation_authority_revalidated": True,
                "voice_authorization_authority_revalidated": True,
                "voice_identity": {
                    "voice_identity_sha256": voice_identity_sha256,
                },
            },
        }
    )
    return {
        "authorization_mode": "owner_authorized_public_evaluation",
        "voice_access_mode": (
            api_deploy.VOICE_ACCESS_MODE_PUBLIC_EVALUATION
        ),
        "source_revision": SOURCE_REVISION,
        "image_id": image_id,
        "voice_identity_sha256": voice_identity_sha256,
        "voice_release_allowed": False,
        "public_evaluation_allowed": True,
        "voice_runtime_enablement_allowed": True,
        "voice_authorization_authority_revalidated": True,
    }


def _public_evaluation_candidate_verifier_payload(
    expectation: Mapping[str, object],
) -> dict[str, object]:
    source_revision = str(expectation["source_revision"])
    return {
        "schema": "ea.manfred_memorial_candidate_smoke.v1",
        "status": "pass",
        "checks": [
            "archive_publication_gate",
            "singular_memorial_alias",
            "source_grounded_first_person_reconstruction_boundary",
            (
                "voice_public_evaluation_authorization_verified_"
                "provider_not_called"
            ),
            "browser_provider_websocket_boundary",
        ],
        "provider_calls_performed": False,
        "page_get_performed": True,
        "voice_release_verification": {
            "mode": "public_evaluation_authorization_verified",
            "status_code": 400,
            "detail": "tts_text_missing",
            "authorization_proof": (
                "authorization_precedes_empty_text_validation_without_provider_call"
            ),
            "provider_calls_performed": False,
            "access_mode": expectation["voice_access_mode"],
            "source_revision": source_revision,
        },
        "browser_audit": {
            "status": "pass",
            "voice_release": "blocked",
            "voice_access": "public-evaluation",
            "evaluation_status": "owner-authorized",
            "source_revision": source_revision,
            "conversation_action_exercised": False,
            "automatic_provider_requests": 0,
            "automatic_readiness_requests": 0,
            "automatic_microphone_requests": 0,
            "automatic_websockets": 0,
            "external_requests": 0,
            "failed_requests": 0,
            "page_errors": 0,
            "http_errors": 0,
        },
    }


def test_joint_phase_one_candidate_verifier_keeps_blocked_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane, _runner = _lane(tmp_path)
    lane.receipt["candidate_promotion_evidence"] = {
        "voice_release_allowed": False,
        "voice_release_authority_revalidated": False,
    }
    parent_verifier = Mock(return_value={"status": "phase_one_pass"})
    monkeypatch.setattr(
        api_deploy.MemorialDeployLane,
        "_verify_candidate_origin",
        parent_verifier,
    )

    result = lane._verify_candidate_origin(
        label="public",
        base_url=ORIGIN,
        public_origin=ORIGIN,
    )

    assert result == {"status": "phase_one_pass"}
    parent_verifier.assert_called_once_with(
        label="public",
        base_url=ORIGIN,
        public_origin=ORIGIN,
        voice_release_expectation=None,
    )


def test_joint_release_verifier_requires_revalidated_signed_authority(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    lane.receipt["candidate_promotion_evidence"] = {
        "voice_release_allowed": True,
        "voice_release_authority_revalidated": False,
    }

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_voice_authorization_authority_not_revalidated",
    ):
        lane._release_enabled_candidate_verifier_expectation()


def test_joint_release_verifier_binds_validated_candidate_state(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    expectation = _released_voice_candidate_state(lane)
    voice_verification = {
        "mode": "signed_voice_release_authorized",
        "status_code": 400,
        "detail": "tts_text_missing",
        "authorization_proof": (
            "authorization_precedes_empty_text_validation_without_provider_call"
        ),
        "provider_calls_performed": False,
        "access_mode": expectation["voice_access_mode"],
        "source_revision": expectation["source_revision"],
    }
    lane._run_json_script = Mock(  # type: ignore[method-assign]
        return_value=_released_voice_candidate_verifier_payload(expectation)
    )

    result = lane._verify_candidate_origin(
        label="public",
        base_url=ORIGIN,
        public_origin=ORIGIN,
    )

    assert result["status"] == "pass"
    assert result["provider_calls_performed"] is False
    assert result["voice_release_verification"] == voice_verification
    assert result["browser"]["voice_release"] == "available"
    assert result["browser"]["voice_access"] == "public-release"
    assert result["browser"]["evaluation_status"] == ""
    assert result["browser"]["source_revision"] == SOURCE_REVISION
    assert result["voice_release_candidate_binding"] == {
        **expectation,
        "binding_proof": (
            "validated_candidate_promotion_evidence_plus_"
            "signed_runtime_release_authorization"
        ),
    }
    command = lane._run_json_script.call_args.args
    assert "--expect-signed-voice-release" in command
    assert SOURCE_REVISION in command
    assert expectation["image_id"] not in command
    assert expectation["voice_identity_sha256"] not in command


def test_joint_public_evaluation_is_verified_without_public_release_claim(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(
        tmp_path,
        require_signed_voice_release=True,
    )
    expectation = _public_evaluation_candidate_state(lane)
    lane._run_json_script = Mock(  # type: ignore[method-assign]
        return_value=_public_evaluation_candidate_verifier_payload(
            expectation
        )
    )

    result = lane._verify_candidate_origin(
        label="public",
        base_url=ORIGIN,
        public_origin=ORIGIN,
    )

    assert result["status"] == "pass"
    assert result["provider_calls_performed"] is False
    assert result["browser"]["voice_release"] == "blocked"
    assert result["browser"]["voice_access"] == "public-evaluation"
    assert result["browser"]["evaluation_status"] == "owner-authorized"
    assert "voice_release_verification" not in result
    assert "voice_release_candidate_binding" not in result
    assert result["voice_public_evaluation_candidate_binding"] == {
        **expectation,
        "binding_proof": (
            "validated_candidate_promotion_evidence_plus_"
            "signed_public_evaluation_authorization"
        ),
    }
    command = lane._run_json_script.call_args.args
    assert "--expect-signed-voice-release" in command
    assert "--voice-access-mode" in command
    assert api_deploy.VOICE_ACCESS_MODE_PUBLIC_EVALUATION in command


def test_joint_public_evaluation_base_dispatch_uses_passive_browser_audit(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(
        tmp_path,
        require_signed_voice_release=True,
    )
    expectation = _public_evaluation_candidate_state(lane)
    lane._run_json_script = Mock(  # type: ignore[method-assign]
        return_value=_public_evaluation_candidate_verifier_payload(
            expectation
        )
    )

    lane._verify_candidate_origins(
        ORIGIN,
        candidate_promotion_evidence=dict(
            lane.receipt["candidate_promotion_evidence"]
        ),
        source_revision=SOURCE_REVISION,
    )

    evidence = lane.receipt["candidate_verifier"]
    assert len(evidence) == 1
    assert evidence[0]["browser"]["conversation_action_exercised"] is False
    assert evidence[0]["browser"]["automatic_readiness_requests"] == 0
    assert evidence[0]["browser"]["automatic_microphone_requests"] == 0
    command = lane._run_json_script.call_args.args
    assert command == (
        "scripts/verify_manfred_memorial_candidate.py",
        "--base-url",
        ORIGIN,
        "--public-origin",
        ORIGIN,
        "--wait-seconds",
        "90",
        "--browser-audit",
        "--expect-signed-voice-release",
        "--voice-access-mode",
        api_deploy.VOICE_ACCESS_MODE_PUBLIC_EVALUATION,
        "--expected-source-revision",
        SOURCE_REVISION,
    )
    verifier_env = lane._run_json_script.call_args.kwargs["env"]
    assert set(verifier_env) == {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "TMPDIR",
        "TZ",
    }
    assert "EA_DEPLOYMENT_ID" not in verifier_env


@pytest.mark.parametrize(
    "candidate_evidence",
    [
        {},
        {
            "voice_release_allowed": False,
            "voice_release_authority_revalidated": False,
        },
    ],
    ids=("missing", "phase-one"),
)
def test_joint_explicit_signed_release_intent_rejects_phase_one_fallback(
    tmp_path: Path,
    candidate_evidence: dict[str, object],
) -> None:
    lane, _runner = _lane(tmp_path, require_signed_voice_release=True)
    lane.receipt["candidate_promotion_evidence"] = candidate_evidence

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_signed_voice_release_required",
    ):
        lane._release_enabled_candidate_verifier_expectation()

    assert lane.receipt["voice_authorization_intent"] == {
        "mode": "signed_voice_authorization_required",
        "signed_voice_authorization_required": True,
        "preflight_verified": False,
    }


def test_joint_signed_release_cli_intent_is_explicit() -> None:
    args = joint._parse_args(["--require-signed-voice-release"])

    assert args.require_signed_voice_release is True


@pytest.mark.parametrize(
    (
        "browser_voice_release",
        "browser_voice_access",
        "browser_source_revision",
    ),
    [
        ("blocked", "text-only", SOURCE_REVISION),
        ("available", "text-only", SOURCE_REVISION),
        ("available", "public-release", "d" * 40),
    ],
    ids=("phase-one-state", "incoherent-pair", "revision-drift"),
)
def test_joint_signed_release_verifier_rejects_browser_state_drift(
    tmp_path: Path,
    browser_voice_release: str,
    browser_voice_access: str,
    browser_source_revision: str,
) -> None:
    lane, _runner = _lane(tmp_path, require_signed_voice_release=True)
    expectation = _released_voice_candidate_state(lane)
    lane._run_json_script = Mock(  # type: ignore[method-assign]
        return_value=_released_voice_candidate_verifier_payload(
            expectation,
            browser_voice_release=browser_voice_release,
            browser_voice_access=browser_voice_access,
            browser_source_revision=browser_source_revision,
        )
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="candidate_voice_authorization_verifier_contract_failed",
    ):
        lane._verify_candidate_origin(
            label="public",
            base_url=ORIGIN,
            public_origin=ORIGIN,
        )


def test_joint_release_verifier_rejects_receipt_binding_drift(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _released_voice_candidate_state(lane)
    evidence = dict(lane.receipt["candidate_promotion_evidence"])
    evidence["source_revision"] = "d" * 40
    lane.receipt["candidate_promotion_evidence"] = evidence

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_voice_authorization_candidate_binding_invalid",
    ):
        lane._release_enabled_candidate_verifier_expectation()


@pytest.mark.parametrize("missing_field", ["source_revision", "candidate_image"])
def test_joint_release_verifier_requires_recorded_top_level_binding(
    tmp_path: Path,
    missing_field: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    _released_voice_candidate_state(lane)
    lane.receipt.pop(missing_field)

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_voice_authorization_candidate_binding_invalid",
    ):
        lane._release_enabled_candidate_verifier_expectation()


def test_receipt_writer_rejects_precreated_temporary_symlink(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    lane.receipt_dir.mkdir(mode=0o700)
    victim = tmp_path / "victim.json"
    victim.write_text("do-not-clobber\n", encoding="utf-8")
    temporary = lane.receipt_path.with_name(
        f".{lane.receipt_path.name}.tmp.{os.getpid()}"
    )
    temporary.symlink_to(victim)

    with pytest.raises(
        api_deploy.DeployError, match="deployment_receipt_write_unavailable"
    ):
        lane._write_receipt()

    assert victim.read_text(encoding="utf-8") == "do-not-clobber\n"
    assert temporary.is_symlink()
    assert not lane.receipt_path.exists()


def test_receipt_writer_is_private_atomic_and_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane, _runner = _lane(tmp_path)
    fsync_modes: list[int] = []
    real_fsync = os.fsync

    def record_fsync(descriptor: int) -> None:
        fsync_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", record_fsync)
    lane._write_receipt()

    assert json.loads(lane.receipt_path.read_text(encoding="utf-8")) == lane.receipt
    assert lane.receipt_path.stat().st_mode & 0o777 == 0o600
    assert any(mode & 0o170000 == 0o100000 for mode in fsync_modes)
    assert any(mode & 0o170000 == 0o040000 for mode in fsync_modes)
    assert not lane.receipt_path.with_name(
        f".{lane.receipt_path.name}.tmp.{os.getpid()}"
    ).exists()


def _ingress_lane(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
) -> ingress.PublicIngressReconciliationLane:
    return ingress.PublicIngressReconciliationLane(
        root=lane.root,
        env={
            "EA_DEPLOYMENT_ID": lane.deployment_id,
            "EA_SOURCE_REVISION": SOURCE_REVISION,
            "EA_PUBLIC_ORIGIN": "https://myexternalbrain.com",
        },
        runner=lane.runner,
        receipt_dir=tmp_path / "ingress-receipts",
        global_lock_path=tmp_path / "global.lock",
    )


def _materialize_ingress_rollback_fixture(
    lane: joint.JointMemorialIngressDeployLane,
    ingress_lane: ingress.PublicIngressReconciliationLane,
) -> dict[str, object]:
    compose_path = lane.root / "docker-compose.yml"
    if not compose_path.exists():
        compose_path.write_text(
            "services:\n  ea-cloudflared:\n    image: test-cloudflared\n",
            encoding="utf-8",
        )
        compose_path.chmod(0o644)

    lane.ingress_receipt_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    lane.ingress_receipt_dir.chmod(0o700)
    overlay_path = lane.ingress_receipt_dir / (
        f"{lane.deployment_id}.{joint.INGRESS_ROLLBACK_OVERLAY_SUFFIX}"
    )
    overlay_raw = (
        f"# {joint.INGRESS_ROLLBACK_OVERLAY_CONTRACT_NAME}\n"
        "services:\n"
        f"  {ingress.CLOUDFLARED_SERVICE}:\n"
        "    networks: !override\n"
        "      public_ingress:\n"
        f'        ipv4_address: "{ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4}"\n'
        "        aliases:\n"
        f'          - "{ingress.CLOUDFLARED_SERVICE}"\n'
        f'          - "{ingress.CLOUDFLARED_CONTAINER}"\n'
        "networks:\n"
        "  public_ingress: !override\n"
        "    external: true\n"
        f'    name: "{ingress.PUBLIC_INGRESS_NETWORK}"\n'
    ).encode("utf-8")
    if not overlay_path.exists():
        overlay_path.write_bytes(overlay_raw)
        overlay_path.chmod(0o600)
    elif overlay_path.read_bytes() != overlay_raw:
        raise AssertionError("rollback overlay fixture changed unexpectedly")

    baseline_files = [str(compose_path)]
    rollback_files = [*baseline_files, str(overlay_path)]
    baseline_seals = ingress_lane._capture_compose_input_seals(
        root=lane.root,
        files=baseline_files,
    )
    rollback_seals = ingress_lane._capture_compose_input_seals(
        root=lane.root,
        files=rollback_files,
    )
    overlay_seal = next(
        seal for seal in rollback_seals if seal.get("path") == str(overlay_path)
    )
    return {
        "baseline_files": baseline_files,
        "baseline_seals": baseline_seals,
        "working_dir": str(lane.root),
        "compose_files": rollback_files,
        "input_seals": rollback_seals,
        "overlay": {
            "contract_name": joint.INGRESS_ROLLBACK_OVERLAY_CONTRACT_NAME,
            "path": str(overlay_path),
            "sha256": str(overlay_seal["sha256"]),
            "contains_secret_material": False,
            "runtime_network_names": [ingress.PUBLIC_INGRESS_NETWORK],
            "logical_network_names": ["public_ingress"],
            "normalized_property_detachment": False,
        },
    }


def _context(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
) -> dict[str, object]:
    ingress_lane = _ingress_lane(lane, tmp_path)
    rollback_fixture = _materialize_ingress_rollback_fixture(
        lane,
        ingress_lane,
    )
    public_edge = {"version_get": {"status": 421}}
    rollback_projection = {
        "service": {
            "image": ingress.PINNED_CLOUDFLARED_IMAGE,
            "environment": {"TUNNEL_TOKEN": "test-tunnel-token"},
            "networks": {
                "public_ingress": {
                    "ipv4_address": ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4,
                    "aliases": sorted(
                        [
                            ingress.CLOUDFLARED_CONTAINER,
                            ingress.CLOUDFLARED_SERVICE,
                        ]
                    ),
                },
            },
        },
        "networks": {
            "public_ingress": {
                "external": True,
                "name": ingress.PUBLIC_INGRESS_NETWORK,
            },
        },
    }
    candidate_path = tmp_path / "candidate.private.json"
    previous = _capsule_backed_previous(lane)
    return {
        "authority": {"authority_posture": "governed"},
        "previous": previous,
        "candidate": {
            "reference": f"ea-runtime:manfred-{SOURCE_REVISION}",
            "image_id": "sha256:" + "2" * 64,
        },
        "candidate_promotion": {
            "path": str(candidate_path),
            "sha256": "4" * 64,
            "schema": joint.CANDIDATE_RUNTIME_SCHEMA,
            "status": "pass",
            "source_revision": SOURCE_REVISION,
            "projection": {},
            "spatial_handoff": {
                "browser_schema": joint.CANDIDATE_BROWSER_SCHEMA,
                "browser_pass": True,
                "identity_bound": True,
            },
        },
        "spatial_browser_binding": {
            "status": "pass",
            "candidate_runtime_receipt_path": str(candidate_path),
            "candidate_runtime_receipt_sha256": "4" * 64,
            "candidate_runtime_schema": joint.CANDIDATE_RUNTIME_SCHEMA,
            "browser_receipt_path": str(tmp_path / "browser.private.json"),
            "browser_receipt_sha256": "5" * 64,
            "browser_schema": joint.CANDIDATE_BROWSER_SCHEMA,
            "secret_material_recorded": False,
            "exact_embedded_binding": True,
        },
        "deployment_input_seal": {
            "forward": [lane._deployment_input_file_seal(lane.root / ".env")],
            "rollback": [lane._deployment_input_file_seal(lane.rollback_capsule_path)],
        },
        "source_revision": SOURCE_REVISION,
        "public_origin": "https://myexternalbrain.com",
        "api_local_origin": "http://127.0.0.1:8090",
        "docker_daemon_identity": {
            "identity_source": "docker_info_engine_id",
            "daemon_id_sha256": "6" * 64,
        },
        "non_memorial_controls": {},
        "target_mounts": [],
        "ingress": {
            "lane": ingress_lane,
            "cloudflared_baseline": {"container": {}},
            "network_baseline": {"present": False},
            "public_edge_baseline": public_edge,
            "rollback_input_seals": list(rollback_fixture["input_seals"]),
            "rollback_working_dir": str(rollback_fixture["working_dir"]),
            "rollback_compose_files": list(rollback_fixture["compose_files"]),
            "rollback_overlay": dict(rollback_fixture["overlay"]),
            "rollback_interpolation_environment": {
                "EA_CF_TUNNEL_TOKEN": "test-tunnel-token",
                "EA_PUBLIC_INGRESS_CLOUDFLARED_IPV4": (
                    ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4
                ),
                "EA_PUBLIC_INGRESS_GATEWAY": ingress.PUBLIC_INGRESS_GATEWAY,
                "EA_PUBLIC_INGRESS_NETWORK_NAME": ingress.PUBLIC_INGRESS_NETWORK,
                "EA_PUBLIC_INGRESS_SUBNET": ingress.PUBLIC_INGRESS_SUBNET,
            },
            "rollback_render_projection": rollback_projection,
            "rollback_render_sha256": joint._canonical_json_sha256(rollback_projection),
            "target_input_seals": [{"scope": "target"}],
            "target_rendered": {},
        },
    }


def _capsule_backed_previous(
    lane: joint.JointMemorialIngressDeployLane,
) -> dict[str, object]:
    cached = getattr(lane, "_test_capsule_backed_previous", None)
    if isinstance(cached, dict):
        return deepcopy(cached)

    original_runner = lane.runner
    try:
        previous_runner = MemorialFakeRunner(lane.root)
        previous_runner.prior_container_id = "c" * 64
        lane.runner = previous_runner
        previous = lane._previous_api()
    finally:
        lane.runner = original_runner
    original_write_receipt = lane._write_receipt
    try:
        # Production materializes this after deploy() owns its receipt path.
        # Test contexts are assembled before deploy() acquires that path, so
        # retain the real capsule write while suppressing only the premature
        # transaction-receipt publication.
        lane._write_receipt = Mock()  # type: ignore[method-assign]
        lane._materialize_rollback_capsule(
            dict(previous["rollback_capsule_document"]),
            dict(previous["functional_identity"]),
        )
    finally:
        lane._write_receipt = original_write_receipt  # type: ignore[method-assign]
    setattr(lane, "_test_capsule_backed_previous", deepcopy(previous))
    return deepcopy(previous)


def _restart_lane(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
    *,
    deployment_id: str = "joint-restart-002",
    root: Path | None = None,
    receipt_dir: Path | None = None,
    ingress_receipt_dir: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> joint.JointMemorialIngressDeployLane:
    restarted = joint.JointMemorialIngressDeployLane(
        root=(root or lane.root),
        env={"EA_DEPLOYMENT_ID": deployment_id, **dict(extra_env or {})},
        runner=NoCommandRunner(),
        receipt_dir=(receipt_dir or lane.receipt_dir),
        ingress_receipt_dir=(ingress_receipt_dir or tmp_path / "ingress-receipts"),
        global_lock_path=tmp_path / "global.lock",
        recovery_journal_path=lane.recovery_journal_path,
        durable_root_check=lambda _path: None,
    )
    restarted.joint_recovery_journal_path = restarted.recovery_journal_path
    restarted.normalization_recovery_journal_path = (
        tmp_path
        / recovery_interlock.NORMALIZATION_RECOVERY_STATE_DIRECTORY
        / recovery_interlock.NORMALIZATION_RECOVERY_JOURNAL_FILENAME
    )
    return restarted


def _install_successful_compose_detection(
    lane: joint.JointMemorialIngressDeployLane,
) -> Mock:
    def detect() -> None:
        lane.compose_bin = ("docker", "compose")

    compose_runner = Mock()

    def detect_ingress(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        command = tuple(args)
        if command != ("docker", "compose", "version"):
            raise AssertionError(f"unexpected recovery command: {command}")
        return subprocess.CompletedProcess(
            list(args),
            0,
            stdout="Docker Compose version v2\n",
            stderr="",
        )

    compose_runner.run.side_effect = detect_ingress
    lane.runner = compose_runner
    detection = Mock(side_effect=detect)
    lane._detect_compose = detection  # type: ignore[method-assign]
    return detection


def _valid_non_memorial_controls(
    lane: joint.JointMemorialIngressDeployLane,
) -> dict[str, object]:
    openapi_document = {
        "openapi": "3.1.0",
        "info": {"title": "EA", "version": "1.0.0"},
        "paths": {
            "/health": {
                "get": {
                    "responses": {
                        "200": {"description": "OK"},
                    }
                }
            }
        },
        "components": {"schemas": {}, "securitySchemes": {}},
    }
    retired_body = b'{"error":{"code":"not_found"}}'
    original_internal_snapshot = lane.internal_openapi_snapshot
    original_http_no_redirect = lane.http_no_redirect
    try:
        lane.internal_openapi_snapshot = lambda: {
            "docs_url": None,
            "document": openapi_document,
            "openapi_url": None,
            "redoc_url": None,
        }
        lane.http_no_redirect = lambda *_args: api_deploy.HttpResponse(
            404,
            "application/json",
            retired_body,
            SOURCE_REVISION,
            headers={},
        )
        openapi = lane._capture_internal_openapi_control()
        openapi["public_endpoint"] = lane._capture_public_openapi_retirement(
            "https://myexternalbrain.com",
            expected_source_revision=SOURCE_REVISION,
        )
    finally:
        lane.internal_openapi_snapshot = original_internal_snapshot
        lane.http_no_redirect = original_http_no_redirect
    return {"openapi": openapi}


def _recovery_context(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
) -> dict[str, object]:
    context = _context(lane, tmp_path)
    ingress_context = context["ingress"]
    assert isinstance(ingress_context, dict)
    ingress_root = lane.root
    rollback_files = list(ingress_context["rollback_compose_files"])
    rollback_seals = list(ingress_context["rollback_input_seals"])
    rollback_overlay = dict(ingress_context["rollback_overlay"])
    ingress_compose_files = rollback_files[:-1]
    ingress_baseline_seals = [
        dict(item)
        for item in rollback_seals
        if dict(item).get("path") != rollback_overlay["path"]
    ]
    context["non_memorial_controls"] = _valid_non_memorial_controls(lane)
    rollback_projection = context["ingress"]["rollback_render_projection"]
    assert isinstance(rollback_projection, dict)
    public_edge_baseline = {}
    for probe in ingress.PUBLIC_PROBES:
        for method in ("GET", "HEAD"):
            public_edge_baseline[f"{probe.label}_{method.lower()}"] = {
                "method": method,
                "path": probe.path,
                "status": 421,
                "content_type": "application/json",
                "source_revision": "",
                "location": "",
                "body_bytes": 0 if method == "HEAD" else 2,
                "body_sha256": "5" * 64,
            }
    cloudflared_baseline = {
        "contract_name": "ea.public_ingress_cloudflared_baseline.v1",
        "captured_at": "2026-07-20T09:00:00Z",
        "container": {
            "id": "prior-cloudflared-container",
            "created_at": "2026-07-20T09:00:00Z",
            "image_id": "sha256:" + "9" * 64,
            "image_reference": ingress.PINNED_CLOUDFLARED_IMAGE,
            "compose_working_dir": str(ingress_root),
            "compose_config_files": ingress_compose_files,
            "compose_input_seals": ingress_baseline_seals,
            "environment_identity": {
                "environment_sha256": "a" * 64,
                "environment_count": 1,
            },
            "command": ["tunnel", "run"],
            "entrypoint": ["cloudflared"],
            "user": "65532:65532",
            "process_config_sha256": "b" * 64,
            "security": {
                "cap_drop": ["ALL"],
                "memory": 268435456,
                "memory_reservation": 67108864,
                "pids_limit": 128,
                "privileged": False,
                "read_only": False,
                "restart": "unless-stopped",
                "security_opt": ["no-new-privileges"],
            },
            "mounts": [],
            "networks": [
                {
                    "name": ingress.PUBLIC_INGRESS_NETWORK,
                    "network_id": "c" * 64,
                    "driver": "bridge",
                    "ipam_driver": "default",
                    "ipam_config": [
                        {
                            "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                            "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
                        }
                    ],
                    "internal": False,
                    "attachable": False,
                    "ipv4_address": ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4,
                    "aliases": [
                        ingress.CLOUDFLARED_SERVICE,
                        ingress.CLOUDFLARED_CONTAINER,
                    ],
                }
            ],
        },
        "contains_environment_values": False,
        "contains_tunnel_token": False,
        "restoration": {
            "status": "coordinator_required",
            "reason": "standalone_mutation_not_supported",
            "compose_no_deps_required": True,
            "network_removal_allowed": False,
        },
    }
    ingress_context.update(
        {
            "cloudflared_baseline": cloudflared_baseline,
            "network_baseline": {"present": False},
            "public_edge_baseline": public_edge_baseline,
            "rollback_input_seals": rollback_seals,
            "rollback_working_dir": str(ingress_root),
            "rollback_compose_files": rollback_files,
            "rollback_overlay": rollback_overlay,
            "rollback_render_sha256": joint._canonical_json_sha256(rollback_projection),
        }
    )
    lane.receipt_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    lane.receipt_dir.chmod(0o700)
    lane.ingress_receipt_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    lane.ingress_receipt_dir.chmod(0o700)
    return context


def _write_recovery_journal(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
    *,
    phase: str,
) -> dict[str, object]:
    context = _recovery_context(lane, tmp_path)
    journal_payload = lane._new_recovery_journal(
        context=context,
        rollback_tag="ea-runtime:memorial-rollback-joint-test-001",
    )
    if phase == "prepared":
        api_possible = False
        ingress_possible = False
    elif phase == "api_mutation_possible":
        api_possible = True
        ingress_possible = False
    else:
        api_possible = True
        ingress_possible = True
    journal_payload.update(
        {
            "phase": phase,
            "api_mutation_possible": api_possible,
            "ingress_mutation_possible": ingress_possible,
        }
    )
    lane._write_recovery_journal(journal_payload)
    return journal_payload


def _rollback_authority_context(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
    *,
    api_mutation_started: bool,
    ingress_mutation_started: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    context = _recovery_context(lane, tmp_path)
    journal_payload = lane._new_recovery_journal(
        context=context,
        rollback_tag=joint._safe_rollback_tag(lane.deployment_id),
    )
    journal_payload.update(
        {
            "phase": "rollback_in_progress",
            "api_mutation_possible": api_mutation_started,
            "ingress_mutation_possible": ingress_mutation_started,
        }
    )
    lane._write_recovery_journal(journal_payload)
    return lane._validate_recovery_journal(journal_payload)


def test_recovery_ingress_api_interpolation_is_exact_inert_and_ambient_safe(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context = _context(lane, tmp_path)
    previous = dict(context["previous"])
    ingress_context = dict(context["ingress"])
    recorded_ingress_environment = dict(
        ingress_context["rollback_interpolation_environment"]
    )
    ambient_values = {
        "DATABASE_URL": "ambient-database-secret",
        "EA_API_TOKEN": "ambient-api-secret",
        "EA_CF_TUNNEL_TOKEN": "ambient-tunnel-secret",
        "EA_MEMORIAL_DATA_HOST_PATH": "/ambient/data",
        "EA_MEMORIAL_IMAGE": "ea-runtime:ambient",
        "EA_MEMORIAL_RUNTIME_HOST_PATH": "/ambient/runtime",
        "EA_MEMORIAL_TRUSTED_PROXY_CIDRS": "198.51.100.0/24",
        "UNRELATED_SECRET": "ambient-unrelated-secret",
    }
    lane.env.update(ambient_values)

    supplemental = lane._recovery_ingress_api_interpolation_environment(previous)

    assert set(supplemental) == RECOVERY_INGRESS_SUPPLEMENTAL_ENV_KEYS
    assert set(supplemental) == set(joint.RECOVERY_INGRESS_API_INTERPOLATION_ENV_KEYS)
    assert supplemental == {
        "EA_MEMORIAL_DATA_HOST_PATH": str(joint.RECOVERY_INGRESS_INERT_DATA_HOST_PATH),
        "EA_MEMORIAL_IMAGE": previous["image_reference"],
        "EA_MEMORIAL_RUNTIME_HOST_PATH": str(
            joint.RECOVERY_INGRESS_INERT_RUNTIME_HOST_PATH
        ),
        "EA_MEMORIAL_TRUSTED_PROXY_CIDRS": (
            f"{ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4}/32"
        ),
    }
    assert all(
        Path(value).is_absolute()
        for key, value in supplemental.items()
        if key.endswith("_HOST_PATH")
    )
    assert all(
        Path(value).parent == Path("/dev/null")
        for key, value in supplemental.items()
        if key.endswith("_HOST_PATH")
    )

    recovery_ingress = lane._build_ingress_lane(
        {
            "source_revision": SOURCE_REVISION,
            "public_origin": "https://myexternalbrain.com",
        },
        deployment_id="recorded-recovery-transaction",
        root=lane.root,
        receipt_dir=lane.ingress_receipt_dir,
        rollback_interpolation_environment=recorded_ingress_environment,
        recovery_previous=previous,
    )
    expected_release_environment = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        **recorded_ingress_environment,
        **supplemental,
        "COMPOSE_PROJECT_NAME": api_deploy.PROJECT_NAME,
        "EA_DEPLOYMENT_ID": "recorded-recovery-transaction",
        "EA_PUBLIC_ORIGIN": "https://myexternalbrain.com",
        "EA_SOURCE_REVISION": SOURCE_REVISION,
    }
    assert recovery_ingress.release_env == expected_release_environment
    assert set(recovery_ingress.release_env) == set(expected_release_environment)
    for key, value in ambient_values.items():
        if key in expected_release_environment:
            assert recovery_ingress.release_env[key] != value
        else:
            assert key not in recovery_ingress.release_env
        assert value not in recovery_ingress.release_env.values()


def test_recovery_environment_renders_real_five_layer_compose_unchanged(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context = _context(lane, tmp_path)
    previous = dict(context["previous"])
    ingress_context = dict(context["ingress"])
    recorded_ingress_environment = dict(
        ingress_context["rollback_interpolation_environment"]
    )
    ambient_secret_values = {
        "DATABASE_URL": "ambient-database-secret",
        "EA_API_TOKEN": "ambient-api-secret",
        "EA_CF_TUNNEL_TOKEN": "ambient-tunnel-secret",
        "EA_MEMORIAL_IMAGE": "ea-runtime:ambient",
        "UNRELATED_SECRET": "ambient-unrelated-secret",
    }
    lane.env.update(ambient_secret_values)
    compose_root, compose_files = _real_five_layer_compose_root(tmp_path)
    runner = RealComposeConfigRunner()
    lane.runner = runner
    recovery_ingress = lane._build_ingress_lane(
        {
            "source_revision": SOURCE_REVISION,
            "public_origin": "https://myexternalbrain.com",
        },
        deployment_id="real-compose-recovery",
        root=compose_root,
        receipt_dir=tmp_path / "real-compose-receipts",
        rollback_interpolation_environment=recorded_ingress_environment,
        recovery_previous=previous,
    )
    recovery_ingress.compose_bin = ("docker", "compose")

    rendered, seals = recovery_ingress._render_compose(
        root=compose_root,
        files=compose_files,
    )

    assert len(seals) == 7
    assert [
        command[command.index("config") :]
        for command, _cwd, _environment in runner.calls
    ] == [
        ("config", "--quiet"),
        ("config", "--format", "json"),
    ]
    assert all(cwd == compose_root for _command, cwd, _environment in runner.calls)
    assert all(
        environment == recovery_ingress.release_env
        for _command, _cwd, environment in runner.calls
    )
    projection = lane._ingress_rollback_projection(rendered)
    assert lane._ingress_rollback_environment(projection) == (
        recorded_ingress_environment
    )
    assert dict(projection["service"])["image"] == ingress.PINNED_CLOUDFLARED_IMAGE
    rendered_api = dict(dict(rendered["services"])[api_deploy.API_SERVICE])
    assert rendered_api["image"] == previous["image_reference"]
    assert dict(rendered_api["environment"])["EA_TRUSTED_PROXY_CIDRS"] == (
        f"{ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4}/32"
    )
    rendered_json = json.dumps(rendered, sort_keys=True)
    assert all(value not in rendered_json for value in ambient_secret_values.values())


def test_v3_recovery_round_trips_capsule_backed_previous_api(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )

    journal, context = lane._validate_recovery_journal(payload)

    previous = dict(context["previous"])
    openapi = dict(dict(context["non_memorial_controls"])["openapi"])
    openapi_probe = dict(openapi["probe"])
    public_endpoint = dict(openapi["public_endpoint"])
    deployment_seal = dict(context["deployment_input_seal"])
    rollback_seals = list(deployment_seal["rollback"])
    assert journal["contract_name"] == joint.JOINT_RECOVERY_JOURNAL_CONTRACT_NAME
    assert journal["version"] == 3
    assert set(previous) == PRODUCTION_PREVIOUS_API_KEYS
    assert "rollback_environment" not in previous
    assert len(rollback_seals) == 1
    assert rollback_seals[0] == lane._deployment_input_file_seal(
        lane.rollback_capsule_path
    )
    assert (
        json.loads(lane.rollback_capsule_path.read_text(encoding="utf-8"))
        == (previous["rollback_capsule_document"])
    )
    assert (
        previous["functional_identity"]
        == dict(previous["rollback_capsule_document"])["x-ea-rollback-capsule"][
            "functional_identity"
        ]
    )
    assert set(openapi) == PRODUCTION_OPENAPI_CONTROL_KEYS
    assert openapi["paths"] == ["/health"]
    assert set(openapi_probe) == PRODUCTION_OPENAPI_PROBE_KEYS
    assert openapi_probe == {
        "container": "ea-api",
        "document_bytes": 179,
        "document_sha256": (
            "fc6c6efc6cb44dc04c690bfaf22219a20f7540c07481366a405797f32443eecb"
        ),
        "public_docs_config_retired": True,
        "source": "deployed_api_container_app.openapi",
    }
    assert set(public_endpoint) == PRODUCTION_PUBLIC_OPENAPI_RETIREMENT_KEYS
    assert public_endpoint == {
        "body_bytes": 30,
        "body_sha256": (
            "61b5f4a46397ebc3f13ec8414b0f3387b404c52120a9a68c320bc3e6808f3b8b"
        ),
        "canonical_json_sha256": (
            "61b5f4a46397ebc3f13ec8414b0f3387b404c52120a9a68c320bc3e6808f3b8b"
        ),
        "content_type": "application/json",
        "error_code": "not_found",
        "media_type": "application/json",
        "method": "GET",
        "path": "/openapi.json",
        "redirect_count": 0,
        "source_revision": SOURCE_REVISION,
        "status_code": 404,
    }
    assert runner.commands == []


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_public_endpoint",
        "extra_public_endpoint_key",
        "tampered_public_endpoint",
        "public_endpoint_schema",
        "public_endpoint_source_revision",
        "paths_schema",
        "paths_tamper",
        "path_hash_tamper",
        "contract_hash_tamper",
        "probe_schema",
    ],
)
def test_v3_recovery_rejects_openapi_public_retirement_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    openapi = payload["rollback_context"]["non_memorial_controls"]["openapi"]
    public_endpoint = openapi["public_endpoint"]
    if mutation == "missing_public_endpoint":
        openapi.pop("public_endpoint")
    elif mutation == "extra_public_endpoint_key":
        public_endpoint["unexpected"] = True
    elif mutation == "tampered_public_endpoint":
        public_endpoint["status_code"] = 200
    elif mutation == "public_endpoint_schema":
        openapi["public_endpoint"] = []
    elif mutation == "public_endpoint_source_revision":
        public_endpoint["source_revision"] = "f" * 40
    elif mutation == "paths_schema":
        openapi["paths"] = "/health"
    elif mutation == "paths_tamper":
        openapi["paths"].append("/private")
    elif mutation == "path_hash_tamper":
        openapi["path_set_sha256"] = "f" * 64
    elif mutation == "contract_hash_tamper":
        openapi["contract_sha256"] = "f" * 64
    else:
        openapi["probe"]["unexpected"] = True

    with pytest.raises(
        api_deploy.DeployError,
        match="^joint_recovery_non_memorial_baseline_invalid$",
    ):
        lane._validate_recovery_journal(payload)

    assert runner.commands == []
    assert lane.recovery_journal_path.exists()
    assert lane.rollback_capsule_path.exists()


@pytest.mark.parametrize(
    "missing_field",
    [
        "source_revision",
        "noncompose_labels",
        "functional_identity",
        "rollback_capsule_document",
    ],
)
def test_v3_recovery_rejects_legacy_previous_api_shape(
    tmp_path: Path,
    missing_field: str,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    previous = payload["rollback_context"]["previous"]
    previous.pop(missing_field)
    previous["rollback_environment"] = {}

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_recovery_previous_api_invalid",
    ):
        lane._validate_recovery_journal(payload)

    assert runner.commands == []
    assert lane.recovery_journal_path.exists()
    assert lane.rollback_capsule_path.exists()


@pytest.mark.parametrize(
    ("authority", "expected_reason"),
    [
        ("source_revision", "joint_recovery_previous_api_invalid"),
        ("functional_identity", "joint_recovery_previous_api_invalid"),
        ("capsule_image", "joint_recovery_rollback_capsule_bytes_mismatch"),
    ],
)
def test_v3_recovery_rejects_previous_capsule_authority_drift(
    tmp_path: Path,
    authority: str,
    expected_reason: str,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    previous = payload["rollback_context"]["previous"]
    if authority == "source_revision":
        previous["source_revision"] = "not-a-revision"
    elif authority == "functional_identity":
        previous["functional_identity"]["functional_identity_sha256"] = "f" * 64
    else:
        previous["rollback_capsule_document"]["x-ea-rollback-capsule"][
            "source_image_id"
        ] = "sha256:" + "f" * 64

    with pytest.raises(
        api_deploy.DeployError,
        match=f"^{expected_reason}$",
    ):
        lane._validate_recovery_journal(payload)

    assert runner.commands == []
    assert lane.recovery_journal_path.exists()
    assert lane.rollback_capsule_path.exists()


@pytest.mark.parametrize("prior_image_mutation", ("missing", "tampered"))
def test_recover_active_rejects_invalid_prior_image_before_any_command(
    tmp_path: Path,
    prior_image_mutation: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    previous = payload["rollback_context"]["previous"]
    if prior_image_mutation == "missing":
        previous.pop("image_reference")
    else:
        previous["image_reference"] = "ea-runtime:attacker"
    lane._write_recovery_journal(payload)
    restarted = _restart_lane(lane, tmp_path)
    restarted._detect_compose = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("invalid prior image reached compose detection")
    )
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("invalid prior image reached rollback mutation")
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="^joint_recovery_previous_api_invalid$",
    ):
        restarted.recover_active()

    assert isinstance(restarted.runner, NoCommandRunner)
    assert restarted.runner.commands == []
    restarted._detect_compose.assert_not_called()
    restarted._perform_joint_rollback.assert_not_called()
    assert restarted.recovery_journal_path.exists()
    assert lane.rollback_capsule_path.exists()


@pytest.mark.parametrize(
    ("tamper", "expected_reason"),
    [
        ("file_bytes", "joint_recovery_rollback_capsule_seal_mismatch"),
        ("replacement_inode", "joint_recovery_rollback_capsule_seal_mismatch"),
        ("sealed_sha256", "joint_recovery_rollback_capsule_seal_mismatch"),
        ("embedded_document", "joint_recovery_rollback_capsule_bytes_mismatch"),
    ],
)
def test_v3_recovery_rejects_capsule_tamper_before_commands(
    tmp_path: Path,
    tamper: str,
    expected_reason: str,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    capsule_path = lane.rollback_capsule_path
    if tamper == "file_bytes":
        capsule_path.write_bytes(capsule_path.read_bytes() + b"\n")
    elif tamper == "replacement_inode":
        original = capsule_path.read_bytes()
        replacement = capsule_path.with_suffix(".replacement")
        replacement.write_bytes(original)
        replacement.chmod(0o600)
        os.replace(replacement, capsule_path)
    elif tamper == "sealed_sha256":
        payload["rollback_context"]["deployment_input_seal"]["rollback"][0][
            "sha256"
        ] = "f" * 64
    else:
        payload["rollback_context"]["previous"]["rollback_capsule_document"]["name"] = (
            "tampered-capsule"
        )

    with pytest.raises(
        api_deploy.DeployError,
        match=f"^{expected_reason}$",
    ):
        lane._validate_recovery_journal(payload)

    assert runner.commands == []
    assert lane.recovery_journal_path.exists()
    assert capsule_path.exists()


def test_recover_active_abandons_prepared_transaction_without_new_deploy(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    journal = _write_recovery_journal(
        lane,
        tmp_path,
        phase="prepared",
    )
    lane.preflight = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("recover-active continued into preflight")
    )

    receipt = lane.recover_active()

    assert receipt["status"] == "active_recovery_complete"
    assert receipt["recovery"] == {
        "status": "prepared_transaction_abandoned",
        "transaction_id": journal["transaction_id"],
        "journal_sha256": receipt["recovery"]["journal_sha256"],
        "mutation_attempted": False,
    }
    assert receipt["recover_active"] == {
        "status": "pass",
        "recovery_status": "prepared_transaction_abandoned",
        "new_deployment_started": False,
    }
    lane.preflight.assert_not_called()
    assert runner.commands == []
    assert not lane.recovery_journal_path.exists()


def test_interrupted_recovery_detects_compose_before_capsule_render_and_rollback(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    actions: list[str] = []
    detection_count = 0
    detection_runner = Mock()

    def run_detection(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal detection_count
        del cwd, env, check
        assert tuple(args) == ("docker", "compose", "version")
        detection_count += 1
        actions.append(
            "detect_api_compose" if detection_count == 1 else "detect_ingress_compose"
        )
        return subprocess.CompletedProcess(
            list(args),
            0,
            stdout="Docker Compose version v2\n",
            stderr="",
        )

    detection_runner.run.side_effect = run_detection
    lane.runner = detection_runner

    def prevalidate(
        recovery_context: Mapping[str, object],
        _rollback_tag: str,
    ) -> None:
        ingress_context = dict(recovery_context["ingress"])
        ingress_lane = ingress_context["lane"]
        assert isinstance(
            ingress_lane,
            ingress.PublicIngressReconciliationLane,
        )
        assert lane.compose_bin == ("docker", "compose")
        assert ingress_lane.compose_bin == ("docker", "compose")
        actions.append("capsule_render")

    lane._prevalidate_recovery_context = Mock(  # type: ignore[method-assign]
        side_effect=prevalidate
    )
    lane._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=lambda **_kwargs: actions.append("rollback") or {"status": "pass"}
    )

    assert lane.compose_bin == ()
    lane._recover_interrupted_transaction(preflight_only=False)

    assert actions == [
        "detect_api_compose",
        "detect_ingress_compose",
        "capsule_render",
        "rollback",
    ]
    assert detection_runner.run.call_count == 2
    lane._prevalidate_recovery_context.assert_called_once()
    lane._perform_joint_rollback.assert_called_once()
    assert lane.receipt["recovery"]["status"] == "pass"
    assert not lane.recovery_journal_path.exists()


def test_interrupted_recovery_compose_detection_failure_is_pre_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    commands: list[tuple[str, ...]] = []
    detection_runner = Mock()

    def fail_detection(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        command = tuple(args)
        commands.append(command)
        return subprocess.CompletedProcess(
            list(args),
            1,
            stdout="",
            stderr="compose unavailable",
        )

    detection_runner.run.side_effect = fail_detection
    lane.runner = detection_runner
    lane._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    lane._perform_joint_rollback = Mock()  # type: ignore[method-assign]
    phases: list[str] = []
    real_set_recovery_phase = lane._set_recovery_phase

    def track_phase(
        journal_payload: dict[str, object],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        phases.append(phase)
        real_set_recovery_phase(
            journal_payload,
            phase,
            api_mutation_possible=api_mutation_possible,
            ingress_mutation_possible=ingress_mutation_possible,
        )

    lane._set_recovery_phase = Mock(  # type: ignore[method-assign]
        side_effect=track_phase
    )

    with pytest.raises(
        api_deploy.DeployError,
        match=(
            "^joint_interrupted_transaction_recovery_failed:docker_compose_unavailable$"
        ),
    ):
        lane._recover_interrupted_transaction(preflight_only=False)

    retained = json.loads(lane.recovery_journal_path.read_text(encoding="utf-8"))
    assert commands == [
        ("docker", "compose", "version"),
        ("docker-compose", "version"),
    ]
    assert phases == ["rollback_failed"]
    assert retained["phase"] == "rollback_failed"
    assert retained["recovery_attempts"] == 0
    assert lane.receipt["status"] == "interrupted_transaction_recovery_failed"
    assert lane.receipt["recovery"]["status"] == "fail"
    assert lane.receipt["recovery"]["reason"] == "docker_compose_unavailable"
    assert lane.compose_bin == ()
    lane._prevalidate_recovery_context.assert_not_called()
    lane._perform_joint_rollback.assert_not_called()


def test_interrupted_recovery_ingress_compose_detection_failure_is_pre_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    commands: list[tuple[str, ...]] = []
    detection_runner = Mock()

    def fail_ingress_detection(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        command = tuple(args)
        commands.append(command)
        api_detection = len(commands) == 1
        return subprocess.CompletedProcess(
            list(args),
            0 if api_detection else 1,
            stdout=("Docker Compose version v2\n" if api_detection else ""),
            stderr=("" if api_detection else "ingress compose unavailable"),
        )

    detection_runner.run.side_effect = fail_ingress_detection
    lane.runner = detection_runner
    reconstructed_ingress_lanes: list[ingress.PublicIngressReconciliationLane] = []
    real_build_ingress_lane = lane._build_ingress_lane

    def capture_ingress_lane(
        *args: object,
        **kwargs: object,
    ) -> ingress.PublicIngressReconciliationLane:
        ingress_lane = real_build_ingress_lane(*args, **kwargs)
        reconstructed_ingress_lanes.append(ingress_lane)
        return ingress_lane

    lane._build_ingress_lane = Mock(  # type: ignore[method-assign]
        side_effect=capture_ingress_lane
    )
    lane._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    lane._perform_joint_rollback = Mock()  # type: ignore[method-assign]
    phases: list[str] = []
    real_set_recovery_phase = lane._set_recovery_phase

    def track_phase(
        journal_payload: dict[str, object],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        phases.append(phase)
        real_set_recovery_phase(
            journal_payload,
            phase,
            api_mutation_possible=api_mutation_possible,
            ingress_mutation_possible=ingress_mutation_possible,
        )

    lane._set_recovery_phase = Mock(  # type: ignore[method-assign]
        side_effect=track_phase
    )

    with pytest.raises(
        api_deploy.DeployError,
        match=(
            "^joint_interrupted_transaction_recovery_failed:docker_compose_unavailable$"
        ),
    ):
        lane._recover_interrupted_transaction(preflight_only=False)

    retained = json.loads(lane.recovery_journal_path.read_text(encoding="utf-8"))
    assert commands == [
        ("docker", "compose", "version"),
        ("docker", "compose", "version"),
        ("docker-compose", "version"),
    ]
    assert phases == ["rollback_failed"]
    assert retained["phase"] == "rollback_failed"
    assert retained["recovery_attempts"] == 0
    assert lane.receipt["status"] == "interrupted_transaction_recovery_failed"
    assert lane.receipt["recovery"]["status"] == "fail"
    assert lane.receipt["recovery"]["reason"] == "docker_compose_unavailable"
    assert lane.compose_bin == ("docker", "compose")
    assert len(reconstructed_ingress_lanes) == 1
    assert reconstructed_ingress_lanes[0].compose_bin == ()
    lane._prevalidate_recovery_context.assert_not_called()
    lane._perform_joint_rollback.assert_not_called()


def _install_success_path(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
) -> tuple[dict[str, object], list[str]]:
    context = _recovery_context(lane, tmp_path)
    lane.receipt["candidate_promotion_evidence"] = dict(
        context["candidate_promotion"]  # type: ignore[arg-type]
    )
    ingress_lane = context["ingress"]["lane"]
    assert isinstance(ingress_lane, ingress.PublicIngressReconciliationLane)
    actions: list[str] = []

    lane.preflight = Mock(return_value=context)  # type: ignore[method-assign]
    lane._require_deployment_input_seal = Mock()  # type: ignore[method-assign]
    lane._require_spatial_browser_binding = Mock()  # type: ignore[method-assign]
    lane._revalidate_ingress_input_seals = Mock()  # type: ignore[method-assign]
    lane.bind_source_snapshot_sha256 = "5" * 64
    lane._revalidate_bind_source_access = Mock()  # type: ignore[method-assign]

    lane._ensure_redis = Mock(side_effect=lambda: actions.append("ensure_redis"))
    lane._protect_previous_image = Mock(  # type: ignore[method-assign]
        side_effect=lambda _previous: (
            actions.append("protect_api")
            or joint._safe_rollback_tag(lane.deployment_id)
        )
    )
    lane._recreate_api = Mock(side_effect=lambda: actions.append("recreate_api"))
    lane._capture_public_network = Mock(  # type: ignore[method-assign]
        return_value={"present": False}
    )
    lane._validate_ingress_address_reservations = Mock()  # type: ignore[method-assign]
    lane._wait_container = Mock(return_value={"running": "true"})
    lane._verify_forward_api = Mock(return_value={"source_revision": SOURCE_REVISION})
    lane._local_origin = Mock(return_value="http://127.0.0.1:8090")
    lane._wait_http = Mock(return_value={"status_code": 200})
    lane._verify_local_https_redirects = Mock(
        return_value={
            "status": "pass",
            "trusted_proxy_headers_sent": False,
            "route_count": 6,
        }
    )
    lane._verify_non_memorial_controls = Mock()
    lane._verify_candidate_origin = Mock(
        side_effect=lambda **kwargs: {
            "origin": kwargs["label"],
            "status": "pass",
        }
    )
    ingress_lane._validate_api_runtime_posture = Mock()  # type: ignore[method-assign]
    lane._recreate_cloudflared = Mock(  # type: ignore[method-assign]
        side_effect=lambda _ingress: actions.append("recreate_cloudflared")
    )
    lane._verify_forward_cloudflared = Mock(return_value={})
    lane._verify_deployed_surface = Mock()
    ingress_lane._verify_public_origin = Mock(  # type: ignore[method-assign]
        return_value={f"probe_{index}": {"status": 200} for index in range(12)}
    )
    lane._materialize_and_verify_release_evidence = Mock(return_value={})
    return context, actions


def test_final_api_revalidation_failure_before_compose_requires_no_rollback(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, actions = _install_success_path(lane, tmp_path)
    phases: list[str] = []
    real_set_recovery_phase = lane._set_recovery_phase

    def track_phase(
        journal_payload: dict[str, object],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        real_set_recovery_phase(
            journal_payload,
            phase,
            api_mutation_possible=api_mutation_possible,
            ingress_mutation_possible=ingress_mutation_possible,
        )
        phases.append(phase)

    lane._set_recovery_phase = Mock(  # type: ignore[method-assign]
        side_effect=track_phase
    )

    def fail_final_api_seal(_seals: object) -> None:
        if phases and phases[-1] == "api_mutation_possible":
            raise api_deploy.DeployError("final_api_seal_changed")

    lane._revalidate_ingress_input_seals = Mock(  # type: ignore[method-assign]
        side_effect=fail_final_api_seal
    )
    lane._perform_joint_rollback = Mock()  # type: ignore[method-assign]

    with pytest.raises(api_deploy.DeployError, match="final_api_seal_changed"):
        lane.deploy()

    assert phases == ["api_mutation_possible", "prepared"]
    assert "recreate_api" not in actions
    assert "recreate_cloudflared" not in actions
    lane._perform_joint_rollback.assert_not_called()
    assert lane.receipt["failure"]["api_mutation_started"] is False
    assert lane.receipt["failure"]["ingress_mutation_started"] is False
    assert lane.receipt["rollback"] == {
        "status": "not_required",
        "reason": "api_and_ingress_unchanged",
        "protected_api_image_tag": joint._safe_rollback_tag(lane.deployment_id),
    }
    assert not lane.recovery_journal_path.exists()


def test_failed_api_journal_downgrade_uses_conservative_rollback(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, actions = _install_success_path(lane, tmp_path)
    phases: list[str] = []
    real_set_recovery_phase = lane._set_recovery_phase

    def track_or_fail_phase(
        journal_payload: dict[str, object],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        if phase == "prepared" and phases == ["api_mutation_possible"]:
            raise api_deploy.DeployError("journal_downgrade_failed")
        real_set_recovery_phase(
            journal_payload,
            phase,
            api_mutation_possible=api_mutation_possible,
            ingress_mutation_possible=ingress_mutation_possible,
        )
        phases.append(phase)

    lane._set_recovery_phase = Mock(  # type: ignore[method-assign]
        side_effect=track_or_fail_phase
    )

    def fail_final_api_seal(_seals: object) -> None:
        if phases and phases[-1] == "api_mutation_possible":
            raise api_deploy.DeployError("final_api_seal_changed")

    lane._revalidate_ingress_input_seals = Mock(  # type: ignore[method-assign]
        side_effect=fail_final_api_seal
    )
    lane._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass"}
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_failed_rolled_back:final_api_seal_changed",
    ):
        lane.deploy()

    assert "recreate_api" not in actions
    assert "recreate_cloudflared" not in actions
    lane._perform_joint_rollback.assert_called_once()
    assert lane._perform_joint_rollback.call_args.kwargs["api_mutation_started"] is True
    assert (
        lane._perform_joint_rollback.call_args.kwargs["ingress_mutation_started"]
        is False
    )
    assert not lane.recovery_journal_path.exists()


def test_final_ingress_revalidation_failure_rolls_back_api_only(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, actions = _install_success_path(lane, tmp_path)
    phases: list[str] = []
    real_set_recovery_phase = lane._set_recovery_phase

    def track_phase(
        journal_payload: dict[str, object],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        real_set_recovery_phase(
            journal_payload,
            phase,
            api_mutation_possible=api_mutation_possible,
            ingress_mutation_possible=ingress_mutation_possible,
        )
        phases.append(phase)

    lane._set_recovery_phase = Mock(  # type: ignore[method-assign]
        side_effect=track_phase
    )

    def fail_final_ingress_seal(_seals: object) -> None:
        if phases and phases[-1] == "ingress_mutation_possible":
            raise api_deploy.DeployError("final_ingress_seal_changed")

    lane._revalidate_ingress_input_seals = Mock(  # type: ignore[method-assign]
        side_effect=fail_final_ingress_seal
    )
    lane._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass"}
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_failed_rolled_back:final_ingress_seal_changed",
    ):
        lane.deploy()

    assert "recreate_api" in actions
    assert "recreate_cloudflared" not in actions
    assert phases[:3] == [
        "api_mutation_possible",
        "ingress_mutation_possible",
        "api_mutation_possible",
    ]
    lane._perform_joint_rollback.assert_called_once()
    assert lane._perform_joint_rollback.call_args.kwargs["api_mutation_started"] is True
    assert (
        lane._perform_joint_rollback.call_args.kwargs["ingress_mutation_started"]
        is False
    )
    assert not lane.recovery_journal_path.exists()


@pytest.mark.parametrize("authority", ["source", "spatial"])
def test_final_api_authority_drift_before_compose_requires_no_rollback(
    tmp_path: Path,
    authority: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, actions = _install_success_path(lane, tmp_path)
    phases: list[str] = []
    real_set_recovery_phase = lane._set_recovery_phase

    def track_phase(
        journal_payload: dict[str, object],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        real_set_recovery_phase(
            journal_payload,
            phase,
            api_mutation_possible=api_mutation_possible,
            ingress_mutation_possible=ingress_mutation_possible,
        )
        phases.append(phase)

    lane._set_recovery_phase = Mock(  # type: ignore[method-assign]
        side_effect=track_phase
    )

    def fail_final_authority(*_args: object, **_kwargs: object) -> None:
        if phases and phases[-1] == "api_mutation_possible":
            raise api_deploy.DeployError(f"final_{authority}_authority_changed")

    if authority == "source":
        lane._revalidate_bind_source_access = Mock(  # type: ignore[method-assign]
            side_effect=fail_final_authority
        )
    else:
        lane._require_spatial_browser_binding = Mock(  # type: ignore[method-assign]
            side_effect=fail_final_authority
        )
    lane._perform_joint_rollback = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError,
        match=f"final_{authority}_authority_changed",
    ):
        lane.deploy()

    assert phases == ["api_mutation_possible", "prepared"]
    assert "recreate_api" not in actions
    assert "recreate_cloudflared" not in actions
    lane._perform_joint_rollback.assert_not_called()
    assert not lane.recovery_journal_path.exists()


def test_final_ingress_spatial_drift_rolls_back_api_only(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, actions = _install_success_path(lane, tmp_path)
    phases: list[str] = []
    real_set_recovery_phase = lane._set_recovery_phase

    def track_phase(
        journal_payload: dict[str, object],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        real_set_recovery_phase(
            journal_payload,
            phase,
            api_mutation_possible=api_mutation_possible,
            ingress_mutation_possible=ingress_mutation_possible,
        )
        phases.append(phase)

    lane._set_recovery_phase = Mock(  # type: ignore[method-assign]
        side_effect=track_phase
    )

    def fail_final_spatial(*_args: object, **_kwargs: object) -> None:
        if phases and phases[-1] == "ingress_mutation_possible":
            raise api_deploy.DeployError("final_ingress_spatial_changed")

    lane._require_spatial_browser_binding = Mock(  # type: ignore[method-assign]
        side_effect=fail_final_spatial
    )
    lane._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass"}
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_failed_rolled_back:final_ingress_spatial_changed",
    ):
        lane.deploy()

    assert "recreate_api" in actions
    assert "recreate_cloudflared" not in actions
    lane._perform_joint_rollback.assert_called_once()
    assert lane._perform_joint_rollback.call_args.kwargs["api_mutation_started"] is True
    assert (
        lane._perform_joint_rollback.call_args.kwargs["ingress_mutation_started"]
        is False
    )
    assert not lane.recovery_journal_path.exists()


def _write_json(path: Path, payload: object, *, mode: int) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(mode)


def test_preflight_only_never_enters_a_bounded_mutation_action(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    context = _context(lane, tmp_path)
    lane.preflight = Mock(return_value=context)  # type: ignore[method-assign]
    lane._bounded_mutation_action = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("bounded mutation action entered")
    )
    lane._ensure_redis = Mock()
    lane._recreate_api = Mock()
    lane._recreate_cloudflared = Mock()

    receipt = lane.deploy(preflight_only=True)

    assert receipt["status"] == "preflight_only_pass"
    assert runner.commands == []
    lane._bounded_mutation_action.assert_not_called()
    lane._ensure_redis.assert_not_called()
    lane._recreate_api.assert_not_called()
    lane._recreate_cloudflared.assert_not_called()


def test_happy_path_orders_api_local_proof_before_ingress_and_public_proof(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    context_value, actions = _install_success_path(lane, tmp_path)

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert receipt["contract_name"] == joint.JOINT_COORDINATION_CONTRACT_NAME
    assert (
        receipt["coordination_contract_name"] == joint.JOINT_COORDINATION_CONTRACT_NAME
    )
    assert actions == [
        "ensure_redis",
        "protect_api",
        "recreate_api",
        "recreate_cloudflared",
    ]
    assert runner.commands == []
    assert lane._revalidate_bind_source_access.call_args_list == [
        call(boundary="before_recreate_api"),
        call(boundary="before_recreate_api"),
    ]
    lane._verify_non_memorial_controls.assert_called_once_with(
        dict(context_value["non_memorial_controls"]),
        public_origin=ORIGIN,
        expected_source_revision=SOURCE_REVISION,
    )
    lane._verify_local_https_redirects.assert_called_once_with(
        "http://127.0.0.1:8090",
        ORIGIN,
    )
    lane._verify_candidate_origin.assert_called_once_with(
        label="public",
        base_url=ORIGIN,
        public_origin=ORIGIN,
    )
    lane._verify_deployed_surface.assert_called_once()
    assert receipt["joint_atomicity"] == materializer.JOINT_ATOMICITY
    assert receipt["spatial_materializer_handoff"]["candidate_browser_receipt"] == {
        "environment": joint.SPATIAL_BROWSER_RECEIPT_ENV,
        "path": str(tmp_path / "browser.private.json"),
        "sha256": "5" * 64,
        "schema": joint.CANDIDATE_BROWSER_SCHEMA,
        "exact_binding": (
            "candidate_runtime.spatial_handoff_runtime.candidate_browser_gate"
        ),
    }
    assert receipt["preparation"] == {
        "status": "complete",
        "attempted_actions": [
            "ensure_redis",
            "protect_previous_image",
            "recreate_api",
            "recreate_cloudflared",
        ],
        "completed_actions": [
            "ensure_redis",
            "protect_previous_image",
            "recreate_api",
            "recreate_cloudflared",
        ],
        "pending_action": None,
        "active_action": None,
        "preparation_side_effects_possible": True,
        "api_mutation_started": True,
        "ingress_mutation_started": True,
        "api_runtime_state": "changed_verified",
        "ingress_runtime_state": "changed_verified",
    }


def test_bind_source_snapshot_drift_blocks_joint_api_and_ingress_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._revalidate_bind_source_access = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError(
            "memorial_bind_source_access_denied:bind_source_snapshot_changed"
        )
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="memorial_bind_source_access_denied:bind_source_snapshot_changed",
    ):
        lane.deploy()

    lane._recreate_api.assert_not_called()
    lane._recreate_cloudflared.assert_not_called()
    preparation = dict(lane.receipt["preparation"])
    assert preparation["api_mutation_started"] is False
    assert preparation["ingress_mutation_started"] is False


def test_redis_preparation_failure_records_possible_side_effects_truthfully(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context_value, _actions = _install_success_path(lane, tmp_path)
    durable_context = _recovery_context(lane, tmp_path)
    for key in ("previous", "non_memorial_controls", "deployment_input_seal"):
        context_value[key] = durable_context[key]
    context_value["ingress"].update(  # type: ignore[union-attr]
        {
            key: value
            for key, value in durable_context["ingress"].items()  # type: ignore[union-attr]
            if key != "lane"
        }
    )
    lane._ensure_redis = Mock(side_effect=api_deploy.DeployError("redis_start_failed"))

    with pytest.raises(api_deploy.DeployError, match="redis_start_failed"):
        lane.deploy()

    assert lane.receipt["status"] == "failed_during_preparation"
    preparation = dict(lane.receipt["preparation"])
    assert preparation["attempted_actions"] == ["ensure_redis"]
    assert preparation["completed_actions"] == []
    assert preparation["preparation_side_effects_possible"] is True
    assert preparation["api_mutation_started"] is False
    assert preparation["ingress_mutation_started"] is False
    assert preparation["api_runtime_state"] == "unchanged"
    assert lane.receipt["rollback"] == {
        "status": "not_required",
        "reason": "api_and_ingress_unchanged",
    }


@pytest.mark.parametrize("interrupt_at", ("api", "ingress"))
def test_sigterm_enters_joint_rollback(
    tmp_path: Path,
    interrupt_at: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._perform_joint_rollback = Mock(return_value={"status": "pass"})

    def interrupt() -> None:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)

    if interrupt_at == "api":
        lane._recreate_api = Mock(side_effect=interrupt)
    else:
        lane._recreate_cloudflared = Mock(side_effect=lambda _ingress: interrupt())

    with (
        joint._deployment_signal_handlers(),
        pytest.raises(
            api_deploy.DeployError,
            match="joint_deployment_failed_rolled_back:joint_deployment_signal",
        ),
    ):
        lane.deploy()

    rollback_call = lane._perform_joint_rollback.call_args.kwargs
    assert rollback_call["api_mutation_started"] is True
    assert rollback_call["ingress_mutation_started"] is (interrupt_at == "ingress")


def test_repeated_process_signal_is_suppressed_after_rollback_interrupt() -> None:
    with joint._deployment_signal_handlers():
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        with pytest.raises(joint.JointDeploySignalInterruption):
            handler(signal.SIGTERM, None)
        assert handler(signal.SIGTERM, None) is None


@pytest.mark.parametrize("signum", (signal.SIGINT, signal.SIGTERM))
def test_signal_between_rollback_components_is_deferred_and_all_restore(
    tmp_path: Path,
    signum: signal.Signals,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal, context = _rollback_authority_context(
        lane,
        tmp_path,
        api_mutation_started=True,
        ingress_mutation_started=True,
    )
    actions: list[str] = []
    lane._rollback_cloudflared = Mock(  # type: ignore[method-assign]
        side_effect=lambda _context: actions.append("ingress") or {"status": "pass"}
    )
    lane._rollback = Mock(  # type: ignore[method-assign]
        side_effect=lambda *_args: actions.append("api") or {"status": "pass"}
    )
    lane._restore_public_network = Mock(  # type: ignore[method-assign]
        side_effect=lambda _context: actions.append("network") or {"status": "pass"}
    )
    lane._capture_public_edge = Mock(  # type: ignore[method-assign]
        side_effect=lambda _origin: context["ingress"]["public_edge_baseline"]
    )
    real_checkpoint = lane._rollback_boundary_checkpoint

    def interrupt_between(boundary: str) -> None:
        if boundary == "after_ingress":
            handler = signal.getsignal(signum)
            assert callable(handler)
            handler(signum, None)
            handler(signum, None)
        real_checkpoint(boundary)

    lane._rollback_boundary_checkpoint = interrupt_between  # type: ignore[method-assign]
    with joint._deployment_signal_handlers():
        result = lane._perform_joint_rollback(
            context=context,
            api_mutation_started=True,
            ingress_mutation_started=True,
            rollback_tag=str(journal["rollback_tag"]),
        )

    assert result["status"] == "pass"
    assert actions == ["ingress", "api", "network"]
    assert result["deferred_signals"] == {signal.Signals(signum).name: 2}


@pytest.mark.parametrize("after_commit", ("error", "signal"))
def test_irrevocable_commit_never_rolls_back_after_pass_is_durable(
    tmp_path: Path,
    after_commit: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    rollback = Mock(side_effect=AssertionError("committed transaction rolled back"))
    lane._perform_joint_rollback = rollback  # type: ignore[method-assign]
    real_write = lane._write_receipt
    pass_writes = 0

    def injected_write() -> None:
        nonlocal pass_writes
        real_write()
        if lane.receipt.get("status") != "pass":
            return
        pass_writes += 1
        if after_commit == "error":
            raise api_deploy.DeployError("injected_after_commit")
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)

    lane._write_receipt = injected_write  # type: ignore[method-assign]
    with joint._deployment_signal_handlers():
        receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert receipt["joint_atomicity"]["transaction_status"] == "committed"
    assert pass_writes == 2
    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["recovery_journal_cleanup"]["status"] == "removed"
    rollback.assert_not_called()


def test_signal_during_postpublication_commit_probe_cannot_trigger_rollback(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    rollback = Mock(side_effect=AssertionError("committed transaction rolled back"))
    lane._perform_joint_rollback = rollback  # type: ignore[method-assign]
    real_write = lane._write_receipt
    real_read = lane._read_trusted_guard_file
    signal_injected = False

    def publish_then_raise() -> None:
        real_write()
        if lane.receipt.get("status") == "pass":
            raise api_deploy.DeployError("injected_after_commit")

    def signal_during_probe(*args: object, **kwargs: object) -> bytes:
        nonlocal signal_injected
        if kwargs.get("reason_prefix") == "joint_final_receipt":
            signal_injected = True
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)
        return real_read(*args, **kwargs)  # type: ignore[arg-type]

    lane._write_receipt = publish_then_raise  # type: ignore[method-assign]
    lane._read_trusted_guard_file = signal_during_probe  # type: ignore[method-assign]
    with joint._deployment_signal_handlers():
        receipt = lane.deploy()

    assert signal_injected is True
    assert receipt["status"] == "pass"
    rollback.assert_not_called()
    assert not lane.recovery_journal_path.exists()


def test_deferred_signal_after_first_commit_still_publishes_cleanup_removed(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed transaction rolled back")
    )
    real_write = lane._write_receipt
    injected = False

    def signal_after_first_commit() -> None:
        nonlocal injected
        real_write()
        cleanup = dict(lane.receipt.get("recovery_journal_cleanup") or {})
        if (
            not injected
            and lane.receipt.get("status") == "pass"
            and cleanup.get("status") == "pending_after_commit"
        ):
            injected = True
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)

    lane._write_receipt = signal_after_first_commit  # type: ignore[method-assign]
    with joint._deployment_signal_handlers():
        receipt = lane.deploy()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert injected is True
    assert receipt["status"] == "pass"
    assert receipt["postcommit_deferred_signals"] == {"SIGTERM": 1}
    assert persisted["status"] == "pass"
    assert persisted["recovery_journal_cleanup"] == _removed_cleanup(lane)
    assert persisted["postcommit_deferred_signals"] == {"SIGTERM": 1}
    assert not lane.recovery_journal_path.exists()
    lane._perform_joint_rollback.assert_not_called()


@pytest.mark.parametrize(
    ("crash_at", "expected_phase", "ingress_possible"),
    (
        ("api", "api_mutation_possible", False),
        ("ingress", "ingress_mutation_possible", True),
    ),
)
def test_uncatchable_crash_phase_is_durable_and_next_run_recovers(
    tmp_path: Path,
    crash_at: str,
    expected_phase: str,
    ingress_possible: bool,
) -> None:
    lane, _runner = _lane(tmp_path)
    context_value, _actions = _install_success_path(lane, tmp_path)
    durable_context = _recovery_context(lane, tmp_path)
    for key in ("previous", "non_memorial_controls", "deployment_input_seal"):
        context_value[key] = durable_context[key]
    context_ingress = context_value["ingress"]
    durable_ingress = durable_context["ingress"]
    assert isinstance(context_ingress, dict)
    assert isinstance(durable_ingress, dict)
    context_ingress.update(
        {key: value for key, value in durable_ingress.items() if key != "lane"}
    )
    if crash_at == "api":
        lane._recreate_api = Mock(side_effect=SystemExit("simulated-crash"))
    else:
        lane._recreate_cloudflared = Mock(  # type: ignore[method-assign]
            side_effect=SystemExit("simulated-crash")
        )

    with pytest.raises(SystemExit, match="simulated-crash"):
        lane.deploy()

    journal_payload, _raw = lane._read_recovery_journal() or ({}, b"")
    assert journal_payload["phase"] == expected_phase
    assert journal_payload["api_mutation_possible"] is True
    assert journal_payload["ingress_mutation_possible"] is ingress_possible

    restarted = _restart_lane(lane, tmp_path)
    detect_compose = _install_successful_compose_detection(restarted)
    restarted._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    restarted._perform_joint_rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    restarted._recover_interrupted_transaction(preflight_only=False)

    detect_compose.assert_called_once_with()
    rollback_call = restarted._perform_joint_rollback.call_args.kwargs
    assert rollback_call["api_mutation_started"] is True
    assert rollback_call["ingress_mutation_started"] is ingress_possible
    assert restarted.receipt["recovery"]["status"] == "pass"
    assert not restarted.recovery_journal_path.exists()


@pytest.mark.parametrize("tamper", ("missing_context", "extra_environment_hash"))
def test_tampered_or_incomplete_recovery_journal_fails_before_runtime_mutation(
    tmp_path: Path,
    tamper: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal_payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    if tamper == "missing_context":
        journal_payload.pop("rollback_context")
    else:
        journal_payload["rollback_context"]["ingress"][  # type: ignore[index]
            "release_environment_sha256"
        ] = "f" * 64
    lane._write_recovery_journal(journal_payload)
    restarted = _restart_lane(lane, tmp_path)
    restarted._prevalidate_recovery_context = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("tampered journal reached runtime validation")
    )
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("tampered journal reached rollback")
    )

    expected = (
        "joint_recovery_journal_schema_invalid"
        if tamper == "missing_context"
        else "joint_recovery_ingress_baseline_invalid"
    )
    with pytest.raises(api_deploy.DeployError, match=expected):
        restarted._recover_interrupted_transaction(preflight_only=False)

    restarted._prevalidate_recovery_context.assert_not_called()
    restarted._perform_joint_rollback.assert_not_called()
    assert restarted.recovery_journal_path.exists()


def test_v1_recovery_journal_is_rejected_before_runtime_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal_payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    journal_payload.update(
        {
            "contract_name": "ea.memorial_joint_recovery_journal.v1",
            "version": 1,
        }
    )
    lane._write_recovery_journal(journal_payload)
    restarted = _restart_lane(lane, tmp_path)
    restarted._build_ingress_lane = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("v1 journal reached ingress construction")
    )
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("v1 journal reached rollback")
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_recovery_journal_schema_invalid",
    ):
        restarted._recover_interrupted_transaction(preflight_only=False)

    restarted._build_ingress_lane.assert_not_called()
    restarted._perform_joint_rollback.assert_not_called()
    assert restarted.runner.commands == []
    assert restarted.recovery_journal_path.exists()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("metadata", "joint_recovery_ingress_overlay_invalid"),
        ("hash", "joint_ingress_input_changed"),
        ("mode", "reconciliation_input_untrusted"),
    ),
)
def test_recovery_overlay_tamper_is_rejected_before_compose(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal_payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    ingress_payload = journal_payload["rollback_context"]["ingress"]
    overlay = ingress_payload["rollback_overlay"]
    overlay_path = Path(str(overlay["path"]))
    restarted = _restart_lane(lane, tmp_path)

    if mutation == "metadata":
        overlay["contains_secret_material"] = True
        restarted._build_ingress_lane = Mock(  # type: ignore[method-assign]
            side_effect=AssertionError("altered metadata reached ingress construction")
        )
        with pytest.raises(api_deploy.DeployError, match=reason):
            restarted._validate_recovery_journal(journal_payload)
        restarted._build_ingress_lane.assert_not_called()
        assert restarted.runner.commands == []
        return

    _journal, context = restarted._validate_recovery_journal(journal_payload)
    recovered_ingress = context["ingress"]["lane"]
    recovered_ingress._render_compose = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("altered overlay reached Compose")
    )
    restarted._require_docker_daemon_identity = Mock()  # type: ignore[method-assign]
    restarted._require_deployment_input_seal = Mock()  # type: ignore[method-assign]
    if mutation == "hash":
        overlay_path.write_bytes(overlay_path.read_bytes() + b"# tampered\n")
    else:
        overlay_path.chmod(0o640)

    with pytest.raises(api_deploy.DeployError, match=reason):
        restarted._prevalidate_recovery_context(
            context,
            str(journal_payload["rollback_tag"]),
        )

    recovered_ingress._render_compose.assert_not_called()
    assert restarted.runner.commands == []


def test_preflight_only_never_mutates_an_interrupted_transaction(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    restarted = _restart_lane(lane, tmp_path)
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("preflight-only attempted recovery mutation")
    )

    with pytest.raises(api_deploy.DeployError, match="joint_recovery_required"):
        restarted._recover_interrupted_transaction(preflight_only=True)

    restarted._perform_joint_rollback.assert_not_called()
    assert restarted.recovery_journal_path.exists()


def test_crash_after_commit_is_recognized_without_rollback(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(lane, tmp_path, phase="commit_pending")
    lane.receipt.update(
        {
            "status": "pass",
            "source_revision": SOURCE_REVISION,
            "public_origin": ORIGIN,
            "candidate_promotion_evidence": dict(
                _context(lane, tmp_path)["candidate_promotion"]  # type: ignore[arg-type]
            ),
            "joint_public_edge": {
                "status": "pass",
                "request_count": 12,
                "source_revision": SOURCE_REVISION,
            },
            "joint_atomicity": {
                "transaction_status": "committed",
                "rollback_executed": False,
                "rollback_execution_status": "not_required",
            },
            "preparation": {
                "status": "complete",
                "api_runtime_state": "changed_verified",
                "ingress_runtime_state": "changed_verified",
            },
            "recovery_journal_cleanup": {
                "status": "pending_after_commit",
                "path": str(lane.recovery_journal_path),
                "contains_secret_material": True,
            },
        }
    )
    lane._write_receipt()
    restarted = _restart_lane(lane, tmp_path)
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed journal attempted rollback")
    )

    restarted._recover_interrupted_transaction(preflight_only=False)

    restarted._perform_joint_rollback.assert_not_called()
    assert restarted.receipt["recovery"]["status"] == (
        "committed_transaction_confirmed"
    )
    assert not restarted.recovery_journal_path.exists()
    finalized = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert finalized["recovery_journal_cleanup"]["status"] == "removed"


def test_full_deploy_retains_invalid_preexisting_journal_byte_exact(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    payload.pop("rollback_context")
    lane._write_recovery_journal(payload)
    expected = lane.recovery_journal_path.read_bytes()

    first = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-invalid-restart-002",
        receipt_dir=tmp_path / "invalid-receipts-2",
    )
    first.preflight = Mock(side_effect=AssertionError("invalid journal bypassed"))  # type: ignore[method-assign]
    with pytest.raises(api_deploy.DeployError, match="journal_schema_invalid"):
        first.deploy()

    assert first.receipt["status"] == "recovery_journal_invalid"
    assert lane.recovery_journal_path.read_bytes() == expected

    second = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-invalid-restart-003",
        receipt_dir=tmp_path / "invalid-receipts-3",
    )
    with pytest.raises(api_deploy.DeployError, match="journal_schema_invalid"):
        second.deploy()
    assert lane.recovery_journal_path.read_bytes() == expected


def test_full_preflight_only_retains_journal_then_normal_run_recovers(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(lane, tmp_path, phase="api_mutation_possible")
    expected = lane.recovery_journal_path.read_bytes()

    preflight = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-preflight-restart-002",
        receipt_dir=tmp_path / "preflight-receipts-2",
    )
    preflight._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("preflight-only mutated recovery")
    )
    with pytest.raises(api_deploy.DeployError, match="joint_recovery_required"):
        preflight.deploy(preflight_only=True)

    assert preflight.receipt["status"] == "recovery_required"
    assert lane.recovery_journal_path.read_bytes() == expected

    recovery = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-preflight-restart-003",
        receipt_dir=tmp_path / "preflight-receipts-3",
    )
    detect_compose = _install_successful_compose_detection(recovery)
    recovery._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    recovery._perform_joint_rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    recovery.preflight = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("stop_after_recovery")
    )
    with pytest.raises(api_deploy.DeployError, match="stop_after_recovery"):
        recovery.deploy()

    detect_compose.assert_called_once_with()
    recovery._perform_joint_rollback.assert_called_once()
    assert not lane.recovery_journal_path.exists()


def test_full_failed_recovery_retains_final_journal_then_next_run_recovers(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(lane, tmp_path, phase="api_mutation_possible")
    failed = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-failed-recovery-002",
        receipt_dir=tmp_path / "failed-recovery-receipts-2",
    )
    failed_detect_compose = _install_successful_compose_detection(failed)
    failed._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    failed._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("injected_recovery_failure")
    )
    real_write = failed._write_receipt
    retained_after_failure: list[bytes] = []

    def capture_failure_receipt() -> None:
        real_write()
        if failed.receipt.get("status") == "interrupted_transaction_recovery_failed":
            retained_after_failure.append(lane.recovery_journal_path.read_bytes())

    failed._write_receipt = capture_failure_receipt  # type: ignore[method-assign]
    with pytest.raises(
        api_deploy.DeployError,
        match="joint_interrupted_transaction_recovery_failed",
    ):
        failed.deploy()

    assert failed.receipt["status"] == "interrupted_transaction_recovery_failed"
    failed_detect_compose.assert_called_once_with()
    assert retained_after_failure
    assert lane.recovery_journal_path.read_bytes() == retained_after_failure[-1]

    recovery = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-failed-recovery-003",
        receipt_dir=tmp_path / "failed-recovery-receipts-3",
    )
    recovery_detect_compose = _install_successful_compose_detection(recovery)
    recovery._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    recovery._perform_joint_rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    recovery.preflight = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("stop_after_recovery")
    )
    with pytest.raises(api_deploy.DeployError, match="stop_after_recovery"):
        recovery.deploy()
    recovery_detect_compose.assert_called_once_with()
    assert not lane.recovery_journal_path.exists()


def test_cross_release_restart_uses_recorded_root_receipts_and_ignores_unrelated_env(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _write_recovery_journal(lane, tmp_path, phase="api_mutation_possible")
    old_root = lane.root
    old_receipts = lane.receipt_dir
    old_ingress_receipts = lane.ingress_receipt_dir

    new_root_parent = tmp_path / "new-release-parent"
    new_root_parent.mkdir()
    new_root = _root(new_root_parent)
    restarted = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-cross-release-002",
        root=new_root,
        receipt_dir=tmp_path / "new-release-receipts",
        ingress_receipt_dir=tmp_path / "new-release-ingress-receipts",
        extra_env={"UNRELATED_FORWARD_ONLY": "changed"},
    )
    payload, _raw = restarted._read_recovery_journal() or ({}, b"")
    _journal, context = restarted._validate_recovery_journal(payload)
    recovered_ingress = context["ingress"]["lane"]

    assert context["recorded_root"] == old_root
    assert context["recorded_receipt_dir"] == old_receipts
    assert context["recorded_ingress_receipt_dir"] == old_ingress_receipts
    assert recovered_ingress.root == old_root
    assert recovered_ingress.receipt_dir == old_ingress_receipts
    assert "UNRELATED_FORWARD_ONLY" not in recovered_ingress.release_env


def test_recovery_prevalidation_checks_only_api_rollback_seals(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    _journal, context = lane._validate_recovery_journal(payload)
    ingress_context = context["ingress"]
    ingress_lane = ingress_context["lane"]
    projection = ingress_context["rollback_render_projection"]
    rendered = {
        "services": {ingress.CLOUDFLARED_SERVICE: projection["service"]},
        "networks": projection["networks"],
    }
    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        return_value=(rendered, ingress_context["rollback_input_seals"])
    )
    lane._require_docker_daemon_identity = Mock()  # type: ignore[method-assign]
    lane._revalidate_ingress_input_seals = Mock()  # type: ignore[method-assign]
    lane._rollback_environment = Mock(return_value={})  # type: ignore[method-assign]
    lane._verify_rollback_renderability = Mock(return_value={})  # type: ignore[method-assign]
    lane._inspect_image = Mock(  # type: ignore[method-assign]
        return_value={"image_id": context["previous"]["image_id"]}
    )
    observed_scopes: list[str | None] = []

    def require_seal(_seal: object, *, scope: str | None = None) -> None:
        observed_scopes.append(scope)
        if scope != "rollback":
            raise AssertionError("forward inputs were consulted during recovery")

    lane._require_deployment_input_seal = require_seal  # type: ignore[method-assign]

    lane._prevalidate_recovery_context(
        context,
        str(payload["rollback_tag"]),
    )

    assert observed_scopes == ["rollback", "rollback"]


def test_recovery_rejects_daemon_or_relevant_render_drift_before_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    _journal, context = lane._validate_recovery_journal(payload)
    ingress_lane = context["ingress"]["lane"]
    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("wrong daemon reached Compose validation")
    )
    lane._capture_docker_daemon_identity = Mock(  # type: ignore[method-assign]
        return_value={
            "identity_source": "docker_info_engine_id",
            "daemon_id_sha256": "f" * 64,
        }
    )
    with pytest.raises(
        api_deploy.DeployError,
        match="joint_recovery_docker_daemon_changed",
    ):
        lane._prevalidate_recovery_context(context, str(payload["rollback_tag"]))
    ingress_lane._render_compose.assert_not_called()

    lane._capture_docker_daemon_identity = Mock(  # type: ignore[method-assign]
        return_value=context["docker_daemon_identity"]
    )
    lane._require_deployment_input_seal = Mock()  # type: ignore[method-assign]
    lane._revalidate_ingress_input_seals = Mock()  # type: ignore[method-assign]
    changed_projection = json.loads(
        json.dumps(context["ingress"]["rollback_render_projection"])
    )
    changed_projection["service"]["environment"]["TUNNEL_TOKEN"] = "changed"
    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        return_value=(
            {
                "services": {
                    ingress.CLOUDFLARED_SERVICE: changed_projection["service"]
                },
                "networks": changed_projection["networks"],
            },
            context["ingress"]["rollback_input_seals"],
        )
    )
    lane._inspect_image = Mock()  # type: ignore[method-assign]
    with pytest.raises(
        api_deploy.DeployError,
        match="joint_recovery_ingress_render_changed",
    ):
        lane._prevalidate_recovery_context(context, str(payload["rollback_tag"]))
    lane._inspect_image.assert_not_called()


def test_committed_cleanup_failure_is_persisted_and_restart_only_retries_cleanup(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context_value, _actions = _install_success_path(lane, tmp_path)
    durable_context = _recovery_context(lane, tmp_path)
    for key in (
        "previous",
        "non_memorial_controls",
        "deployment_input_seal",
        "api_local_origin",
        "docker_daemon_identity",
    ):
        context_value[key] = durable_context[key]
    context_value["ingress"].update(  # type: ignore[union-attr]
        {
            key: value
            for key, value in durable_context["ingress"].items()  # type: ignore[union-attr]
            if key != "lane"
        }
    )
    lane._remove_owned_recovery_journal = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("injected_cleanup_failure")
    )

    with pytest.raises(
        joint.JointCommittedCleanupIncident,
        match="joint_committed_recovery_journal_cleanup_failed",
    ):
        lane.deploy()

    assert lane.receipt["status"] == "committed_cleanup_incident"
    assert lane.receipt["recovery_journal_cleanup"]["status"] == (
        "retained_cleanup_failed"
    )
    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["recovery_journal_cleanup"]["status"] == (
        "retained_cleanup_failed"
    )
    assert persisted["status"] == "committed_cleanup_incident"
    assert lane.recovery_journal_path.exists()

    restarted = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-cleanup-restart-002",
        receipt_dir=tmp_path / "cleanup-restart-receipts",
    )
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed cleanup retry rolled back")
    )
    restarted._recover_interrupted_transaction(preflight_only=False)
    restarted._perform_joint_rollback.assert_not_called()
    assert not lane.recovery_journal_path.exists()
    finalized = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert finalized["status"] == "pass"
    assert finalized["recovery_journal_cleanup"]["status"] == "removed"
    assert "operator_action_required" not in finalized


def test_committed_cleanup_and_metadata_write_failure_raises_then_restart_cleans_only(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context_value, _actions = _install_success_path(lane, tmp_path)
    durable_context = _recovery_context(lane, tmp_path)
    for key in (
        "previous",
        "non_memorial_controls",
        "deployment_input_seal",
        "api_local_origin",
        "docker_daemon_identity",
    ):
        context_value[key] = durable_context[key]
    context_value["ingress"].update(  # type: ignore[union-attr]
        {
            key: value
            for key, value in durable_context["ingress"].items()  # type: ignore[union-attr]
            if key != "lane"
        }
    )
    lane._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed transaction rolled back")
    )
    lane._remove_owned_recovery_journal = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("injected_cleanup_failure")
    )
    real_write = lane._write_receipt

    def fail_cleanup_metadata_write() -> None:
        if lane.receipt.get("status") == "committed_cleanup_incident":
            raise api_deploy.DeployError("injected_cleanup_metadata_write_failure")
        real_write()

    lane._write_receipt = fail_cleanup_metadata_write  # type: ignore[method-assign]

    with pytest.raises(
        joint.JointCommittedCleanupIncident,
        match="joint_committed_recovery_journal_cleanup_failed",
    ):
        lane.deploy()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
    assert persisted["recovery_journal_cleanup"]["status"] == ("pending_after_commit")
    assert lane.receipt["status"] == "committed_cleanup_incident"
    assert lane.receipt["recovery_journal_cleanup"]["status"] == (
        "retained_cleanup_failed"
    )
    assert lane.recovery_journal_path.exists()
    lane._perform_joint_rollback.assert_not_called()

    restarted = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-combined-cleanup-restart-002",
        receipt_dir=tmp_path / "combined-cleanup-restart-receipts",
    )
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed cleanup retry rolled back")
    )
    restarted._recover_interrupted_transaction(preflight_only=False)

    restarted._perform_joint_rollback.assert_not_called()
    assert restarted.receipt["recovery"]["status"] == (
        "committed_transaction_confirmed"
    )
    assert not lane.recovery_journal_path.exists()
    finalized = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert finalized["status"] == "pass"
    assert finalized["recovery_journal_cleanup"]["status"] == "removed"
    assert "operator_action_required" not in finalized


def test_cleanup_removed_metadata_write_failure_is_nonzero_and_finalizable(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed transaction rolled back")
    )
    real_write = lane._write_receipt

    def fail_before_removed_publication() -> None:
        cleanup = dict(lane.receipt.get("recovery_journal_cleanup") or {})
        if cleanup.get("status") == "removed":
            raise api_deploy.DeployError("injected_removed_metadata_write_failure")
        real_write()

    lane._write_receipt = fail_before_removed_publication  # type: ignore[method-assign]
    with pytest.raises(
        joint.JointCommittedCleanupIncident,
        match="joint_committed_cleanup_evidence_publication_failed",
    ):
        lane.deploy()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
    assert persisted["recovery_journal_cleanup"]["status"] == ("pending_after_commit")
    assert lane.receipt["status"] == "committed_cleanup_incident"
    assert lane.receipt["recovery_journal_cleanup"]["status"] == "removed"
    assert not lane.recovery_journal_path.exists()
    lane._perform_joint_rollback.assert_not_called()

    lane._write_receipt = real_write  # type: ignore[method-assign]
    finalized = lane.finalize_committed_cleanup()

    assert finalized["status"] == "pass"
    assert finalized["recovery_journal_cleanup"] == _removed_cleanup(lane)
    assert json.loads(lane.receipt_path.read_text(encoding="utf-8")) == finalized


def test_cleanup_finalizer_rejects_present_recovery_journal(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    receipt = lane.deploy()
    receipt["recovery_journal_cleanup"] = _pending_cleanup(lane)
    lane._write_receipt()
    _write_recovery_journal(lane, tmp_path, phase="commit_pending")

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_committed_cleanup_journal_still_present",
    ):
        lane.finalize_committed_cleanup()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["recovery_journal_cleanup"]["status"] == ("pending_after_commit")
    assert lane.recovery_journal_path.exists()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("source_revision", "not-a-revision", "source_revision_invalid"),
        ("source_revision", "A" * 40, "source_revision_invalid"),
        ("source_revision", "a" * 39, "source_revision_invalid"),
        ("public_origin", "file:///tmp/not-public", "public_origin_invalid"),
        ("public_origin", "https://evil.example", "public_origin_invalid"),
        (
            "public_origin",
            "https://user@myexternalbrain.com",
            "public_origin_invalid",
        ),
        (
            "public_origin",
            "https://myexternalbrain.com/path",
            "public_origin_invalid",
        ),
        (
            "public_origin",
            "https://myexternalbrain.com?query=1",
            "public_origin_invalid",
        ),
        (
            "public_origin",
            "https://MYEXTERNALBRAIN.COM",
            "public_origin_invalid",
        ),
        (
            "public_origin",
            "https://myexternalbrain.com:443",
            "public_origin_invalid",
        ),
    ),
)
def test_cleanup_finalizer_rejects_self_asserted_revision_or_origin(
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
) -> None:
    lane, runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    receipt = lane.deploy()
    receipt["recovery_journal_cleanup"] = _pending_cleanup(lane)
    receipt[field] = value
    lane._write_receipt()

    with pytest.raises(api_deploy.DeployError, match=reason):
        lane.finalize_committed_cleanup()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["recovery_journal_cleanup"]["status"] == ("pending_after_commit")
    assert runner.commands == []


@pytest.mark.parametrize(
    "mutation",
    (
        "incident_pending",
        "incident_removed",
        "incident_retained",
        "cleanup_extra_key",
        "operator_false",
    ),
)
def test_external_cleanup_finalizer_requires_exact_pass_cleanup_shape(
    tmp_path: Path,
    mutation: str,
) -> None:
    lane, runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    receipt = lane.deploy()
    cleanup = _pending_cleanup(lane)
    if mutation.startswith("incident_"):
        receipt["status"] = "committed_cleanup_incident"
        receipt["operator_action_required"] = True
        cleanup["status"] = mutation.removeprefix("incident_")
        if cleanup["status"] == "retained":
            cleanup["status"] = "retained_cleanup_failed"
            cleanup["reason"] = "retained"
    elif mutation == "cleanup_extra_key":
        cleanup["unexpected"] = True
    elif mutation == "operator_false":
        receipt["operator_action_required"] = False
    receipt["recovery_journal_cleanup"] = cleanup
    lane._write_receipt()

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_committed_cleanup_receipt_invalid",
    ):
        lane.finalize_committed_cleanup()

    assert json.loads(lane.receipt_path.read_text(encoding="utf-8")) == receipt
    assert runner.commands == []


@pytest.mark.parametrize("mutation", ("missing", "wrong_mode", "symlink"))
def test_cleanup_finalizer_requires_existing_trusted_state_directory(
    tmp_path: Path,
    mutation: str,
) -> None:
    lane, runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    receipt = lane.deploy()
    receipt["recovery_journal_cleanup"] = _pending_cleanup(lane)
    lane._write_receipt()
    state_directory = lane.recovery_journal_path.parent
    if mutation == "missing":
        state_directory.rmdir()
    elif mutation == "wrong_mode":
        state_directory.chmod(0o755)
    else:
        moved = state_directory.with_name("moved-state-directory")
        state_directory.rename(moved)
        state_directory.symlink_to(moved, target_is_directory=True)

    with pytest.raises(api_deploy.DeployError):
        lane.finalize_committed_cleanup()

    if mutation == "wrong_mode":
        assert stat.S_IMODE(state_directory.stat().st_mode) == 0o755
    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["recovery_journal_cleanup"]["status"] == ("pending_after_commit")
    assert runner.commands == []


def test_cleanup_finalizer_rejects_state_directory_swap_between_absence_proofs(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    receipt = lane.deploy()
    receipt["recovery_journal_cleanup"] = _pending_cleanup(lane)
    lane._write_receipt()
    state_directory = lane.recovery_journal_path.parent
    real_write = lane._write_transaction_receipt_payload

    def write_then_swap(path: Path, payload: Mapping[str, object]) -> None:
        real_write(path, payload)
        moved = state_directory.with_name("swapped-state-directory")
        state_directory.rename(moved)
        state_directory.mkdir(mode=0o700)

    lane._write_transaction_receipt_payload = write_then_swap  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_committed_cleanup_state_directory_changed",
    ):
        lane.finalize_committed_cleanup()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["recovery_journal_cleanup"] == _pending_cleanup(lane)
    assert runner.commands == []


def test_cleanup_finalizer_rejects_journal_created_after_receipt_write(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    receipt = lane.deploy()
    receipt["recovery_journal_cleanup"] = _pending_cleanup(lane)
    lane._write_receipt()
    real_write = lane._write_transaction_receipt_payload

    def write_then_create_journal(
        path: Path,
        payload: Mapping[str, object],
    ) -> None:
        real_write(path, payload)
        cleanup = dict(payload.get("recovery_journal_cleanup") or {})
        if cleanup.get("status") == "removed":
            lane.recovery_journal_path.write_bytes(b"{}\n")
            lane.recovery_journal_path.chmod(0o600)

    lane._write_transaction_receipt_payload = write_then_create_journal  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_committed_cleanup_state_directory_changed",
    ):
        lane.finalize_committed_cleanup()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["recovery_journal_cleanup"] == _pending_cleanup(lane)
    assert lane.recovery_journal_path.exists()
    assert runner.commands == []


def test_recovery_normalizes_pending_before_unlink_and_external_finalizer_repairs(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context_value, _actions = _install_success_path(lane, tmp_path)
    durable_context = _recovery_context(lane, tmp_path)
    for key in (
        "previous",
        "non_memorial_controls",
        "deployment_input_seal",
        "api_local_origin",
        "docker_daemon_identity",
    ):
        context_value[key] = durable_context[key]
    context_value["ingress"].update(  # type: ignore[union-attr]
        {
            key: value
            for key, value in durable_context["ingress"].items()  # type: ignore[union-attr]
            if key != "lane"
        }
    )
    lane._remove_owned_recovery_journal = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("injected_initial_cleanup_failure")
    )
    with pytest.raises(joint.JointCommittedCleanupIncident):
        lane.deploy()
    assert lane.recovery_journal_path.exists()

    restarted = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-two-phase-restart-002",
        receipt_dir=tmp_path / "two-phase-restart-receipts",
    )
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed recovery rolled back")
    )
    real_write = restarted._write_transaction_receipt_payload

    def fail_removed_publication(
        path: Path,
        payload: Mapping[str, object],
    ) -> None:
        cleanup = dict(payload.get("recovery_journal_cleanup") or {})
        if cleanup.get("status") == "removed":
            raise api_deploy.DeployError("injected_final_publication_failure")
        real_write(path, payload)

    restarted._write_transaction_receipt_payload = fail_removed_publication  # type: ignore[method-assign]
    with pytest.raises(
        api_deploy.DeployError,
        match="injected_final_publication_failure",
    ):
        restarted._recover_interrupted_transaction(preflight_only=False)

    pending = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert pending["status"] == "pass"
    assert pending["recovery_journal_cleanup"]["status"] == ("pending_after_commit")
    assert "operator_action_required" not in pending
    assert not lane.recovery_journal_path.exists()
    restarted._perform_joint_rollback.assert_not_called()

    second = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-two-phase-restart-003",
        receipt_dir=tmp_path / "two-phase-restart-receipts-3",
    )
    second._recover_interrupted_transaction(preflight_only=False)
    assert "recovery" not in second.receipt
    assert json.loads(lane.receipt_path.read_text(encoding="utf-8")) == pending

    finalized = lane.finalize_committed_cleanup()
    assert finalized["status"] == "pass"
    assert finalized["recovery_journal_cleanup"]["status"] == "removed"


def test_recovery_binds_finalization_to_post_unlink_state_directory(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context_value, _actions = _install_success_path(lane, tmp_path)
    durable_context = _recovery_context(lane, tmp_path)
    for key in (
        "previous",
        "non_memorial_controls",
        "deployment_input_seal",
        "api_local_origin",
        "docker_daemon_identity",
    ):
        context_value[key] = durable_context[key]
    context_value["ingress"].update(  # type: ignore[union-attr]
        {
            key: value
            for key, value in durable_context["ingress"].items()  # type: ignore[union-attr]
            if key != "lane"
        }
    )
    lane._remove_owned_recovery_journal = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("injected_initial_cleanup_failure")
    )
    with pytest.raises(joint.JointCommittedCleanupIncident):
        lane.deploy()

    restarted = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-state-swap-restart-002",
        receipt_dir=tmp_path / "state-swap-restart-receipts",
    )
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("committed recovery rolled back")
    )
    real_remove = restarted._remove_owned_recovery_journal
    state_directory = restarted.recovery_journal_path.parent

    def remove_then_swap(
        journal_payload: Mapping[str, object],
        *,
        transaction_id: str | None = None,
    ) -> dict[str, object]:
        identity = real_remove(
            journal_payload,
            transaction_id=transaction_id,
        )
        moved = state_directory.with_name("recovery-post-unlink-original")
        state_directory.rename(moved)
        state_directory.mkdir(mode=0o700)
        return identity

    restarted._remove_owned_recovery_journal = remove_then_swap  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_committed_cleanup_state_directory_changed",
    ):
        restarted._recover_interrupted_transaction(preflight_only=False)

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
    assert persisted["recovery_journal_cleanup"] == _pending_cleanup(restarted)
    assert not restarted.recovery_journal_path.exists()
    restarted._perform_joint_rollback.assert_not_called()


def test_verified_rollback_cleanup_failure_is_persisted_with_journal_retained(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._verify_forward_api = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("forward_api_failed")
    )
    lane._perform_joint_rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    lane._remove_owned_recovery_journal = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("injected_cleanup_failure")
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_failed_rolled_back:forward_api_failed",
    ):
        lane.deploy()

    persisted = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "failed_rolled_back"
    assert persisted["recovery_journal_cleanup"]["status"] == (
        "retained_cleanup_failed"
    )
    assert lane.recovery_journal_path.exists()


def test_delegated_ingress_commands_share_one_joint_rollback_deadline(
    tmp_path: Path,
) -> None:
    clock = [0.0]

    class DeadlineRunner(api_deploy.SubprocessRunner):
        def __init__(self) -> None:
            self.timeouts: list[float | None] = []

        def run(
            self,
            args: Sequence[str],
            *,
            cwd: Path,
            env: Mapping[str, str],
            check: bool = True,
            timeout_seconds: float | None = None,
        ) -> subprocess.CompletedProcess[str]:
            del cwd, env, check
            self.timeouts.append(timeout_seconds)
            clock[0] += 20.0
            return subprocess.CompletedProcess(list(args), 0, "[]", "")

    root = _root(tmp_path)
    runner = DeadlineRunner()
    lane = joint.JointMemorialIngressDeployLane(
        root=root,
        env={
            "EA_DEPLOYMENT_ID": "joint-deadline-001",
            "EA_MEMORIAL_JOINT_ROLLBACK_DEADLINE_SECONDS": "30",
        },
        runner=runner,
        monotonic=lambda: clock[0],
        receipt_dir=tmp_path / "receipts",
        ingress_receipt_dir=tmp_path / "ingress-receipts",
        global_lock_path=tmp_path / "global.lock",
        durable_root_check=lambda _path: None,
    )
    ingress_lane = _ingress_lane(lane, tmp_path)
    ingress_lane.runner = runner

    with pytest.raises(api_deploy.DeployError, match="deadline_exceeded"):
        with lane._rollback_deadline_scope():
            ingress_lane.command_timeout_provider = (
                lane._remaining_mutation_action_seconds
            )
            ingress_lane._run(["docker", "network", "inspect", "ea-public"])
            ingress_lane._run(["docker", "network", "inspect", "ea-public"])
            ingress_lane._run(["docker", "network", "inspect", "ea-public"])

    assert runner.timeouts == [30.0, 10.0]


def test_late_rollback_http_probe_clamps_to_remaining_joint_budget(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    clock = [0.0]
    observed_timeouts: list[float] = []
    lane.monotonic = lambda: clock[0]
    lane.rollback_deadline_seconds = 30.0

    def timeout_probe(
        _url: str,
        timeout_seconds: float,
        _public_authority: str,
    ) -> api_deploy.HttpResponse:
        observed_timeouts.append(timeout_seconds)
        clock[0] += timeout_seconds
        raise api_deploy.DeployError("probe_timeout")

    lane.http_get = timeout_probe
    with pytest.raises(api_deploy.DeployError):
        with lane._rollback_deadline_scope():
            clock[0] = 25.0
            lane._wait_http("http://127.0.0.1:8090/health", kind="health")

    assert observed_timeouts == [5.0]


def test_transaction_lock_rejects_fifo_hardlink_and_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane, _runner = _lane(tmp_path)
    fifo = tmp_path / "fifo.lock"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(api_deploy.DeployError, match="lock_file_untrusted"):
        lane._open_lock(fifo, busy_reason="busy")

    original = tmp_path / "original.lock"
    original.write_text("lock\n", encoding="utf-8")
    original.chmod(0o600)
    hardlink = tmp_path / "hardlink.lock"
    os.link(original, hardlink)
    with pytest.raises(api_deploy.DeployError, match="lock_file_untrusted"):
        lane._open_lock(hardlink, busy_reason="busy")

    replaced = tmp_path / "replaced.lock"
    replaced.write_text("old\n", encoding="utf-8")
    replaced.chmod(0o600)

    def replace_after_flock(_descriptor: int, _operation: int) -> None:
        replaced.unlink()
        replaced.write_text("new\n", encoding="utf-8")
        replaced.chmod(0o600)

    monkeypatch.setattr(api_deploy.fcntl, "flock", replace_after_flock)
    with pytest.raises(api_deploy.DeployError, match="lock_file_changed"):
        lane._open_lock(replaced, busy_reason="busy")


def test_failure_after_ingress_attempt_rolls_back_both_components(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._verify_forward_cloudflared = Mock(
        side_effect=api_deploy.DeployError("forward_ingress_failed")
    )
    lane._perform_joint_rollback = Mock(return_value={"status": "pass"})

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_failed_rolled_back:forward_ingress_failed",
    ):
        lane.deploy()

    kwargs = lane._perform_joint_rollback.call_args.kwargs
    assert kwargs["api_mutation_started"] is True
    assert kwargs["ingress_mutation_started"] is True
    assert lane.receipt["status"] == "failed_rolled_back"


def test_failure_after_api_before_ingress_rolls_back_api_only(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._verify_non_memorial_controls = Mock(
        side_effect=api_deploy.DeployError("local_api_proof_failed")
    )
    lane._perform_joint_rollback = Mock(return_value={"status": "pass"})

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_failed_rolled_back:local_api_proof_failed",
    ):
        lane.deploy()

    kwargs = lane._perform_joint_rollback.call_args.kwargs
    assert kwargs["api_mutation_started"] is True
    assert kwargs["ingress_mutation_started"] is False


def test_joint_rollback_restores_components_in_order(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal, context = _rollback_authority_context(
        lane,
        tmp_path,
        api_mutation_started=True,
        ingress_mutation_started=True,
    )
    actions: list[str] = []
    lane._rollback_cloudflared = Mock(  # type: ignore[method-assign]
        side_effect=lambda _context: (
            actions.append("rollback_ingress") or {"status": "pass"}
        )
    )

    def rollback_api(
        _previous: Mapping[str, object],
        _rollback_tag: str,
        _baseline: Mapping[str, object],
        _deployment_input_seal: Mapping[str, object],
        _public_origin: str,
    ) -> dict[str, str]:
        actions.append("rollback_api")
        return {"status": "pass"}

    lane._rollback = Mock(side_effect=rollback_api)  # type: ignore[method-assign]
    lane._restore_public_network = Mock(  # type: ignore[method-assign]
        side_effect=lambda _context: (
            actions.append("restore_network") or {"status": "pass"}
        )
    )
    lane._capture_public_edge = Mock(  # type: ignore[method-assign]
        side_effect=lambda _origin: context["ingress"]["public_edge_baseline"]
    )

    result = lane._perform_joint_rollback(
        context=context,
        api_mutation_started=True,
        ingress_mutation_started=True,
        rollback_tag=str(journal["rollback_tag"]),
    )

    assert result["status"] == "pass"
    assert actions == [
        "rollback_ingress",
        "rollback_api",
        "restore_network",
    ]
    assert lane._rollback.call_args.args[4] == context["public_origin"]


def test_ingress_compose_detection_failure_does_not_skip_api_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal, context = _rollback_authority_context(
        lane,
        tmp_path,
        api_mutation_started=True,
        ingress_mutation_started=True,
    )
    detect_compose = Mock(
        side_effect=api_deploy.DeployError("docker_compose_unavailable")
    )
    monkeypatch.setattr(
        ingress.PublicIngressReconciliationLane,
        "_detect_compose",
        detect_compose,
    )
    lane._rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    lane._restore_public_network = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass", "preexisting": True, "removed": False}
    )
    lane._capture_public_edge = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_rollback_failed:ingress:docker_compose_unavailable",
    ):
        lane._perform_joint_rollback(
            context=context,
            api_mutation_started=True,
            ingress_mutation_started=True,
            rollback_tag=str(journal["rollback_tag"]),
        )

    detect_compose.assert_called_once_with()
    lane._rollback.assert_called_once()
    lane._restore_public_network.assert_called_once()
    lane._capture_public_edge.assert_not_called()
    rollback = dict(lane.receipt["rollback"])
    assert rollback["ingress"] == {
        "status": "fail",
        "reason": "docker_compose_unavailable",
    }
    assert rollback["api"]["status"] == "pass"
    assert rollback["network"]["status"] == "pass"


def test_recovery_context_forwards_recorded_public_origin_to_api_rollback(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal_payload, context = _rollback_authority_context(
        lane,
        tmp_path,
        api_mutation_started=True,
        ingress_mutation_started=False,
    )
    recorded_origin = str(journal_payload["public_origin"])
    lane._rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    lane._restore_public_network = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass", "preexisting": True, "removed": False}
    )
    lane._capture_public_edge = Mock(  # type: ignore[method-assign]
        return_value=dict(context["ingress"])["public_edge_baseline"]
    )

    result = lane._perform_joint_rollback(
        context=context,
        api_mutation_started=True,
        ingress_mutation_started=False,
        rollback_tag=str(journal_payload["rollback_tag"]),
    )

    assert result["status"] == "pass"
    assert lane._rollback.call_args.args[4] == recorded_origin


def test_public_edge_rollback_mismatch_records_only_bounded_identity_evidence(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal_payload, context = _rollback_authority_context(
        lane,
        tmp_path,
        api_mutation_started=True,
        ingress_mutation_started=False,
    )
    expected = dict(context["ingress"]["public_edge_baseline"])
    observed = json.loads(json.dumps(expected))
    observed["version_get"].update(
        {
            "content_type": "text/plain; diagnostic=secret-like-value",
            "body_bytes": 7,
            "body_sha256": "f" * 64,
        }
    )
    lane._rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    lane._restore_public_network = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass", "preexisting": True, "removed": False}
    )
    lane._capture_public_edge = Mock(  # type: ignore[method-assign]
        side_effect=[observed, observed]
    )
    lane._spatial_manifest_restart_order_compatibility = Mock(  # type: ignore[method-assign]
        return_value=None
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_rollback_failed:public_edge:joint_public_edge_rollback_mismatch",
    ):
        lane._perform_joint_rollback(
            context=context,
            api_mutation_started=True,
            ingress_mutation_started=False,
            rollback_tag=str(journal_payload["rollback_tag"]),
        )

    public_edge = lane.receipt["rollback"]["public_edge"]
    mismatch = public_edge["mismatch_evidence"]
    assert mismatch["mismatch_count"] == 1
    assert mismatch["response_metadata_copied"] is False
    assert set(mismatch["mismatches"]) == {"version_get"}
    row = mismatch["mismatches"]["version_get"]
    assert row["differing_fields"] == [
        "body_bytes",
        "body_sha256",
        "content_type",
    ]
    assert row["observed"]["body_bytes"] == 7
    assert row["observed"]["body_sha256"] == "f" * 64
    assert "secret-like-value" not in json.dumps(mismatch)
    assert lane._capture_public_edge.call_count == 2


def _legacy_spatial_manifest_body(
    variant_order: Sequence[str],
    *,
    display_title: str = "Alpha",
) -> bytes:
    values: dict[str, object] = {
        "creation_mode": "propertyquarry_governed_publication",
        "display_title": display_title,
        "scene_strategy": "generated_layout_reconstruction",
        "slug": "control-tour",
        "tour_privacy_mode": "anonymous_public",
        "facts": {},
        "brief": {},
        "scenes": [],
        "public_assets": [],
        "generated_viewer": {
            "url": "/tours/viewer/control-tour/generated-reconstruction/viewer.html",
            "release_revision": "property-3d-test",
            "disclosure": "Generated layout preview.",
            "synthetic": True,
            "verified_provider_capture": False,
        },
    }
    payload = {
        key: values[key]
        for key in (
            *variant_order,
            *joint.LEGACY_SPATIAL_MANIFEST_FIXED_SUFFIX_KEYS,
        )
    }
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _legacy_spatial_manifest_edge_row(body: bytes) -> dict[str, object]:
    probe = next(
        item for item in ingress.PUBLIC_PROBES if item.label == "spatial_manifest"
    )
    return {
        "method": "GET",
        "path": probe.path,
        "status": 200,
        "content_type": "application/json",
        "source_revision": SOURCE_REVISION,
        "location": "",
        "body_bytes": len(body),
        "body_sha256": joint._sha256(body),
    }


def test_legacy_spatial_manifest_restart_order_is_cryptographically_equivalent(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    expected_body = _legacy_spatial_manifest_body(
        ("scene_strategy", "slug", "display_title", "creation_mode")
    )
    observed_body = _legacy_spatial_manifest_body(
        ("slug", "creation_mode", "display_title", "scene_strategy")
    )
    assert len(expected_body) == len(observed_body)
    expected_row = _legacy_spatial_manifest_edge_row(expected_body)
    observed_row = _legacy_spatial_manifest_edge_row(observed_body)
    expected = {"spatial_manifest_get": expected_row}
    observed = {"spatial_manifest_get": observed_row}
    lane._capture_public_edge_response = Mock(  # type: ignore[method-assign]
        return_value=(observed_row, observed_body)
    )

    compatibility = lane._spatial_manifest_restart_order_compatibility(
        public_origin=ORIGIN,
        expected=expected,
        observed=observed,
    )

    assert compatibility is not None
    assert compatibility["status"] == "pass"
    assert compatibility["comparison"] == "legacy_json_top_level_order_only"
    assert compatibility["permuted_key_count"] == 4
    assert compatibility["variant_count"] == 24
    assert compatibility["expected_body_sha256"] == joint._sha256(expected_body)
    assert compatibility["observed_body_sha256"] == joint._sha256(observed_body)
    assert "control-tour" not in json.dumps(compatibility)


def test_legacy_spatial_manifest_restart_order_rejects_same_length_value_change(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    expected_body = _legacy_spatial_manifest_body(
        ("scene_strategy", "slug", "display_title", "creation_mode"),
        display_title="Alpha",
    )
    observed_body = _legacy_spatial_manifest_body(
        ("slug", "creation_mode", "display_title", "scene_strategy"),
        display_title="Bravo",
    )
    assert len(expected_body) == len(observed_body)
    expected_row = _legacy_spatial_manifest_edge_row(expected_body)
    observed_row = _legacy_spatial_manifest_edge_row(observed_body)
    expected = {"spatial_manifest_get": expected_row}
    observed = {"spatial_manifest_get": observed_row}
    lane._capture_public_edge_response = Mock(  # type: ignore[method-assign]
        return_value=(observed_row, observed_body)
    )

    assert (
        lane._spatial_manifest_restart_order_compatibility(
            public_origin=ORIGIN,
            expected=expected,
            observed=observed,
        )
        is None
    )


def test_legacy_spatial_manifest_restart_order_rejects_nonproducer_key_order(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    expected_body = _legacy_spatial_manifest_body(
        ("scene_strategy", "slug", "display_title", "creation_mode")
    )
    producer_body = _legacy_spatial_manifest_body(
        ("slug", "creation_mode", "display_title", "scene_strategy")
    )
    payload = json.loads(producer_body)
    nonproducer_body = json.dumps(
        {
            key: payload[key]
            for key in (
                *joint.LEGACY_SPATIAL_MANIFEST_FIXED_SUFFIX_KEYS,
                *joint.LEGACY_SPATIAL_MANIFEST_ORDER_VARIANT_KEYS,
            )
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(expected_body) == len(nonproducer_body)
    expected_row = _legacy_spatial_manifest_edge_row(expected_body)
    observed_row = _legacy_spatial_manifest_edge_row(nonproducer_body)
    lane._capture_public_edge_response = Mock(  # type: ignore[method-assign]
        return_value=(observed_row, nonproducer_body)
    )

    assert (
        lane._spatial_manifest_restart_order_compatibility(
            public_origin=ORIGIN,
            expected={"spatial_manifest_get": expected_row},
            observed={"spatial_manifest_get": observed_row},
        )
        is None
    )


def test_legacy_spatial_manifest_restart_order_rejects_confirmation_drift(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    expected_body = _legacy_spatial_manifest_body(
        ("scene_strategy", "slug", "display_title", "creation_mode")
    )
    observed_body = _legacy_spatial_manifest_body(
        ("slug", "creation_mode", "display_title", "scene_strategy")
    )
    drifted_body = _legacy_spatial_manifest_body(
        ("display_title", "slug", "creation_mode", "scene_strategy")
    )
    expected_row = _legacy_spatial_manifest_edge_row(expected_body)
    observed_row = _legacy_spatial_manifest_edge_row(observed_body)
    drifted_row = _legacy_spatial_manifest_edge_row(drifted_body)
    lane._capture_public_edge_response = Mock(  # type: ignore[method-assign]
        return_value=(drifted_row, drifted_body)
    )

    assert (
        lane._spatial_manifest_restart_order_compatibility(
            public_origin=ORIGIN,
            expected={"spatial_manifest_get": expected_row},
            observed={"spatial_manifest_get": observed_row},
        )
        is None
    )


def test_joint_rollback_records_verified_spatial_manifest_compatibility(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal, context = _rollback_authority_context(
        lane,
        tmp_path,
        api_mutation_started=True,
        ingress_mutation_started=False,
    )
    expected_body = _legacy_spatial_manifest_body(
        ("scene_strategy", "slug", "display_title", "creation_mode")
    )
    observed_body = _legacy_spatial_manifest_body(
        ("slug", "creation_mode", "display_title", "scene_strategy")
    )
    expected = {
        "spatial_manifest_get": _legacy_spatial_manifest_edge_row(expected_body)
    }
    observed = {
        "spatial_manifest_get": _legacy_spatial_manifest_edge_row(observed_body)
    }
    context["ingress"]["public_edge_baseline"] = expected
    compatibility = {
        "status": "pass",
        "comparison": "legacy_json_top_level_order_only",
    }
    lane._rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    lane._restore_public_network = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass", "preexisting": True, "removed": False}
    )
    lane._capture_public_edge = Mock(  # type: ignore[method-assign]
        side_effect=[observed, observed]
    )
    lane._spatial_manifest_restart_order_compatibility = Mock(  # type: ignore[method-assign]
        return_value=compatibility
    )

    result = lane._perform_joint_rollback_components(
        context=context,
        api_mutation_started=True,
        ingress_mutation_started=False,
        rollback_tag=str(journal["rollback_tag"]),
    )

    assert result["status"] == "pass"
    assert result["public_edge"] == {
        "status": "pass",
        "request_count": 3,
        "request_count_per_sample": 1,
        "stability_sample_count": 2,
        "compatibility_confirmation_request_count": 1,
        "matches_predeploy": True,
        "raw_fingerprint_matches_predeploy": False,
        "semantic_equivalence_verified": True,
        "compatibility": compatibility,
    }


def test_failed_component_rollback_receipt_preserves_every_component_result(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)
    lane._verify_forward_cloudflared = Mock(
        side_effect=api_deploy.DeployError("forward_ingress_failed")
    )
    lane._rollback_cloudflared = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("ingress_restore_failed")
    )
    lane._rollback = Mock(return_value={"status": "pass", "identity_restored": True})
    lane._restore_public_network = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass", "preexisting": True, "removed": False}
    )

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_and_rollback_failed:forward_ingress_failed",
    ):
        lane.deploy()

    rollback = dict(lane.receipt["rollback"])
    assert lane.receipt["status"] == "rollback_failed"
    assert rollback["ingress"] == {
        "status": "fail",
        "reason": "ingress_restore_failed",
    }
    assert rollback["api"]["status"] == "pass"
    assert rollback["network"]["status"] == "pass"
    assert rollback["failures"] == ["ingress:ingress_restore_failed"]
    assert rollback["primary_failure"] == "forward_ingress_failed"
    assert lane.receipt["joint_atomicity"]["rollback_executed"] is True
    assert lane.receipt["joint_atomicity"]["rollback_execution_status"] == "fail"


def test_second_interruption_during_rollback_does_not_skip_other_components(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    journal, context = _rollback_authority_context(
        lane,
        tmp_path,
        api_mutation_started=True,
        ingress_mutation_started=True,
    )
    lane._rollback_cloudflared = Mock(  # type: ignore[method-assign]
        side_effect=joint.JointDeploySignalInterruption("joint_deployment_signal:15")
    )
    lane._rollback = Mock(return_value={"status": "pass"})
    lane._restore_public_network = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]

    with pytest.raises(api_deploy.DeployError, match="joint_rollback_failed"):
        lane._perform_joint_rollback(
            context=context,
            api_mutation_started=True,
            ingress_mutation_started=True,
            rollback_tag=str(journal["rollback_tag"]),
        )

    lane._rollback.assert_called_once()
    lane._restore_public_network.assert_called_once()
    assert lane.receipt["rollback"]["ingress"]["status"] == "fail"


def test_cloudflared_runtime_identity_normalizes_only_alias_multiplicity() -> None:
    baseline = {
        "container": {
            "networks": [
                {
                    "name": ingress.PUBLIC_INGRESS_NETWORK,
                    "network_id": "f" * 64,
                    "ipv4_address": ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4,
                    "aliases": [
                        ingress.CLOUDFLARED_CONTAINER,
                        ingress.CLOUDFLARED_SERVICE,
                    ],
                }
            ]
        }
    }
    restored = json.loads(json.dumps(baseline))
    restored["container"]["networks"][0]["aliases"] = [
        ingress.CLOUDFLARED_SERVICE,
        ingress.CLOUDFLARED_SERVICE,
        ingress.CLOUDFLARED_CONTAINER,
    ]
    original_baseline = json.loads(json.dumps(baseline))
    original_restored = json.loads(json.dumps(restored))

    baseline_identity = (
        joint.JointMemorialIngressDeployLane._cloudflared_runtime_identity(baseline)
    )
    restored_identity = (
        joint.JointMemorialIngressDeployLane._cloudflared_runtime_identity(restored)
    )

    assert baseline_identity == restored_identity
    assert baseline_identity["networks"][0]["aliases"] == [
        ingress.CLOUDFLARED_SERVICE,
        ingress.CLOUDFLARED_CONTAINER,
    ]
    assert baseline == original_baseline
    assert restored == original_restored

    unexpected_alias = json.loads(json.dumps(restored))
    unexpected_alias["container"]["networks"][0]["aliases"].append("unexpected")
    assert (
        joint.JointMemorialIngressDeployLane._cloudflared_runtime_identity(
            unexpected_alias
        )
        != baseline_identity
    )

    changed_address = json.loads(json.dumps(restored))
    changed_address["container"]["networks"][0]["ipv4_address"] = "172.31.254.7"
    assert (
        joint.JointMemorialIngressDeployLane._cloudflared_runtime_identity(
            changed_address
        )
        != baseline_identity
    )

    malformed_alias = json.loads(json.dumps(restored))
    malformed_alias["container"]["networks"][0]["aliases"] = [1]
    assert (
        joint.JointMemorialIngressDeployLane._cloudflared_runtime_identity(
            malformed_alias
        )
        != baseline_identity
    )


@pytest.mark.parametrize("environment_kind", ("forward", "recovery"))
def test_ingress_rollback_rerenders_sealed_baseline_with_exact_environment(
    tmp_path: Path,
    environment_kind: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    context = _context(lane, tmp_path)
    context_ingress = context["ingress"]
    recovery_api_environment: dict[str, str] | None = None
    if environment_kind == "forward":
        ingress_lane = _ingress_lane(lane, tmp_path)
        ingress_lane.release_env.update(
            {
                "TUNNEL_TOKEN": "test-token",
                "CUSTOM_INTERPOLATION": "exact-value",
            }
        )
    else:
        lane.env.update(
            {
                "EA_CF_TUNNEL_TOKEN": "ambient-tunnel-secret",
                "EA_MEMORIAL_IMAGE": "ea-runtime:ambient",
                "UNRELATED_SECRET": "ambient-unrelated-secret",
            }
        )
        previous = dict(context["previous"])
        recovery_api_environment = lane._recovery_ingress_api_interpolation_environment(
            previous
        )
        ingress_lane = lane._build_ingress_lane(
            {
                "source_revision": SOURCE_REVISION,
                "public_origin": "https://myexternalbrain.com",
            },
            root=lane.root,
            receipt_dir=lane.ingress_receipt_dir,
            rollback_interpolation_environment=dict(
                context_ingress["rollback_interpolation_environment"]
            ),
            recovery_previous=previous,
        )
    rollback_seals = list(context_ingress["rollback_input_seals"])
    rollback_files = list(context_ingress["rollback_compose_files"])
    rollback_overlay = dict(context_ingress["rollback_overlay"])
    baseline_seals = [
        dict(item)
        for item in rollback_seals
        if dict(item).get("path") != rollback_overlay["path"]
    ]
    rendered = {
        "services": {
            ingress.CLOUDFLARED_SERVICE: context_ingress["rollback_render_projection"][
                "service"
            ]
        },
        "networks": context_ingress["rollback_render_projection"]["networks"],
    }
    rollback_projection = lane._ingress_rollback_projection(rendered)
    baseline = {
        "container": {
            "compose_working_dir": str(lane.root),
            "compose_config_files": rollback_files[:-1],
            "image_id": "sha256:" + "1" * 64,
            "image_reference": "cloudflare/cloudflared:2026.6.0",
            "compose_input_seals": baseline_seals,
            "environment_identity": {"environment_sha256": "2" * 64},
            "command": ["tunnel", "run"],
            "entrypoint": ["cloudflared"],
            "user": "65532:65532",
            "process_config_sha256": "3" * 64,
            "security": {},
            "mounts": [],
            "networks": [
                {
                    "name": ingress.PUBLIC_INGRESS_NETWORK,
                    "network_id": "f" * 64,
                    "driver": "bridge",
                    "ipam_driver": "default",
                    "ipam_config": [
                        {
                            "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                            "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
                        }
                    ],
                    "internal": False,
                    "attachable": False,
                    "ipv4_address": ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4,
                    "aliases": [
                        ingress.CLOUDFLARED_SERVICE,
                        ingress.CLOUDFLARED_CONTAINER,
                    ],
                }
            ],
        }
    }
    ingress_context = {
        "lane": ingress_lane,
        "cloudflared_baseline": baseline,
        "rollback_input_seals": rollback_seals,
        "rollback_working_dir": str(lane.root),
        "rollback_compose_files": rollback_files,
        "rollback_overlay": rollback_overlay,
        "rollback_interpolation_environment": dict(
            context_ingress["rollback_interpolation_environment"]
        ),
        "rollback_render_projection": rollback_projection,
        "rollback_render_sha256": joint._canonical_json_sha256(rollback_projection),
    }
    if recovery_api_environment is not None:
        ingress_context["recovery_api_interpolation_environment"] = (
            recovery_api_environment
        )
    lane._revalidate_ingress_input_seals = Mock()  # type: ignore[method-assign]
    lane._validate_ingress_rollback_networks = Mock()  # type: ignore[method-assign]
    rollback_steps: list[str] = []
    ingress_lane._detect_compose = Mock(  # type: ignore[method-assign]
        side_effect=lambda: rollback_steps.append("detect_compose")
    )

    def render_rollback(**_kwargs: object) -> tuple[dict[str, object], list[object]]:
        rollback_steps.append("render_compose")
        return rendered, rollback_seals

    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        side_effect=render_rollback
    )
    ingress_lane._compose_args = Mock(return_value=["docker", "compose"])  # type: ignore[method-assign]
    observed_environments: list[dict[str, str]] = []
    lane._run = Mock(  # type: ignore[method-assign]
        side_effect=lambda _args, **kwargs: (
            observed_environments.append(dict(kwargs["env"]))
            or subprocess.CompletedProcess([], 0, "", "")
        )
    )
    lane._wait_container = Mock(return_value={"running": "true"})

    def capture_restored() -> dict[str, object]:
        restored = json.loads(json.dumps(baseline))
        restored["container"]["compose_config_files"] = rollback_files
        restored["container"]["compose_input_seals"] = rollback_seals
        aliases = restored["container"]["networks"][0]["aliases"]
        restored["container"]["networks"][0]["aliases"] = [
            aliases[0],
            aliases[0],
            aliases[1],
            aliases[1],
        ]
        ingress_lane._write_private_json(ingress_lane.baseline_path, restored)
        return restored

    ingress_lane._capture_cloudflared_baseline = Mock(  # type: ignore[method-assign]
        side_effect=capture_restored
    )

    result = lane._rollback_cloudflared(ingress_context)

    assert result["status"] == "pass"
    assert rollback_steps == ["detect_compose", "render_compose"]
    ingress_lane._detect_compose.assert_called_once_with()
    if environment_kind == "forward":
        expected_environment = {
            **ingress_lane.release_env,
            **context_ingress["rollback_interpolation_environment"],
            "COMPOSE_PROJECT_NAME": "ea",
        }
    else:
        expected_environment = ingress_lane.release_env
        assert lane._run.call_args.kwargs["env"] is ingress_lane.release_env
    assert observed_environments == [expected_environment]
    ingress_lane._render_compose.assert_called_once_with(
        root=lane.root,
        files=rollback_files,
        expected_input_seals=rollback_seals,
    )
    lane._validate_ingress_rollback_networks.assert_called_once_with(  # type: ignore[attr-defined]
        ingress_lane,
        baseline,
    )


def test_rollback_overlay_change_after_render_blocks_before_compose(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context = _recovery_context(lane, tmp_path)
    ingress_context = context["ingress"]
    ingress_lane = ingress_context["lane"]
    ingress_lane._detect_compose = Mock()  # type: ignore[method-assign]
    rollback_projection = ingress_context["rollback_render_projection"]
    rendered = {
        "services": {ingress.CLOUDFLARED_SERVICE: rollback_projection["service"]},
        "networks": rollback_projection["networks"],
    }
    rollback_seals = list(ingress_context["rollback_input_seals"])
    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        return_value=(rendered, rollback_seals)
    )
    overlay_path = Path(str(ingress_context["rollback_overlay"]["path"]))

    def mutate_after_network_check(
        _ingress: ingress.PublicIngressReconciliationLane,
        _baseline: Mapping[str, object],
    ) -> None:
        overlay_path.write_text("# changed after render\n", encoding="utf-8")
        overlay_path.chmod(0o600)

    lane._validate_ingress_rollback_networks = mutate_after_network_check  # type: ignore[method-assign]
    lane._run = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_ingress_input_changed",
    ):
        lane._rollback_cloudflared(ingress_context)

    lane._run.assert_not_called()  # type: ignore[attr-defined]


def test_broken_421_edge_is_a_valid_prechange_rollback_fingerprint(
    tmp_path: Path,
) -> None:
    def snapshot(_url: str, _timeout: float, method: str) -> api_deploy.HttpResponse:
        return api_deploy.HttpResponse(
            421,
            "application/json",
            b"" if method == "HEAD" else b'{"error":"host_not_allowed"}',
            "",
            headers={},
        )

    root = _root(tmp_path)
    lane = joint.JointMemorialIngressDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "joint-421-test"},
        runner=NoCommandRunner(),
        public_snapshot=snapshot,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        durable_root_check=lambda _path: None,
    )

    evidence = lane._capture_public_edge("https://myexternalbrain.com")

    assert len(evidence) == len(ingress.PUBLIC_PROBES) * 2
    assert {item["status"] for item in evidence.values()} == {421}
    assert all(
        item["body_bytes"] == 0
        for item in evidence.values()
        if item["method"] == "HEAD"
    )


def test_changing_421_body_is_rejected_as_an_unstable_rollback_baseline(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    lane._capture_public_edge = Mock(  # type: ignore[method-assign]
        side_effect=[
            {"version_get": {"status": 421, "body_sha256": "a" * 64}},
            {"version_get": {"status": 421, "body_sha256": "b" * 64}},
        ]
    )

    with pytest.raises(api_deploy.DeployError, match="joint_public_snapshot_unstable"):
        lane._capture_stable_public_edge(ORIGIN)


def test_changed_ingress_input_is_rejected_before_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "docker-compose.yml"
    path.write_text("services: {}\n", encoding="utf-8")
    seal = ingress._trusted_file_seal(path)
    path.write_text("services:\n  changed: {}\n", encoding="utf-8")

    with pytest.raises(api_deploy.DeployError, match="joint_ingress_input_changed"):
        joint.JointMemorialIngressDeployLane._revalidate_ingress_input_seals([seal])


def test_optional_env_local_seal_accepts_exact_absence_and_private_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local"
    absent = ingress._trusted_optional_private_file_seal(path)
    joint.JointMemorialIngressDeployLane._revalidate_ingress_input_seals([absent])

    path.write_text("TUNNEL_TOKEN=test\n", encoding="utf-8")
    path.chmod(0o600)
    present = ingress._trusted_optional_private_file_seal(path)
    joint.JointMemorialIngressDeployLane._revalidate_ingress_input_seals([present])


def test_optional_env_local_seal_rejects_drift_and_symlink(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text("TUNNEL_TOKEN=first\n", encoding="utf-8")
    path.chmod(0o600)
    present = ingress._trusted_optional_private_file_seal(path)
    path.write_text("TUNNEL_TOKEN=changed\n", encoding="utf-8")
    with pytest.raises(api_deploy.DeployError, match="joint_ingress_input_changed"):
        joint.JointMemorialIngressDeployLane._revalidate_ingress_input_seals([present])

    path.unlink()
    absent = ingress._trusted_optional_private_file_seal(path)
    target = tmp_path / "target.env"
    target.write_text("TUNNEL_TOKEN=secret\n", encoding="utf-8")
    target.chmod(0o600)
    path.symlink_to(target)
    with pytest.raises(api_deploy.DeployError, match="reconciliation_input_untrusted"):
        joint.JointMemorialIngressDeployLane._revalidate_ingress_input_seals([absent])


def test_exact_legacy_property_detached_baseline_gets_private_sealed_overlay(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    lane.ingress_receipt_dir.mkdir(parents=True, mode=0o700)
    lane.ingress_receipt_dir.chmod(0o700)
    compose_path = lane.root / "docker-compose.yml"
    compose_path.write_text(
        "services:\n  ea-cloudflared:\n    image: test-cloudflared\n",
        encoding="utf-8",
    )
    compose_path.chmod(0o644)
    prior_files = [str(compose_path)]
    baseline_seals = ingress_lane._capture_compose_input_seals(
        root=lane.root,
        files=prior_files,
    )
    prior_service = {
        "image": ingress.PINNED_CLOUDFLARED_IMAGE,
        "environment": {"TUNNEL_TOKEN": "test-tunnel-token"},
        "networks": {
            "default": None,
            ingress.LEGACY_PROPERTY_NETWORK: None,
        },
    }
    prior_rendered = {
        "services": {ingress.CLOUDFLARED_SERVICE: prior_service},
        "networks": {
            "default": {"name": "ea_default"},
            ingress.LEGACY_PROPERTY_NETWORK: {
                "external": True,
                "name": ingress.LEGACY_PROPERTY_NETWORK,
            },
        },
    }
    normalized_service = {
        **prior_service,
        "networks": {
            "default": {
                "ipv4_address": "172.30.0.2",
                "aliases": sorted(
                    [
                        ingress.CLOUDFLARED_CONTAINER,
                        ingress.CLOUDFLARED_SERVICE,
                    ]
                ),
            }
        },
    }
    normalized_rendered = {
        "services": {ingress.CLOUDFLARED_SERVICE: normalized_service},
        "networks": {
            "default": {"external": True, "name": "ea_default"},
        },
    }
    baseline = {
        "container": {
            "compose_working_dir": str(lane.root),
            "compose_config_files": prior_files,
            "compose_input_seals": baseline_seals,
            "networks": [
                {
                    "name": "ea_default",
                    "ipv4_address": "172.30.0.2",
                    "aliases": [
                        ingress.CLOUDFLARED_CONTAINER,
                        ingress.CLOUDFLARED_SERVICE,
                    ],
                }
            ],
        }
    }
    render_calls: list[list[str]] = []

    def render_compose(
        *,
        root: Path,
        files: Sequence[str],
        expected_input_seals: Sequence[Mapping[str, object]],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        assert root == lane.root
        selected_files = list(files)
        render_calls.append(selected_files)
        if selected_files == prior_files:
            assert list(expected_input_seals) == baseline_seals
            return prior_rendered, baseline_seals
        current_seals = ingress_lane._capture_compose_input_seals(
            root=root,
            files=selected_files,
        )
        assert list(expected_input_seals) == current_seals
        return normalized_rendered, current_seals

    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        side_effect=render_compose
    )

    bundle = lane._prepare_ingress_rollback_bundle(
        ingress_lane,
        baseline,
    )

    overlay = dict(bundle["overlay"])
    overlay_path = Path(str(overlay["path"]))
    overlay_metadata = overlay_path.stat()
    overlay_text = overlay_path.read_text(encoding="utf-8")
    assert overlay == {
        "contract_name": joint.INGRESS_ROLLBACK_OVERLAY_CONTRACT_NAME,
        "path": str(overlay_path),
        "sha256": ingress._trusted_file_seal(
            overlay_path,
            private=True,
            expected_uid=os.geteuid(),
        )["sha256"],
        "contains_secret_material": False,
        "runtime_network_names": ["ea_default"],
        "logical_network_names": ["default"],
        "normalized_property_detachment": True,
    }
    assert stat.S_IMODE(overlay_metadata.st_mode) == 0o600
    assert overlay_metadata.st_uid == os.geteuid()
    assert overlay_metadata.st_nlink == 1
    assert ingress.LEGACY_PROPERTY_NETWORK not in overlay_text
    assert "test-tunnel-token" not in overlay_text
    assert render_calls == [
        prior_files,
        list(bundle["compose_files"]),
        list(bundle["compose_files"]),
    ]

    reused_baseline = {
        "container": {
            **baseline["container"],
            "compose_config_files": list(bundle["compose_files"]),
            "compose_input_seals": list(bundle["input_seals"]),
        }
    }
    reused_bundle = lane._prepare_ingress_rollback_bundle(
        ingress_lane,
        reused_baseline,
    )

    assert reused_bundle["compose_files"] == bundle["compose_files"]
    assert reused_bundle["input_seals"] == bundle["input_seals"]
    assert reused_bundle["overlay"] == bundle["overlay"] | {
        "normalized_property_detachment": False
    }
    assert (
        sum(
            Path(item).name.endswith(f".{joint.INGRESS_ROLLBACK_OVERLAY_SUFFIX}")
            for item in reused_bundle["compose_files"]
        )
        == 1
    )


def test_reused_overlay_round_trips_through_v2_recovery_journal(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    context = _recovery_context(lane, tmp_path)
    ingress_context = context["ingress"]
    assert isinstance(ingress_context, dict)
    cloudflared_baseline = ingress_context["cloudflared_baseline"]
    assert isinstance(cloudflared_baseline, dict)
    container = cloudflared_baseline["container"]
    assert isinstance(container, dict)
    container["compose_config_files"] = list(ingress_context["rollback_compose_files"])
    container["compose_input_seals"] = list(ingress_context["rollback_input_seals"])
    journal_payload = lane._new_recovery_journal(
        context=context,
        rollback_tag=joint._safe_rollback_tag(lane.deployment_id),
    )

    _validated, recovery_context = lane._validate_recovery_journal(journal_payload)

    recovered_ingress = recovery_context["ingress"]
    assert (
        recovered_ingress["rollback_compose_files"]
        == (ingress_context["rollback_compose_files"])
    )
    assert (
        recovered_ingress["rollback_input_seals"]
        == (ingress_context["rollback_input_seals"])
    )
    assert runner.commands == []


def _strict_public_network_snapshot() -> dict[str, object]:
    return {
        "present": True,
        "id": "network-id",
        "name": ingress.PUBLIC_INGRESS_NETWORK,
        "driver": "bridge",
        "ipam_driver": "default",
        "ipam_config": [
            {
                "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
            }
        ],
        "internal": False,
        "attachable": False,
        "containers": [
            {
                "container_id": "prior-api-container",
                "name": ingress.API_SERVICE,
                "ipv4_address": (f"{ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4}/29"),
                "ipv6_address": "",
            }
        ],
    }


def test_pre_api_network_recheck_binds_exact_preflight_membership(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    baseline = _strict_public_network_snapshot()
    context = {"previous": {"container_id": "prior-api-container"}}
    cloudflared = {"container": {"id": "prior-cloudflared-container"}}

    lane._validate_ingress_address_reservations(
        context=context,
        network_baseline=baseline,
        cloudflared_baseline=cloudflared,
    )
    changed = json.loads(json.dumps(baseline))
    changed["containers"][0]["ipv4_address"] = f"{ingress.PUBLIC_INGRESS_API_IPV4}/29"

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_ingress_network_topology_changed",
    ):
        lane._validate_ingress_address_reservations(
            context=context,
            network_baseline=changed,
            cloudflared_baseline=cloudflared,
            phase="before_recreate_api",
            expected_network_baseline=baseline,
        )

    assert runner.commands == []


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("network_id", "joint_ingress_rollback_network_changed"),
        ("foreign_member", "joint_ingress_rollback_network_members_invalid"),
        ("occupied_ipv4", "joint_ingress_rollback_ipv4_unavailable"),
    ],
)
def test_rollback_network_recheck_blocks_changed_or_occupied_topology(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    baseline = _recovery_context(lane, tmp_path)["ingress"]["cloudflared_baseline"]
    current = {
        "Id": "c" * 64,
        "Name": ingress.PUBLIC_INGRESS_NETWORK,
        "Driver": "bridge",
        "IPAM": {
            "Driver": "default",
            "Config": [
                {
                    "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                    "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
                }
            ],
        },
        "Internal": False,
        "Attachable": False,
        "Containers": {
            "api-current": {
                "Name": ingress.API_SERVICE,
                "IPv4Address": f"{ingress.PUBLIC_INGRESS_API_IPV4}/29",
                "IPv6Address": "",
            },
            "cloudflared-current": {
                "Name": ingress.CLOUDFLARED_CONTAINER,
                "IPv4Address": (f"{ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4}/29"),
                "IPv6Address": "",
            },
        },
    }
    if mutation == "network_id":
        current["Id"] = "d" * 64
    elif mutation == "foreign_member":
        current["Containers"]["foreign"] = {
            "Name": "foreign",
            "IPv4Address": "172.31.254.4/29",
            "IPv6Address": "",
        }
    else:
        current["Containers"]["cloudflared-current"]["Name"] = "foreign"
    ingress_lane._inspect_network = Mock(return_value=current)  # type: ignore[method-assign]

    with pytest.raises(api_deploy.DeployError, match=reason):
        lane._validate_ingress_rollback_networks(ingress_lane, baseline)


@pytest.mark.parametrize(
    "corruption",
    [
        "previous_compose_type",
        "previous_compose_nul",
        "cloudflared_container_type",
        "cloudflared_compose_nul",
        "cloudflared_networks_type",
        "cloudflared_security_memory_type",
        "cloudflared_aliases_type",
        "deployment_rollback_seal_type",
        "rollback_compose_nul",
        "overlay_path_nul",
        "top_receipt_nul",
        "top_ingress_receipt_surrogate",
        "rollback_projection_surrogate",
        "rollback_seal_type",
        "rollback_seal_uid_type",
    ],
)
def test_malformed_v2_recovery_nested_types_fail_as_deploy_error_without_commands(
    tmp_path: Path,
    corruption: str,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    damaged = json.loads(json.dumps(payload))
    rollback_context = damaged["rollback_context"]
    ingress_payload = rollback_context["ingress"]
    if corruption == "previous_compose_type":
        rollback_context["previous"]["compose_config_files"] = 7
    elif corruption == "previous_compose_nul":
        rollback_context["previous"]["compose_config_files"][0] += "\x00bad"
    elif corruption == "cloudflared_container_type":
        ingress_payload["cloudflared_baseline"]["container"] = 7
    elif corruption == "cloudflared_compose_nul":
        ingress_payload["cloudflared_baseline"]["container"]["compose_config_files"][
            0
        ] += "\x00bad"
    elif corruption == "cloudflared_networks_type":
        ingress_payload["cloudflared_baseline"]["container"]["networks"] = 7
    elif corruption == "cloudflared_security_memory_type":
        ingress_payload["cloudflared_baseline"]["container"]["security"]["memory"] = []
    elif corruption == "cloudflared_aliases_type":
        ingress_payload["cloudflared_baseline"]["container"]["networks"][0][
            "aliases"
        ] = 7
    elif corruption == "deployment_rollback_seal_type":
        rollback_context["deployment_input_seal"]["rollback"] = [7]
    elif corruption == "rollback_compose_nul":
        ingress_payload["rollback_compose_files"][0] += "\x00bad"
    elif corruption == "overlay_path_nul":
        ingress_payload["rollback_overlay"]["path"] += "\x00bad"
    elif corruption == "top_receipt_nul":
        damaged["receipt_dir"] += "\x00bad"
    elif corruption == "top_ingress_receipt_surrogate":
        damaged["ingress_receipt_dir"] += "\ud800"
    elif corruption == "rollback_projection_surrogate":
        ingress_payload["rollback_render_projection"]["service"]["image"] = "\ud800"
    elif corruption == "rollback_seal_type":
        ingress_payload["rollback_input_seals"] = [7]
    else:
        ingress_payload["rollback_input_seals"][-2]["uid"] = "not-an-int"

    with pytest.raises(api_deploy.DeployError):
        lane._validate_recovery_journal(damaged)

    assert runner.commands == []


@pytest.mark.parametrize(
    "timestamp",
    [
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-14:00",
    ],
)
def test_v2_recovery_timestamp_overflow_is_a_controlled_deploy_error(
    tmp_path: Path,
    timestamp: str,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    damaged = json.loads(json.dumps(payload))
    damaged["created_at"] = timestamp

    with pytest.raises(
        api_deploy.DeployError,
        match="joint_recovery_journal_schema_invalid",
    ):
        lane._validate_recovery_journal(damaged)

    assert runner.commands == []


@pytest.mark.parametrize(
    "corruption",
    ["timestamp_overflow", "path_surrogate", "projection_surrogate", "security_type"],
)
def test_malformed_v2_journal_is_classified_invalid_before_recovery_mutation(
    tmp_path: Path,
    corruption: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    damaged = json.loads(json.dumps(payload))
    ingress_payload = damaged["rollback_context"]["ingress"]
    if corruption == "timestamp_overflow":
        damaged["created_at"] = "0001-01-01T00:00:00+14:00"
    elif corruption == "path_surrogate":
        damaged["ingress_receipt_dir"] += "\ud800"
    elif corruption == "projection_surrogate":
        ingress_payload["rollback_render_projection"]["service"]["image"] = "\ud800"
    else:
        ingress_payload["cloudflared_baseline"]["container"]["security"]["memory"] = []
    _write_json(lane.recovery_journal_path, damaged, mode=0o600)
    restarted = _restart_lane(lane, tmp_path)
    restarted._perform_joint_rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("invalid journal reached rollback")
    )

    with pytest.raises(api_deploy.DeployError):
        restarted._recover_interrupted_transaction(preflight_only=False)

    assert restarted.receipt["status"] == "recovery_journal_invalid"
    assert restarted.receipt["recovery"]["mutation_attempted"] is False
    restarted._perform_joint_rollback.assert_not_called()
    assert restarted.runner.commands == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "public_origin",
            "https://myexternalbrain.com:99999",
            "joint_recovery_public_origin_invalid",
        ),
        (
            "public_origin",
            "https://[broken",
            "joint_recovery_public_origin_invalid",
        ),
        (
            "api_local_origin",
            "http://127.0.0.1:99999",
            "joint_recovery_api_local_origin_invalid",
        ),
        (
            "api_local_origin",
            "http://[broken",
            "joint_recovery_api_local_origin_invalid",
        ),
    ],
)
def test_malformed_v2_recovery_origins_are_controlled_deploy_errors(
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
) -> None:
    lane, runner = _lane(tmp_path)
    payload = _write_recovery_journal(
        lane,
        tmp_path,
        phase="api_mutation_possible",
    )
    damaged = json.loads(json.dumps(payload))
    damaged[field] = value

    with pytest.raises(api_deploy.DeployError, match=reason):
        lane._validate_recovery_journal(damaged)

    assert runner.commands == []


def test_ingress_input_seal_rejects_control_character_path_before_io() -> None:
    with pytest.raises(
        api_deploy.DeployError,
        match="joint_ingress_input_seal_invalid",
    ):
        joint.JointMemorialIngressDeployLane._revalidate_ingress_input_seals(
            [
                {
                    "path": "/tmp/invalid\x00seal",
                    "present": False,
                }
            ]
        )


def test_external_public_rollback_projection_accepts_only_empty_compose_ipam(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    projection = _context(lane, tmp_path)["ingress"]["rollback_render_projection"]
    projection["networks"]["public_ingress"]["ipam"] = {}

    environment = lane._ingress_rollback_environment(projection)

    assert environment["EA_PUBLIC_INGRESS_NETWORK_NAME"] == (
        ingress.PUBLIC_INGRESS_NETWORK
    )
    projection["networks"]["public_ingress"]["ipam"] = {
        "config": [{"subnet": "10.0.0.0/8"}]
    }
    with pytest.raises(
        api_deploy.DeployError,
        match="joint_ingress_rollback_environment_invalid",
    ):
        lane._ingress_rollback_environment(projection)


def test_real_joint_ingress_preflight_passes_captured_seals_to_render_and_is_read_only(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    fixture_context = _context(lane, tmp_path)["ingress"]
    target_seals = [{"path": "/target", "scope": "target"}]
    rollback_seals = list(fixture_context["rollback_input_seals"])
    rollback_bundle = {
        "working_dir": fixture_context["rollback_working_dir"],
        "compose_files": list(fixture_context["rollback_compose_files"]),
        "input_seals": rollback_seals,
        "interpolation_environment": dict(
            fixture_context["rollback_interpolation_environment"]
        ),
        "render_projection": dict(fixture_context["rollback_render_projection"]),
        "render_sha256": fixture_context["rollback_render_sha256"],
        "overlay": dict(fixture_context["rollback_overlay"]),
    }
    events: list[str] = []
    lane._build_ingress_lane = Mock(return_value=ingress_lane)  # type: ignore[method-assign]
    ingress_lane._git_source_preflight = Mock()  # type: ignore[method-assign]
    ingress_lane._detect_compose = Mock()  # type: ignore[method-assign]
    ingress_lane._capture_compose_input_seals = Mock(  # type: ignore[method-assign]
        side_effect=lambda **_kwargs: (
            events.append("capture_target_seals") or target_seals
        )
    )
    lane._capture_public_network = Mock(  # type: ignore[method-assign]
        side_effect=lambda _ingress: (
            events.append("capture_network") or {"present": False}
        )
    )

    def capture_baseline(
        *, allow_legacy_property_detached: bool = False
    ) -> dict[str, object]:
        assert allow_legacy_property_detached is True
        events.append("capture_cloudflared_baseline")
        payload = {"container": {"compose_input_seals": rollback_seals}}
        ingress_lane._write_private_json(ingress_lane.baseline_path, payload)
        return payload

    ingress_lane._capture_cloudflared_baseline = Mock(  # type: ignore[method-assign]
        side_effect=capture_baseline
    )

    def validate_target(
        *, expected_input_seals: Sequence[Mapping[str, object]]
    ) -> dict[str, object]:
        events.append("validate_target")
        assert list(expected_input_seals) == target_seals
        ingress_lane._record_check(
            "target_compose",
            "pass",
            compose_input_seals=target_seals,
        )
        return {"services": {}}

    ingress_lane._validate_target_compose = Mock(  # type: ignore[method-assign]
        side_effect=validate_target
    )

    def prepare_rollback(
        selected_ingress: ingress.PublicIngressReconciliationLane,
        selected_baseline: Mapping[str, object],
    ) -> dict[str, object]:
        assert selected_ingress is ingress_lane
        assert selected_baseline["container"]["compose_input_seals"] == (rollback_seals)
        events.append("prepare_rollback")
        return rollback_bundle

    lane._prepare_ingress_rollback_bundle = Mock(  # type: ignore[method-assign]
        side_effect=prepare_rollback
    )
    lane._revalidate_ingress_input_seals = Mock()  # type: ignore[method-assign]
    lane._capture_public_edge = Mock(  # type: ignore[method-assign]
        return_value={"version_get": {"status": 421}}
    )

    result = lane._preflight_ingress(
        {"source_revision": SOURCE_REVISION, "public_origin": ORIGIN}
    )

    assert result["target_input_seals"] == target_seals
    assert events == [
        "capture_target_seals",
        "capture_network",
        "capture_cloudflared_baseline",
        "validate_target",
        "prepare_rollback",
    ]
    assert runner.commands == []


def _spatial_binding_inputs(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
    *,
    browser_override: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], Path, Path]:
    browser = {
        "schema": joint.CANDIDATE_BROWSER_SCHEMA,
        "status": "pass",
        "secret_material_recorded": False,
        "proof": "exact",
    }
    candidate = {
        "schema": joint.CANDIDATE_RUNTIME_SCHEMA,
        "status": "pass",
        "spatial_handoff_runtime": {"candidate_browser_gate": browser},
    }
    candidate_path = tmp_path / "candidate-binding.private.json"
    browser_path = tmp_path / "browser-binding.private.json"
    _write_json(candidate_path, candidate, mode=0o600)
    _write_json(browser_path, browser_override or browser, mode=0o600)
    lane.env[joint.SPATIAL_BROWSER_RECEIPT_ENV] = str(browser_path)
    evidence = {
        "path": str(candidate_path),
        "sha256": joint._sha256(candidate_path.read_bytes()),
        "schema": joint.CANDIDATE_RUNTIME_SCHEMA,
        "status": "pass",
        "spatial_handoff": {
            "browser_schema": joint.CANDIDATE_BROWSER_SCHEMA,
            "browser_pass": True,
            "identity_bound": True,
        },
    }
    return evidence, candidate_path, browser_path


def test_joint_preflight_requires_explicit_spatial_browser_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane, _runner = _lane(tmp_path)
    context = _context(lane, tmp_path)
    monkeypatch.setattr(
        api_deploy.MemorialDeployLane,
        "preflight",
        lambda _self: context,
    )
    lane._preflight_ingress = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError, match="joint_spatial_browser_receipt_required"
    ):
        lane.preflight()

    lane._preflight_ingress.assert_not_called()


def test_spatial_browser_receipt_must_equal_candidate_embedded_gate(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    evidence, _candidate_path, _browser_path = _spatial_binding_inputs(
        lane,
        tmp_path,
        browser_override={
            "schema": joint.CANDIDATE_BROWSER_SCHEMA,
            "status": "pass",
            "secret_material_recorded": False,
            "proof": "different",
        },
    )

    with pytest.raises(
        api_deploy.DeployError, match="joint_spatial_browser_binding_invalid"
    ):
        lane._load_spatial_browser_binding(evidence)


def test_network_cleanup_refuses_nonempty_network(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    lane._capture_public_network = Mock(  # type: ignore[method-assign]
        return_value={
            "present": True,
            "name": ingress.PUBLIC_INGRESS_NETWORK,
            "driver": "bridge",
            "ipam_driver": "default",
            "ipam_config": [
                {
                    "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                    "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
                }
            ],
            "containers": [{"name": "foreign"}],
        }
    )
    lane._run = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError, match="joint_public_network_cleanup_unsafe"
    ):
        lane._restore_public_network(
            {
                "lane": ingress_lane,
                "network_baseline": {"present": False},
            }
        )

    lane._run.assert_not_called()


def _empty_compose_owned_public_network() -> tuple[
    dict[str, object], dict[str, object]
]:
    network_id = "a" * 64
    snapshot = {
        "present": True,
        "id": network_id,
        "name": ingress.PUBLIC_INGRESS_NETWORK,
        "driver": "bridge",
        "ipam_driver": "default",
        "ipam_config": [
            {
                "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
            }
        ],
        "internal": False,
        "attachable": False,
        "containers": [],
    }
    inspection = {
        "Id": network_id,
        "Name": ingress.PUBLIC_INGRESS_NETWORK,
        "Driver": "bridge",
        "Internal": False,
        "Attachable": False,
        "Containers": {},
        "Labels": {
            "com.docker.compose.config-hash": "b" * 64,
            "com.docker.compose.network": "public_ingress",
            "com.docker.compose.project": "ea",
            "com.docker.compose.version": "5.1.3",
        },
    }
    return snapshot, inspection


def test_absent_baseline_cleanup_removes_only_exact_compose_owned_network_id(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    snapshot, inspection = _empty_compose_owned_public_network()
    lane._capture_public_network = Mock(  # type: ignore[method-assign]
        side_effect=[snapshot, {"present": False}]
    )
    ingress_lane._inspect_network = Mock(  # type: ignore[method-assign]
        return_value=inspection
    )
    lane._run = Mock()  # type: ignore[method-assign]

    result = lane._restore_public_network(
        {
            "lane": ingress_lane,
            "network_baseline": {"present": False},
        }
    )

    lane._run.assert_called_once_with(["docker", "network", "rm", "a" * 64])
    assert result == {
        "status": "pass",
        "preexisting": False,
        "removed": True,
        "network_id_sha256": joint._sha256(("a" * 64).encode("ascii")),
        "ownership": "exact_compose_network_labels_verified",
    }


@pytest.mark.parametrize(
    "drift",
    ["replacement_id", "project_label", "internal", "attachable"],
)
def test_absent_baseline_cleanup_refuses_replacement_or_flag_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    snapshot, inspection = _empty_compose_owned_public_network()
    if drift == "replacement_id":
        inspection["Id"] = "c" * 64
    elif drift == "project_label":
        inspection["Labels"]["com.docker.compose.project"] = "foreign"
    elif drift == "internal":
        snapshot["internal"] = True
    else:
        snapshot["attachable"] = True
    lane._capture_public_network = Mock(  # type: ignore[method-assign]
        return_value=snapshot
    )
    ingress_lane._inspect_network = Mock(  # type: ignore[method-assign]
        return_value=inspection
    )
    lane._run = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError,
        match=(
            "joint_public_network_cleanup_unsafe"
            if drift in {"internal", "attachable"}
            else "joint_public_network_cleanup_ownership_unproven"
        ),
    ):
        lane._restore_public_network(
            {
                "lane": ingress_lane,
                "network_baseline": {"present": False},
            }
        )

    lane._run.assert_not_called()


def _preexisting_network_snapshot(
    *,
    api_id: str,
    cloudflared_id: str,
    cloudflared_ipv4: str = "172.31.250.2/24",
) -> dict[str, object]:
    return {
        "present": True,
        "id": "network-id-stable",
        "name": ingress.PUBLIC_INGRESS_NETWORK,
        "driver": "bridge",
        "ipam_driver": "default",
        "ipam_config": [
            {
                "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
            }
        ],
        "internal": False,
        "attachable": False,
        "containers": [
            {
                "container_id": api_id,
                "name": "ea-api",
                "ipv4_address": "172.31.250.3/24",
                "ipv6_address": "",
            },
            {
                "container_id": cloudflared_id,
                "name": "ea-cloudflared",
                "ipv4_address": cloudflared_ipv4,
                "ipv6_address": "",
            },
        ],
    }


def test_preexisting_network_rollback_ignores_only_recreated_container_ids(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    baseline = _preexisting_network_snapshot(api_id="old-api", cloudflared_id="old-cf")
    current = _preexisting_network_snapshot(api_id="new-api", cloudflared_id="new-cf")
    lane._capture_public_network = Mock(return_value=current)  # type: ignore[method-assign]

    result = lane._restore_public_network(
        {"lane": ingress_lane, "network_baseline": baseline}
    )

    assert result == {"status": "pass", "preexisting": True, "removed": False}


def test_preexisting_network_rollback_rejects_stable_topology_mismatch(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    baseline = _preexisting_network_snapshot(api_id="old-api", cloudflared_id="old-cf")
    current = _preexisting_network_snapshot(
        api_id="new-api",
        cloudflared_id="new-cf",
        cloudflared_ipv4="172.31.250.99/24",
    )
    lane._capture_public_network = Mock(return_value=current)  # type: ignore[method-assign]

    with pytest.raises(
        api_deploy.DeployError, match="joint_public_network_rollback_mismatch"
    ):
        lane._restore_public_network(
            {"lane": ingress_lane, "network_baseline": baseline}
        )


def _successful_joint_materializer_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, materializer.SourceState]:
    legacy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    lane, _runner = _lane(tmp_path)
    context, _actions = _install_success_path(lane, tmp_path)
    promotion = dict(legacy["candidate_promotion_evidence"])
    promotion.update(
        {
            "schema": joint.CANDIDATE_RUNTIME_SCHEMA,
            "spatial_handoff": {
                "browser_schema": joint.CANDIDATE_BROWSER_SCHEMA,
                "browser_pass": True,
                "identity_bound": True,
            },
            "projection": {},
        }
    )
    browser_sha256 = joint._sha256(browser_path.read_bytes())
    browser_binding = {
        "status": "pass",
        "candidate_runtime_receipt_path": promotion["path"],
        "candidate_runtime_receipt_sha256": promotion["sha256"],
        "candidate_runtime_schema": joint.CANDIDATE_RUNTIME_SCHEMA,
        "browser_receipt_path": str(browser_path),
        "browser_receipt_sha256": browser_sha256,
        "browser_schema": joint.CANDIDATE_BROWSER_SCHEMA,
        "secret_material_recorded": False,
        "exact_embedded_binding": True,
    }
    context["candidate_promotion"] = promotion
    context["spatial_browser_binding"] = browser_binding
    lane.receipt.update(
        {
            "source_revision": legacy["source_revision"],
            "public_origin": legacy["public_origin"],
            "source_worktree": legacy["source_worktree"],
            "candidate_promotion_evidence": promotion,
            "public_spatial_tour": legacy["public_spatial_tour"],
            "spatial_browser_binding": browser_binding,
        }
    )

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert lane.receipt_path.read_bytes()
    return lane.receipt_path, browser_path, source_state


def test_successful_joint_receipt_materializes_strict_spatial_gold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _successful_joint_materializer_inputs(
        tmp_path, monkeypatch
    )
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    cleanup = dict(deploy["recovery_journal_cleanup"])
    assert cleanup["status"] == "removed"
    assert cleanup["path"] == str(
        tmp_path / "host-state" / joint.JOINT_RECOVERY_JOURNAL_FILENAME
    )
    assert cleanup["contains_secret_material"] is True
    assert cleanup["state_directory"] == _cleanup_state_directory_identity(
        tmp_path / "host-state"
    )

    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        expected_public_origin=ORIGIN,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )

    assert receipt["status"] == "pass", receipt
    assert receipt["deploy_binding"]["contract_name"] == (
        spatial_contract.JOINT_DEPLOY_RECEIPT_CONTRACT
    )
    assert (
        spatial_contract.validate_memorial_spatial_public_origin_receipt(
            receipt,
            current_head=source_state.head,
            current_fingerprint=source_state.fingerprint,
        )
        == []
    )


def test_new_spatial_materialization_rejects_legacy_api_only_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(
        tmp_path,
        monkeypatch,
        joint_deploy=False,
    )
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    deploy["service_scope"] = ["ea-api", "ea-redis"]
    deploy["api_mutation_scope"] = ["ea-api"]
    _write_json(deploy_path, deploy, mode=0o600)

    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        expected_public_origin=ORIGIN,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )

    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["failed_codes"] == ["joint_deploy_receipt_required"]


@pytest.mark.parametrize(
    "mutation",
    (
        "atomicity",
        "cleanup_incident",
        "cleanup_missing",
        "cleanup_pending",
        "edge",
        "handoff_browser_sha",
        "browser_binding",
        "legacy_downgrade",
    ),
)
def test_joint_materializer_rejects_incomplete_or_downgraded_envelopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    deploy_path, browser_path, source_state = _successful_joint_materializer_inputs(
        tmp_path, monkeypatch
    )
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    if mutation == "atomicity":
        deploy["joint_atomicity"]["rollback_executed"] = True
        deploy["joint_atomicity"]["rollback_execution_status"] = "pass"
    elif mutation == "cleanup_incident":
        deploy["recovery_journal_cleanup"]["status"] = "retained_cleanup_failed"
    elif mutation == "cleanup_missing":
        deploy.pop("recovery_journal_cleanup")
    elif mutation == "cleanup_pending":
        deploy["recovery_journal_cleanup"]["status"] = "pending_after_commit"
    elif mutation == "edge":
        deploy["joint_public_edge"]["source_revision"] = "f" * 40
    elif mutation == "handoff_browser_sha":
        deploy["spatial_materializer_handoff"]["candidate_browser_receipt"][
            "sha256"
        ] = "f" * 64
    elif mutation == "browser_binding":
        deploy.pop("spatial_browser_binding")
    elif mutation == "legacy_downgrade":
        deploy["contract_name"] = spatial_contract.DEPLOY_RECEIPT_CONTRACT
    _write_json(deploy_path, deploy, mode=0o600)

    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        expected_public_origin=ORIGIN,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )

    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False
    if mutation == "cleanup_missing":
        assert receipt["failed_codes"] == ["joint_recovery_journal_cleanup_missing"]
    elif mutation in {"cleanup_incident", "cleanup_pending"}:
        assert receipt["failed_codes"] == ["joint_recovery_journal_cleanup_invalid"]


def test_joint_cli_modes_are_mutually_exclusive() -> None:
    args = joint._parse_args(["--preflight-only"])
    assert args.preflight_only is True
    finalizer = joint._parse_args(["--finalize-committed-cleanup"])
    assert finalizer.finalize_committed_cleanup is True
    recovery = joint._parse_args(["--recover-active"])
    assert recovery.recover_active is True
    with pytest.raises(SystemExit):
        joint._parse_args(["--preflight-only", "--finalize-committed-cleanup"])
    with pytest.raises(SystemExit):
        joint._parse_args(["--preflight-only", "--recover-active"])
    with pytest.raises(SystemExit):
        joint._parse_args(["--finalize-committed-cleanup", "--recover-active"])
    with pytest.raises(SystemExit):
        joint._parse_args(["--mutate-ingress-only"])


def test_joint_recover_active_cli_exits_without_deploy_continuation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = {
        "status": "active_recovery_complete",
        "recover_active": {
            "status": "pass",
            "recovery_status": "pass",
            "new_deployment_started": False,
        },
    }
    lane = Mock()
    lane.recover_active.return_value = receipt
    constructor = Mock(return_value=lane)
    monkeypatch.setattr(joint, "JointMemorialIngressDeployLane", constructor)

    assert joint.main(["--recover-active"]) == 0

    lane.recover_active.assert_called_once_with()
    lane.deploy.assert_not_called()
    lane.finalize_committed_cleanup.assert_not_called()
    assert json.loads(capsys.readouterr().out) == receipt


def test_inherited_deployed_surface_uses_joint_wait_http_public_authority_signature(
    tmp_path: Path,
) -> None:
    authorities: list[str] = []
    html = (
        "<!doctype html><html><body>Manfred – ist nicht Manfred; "
        "spricht nicht für ihn.</body></html>"
    ).encode()
    manifest = json.dumps(
        {
            "slug": "manfred",
            "intro": "Dies ist nicht Manfred und spricht nicht für ihn.",
        },
        separators=(",", ":"),
    ).encode()

    def http_get(
        url: str,
        _timeout: float,
        public_authority: str = "",
    ) -> api_deploy.HttpResponse:
        authorities.append(public_authority)
        if url.endswith(".json"):
            return api_deploy.HttpResponse(
                200,
                "application/json",
                manifest,
                SOURCE_REVISION,
            )
        if url.endswith("/health"):
            return api_deploy.HttpResponse(
                200,
                "application/json",
                b"{}",
                SOURCE_REVISION,
            )
        return api_deploy.HttpResponse(200, "text/html", html, SOURCE_REVISION)

    def no_redirect(
        url: str,
        _timeout: float,
        method: str,
        public_authority: str = "",
    ) -> api_deploy.HttpResponse:
        if urllib.parse.urlsplit(url).hostname == "127.0.0.1":
            assert public_authority == "myexternalbrain.com"
            parsed = urllib.parse.urlsplit(url)
            location = f"{ORIGIN}{parsed.path}"
            if parsed.query:
                location = f"{location}?{parsed.query}"
            return api_deploy.HttpResponse(
                308,
                "text/html",
                b"" if method == "HEAD" else b"redirect",
                headers={"Location": location},
            )
        return api_deploy.HttpResponse(
            308,
            "text/html",
            b"" if method == "HEAD" else b"redirect",
            "",
            headers={
                "Location": "/memorials/manfred?from=ea-launch-verifier",
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    root = _root(tmp_path)
    lane = joint.JointMemorialIngressDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "joint-signature-001"},
        runner=NoCommandRunner(),
        http_get=http_get,
        http_no_redirect=no_redirect,
        receipt_dir=tmp_path / "signature-receipts",
        ingress_receipt_dir=tmp_path / "signature-ingress-receipts",
        global_lock_path=tmp_path / "signature-global.lock",
        recovery_journal_path=(
            tmp_path / "signature-state" / joint.JOINT_RECOVERY_JOURNAL_FILENAME
        ),
        durable_root_check=lambda _path: None,
    )
    lane._verify_public_spatial_tour = Mock(  # type: ignore[method-assign]
        return_value={"request_count": 6}
    )

    lane._verify_deployed_surface(
        ORIGIN,
        source_revision=SOURCE_REVISION,
        candidate_promotion_evidence={},
    )

    assert authorities == ["", "", ""]
    assert lane.receipt["local_https_redirects"]["trusted_proxy_headers_sent"] is False
    assert lane.receipt["checks"][-1]["name"] == "local_and_public_memorial"
