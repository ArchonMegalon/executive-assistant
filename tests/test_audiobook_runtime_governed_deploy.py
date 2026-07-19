from __future__ import annotations

import copy
from contextlib import nullcontext
import fcntl
import hashlib
import json
import os
import subprocess
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from scripts import deploy_ea_audiobook_runtime as deploy
from scripts import vexp_schema_v6_authority as schema_v6
from scripts import verify_audiobook_runtime_production_stage as producer


NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
SOURCE = "b" * 40
IMAGE_ID = "sha256:" + "c" * 64
IMAGE_REFERENCE = "registry.example/ea-runtime@sha256:" + "d" * 64
OVERLAY_SHA = "e" * 64
RENDERED_SHA = "f" * 64
SBOM_SHA = "a" * 64


class NoCommandRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        call = tuple(args)
        self.calls.append(call)
        raise AssertionError(f"unexpected command: {call!r}")

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, env, check
        call = tuple(args)
        self.calls.append(call)
        raise AssertionError(f"unexpected command: {call!r}")


def _compose_config_sha256(service: str) -> str:
    return hashlib.sha256(f"compose:{service}".encode()).hexdigest()


class RenderRunner:
    def __init__(
        self,
        rendered: Mapping[str, Any],
        *,
        config_hashes: Mapping[str, str] | None = None,
    ) -> None:
        self.rendered = dict(rendered)
        self.config_hashes = {
            service: _compose_config_sha256(service)
            for service in deploy.TARGET_SERVICES
        }
        if config_hashes is not None:
            self.config_hashes.update(config_hashes)
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        call = tuple(args)
        self.calls.append(call)
        if "--hash" in call:
            service = call[call.index("--hash") + 1]
            stdout = f"{service} {self.config_hashes[service]}\n"
        elif "config" in call:
            stdout = json.dumps(self.rendered)
        else:
            stdout = ""
        return subprocess.CompletedProcess(list(args), 0, stdout, "")

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        result = self.run(args, cwd=cwd, env=env, check=check)
        return subprocess.CompletedProcess(
            result.args,
            result.returncode,
            result.stdout.encode(),
            result.stderr.encode(),
        )


class GitBlobRunner:
    def __init__(
        self,
        blobs: Mapping[str, bytes],
        *,
        drift_on_final_read: str | None = None,
    ) -> None:
        self.blobs = dict(blobs)
        self.drift_on_final_read = drift_on_final_read
        self.read_counts: dict[str, int] = {}
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del check
        call = tuple(args)
        self.calls.append((call, dict(env)))
        if "symbolic-ref" in call:
            stdout = "main\n"
        elif "--abbrev-ref" in call:
            stdout = "origin/main\n"
        elif "--show-toplevel" in call:
            stdout = f"{cwd.resolve()}\n"
        elif "--git-common-dir" in call or "--git-dir" in call:
            stdout = f"{(cwd / '.git').resolve()}\n"
        elif "rev-parse" in call:
            stdout = f"{SOURCE}\n"
        elif "for-each-ref" in call or "ls-files" in call or "diff" in call:
            stdout = ""
        else:
            raise AssertionError(f"unexpected text git command: {call!r}")
        return subprocess.CompletedProcess(list(args), 0, stdout, "")

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, check
        call = tuple(args)
        self.calls.append((call, dict(env)))
        path = call[-1].split(":", 1)[1]
        count = self.read_counts.get(path, 0) + 1
        self.read_counts[path] = count
        payload = self.blobs[path]
        if self.drift_on_final_read == path and count > 1:
            payload += b"# drift\n"
        return subprocess.CompletedProcess(list(args), 0, payload, b"")


class LocalAuthorityLane(deploy.AudiobookRuntimeDeployLane):
    def __init__(self, *, authority_root: Path, **kwargs: Any) -> None:
        self._authority_root = authority_root
        super().__init__(**kwargs)

    @property
    def root_authority_uid(self) -> int:
        return os.geteuid()

    @property
    def schema_v6_permit_path(self) -> Path:
        return self._authority_root / "schema-v6-permit.json"

    @property
    def stage_owner_permit_path(self) -> Path:
        return self._authority_root / "stage-owner-permit.json"

    @property
    def authority_lock_paths(self) -> tuple[Path, Path]:
        return (
            self._authority_root / "schema-v6-permit.lock",
            self._authority_root / "stage-owner-permit.lock",
        )

    def _load_schema_v6_qualification(
        self,
    ) -> schema_v6.QualificationEvidence:
        state = deploy._read_trusted_json(
            self.sentinel_path,
            expected_uid=self.sentinel_owner_uid,
            maximum_bytes=deploy.MAX_EVIDENCE_BYTES,
            reason_prefix="test_schema_v6_state",
        )
        permit = deploy._read_trusted_json(
            self.schema_v6_permit_path,
            expected_uid=self.root_authority_uid,
            expected_mode=0o644,
            maximum_bytes=deploy.MAX_AUTHORITY_BYTES,
            reason_prefix="test_schema_v6_permit",
        )
        return schema_v6.validate_schema_v6_qualification(
            state.payload,
            permit.payload,
            state_sha256=state.sha256,
            permit_sha256=permit.sha256,
            now=self._guard_now(),
        )


def _write_json(path: Path, payload: object, *, mode: int = 0o600) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    path.chmod(mode)
    return hashlib.sha256(raw).hexdigest()


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    for name in (
        ".env",
        "docker-compose.yml",
        "docker-compose.memorial.yml",
        "docker-compose.whatsapp-web-session.yml",
        str(deploy.PRODUCTION_OVERLAY),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("services: {}\n", encoding="utf-8")
    return root


def _lane(
    tmp_path: Path,
    *,
    runner: object | None = None,
) -> deploy.AudiobookRuntimeDeployLane:
    root = _root(tmp_path)
    config = tmp_path / "candidate-config.json"
    provenance = tmp_path / "candidate-provenance.json"
    sbom = tmp_path / "candidate-sbom.json"
    memorial_baseline = tmp_path / "memorial-baseline.json"
    for issuer_lock in (
        tmp_path / "schema-v6-permit.lock",
        tmp_path / "stage-owner-permit.lock",
    ):
        issuer_lock.write_text("issuer-coordinated\n", encoding="utf-8")
        issuer_lock.chmod(0o644)
    env = {
        "EA_DEPLOYMENT_ID": "audiobook-test-001",
        "EA_AUDIOBOOK_RUNTIME_IMAGE": IMAGE_REFERENCE,
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_CONFIGURATION_RECEIPT": str(config),
        "EA_AUDIOBOOK_RUNTIME_PROVENANCE_RECEIPT": str(provenance),
        "EA_AUDIOBOOK_RUNTIME_SBOM": str(sbom),
        "EA_AUDIOBOOK_RUNTIME_MEMORIAL_BASELINE_RECEIPT": str(memorial_baseline),
        "EA_AUDIOBOOK_RUNTIME_PRODUCTION_OVERLAY": str(deploy.PRODUCTION_OVERLAY),
        "PATH": os.environ.get("PATH", ""),
    }
    return LocalAuthorityLane(
        authority_root=tmp_path,
        root=root,
        env=env,
        runner=runner or NoCommandRunner(),
        utc_now=lambda: NOW,
        sleep=lambda _seconds: None,
        monotonic=lambda: 0.0,
        wait_seconds=0,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        memorial_api_lock_path=tmp_path / "memorial-api.lock",
        sentinel_path=tmp_path / "sentinel.json",
        sentinel_owner_uid=os.geteuid(),
        evidence_owner_uid=os.geteuid(),
    )


def _state(**changes: object) -> dict[str, Any]:
    state: dict[str, Any] = {
        "version": 6,
        "epoch_started_at": "2026-07-13T09:43:56.206Z",
        "epoch_started_ms": 1783935836206,
        "qualification_phase": "qualified",
        "qualification_earliest_completion_at": "2026-07-20T09:43:56.206Z",
        "qualified_at": "2026-07-20T09:43:56.206Z",
        "updated_at": "2026-07-20T09:59:30Z",
        "current_resources_healthy": True,
        "certification_blockers": [],
    }
    state.update(changes)
    return state


def _inert_projection() -> dict[str, Any]:
    projection: dict[str, Any] = {
        "contract_name": deploy.CANDIDATE_CONFIGURATION_CONTRACT,
        "status": "pass",
        "configuration_only": True,
        "deploy_ready": False,
        "target_services": list(deploy.TARGET_SERVICES),
        "source_revision": SOURCE,
        "candidate_image_reference": IMAGE_REFERENCE,
        "overlay_sha256": OVERLAY_SHA,
        "rendered_contract_sha256": RENDERED_SHA,
        "execution_scope": "isolated_candidate_configuration",
        "live_api_owner": "memorial",
        "owner_handoff_required": True,
        "memorial_compatible": False,
        "group_deploy_eligible": False,
        "silent_takeover_allowed": False,
    }
    projection.update(
        {field: False for field in deploy.INERT_CONFIGURATION_AUTHORITY_FIELDS}
    )
    return projection


def _schema_v6_permit(state: Mapping[str, Any]) -> dict[str, Any]:
    terminal = deploy._vexp_terminal_identity(state)
    return {
        "contract_name": "ea.vexp_memorial_mutation_permit.v1",
        "version": 1,
        "status": "allow",
        **terminal,
        "terminal_identity_sha256": deploy._canonical_sha256(terminal),
        "issued_at": "2026-07-20T09:50:00Z",
        "expires_at": "2026-07-20T10:30:00Z",
        "mutation_boundaries": [
            "before_ensure_redis",
            "before_protect_previous_image",
            "before_recreate_api",
        ],
    }


def _provenance(sbom_sha256: str) -> dict[str, Any]:
    return {
        "contract_name": deploy.PRODUCTION_PROVENANCE_CONTRACT,
        "version": 1,
        "status": "pass",
        "source_revision": SOURCE,
        "image_reference": IMAGE_REFERENCE,
        "image_id": IMAGE_ID,
        "sbom_sha256": sbom_sha256,
    }


def _sbom() -> dict[str, Any]:
    namespace = "urn:ea:audiobook-runtime:test-document"
    serial = "urn:uuid:12345678-1234-5678-1234-567812345678"
    return {
        "contract_name": deploy.PRODUCTION_SBOM_CONTRACT,
        "version": 1,
        "status": "pass",
        "document_namespace": namespace,
        "serial_number": serial,
        "subject_name": "ea-runtime",
        "subject_image_reference": IMAGE_REFERENCE,
        "subject_image_id": IMAGE_ID,
        "subject_source_revision": SOURCE,
        "bom": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "serialNumber": serial,
            "metadata": {
                "component": {
                    "name": "ea-runtime",
                    "properties": [
                        {"name": "ea:document-namespace", "value": namespace},
                        {"name": "ea:image-reference", "value": IMAGE_REFERENCE},
                        {"name": "ea:image-id", "value": IMAGE_ID},
                        {"name": "ea:source-revision", "value": SOURCE},
                    ],
                }
            },
            "components": [{"type": "application", "name": "ea-runtime"}],
        },
    }


