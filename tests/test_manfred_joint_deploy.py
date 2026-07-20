from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from unittest.mock import Mock

import pytest

from scripts import deploy_ea_memorial as api_deploy
from scripts import deploy_ea_memorial_joint as joint
from scripts import manage_manfred_vexp_mutation_permit as permit
from scripts import materialize_memorial_spatial_tour_public_origin as materializer
from scripts import memorial_spatial_public_origin_contract as spatial_contract
from scripts import reconcile_ea_public_ingress as ingress
from tests.test_memorial_spatial_tour_public_origin import ORIGIN, _valid_inputs


SOURCE_REVISION = "a" * 40
NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)


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


class TestAuthority(api_deploy.VexpMemorialMutationAuthority):
    __test__ = False

    def __init__(
        self,
        *,
        state_path: Path,
        certificate_root: Path,
        certificate_directory: Path,
        permit_path: Path,
        lock_path: Path,
    ) -> None:
        self._state_path = state_path
        self._certificate_root = certificate_root
        self._certificate_directory = certificate_directory
        self._permit_path = permit_path
        self._lock_path = lock_path

    @property
    def sentinel_state_path(self) -> Path:
        return self._state_path

    @property
    def mutation_permit_path(self) -> Path:
        return self._permit_path

    @property
    def qualification_certificate_root(self) -> Path:
        return self._certificate_root

    @property
    def qualification_certificate_directory(self) -> Path:
        return self._certificate_directory

    @property
    def qualification_certificate_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def qualification_certificate_owner_gid(self) -> int:
        return os.getegid()

    @property
    def mutation_permit_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def mutation_permit_lock_path(self) -> Path:
        return self._lock_path

    @property
    def mutation_permit_lock_owner_uid(self) -> int:
        return os.geteuid()

    def utc_now(self) -> datetime:
        return NOW


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    (root / ".env").write_text("# test\n", encoding="utf-8")
    (root / ".env").chmod(0o600)
    return root


def _lane(
    tmp_path: Path,
) -> tuple[joint.JointMemorialIngressDeployLane, NoCommandRunner]:
    root = _root(tmp_path)
    runner = NoCommandRunner()
    lane = joint.JointMemorialIngressDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "joint-test-001"},
        runner=runner,
        receipt_dir=tmp_path / "receipts",
        ingress_receipt_dir=tmp_path / "ingress-receipts",
        global_lock_path=tmp_path / "global.lock",
        recovery_journal_path=(
            tmp_path / "host-state" / joint.JOINT_RECOVERY_JOURNAL_FILENAME
        ),
        durable_root_check=lambda _path: None,
    )
    return lane, runner


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

    with pytest.raises(api_deploy.DeployError, match="deployment_receipt_write_unavailable"):
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


def _context(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
) -> dict[str, object]:
    ingress_lane = _ingress_lane(lane, tmp_path)
    public_edge = {"version_get": {"status": 421}}
    rollback_projection = {
        "service": {
            "image": ingress.PINNED_CLOUDFLARED_IMAGE,
            "environment": {"TUNNEL_TOKEN": "test-tunnel-token"},
            "networks": {
                "public_ingress": {
                    "ipv4_address": ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4
                },
                "property_default": None,
            },
        },
        "networks": {
            "property_default": {"external": True, "name": "property_default"},
            "public_ingress": {
                "name": ingress.PUBLIC_INGRESS_NETWORK,
                "ipam": {
                    "config": [
                        {
                            "subnet": ingress.PUBLIC_INGRESS_SUBNET,
                            "gateway": ingress.PUBLIC_INGRESS_GATEWAY,
                        }
                    ]
                },
            },
        },
    }
    candidate_path = tmp_path / "candidate.private.json"
    return {
        "authority": {"authority_posture": "governed"},
        "previous": {
            "working_dir": str(tmp_path / "previous"),
            "image_id": "sha256:" + "1" * 64,
            "compose_config_files": [str(tmp_path / "docker-compose.yml")],
        },
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
        "deployment_input_seal": {"seal_sha256": "3" * 64},
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
            "rollback_input_seals": [{"scope": "rollback"}],
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
            "rollback_render_sha256": joint._canonical_json_sha256(
                rollback_projection
            ),
            "target_input_seals": [{"scope": "target"}],
            "target_rendered": {},
        },
    }


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
    return joint.JointMemorialIngressDeployLane(
        root=(root or lane.root),
        env={"EA_DEPLOYMENT_ID": deployment_id, **dict(extra_env or {})},
        runner=NoCommandRunner(),
        receipt_dir=(receipt_dir or lane.receipt_dir),
        ingress_receipt_dir=(
            ingress_receipt_dir or tmp_path / "ingress-receipts"
        ),
        global_lock_path=tmp_path / "global.lock",
        recovery_journal_path=lane.recovery_journal_path,
        durable_root_check=lambda _path: None,
    )