def _production_authority(
    lane: deploy.AudiobookRuntimeDeployLane,
    *,
    rendered_sha256: str = RENDERED_SHA,
    baseline_rendered_sha256: str = "8" * 64,
    baseline_api_sha256: str = "9" * 64,
) -> dict[str, Any]:
    state = _state()
    state_sha = _write_json(lane.sentinel_path, state)
    schema_permit_sha = _write_json(
        lane.schema_v6_permit_path,
        _schema_v6_permit(state),
        mode=0o644,
    )
    sbom_sha = _write_json(lane.sbom_receipt_path, _sbom())
    provenance_sha = _write_json(lane.provenance_receipt_path, _provenance(sbom_sha))
    inventory: list[dict[str, str]] = []
    for index, path in enumerate(deploy.PRODUCTION_COMPOSE_SOURCE_PATHS):
        digest = (
            OVERLAY_SHA
            if path == deploy.PRODUCTION_OVERLAY
            else hashlib.sha256(
                f"compose:{index}:{path.as_posix()}".encode()
            ).hexdigest()
        )
        inventory.append(
            {
                "path": path.as_posix(),
                "blob_sha256": digest,
                "working_sha256": digest,
            }
        )
    baseline_inventory = inventory[:-1]
    baseline_inventory_sha = deploy._canonical_sha256(baseline_inventory)
    baseline_receipt = {
        "contract_name": deploy.MEMORIAL_BASELINE_CONTRACT,
        "version": 1,
        "status": "pass",
        "issuer": "ea-memorial-runtime-owner",
        "source_revision": SOURCE,
        "compose_source_inventory": baseline_inventory,
        "compose_source_inventory_sha256": baseline_inventory_sha,
        "rendered_compose_sha256": baseline_rendered_sha256,
        "ea_api_sha256": baseline_api_sha256,
        "issued_at": "2026-07-20T09:45:00Z",
        "expires_at": "2026-07-20T10:25:00Z",
    }
    memorial_receipt_sha = _write_json(
        lane.memorial_baseline_receipt_path,
        baseline_receipt,
        mode=0o644,
    )
    qualification = {
        "state_version": 6,
        "state_sha256": state_sha,
        "terminal_identity_sha256": deploy._canonical_sha256(
            deploy._vexp_terminal_identity(state)
        ),
        "qualified_at": state["qualified_at"],
        "permit_contract_name": "ea.vexp_memorial_mutation_permit.v1",
        "permit_sha256": schema_permit_sha,
        "permit_expires_at": "2026-07-20T10:30:00Z",
        "evidence_scope": "schema_v6_terminal_qualification_only",
        "mutation_authority_transferred": False,
        "validated": True,
    }
    memorial_summary = {
        "contract_name": deploy.MEMORIAL_BASELINE_CONTRACT,
        "receipt_sha256": memorial_receipt_sha,
        "source_revision": SOURCE,
        "compose_inventory_sha256": baseline_inventory_sha,
        "rendered_compose_sha256": baseline_rendered_sha256,
        "ea_api_sha256": baseline_api_sha256,
    }
    provenance_summary = {
        "contract_name": deploy.PRODUCTION_PROVENANCE_CONTRACT,
        "sha256": provenance_sha,
        "source_revision": SOURCE,
        "image_reference": IMAGE_REFERENCE,
        "image_id": IMAGE_ID,
    }
    sbom_payload = _sbom()
    sbom_summary = {
        "contract_name": deploy.PRODUCTION_SBOM_CONTRACT,
        "sha256": sbom_sha,
        "document_namespace": sbom_payload["document_namespace"],
        "serial_number": sbom_payload["serial_number"],
        "subject_name": "ea-runtime",
        "subject_image_reference": IMAGE_REFERENCE,
        "subject_image_id": IMAGE_ID,
        "subject_source_revision": SOURCE,
    }
    projection_core = {
        "contract_name": deploy.PRODUCTION_PROJECTION_CONTRACT,
        "deployment_scope": "paused_stage_only",
        "target_services": list(deploy.TARGET_SERVICES),
        "stage_mutation_services": list(deploy.WORKER_SERVICES),
        "preserved_services": [deploy.API_SERVICE],
        "source_revision": SOURCE,
        "candidate_image_reference": IMAGE_REFERENCE,
        "candidate_image_id": IMAGE_ID,
        "compose_source_inventory": inventory,
        "compose_source_inventory_sha256": deploy._canonical_sha256(inventory),
        "overlay_path": deploy.PRODUCTION_OVERLAY.as_posix(),
        "overlay_blob_sha256": OVERLAY_SHA,
        "overlay_working_sha256": OVERLAY_SHA,
        "rendered_compose_sha256": rendered_sha256,
        "memorial_baseline": memorial_summary,
        "schema_v6_terminal_identity_sha256": qualification["terminal_identity_sha256"],
        "provenance": provenance_summary,
        "sbom": sbom_summary,
        "live_api_owner": "memorial",
        "live_api_mutation_authority": False,
        "runtime_activation_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
    }
    stage_projection_sha = deploy._canonical_sha256(projection_core)
    denied = {
        "deployment_authority": False,
        "group_deploy_eligible": False,
        "runtime_activation_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
    }
    projection = {
        "contract_name": deploy.PRODUCTION_PROJECTION_CONTRACT,
        "version": 1,
        "status": "prepared",
        "configuration_only": True,
        "configuration_valid": True,
        "preparation_valid": True,
        "non_transferable": True,
        "deploy_ready": False,
        "deployment_scope": "paused_stage_only",
        "stage_deploy_eligible": False,
        "stage_mutation_authority": False,
        **denied,
        "target_services": list(deploy.TARGET_SERVICES),
        "stage_mutation_services": list(deploy.WORKER_SERVICES),
        "preserved_services": [deploy.API_SERVICE],
        "source_revision": SOURCE,
        "candidate_image_reference": IMAGE_REFERENCE,
        "candidate_image_id": IMAGE_ID,
        "compose_source_inventory": inventory,
        "compose_source_inventory_sha256": deploy._canonical_sha256(inventory),
        "overlay_path": deploy.PRODUCTION_OVERLAY.as_posix(),
        "overlay_blob_sha256": OVERLAY_SHA,
        "overlay_working_sha256": OVERLAY_SHA,
        "rendered_compose_sha256": rendered_sha256,
        "memorial_baseline": memorial_summary,
        "stage_projection_sha256": stage_projection_sha,
        "provenance": provenance_summary,
        "sbom": sbom_summary,
        "live_api_owner": "memorial",
        "live_api_mutation_authority": False,
        "owner_handoff_required": True,
        "owner_handoff_performed": False,
        "owner_preservation_permit_required": True,
        "required_owner_permit_contract": deploy.STAGE_OWNER_PERMIT_CONTRACT,
        "silent_takeover_allowed": False,
        "memorial_compatible": True,
        "schema_v6_qualification": qualification,
        "side_effect_posture": {
            "deployment_hold": True,
            "replicas_zero": {service: 0 for service in deploy.WORKER_SERVICES},
            "idle_command_bound": True,
            "queue_mutation_authority": False,
            "provider_work_authority": False,
            "outbound_send_authority": False,
            "runtime_activation_authority": False,
        },
    }
    return {
        "contract_name": deploy.PRODUCTION_PREFLIGHT_CONTRACT,
        "version": 1,
        "status": "prepared",
        "verification_mode": "prepare",
        "verified_at": "2026-07-20T09:56:00Z",
        "mutations_performed": 0,
        "preparation_valid": True,
        "non_transferable": True,
        "deploy_ready": False,
        "deployment_scope": "paused_stage_only",
        "stage_deploy_eligible": False,
        "stage_mutation_authority": False,
        **denied,
        "issues": [],
        "production_projection": projection,
        "next_action": (
            "governed_consumer_must_issue_and_atomically_consume_a_"
            "distinct_root_one_shot_permit"
        ),
    }


def _rendered_service(service: str) -> dict[str, Any]:
    env = {
        "EA_SOURCE_REVISION": SOURCE,
        "EA_DEPLOY_COMMIT_SHA": SOURCE,
        **deploy.PAUSED_STAGE_SERVICE_ENV.get(service, {}),
    }
    return {
        "image": IMAGE_REFERENCE,
        "pull_policy": "never",
        "command": list(deploy.PAUSED_STAGE_IDLE_COMMAND),
        "entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
        "working_dir": "/app",
        "user": "10001:10001",
        "environment": env,
        "labels": {
            "org.opencontainers.image.revision": SOURCE,
            **deploy.PAUSED_STAGE_LABELS,
        },
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "restart": "no",
        "tmpfs": ["/tmp", "/run"],
        "healthcheck": {"disable": True},
        "container_name": service,
        "networks": {"default": None},
        "deploy": {"placement": {}, "replicas": 0, "resources": {}},
        **deploy.PAUSED_STAGE_RESOURCES.get(service, {}),
    }


def _prepare_owner_permit_subject(
    lane: deploy.AudiobookRuntimeDeployLane,
) -> None:
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    lane.target_compose_config_sha256 = {
        "ea-worker": _compose_config_sha256("ea-worker")
    }
    _write_json(
        lane.configuration_receipt_path,
        _production_authority(lane),
    )
    lane._read_evidence()
    lane.pre_state = {"sha256": "1" * 64}
    lane.target_compose_sha256 = RENDERED_SHA
    lane.target_compose_config_sha256 = {
        service: _compose_config_sha256(service) for service in deploy.WORKER_SERVICES
    }
    lane.rollback_plan_sha256 = "2" * 64
    lane.forward_input_plan_sha256 = "4" * 64
    prior_path = lane.receipt_dir / "prior-owner-request.json"
    _write_json(
        prior_path,
        {
            "contract_name": deploy.DEPLOY_RECEIPT_CONTRACT,
            "deployment_id": lane.deployment_id,
            "status": "preflight_only_owner_permit_required",
            "permit_request": {"stage_projection_sha256": "request"},
            "cleanup": {"status": "pass"},
        },
    )
    lane.prior_preflight_receipt = deploy._read_trusted_json(
        prior_path,
        expected_uid=os.geteuid(),
        maximum_bytes=deploy.MAX_EVIDENCE_BYTES,
        reason_prefix="test_prior_preflight",
    )


def _stage_owner_permit(
    lane: deploy.AudiobookRuntimeDeployLane,
) -> dict[str, Any]:
    projection = lane.configuration_projection
    qualification = lane.schema_v6_qualification
    assert qualification is not None
    assert lane.configuration_document is not None
    assert lane.prior_preflight_receipt is not None
    memorial = projection["memorial_baseline"]
    return {
        "contract_name": deploy.STAGE_OWNER_PERMIT_CONTRACT,
        "version": 1,
        "status": "allow",
        "issuer": "ea-memorial-runtime-owner",
        "permit_id": "audiobook-paused-stage-001",
        "nonce": "3" * 64,
        "deployment_id": lane.deployment_id,
        "single_use": True,
        "scope": "paused_stage_only",
        "live_api_owner": "memorial",
        "owner_decision": "preserve_memorial_api_and_allow_paused_stage",
        "stage_projection_sha256": projection["stage_projection_sha256"],
        "production_preflight_sha256": lane.configuration_document.sha256,
        "consumer_preflight_receipt_sha256": (lane.prior_preflight_receipt.sha256),
        "source_revision": SOURCE,
        "candidate_image_reference": IMAGE_REFERENCE,
        "candidate_image_id": IMAGE_ID,
        "compose_source_inventory_sha256": projection[
            "compose_source_inventory_sha256"
        ],
        "overlay_blob_sha256": projection["overlay_blob_sha256"],
        "rendered_compose_sha256": projection["rendered_compose_sha256"],
        "memorial_baseline_receipt_sha256": memorial["receipt_sha256"],
        "memorial_ea_api_sha256": memorial["ea_api_sha256"],
        "stage_mutation_services": list(deploy.WORKER_SERVICES),
        "preserved_services": list(deploy.PRESERVED_RUNTIME_SERVICES),
        "pre_state_sha256": lane.pre_state["sha256"],
        "target_compose_sha256": lane.target_compose_sha256,
        "target_compose_config_sha256": dict(lane.target_compose_config_sha256),
        "rollback_plan_sha256": lane.rollback_plan_sha256,
        "forward_input_plan_sha256": lane.forward_input_plan_sha256,
        "schema_v6_terminal_identity_sha256": (qualification.terminal_identity_sha256),
        "schema_v6_permit_sha256": qualification.permit_sha256,
        "provenance_sha256": projection["provenance"]["sha256"],
        "sbom_sha256": projection["sbom"]["sha256"],
        "allowed_actions": list(deploy.PAUSED_STAGE_MUTATION_ACTIONS),
        "issued_at": "2026-07-20T09:59:00Z",
        "expires_at": "2026-07-20T10:20:00Z",
        "stage_mutation_authority": True,
        "deployment_authority": False,
        "group_deploy_eligible": False,
        "live_api_mutation_authority": False,
        "runtime_activation_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
    }


def _paused_inspection(
    lane: deploy.AudiobookRuntimeDeployLane,
    service: str,
) -> dict[str, Any]:
    resources = deploy.PAUSED_STAGE_RESOURCES[service]
    labels = {
        "com.docker.compose.project": "ea",
        "com.docker.compose.service": service,
        "com.docker.compose.project.working_dir": str(lane.root),
        "com.docker.compose.project.config_files": ",".join(
            str(
                (lane.root / raw).resolve()
                if not Path(raw).is_absolute()
                else Path(raw).resolve()
            )
            for raw in lane.target_compose_files
        ),
        "com.docker.compose.config-hash": lane.target_compose_config_sha256[service],
        "org.opencontainers.image.revision": SOURCE,
        **deploy.PAUSED_STAGE_LABELS,
    }
    environment = {
        "EA_SOURCE_REVISION": SOURCE,
        "EA_DEPLOY_COMMIT_SHA": SOURCE,
        **deploy.PAUSED_STAGE_SERVICE_ENV[service],
    }
    host: dict[str, Any] = {
        "ReadonlyRootfs": True,
        "Privileged": False,
        "CapAdd": [],
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true"],
        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        "Tmpfs": {"/tmp": "", "/run": ""},
        "CpuShares": resources["cpu_shares"],
        "NanoCpus": int(float(resources["cpus"]) * 1_000_000_000),
        "Binds": [],
        "PublishAllPorts": False,
        "PortBindings": {},
    }
    if "pids_limit" in resources:
        host["PidsLimit"] = resources["pids_limit"]
    return {
        "Id": hashlib.sha256(f"container:{service}".encode()).hexdigest(),
        "Image": IMAGE_ID,
        "Config": {
            "Image": IMAGE_REFERENCE,
            "Cmd": list(deploy.PAUSED_STAGE_IDLE_COMMAND),
            "Entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
            "WorkingDir": "/app",
            "User": "10001:10001",
            "Healthcheck": {"Test": ["NONE"]},
            "Env": [f"{key}={value}" for key, value in environment.items()],
            "Labels": labels,
        },
        "HostConfig": host,
        "State": {
            "Status": "created",
            "Running": False,
            "Restarting": False,
            "Paused": False,
            "Dead": False,
        },
        "Mounts": [],
        "NetworkSettings": {"Networks": {"ea_default": {}}},
    }


def test_default_is_preflight_only() -> None:
    assert deploy._parse_args([]).execute is False


def test_consumer_constants_match_exact_producer_contract() -> None:
    assert deploy.PRODUCTION_PREFLIGHT_CONTRACT == producer.ROOT_CONTRACT
    assert deploy.PRODUCTION_PROJECTION_CONTRACT == producer.PROJECTION_CONTRACT
    assert deploy.STAGE_OWNER_PERMIT_CONTRACT == (
        producer.REQUIRED_OWNER_PERMIT_CONTRACT
    )
    assert deploy.MEMORIAL_BASELINE_CONTRACT == (producer.MEMORIAL_BASELINE_CONTRACT)
    assert deploy.PRODUCTION_PROVENANCE_CONTRACT == producer.PROVENANCE_CONTRACT
    assert deploy.PRODUCTION_SBOM_CONTRACT == producer.SBOM_CONTRACT
    assert deploy.PRODUCTION_COMPOSE_SOURCE_PATHS == producer.COMPOSE_SOURCE_PATHS
    assert deploy.TARGET_SERVICES == producer.TARGET_SERVICES
    assert deploy.WORKER_SERVICES == producer.STAGE_MUTATION_SERVICES
    assert set(deploy.EXPECTED_RUNTIME_SERVICES) == set(producer.EXPECTED_SERVICE_NAMES)
    assert deploy.PAUSED_STAGE_SERVICE_ENV == producer.EXPECTED_STAGE_ENVIRONMENT
    assert deploy.PAUSED_STAGE_LABELS == producer.EXPECTED_STAGE_LABELS
    assert deploy.PAUSED_STAGE_IDLE_COMMAND == producer.IDLE_COMMAND
    assert deploy.PAUSED_STAGE_SERVICE_KEYS == producer.EXPECTED_STAGE_SERVICE_KEYS
    assert deploy.PAUSED_STAGE_RESOURCES == producer.EXPECTED_STAGE_RESOURCES


def test_production_root_authorities_are_not_caller_selectable() -> None:
    lane = object.__new__(deploy.AudiobookRuntimeDeployLane)
    assert lane.root_authority_uid == 0
    assert lane.schema_v6_permit_path == deploy.DEFAULT_SCHEMA_V6_PERMIT_PATH
    assert lane.stage_owner_permit_path == deploy.DEFAULT_STAGE_OWNER_PERMIT_PATH
    assert lane.authority_lock_paths == (
        deploy.DEFAULT_SCHEMA_V6_PERMIT_LOCK_PATH,
        deploy.DEFAULT_STAGE_OWNER_PERMIT_LOCK_PATH,
    )
    parsed = deploy._parse_args([])
    assert not hasattr(parsed, "vexp_mutation_permit_lock")


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ("sentinel", "explicit_vexp_sentinel_state_path_required"),
        ("sentinel_uid", "explicit_sentinel_owner_uid_required"),
        ("evidence_uid", "explicit_evidence_owner_uid_required"),
    ],
)
def test_trust_inputs_must_be_explicit(
    tmp_path: Path, missing: str, reason: str
) -> None:
    root = _root(tmp_path)
    env = {
        "EA_DEPLOYMENT_ID": "audiobook-test-001",
        "EA_VEXP_SENTINEL_STATE_PATH": str(tmp_path / "state.json"),
        "EA_VEXP_SENTINEL_OWNER_UID": str(os.geteuid()),
        "EA_AUDIOBOOK_RUNTIME_EVIDENCE_OWNER_UID": str(os.geteuid()),
    }
    field = {
        "sentinel": "EA_VEXP_SENTINEL_STATE_PATH",
        "sentinel_uid": "EA_VEXP_SENTINEL_OWNER_UID",
        "evidence_uid": "EA_AUDIOBOOK_RUNTIME_EVIDENCE_OWNER_UID",
    }[missing]
    env.pop(field)
    with pytest.raises(deploy.DeployError, match=reason):
        deploy.AudiobookRuntimeDeployLane(root=root, env=env)


def test_evidence_paths_must_be_absolute(tmp_path: Path) -> None:
    root = _root(tmp_path)
    env = {
        "EA_DEPLOYMENT_ID": "audiobook-test-001",
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_CONFIGURATION_RECEIPT": "relative.json",
    }
    with pytest.raises(deploy.DeployError, match="receipt_path_not_absolute"):
        deploy.AudiobookRuntimeDeployLane(root=root, env=env)


def test_inert_candidate_projection_is_hard_rejected(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    _write_json(
        lane.configuration_receipt_path,
        {
            "contract_name": deploy.CANDIDATE_PREFLIGHT_CONTRACT,
            "status": "configuration_only",
            "configuration_projection": _inert_projection(),
        },
    )
    _write_json(lane.provenance_receipt_path, {"supporting_only": True})
    _write_json(lane.sbom_receipt_path, _sbom())
    with pytest.raises(
        deploy.DeployError, match="inert_candidate_configuration_forbidden"
    ):
        lane._read_evidence()


def test_unknown_production_contract_remains_blocked(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    _write_json(lane.configuration_receipt_path, {"contract_name": "invented.v1"})
    _write_json(lane.provenance_receipt_path, {})
    _write_json(lane.sbom_receipt_path, _sbom())
    with pytest.raises(
        deploy.DeployError,
        match="approved_production_configuration_contract_required",
    ):
        lane._read_evidence()


def test_exact_authorized_paused_stage_projection_is_consumed(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    payload = _production_authority(lane)
    _write_json(lane.configuration_receipt_path, payload)
    lane._read_evidence()
    assert lane.configuration_projection["preparation_valid"] is True
    assert lane.configuration_projection["stage_deploy_eligible"] is False
    assert lane.configuration_projection["stage_mutation_authority"] is False
    assert lane.configuration_projection["runtime_activation_authority"] is False
    assert lane.configuration_projection["preserved_services"] == ["ea-api"]
    assert lane.schema_v6_qualification is not None
    assert lane.stage_owner_permit_document is None


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("runtime_activation_authority", True, "authority_ambiguous"),
        ("deployment_authority", True, "authority_ambiguous"),
        ("stage_mutation_services", ["ea-api"], "projection_invalid"),
        ("memorial_compatible", False, "projection_invalid"),
    ],
)
def test_production_projection_authority_drift_fails_closed(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    payload = _production_authority(lane)
    payload["production_projection"][field] = value
    _write_json(lane.configuration_receipt_path, payload)
    with pytest.raises(deploy.DeployError, match=reason):
        lane._read_evidence()


def test_producer_preflight_must_remain_non_transferable(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    payload = _production_authority(lane)
    payload["production_projection"]["stage_mutation_authority"] = True
    _write_json(lane.configuration_receipt_path, payload)
    with pytest.raises(deploy.DeployError, match="projection_invalid"):
        lane._read_evidence()


def test_exact_root_owner_permit_binds_complete_consumer_preflight(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    _prepare_owner_permit_subject(lane)
    _write_json(
        lane.stage_owner_permit_path,
        _stage_owner_permit(lane),
        mode=0o644,
    )
    owner = deploy._read_trusted_json(
        lane.stage_owner_permit_path,
        expected_uid=os.geteuid(),
        expected_mode=0o644,
        maximum_bytes=deploy.MAX_AUTHORITY_BYTES,
        reason_prefix="test_stage_owner_permit",
    )
    assert lane.schema_v6_qualification is not None
    lane._validate_stage_owner_permit(
        owner,
        lane.configuration_projection,
        lane.schema_v6_qualification,
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("consumer_preflight_receipt_sha256", "0" * 64, "binding_mismatch"),
        ("target_compose_sha256", "0" * 64, "binding_mismatch"),
        (
            "target_compose_config_sha256",
            {service: "0" * 64 for service in deploy.WORKER_SERVICES},
            "binding_mismatch",
        ),
        ("runtime_activation_authority", True, "binding_mismatch"),
        ("preserved_services", [deploy.API_SERVICE], "binding_mismatch"),
        ("allowed_actions", ["apply_exact_paused_stage"], "binding_mismatch"),
        ("expires_at", "2026-07-20T10:31:00Z", "not_current"),
    ],
)
def test_root_owner_permit_drift_fails_before_mutation(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    lane = _lane(tmp_path)
    _prepare_owner_permit_subject(lane)
    payload = _stage_owner_permit(lane)
    payload[field] = value
    path = tmp_path / "owner-drift.json"
    _write_json(path, payload, mode=0o644)
    owner = deploy._read_trusted_json(
        path,
        expected_uid=os.geteuid(),
        expected_mode=0o644,
        maximum_bytes=deploy.MAX_AUTHORITY_BYTES,
        reason_prefix="test_stage_owner_permit",
    )
    assert lane.schema_v6_qualification is not None
    with pytest.raises(deploy.DeployError, match=reason):
        lane._validate_stage_owner_permit(
            owner,
            lane.configuration_projection,
            lane.schema_v6_qualification,
        )
    assert lane.runner.calls == []


def test_sbom_bytes_are_bound_to_projection(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    payload = _production_authority(lane)
    _write_json(
        lane.sbom_receipt_path,
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "library", "name": "replacement"}],
        },
    )
    _write_json(lane.configuration_receipt_path, payload)
    with pytest.raises(deploy.DeployError, match="provenance_contract_invalid"):
        lane._read_evidence()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            {"qualification_phase": "enforced_soak", "qualified_at": None},
            "not_terminal",
        ),
        ({"epoch_started_ms": 1}, "epoch_invalid"),
        (
            {"qualification_earliest_completion_at": "2026-07-20T09:43:55.206Z"},
            "earliest_completion_invalid",
        ),
        ({"updated_at": "2026-07-20T09:50:00Z"}, "state_stale"),
        ({"certification_blockers": ["still-soaking"]}, "resources_not_healthy"),
    ],
)
def test_schema_v6_terminal_state_fails_closed(
    tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    lane = _lane(tmp_path)
    _write_json(lane.sentinel_path, _state(**change))
    with pytest.raises(deploy.DeployError, match=reason):
        lane._read_and_validate_state()


def test_schema_v6_terminal_state_validates_exact_epoch(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    digest = _write_json(lane.sentinel_path, _state())
    assert lane._read_and_validate_state().sha256 == digest


def test_trusted_json_rejects_duplicate_keys_and_links(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"status":"allow","status":"deny"}\n')
    duplicate.chmod(0o600)
    with pytest.raises(deploy.DeployError, match="json_invalid"):
        deploy._read_trusted_json(
            duplicate,
            expected_uid=os.geteuid(),
            maximum_bytes=1024,
            reason_prefix="guard",
        )
    linked = tmp_path / "linked.json"
    os.link(duplicate, linked)
    with pytest.raises(deploy.DeployError, match="untrusted"):
        deploy._read_trusted_json(
            duplicate,
            expected_uid=os.geteuid(),
            maximum_bytes=1024,
            reason_prefix="guard",
        )


def test_issuer_lock_lease_revalidates_before_and_after(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    boundaries: list[str] = []
    lane._revalidate_authority = types.MethodType(
        lambda self, boundary: boundaries.append(boundary), lane
    )
    with lane._issuer_authority_lease("stage_workers"):
        boundaries.append("mutation")
    assert boundaries == [
        "immediately_before:stage_workers",
        "mutation",
        "immediately_after:stage_workers",
    ]


def test_issuer_lock_blocks_uncoordinated_mutation(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    descriptor = os.open(lane.authority_lock_paths[0], os.O_RDONLY)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(deploy.DeployError, match="lock_busy"):
            with lane._issuer_authority_lease("stage_workers"):
                pass
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_post_mutation_authority_failure_is_not_ignored(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    count = 0

    def revalidate(self, boundary: str) -> None:
        nonlocal count
        del self
        count += 1
        if boundary.startswith("immediately_after"):
            raise deploy.DeployError("owner_handoff_revoked")

    lane._revalidate_authority = types.MethodType(revalidate, lane)
    with pytest.raises(deploy.DeployError, match="owner_handoff_revoked"):
        with lane._issuer_authority_lease("stage_workers"):
            pass
    assert count == 2


def test_inert_overlay_can_never_be_selected_for_live_tuple(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.production_overlay_value = str(deploy.INERT_CANDIDATE_OVERLAY)
    with pytest.raises(deploy.DeployError, match="production_overlay_path_invalid"):
        lane._production_overlay()


def test_production_overlay_is_rendered_only_from_private_snapshot(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    source = lane.root / deploy.PRODUCTION_OVERLAY
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lane.configuration_projection = {"overlay_working_sha256": digest}
    lane._prepare_rollback_snapshot_directory()
    snapshot = lane._production_overlay()
    assert snapshot != source
    assert snapshot.read_bytes() == source.read_bytes()
    assert snapshot.stat().st_mode & 0o777 == 0o600
    source.write_text("services:\n  attacker:\n    image: latest\n", encoding="utf-8")
    assert snapshot.read_text(encoding="utf-8") == "services: {}\n"
    with pytest.raises(deploy.DeployError, match="projection_mismatch"):
        lane._production_overlay()
    lane._cleanup_rollback_snapshots()


def test_compose_source_inventory_uses_hermetic_raw_git_bytes(
    tmp_path: Path,
) -> None:
    blobs = {
        path.as_posix(): (f"services:\r\n  source-{index}: {{}}\r\n".encode())
        for index, path in enumerate(deploy.PRODUCTION_COMPOSE_SOURCE_PATHS)
    }
    runner = GitBlobRunner(blobs)
    lane = _lane(tmp_path, runner=runner)
    (lane.root / ".git").mkdir()
    lane.env.update(
        {
            "GIT_DIR": "/attacker/git-dir",
            "GIT_OBJECT_DIRECTORY": "/attacker/objects",
            "GIT_REPLACE_REF_BASE": "refs/evil/",
            "GIT_CONFIG_GLOBAL": "/attacker/config",
        }
    )
    for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS:
        (lane.root / relative).write_bytes(blobs[relative.as_posix()])
    assert lane._source_metadata()["source_revision"] == SOURCE
    lane.source_revision = SOURCE
    lane._capture_compose_source_inventory()
    assert [entry["blob_sha256"] for entry in lane.compose_source_inventory] == [
        hashlib.sha256(blobs[path.as_posix()]).hexdigest()
        for path in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    ]
    assert all(count == 2 for count in runner.read_counts.values())
    for command, environment in runner.calls:
        assert command[0] == str(lane._trusted_git_executable())
        assert environment["PATH"] == deploy.GIT_SAFE_PATH
        assert environment["GIT_NO_LAZY_FETCH"] == "1"
        assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert environment["GIT_ALLOW_PROTOCOL"] == ""
        assert environment["GIT_ASKPASS"] == "/bin/false"
        assert "GIT_DIR" not in environment
        assert "GIT_OBJECT_DIRECTORY" not in environment
        assert "GIT_REPLACE_REF_BASE" not in environment
        assert "TMPDIR" not in environment


def test_compose_source_inventory_rejects_final_blob_drift(
    tmp_path: Path,
) -> None:
    blobs = {
        path.as_posix(): f"services:\n  source-{index}: {{}}\n".encode()
        for index, path in enumerate(deploy.PRODUCTION_COMPOSE_SOURCE_PATHS)
    }
    drift_path = deploy.PRODUCTION_COMPOSE_SOURCE_PATHS[0].as_posix()
    runner = GitBlobRunner(blobs, drift_on_final_read=drift_path)
    lane = _lane(tmp_path, runner=runner)
    (lane.root / ".git").mkdir()
    for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS:
        (lane.root / relative).write_bytes(blobs[relative.as_posix()])
    assert lane._source_metadata()["source_revision"] == SOURCE
    lane.source_revision = SOURCE
    with pytest.raises(deploy.DeployError, match="changed_during_snapshot"):
        lane._capture_compose_source_inventory()
    assert lane.compose_source_inventory == []


def test_root_authority_open_requires_descriptor_path_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deploy,
        "_root_authority_anchor_is_trusted",
        lambda opened, current: False,
    )
    with pytest.raises(deploy.DeployError, match="root_anchor_untrusted"):
        descriptor = deploy._open_absolute_nofollow(
            Path("/etc/passwd"),
            flags=os.O_RDONLY,
            reason="root_anchor_test",
            require_root_parents=True,
        )
        os.close(descriptor)


def test_root_authority_anchor_rejects_identity_or_policy_drift() -> None:
    root = os.stat("/", follow_symlinks=False)
    trusted = types.SimpleNamespace(
        st_mode=root.st_mode,
        st_uid=0,
        st_dev=root.st_dev,
        st_ino=root.st_ino,
    )
    assert deploy._root_authority_anchor_is_trusted(trusted, trusted)
    for field, value in (
        ("st_uid", 1),
        ("st_dev", root.st_dev + 1),
        ("st_ino", root.st_ino + 1),
        ("st_mode", root.st_mode | 0o002),
    ):
        changed = types.SimpleNamespace(
            st_mode=trusted.st_mode,
            st_uid=trusted.st_uid,
            st_dev=trusted.st_dev,
            st_ino=trusted.st_ino,
        )
        setattr(changed, field, value)
        assert not deploy._root_authority_anchor_is_trusted(trusted, changed)


def test_missing_promisor_blob_fails_without_transport_or_helper(
    tmp_path: Path,
) -> None:
    class MissingBlobRunner(GitBlobRunner):
        def run_bytes(self, args, *, cwd, env, check=True):
            call = tuple(args)
            self.calls.append((call, dict(env)))
            if check:
                raise deploy.DeployError("command_failed:128:git")
            return subprocess.CompletedProcess(list(args), 128, b"", b"missing")

    blobs = {
        path.as_posix(): b"services: {}\n"
        for path in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    }
    runner = MissingBlobRunner(blobs)
    lane = _lane(tmp_path, runner=runner)
    (lane.root / ".git").mkdir()
    for relative, payload in blobs.items():
        (lane.root / relative).write_bytes(payload)
    assert lane._source_metadata()["source_revision"] == SOURCE
    lane.source_revision = SOURCE
    with pytest.raises(deploy.DeployError, match="command_failed:128:git"):
        lane._capture_compose_source_inventory()
    command, environment = runner.calls[-1]
    assert "cat-file" in command
    assert environment["GIT_NO_LAZY_FETCH"] == "1"
    assert environment["GIT_ALLOW_PROTOCOL"] == ""
    assert environment["GIT_PROTOCOL_FROM_USER"] == "0"
    assert environment["GIT_ASKPASS"] == "/bin/false"
    assert environment["GIT_SSH_COMMAND"] == "/bin/false"


def test_source_binding_rejects_replacement_refs_and_alternates(
    tmp_path: Path,
) -> None:
    blobs = {
        path.as_posix(): b"services: {}\n"
        for path in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    }

    class ReplacementRunner(GitBlobRunner):
        def run(self, args, *, cwd, env, check=True):
            result = super().run(args, cwd=cwd, env=env, check=check)
            if "for-each-ref" in tuple(args):
                return subprocess.CompletedProcess(
                    list(args), 0, "refs/replace/evil\n", ""
                )
            return result

    replacement_lane = _lane(tmp_path / "replacement", runner=ReplacementRunner(blobs))
    (replacement_lane.root / ".git").mkdir()
    with pytest.raises(deploy.DeployError, match="replace_refs_present"):
        replacement_lane._source_metadata()

    alternate_lane = _lane(tmp_path / "alternate", runner=GitBlobRunner(blobs))
    alternates = alternate_lane.root / ".git" / "objects" / "info"
    alternates.mkdir(parents=True)
    (alternates / "alternates").write_text("/attacker/objects\n", encoding="utf-8")
    with pytest.raises(deploy.DeployError, match="alternates_present"):
        alternate_lane._source_metadata()


def test_provider_queue_or_send_activation_is_rejected(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    service = _rendered_service("ea-worker")
    service["environment"]["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED"] = "1"
    with pytest.raises(deploy.DeployError, match="side_effect_not_quiescent"):
        lane._validate_rendered_service("ea-worker", service)


def test_target_preserves_api_and_requires_zero_worker_replicas(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    api = _rendered_service("ea-api")
    workers = {
        service: _rendered_service(service) for service in deploy.WORKER_SERVICES
    }
    baseline_services = {
        service: {"image": f"prior/{service}:test"}
        for service in deploy.EXPECTED_RUNTIME_SERVICES
    }
    baseline_services[deploy.API_SERVICE] = api
    baseline = {
        "name": "ea",
        "networks": {"default": {"name": "ea_default"}},
        "services": baseline_services,
        "volumes": {},
    }
    staged = copy.deepcopy(baseline)
    staged["services"].update(workers)
    staged["x-audiobook-production-stage"] = {}
    staged["x-audiobook-production-stage-service"] = {}
    payload = _production_authority(
        lane,
        rendered_sha256=deploy._canonical_sha256(staged),
        baseline_rendered_sha256=deploy._canonical_sha256(baseline),
        baseline_api_sha256=deploy._canonical_sha256(api),
    )
    _write_json(lane.configuration_receipt_path, payload)
    lane._read_evidence()
    lane.compose_source_inventory = list(
        lane.configuration_projection["compose_source_inventory"]
    )
    lane.compose_source_inventory_sha256 = lane.configuration_projection[
        "compose_source_inventory_sha256"
    ]
    lane.pre_state = {
        "services": {
            deploy.API_SERVICE: {
                "runtime": {
                    "rollback_projection_sha256": deploy._canonical_sha256(
                        lane._rendered_rollback_projection(api)
                    )
                }
            }
        }
    }
    lane.production_overlay_sha256 = OVERLAY_SHA
    target_files = (*deploy.PRODUCTION_BASE_COMPOSE_FILES, "/private/overlay.yml")
    lane._production_target_compose_files = types.MethodType(
        lambda self: target_files,
        lane,
    )
    lane._render_target = types.MethodType(
        lambda self, files: (
            baseline if tuple(files) == deploy.PRODUCTION_BASE_COMPOSE_FILES else staged
        ),
        lane,
    )
    lane._validate_target_compose()
    workers["ea-worker"]["deploy"]["replicas"] = 1
    with pytest.raises(deploy.DeployError, match="paused_stage_contract_invalid"):
        lane._validate_target_compose()


def test_paused_stage_verification_requires_exact_stopped_runtime(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    lane.target_compose_files = (
        *deploy.PRODUCTION_BASE_COMPOSE_FILES,
        str(lane.root / deploy.PRODUCTION_OVERLAY),
    )
    lane.target_compose_config_sha256 = {
        service: _compose_config_sha256(service) for service in deploy.WORKER_SERVICES
    }
    inspections = {
        service: _paused_inspection(lane, service) for service in deploy.WORKER_SERVICES
    }
    lane._inspect_container = types.MethodType(
        lambda self, service: inspections[service], lane
    )
    lane._verify_paused_stage(deploy.WORKER_SERVICES, lane.target_compose_files)
    assert set(lane.staged_worker_identities) == set(deploy.WORKER_SERVICES)
    assert lane.receipt["paused_stage"]["status"] == "created_not_started"
    assert lane.receipt["paused_stage"]["runtime_activation_authority"] is False


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (("State", "Running", True), "not_inert"),
        (("Config", "Image", "attacker/latest"), "identity_mismatch"),
        (
            (
                "Config",
                "Env",
                ["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED=1"],
            ),
            "side_effect_posture_invalid",
        ),
        (("HostConfig", "Privileged", True), "runtime_contract_invalid"),
        (
            (
                "Mounts",
                None,
                [
                    {
                        "Type": "bind",
                        "Source": "/private/source",
                        "Destination": "/host",
                        "RW": False,
                    }
                ],
            ),
            "runtime_contract_invalid",
        ),
    ],
)
def test_paused_stage_runtime_drift_fails_closed(
    tmp_path: Path,
    change: tuple[str, str | None, object],
    reason: str,
) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    lane.target_compose_files = (
        *deploy.PRODUCTION_BASE_COMPOSE_FILES,
        str(lane.root / deploy.PRODUCTION_OVERLAY),
    )
    lane.target_compose_config_sha256 = {
        service: _compose_config_sha256(service) for service in deploy.WORKER_SERVICES
    }
    inspections = {
        service: _paused_inspection(lane, service) for service in deploy.WORKER_SERVICES
    }
    section, field, value = change
    if field is None:
        inspections["ea-worker"][section] = value
    else:
        inspections["ea-worker"][section][field] = value
    lane._inspect_container = types.MethodType(
        lambda self, service: inspections[service], lane
    )
    with pytest.raises(deploy.DeployError, match=reason):
        lane._verify_paused_stage(deploy.WORKER_SERVICES, lane.target_compose_files)


@pytest.mark.parametrize("drift", ("blkio_weight", "mount_propagation"))
def test_rollback_contract_and_projection_detect_restorable_host_drift(
    tmp_path: Path, drift: str
) -> None:
    lane = _lane(tmp_path)
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    lane.target_compose_config_sha256 = {
        "ea-worker": _compose_config_sha256("ea-worker")
    }
    baseline = _paused_inspection(lane, "ea-worker")
    changed = copy.deepcopy(baseline)
    rendered = _rendered_service("ea-worker")
    if drift == "blkio_weight":
        baseline["HostConfig"]["BlkioWeight"] = 0
        changed["HostConfig"]["BlkioWeight"] = 500
    else:
        mount = {
            "Type": "bind",
            "Source": "/private/source",
            "Destination": "/data",
            "Driver": "",
            "Mode": "rw",
            "RW": True,
            "Propagation": "rprivate",
        }
        baseline["Mounts"] = [mount]
        changed["Mounts"] = [{**mount, "Propagation": "rshared"}]
    baseline_digest = deploy._canonical_sha256(
        lane._inspection_restorable_contract(baseline)
    )
    changed_digest = deploy._canonical_sha256(
        lane._inspection_restorable_contract(changed)
    )
    assert changed_digest != baseline_digest
    assert not lane._rendered_rollback_matches_live(
        lane._rendered_rollback_projection(rendered),
        lane._inspection_rollback_projection(changed),
    )


def test_rollback_contract_rejects_unknown_host_or_mount_fields(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    lane.target_compose_config_sha256 = {
        "ea-worker": _compose_config_sha256("ea-worker")
    }
    inspection = _paused_inspection(lane, "ea-worker")
    inspection["HostConfig"]["FutureMutableField"] = True
    with pytest.raises(deploy.DeployError, match="host_config_field_unsupported"):
        lane._inspection_restorable_contract(inspection)
    inspection["HostConfig"].pop("FutureMutableField")
    inspection["Mounts"] = [
        {
            "Type": "bind",
            "Source": "/private/source",
            "Destination": "/data",
            "RW": True,
            "FutureMountOption": "unsafe",
        }
    ]
    with pytest.raises(deploy.DeployError, match="mount_field_unsupported"):
        lane._inspection_restorable_contract(inspection)


def test_restorable_contract_rejects_unknown_config_and_network_collisions(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    lane.target_compose_config_sha256 = {
        "ea-worker": _compose_config_sha256("ea-worker")
    }
    baseline = _paused_inspection(lane, "ea-worker")
    baseline["Config"]["MacAddress"] = "02:42:ac:14:00:05"
    endpoint = baseline["NetworkSettings"]["Networks"]["ea_default"]
    endpoint.update(
        {
            "Aliases": ["ea-worker", "worker"],
            "DNSNames": ["ea-worker"],
            "DriverOpts": {"com.example.mode": "safe"},
            "EndpointID": "endpoint-safe",
            "Gateway": "172.20.0.1",
            "IPAMConfig": {
                "IPv4Address": "172.20.0.5",
                "IPv6Address": "fd00::5",
                "LinkLocalIPs": ["169.254.20.5"],
            },
            "IPAddress": "172.20.0.5",
            "IPPrefixLen": 16,
            "IPv6Gateway": "fd00::1",
            "MacAddress": "02:42:ac:14:00:05",
            "NetworkID": "network-safe",
        }
    )
    baseline_rendered = _rendered_service("ea-worker")
    baseline_rendered["networks"] = {"default": {"mac_address": "02:42:ac:14:00:05"}}
    baseline_requested = lane._rendered_network_endpoint_contract(baseline_rendered)
    baseline_sha256 = deploy._canonical_sha256(
        lane._inspection_restorable_contract(baseline, baseline_requested)
    )
    mutations = (
        ("Aliases", ["attacker"]),
        ("DriverOpts", {"com.example.mode": "unsafe"}),
        ("GwPriority", 10),
        (
            "IPAMConfig",
            {
                "IPv4Address": "172.20.0.99",
                "IPv6Address": "fd00::63",
                "LinkLocalIPs": ["169.254.20.99"],
            },
        ),
    )
    for field, value in mutations:
        changed = copy.deepcopy(baseline)
        changed["NetworkSettings"]["Networks"]["ea_default"][field] = value
        assert (
            deploy._canonical_sha256(
                lane._inspection_restorable_contract(changed, baseline_requested)
            )
            != baseline_sha256
        )

    explicit_mac_changed = copy.deepcopy(baseline)
    explicit_mac_changed["Config"]["MacAddress"] = "02:42:ac:14:00:63"
    explicit_mac_changed["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = (
        "02:42:ac:14:00:63"
    )
    changed_rendered = copy.deepcopy(baseline_rendered)
    changed_rendered["networks"]["default"]["mac_address"] = "02:42:ac:14:00:63"
    changed_requested = lane._rendered_network_endpoint_contract(changed_rendered)
    assert (
        deploy._canonical_sha256(
            lane._inspection_restorable_contract(
                explicit_mac_changed, changed_requested
            )
        )
        != baseline_sha256
    )

    volatile = copy.deepcopy(baseline)
    volatile["Id"] = "replacement-container-id"
    volatile_endpoint = volatile["NetworkSettings"]["Networks"]["ea_default"]
    volatile_endpoint.update(
        {
            "DNSNames": ["ea-worker", "replacement-container-id"],
            "EndpointID": "replacement-endpoint-id",
            "Gateway": "172.20.0.254",
            "IPAddress": "172.20.0.99",
            "IPPrefixLen": 24,
            "NetworkID": "replacement-network-id",
        }
    )
    assert (
        deploy._canonical_sha256(
            lane._inspection_restorable_contract(volatile, baseline_requested)
        )
        == baseline_sha256
    )

    dynamic = copy.deepcopy(baseline)
    dynamic["Config"]["MacAddress"] = ""
    dynamic_endpoint = dynamic["NetworkSettings"]["Networks"]["ea_default"]
    dynamic_endpoint["IPAMConfig"] = {}
    dynamic_requested = lane._rendered_network_endpoint_contract(
        _rendered_service("ea-worker")
    )
    dynamic_sha256 = deploy._canonical_sha256(
        lane._inspection_restorable_contract(dynamic, dynamic_requested)
    )
    dynamic_endpoint.update(
        {
            "DNSNames": ["ea-worker", "new-container-id"],
            "EndpointID": "new-endpoint-id",
            "IPAddress": "172.20.0.77",
            "MacAddress": "02:42:ac:14:00:4d",
        }
    )
    assert (
        deploy._canonical_sha256(
            lane._inspection_restorable_contract(dynamic, dynamic_requested)
        )
        == dynamic_sha256
    )

    unknown_config = copy.deepcopy(baseline)
    unknown_config["Config"]["FutureMutableRuntimeField"] = True
    with pytest.raises(deploy.DeployError, match="config_field_unsupported"):
        lane._inspection_restorable_contract(unknown_config)

    unknown_endpoint = copy.deepcopy(baseline)
    unknown_endpoint["NetworkSettings"]["Networks"]["ea_default"][
        "FutureEndpointField"
    ] = True
    with pytest.raises(deploy.DeployError, match="endpoint_field_unsupported"):
        lane._inspection_restorable_contract(unknown_endpoint)

    unknown_ipam = copy.deepcopy(baseline)
    unknown_ipam["NetworkSettings"]["Networks"]["ea_default"]["IPAMConfig"][
        "FutureIPAMField"
    ] = True
    with pytest.raises(deploy.DeployError, match="ipam_field_unsupported"):
        lane._inspection_restorable_contract(unknown_ipam)


def test_rollback_accepts_volatile_endpoint_recreation_but_rejects_requested_drift(
    tmp_path: Path,
) -> None:
    service = deploy.WORKER_SERVICES[0]
    runner = RenderRunner({})
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    lane.target_compose_config_sha256 = {service: _compose_config_sha256(service)}
    baseline = _paused_inspection(lane, service)
    baseline_endpoint = baseline["NetworkSettings"]["Networks"]["ea_default"]
    baseline_endpoint.update(
        {
            "Aliases": [service, "audiobook-worker"],
            "DNSNames": [service, baseline["Id"]],
            "DriverOpts": {"com.example.mode": "safe"},
            "EndpointID": "old-endpoint-id",
            "IPAMConfig": {},
            "IPAddress": "172.20.0.5",
            "MacAddress": "02:42:ac:14:00:05",
        }
    )
    dynamic_requested = lane._rendered_network_endpoint_contract(
        _rendered_service(service)
    )
    baseline_sha256 = deploy._canonical_sha256(
        lane._inspection_restorable_contract(baseline, dynamic_requested)
    )
    recreated = copy.deepcopy(baseline)
    recreated["Id"] = "replacement-container-id"
    recreated_endpoint = recreated["NetworkSettings"]["Networks"]["ea_default"]
    recreated_endpoint.update(
        {
            "DNSNames": [service, "replacement-container-id"],
            "EndpointID": "replacement-endpoint-id",
            "IPAddress": "172.20.0.88",
            "MacAddress": "02:42:ac:14:00:58",
        }
    )
    assert (
        deploy._canonical_sha256(
            lane._inspection_restorable_contract(recreated, dynamic_requested)
        )
        == baseline_sha256
    )

    requested_drifts: list[dict[str, Any]] = []
    for field, value in (
        ("Aliases", [service, "changed-alias"]),
        ("DriverOpts", {"com.example.mode": "unsafe"}),
        ("IPAMConfig", {"IPv4Address": "172.20.0.88"}),
    ):
        changed = copy.deepcopy(recreated)
        changed["NetworkSettings"]["Networks"]["ea_default"][field] = value
        requested_drifts.append(changed)
    explicit_mac = copy.deepcopy(recreated)
    explicit_mac["Config"]["MacAddress"] = "02:42:ac:14:00:63"
    explicit_mac["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = (
        "02:42:ac:14:00:63"
    )
    explicit_rendered = _rendered_service(service)
    explicit_rendered["networks"] = {"default": {"mac_address": "02:42:ac:14:00:63"}}
    explicit_requested = lane._rendered_network_endpoint_contract(explicit_rendered)
    assert all(
        deploy._canonical_sha256(
            lane._inspection_restorable_contract(changed, dynamic_requested)
        )
        != baseline_sha256
        for changed in requested_drifts
    )
    assert (
        deploy._canonical_sha256(
            lane._inspection_restorable_contract(explicit_mac, explicit_requested)
        )
        != baseline_sha256
    )

    rendered_file = lane.root / "network-rollback.json"
    rendered_file.write_text('{"services":{}}\n', encoding="utf-8")
    env_file = lane.root / ".env"
    manifest_file = lane.root / "network-rollback.topology.json"
    manifest_sha256 = _write_json(
        manifest_file,
        {"contract_name": deploy.ACTIVE_TOPOLOGY_CONTRACT},
    )
    lane.rollback_plans = {
        service: {
            "working_dir": str(lane.root),
            "rendered_file": str(rendered_file),
            "rendered_sha256": hashlib.sha256(rendered_file.read_bytes()).hexdigest(),
            "env_file": str(env_file),
            "env_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
            "topology_manifest_file": str(manifest_file),
            "topology_manifest_sha256": manifest_sha256,
            "compose_config_sha256": {service: _compose_config_sha256(service)},
        }
    }
    lane.pre_state = {
        "services": {
            service: {
                "runtime": {
                    "lifecycle": "running",
                    "restorable_contract_sha256": baseline_sha256,
                }
            }
        }
    }
    current_inspection = recreated
    lane._retag_prior_reference = types.MethodType(lambda self, selected: None, lane)
    lane._wait_ready = types.MethodType(lambda self, services: None, lane)
    lane._inspect_container = types.MethodType(
        lambda self, selected: current_inspection, lane
    )
    lane._container_identity = types.MethodType(
        lambda self, inspection, selected: {
            "runtime": {
                "lifecycle": "running",
                "restorable_contract_sha256": deploy._canonical_sha256(
                    self._inspection_restorable_contract(inspection, dynamic_requested)
                ),
            }
        },
        lane,
    )
    lane._verify_rollback_active_topology = types.MethodType(
        lambda self, **kwargs: None, lane
    )

    lane._rollback_services((service,))
    current_inspection = requested_drifts[0]
    with pytest.raises(deploy.DeployError, match="recovery_incomplete"):
        lane._rollback_services((service,))


def test_network_mac_contract_binds_modern_endpoint_request_from_render(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    lane.target_compose_config_sha256 = {
        "ea-worker": _compose_config_sha256("ea-worker")
    }
    inspection = _paused_inspection(lane, "ea-worker")
    inspection["Config"]["MacAddress"] = ""
    inspection["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = (
        "02:42:AC:14:00:17"
    )
    rendered = _rendered_service("ea-worker")
    rendered["networks"] = {"default": {"mac_address": "02:42:ac:14:00:17"}}
    requested = lane._rendered_network_endpoint_contract(rendered)

    contract = lane._network_endpoint_contract(inspection, requested)

    assert contract["default"]["MacAddress"] == "02:42:ac:14:00:17"
    assert contract["default"]["MacAddressSource"] == "network"
    assert lane._rendered_rollback_matches_live(
        lane._rendered_rollback_projection(rendered),
        lane._inspection_rollback_projection(inspection, requested),
    )


def test_network_mac_contract_accepts_unambiguous_legacy_global_request(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    lane.target_compose_config_sha256 = {
        "ea-worker": _compose_config_sha256("ea-worker")
    }
    inspection = _paused_inspection(lane, "ea-worker")
    inspection["Config"]["MacAddress"] = "02:42:AC:14:00:17"
    inspection["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = ""
    rendered = _rendered_service("ea-worker")
    rendered["mac_address"] = "02:42:ac:14:00:17"
    requested = lane._rendered_network_endpoint_contract(rendered)

    contract = lane._network_endpoint_contract(inspection, requested)

    assert contract["default"]["MacAddress"] == "02:42:ac:14:00:17"
    assert contract["default"]["MacAddressSource"] == "global"
    assert lane._rendered_rollback_matches_live(
        lane._rendered_rollback_projection(rendered),
        lane._inspection_rollback_projection(inspection, requested),
    )

    cross_shape_rendered = _rendered_service("ea-worker")
    cross_shape_rendered["networks"] = {"default": {"mac_address": "02:42:ac:14:00:17"}}
    cross_shape_requested = lane._rendered_network_endpoint_contract(
        cross_shape_rendered
    )
    cross_shape_contract = lane._network_endpoint_contract(
        inspection, cross_shape_requested
    )
    assert cross_shape_contract["default"]["MacAddress"] == ("02:42:ac:14:00:17")
    assert cross_shape_contract["default"]["MacAddressSource"] == "network"
    assert lane._rendered_rollback_matches_live(
        lane._rendered_rollback_projection(cross_shape_rendered),
        lane._inspection_rollback_projection(inspection, cross_shape_requested),
    )


def test_rollback_recreate_retains_legacy_config_for_per_network_mac_request(
    tmp_path: Path,
) -> None:
    service = deploy.WORKER_SERVICES[0]
    runner = RenderRunner({})
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    lane.target_compose_config_sha256 = {service: _compose_config_sha256(service)}
    inspection = _paused_inspection(lane, service)
    inspection["Config"]["MacAddress"] = "02:42:ac:14:00:17"
    inspection["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = ""
    rendered = _rendered_service(service)
    rendered["networks"] = {"default": {"mac_address": "02:42:ac:14:00:17"}}
    requested = lane._rendered_network_endpoint_contract(rendered)
    expected_sha256 = deploy._canonical_sha256(
        lane._inspection_restorable_contract(inspection, requested)
    )
    rendered_file = lane.root / "legacy-cross-shape-rollback.json"
    rendered_file.write_text(' {"services": {}}\n', encoding="utf-8")
    env_file = lane.root / ".env"
    manifest_file = lane.root / "legacy-cross-shape-rollback.topology.json"
    manifest_sha256 = _write_json(
        manifest_file,
        {"contract_name": deploy.ACTIVE_TOPOLOGY_CONTRACT},
    )
    lane.rollback_plans = {
        service: {
            "working_dir": str(lane.root),
            "rendered_file": str(rendered_file),
            "rendered_sha256": hashlib.sha256(rendered_file.read_bytes()).hexdigest(),
            "env_file": str(env_file),
            "env_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
            "topology_manifest_file": str(manifest_file),
            "topology_manifest_sha256": manifest_sha256,
            "compose_config_sha256": {service: _compose_config_sha256(service)},
        }
    }
    lane.pre_state = {
        "services": {
            service: {
                "runtime": {
                    "lifecycle": "running",
                    "restorable_contract_sha256": expected_sha256,
                },
                "requested_network_endpoints": requested,
            }
        }
    }
    observed_requests: list[Mapping[str, Mapping[str, Any]]] = []

    def identity(
        self: deploy.AudiobookRuntimeDeployLane,
        current: Mapping[str, Any],
        selected: str,
        requested_network_endpoints: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        assert selected == service
        assert requested_network_endpoints is not None
        observed_requests.append(requested_network_endpoints)
        return {
            "runtime": {
                "lifecycle": "running",
                "restorable_contract_sha256": deploy._canonical_sha256(
                    self._inspection_restorable_contract(
                        current, requested_network_endpoints
                    )
                ),
            }
        }

    lane._retag_prior_reference = types.MethodType(lambda self, selected: None, lane)
    lane._wait_ready = types.MethodType(lambda self, services: None, lane)
    lane._inspect_container = types.MethodType(
        lambda self, selected: inspection,
        lane,
    )
    lane._container_identity = types.MethodType(identity, lane)
    lane._verify_rollback_active_topology = types.MethodType(
        lambda self, **kwargs: None,
        lane,
    )

    lane._rollback_services((service,))

    assert observed_requests == [requested]
    assert any("up" in call and service in call for call in runner.calls)


def test_network_mac_contract_rejects_conflict_missing_and_global_ambiguity(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    lane.target_compose_config_sha256 = {
        "ea-worker": _compose_config_sha256("ea-worker")
    }
    rendered = _rendered_service("ea-worker")
    rendered["networks"] = {"default": {"mac_address": "02:42:ac:14:00:17"}}
    requested = lane._rendered_network_endpoint_contract(rendered)

    conflict = _paused_inspection(lane, "ea-worker")
    conflict["Config"]["MacAddress"] = ""
    conflict["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = (
        "02:42:ac:14:00:18"
    )
    with pytest.raises(deploy.DeployError, match="network_mac_render_conflict"):
        lane._network_endpoint_contract(conflict, requested)

    missing = _paused_inspection(lane, "ea-worker")
    missing["Config"]["MacAddress"] = ""
    missing["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = ""
    with pytest.raises(deploy.DeployError, match="network_requested_mac_missing"):
        lane._network_endpoint_contract(missing, requested)

    ambiguous = _paused_inspection(lane, "ea-worker")
    ambiguous["Config"]["MacAddress"] = "02:42:ac:14:00:17"
    ambiguous["NetworkSettings"]["Networks"] = {
        "ea_default": {"MacAddress": "02:42:ac:14:00:17"},
        "ea_secondary": {"MacAddress": "02:42:ac:14:00:18"},
    }
    ambiguous_rendered = _rendered_service("ea-worker")
    ambiguous_rendered["networks"] = {
        "default": {"mac_address": "02:42:ac:14:00:17"},
        "secondary": {"mac_address": "02:42:ac:14:00:18"},
    }
    ambiguous_requested = lane._rendered_network_endpoint_contract(ambiguous_rendered)
    with pytest.raises(deploy.DeployError, match="network_global_mac_ambiguous"):
        lane._network_endpoint_contract(ambiguous, ambiguous_requested)


def _prepare_snapshot_state(lane: deploy.AudiobookRuntimeDeployLane) -> dict[str, Any]:
    compose_file = lane.root / "prior.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    compose_sha = hashlib.sha256(compose_file.read_bytes()).hexdigest()
    env_sha = hashlib.sha256((lane.root / ".env").read_bytes()).hexdigest()
    services: dict[str, Any] = {}
    for service in deploy.TARGET_SERVICES:
        rendered = _rendered_service(service)
        rollback_projection = lane._rendered_rollback_projection(rendered)
        services[service] = {
            "topology": {
                "working_dir": str(lane.root),
                "compose_files": [str(compose_file)],
                "compose_inputs": [{"name": compose_file.name, "sha256": compose_sha}],
                "compose_config_sha256": _compose_config_sha256(service),
                "env_file": str(lane.root / ".env"),
                "env_sha256": env_sha,
            },
            "runtime": {
                "image_id": IMAGE_ID,
                "image_reference": IMAGE_REFERENCE,
                "rollback_projection_sha256": deploy._canonical_sha256(
                    rollback_projection
                ),
                "restorable_contract_sha256": hashlib.sha256(
                    f"restorable:{service}".encode()
                ).hexdigest(),
            },
            "rollback_projection": rollback_projection,
            "identity_sha256": hashlib.sha256(service.encode()).hexdigest(),
        }
    lane.pre_state = {"services": services}
    return {
        "services": {name: _rendered_service(name) for name in deploy.TARGET_SERVICES}
    }


def _bind_explicit_network_endpoint_prestate(
    lane: deploy.AudiobookRuntimeDeployLane,
    service: str,
) -> dict[str, Any]:
    lane.target_compose_config_sha256.setdefault(
        service, _compose_config_sha256(service)
    )
    inspection = _paused_inspection(lane, service)
    container_id = str(inspection["Id"])
    configured_mac = "02:42:ac:1f:00:17"
    inspection["Config"]["MacAddress"] = ""
    inspection["NetworkSettings"]["Networks"]["ea_default"] = {
        "Aliases": [service, container_id[:12], "must-preserve-alias"],
        "DriverOpts": {"com.example.endpoint-mode": "governed"},
        "GwPriority": 7,
        "IPAMConfig": {
            "IPv4Address": "172.31.0.23",
            "IPv6Address": "fd00::23",
            "LinkLocalIPs": ["169.254.23.1", "fe80::23"],
        },
        "Links": ["database:db"],
        "MacAddress": configured_mac,
    }
    requested_service = _rendered_service(service)
    _render_explicit_network_endpoint(requested_service)
    requested = lane._rendered_network_endpoint_contract(requested_service)
    endpoint_contract = lane._network_endpoint_contract(inspection, requested)
    assert endpoint_contract == {
        "default": {
            "Aliases": ["must-preserve-alias"],
            "DriverOpts": {"com.example.endpoint-mode": "governed"},
            "GwPriority": 7,
            "IPAMConfig": {
                "IPv4Address": "172.31.0.23",
                "IPv6Address": "fd00::23",
                "LinkLocalIPs": ["169.254.23.1", "fe80::23"],
            },
            "Links": ["database:db"],
            "MacAddress": configured_mac,
            "MacAddressSource": "network",
        }
    }
    entry = lane.pre_state["services"][service]
    live_projection = copy.deepcopy(entry["rollback_projection"])
    live_projection["security"]["network_endpoints"] = endpoint_contract
    entry["rollback_projection"] = live_projection
    entry["runtime"]["rollback_projection_sha256"] = deploy._canonical_sha256(
        live_projection
    )
    entry["runtime"]["restorable_contract_sha256"] = deploy._canonical_sha256(
        lane._inspection_restorable_contract(inspection, requested)
    )
    entry["requested_network_endpoints"] = requested
    return inspection


def _render_explicit_network_endpoint(service: dict[str, Any]) -> None:
    service["networks"] = {
        "default": {
            "aliases": ["must-preserve-alias"],
            "driver_opts": {"com.example.endpoint-mode": "governed"},
            "gw_priority": 7,
            "ipv4_address": "172.31.0.23",
            "ipv6_address": "fd00::23",
            "link_local_ips": ["169.254.23.1", "fe80::23"],
            "mac_address": "02:42:ac:1f:00:17",
        }
    }
    service["links"] = ["database:db"]


def _prepare_forward_snapshot_lane(
    tmp_path: Path,
) -> tuple[deploy.AudiobookRuntimeDeployLane, RenderRunner, dict[str, Any]]:
    rendered = {
        "services": {name: _rendered_service(name) for name in deploy.TARGET_SERVICES}
    }
    runner = RenderRunner(rendered)
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    lane.compose_source_inventory = [
        {
            "path": relative.as_posix(),
            "working_sha256": hashlib.sha256(
                (lane.root / relative).read_bytes()
            ).hexdigest(),
        }
        for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    ]
    lane.target_compose_files = tuple(
        str((lane.root / relative).resolve())
        for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    )
    lane.target_compose_sha256 = deploy._canonical_sha256(rendered)
    lane.target_compose_config_sha256 = {
        service: _compose_config_sha256(service) for service in deploy.WORKER_SERVICES
    }
    lane._prepare_rollback_snapshot_directory()
    lane._prepare_forward_input_plan()
    lane._capture_forward_topology_inputs()
    return lane, runner, rendered


def test_forward_create_uses_private_snapshots_after_transient_live_edit_restore(
    tmp_path: Path,
) -> None:
    lane, runner, _rendered = _prepare_forward_snapshot_lane(tmp_path)
    snapshot_bytes = {
        path: Path(path).read_bytes() for path in lane.forward_compose_files
    }
    live_source = lane.root / deploy.PRODUCTION_COMPOSE_SOURCE_PATHS[0]
    original = live_source.read_bytes()
    live_source.write_text(
        "services:\n  attacker:\n    image: attacker/latest\n    privileged: true\n",
        encoding="utf-8",
    )
    live_source.write_bytes(original)

    lane._revalidate_forward_topology_inputs()
    runner.calls.clear()
    lane._target_create_paused(
        lane.forward_compose_files,
        deploy.WORKER_SERVICES,
        env_file=lane.forward_env_path,
    )

    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert "--no-deps" in call
    assert "--pull" in call and call[call.index("--pull") + 1] == "never"
    assert "--no-build" in call
    assert call[call.index("--env-file") + 1] == str(lane.forward_env_path)
    live_paths = {
        str((lane.root / relative).resolve())
        for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    }
    assert live_paths.isdisjoint(call)
    assert str((lane.root / ".env").resolve()) not in call
    assert all(Path(path).read_bytes() == raw for path, raw in snapshot_bytes.items())
    assert all(
        Path(path).stat().st_mode & 0o777 == 0o600
        for path in (
            *lane.forward_compose_files,
            str(lane.forward_env_path),
            str(lane.forward_topology_manifest_path),
        )
    )


def test_active_forward_topology_is_retained_and_reproduced_by_next_preflight(
    tmp_path: Path,
) -> None:
    lane, _runner, rendered = _prepare_forward_snapshot_lane(tmp_path)
    lane.target_compose_files = lane.forward_compose_files
    inspections = {
        service: _paused_inspection(lane, service) for service in deploy.WORKER_SERVICES
    }
    lane._inspect_container = types.MethodType(
        lambda self, service: inspections[service], lane
    )
    lane._activate_forward_topology_inputs()
    assert lane.retain_active_topology_inputs is True
    assert lane.rollback_snapshot_dir.is_dir()
    assert lane.receipt["active_topology"]["manifest_sha256"] == (
        lane.forward_topology_manifest_sha256
    )

    next_runner = RenderRunner(rendered)
    next_lane = _lane(tmp_path, runner=next_runner)
    next_lane.compose_bin = ("docker", "compose")
    next_lane.source_revision = SOURCE
    next_lane.candidate_reference = IMAGE_REFERENCE
    next_lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    next_lane.target_compose_files = lane.forward_compose_files
    next_lane.target_compose_config_sha256 = dict(lane.target_compose_config_sha256)
    next_lane.rollback_snapshot_dir = (
        next_lane.receipt_dir / "audiobook-test-next.active-topology"
    )
    next_inspections = {
        service: _paused_inspection(next_lane, service)
        for service in deploy.WORKER_SERVICES
    }
    for service in deploy.PRESERVED_RUNTIME_SERVICES:
        inspection = copy.deepcopy(next_inspections[deploy.WORKER_SERVICES[0]])
        inspection["Id"] = hashlib.sha256(f"container:{service}".encode()).hexdigest()
        labels = inspection["Config"]["Labels"]
        labels["com.docker.compose.service"] = service
        labels["com.docker.compose.project.config_files"] = str(
            (next_lane.root / deploy.PRODUCTION_BASE_COMPOSE_FILES[0]).resolve()
        )
        labels["com.docker.compose.config-hash"] = _compose_config_sha256(service)
        environment = [f"EA_SOURCE_REVISION={SOURCE}"]
        if service == deploy.API_SERVICE:
            environment.append("EA_DEPLOY_PRIMARY_MODE=MEMORIAL")
        inspection["Config"]["Env"] = environment
        inspection["State"].update(
            {"Status": "running", "Running": True, "Paused": False}
        )
        next_inspections[service] = inspection
    next_lane._inspect_container = types.MethodType(
        lambda self, service, **kwargs: next_inspections[service], next_lane
    )
    next_lane._capture_pre_state()
    retained_env = lane.forward_env_path.read_bytes()
    (next_lane.root / ".env").write_text("ATTACKER_DRIFT=1\n", encoding="utf-8")
    next_lane._snapshot_and_validate_rollback_inputs()

    assert {
        identity["topology"]["topology_manifest_sha256"]
        for service, identity in next_lane.pre_state["services"].items()
        if service in deploy.WORKER_SERVICES
    } == {lane.forward_topology_manifest_sha256}
    assert {
        identity["runtime"]["lifecycle"]
        for service, identity in next_lane.pre_state["services"].items()
        if service in deploy.WORKER_SERVICES
    } == {"non_running"}
    assert all(
        Path(plan["env_file"]).read_bytes() == retained_env
        for plan in next_lane.rollback_plans.values()
    )
    assert all(
        Path(plan["env_file"]).resolve() != (next_lane.root / ".env").resolve()
        for plan in next_lane.rollback_plans.values()
    )
    assert lane.rollback_snapshot_dir.is_dir()


def test_rollback_uses_private_immutable_render_and_pull_never(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    rendered = _prepare_snapshot_state(lane)
    runner = RenderRunner(rendered)
    lane.runner = runner
    lane.compose_bin = ("docker", "compose")
    lane._snapshot_and_validate_rollback_inputs()
    hash_calls = [call for call in runner.calls if "--hash" in call]
    assert [call[call.index("--hash") + 1] for call in hash_calls] == list(
        deploy.WORKER_SERVICES
    )
    expected_hashes = {
        service: _compose_config_sha256(service) for service in deploy.WORKER_SERVICES
    }
    assert (
        lane.receipt["rollback_plan"]["plans"]["plan-00"]["compose_config_sha256"]
        == expected_hashes
    )
    assert lane.receipt["rollback_plan"]["plans"]["plan-00"][
        "restorable_contract_sha256"
    ] == {
        service: lane.pre_state["services"][service]["runtime"][
            "restorable_contract_sha256"
        ]
        for service in deploy.WORKER_SERVICES
    }
    original = lane.root / "prior.yml"
    original.write_text(
        "services:\n  ea-worker:\n    image: attacker/latest\n    privileged: true\n",
        encoding="utf-8",
    )
    lane._retag_prior_reference = types.MethodType(lambda self, service: None, lane)
    lane._wait_ready = types.MethodType(lambda self, services: None, lane)
    lane._inspect_container = types.MethodType(lambda self, service: {}, lane)
    lane._container_identity = types.MethodType(
        lambda self, inspection, service: {
            "runtime": {
                "restorable_contract_sha256": self.pre_state["services"][service][
                    "runtime"
                ]["restorable_contract_sha256"]
            }
        },
        lane,
    )
    lane._verify_rollback_active_topology = types.MethodType(
        lambda self, **kwargs: None, lane
    )
    lane._rollback_services(("ea-worker",))
    rollback_call = runner.calls[-1]
    assert "--pull" in rollback_call
    assert rollback_call[rollback_call.index("--pull") + 1] == "never"
    assert any(value.endswith(".rendered.json") for value in rollback_call)
    assert str(original) not in rollback_call
    assert all(
        path.stat().st_mode & 0o777 == 0o600 for path in lane.rollback_snapshot_paths
    )
    lane._cleanup_rollback_snapshots()
    assert not lane.rollback_snapshot_dir.exists()


def test_rollback_preserves_mixed_running_nonrunning_and_absent_worker_states(
    tmp_path: Path,
) -> None:
    running_service, nonrunning_service, absent_service = deploy.WORKER_SERVICES

    class MixedStateRunner(RenderRunner):
        def __init__(self) -> None:
            super().__init__({})
            self.absent_present = True
            self.absent_inspection: dict[str, Any] = {}

        def run(self, args, *, cwd, env, check=True):
            call = tuple(args)
            if call[:2] == ("docker", "inspect"):
                self.calls.append(call)
                service = call[-1]
                if service == absent_service:
                    if self.absent_present:
                        return subprocess.CompletedProcess(
                            list(args), 0, json.dumps([self.absent_inspection]), ""
                        )
                    return subprocess.CompletedProcess(list(args), 1, "[]", "missing")
                return subprocess.CompletedProcess(
                    list(args), 0, json.dumps([{"service": service}]), ""
                )
            if call == ("docker", "rm", "--force", absent_service):
                self.calls.append(call)
                self.absent_present = False
                return subprocess.CompletedProcess(list(args), 0, absent_service, "")
            return super().run(args, cwd=cwd, env=env, check=check)

    runner = MixedStateRunner()
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    lane.target_compose_files = tuple(
        str((lane.root / relative).resolve())
        for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    )
    lane.target_compose_config_sha256 = {
        service: _compose_config_sha256(service) for service in deploy.WORKER_SERVICES
    }
    runner.absent_inspection = _paused_inspection(lane, absent_service)

    rendered_file = lane.root / "mixed-rollback.json"
    rendered_file.write_text('{"services":{}}\n', encoding="utf-8")
    env_file = lane.root / ".env"
    topology_manifest_file = lane.root / "mixed-rollback.topology.json"
    topology_manifest_sha256 = _write_json(
        topology_manifest_file,
        {"contract_name": deploy.ACTIVE_TOPOLOGY_CONTRACT},
    )
    for service in (running_service, nonrunning_service):
        lane.rollback_plans[service] = {
            "working_dir": str(lane.root),
            "rendered_file": str(rendered_file),
            "rendered_sha256": hashlib.sha256(rendered_file.read_bytes()).hexdigest(),
            "env_file": str(env_file),
            "env_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
            "topology_manifest_file": str(topology_manifest_file),
            "topology_manifest_sha256": topology_manifest_sha256,
            "compose_config_sha256": {service: _compose_config_sha256(service)},
        }
    lane.pre_state = {
        "services": {
            running_service: {
                "runtime": {
                    "lifecycle": "running",
                    "restorable_contract_sha256": "1" * 64,
                }
            },
            nonrunning_service: {
                "runtime": {
                    "lifecycle": "non_running",
                    "restorable_contract_sha256": "2" * 64,
                }
            },
            absent_service: {"runtime": {"lifecycle": "absent"}},
        }
    }
    lane._retag_prior_reference = types.MethodType(lambda self, service: None, lane)
    waited: list[tuple[str, ...]] = []
    lane._wait_ready = types.MethodType(
        lambda self, services: waited.append(tuple(services)), lane
    )
    lane._container_identity = types.MethodType(
        lambda self, inspection, service: {
            "runtime": dict(self.pre_state["services"][service]["runtime"])
        },
        lane,
    )
    lane._verify_rollback_active_topology = types.MethodType(
        lambda self, **kwargs: None, lane
    )

    lane._rollback_services(deploy.WORKER_SERVICES)

    compose_calls = [
        call
        for call in runner.calls
        if "compose" in call and ("up" in call or "create" in call)
    ]
    assert len(compose_calls) == 2
    running_call = next(call for call in compose_calls if running_service in call)
    nonrunning_call = next(call for call in compose_calls if nonrunning_service in call)
    assert "up" in running_call and "-d" in running_call
    assert "create" in nonrunning_call and "up" not in nonrunning_call
    assert all(absent_service not in call for call in compose_calls)
    assert ("docker", "rm", "--force", absent_service) in runner.calls
    assert runner.absent_present is False
    assert waited == [(running_service,)]


def test_rollback_snapshot_rejects_environment_drift_before_recreate(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    rendered = _prepare_snapshot_state(lane)
    rendered["services"]["ea-worker"]["environment"]["INJECTED"] = "1"
    lane.runner = RenderRunner(rendered)
    lane.compose_bin = ("docker", "compose")
    with pytest.raises(deploy.DeployError, match="rollback_projection_mismatch"):
        lane._snapshot_and_validate_rollback_inputs()
    lane._cleanup_rollback_snapshots()


def test_rollback_snapshot_rejects_unrendered_explicit_network_endpoint_fields(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    rendered = _prepare_snapshot_state(lane)
    _bind_explicit_network_endpoint_prestate(lane, "ea-worker")
    lane.runner = RenderRunner(rendered)
    lane.compose_bin = ("docker", "compose")

    with pytest.raises(
        deploy.DeployError,
        match="rollback_projection_mismatch:ea-worker",
    ):
        lane._snapshot_and_validate_rollback_inputs()
    lane._cleanup_rollback_snapshots()


def test_rollback_snapshot_accepts_exact_explicit_network_endpoint_render(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    rendered = _prepare_snapshot_state(lane)
    _bind_explicit_network_endpoint_prestate(lane, "ea-worker")
    _render_explicit_network_endpoint(rendered["services"]["ea-worker"])
    lane.runner = RenderRunner(rendered)
    lane.compose_bin = ("docker", "compose")

    lane._snapshot_and_validate_rollback_inputs()
    lane._cleanup_rollback_snapshots()


def test_rollback_snapshot_accepts_legacy_config_for_per_network_mac_render(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    rendered = _prepare_snapshot_state(lane)
    lane.target_compose_config_sha256.setdefault(
        "ea-worker", _compose_config_sha256("ea-worker")
    )
    inspection = _paused_inspection(lane, "ea-worker")
    inspection["Config"]["MacAddress"] = "02:42:AC:1F:00:17"
    inspection["NetworkSettings"]["Networks"]["ea_default"]["MacAddress"] = ""
    rendered_service = rendered["services"]["ea-worker"]
    rendered_service["networks"] = {"default": {"mac_address": "02:42:ac:1f:00:17"}}
    requested = lane._rendered_network_endpoint_contract(rendered_service)
    endpoint_contract = lane._network_endpoint_contract(inspection, requested)
    entry = lane.pre_state["services"]["ea-worker"]
    live_projection = copy.deepcopy(entry["rollback_projection"])
    live_projection["security"]["network_endpoints"] = endpoint_contract
    entry["rollback_projection"] = live_projection
    entry["runtime"]["rollback_projection_sha256"] = deploy._canonical_sha256(
        live_projection
    )
    entry["runtime"]["restorable_contract_sha256"] = deploy._canonical_sha256(
        lane._inspection_restorable_contract(inspection, requested)
    )
    entry["requested_network_endpoints"] = requested
    lane.runner = RenderRunner(rendered)
    lane.compose_bin = ("docker", "compose")

    lane._snapshot_and_validate_rollback_inputs()
    lane._cleanup_rollback_snapshots()


def test_rollback_snapshot_rejects_compose_config_hash_mismatch_before_render(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    rendered = _prepare_snapshot_state(lane)
    runner = RenderRunner(
        rendered,
        config_hashes={"ea-worker": hashlib.sha256(b"drifted-compose").hexdigest()},
    )
    lane.runner = runner
    lane.compose_bin = ("docker", "compose")
    with pytest.raises(
        deploy.DeployError,
        match="rollback_compose_config_hash_mismatch:ea-worker",
    ):
        lane._snapshot_and_validate_rollback_inputs()
    assert not any("--format" in call for call in runner.calls)
    lane._cleanup_rollback_snapshots()


def test_one_retag_failure_does_not_suppress_other_recovery(tmp_path: Path) -> None:
    runner = RenderRunner({})
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    rendered_file = lane.root / "rollback.json"
    rendered_file.write_text('{"services":{}}\n')
    env_file = lane.root / ".env"
    rendered_sha256 = hashlib.sha256(rendered_file.read_bytes()).hexdigest()
    env_sha256 = hashlib.sha256(env_file.read_bytes()).hexdigest()
    topology_manifest_file = lane.root / "rollback.topology-manifest.json"
    topology_manifest_sha256 = _write_json(
        topology_manifest_file,
        {"contract_name": deploy.ACTIVE_TOPOLOGY_CONTRACT},
    )
    services = ("ea-worker", "ea-scheduler")
    lane.rollback_plans = {
        service: {
            "working_dir": str(lane.root),
            "rendered_file": str(rendered_file),
            "rendered_sha256": rendered_sha256,
            "env_file": str(env_file),
            "env_sha256": env_sha256,
            "topology_manifest_file": str(topology_manifest_file),
            "topology_manifest_sha256": topology_manifest_sha256,
            "compose_config_sha256": {service: _compose_config_sha256(service)},
        }
        for service in services
    }
    lane.pre_state = {
        "services": {
            service: {
                "runtime": {
                    "restorable_contract_sha256": hashlib.sha256(
                        service.encode()
                    ).hexdigest()
                }
            }
            for service in services
        }
    }

    def retag(self, service: str) -> None:
        del self
        if service == "ea-scheduler":
            raise deploy.DeployError("retag_failed")

    lane._retag_prior_reference = types.MethodType(retag, lane)
    lane._wait_ready = types.MethodType(lambda self, selected: None, lane)
    lane._inspect_container = types.MethodType(lambda self, service: {}, lane)
    lane._container_identity = types.MethodType(
        lambda self, inspection, service: {
            "runtime": {
                "restorable_contract_sha256": self.pre_state["services"][service][
                    "runtime"
                ]["restorable_contract_sha256"]
            }
        },
        lane,
    )
    lane._verify_rollback_active_topology = types.MethodType(
        lambda self, **kwargs: None, lane
    )
    with pytest.raises(deploy.DeployError, match="recovery_incomplete"):
        lane._rollback_services(services)
    up_calls = [call for call in runner.calls if "up" in call]
    assert len(up_calls) == 1
    assert "ea-worker" in up_calls[0]


def test_rollback_private_snapshot_drift_fails_before_retag_or_recreate(
    tmp_path: Path,
) -> None:
    runner = RenderRunner({})
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    rendered_file = lane.root / "rollback.json"
    rendered_file.write_text('{"services":{}}\n', encoding="utf-8")
    env_file = lane.root / ".env"
    lane.rollback_plans = {
        "ea-worker": {
            "working_dir": str(lane.root),
            "rendered_file": str(rendered_file),
            "rendered_sha256": hashlib.sha256(rendered_file.read_bytes()).hexdigest(),
            "env_file": str(env_file),
            "env_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
        }
    }
    lane.pre_state = {"services": {"ea-worker": {"runtime": {"lifecycle": "running"}}}}
    rendered_file.write_text(
        '{"services":{"attacker":{"privileged":true}}}\n',
        encoding="utf-8",
    )
    retagged: list[str] = []
    lane._retag_prior_reference = types.MethodType(
        lambda self, service: retagged.append(service), lane
    )
    with pytest.raises(deploy.DeployError, match="recovery_incomplete"):
        lane._rollback_services(("ea-worker",))
    assert retagged == []
    assert runner.calls == []


def test_partial_image_tags_are_accounted_and_cleanable(tmp_path: Path) -> None:
    class TagRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []
            self.tags: dict[str, str] = {}
            self.tag_count = 0

        def run(self, args, *, cwd, env, check=True):
            del cwd, env, check
            call = tuple(args)
            self.calls.append(call)
            if call[:3] == ("docker", "image", "tag"):
                self.tag_count += 1
                if self.tag_count == 2:
                    raise deploy.DeployError("second_tag_failed")
                self.tags[call[4]] = call[3]
            if call[:3] == ("docker", "image", "inspect"):
                if call[3] not in self.tags:
                    return subprocess.CompletedProcess(list(args), 1, "", "")
                return subprocess.CompletedProcess(
                    list(args), 0, json.dumps([{"Id": self.tags[call[3]]}]), ""
                )
            return subprocess.CompletedProcess(list(args), 0, "", "")

    runner = TagRunner()
    lane = _lane(tmp_path, runner=runner)
    lane.stage_owner_permit_document = types.SimpleNamespace(
        payload={"nonce": "a" * 64}
    )
    lane.pre_state = {
        "services": {
            service: {"runtime": {"image_id": "sha256:" + str(index + 1) * 64}}
            for index, service in enumerate(deploy.WORKER_SERVICES)
        }
    }
    lane._write_receipt = types.MethodType(lambda self: None, lane)
    with pytest.raises(deploy.DeployError, match="second_tag_failed"):
        lane._protect_previous_images()
    assert len(lane.protected_prior_images) == 1
    lane._remove_protected_image_tags()
    assert not lane.protected_prior_images
    assert any(call[:3] == ("docker", "image", "rm") for call in runner.calls)


@pytest.mark.parametrize(
    ("probe_returncode", "reason"),
    (
        (0, "rollback_image_protection_tag_exists"),
        (125, "rollback_image_protection_tag_probe_failed"),
    ),
)
def test_image_protection_refuses_collision_or_ambiguous_probe(
    tmp_path: Path, probe_returncode: int, reason: str
) -> None:
    class CollisionRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(self, args, *, cwd, env, check=True):
            del cwd, env, check
            call = tuple(args)
            self.calls.append(call)
            if call[:3] == ("docker", "image", "inspect"):
                return subprocess.CompletedProcess(
                    list(args), probe_returncode, "[]", "probe failed"
                )
            return subprocess.CompletedProcess(list(args), 0, "", "")

    runner = CollisionRunner()
    lane = _lane(tmp_path, runner=runner)
    lane.stage_owner_permit_document = types.SimpleNamespace(
        payload={"nonce": "a" * 64}
    )
    lane.pre_state = {
        "services": {
            deploy.WORKER_SERVICES[0]: {"runtime": {"image_id": "sha256:" + "1" * 64}}
        }
    }
    with pytest.raises(deploy.DeployError, match=reason):
        lane._protect_previous_images((deploy.WORKER_SERVICES[0],))
    assert lane.protected_prior_images == {}
    assert not any(call[:3] == ("docker", "image", "tag") for call in runner.calls)


def test_protected_tag_cleanup_refuses_retargeted_tag(tmp_path: Path) -> None:
    class RetargetedTagRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(self, args, *, cwd, env, check=True):
            del cwd, env, check
            call = tuple(args)
            self.calls.append(call)
            if call[:3] == ("docker", "image", "inspect"):
                return subprocess.CompletedProcess(
                    list(args), 0, json.dumps([{"Id": "sha256:" + "9" * 64}]), ""
                )
            return subprocess.CompletedProcess(list(args), 0, "", "")

    runner = RetargetedTagRunner()
    lane = _lane(tmp_path, runner=runner)
    expected = "sha256:" + "1" * 64
    lane.protected_prior_images = {expected: "ea-runtime:protected"}
    lane._write_receipt = types.MethodType(lambda self: None, lane)
    with pytest.raises(deploy.DeployError, match="tag_cleanup_failed"):
        lane._remove_protected_image_tags()
    assert lane.protected_prior_images == {expected: "ea-runtime:protected"}
    assert not any(call[:3] == ("docker", "image", "rm") for call in runner.calls)


def test_execute_path_without_loaded_authority_runs_no_command(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.preflight = types.MethodType(lambda self: None, lane)
    lane._load_authorities = types.MethodType(lambda self: None, lane)
    with pytest.raises(
        deploy.DeployError,
        match="paused_stage_execution_precondition_missing",
    ):
        lane.deploy(execute=True)
    assert lane.receipt["status"] == "preflight_failed"
    assert lane.runner.calls == []


def _authorized_transaction_lane(
    tmp_path: Path,
) -> tuple[deploy.AudiobookRuntimeDeployLane, RenderRunner, list[str]]:
    runner = RenderRunner({})
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    lane.source_revision = SOURCE
    lane.candidate_reference = IMAGE_REFERENCE
    lane.candidate = {"reference": IMAGE_REFERENCE, "image_id": IMAGE_ID}
    lane.stage_owner_permit_document = object()  # type: ignore[assignment]
    lane.target_compose_files = (
        *deploy.PRODUCTION_BASE_COMPOSE_FILES,
        str(lane.root / deploy.PRODUCTION_OVERLAY),
    )
    lane.target_compose_config_sha256 = {
        service: _compose_config_sha256(service) for service in deploy.WORKER_SERVICES
    }
    lane.forward_input_plan_sha256 = "4" * 64
    events: list[str] = []
    lane._issuer_file_locks = types.MethodType(lambda self: nullcontext(), lane)
    lane._revalidate_authority = types.MethodType(
        lambda self, boundary: events.append(f"authority:{boundary}"), lane
    )
    lane._revalidate_candidate_image = types.MethodType(
        lambda self: events.append("candidate"), lane
    )
    lane._revalidate_target_configuration = types.MethodType(
        lambda self: events.append("target_config"), lane
    )
    lane._consume_stage_owner_permit = types.MethodType(
        lambda self: (
            events.append("consume"),
            setattr(self, "stage_owner_permit_consumed", True),
        ),
        lane,
    )
    lane._revalidate_pre_state = types.MethodType(
        lambda self, services=deploy.EXPECTED_RUNTIME_SERVICES: events.append(
            "prestate:" + ",".join(services)
        ),
        lane,
    )
    lane._protect_previous_images = types.MethodType(
        lambda self, services=deploy.WORKER_SERVICES: events.append(
            "protect:" + ",".join(services)
        ),
        lane,
    )
    lane._verify_controls = types.MethodType(
        lambda self, baseline: events.append("controls"), lane
    )
    lane._capture_forward_topology_inputs = types.MethodType(
        lambda self: (
            events.append("capture_forward"),
            setattr(self, "forward_compose_files", self.target_compose_files),
            setattr(self, "forward_env_path", self.root / ".env"),
        ),
        lane,
    )
    lane._revalidate_forward_topology_inputs = types.MethodType(
        lambda self: events.append("forward_inputs"), lane
    )
    lane._activate_forward_topology_inputs = types.MethodType(
        lambda self: events.append("activate_topology"), lane
    )
    lane._write_receipt = types.MethodType(lambda self: None, lane)
    original_create = lane._target_create_paused

    def create(
        self: deploy.AudiobookRuntimeDeployLane,
        files: Sequence[str],
        services: Sequence[str],
        *,
        env_file: Path,
    ) -> None:
        del self
        events.append("create")
        original_create(files, services, env_file=env_file)

    lane._target_create_paused = types.MethodType(create, lane)
    return lane, runner, events


def _expected_paused_create_command(
    lane: deploy.AudiobookRuntimeDeployLane,
) -> tuple[str, ...]:
    command = [
        "docker",
        "compose",
        "--project-name",
        "ea",
        "--project-directory",
        str(lane.root),
        "--env-file",
        str(lane.forward_env_path),
    ]
    for raw in lane.forward_compose_files:
        path = Path(raw)
        if not path.is_absolute():
            path = lane.root / path
        command.extend(("-f", str(path.resolve())))
    command.extend(
        (
            "create",
            "--no-deps",
            "--pull",
            "never",
            "--no-build",
            "--force-recreate",
        )
    )
    for service in deploy.WORKER_SERVICES:
        command.extend(("--scale", f"{service}=1"))
    command.extend(deploy.WORKER_SERVICES)
    return tuple(command)


def test_real_preflight_prepares_permit_bound_plan_before_fake_execute(
    tmp_path: Path,
) -> None:
    rendered = {
        "services": {
            service: _rendered_service(service) for service in deploy.WORKER_SERVICES
        }
    }
    runner = RenderRunner(rendered)
    lane = _lane(tmp_path, runner=runner)
    lane.compose_bin = ("docker", "compose")
    lane.configuration_document = types.SimpleNamespace(sha256="5" * 64)
    lane.provenance_document = types.SimpleNamespace(sha256="6" * 64)
    lane.sbom_document = types.SimpleNamespace(sha256="7" * 64)
    lane.memorial_baseline_document = types.SimpleNamespace(sha256="8" * 64)
    lane.schema_v6_qualification = types.SimpleNamespace(
        terminal_identity_sha256="9" * 64,
        permit_sha256="a" * 64,
        qualified_at="2026-07-20T09:43:56.206Z",
        permit_expires_at="2026-07-20T10:30:00Z",
    )
    lane.compose_source_inventory = [
        {
            "path": relative.as_posix(),
            "working_sha256": hashlib.sha256(
                (lane.root / relative).read_bytes()
            ).hexdigest(),
        }
        for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    ]
    lane.compose_source_inventory_sha256 = deploy._canonical_sha256(
        lane.compose_source_inventory
    )
    target_sha256 = deploy._canonical_sha256(rendered)
    lane.configuration_projection = {
        "stage_projection_sha256": "b" * 64,
        "compose_source_inventory_sha256": lane.compose_source_inventory_sha256,
        "overlay_blob_sha256": lane.compose_source_inventory[-1]["working_sha256"],
        "rendered_compose_sha256": target_sha256,
        "memorial_baseline": {
            "receipt_sha256": lane.memorial_baseline_document.sha256,
            "ea_api_sha256": "c" * 64,
        },
        "schema_v6_qualification": {
            "terminal_identity_sha256": "9" * 64,
        },
        "provenance": {"sha256": lane.provenance_document.sha256},
        "sbom": {"sha256": lane.sbom_document.sha256},
    }
    target_files = tuple(
        str((lane.root / relative).resolve())
        for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    )

    lane._source_metadata = types.MethodType(
        lambda self: {"source_revision": SOURCE}, lane
    )
    lane._inspect_image = types.MethodType(
        lambda self, reference: {
            "reference": reference,
            "image_id": IMAGE_ID,
        },
        lane,
    )
    lane._read_evidence = types.MethodType(lambda self: None, lane)
    lane._capture_compose_source_inventory = types.MethodType(lambda self: None, lane)
    lane._detect_compose = types.MethodType(lambda self: None, lane)
    lane._capture_pre_state = types.MethodType(
        lambda self: setattr(self, "pre_state", {"sha256": "d" * 64}), lane
    )

    def prepare_rollback(self: deploy.AudiobookRuntimeDeployLane) -> None:
        self._prepare_rollback_snapshot_directory()
        self.rollback_plan_sha256 = "e" * 64

    lane._snapshot_and_validate_rollback_inputs = types.MethodType(
        prepare_rollback, lane
    )
    lane._capture_controls = lambda: {"memorial": "stable"}
    lane._verify_controls = types.MethodType(lambda self, baseline: None, lane)

    def validate_target(self: deploy.AudiobookRuntimeDeployLane) -> None:
        self.target_compose_files = target_files
        self.target_compose_sha256 = target_sha256
        self.receipt["target_compose"] = {"sha256": target_sha256}

    lane._validate_target_compose = types.MethodType(validate_target, lane)

    lane.preflight()

    assert deploy.SHA256_RE.fullmatch(lane.forward_input_plan_sha256)
    assert lane.receipt["forward_input_plan"]["sha256"] == (
        lane.forward_input_plan_sha256
    )
    assert lane.receipt["permit_request"]["forward_input_plan_sha256"] == (
        lane.forward_input_plan_sha256
    )
    lane.prior_preflight_receipt = types.SimpleNamespace(sha256="f" * 64)
    permit = _stage_owner_permit(lane)
    assert permit["forward_input_plan_sha256"] == lane.forward_input_plan_sha256
    lane.stage_owner_permit_document = types.SimpleNamespace(payload=permit)

    def revalidate_authority(
        self: deploy.AudiobookRuntimeDeployLane, boundary: str
    ) -> None:
        del boundary
        assert (
            self.stage_owner_permit_document.payload["forward_input_plan_sha256"]
            == self.forward_input_plan_sha256
        )
        assert self.receipt["permit_request"]["forward_input_plan_sha256"] == (
            self.forward_input_plan_sha256
        )

    lane._issuer_file_locks = types.MethodType(lambda self: nullcontext(), lane)
    lane._revalidate_authority = types.MethodType(revalidate_authority, lane)
    lane._revalidate_pre_state = types.MethodType(
        lambda self, services=deploy.EXPECTED_RUNTIME_SERVICES: None, lane
    )
    lane._consume_stage_owner_permit = types.MethodType(
        lambda self: setattr(self, "stage_owner_permit_consumed", True), lane
    )
    lane._protect_previous_images = types.MethodType(
        lambda self, services=deploy.WORKER_SERVICES: {}, lane
    )
    lane._verify_paused_stage = types.MethodType(
        lambda self, services, files: None, lane
    )
    lane._activate_forward_topology_inputs = types.MethodType(lambda self: None, lane)

    lane._execute_paused_stage_transaction()

    create_calls = [call for call in runner.calls if "create" in call]
    assert len(create_calls) == 1
    create_call = create_calls[0]
    assert "--no-deps" in create_call
    assert all(
        str(lane.rollback_snapshot_dir) in value for value in lane.forward_compose_files
    )
    assert all(
        str((lane.root / relative).resolve()) not in create_call
        for relative in deploy.PRODUCTION_COMPOSE_SOURCE_PATHS
    )
    assert lane.receipt["status"] == "pass_paused_stage"
    lane._cleanup_rollback_snapshots()


def test_authorized_fake_creates_exact_paused_stage_without_activation(
    tmp_path: Path,
) -> None:
    lane, runner, events = _authorized_transaction_lane(tmp_path)
    lane._verify_paused_stage = types.MethodType(
        lambda self, services, files: events.append("verify_paused"), lane
    )
    lane._execute_paused_stage_transaction()
    assert runner.calls == [_expected_paused_create_command(lane)]
    assert events[:14] == [
        "authority:immediately_before:paused_stage_transaction",
        "candidate",
        "target_config",
        "prestate:" + ",".join(deploy.EXPECTED_RUNTIME_SERVICES),
        "controls",
        "capture_forward",
        "consume",
        "protect:" + ",".join(deploy.WORKER_SERVICES),
        "authority:before:paused_stage_create",
        "candidate",
        "target_config",
        "prestate:" + ",".join(deploy.EXPECTED_RUNTIME_SERVICES),
        "controls",
        "forward_inputs",
    ]
    assert events.count("create") == 1
    assert events.count("verify_paused") == 2
    assert lane.receipt["status"] == "pass_paused_stage"
    assert lane.receipt["runtime_side_effect_posture"]["runtime_activation"] == "denied"
    serialized = " ".join(runner.calls[0])
    assert " up " not in f" {serialized} "
    assert " start " not in f" {serialized} "
    assert "--pull never" in serialized
    assert "--no-build" in serialized
    assert "--no-deps" in serialized


@pytest.mark.parametrize(
    "gate",
    (
        "_revalidate_authority",
        "_revalidate_candidate_image",
        "_revalidate_target_configuration",
        "_revalidate_pre_state",
        "_verify_controls",
        "_require_mutation_deadline",
        "_capture_forward_topology_inputs",
        "_revalidate_forward_topology_inputs",
        "_consume_stage_owner_permit",
        "_protect_previous_images",
    ),
)
def test_each_pre_create_gate_failure_issues_no_compose_mutation(
    tmp_path: Path, gate: str
) -> None:
    lane, runner, _events = _authorized_transaction_lane(tmp_path)

    def deny(self: deploy.AudiobookRuntimeDeployLane, *args: object) -> None:
        del self, args
        raise deploy.DeployError("authorized_fake_gate_denied")

    setattr(lane, gate, types.MethodType(deny, lane))
    with pytest.raises(deploy.DeployError, match="authorized_fake_gate_denied"):
        lane._execute_paused_stage_transaction()
    mutation_words = {"create", "up", "start", "run"}
    assert all(not mutation_words.intersection(call) for call in runner.calls)


def test_authorized_fake_failure_rolls_back_exact_workers_in_reverse_order(
    tmp_path: Path,
) -> None:
    lane, runner, events = _authorized_transaction_lane(tmp_path)
    rendered_file = lane.root / "rollback.json"
    rendered_file.write_text('{"services":{}}\n', encoding="utf-8")
    rendered_sha256 = hashlib.sha256(rendered_file.read_bytes()).hexdigest()
    env_sha256 = hashlib.sha256((lane.root / ".env").read_bytes()).hexdigest()
    topology_manifest_file = lane.root / "rollback.topology-manifest.json"
    topology_manifest_sha256 = _write_json(
        topology_manifest_file,
        {"contract_name": deploy.ACTIVE_TOPOLOGY_CONTRACT},
    )
    lane.rollback_plans = {
        service: {
            "working_dir": str(lane.root),
            "rendered_file": str(rendered_file),
            "rendered_sha256": rendered_sha256,
            "env_file": str(lane.root / ".env"),
            "env_sha256": env_sha256,
            "topology_manifest_file": str(topology_manifest_file),
            "topology_manifest_sha256": topology_manifest_sha256,
            "compose_config_sha256": {service: _compose_config_sha256(service)},
        }
        for service in deploy.WORKER_SERVICES
    }
    lane.pre_state = {
        "services": {
            service: {
                "runtime": {
                    "restorable_contract_sha256": hashlib.sha256(
                        f"restore:{service}".encode()
                    ).hexdigest()
                }
            }
            for service in deploy.WORKER_SERVICES
        }
    }
    lane._retag_prior_reference = types.MethodType(
        lambda self, service: events.append(f"retag:{service}"), lane
    )
    lane._wait_ready = types.MethodType(lambda self, services: None, lane)
    lane._inspect_container = types.MethodType(
        lambda self, service: {"service": service}, lane
    )
    lane._container_identity = types.MethodType(
        lambda self, inspection, service: {
            "runtime": {
                "restorable_contract_sha256": self.pre_state["services"][service][
                    "runtime"
                ]["restorable_contract_sha256"]
            }
        },
        lane,
    )
    lane._verify_rollback_active_topology = types.MethodType(
        lambda self, **kwargs: None, lane
    )
    verification_count = 0

    def fail_first_verification(
        self: deploy.AudiobookRuntimeDeployLane,
        services: Sequence[str],
        files: Sequence[str],
    ) -> None:
        nonlocal verification_count
        del self, services, files
        verification_count += 1
        raise deploy.DeployError("authorized_fake_post_create_failure")

    lane._verify_paused_stage = types.MethodType(fail_first_verification, lane)
    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane._execute_paused_stage_transaction()
    assert runner.calls[0] == _expected_paused_create_command(lane)
    rollback_calls = runner.calls[1:]
    assert len(rollback_calls) == len(deploy.WORKER_SERVICES)
    for call, service in zip(
        rollback_calls, reversed(deploy.WORKER_SERVICES), strict=True
    ):
        assert call[-1] == service
        assert call[call.index("--pull") + 1] == "never"
        assert "--no-build" in call
        assert "--no-deps" in call
        assert "--force-recreate" in call
        assert "create" not in call
        assert "start" not in call
    assert lane.receipt["status"] == "failed_rolled_back"
    assert lane.receipt["rollback"] == {
        "status": "pass",
        "order": list(reversed(deploy.WORKER_SERVICES)),
    }


def test_failed_rollback_retains_recovery_assets(tmp_path: Path) -> None:
    lane, runner, _events = _authorized_transaction_lane(tmp_path)
    lane.protected_prior_images = {
        "sha256:" + "1" * 64: "ea-runtime:rollback-protected"
    }
    lane._verify_paused_stage = types.MethodType(
        lambda self, services, files: (_ for _ in ()).throw(
            deploy.DeployError("post_create_failure")
        ),
        lane,
    )
    lane._rollback_services = types.MethodType(
        lambda self, services: (_ for _ in ()).throw(
            deploy.DeployError("rollback_service_recovery_incomplete")
        ),
        lane,
    )
    with pytest.raises(deploy.DeployError, match="deployment_and_rollback_failed"):
        lane._execute_paused_stage_transaction()
    assert runner.calls == [_expected_paused_create_command(lane)]
    assert lane.retain_recovery_assets is True
    assert lane.protected_prior_images
    assert lane.receipt["status"] == "rollback_failed"
    assert lane.receipt["rollback"]["status"] == "fail"
    assert lane.receipt["rollback"]["recovery_assets"] == "retained"


def test_stage_owner_permit_is_one_shot_even_in_same_process(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    _write_json(
        lane.stage_owner_permit_path,
        {"permit": "one-shot", "nonce": "a" * 64},
        mode=0o644,
    )
    lane.stage_owner_permit_document = deploy._read_trusted_json(
        lane.stage_owner_permit_path,
        expected_uid=os.geteuid(),
        expected_mode=0o644,
        maximum_bytes=deploy.MAX_AUTHORITY_BYTES,
        reason_prefix="permit",
    )
    lane.receipt["authority"] = {}
    lane._write_receipt = types.MethodType(lambda self: None, lane)
    lane._consume_stage_owner_permit()
    assert lane.stage_owner_permit_consumed is True
    with pytest.raises(deploy.DeployError, match="already_consumed"):
        lane._consume_stage_owner_permit()


def test_receipt_mount_projection_never_contains_host_source() -> None:
    source = "/private/machine-specific/secret-path"
    projected = deploy._mounts_from_inspection(
        {
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": source,
                    "Destination": "/run/secret",
                    "RW": False,
                }
            ]
        }
    )
    assert source not in json.dumps(projected)
    assert projected[0]["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()


def test_blocked_preflight_cli_is_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubLane:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def deploy(self, *, execute: bool = False):
            assert execute is False
            return {"status": "blocked_authority"}

    monkeypatch.setattr(deploy, "AudiobookRuntimeDeployLane", StubLane)
    assert deploy.main([]) == 2