def _recovery_context(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
) -> dict[str, object]:
    context = _context(lane, tmp_path)
    ingress_context = context["ingress"]
    assert isinstance(ingress_context, dict)
    previous_root = tmp_path / "previous"
    previous_compose = previous_root / "docker-compose.yml"
    ingress_root = lane.root
    ingress_compose = ingress_root / "docker-compose.yml"
    context["previous"] = {
        "container_id": "prior-api-container",
        "created_at": "2026-07-20T09:00:00Z",
        "working_dir": str(previous_root),
        "compose_config_files": [str(previous_compose)],
        "image_id": "sha256:" + "1" * 64,
        "image_reference": "ea-runtime:previous",
        "rollback_environment": {},
        "mount_identities": [],
        "mount_identity_sha256": "2" * 64,
        "mount_identity_count": 0,
        "environment_sha256": "3" * 64,
        "environment_count": 0,
        "process_config_sha256": "4" * 64,
        "state": {
            "running": True,
            "restarting": False,
            "started_at": "2026-07-20T09:00:00Z",
            "health": "healthy",
        },
    }
    context["non_memorial_controls"] = {
        "openapi": {
            "path_count": 1,
            "operation_count": 1,
            "schema_count": 0,
            "security_scheme_count": 0,
            "path_set_sha256": "7" * 64,
            "contract_sha256": "8" * 64,
            "probe": {},
            "_contract": {
                "operations": {"GET /health": {}},
                "schemas": {},
                "security_schemes": {},
            },
        }
    }
    context["deployment_input_seal"] = {
        "forward": [{"path": str(lane.root / ".env")}],
        "rollback": [{"path": str(previous_root / ".env")}],
    }
    rollback_seals = [{"path": str(ingress_root / ".env")}]
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
            "compose_config_files": [str(ingress_compose)],
            "compose_input_seals": rollback_seals,
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
                    "network_id": "network-id",
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
                        ingress.CLOUDFLARED_CONTAINER,
                        ingress.CLOUDFLARED_SERVICE,
                    ],
                }
            ],
        },
        "contains_environment_values": False,
        "contains_tunnel_token": False,
        "restoration": {
            "status": "coordinator_required",
            "reason": "standalone_mutation_has_no_authorized_permit_boundary",
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
            "rollback_render_sha256": joint._canonical_json_sha256(
                rollback_projection
            ),
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


def _install_success_path(
    lane: joint.JointMemorialIngressDeployLane,
    tmp_path: Path,
) -> tuple[dict[str, object], list[str]]:
    context = _context(lane, tmp_path)
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

    @contextmanager
    def lease(boundary: str) -> Iterator[None]:
        actions.append(f"lease:{boundary}")
        yield

    lane._vexp_mutation_lease = lease  # type: ignore[method-assign]
    lane._ensure_redis = Mock(side_effect=lambda: actions.append("ensure_redis"))
    lane._protect_previous_image = Mock(  # type: ignore[method-assign]
        side_effect=lambda _previous: (
            actions.append("protect_api")
            or joint._safe_rollback_tag(lane.deployment_id)
        )
    )
    lane._recreate_api = Mock(side_effect=lambda: actions.append("recreate_api"))
    lane._wait_container = Mock(return_value={"running": "true"})
    lane._verify_forward_api = Mock(return_value={"source_revision": SOURCE_REVISION})
    lane._local_origin = Mock(return_value="http://127.0.0.1:8090")
    lane._wait_http = Mock(return_value={"status_code": 200})
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


def test_joint_permit_contract_is_exact_and_distinct() -> None:
    assert api_deploy.MemorialDeployLane.vexp_mutation_boundaries == (
        "before_ensure_redis",
        "before_protect_previous_image",
        "before_recreate_api",
    )
    assert joint.JointMemorialIngressDeployLane.vexp_mutation_boundaries == (
        "before_ensure_redis",
        "before_protect_previous_image",
        "before_recreate_api",
        "before_recreate_cloudflared",
    )
    assert (
        joint.JointMemorialIngressDeployLane.vexp_mutation_permit_contract_name
        != api_deploy.MemorialDeployLane.vexp_mutation_permit_contract_name
    )


def _terminal_state(*, terminal: bool = True) -> dict[str, object]:
    return {
        "version": 6,
        "epoch_started_at": "2026-07-13T09:43:56.206Z",
        "epoch_started_ms": 1783935836206,
        "qualification_phase": "qualified" if terminal else "enforced_soak",
        "qualification_earliest_completion_at": "2026-07-20T09:43:56.206Z",
        "qualified_at": "2026-07-20T09:43:56.206Z" if terminal else None,
        "updated_at": "2026-07-20T09:59:00.000Z",
        "current_resources_healthy": True,
        "certification_blockers": [],
        "certification_deferments": [],
        "predicate_contract": "v6",
        "predicate_contract_sha256": "8" * 64,
    }


def _qualification_certificate(state: Mapping[str, object]) -> dict[str, object]:
    reset_hash = "1" * 64
    event_hash = "2" * 64
    tail_hash = "f" * 64
    reset_event = {
        "at": state["epoch_started_at"],
        "event": "qualification_reset",
        "sequence": 41,
        "previous_hash": "0" * 64,
        "hash": reset_hash,
    }
    event = {
        "at": state["qualified_at"],
        "event": "seven_day_qualification_achieved",
        "sequence": 42,
        "previous_hash": reset_hash,
        "hash": event_hash,
    }
    tail_event = {
        "at": "2026-07-20T09:44:56.206Z",
        "event": "resource_sample",
        "sequence": 43,
        "previous_hash": event_hash,
        "hash": tail_hash,
    }
    index = [reset_event, event, tail_event]
    certificate: dict[str, object] = {
        "schema": permit.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA,
        "sentinel_version": permit.VEXP_SENTINEL_STATE_VERSION,
        "epoch_started_at": state["epoch_started_at"],
        "epoch_started_ms": state["epoch_started_ms"],
        "qualified_at": state["qualified_at"],
        "qualification_duration_ms": permit.MINIMUM_QUALIFICATION_DURATION_MS,
        "qualification_monotonic_duration_ms": (
            permit.MINIMUM_QUALIFICATION_DURATION_MS
        ),
        "active_chain": {
            "anchor": {**reset_event, "source": "sentinel"},
            "qualification_event": {**event, "source": "sentinel"},
            "tail_sequence": tail_event["sequence"],
            "tail_hash": tail_hash,
            "event_count": len(index),
            "index": index,
            "index_sha256": permit._canonical_json_sha256(index),
        },
        "terminal_state": {
            "version": permit.VEXP_SENTINEL_STATE_VERSION,
            "epoch_started_at": state["epoch_started_at"],
            "epoch_started_ms": state["epoch_started_ms"],
            "qualified_at": state["qualified_at"],
            "qualification_phase": "qualified",
            "certification_blockers": [],
            "certification_deferments": [],
            "predicate_contract": state["predicate_contract"],
            "predicate_contract_sha256": state["predicate_contract_sha256"],
            "last_event_hash": tail_hash,
        },
        "source_attestations": {
            "sentinel_state_sha256": "3" * 64,
            "event_generations": {"qualification": 1},
            "event_log_guard_sha256": "4" * 64,
            "event_log_guard": {"status": "pass"},
            "apparmor_audit_sha256": "5" * 64,
            "apparmor_audit": {"status": "pass"},
            "implementation": {
                "sentinel_executable": {"sha256": "6" * 64},
                "sentinel_systemd_unit": {"sha256": "7" * 64},
                "predicate_contract": {"value": "v6", "sha256": "8" * 64},
                "finalizer_executable": {"sha256": "9" * 64},
                "finalizer_checksum_manifest": {"sha256": "a" * 64},
                "finalizer_checksum_binding": {"sha256": "b" * 64},
                "finalizer_systemd_unit": {"sha256": "c" * 64},
                "systemd_runtime": {"sha256": "d" * 64},
                "apparmor_policy": {"sha256": "e" * 64},
            },
        },
        "seal": {
            "writer": "root_owned_systemd_oneshot",
            "write_policy": "create_exclusive_never_overwrite",
            "telegram_sent_by_finalizer": False,
            "docker_socket_used": False,
        },
    }
    certificate["identity"] = (
        f"sha256:{permit._canonical_json_sha256(certificate)}"
    )
    return certificate


def _certificate_evidence(state: Mapping[str, object]) -> dict[str, str]:
    certificate = _qualification_certificate(state)
    raw = (
        json.dumps(
            certificate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    active_chain = certificate["active_chain"]
    assert isinstance(active_chain, dict)
    qualification_event = active_chain["qualification_event"]
    assert isinstance(qualification_event, dict)
    return {
        "schema": str(certificate["schema"]),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "identity": str(certificate["identity"]),
        "event_hash": str(qualification_event["hash"]),
    }


def _write_qualification_certificate(
    directory: Path, state: Mapping[str, object]
) -> None:
    certificate = _qualification_certificate(state)
    raw = (
        json.dumps(
            certificate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    path = directory / f"{state['epoch_started_ms']}.json"
    path.write_bytes(raw)
    path.chmod(0o640)
    sidecar = path.with_suffix(".json.sha256")
    sidecar.write_bytes(
        f"sha256:{hashlib.sha256(raw).hexdigest()}\n".encode("ascii")
    )
    sidecar.chmod(0o640)


def _write_json(path: Path, payload: object, *, mode: int) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(mode)


def _install_authority(
    lane: api_deploy.MemorialDeployLane,
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    state_path = tmp_path / "state.json"
    permit_path = tmp_path / "permit.json"
    lock_path = tmp_path / "permit.lock"
    certificate_root = tmp_path / "qualification-certificate"
    certificate_root.mkdir(mode=0o750, exist_ok=True)
    certificate_root.chmod(0o750)
    certificate_directory = certificate_root / "certificates"
    certificate_directory.mkdir(mode=0o750, exist_ok=True)
    certificate_directory.chmod(0o750)
    _write_qualification_certificate(
        certificate_directory, _terminal_state()
    )
    lock_path.touch()
    lock_path.chmod(0o644)
    lane._vexp_mutation_authority = TestAuthority(
        state_path=state_path,
        certificate_root=certificate_root,
        certificate_directory=certificate_directory,
        permit_path=permit_path,
        lock_path=lock_path,
    )
    return state_path, permit_path, lock_path


def test_api_and_joint_permits_cannot_be_cross_used(tmp_path: Path) -> None:
    joint_lane, _runner = _lane(tmp_path)
    api_lane = api_deploy.MemorialDeployLane(
        root=joint_lane.root,
        env={"EA_DEPLOYMENT_ID": "api-test-001"},
        runner=NoCommandRunner(),
        receipt_dir=tmp_path / "api-receipts",
        global_lock_path=tmp_path / "api-global.lock",
        durable_root_check=lambda _path: None,
    )
    _state_path, permit_path, _lock_path = _install_authority(joint_lane, tmp_path)
    api_lane._vexp_mutation_authority = joint_lane._vexp_mutation_authority
    state = _terminal_state()
    joint_payload = permit._permit_payload(
        state,
        qualification_certificate=_certificate_evidence(state),
        now=datetime(2026, 7, 20, 9, 45, tzinfo=UTC),
        ttl_seconds=2700,
        permit_mode=permit.JOINT_PERMIT_MODE,
    )
    _write_json(permit_path, joint_payload, mode=0o644)

    joint_lane._read_trusted_vexp_mutation_permit()
    with pytest.raises(
        api_deploy.DeployError, match="vexp_mutation_permit_contract_invalid"
    ):
        api_lane._read_trusted_vexp_mutation_permit()

    api_payload = permit._permit_payload(
        state,
        qualification_certificate=_certificate_evidence(state),
        now=datetime(2026, 7, 20, 9, 45, tzinfo=UTC),
        ttl_seconds=2700,
    )
    _write_json(permit_path, api_payload, mode=0o644)
    api_lane._read_trusted_vexp_mutation_permit()
    with pytest.raises(
        api_deploy.DeployError, match="vexp_mutation_permit_contract_invalid"
    ):
        joint_lane._read_trusted_vexp_mutation_permit()


def test_joint_permit_passes_all_four_exact_leases(tmp_path: Path) -> None:
    lane, runner = _lane(tmp_path)
    state_path, permit_path, _lock_path = _install_authority(lane, tmp_path)
    state = _terminal_state()
    payload = permit._permit_payload(
        state,
        qualification_certificate=_certificate_evidence(state),
        now=datetime(2026, 7, 20, 9, 45, tzinfo=UTC),
        ttl_seconds=2700,
        permit_mode=permit.JOINT_PERMIT_MODE,
    )
    _write_json(state_path, state, mode=0o600)
    _write_json(permit_path, payload, mode=0o644)

    for boundary in joint.JOINT_VEXP_MUTATION_BOUNDARIES:
        with lane._vexp_mutation_lease(boundary):
            pass

    assert runner.commands == []
    guards = [
        item
        for item in lane.receipt["checks"]
        if item.get("name") == "vexp_soak_mutation_guard"
    ]
    assert [item["boundary"] for item in guards] == list(
        joint.JOINT_VEXP_MUTATION_BOUNDARIES
    )
    assert {item["status"] for item in guards} == {"pass"}


def test_enforced_soak_blocks_joint_lane_before_any_command(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    state_path, _permit_path, _lock_path = _install_authority(lane, tmp_path)
    _write_json(state_path, _terminal_state(terminal=False), mode=0o600)

    with pytest.raises(api_deploy.DeployError, match="vexp_soak_mutation_blocked"):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            raise AssertionError("lease must not yield")

    assert runner.commands == []
    assert lane.receipt["status"] == "blocked_vexp_soak"


def test_permit_manager_default_and_explicit_joint_profiles_are_not_relabelable() -> (
    None
):
    state = _terminal_state()
    issued_at = datetime(2026, 7, 20, 9, 45, tzinfo=UTC)
    certificate = _certificate_evidence(state)
    api_payload = permit._permit_payload(
        state,
        qualification_certificate=certificate,
        now=issued_at,
        ttl_seconds=2700,
    )
    joint_payload = permit._permit_payload(
        state,
        qualification_certificate=certificate,
        now=issued_at,
        ttl_seconds=2700,
        permit_mode=permit.JOINT_PERMIT_MODE,
    )
    assert api_payload["contract_name"] == ("ea.vexp_memorial_mutation_permit.v2")
    assert joint_payload["contract_name"] == (
        "ea.vexp_memorial_joint_mutation_permit.v2"
    )
    assert api_payload["mutation_boundaries"] == list(
        api_deploy.VEXP_MUTATION_BOUNDARIES
    )
    assert joint_payload["mutation_boundaries"] == list(
        joint.JOINT_VEXP_MUTATION_BOUNDARIES
    )
    permit._validate_permit(
        api_payload,
        now=NOW,
        require_current=True,
    )
    permit._validate_permit(
        joint_payload,
        now=NOW,
        require_current=True,
        permit_mode=permit.JOINT_PERMIT_MODE,
    )
    with pytest.raises(permit.PermitError, match="contract_invalid"):
        permit._validate_permit(
            api_payload,
            now=NOW,
            require_current=True,
            permit_mode=permit.JOINT_PERMIT_MODE,
        )
    with pytest.raises(permit.PermitError, match="contract_invalid"):
        permit._validate_permit(
            joint_payload,
            now=NOW,
            require_current=True,
        )
    hybrid = dict(joint_payload)
    hybrid["contract_name"] = api_payload["contract_name"]
    with pytest.raises(permit.PermitError, match="boundaries_invalid"):
        permit._validate_permit(
            hybrid,
            now=NOW,
            require_current=True,
        )


def test_permit_manager_cli_defaults_to_api_and_requires_explicit_joint() -> None:
    api_args = permit._parse_args(
        [
            "issue",
            "--state-path",
            "/state.json",
            "--state-owner-uid",
            "1000",
        ]
    )
    joint_args = permit._parse_args(
        [
            "issue",
            "--state-path",
            "/state.json",
            "--state-owner-uid",
            "1000",
            "--permit-mode",
            "joint",
        ]
    )
    assert api_args.permit_mode == permit.API_PERMIT_MODE
    assert joint_args.permit_mode == permit.JOINT_PERMIT_MODE


def test_permit_manager_joint_issue_status_revoke_roundtrip_and_cross_mode_denial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "permit-runtime"
    runtime.mkdir(mode=0o755)
    runtime.chmod(0o755)
    state_path = tmp_path / "terminal-state.json"
    state = _terminal_state()
    _write_json(state_path, state, mode=0o600)
    certificate_root = tmp_path / "qualification-certificate-manager"
    certificate_root.mkdir(mode=0o750)
    certificate_root.chmod(0o750)
    certificate_directory = certificate_root / "certificates"
    certificate_directory.mkdir(mode=0o750)
    certificate_directory.chmod(0o750)
    _write_qualification_certificate(certificate_directory, state)
    monkeypatch.setattr(permit, "PERMIT_PATH", runtime / "permit.json")
    monkeypatch.setattr(permit, "LOCK_PATH", runtime / "permit.lock")
    monkeypatch.setattr(permit, "ROOT_UID", os.geteuid())
    monkeypatch.setattr(permit, "ROOT_GID", os.getegid())
    monkeypatch.setattr(permit, "QUALIFICATION_CERTIFICATE_ROOT", certificate_root)
    monkeypatch.setattr(
        permit, "QUALIFICATION_CERTIFICATE_DIRECTORY", certificate_directory
    )
    monkeypatch.setattr(
        permit, "QUALIFICATION_CERTIFICATE_OWNER_UID", os.geteuid()
    )
    monkeypatch.setattr(
        permit, "QUALIFICATION_CERTIFICATE_OWNER_GID", os.getegid()
    )
    monkeypatch.setattr(permit, "_verify_trusted_execution_path", lambda: None)
    monkeypatch.setattr(permit, "_require_root", lambda: None)
    monkeypatch.setattr(permit, "_utc_now_datetime", lambda: NOW)

    issued = permit.issue(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        ttl_seconds=900,
        permit_mode=permit.JOINT_PERMIT_MODE,
    )
    assert issued["contract_name"] == permit.JOINT_VEXP_MUTATION_PERMIT_CONTRACT_NAME
    current = permit.status(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        permit_mode=permit.JOINT_PERMIT_MODE,
    )
    assert current["mutation_boundaries"] == list(permit.JOINT_VEXP_MUTATION_BOUNDARIES)
    with pytest.raises(permit.PermitError, match="contract_invalid"):
        permit.status(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            permit_mode=permit.API_PERMIT_MODE,
        )
    with pytest.raises(permit.PermitError, match="contract_invalid"):
        permit.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
            permit_mode=permit.API_PERMIT_MODE,
        )
    with pytest.raises(permit.PermitError, match="contract_invalid"):
        permit.revoke(permit_mode=permit.API_PERMIT_MODE)
    assert permit.revoke(permit_mode=permit.JOINT_PERMIT_MODE)["status"] == "revoked"

    api_issued = permit.issue(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        ttl_seconds=900,
    )
    assert api_issued["contract_name"] == permit.VEXP_MUTATION_PERMIT_CONTRACT_NAME
    with pytest.raises(permit.PermitError, match="contract_invalid"):
        permit.status(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            permit_mode=permit.JOINT_PERMIT_MODE,
        )
    with pytest.raises(permit.PermitError, match="contract_invalid"):
        permit.revoke(permit_mode=permit.JOINT_PERMIT_MODE)
    assert permit.revoke()["status"] == "revoked"


def test_preflight_only_never_enters_a_mutation_lease(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    context = _context(lane, tmp_path)
    lane.preflight = Mock(return_value=context)  # type: ignore[method-assign]
    lane._vexp_mutation_lease = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("mutation lease entered")
    )
    lane._ensure_redis = Mock()
    lane._recreate_api = Mock()
    lane._recreate_cloudflared = Mock()

    receipt = lane.deploy(preflight_only=True)

    assert receipt["status"] == "preflight_only_pass"
    assert runner.commands == []
    lane._vexp_mutation_lease.assert_not_called()
    lane._ensure_redis.assert_not_called()
    lane._recreate_api.assert_not_called()
    lane._recreate_cloudflared.assert_not_called()


def test_happy_path_orders_api_local_proof_before_ingress_and_public_proof(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    _context_value, actions = _install_success_path(lane, tmp_path)

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert receipt["contract_name"] == joint.JOINT_COORDINATION_CONTRACT_NAME
    assert (
        receipt["coordination_contract_name"] == joint.JOINT_COORDINATION_CONTRACT_NAME
    )
    assert actions == [
        "lease:before_ensure_redis",
        "ensure_redis",
        "lease:before_protect_previous_image",
        "protect_api",
        "lease:before_recreate_api",
        "recreate_api",
        "lease:before_recreate_cloudflared",
        "recreate_cloudflared",
    ]
    assert runner.commands == []
    lane._revalidate_bind_source_access.assert_called_once_with(
        boundary="before_recreate_api"
    )
    lane._verify_non_memorial_controls.assert_called_once()
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


def test_authorization_failure_before_yield_records_no_attempted_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    _context_value, _actions = _install_success_path(lane, tmp_path)

    @contextmanager
    def denied(_boundary: str) -> Iterator[None]:
        raise api_deploy.DeployError("joint_permit_denied")
        yield  # pragma: no cover

    lane._vexp_mutation_lease = denied  # type: ignore[method-assign]

    with pytest.raises(api_deploy.DeployError, match="joint_permit_denied"):
        lane.deploy()

    assert lane.receipt["status"] == "authorization_failed"
    assert lane.receipt["preparation"] == {
        "status": "authorization_failed",
        "attempted_actions": [],
        "completed_actions": [],
        "pending_action": "ensure_redis",
        "active_action": None,
        "preparation_side_effects_possible": False,
        "api_mutation_started": False,
        "ingress_mutation_started": False,
        "api_runtime_state": "unchanged",
        "ingress_runtime_state": "unchanged",
    }


@pytest.mark.parametrize("interrupt_at", ("api", "ingress"))
def test_sigterm_enters_permit_free_joint_rollback(
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

    with joint._deployment_signal_handlers(), pytest.raises(
        api_deploy.DeployError,
        match="joint_deployment_failed_rolled_back:joint_deployment_signal",
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
    context = _context(lane, tmp_path)
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
            rollback_tag="ea-runtime:rollback-joint",
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
def test_uncatchable_crash_phase_is_durable_and_next_run_recovers_permit_free(
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
    restarted._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    restarted._perform_joint_rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    restarted._vexp_mutation_lease = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("recovery requested promotion authority")
    )
    restarted._recover_interrupted_transaction(preflight_only=False)

    rollback_call = restarted._perform_joint_rollback.call_args.kwargs
    assert rollback_call["api_mutation_started"] is True
    assert rollback_call["ingress_mutation_started"] is ingress_possible
    restarted._vexp_mutation_lease.assert_not_called()
    assert restarted.receipt["recovery"]["permit_requested"] is False
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
    recovery._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    recovery._perform_joint_rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    recovery.preflight = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("stop_after_recovery")
    )
    with pytest.raises(api_deploy.DeployError, match="stop_after_recovery"):
        recovery.deploy()

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
    assert retained_after_failure
    assert lane.recovery_journal_path.read_bytes() == retained_after_failure[-1]

    recovery = _restart_lane(
        lane,
        tmp_path,
        deployment_id="joint-failed-recovery-003",
        receipt_dir=tmp_path / "failed-recovery-receipts-3",
    )
    recovery._prevalidate_recovery_context = Mock()  # type: ignore[method-assign]
    recovery._perform_joint_rollback = Mock(return_value={"status": "pass"})  # type: ignore[method-assign]
    recovery.preflight = Mock(  # type: ignore[method-assign]
        side_effect=api_deploy.DeployError("stop_after_recovery")
    )
    with pytest.raises(api_deploy.DeployError, match="stop_after_recovery"):
        recovery.deploy()
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
    assert persisted["recovery_journal_cleanup"]["status"] == (
        "pending_after_commit"
    )
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
    assert persisted["recovery_journal_cleanup"]["status"] == (
        "pending_after_commit"
    )
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
    assert persisted["recovery_journal_cleanup"]["status"] == (
        "pending_after_commit"
    )
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
    assert persisted["recovery_journal_cleanup"]["status"] == (
        "pending_after_commit"
    )
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
    assert persisted["recovery_journal_cleanup"]["status"] == (
        "pending_after_commit"
    )
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
    assert pending["recovery_journal_cleanup"]["status"] == (
        "pending_after_commit"
    )
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
            ingress_lane.command_timeout_provider = lane._remaining_vexp_mutation_seconds
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


def test_joint_rollback_never_requests_new_mutation_authority(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    context = _context(lane, tmp_path)
    actions: list[str] = []
    lane._vexp_mutation_lease = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("rollback requested promotion authority")
    )
    lane._rollback_cloudflared = Mock(  # type: ignore[method-assign]
        side_effect=lambda _context: (
            actions.append("rollback_ingress") or {"status": "pass"}
        )
    )
    lane._rollback = Mock(  # type: ignore[method-assign]
        side_effect=lambda *_args: actions.append("rollback_api") or {"status": "pass"}
    )
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
        rollback_tag="ea-runtime:rollback-joint",
    )

    assert result["status"] == "pass"
    assert actions == [
        "rollback_ingress",
        "rollback_api",
        "restore_network",
    ]
    lane._vexp_mutation_lease.assert_not_called()


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
    context = _context(lane, tmp_path)
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
            rollback_tag="ea-runtime:rollback-joint",
        )

    lane._rollback.assert_called_once()
    lane._restore_public_network.assert_called_once()
    assert lane.receipt["rollback"]["ingress"]["status"] == "fail"


def test_ingress_rollback_rerenders_sealed_baseline_with_exact_forward_environment(
    tmp_path: Path,
) -> None:
    lane, _runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    ingress_lane.release_env.update(
        {
            "TUNNEL_TOKEN": "test-token",
            "CUSTOM_INTERPOLATION": "exact-value",
        }
    )
    rollback_seals = [{"path": "/sealed", "scope": "rollback"}]
    context = _context(lane, tmp_path)
    rendered = {
        "services": {
            ingress.CLOUDFLARED_SERVICE: context["ingress"][
                "rollback_render_projection"
            ]["service"]
        },
        "networks": context["ingress"]["rollback_render_projection"]["networks"],
    }
    rollback_projection = lane._ingress_rollback_projection(rendered)
    baseline = {
        "container": {
            "compose_working_dir": str(lane.root),
            "compose_config_files": [str(lane.root / "docker-compose.yml")],
            "image_id": "sha256:" + "1" * 64,
            "image_reference": "cloudflare/cloudflared:2026.6.0",
            "compose_input_seals": rollback_seals,
            "environment_identity": {"environment_sha256": "2" * 64},
            "command": ["tunnel", "run"],
            "entrypoint": ["cloudflared"],
            "user": "65532:65532",
            "process_config_sha256": "3" * 64,
            "security": {},
            "mounts": [],
            "networks": [],
        }
    }
    ingress_context = {
        "lane": ingress_lane,
        "cloudflared_baseline": baseline,
        "rollback_input_seals": rollback_seals,
        "rollback_render_projection": rollback_projection,
        "rollback_render_sha256": joint._canonical_json_sha256(
            rollback_projection
        ),
    }
    lane._revalidate_ingress_input_seals = Mock()  # type: ignore[method-assign]
    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        return_value=(rendered, rollback_seals)
    )
    ingress_lane._compose_args = Mock(return_value=["docker", "compose"])  # type: ignore[method-assign]
    observed_environments: list[dict[str, str]] = []
    lane._run = Mock(  # type: ignore[method-assign]
        side_effect=lambda _args, **kwargs: observed_environments.append(
            dict(kwargs["env"])
        )
        or subprocess.CompletedProcess([], 0, "", "")
    )
    lane._wait_container = Mock(return_value={"running": "true"})

    def capture_restored() -> dict[str, object]:
        ingress_lane._write_private_json(ingress_lane.baseline_path, baseline)
        return baseline

    ingress_lane._capture_cloudflared_baseline = Mock(  # type: ignore[method-assign]
        side_effect=capture_restored
    )

    result = lane._rollback_cloudflared(ingress_context)

    assert result["status"] == "pass"
    assert observed_environments == [
        {
            **ingress_lane.release_env,
            "COMPOSE_PROJECT_NAME": "ea",
        }
    ]
    ingress_lane._render_compose.assert_called_once_with(
        root=lane.root,
        files=[str(lane.root / "docker-compose.yml")],
        expected_input_seals=rollback_seals,
    )


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


def test_real_joint_ingress_preflight_passes_captured_seals_to_render_and_is_read_only(
    tmp_path: Path,
) -> None:
    lane, runner = _lane(tmp_path)
    ingress_lane = _ingress_lane(lane, tmp_path)
    target_seals = [{"path": "/target", "scope": "target"}]
    rollback_seals = [{"path": "/rollback", "scope": "rollback"}]
    events: list[str] = []
    lane._build_ingress_lane = Mock(return_value=ingress_lane)  # type: ignore[method-assign]
    ingress_lane._git_source_preflight = Mock()  # type: ignore[method-assign]
    ingress_lane._detect_compose = Mock()  # type: ignore[method-assign]
    ingress_lane._capture_compose_input_seals = Mock(  # type: ignore[method-assign]
        side_effect=lambda **_kwargs: events.append("capture_target_seals")
        or target_seals
    )
    lane._capture_public_network = Mock(  # type: ignore[method-assign]
        side_effect=lambda _ingress: events.append("capture_network")
        or {"present": False}
    )

    def capture_baseline() -> dict[str, object]:
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
    ingress_lane._render_compose = Mock(  # type: ignore[method-assign]
        side_effect=lambda **_kwargs: events.append("render_rollback")
        or (
            {
                "services": {
                    ingress.CLOUDFLARED_SERVICE: _context(lane, tmp_path)[
                        "ingress"
                    ]["rollback_render_projection"]["service"]
                },
                "networks": _context(lane, tmp_path)["ingress"][
                    "rollback_render_projection"
                ]["networks"],
            },
            rollback_seals,
        )
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
        "render_rollback",
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
        deploy["recovery_journal_cleanup"]["status"] = (
            "retained_cleanup_failed"
        )
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
        assert receipt["failed_codes"] == [
            "joint_recovery_journal_cleanup_missing"
        ]
    elif mutation in {"cleanup_incident", "cleanup_pending"}:
        assert receipt["failed_codes"] == [
            "joint_recovery_journal_cleanup_invalid"
        ]


def test_joint_cli_has_only_deploy_preflight_or_cleanup_finalizer_modes() -> None:
    args = joint._parse_args(["--preflight-only"])
    assert args.preflight_only is True
    finalizer = joint._parse_args(["--finalize-committed-cleanup"])
    assert finalizer.finalize_committed_cleanup is True
    with pytest.raises(SystemExit):
        joint._parse_args(
            ["--preflight-only", "--finalize-committed-cleanup"]
        )
    with pytest.raises(SystemExit):
        joint._parse_args(["--mutate-ingress-only"])


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
            return api_deploy.HttpResponse(200, "application/json", b"{}", "")
        return api_deploy.HttpResponse(200, "text/html", html, SOURCE_REVISION)

    def no_redirect(
        _url: str,
        _timeout: float,
        method: str,
        _public_authority: str = "",
    ) -> api_deploy.HttpResponse:
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
            tmp_path
            / "signature-state"
            / joint.JOINT_RECOVERY_JOURNAL_FILENAME
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

    assert authorities.count("myexternalbrain.com") == 2
    assert lane.receipt["checks"][-1]["name"] == "local_and_public_memorial"
