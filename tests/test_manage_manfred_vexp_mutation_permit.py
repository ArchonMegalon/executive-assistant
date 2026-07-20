from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
import stat
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping

import pytest

from scripts import manage_manfred_vexp_mutation_permit as manager


NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
REVIEWED_REVISION = "d" * 40
REAL_READ_CURRENT_PREDICATE = manager._read_current_predicate_evidence
REAL_READ_CANDIDATE_OPERATION_EVIDENCE = manager._read_candidate_operation_evidence
REAL_READ_CANDIDATE_PUBLICATION_EVIDENCE = (
    manager._read_candidate_publication_evidence
)
REAL_REQUIRE_CANDIDATE_PUBLICATION_RECORD_CURRENT = (
    manager._require_candidate_publication_record_current
)
REAL_REQUIRE_IMPLEMENTATION_MANIFEST = (
    manager._require_reviewed_qualification_implementation_manifest
)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _state(*, terminal: bool = True) -> dict[str, object]:
    return {
        "version": manager.VEXP_SENTINEL_STATE_VERSION,
        "updated_at": _timestamp(NOW),
        "epoch_started_at": "2026-07-13T09:43:56.206Z",
        "epoch_started_ms": 1783935836206,
        "qualification_phase": "qualified" if terminal else "enforced_soak",
        "qualification_earliest_completion_at": "2026-07-20T09:43:56.206Z",
        "qualified_at": "2026-07-20T09:43:56.206Z" if terminal else None,
        "current_resources_healthy": True,
        "certification_blockers": [],
        "certification_deferments": [],
        "predicate_contract": "v6",
        "predicate_contract_sha256": "3" * 64,
    }


def _current_predicate(state: dict[str, object]) -> dict[str, object]:
    return {
        "contract_name": manager.VEXP_CURRENT_PREDICATE_CONTRACT_NAME,
        "version": manager.VEXP_CURRENT_PREDICATE_VERSION,
        "status": "positive",
        "epoch_started_ms": state["epoch_started_ms"],
        "generation": 7,
        "record_sha256": "8" * 64,
        "boot_id": "12345678-1234-4234-9234-123456789abc",
        "monotonic_ns": 10_000_000_000,
        "sentinel_producer_sha256": "1" * 64,
        "root_predicate_producer_sha256": "2" * 64,
    }


def _certificate(state: dict[str, object]) -> dict[str, object]:
    reset_hash = "a" * 64
    event_hash = "b" * 64
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
        "schema": manager.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA,
        "sentinel_version": manager.VEXP_SENTINEL_STATE_VERSION,
        "epoch_started_at": state["epoch_started_at"],
        "epoch_started_ms": state["epoch_started_ms"],
        "qualified_at": state["qualified_at"],
        "qualification_duration_ms": manager.MINIMUM_QUALIFICATION_DURATION_MS,
        "qualification_monotonic_duration_ms": (
            manager.MINIMUM_QUALIFICATION_DURATION_MS
        ),
        "qualification_boot_id": "12345678-1234-4234-9234-123456789abc",
        "qualification_monotonic_started_ns": 1_000_000_000,
        "qualification_monotonic_qualified_ns": (
            1_000_000_000
            + manager.MINIMUM_QUALIFICATION_DURATION_MS * 1_000_000
        ),
        "active_chain": {
            "anchor": {**reset_event, "source": "sentinel"},
            "qualification_event": {**event, "source": "sentinel"},
            "tail_sequence": tail_event["sequence"],
            "tail_hash": tail_hash,
            "event_count": len(index),
            "index": index,
            "index_sha256": manager._canonical_json_sha256(index),
        },
        "terminal_state": {
            "version": manager.VEXP_SENTINEL_STATE_VERSION,
            "epoch_started_at": state["epoch_started_at"],
            "epoch_started_ms": state["epoch_started_ms"],
            "qualified_at": state["qualified_at"],
            "qualification_boot_id": (
                "12345678-1234-4234-9234-123456789abc"
            ),
            "qualification_monotonic_started_ns": 1_000_000_000,
            "qualification_monotonic_qualified_ns": (
                1_000_000_000
                + manager.MINIMUM_QUALIFICATION_DURATION_MS * 1_000_000
            ),
            "qualification_phase": "qualified",
            "certification_blockers": [],
            "certification_deferments": [],
            "predicate_contract": state["predicate_contract"],
            "predicate_contract_sha256": state["predicate_contract_sha256"],
            "last_event_hash": tail_hash,
            "probes_passed": 42,
        },
        "source_attestations": {
            "sentinel_state_sha256": "c" * 64,
            "event_generations": {"qualification": 1},
            "event_log_guard_sha256": "d" * 64,
            "event_log_guard": {"status": "pass"},
            "apparmor_audit_sha256": "e" * 64,
            "apparmor_audit": {"status": "pass"},
            "implementation_manifest_sha256": "0" * 64,
            "implementation": {
                "sentinel_executable": {"sha256": "1" * 64},
                "sentinel_systemd_unit": {"sha256": "2" * 64},
                "predicate_contract": {"value": "v6", "sha256": "3" * 64},
                "finalizer_executable": {"sha256": "4" * 64},
                "finalizer_checksum_manifest": {"sha256": "5" * 64},
                "finalizer_checksum_binding": {"sha256": "6" * 64},
                "finalizer_systemd_unit": {"sha256": "7" * 64},
                "systemd_runtime": {"sha256": "8" * 64},
                "apparmor_policy": {"sha256": "9" * 64},
            },
        },
        "seal": {
            "writer": "root_owned_systemd_oneshot",
            "write_policy": "create_exclusive_never_overwrite",
            "telegram_sent_by_finalizer": False,
            "docker_socket_used": False,
        },
    }
    certificate["identity"] = f"sha256:{manager._canonical_json_sha256(certificate)}"
    return certificate


def _write_certificate(
    state: dict[str, object], *, certificate: dict[str, object] | None = None
) -> tuple[Path, Path]:
    payload = certificate or _certificate(state)
    raw = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    certificate_path = (
        manager.QUALIFICATION_CERTIFICATE_DIRECTORY
        / f"{state['epoch_started_ms']}.json"
    )
    sidecar_path = certificate_path.with_suffix(".json.sha256")
    certificate_path.write_bytes(raw)
    certificate_path.chmod(manager.QUALIFICATION_CERTIFICATE_MODE)
    sidecar_path.write_bytes(
        f"sha256:{hashlib.sha256(raw).hexdigest()}\n".encode("ascii")
    )
    sidecar_path.chmod(manager.QUALIFICATION_CERTIFICATE_MODE)
    return certificate_path, sidecar_path


def _write_state(path: Path, payload: object, *, mode: int = 0o600) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(mode)


def _recovery_manifest() -> dict[str, object]:
    return {
        "contract_name": manager.VEXP_RECOVERY_MANIFEST_CONTRACT_NAME,
        "version": manager.VEXP_RECOVERY_MANIFEST_VERSION,
        "status": "reviewed",
        "qualification_schema_version": manager.VEXP_SENTINEL_STATE_VERSION,
        "recovery_scope": manager.VEXP_RECOVERY_SCOPE,
        "reviewed_revision": REVIEWED_REVISION,
        "artifacts": [
            {
                "path": "/usr/local/libexec/vexp-codex-sentinel-v6.mjs",
                "sha256": "a" * 64,
            }
        ],
    }


@pytest.fixture
def authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    authority_parent = tmp_path / "run"
    authority_parent.mkdir()
    authority_parent.chmod(manager.RUNTIME_DIRECTORY_MODE)
    permit_parent = authority_parent / "ea"
    void_ledger_root = tmp_path / "epoch-voids"
    void_ledger_root.mkdir(mode=manager.EPOCH_VOID_LEDGER_DIRECTORY_MODE)
    void_ledger_root.chmod(manager.EPOCH_VOID_LEDGER_DIRECTORY_MODE)
    candidate_authority_root = tmp_path / "candidate-authority"
    candidate_authority_root.mkdir(
        mode=manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_authority_root.chmod(
        manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_issuance_directory = candidate_authority_root / "issuances"
    candidate_issuance_directory.mkdir(
        mode=manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_issuance_directory.chmod(
        manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_finalization_directory = candidate_authority_root / "finalizations"
    candidate_finalization_directory.mkdir(
        mode=manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_finalization_directory.chmod(
        manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_operation_directory = candidate_authority_root / "operations"
    candidate_operation_directory.mkdir(
        mode=manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_operation_directory.chmod(
        manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_publication_directory = candidate_authority_root / "publications"
    candidate_publication_directory.mkdir(
        mode=manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_publication_directory.chmod(
        manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_revocation_directory = candidate_authority_root / "revocations"
    candidate_revocation_directory.mkdir(
        mode=manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    candidate_revocation_directory.chmod(
        manager.CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE
    )
    trusted_producer_parent = tmp_path / "root-producers"
    trusted_producer_parent.mkdir(
        mode=manager.TRUSTED_ROOT_PRODUCER_DIRECTORY_MODE
    )
    trusted_producer_parent.chmod(manager.TRUSTED_ROOT_PRODUCER_DIRECTORY_MODE)
    current_predicate_producer = trusted_producer_parent / "current-predicate-attestor"
    current_predicate_producer.write_bytes(b"test current predicate attestor\n")
    current_predicate_producer.chmod(manager.TRUSTED_ROOT_PRODUCER_MODE)
    candidate_boundary_attestor = trusted_producer_parent / "candidate-boundary-attestor"
    candidate_boundary_attestor.write_bytes(b"test candidate boundary attestor\n")
    candidate_boundary_attestor.chmod(manager.TRUSTED_ROOT_PRODUCER_MODE)
    recovery_manifest_root = tmp_path / "qualification-recovery"
    recovery_manifest_root.mkdir(mode=manager.RECOVERY_MANIFEST_DIRECTORY_MODE)
    recovery_manifest_root.chmod(manager.RECOVERY_MANIFEST_DIRECTORY_MODE)
    recovery_manifest_path = recovery_manifest_root / "reviewed-manifest.json"
    recovery_manifest_path.write_text(
        json.dumps(_recovery_manifest()) + "\n", encoding="utf-8"
    )
    recovery_manifest_path.chmod(manager.RECOVERY_MANIFEST_MODE)
    certificate_root = tmp_path / "qualification-certificate"
    certificate_root.mkdir(mode=manager.QUALIFICATION_CERTIFICATE_DIRECTORY_MODE)
    certificate_root.chmod(manager.QUALIFICATION_CERTIFICATE_DIRECTORY_MODE)
    certificate_directory = certificate_root / "certificates"
    certificate_directory.mkdir(
        mode=manager.QUALIFICATION_CERTIFICATE_DIRECTORY_MODE
    )
    certificate_directory.chmod(manager.QUALIFICATION_CERTIFICATE_DIRECTORY_MODE)
    monkeypatch.setattr(manager, "ROOT_UID", os.geteuid())
    monkeypatch.setattr(manager, "ROOT_GID", os.getegid())
    monkeypatch.setattr(
        manager,
        "TRUSTED_ROOT_PRODUCER_INSTALL_PARENT",
        trusted_producer_parent,
    )
    monkeypatch.setattr(
        manager,
        "CURRENT_PREDICATE_PRODUCER_PATH",
        current_predicate_producer,
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_ATTESTOR_PATH",
        candidate_boundary_attestor,
    )
    monkeypatch.setattr(
        manager, "TRUSTED_AUTHORITY_STORAGE_PREFIX", candidate_authority_root
    )
    monkeypatch.setattr(manager, "QUALIFICATION_CERTIFICATE_ROOT", certificate_root)
    monkeypatch.setattr(
        manager, "QUALIFICATION_CERTIFICATE_DIRECTORY", certificate_directory
    )
    monkeypatch.setattr(
        manager, "QUALIFICATION_CERTIFICATE_OWNER_UID", os.geteuid()
    )
    monkeypatch.setattr(
        manager, "QUALIFICATION_CERTIFICATE_OWNER_GID", os.getegid()
    )
    monkeypatch.setattr(manager, "PERMIT_PATH", permit_parent / "permit.json")
    monkeypatch.setattr(
        manager, "PERMIT_COMMIT_PATH", permit_parent / "permit.commit.json"
    )
    monkeypatch.setattr(manager, "LOCK_PATH", permit_parent / "permit.lock")
    monkeypatch.setattr(
        manager,
        "RUNTIME_AUTHORITY_TRUSTED_PARENT",
        authority_parent,
    )
    monkeypatch.setattr(manager, "EPOCH_VOID_LEDGER_ROOT", void_ledger_root)
    monkeypatch.setattr(manager, "EPOCH_VOID_LEDGER_OWNER_UID", os.geteuid())
    monkeypatch.setattr(manager, "EPOCH_VOID_LEDGER_OWNER_GID", os.getegid())
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_LEDGER_ROOT",
        candidate_authority_root,
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY",
        candidate_issuance_directory,
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY",
        candidate_finalization_directory,
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_OPERATION_DIRECTORY",
        candidate_operation_directory,
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_PUBLICATION_DIRECTORY",
        candidate_publication_directory,
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY",
        candidate_revocation_directory,
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_PRODUCER_MANIFEST_PATH",
        candidate_authority_root / "producer-manifest.json",
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_LEDGER_OWNER_UID",
        os.geteuid(),
    )
    monkeypatch.setattr(
        manager,
        "CANDIDATE_AUTHORITY_LEDGER_OWNER_GID",
        os.getegid(),
    )
    manager.CANDIDATE_AUTHORITY_PRODUCER_MANIFEST_PATH.write_bytes(
        manager._canonical_record_bytes(_candidate_producer_manifest())
    )
    manager.CANDIDATE_AUTHORITY_PRODUCER_MANIFEST_PATH.chmod(
        manager.CANDIDATE_AUTHORITY_RECORD_MODE
    )
    monkeypatch.setattr(manager, "RECOVERY_MANIFEST_ROOT", recovery_manifest_root)
    monkeypatch.setattr(manager, "RECOVERY_MANIFEST_PATH", recovery_manifest_path)
    monkeypatch.setattr(manager, "RECOVERY_MANIFEST_OWNER_UID", os.geteuid())
    monkeypatch.setattr(manager, "RECOVERY_MANIFEST_OWNER_GID", os.getegid())
    monkeypatch.setattr(manager, "_utc_now_datetime", lambda: NOW)
    monkeypatch.setattr(
        manager,
        "_read_current_predicate_evidence",
        lambda **kwargs: _current_predicate(dict(kwargs["state"])),
    )
    monkeypatch.setattr(
        manager,
        "_read_candidate_operation_evidence",
        lambda **kwargs: {
            "aggregate_sha256": (
                "6" * 64
                if kwargs["receipt_kind"] == "candidate_runtime"
                else "7" * 64
            ),
            "tail_sha256": "9" * 64,
            "last_closed_monotonic_ns": 9_000_000_000,
            "last_closed_at": _timestamp(NOW),
            "boot_id": "12345678-1234-4234-9234-123456789abc",
        },
    )
    monkeypatch.setattr(
        manager,
        "_read_candidate_publication_evidence",
        lambda **kwargs: (
            {
                "published_at": _timestamp(NOW),
                "published_monotonic_ns": 9_500_000_000,
                "deadline_monotonic_ns": 11_000_000_000,
            },
            (
                "a" * 64
                if kwargs["receipt_kind"] == "candidate_runtime"
                else "b" * 64
            ),
        ),
    )
    monkeypatch.setattr(
        manager,
        "_require_candidate_publication_record_current",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        manager,
        "_current_boot_id",
        lambda: "12345678-1234-4234-9234-123456789abc",
    )
    monkeypatch.setattr(manager, "_monotonic_ns", lambda: 10_000_000_000)
    monkeypatch.setattr(
        manager,
        "_require_reviewed_qualification_implementation_manifest",
        lambda _certificate: None,
    )
    monkeypatch.setattr(manager, "_verify_trusted_execution_path", lambda: None)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        manager,
        "_canonical_sentinel_state_path",
        lambda _owner_uid: state_path,
    )
    _write_certificate(_state())
    return state_path, permit_parent


def _issue(
    state_path: Path,
    payload: object | None = None,
    *,
    permit_mode: str = manager.API_PERMIT_MODE,
) -> dict[str, object]:
    _write_state(state_path, _state() if payload is None else payload)
    return manager.issue(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        ttl_seconds=900,
        permit_mode=permit_mode,
    )


def _status(
    state_path: Path,
    *,
    permit_mode: str = manager.API_PERMIT_MODE,
) -> dict[str, object]:
    return manager.status(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        permit_mode=permit_mode,
    )


def _candidate_authority_row(
    candidate_status: dict[str, object],
    *,
    phase: str,
    boundary: str,
) -> dict[str, object]:
    return {
        "status": "pass",
        "phase": phase,
        "boundary": boundary,
        "contract_name": candidate_status["contract_name"],
        "version": manager.CANDIDATE_VEXP_MUTATION_PERMIT_VERSION,
        "epoch_started_ms": candidate_status["epoch_started_ms"],
        "qualified_at": candidate_status["qualified_at"],
        "terminal_identity_sha256": candidate_status[
            "terminal_identity_sha256"
        ],
        "qualification_certificate_schema": candidate_status[
            "qualification_certificate_schema"
        ],
        "qualification_certificate_sha256": candidate_status[
            "qualification_certificate_sha256"
        ],
        "qualification_certificate_identity": candidate_status[
            "qualification_certificate_identity"
        ],
        "qualification_certificate_event_hash": candidate_status[
            "qualification_certificate_event_hash"
        ],
        "permit_sha256": candidate_status["permit_sha256"],
        "permit_commit": dict(candidate_status["permit_commit"]),
        "epoch_void_ledger": dict(candidate_status["epoch_void_ledger"]),
        "permit_issued_at": candidate_status["issued_at"],
        "permit_expires_at": candidate_status["expires_at"],
        "current_predicate": dict(candidate_status["current_predicate"]),
    }


def _write_candidate_seal_receipts(
    root: Path,
    *,
    candidate_status: dict[str, object],
    image_candidate_status: dict[str, object] | None = None,
    extra_candidate_field: object | None = None,
) -> tuple[Path, str, Path, str]:
    image_status = image_candidate_status or candidate_status
    revision = "a" * 40
    image_tag = f"ea-runtime:manfred-{revision}"
    image_id = f"sha256:{'b' * 64}"
    producer_sha256 = "c" * 64
    image_operations = [
        {
            "sequence": index,
            "operation": operation,
            "resource": {
                "argv": ["fixture-image-runner", operation],
                "target": f"image-resource-{index}",
            },
            "runner_acknowledged": True,
            "authority": _candidate_authority_row(
                image_status,
                phase="pre_mutation",
                boundary="before_candidate_image_build",
            ),
        }
        for index, operation in enumerate(
            (
                "verification_create",
                "verification_probe",
                "verification_cleanup",
            ),
            start=1,
        )
    ]
    image_authority = {
        "entry": _candidate_authority_row(
            image_status,
            phase="entry",
            boundary="candidate_entry",
        ),
        "operations": image_operations,
        "finalization": _candidate_authority_row(
            image_status,
            phase="finalization",
            boundary="candidate_receipt_publication",
        ),
        "operation_count": len(image_operations),
        "operations_exact": True,
        "authority_basis": "preexisting_image_current_authority_probe",
        "receipt_publication": "exclusive_hardlink_noreplace_v1",
        "receipt_publication_held_under_authority": True,
    }
    image_receipt = {
        "schema": manager.CANDIDATE_IMAGE_BUILD_RECEIPT_SCHEMA,
        "status": "pass",
        "commit": revision,
        "runtime_source_revision": revision,
        "image_tag": image_tag,
        "image_id": image_id,
        "producer_sha256": producer_sha256,
        "image_reused": True,
        "created_at": _timestamp(NOW),
        "image_build_authority": image_authority,
    }
    image_receipt_path = root / "image-build.json"
    image_raw = (
        json.dumps(image_receipt, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    image_receipt_path.write_bytes(image_raw)
    image_receipt_path.chmod(0o600)
    image_receipt_sha256 = hashlib.sha256(image_raw).hexdigest()
    binding = {
        "receipt_schema": manager.CANDIDATE_IMAGE_BUILD_RECEIPT_SCHEMA,
        "receipt_path": str(image_receipt_path),
        "receipt_sha256": image_receipt_sha256,
        "image_tag": image_tag,
        "image_id": image_id,
        "runtime_source_revision": revision,
        "producer_sha256": producer_sha256,
        "image_reused": True,
        "authority": image_authority,
    }
    runtime_authority = {
        "entry": _candidate_authority_row(
            candidate_status,
            phase="entry",
            boundary="candidate_entry",
        ),
        "mutations": [
            {
                "sequence": index,
                "operation": {
                    "before_candidate_up": "compose_up",
                    "before_candidate_exec": "redis_ping",
                    "before_candidate_interaction": "candidate_smoke",
                    "before_candidate_restart": "compose_restart_api",
                }[boundary],
                "resource": {
                    "argv": ["fixture-candidate-runner", boundary],
                    "target": f"candidate-resource-{index}",
                },
                "runner_acknowledged": True,
                "authority": _candidate_authority_row(
                    candidate_status,
                    phase="pre_mutation",
                    boundary=boundary,
                ),
            }
            for index, boundary in enumerate(
                manager.CANDIDATE_VEXP_MUTATION_SEQUENCE,
                start=1,
            )
        ],
        "finalization": _candidate_authority_row(
            candidate_status,
            phase="finalization",
            boundary="candidate_receipt_publication",
        ),
        "cleanup_requires_positive_authority": True,
        "retention_timer_only_authority_free_cleanup": True,
    }
    candidate_receipt: dict[str, object] = {
        "schema": manager.CANDIDATE_RUNTIME_RECEIPT_SCHEMA,
        "status": "pass",
        "producer_sha256": "d" * 64,
        "observed_at": _timestamp(NOW),
        "image": image_tag,
        "image_id": image_id,
        "image_source_revision": revision,
        "runtime_source_revision": revision,
        "runtime_authority_commit": revision,
        "compose_project": "ea-manfred-candidate-abcdef12",
        "image_build_authority_binding": binding,
        "vexp_candidate_mutation_authority": runtime_authority,
    }
    if extra_candidate_field is not None:
        candidate_receipt["test_extension"] = extra_candidate_field
    candidate_receipt_path = root / "candidate-runtime.json"
    candidate_raw = (
        json.dumps(candidate_receipt, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    candidate_receipt_path.write_bytes(candidate_raw)
    candidate_receipt_path.chmod(0o600)
    return (
        candidate_receipt_path,
        hashlib.sha256(candidate_raw).hexdigest(),
        image_receipt_path,
        image_receipt_sha256,
    )


def test_issue_and_status_reject_copied_noncanonical_state(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    copied_state_path = state_path.with_name("copied-state.json")
    _write_state(copied_state_path, _state())

    with pytest.raises(
        manager.PermitError,
        match="canonical_sentinel_state_required",
    ):
        manager.issue(
            state_path=copied_state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    _issue(state_path)
    with pytest.raises(
        manager.PermitError,
        match="canonical_sentinel_state_required",
    ):
        manager.status(
            state_path=copied_state_path,
            state_owner_uid=os.geteuid(),
        )


def test_runbook_limits_provisioning_and_documents_atomic_ledger_bootstrap() -> None:
    runbook = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md"
    ).read_text(encoding="utf-8")

    assert (
        "/usr/bin/install -d -o root -g 1000 -m 0750 \\\n"
        "  /var/lib/vexp-qualification-epoch-voids"
    ) in runbook
    assert (
        "/usr/bin/install -d -o root -g 1000 -m 0750 \\\n"
        "  /var/lib/vexp-manfred-candidate-authority \\\n"
        "  /var/lib/vexp-manfred-candidate-authority/issuances \\\n"
        "  /var/lib/vexp-manfred-candidate-authority/finalizations"
    ) in runbook
    assert "= \"750:0:1000:directory\"" in runbook
    assert "only for\nclean-host initialization" in runbook
    assert "It never exposes an\nempty canonical ledger" in runbook
    assert "Normal `issue` and `status`\noperations always fail closed" in runbook
    assert "record denies recovery and is never\noverwritten" in runbook
    assert "mode `0640`, canonical JSON files" in runbook
    assert "Candidate-mode `issue` publishes the exact permit\nissuance record" in runbook
    assert "candidate-mode `status` requires that\nexact issuance" in runbook


def test_runbooks_require_root_candidate_seal_before_promotion() -> None:
    root = Path(__file__).resolve().parents[1]
    scoped = (
        root / "docs" / "MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md"
    ).read_text(encoding="utf-8")
    joint = (
        root / "docs" / "MANFRED_MEMORIAL_JOINT_DEPLOY_RUNBOOK.md"
    ).read_text(encoding="utf-8")
    finalization_path = (
        "/var/lib/vexp-manfred-candidate-authority/finalizations/"
        "<candidate-permit-sha256>.json"
    )

    for runbook in (scoped, joint):
        seal_at = runbook.index('/usr/bin/python3 -I "$manager" seal-candidate')
        status_at = runbook.index(
            '/usr/bin/python3 -I "$manager" candidate-seal-status',
            seal_at,
        )
        revoke_at = runbook.index(
            '/usr/bin/python3 -I "$manager" revoke',
            status_at,
        )
        assert seal_at < status_at < revoke_at
        assert "--candidate-permit-sha256" in runbook[status_at:revoke_at]
        assert "--candidate-receipt-sha256" in runbook[status_at:revoke_at]
        assert "--image-build-receipt-sha256" in runbook[status_at:revoke_at]
        assert "ea.vexp_candidate_finalization.v1" in runbook
        assert finalization_path in runbook
        assert "aborted" in runbook.lower()
        assert "cannot" in runbook[revoke_at : revoke_at + 900].lower()


def test_source_gate_keeps_candidate_registry_v6_contract() -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(
        encoding="utf-8"
    )
    source_gate = makefile.split("verify-manfred-memorial-source-gate:", 1)[1]
    source_gate = source_gate.split("\n\n", 1)[0]

    assert "tests/test_manfred_candidate_registry_v6.py" in source_gate


def _trusted_manager_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    parent = tmp_path / "ea"
    parent.mkdir(mode=manager.TRUSTED_EXECUTABLE_PARENT_MODE)
    parent.chmod(manager.TRUSTED_EXECUTABLE_PARENT_MODE)
    executable = parent / "manage-manfred-vexp-mutation-permit"
    executable.write_text("# reviewed\n", encoding="utf-8")
    executable.chmod(manager.TRUSTED_EXECUTABLE_MODE)
    monkeypatch.setattr(manager, "ROOT_UID", os.geteuid())
    monkeypatch.setattr(manager, "ROOT_GID", os.getegid())
    monkeypatch.setattr(manager, "TRUSTED_EXECUTABLE_PATH", executable)
    monkeypatch.setattr(manager, "_current_executable_path", lambda: executable)
    monkeypatch.setattr(manager, "_isolated_mode_enabled", lambda: True)
    monkeypatch.setattr(
        manager,
        "_current_python_executable",
        lambda: manager.TRUSTED_PYTHON_EXECUTABLE,
    )
    return executable


def test_trusted_execution_metadata_accepts_exact_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trusted_manager_install(tmp_path, monkeypatch)

    manager._verify_trusted_execution_path()


def test_execution_verifier_requires_isolated_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trusted_manager_install(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "_isolated_mode_enabled", lambda: False)

    with pytest.raises(manager.PermitError, match="isolated_mode_required"):
        manager._verify_trusted_execution_path()


def test_execution_verifier_requires_fixed_system_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trusted_manager_install(tmp_path, monkeypatch)
    monkeypatch.setattr(
        manager, "_current_python_executable", lambda: Path("/opt/python3")
    )

    with pytest.raises(manager.PermitError, match="python_untrusted"):
        manager._verify_trusted_execution_path()


def test_execution_verifier_rejects_checkout_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trusted_manager_install(tmp_path, monkeypatch)
    monkeypatch.setattr(
        manager, "_current_executable_path", lambda: tmp_path / "checkout.py"
    )

    with pytest.raises(manager.PermitError, match="execution_path_untrusted"):
        manager._verify_trusted_execution_path()


@pytest.mark.parametrize("kind", ["mode", "hardlink", "symlink", "parent_mode"])
def test_execution_verifier_rejects_untrusted_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    executable = _trusted_manager_install(tmp_path, monkeypatch)
    if kind == "mode":
        executable.chmod(0o755)
    elif kind == "hardlink":
        os.link(executable, tmp_path / "second-link")
    elif kind == "symlink":
        executable.unlink()
        target = tmp_path / "target"
        target.write_text("# target\n", encoding="utf-8")
        target.chmod(manager.TRUSTED_EXECUTABLE_MODE)
        executable.symlink_to(target)
    else:
        executable.parent.chmod(0o775)

    with pytest.raises(manager.PermitError, match="manager_(parent|executable)_"):
        manager._verify_trusted_execution_path()


def test_manager_source_is_self_contained() -> None:
    source = Path(manager.__file__).read_text(encoding="utf-8")

    assert "deploy_ea_memorial" not in source


def test_duplicated_contract_matches_non_root_deploy_consumer() -> None:
    from scripts import deploy_ea_memorial as consumer

    assert manager.PERMIT_PATH == consumer.DEFAULT_VEXP_MUTATION_PERMIT_PATH
    assert manager.PERMIT_COMMIT_PATH == (
        consumer.DEFAULT_VEXP_MUTATION_PERMIT_COMMIT_PATH
    )
    assert manager.LOCK_PATH == consumer.DEFAULT_VEXP_MUTATION_PERMIT_LOCK_PATH
    assert manager.EPOCH_VOID_LEDGER_ROOT == (
        consumer.DEFAULT_VEXP_EPOCH_VOID_LEDGER_ROOT
    )
    assert manager.VEXP_SENTINEL_STATE_VERSION == consumer.VEXP_SENTINEL_STATE_VERSION
    assert (
        manager.VEXP_MUTATION_PERMIT_CONTRACT_NAME
        == consumer.VEXP_MUTATION_PERMIT_CONTRACT_NAME
    )
    assert manager.VEXP_MUTATION_PERMIT_VERSION == consumer.VEXP_MUTATION_PERMIT_VERSION
    assert manager.VEXP_MUTATION_BOUNDARIES == consumer.VEXP_MUTATION_BOUNDARIES
    assert manager.VEXP_MUTATION_PERMIT_KEYS == consumer.VEXP_MUTATION_PERMIT_KEYS
    assert (
        manager.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
        == consumer.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
    )
    assert (
        manager.QUALIFICATION_CERTIFICATE_ROOT
        == consumer.DEFAULT_VEXP_QUALIFICATION_CERTIFICATE_ROOT
    )
    assert (
        manager.QUALIFICATION_CERTIFICATE_DIRECTORY
        == consumer.DEFAULT_VEXP_QUALIFICATION_CERTIFICATE_DIRECTORY
    )
    assert (
        manager.QUALIFICATION_CERTIFICATE_MODE
        == consumer.VEXP_QUALIFICATION_CERTIFICATE_MODE
    )
    assert (
        manager.QUALIFICATION_CERTIFICATE_DIRECTORY_MODE
        == consumer.VEXP_QUALIFICATION_CERTIFICATE_DIRECTORY_MODE
    )
    assert (
        manager.MINIMUM_VEXP_QUALIFICATION_AT == consumer.MINIMUM_VEXP_QUALIFICATION_AT
    )
    assert manager.MAX_TTL_SECONDS == int(
        consumer.MAX_VEXP_MUTATION_PERMIT_LIFETIME.total_seconds()
    )
    assert (
        manager.MAX_VEXP_MUTATION_PERMIT_BYTES
        == consumer.MAX_VEXP_MUTATION_PERMIT_BYTES
    )

    from scripts import manfred_candidate_vexp_authority as candidate_consumer

    assert (
        manager.CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME
        == candidate_consumer.CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME
    )
    assert (
        manager.CANDIDATE_VEXP_MUTATION_PERMIT_VERSION
        == candidate_consumer.CANDIDATE_VEXP_MUTATION_PERMIT_VERSION
    )
    assert (
        manager.CANDIDATE_VEXP_MUTATION_BOUNDARIES
        == candidate_consumer.CANDIDATE_VEXP_MUTATION_BOUNDARIES
    )


def test_issue_status_and_revoke_round_trip(
    authority: tuple[Path, Path],
) -> None:
    state_path, permit_parent = authority

    issued = _issue(state_path)

    assert issued["status"] == "issued"
    assert issued["expires_at"] == "2026-07-20T10:15:00.000Z"
    assert stat.S_IMODE(permit_parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(manager.LOCK_PATH.stat().st_mode) == 0o644
    assert stat.S_IMODE(manager.PERMIT_PATH.stat().st_mode) == 0o644
    assert stat.S_IMODE(manager.PERMIT_COMMIT_PATH.stat().st_mode) == 0o644
    lock_inode = manager.LOCK_PATH.stat().st_ino
    permit = json.loads(manager.PERMIT_PATH.read_text(encoding="utf-8"))
    assert set(permit) == manager.VEXP_MUTATION_PERMIT_KEYS
    assert permit["terminal_identity_sha256"] == issued["terminal_identity_sha256"]
    assert permit["qualification_certificate_schema"] == (
        manager.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
    )
    assert permit["qualification_certificate_sha256"] == (
        issued["qualification_certificate_sha256"]
    )
    assert permit["qualification_certificate_identity"] == (
        issued["qualification_certificate_identity"]
    )
    assert permit["qualification_certificate_event_hash"] == (
        issued["qualification_certificate_event_hash"]
    )
    commit = json.loads(manager.PERMIT_COMMIT_PATH.read_text(encoding="utf-8"))
    assert commit["status"] == "committed"
    assert commit["permit_sha256"] == issued["permit_sha256"]
    assert issued["permit_commit"]["status"] == "committed"
    assert issued["epoch_void_ledger"]["entry_present"] is False

    permit_status = _status(state_path)
    assert permit_status["status"] == "valid"
    assert permit_status["permit_sha256"] == issued["permit_sha256"]
    assert permit_status["permit_commit"]["status"] == "committed"
    assert permit_status["epoch_void_ledger"]["entry_present"] is False
    assert manager.LOCK_PATH.stat().st_ino == lock_inode

    revoked = manager.revoke()
    assert revoked["status"] == "revoked"
    assert revoked["permit_sha256"] == issued["permit_sha256"]
    assert revoked["permit_commit_sha256"] == issued["permit_commit"]["sha256"]
    assert revoked["permit_commit_invalidated"] is True
    assert not manager.PERMIT_PATH.exists()
    assert not manager.PERMIT_COMMIT_PATH.exists()
    assert manager.LOCK_PATH.is_file()


def test_candidate_issue_status_and_revoke_round_trip(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority

    issued = _issue(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )

    assert issued["contract_name"] == (
        manager.CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME
    )
    assert candidate_status["status"] == "valid"
    assert candidate_status["mutation_boundaries"] == list(
        manager.CANDIDATE_VEXP_MUTATION_BOUNDARIES
    )
    with pytest.raises(manager.PermitError, match="permit_contract_invalid"):
        _status(state_path, permit_mode=manager.API_PERMIT_MODE)
    with pytest.raises(manager.PermitError, match="permit_contract_invalid"):
        _status(state_path, permit_mode=manager.JOINT_PERMIT_MODE)

    revoked = manager.revoke(permit_mode=manager.CANDIDATE_PERMIT_MODE)

    assert revoked["permit_sha256"] == issued["permit_sha256"]
    assert not manager.PERMIT_PATH.exists()
    assert not manager.PERMIT_COMMIT_PATH.exists()


def test_candidate_issuance_record_is_root_owned_and_persists_after_revoke(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    issuance = dict(issued["candidate_issuance"])
    issuance_path = Path(str(issuance["path"]))

    assert issuance["created"] is True
    assert issuance_path.is_file()
    assert stat.S_IMODE(issuance_path.stat().st_mode) == (
        manager.CANDIDATE_AUTHORITY_RECORD_MODE
    )
    record, record_sha256 = manager._read_candidate_issuance_record(
        str(issued["permit_sha256"])
    )
    assert record_sha256 == issuance["sha256"]
    assert record["permit_sha256"] == issued["permit_sha256"]
    assert record["permit_commit_sha256"] == issued["permit_commit"]["sha256"]

    manager.revoke(permit_mode=manager.CANDIDATE_PERMIT_MODE)

    persisted, persisted_sha256 = manager._read_candidate_issuance_record(
        str(issued["permit_sha256"])
    )
    assert persisted == record
    assert persisted_sha256 == record_sha256


def test_candidate_seal_survives_revoke_and_status_binds_exact_receipts(
    authority: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )

    sealed = manager.seal_candidate(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        candidate_receipt_path=candidate_path,
        candidate_receipt_sha256=candidate_sha256,
    )
    manager.revoke(permit_mode=manager.CANDIDATE_PERMIT_MODE)
    verified = manager.candidate_seal_status(
        candidate_permit_sha256=str(issued["permit_sha256"]),
        candidate_receipt_path=candidate_path,
        candidate_receipt_sha256=candidate_sha256,
        image_build_receipt_sha256=image_sha256,
    )

    assert sealed["status"] == "sealed"
    assert sealed["created"] is True
    assert verified["status"] == "valid"
    assert verified["sha256"] == sealed["sha256"]
    assert verified["candidate_permit_sha256"] == issued["permit_sha256"]
    assert verified["candidate_receipt_sha256"] == candidate_sha256
    assert verified["image_build_receipt_sha256"] == image_sha256


def test_revoke_before_seal_remains_possible_but_late_seal_is_denied(
    authority: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )

    revoked = manager.revoke(permit_mode=manager.CANDIDATE_PERMIT_MODE)

    assert revoked["status"] == "revoked"
    with pytest.raises(manager.PermitError, match="permit_(lock|commit|unavailable)"):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
        )
    with pytest.raises(manager.PermitError, match="finalization_record_unavailable"):
        manager.candidate_seal_status(
            candidate_permit_sha256=str(issued["permit_sha256"]),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
            image_build_receipt_sha256=image_sha256,
        )


def test_candidate_seal_rejects_fabricated_historical_permit_hash(
    authority: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, _candidate_sha256, _image_path, _image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    authority_envelope = dict(payload["vexp_candidate_mutation_authority"])
    rows = [
        authority_envelope["entry"],
        *authority_envelope["mutations"],
        authority_envelope["finalization"],
    ]
    for row in rows:
        authority_row = row.get("authority", row)
        authority_row["permit_sha256"] = "f" * 64
        authority_row["permit_commit"]["sha256"] = "e" * 64
    candidate_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    candidate_path.chmod(0o600)
    fabricated_sha256 = hashlib.sha256(candidate_path.read_bytes()).hexdigest()

    with pytest.raises(manager.PermitError, match="runtime_authority_invalid"):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=fabricated_sha256,
        )
    assert list(manager.CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY.iterdir()) == []


def test_candidate_seal_rejects_image_build_issuance_from_different_epoch_and_owner(
    authority: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    state_path, _permit_parent = authority
    image_issued = _issue(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    image_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    image_issuance_path = Path(str(image_issued["candidate_issuance"]["path"]))
    image_issuance = json.loads(image_issuance_path.read_text(encoding="utf-8"))
    image_issuance["sentinel_state_owner_uid"] = os.geteuid() + 1
    image_issuance_path.write_bytes(manager._canonical_record_bytes(image_issuance))
    image_issuance_path.chmod(manager.CANDIDATE_AUTHORITY_RECORD_MODE)
    manager.revoke(permit_mode=manager.CANDIDATE_PERMIT_MODE)

    runtime_state = _state()
    runtime_state.update(
        {
            "epoch_started_at": "2026-07-13T09:43:57.206Z",
            "epoch_started_ms": 1783935837206,
            "qualification_earliest_completion_at": "2026-07-20T09:43:57.206Z",
            "qualified_at": "2026-07-20T09:43:57.206Z",
        }
    )
    _write_certificate(runtime_state)
    _issue(
        state_path,
        runtime_state,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    runtime_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, _image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=runtime_status,
            image_candidate_status=image_status,
        )
    )

    with pytest.raises(
        manager.PermitError,
        match="vexp_candidate_image_build_epoch_binding_mismatch",
    ):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
        )
    assert list(manager.CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY.iterdir()) == []


def test_candidate_seal_rejects_wrong_runtime_receipt_hash(
    authority: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, _candidate_sha256, _image_path, _image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )

    with pytest.raises(manager.PermitError, match="receipt_sha256_mismatch"):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256="0" * 64,
        )
    assert list(manager.CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY.iterdir()) == []


def test_candidate_seal_exact_retry_is_idempotent_and_conflict_is_denied(
    authority: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, _image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )
    first = manager.seal_candidate(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        candidate_receipt_path=candidate_path,
        candidate_receipt_sha256=candidate_sha256,
    )
    monkeypatch.setattr(
        manager,
        "_utc_now_datetime",
        lambda: NOW + timedelta(seconds=1),
    )
    second = manager.seal_candidate(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        candidate_receipt_path=candidate_path,
        candidate_receipt_sha256=candidate_sha256,
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["sha256"] == first["sha256"]

    candidate_path, changed_sha256, _image_path, _image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
            extra_candidate_field="different-exact-bytes",
        )
    )
    with pytest.raises(manager.PermitError, match="record_conflict"):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=changed_sha256,
        )


def test_candidate_seal_status_rejects_fabricated_receipt_hash(
    authority: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )
    manager.seal_candidate(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        candidate_receipt_path=candidate_path,
        candidate_receipt_sha256=candidate_sha256,
    )
    manager.revoke(permit_mode=manager.CANDIDATE_PERMIT_MODE)

    with pytest.raises(manager.PermitError, match="seal_status_binding_mismatch"):
        manager.candidate_seal_status(
            candidate_permit_sha256=str(issued["permit_sha256"]),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256="f" * 64,
            image_build_receipt_sha256=image_sha256,
        )


def test_candidate_finalization_is_unclaimable_when_postpublish_predicate_changes(
    authority: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )
    real_publish = manager._atomic_publish_candidate_authority_record
    finalization_published = False

    def publish_then_change_predicate(
        path: Path, payload: dict[str, object]
    ) -> tuple[str, bool]:
        nonlocal finalization_published
        result = real_publish(path, payload)
        if path == manager._candidate_authority_record_path(
            manager.CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
            str(issued["permit_sha256"]),
        ):
            finalization_published = True
        return result

    def predicate_after_publication(**kwargs: object) -> dict[str, object]:
        value = _current_predicate(dict(kwargs["state"]))
        if finalization_published:
            value["generation"] = int(value["generation"]) + 1
            value["record_sha256"] = "7" * 64
        return value

    monkeypatch.setattr(
        manager,
        "_atomic_publish_candidate_authority_record",
        publish_then_change_predicate,
    )
    monkeypatch.setattr(
        manager,
        "_read_current_predicate_evidence",
        predicate_after_publication,
    )

    with pytest.raises(
        manager.PermitError,
        match="authority_changed_after_finalization",
    ):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
        )

    assert manager._candidate_authority_record_path(
        manager.CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
        str(issued["permit_sha256"]),
    ).is_file()
    assert not manager._candidate_finalization_commit_path(
        str(issued["permit_sha256"])
    ).exists()
    with pytest.raises(manager.PermitError, match="finalization_commit_unavailable"):
        manager.candidate_seal_status(
            candidate_permit_sha256=str(issued["permit_sha256"]),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
            image_build_receipt_sha256=image_sha256,
        )


def test_candidate_seal_status_rechecks_publication_revocation(
    authority: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )
    manager.seal_candidate(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        candidate_receipt_path=candidate_path,
        candidate_receipt_sha256=candidate_sha256,
    )

    def revoked(**_kwargs: object) -> None:
        raise manager.PermitError("vexp_candidate_publication_revoked")

    monkeypatch.setattr(
        manager,
        "_require_candidate_publication_record_current",
        revoked,
    )
    with pytest.raises(manager.PermitError, match="publication_revoked"):
        manager.candidate_seal_status(
            candidate_permit_sha256=str(issued["permit_sha256"]),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
            image_build_receipt_sha256=image_sha256,
        )


def test_candidate_commit_postfsync_expiry_is_aborted_and_unclaimable(
    authority: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_status = _status(
        state_path,
        permit_mode=manager.CANDIDATE_PERMIT_MODE,
    )
    candidate_path, candidate_sha256, _image_path, image_sha256 = (
        _write_candidate_seal_receipts(
            tmp_path,
            candidate_status=candidate_status,
        )
    )
    real_publish = manager._atomic_publish_candidate_authority_record
    commit_published = False

    def publish_and_expire(
        path: Path, payload: dict[str, object]
    ) -> tuple[str, bool]:
        nonlocal commit_published
        result = real_publish(path, payload)
        if path == manager._candidate_finalization_commit_path(
            str(issued["permit_sha256"])
        ):
            commit_published = True
        return result

    monkeypatch.setattr(
        manager,
        "_atomic_publish_candidate_authority_record",
        publish_and_expire,
    )
    monkeypatch.setattr(
        manager,
        "_monotonic_ns",
        lambda: 12_000_000_000 if commit_published else 10_000_000_000,
    )

    with pytest.raises(manager.PermitError, match="postcommit_authority_expired"):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
        )

    assert manager._candidate_finalization_commit_path(
        str(issued["permit_sha256"])
    ).is_file()
    assert manager._candidate_finalization_abort_path(
        str(issued["permit_sha256"])
    ).is_file()
    with pytest.raises(manager.PermitError, match="finalization_aborted"):
        manager.candidate_seal_status(
            candidate_permit_sha256=str(issued["permit_sha256"]),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha256,
            image_build_receipt_sha256=image_sha256,
        )


def test_void_epoch_cli_requires_explicit_state_and_reviewed_revision() -> None:
    args = manager._parse_args(
        [
            "void-epoch",
            "--state-path",
            "/home/operator/.local/state/vexp-sentinel/state.json",
            "--state-owner-uid",
            "1000",
            "--reviewed-revision",
            REVIEWED_REVISION,
        ]
    )

    assert args.command == "void-epoch"
    assert args.state_owner_uid == 1000
    assert args.reviewed_revision == REVIEWED_REVISION


def test_void_epoch_waits_for_shared_lease_then_permanently_denies_authority(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    entry = manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    context = multiprocessing.get_context("fork")
    lease_acquired = context.Event()
    release_lease = context.Event()

    def hold_shared_lease() -> None:
        descriptor = os.open(manager.LOCK_PATH, os.O_RDONLY | os.O_CLOEXEC)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            lease_acquired.set()
            release_lease.wait(timeout=2)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    worker = context.Process(target=hold_shared_lease, daemon=True)
    worker.start()
    assert lease_acquired.wait(timeout=1)
    assert not entry.exists()
    release_timer = threading.Timer(0.1, release_lease.set)
    release_timer.start()
    started_at = time.monotonic()
    result = manager.void_epoch(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        reviewed_revision=REVIEWED_REVISION,
    )
    elapsed = time.monotonic() - started_at
    worker.join(timeout=2)
    release_timer.join(timeout=2)

    assert not worker.is_alive()
    assert not release_timer.is_alive()
    assert elapsed >= 0.05
    assert result["status"] == "voided"
    assert result["authority_granted"] is False
    assert result["permit_invalidated_sha256"] == issued["permit_sha256"]
    assert result["epoch_void_record"]["created"] is True
    assert entry.is_file()
    assert not manager.PERMIT_PATH.exists()
    assert not manager.PERMIT_COMMIT_PATH.exists()
    with pytest.raises(manager.PermitError, match="epoch_voided"):
        _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)


def test_void_epoch_retry_accepts_same_epoch_after_state_snapshot_refresh(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())

    first = manager.void_epoch(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        reviewed_revision=REVIEWED_REVISION,
    )
    refreshed = _state()
    refreshed["updated_at"] = _timestamp(NOW + timedelta(seconds=1))
    _write_state(state_path, refreshed)
    second = manager.void_epoch(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        reviewed_revision=REVIEWED_REVISION,
    )

    assert first["epoch_void_record"]["created"] is True
    assert second["epoch_void_record"]["created"] is False
    assert second["epoch_void_record"]["sha256"] == (
        first["epoch_void_record"]["sha256"]
    )


def test_issue_and_status_fail_closed_when_epoch_void_ledger_is_absent(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path)
    permit_before = manager.PERMIT_PATH.read_bytes()
    commit_before = manager.PERMIT_COMMIT_PATH.read_bytes()
    manager.EPOCH_VOID_LEDGER_ROOT.rmdir()

    with pytest.raises(manager.PermitError, match="ledger_root_unavailable"):
        _status(state_path)

    assert manager.PERMIT_PATH.read_bytes() == permit_before
    assert manager.PERMIT_COMMIT_PATH.read_bytes() == commit_before
    revoked = manager.revoke()
    assert revoked["permit_sha256"] == issued["permit_sha256"]

    with pytest.raises(manager.PermitError, match="ledger_root_unavailable"):
        _issue(state_path)

    assert not manager.PERMIT_PATH.exists()
    assert not manager.PERMIT_COMMIT_PATH.exists()


def test_void_epoch_atomically_bootstraps_absent_ledger_with_first_record(
    authority: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path)
    manager.EPOCH_VOID_LEDGER_ROOT.rmdir()
    real_rename_noreplace = manager._rename_noreplace
    observed_bootstrap = False

    def inspect_bootstrap_before_publish(source: Path, destination: Path) -> None:
        nonlocal observed_bootstrap
        if destination == manager.EPOCH_VOID_LEDGER_ROOT:
            observed_bootstrap = True
            assert not destination.exists()
            assert source.is_dir()
            assert stat.S_IMODE(source.stat().st_mode) == (
                manager.EPOCH_VOID_LEDGER_DIRECTORY_MODE
            )
            staged_entry = source / f"{_state()['epoch_started_ms']}.json"
            assert staged_entry.is_file()
            assert stat.S_IMODE(staged_entry.stat().st_mode) == (
                manager.EPOCH_VOID_LEDGER_ENTRY_MODE
            )
            assert staged_entry.stat().st_nlink == 1
        real_rename_noreplace(source, destination)

    monkeypatch.setattr(manager, "_rename_noreplace", inspect_bootstrap_before_publish)

    result = manager.void_epoch(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        reviewed_revision=REVIEWED_REVISION,
    )

    entry = manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    record = json.loads(entry.read_text(encoding="utf-8"))
    assert observed_bootstrap is True
    assert result["epoch_void_record"]["created"] is True
    assert record["sentinel_state_sha256"] == hashlib.sha256(
        state_path.read_bytes()
    ).hexdigest()
    assert entry.stat().st_nlink == 1
    assert stat.S_IMODE(manager.EPOCH_VOID_LEDGER_ROOT.stat().st_mode) == (
        manager.EPOCH_VOID_LEDGER_DIRECTORY_MODE
    )
    assert not manager.PERMIT_PATH.exists()
    assert not manager.PERMIT_COMMIT_PATH.exists()
    assert result["permit_invalidated_sha256"] == issued["permit_sha256"]


def test_existing_ledger_void_publication_uses_atomic_noreplace_not_hardlink(
    authority: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())
    real_rename_noreplace = manager._rename_noreplace
    published_destinations: list[Path] = []

    def reject_hardlink(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("epoch void publication must not use hard links")

    def observe_rename(source: Path, destination: Path) -> None:
        published_destinations.append(destination)
        real_rename_noreplace(source, destination)

    monkeypatch.setattr(manager.os, "link", reject_hardlink)
    monkeypatch.setattr(manager, "_rename_noreplace", observe_rename)

    result = manager.void_epoch(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        reviewed_revision=REVIEWED_REVISION,
    )

    entry = manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    assert published_destinations == [entry]
    assert result["epoch_void_record"]["created"] is True
    assert entry.stat().st_nlink == 1
    assert [path for path in manager.EPOCH_VOID_LEDGER_ROOT.iterdir()] == [entry]


def test_epoch_void_fsync_failure_after_rename_is_retryable_without_temp_wedge(
    authority: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())
    entry = manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    real_fsync_directory = manager._fsync_directory
    injected = False

    def fail_once_after_publication(path: Path) -> None:
        nonlocal injected
        if path == manager.EPOCH_VOID_LEDGER_ROOT and entry.exists() and not injected:
            injected = True
            raise manager.PermitError("injected_epoch_void_directory_fsync_failure")
        real_fsync_directory(path)

    monkeypatch.setattr(manager, "_fsync_directory", fail_once_after_publication)
    with pytest.raises(
        manager.PermitError,
        match="injected_epoch_void_directory_fsync_failure",
    ):
        manager.void_epoch(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            reviewed_revision=REVIEWED_REVISION,
        )

    assert injected is True
    assert entry.is_file()
    assert entry.stat().st_nlink == 1
    assert [path for path in manager.EPOCH_VOID_LEDGER_ROOT.iterdir()] == [entry]

    retried = manager.void_epoch(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        reviewed_revision=REVIEWED_REVISION,
    )

    assert retried["epoch_void_record"]["created"] is False
    assert entry.stat().st_nlink == 1


def test_void_epoch_never_overwrites_conflicting_existing_record(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())
    manifest_sha256 = hashlib.sha256(
        manager.RECOVERY_MANIFEST_PATH.read_bytes()
    ).hexdigest()
    payload = manager._epoch_void_payload(
        _state(),
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        state_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
        voided_at=NOW,
        maintenance_manifest_sha256=manifest_sha256,
        reviewed_revision="e" * 40,
    )
    entry = manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    entry.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    entry.chmod(manager.EPOCH_VOID_LEDGER_ENTRY_MODE)
    before = entry.read_bytes()

    with pytest.raises(manager.PermitError, match="epoch_void_record_invalid"):
        manager.void_epoch(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            reviewed_revision=REVIEWED_REVISION,
        )

    assert entry.read_bytes() == before
    assert entry.stat().st_nlink == 1


def test_rename_noreplace_preserves_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"new")
    destination.write_bytes(b"permanent")

    with pytest.raises(FileExistsError):
        manager._rename_noreplace(source, destination)

    assert source.read_bytes() == b"new"
    assert destination.read_bytes() == b"permanent"


def test_void_epoch_rejects_unreviewed_manifest_before_record_or_revocation(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    issued = _issue(state_path)
    manifest = _recovery_manifest()
    manifest["status"] = "draft"
    manager.RECOVERY_MANIFEST_PATH.write_text(
        json.dumps(manifest) + "\n", encoding="utf-8"
    )
    manager.RECOVERY_MANIFEST_PATH.chmod(manager.RECOVERY_MANIFEST_MODE)

    with pytest.raises(manager.PermitError, match="recovery_manifest_invalid"):
        manager.void_epoch(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            reviewed_revision=REVIEWED_REVISION,
        )

    entry = manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    assert not entry.exists()
    assert manager.PERMIT_PATH.is_file()
    assert manager.PERMIT_COMMIT_PATH.is_file()
    assert _status(state_path)["permit_sha256"] == issued["permit_sha256"]


def test_void_epoch_invalid_manifest_never_creates_runtime_plumbing(
    authority: tuple[Path, Path],
) -> None:
    state_path, permit_parent = authority
    _write_state(state_path, _state(terminal=False))
    manifest = _recovery_manifest()
    manifest["status"] = "draft"
    manager.RECOVERY_MANIFEST_PATH.write_text(
        json.dumps(manifest) + "\n", encoding="utf-8"
    )
    manager.RECOVERY_MANIFEST_PATH.chmod(manager.RECOVERY_MANIFEST_MODE)
    assert not permit_parent.exists()

    with pytest.raises(manager.PermitError, match="recovery_manifest_invalid"):
        manager.void_epoch(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            reviewed_revision=REVIEWED_REVISION,
        )

    assert not permit_parent.exists()
    assert not manager.LOCK_PATH.exists()
    assert not (
        manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    ).exists()


def test_void_epoch_missing_lock_publishes_void_first_without_runtime_creation(
    authority: tuple[Path, Path],
) -> None:
    state_path, permit_parent = authority
    _write_state(state_path, _state(terminal=False))
    assert not permit_parent.exists()

    result = manager.void_epoch(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        reviewed_revision=REVIEWED_REVISION,
    )

    entry = manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    assert result["status"] == "voided"
    assert result["permit_invalidated_sha256"] is None
    assert result["permit_commit_invalidated_sha256"] is None
    assert entry.is_file()
    assert not permit_parent.exists()


def test_void_epoch_missing_lock_denies_if_any_permit_artifact_exists(
    authority: tuple[Path, Path],
) -> None:
    state_path, permit_parent = authority
    _write_state(state_path, _state(terminal=False))
    manager._ensure_runtime_directory()
    manager.PERMIT_PATH.write_text("{}\n", encoding="utf-8")
    manager.PERMIT_PATH.chmod(manager.PERMIT_MODE)
    assert not manager.LOCK_PATH.exists()

    with pytest.raises(manager.PermitError, match="lockless_authority_present"):
        manager.void_epoch(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            reviewed_revision=REVIEWED_REVISION,
        )

    assert manager.PERMIT_PATH.is_file()
    assert not (
        manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    ).exists()


def test_void_epoch_rejects_operator_selected_state_snapshot(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    copied_state = state_path.with_name("copied-terminal-state.json")
    _write_state(copied_state, _state())

    with pytest.raises(
        manager.PermitError,
        match="canonical_sentinel_state_required",
    ):
        manager.void_epoch(
            state_path=copied_state,
            state_owner_uid=os.geteuid(),
            reviewed_revision=REVIEWED_REVISION,
        )

    assert not (
        manager.EPOCH_VOID_LEDGER_ROOT / f"{_state()['epoch_started_ms']}.json"
    ).exists()


def test_reissue_preserves_stable_lock_inode(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    lock_inode = manager.LOCK_PATH.stat().st_ino

    manager.issue(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        ttl_seconds=1200,
    )

    assert manager.LOCK_PATH.stat().st_ino == lock_inode


@pytest.mark.parametrize("operation", ["issue", "revoke", "void_epoch"])
def test_mutating_commands_require_root(
    authority: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())
    if operation == "revoke":
        _issue(state_path)
    monkeypatch.setattr(manager.os, "geteuid", lambda: manager.ROOT_UID + 1)

    with pytest.raises(manager.PermitError, match="root_required"):
        if operation == "issue":
            manager.issue(
                state_path=state_path,
                state_owner_uid=os.getuid(),
                ttl_seconds=900,
            )
        elif operation == "revoke":
            manager.revoke()
        else:
            manager.void_epoch(
                state_path=state_path,
                state_owner_uid=os.getuid(),
                reviewed_revision=REVIEWED_REVISION,
            )


def test_active_soak_denies_before_creating_runtime_authority(
    authority: tuple[Path, Path],
) -> None:
    state_path, permit_parent = authority
    _write_state(state_path, _state(terminal=False))

    with pytest.raises(manager.PermitError, match="state_not_terminal"):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert not permit_parent.exists()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"current_resources_healthy": False}, "resources_not_healthy"),
        ({"certification_blockers": ["still_soaking"]}, "blockers_present"),
        ({"certification_blockers": None}, "blockers_present"),
        (
            {"qualified_at": "2026-07-20T09:43:56.205Z"},
            "qualification_before_minimum",
        ),
        (
            {
                "qualification_earliest_completion_at": (
                    "2026-07-20T09:43:56.205Z"
                )
            },
            "earliest_completion_invalid",
        ),
    ],
)
def test_issue_requires_complete_terminal_health(
    authority: tuple[Path, Path], change: dict[str, object], reason: str
) -> None:
    state_path, permit_parent = authority
    payload = {**_state(), **change}
    _write_state(state_path, payload)

    with pytest.raises(manager.PermitError, match=reason):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert not permit_parent.exists()


def test_issue_requires_certification_blockers_key(
    authority: tuple[Path, Path],
) -> None:
    state_path, permit_parent = authority
    payload = _state()
    del payload["certification_blockers"]
    _write_state(state_path, payload)

    with pytest.raises(manager.PermitError, match="blockers_missing"):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert not permit_parent.exists()


@pytest.mark.parametrize(
    ("updated_at", "reason"),
    [
        (None, "updated_at_invalid"),
        (_timestamp(NOW - timedelta(minutes=5, milliseconds=1)), "updated_at_stale"),
        (_timestamp(NOW + timedelta(seconds=30, milliseconds=1)), "updated_at_future"),
        ("2026-07-20T10:00:00+00:00", "updated_at_invalid"),
    ],
)
def test_issue_requires_fresh_exact_utc_state(
    authority: tuple[Path, Path], updated_at: object, reason: str
) -> None:
    state_path, permit_parent = authority
    payload = _state()
    if updated_at is None:
        del payload["updated_at"]
    else:
        payload["updated_at"] = updated_at
    _write_state(state_path, payload)

    with pytest.raises(manager.PermitError, match=reason):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert not permit_parent.exists()


@pytest.mark.parametrize("ttl", [0, 3601])
def test_issue_rejects_out_of_range_ttl(authority: tuple[Path, Path], ttl: int) -> None:
    state_path, permit_parent = authority
    _write_state(state_path, _state())

    with pytest.raises(manager.PermitError, match="ttl_invalid"):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=ttl,
        )

    assert not permit_parent.exists()


@pytest.mark.parametrize("operation", ["issue", "status"])
def test_state_bound_commands_require_explicit_absolute_state_path(
    authority: tuple[Path, Path], operation: str
) -> None:
    state_path, permit_parent = authority
    if operation == "status":
        _issue(state_path)

    with pytest.raises(manager.PermitError, match="path_not_absolute"):
        if operation == "issue":
            manager.issue(
                state_path=Path("state.json"),
                state_owner_uid=os.geteuid(),
                ttl_seconds=900,
            )
        else:
            manager.status(state_path=Path("state.json"), state_owner_uid=os.geteuid())

    if operation == "issue":
        assert not permit_parent.exists()


@pytest.mark.parametrize("kind", ["mode", "symlink", "hardlink", "fifo"])
def test_state_input_must_be_trusted_and_nonblocking(
    authority: tuple[Path, Path], tmp_path: Path, kind: str
) -> None:
    state_path, permit_parent = authority
    if kind == "mode":
        _write_state(state_path, _state(), mode=0o640)
    elif kind == "symlink":
        target = tmp_path / "real-state.json"
        _write_state(target, _state())
        state_path.symlink_to(target)
    elif kind == "hardlink":
        target = tmp_path / "linked-state.json"
        _write_state(target, _state())
        os.link(target, state_path)
    else:
        os.mkfifo(state_path, 0o600)
        state_path.chmod(0o600)

    started = time.monotonic()
    with pytest.raises(manager.PermitError):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert time.monotonic() - started < 0.5
    assert not permit_parent.exists()


def test_state_owner_uid_must_match(authority: tuple[Path, Path]) -> None:
    state_path, permit_parent = authority
    _write_state(state_path, _state())

    with pytest.raises(manager.PermitError, match="state_untrusted"):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid() + 1,
            ttl_seconds=900,
        )

    assert not permit_parent.exists()


@pytest.mark.parametrize("postwrite_change", ["epoch", "stale"])
def test_postwrite_state_change_removes_just_written_permit(
    authority: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    postwrite_change: str,
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())
    real_read = manager._read_state_with_sha256
    calls = 0

    def changing_read(
        path: Path, *, owner_uid: int
    ) -> tuple[dict[str, object], str]:
        nonlocal calls
        calls += 1
        payload, sha256 = real_read(path, owner_uid=owner_uid)
        if calls == 4:
            payload = dict(payload)
            if postwrite_change == "epoch":
                payload["epoch_started_at"] = "2026-07-13T09:43:56.205Z"
                payload["epoch_started_ms"] = 1783935836205
            else:
                payload["updated_at"] = _timestamp(
                    NOW - timedelta(minutes=5, milliseconds=1)
                )
        return payload, sha256

    monkeypatch.setattr(manager, "_read_state_with_sha256", changing_read)

    reason = "identity_changed" if postwrite_change == "epoch" else "updated_at_stale"
    with pytest.raises(manager.PermitError, match=reason):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert calls == 4
    assert not manager.PERMIT_PATH.exists()
    assert not manager.PERMIT_COMMIT_PATH.exists()


def test_commit_directory_fsync_failure_revokes_authority_and_orphan_permit(
    authority: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())
    real_replace = manager.os.replace
    real_fsync_directory = manager._fsync_directory
    commit_replaced = False
    injected = False

    def observed_replace(source: object, destination: object, *args: object, **kwargs: object) -> None:
        nonlocal commit_replaced
        real_replace(source, destination, *args, **kwargs)
        if Path(destination) == manager.PERMIT_COMMIT_PATH:
            commit_replaced = True

    def fail_once_after_commit(path: Path) -> None:
        nonlocal injected
        if commit_replaced and not injected and path == manager.PERMIT_COMMIT_PATH.parent:
            injected = True
            raise manager.PermitError("injected_commit_directory_fsync_failure")
        real_fsync_directory(path)

    monkeypatch.setattr(manager.os, "replace", observed_replace)
    monkeypatch.setattr(manager, "_fsync_directory", fail_once_after_commit)

    with pytest.raises(
        manager.PermitError,
        match="injected_commit_directory_fsync_failure",
    ):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert injected is True
    assert not manager.PERMIT_COMMIT_PATH.exists()
    assert not manager.PERMIT_PATH.exists()


def test_commit_postpublication_mismatch_revokes_authority_and_orphan_permit(
    authority: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, _permit_parent = authority
    _write_state(state_path, _state())
    real_replace = manager.os.replace
    real_trusted_read = manager._trusted_read
    commit_replaced = False
    injected = False

    def observed_replace(source: object, destination: object, *args: object, **kwargs: object) -> None:
        nonlocal commit_replaced
        real_replace(source, destination, *args, **kwargs)
        if Path(destination) == manager.PERMIT_COMMIT_PATH:
            commit_replaced = True

    def mismatch_once(path: Path, **kwargs: object) -> tuple[bytes, os.stat_result]:
        nonlocal injected
        raw, metadata = real_trusted_read(path, **kwargs)
        if commit_replaced and not injected and path == manager.PERMIT_COMMIT_PATH:
            injected = True
            return raw + b" ", metadata
        return raw, metadata

    monkeypatch.setattr(manager.os, "replace", observed_replace)
    monkeypatch.setattr(manager, "_trusted_read", mismatch_once)

    with pytest.raises(
        manager.PermitError,
        match="commit_postpublication_mismatch",
    ):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert injected is True
    assert not manager.PERMIT_COMMIT_PATH.exists()
    assert not manager.PERMIT_PATH.exists()


def test_status_rejects_expired_permit(
    authority: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    later = NOW + timedelta(hours=2)
    payload = _state()
    payload["updated_at"] = _timestamp(later)
    _write_state(state_path, payload)
    monkeypatch.setattr(manager, "_utc_now_datetime", lambda: later)

    with pytest.raises(manager.PermitError, match="permit_not_current"):
        _status(state_path)


def test_status_rejects_permit_bound_to_previous_epoch(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    rolled = _state()
    rolled["epoch_started_at"] = "2026-07-13T09:43:56.205Z"
    rolled["epoch_started_ms"] = 1783935836205
    _write_state(state_path, rolled)

    with pytest.raises(manager.PermitError, match="state_binding_mismatch"):
        _status(state_path)


def test_status_rejects_epoch_rollover_during_read(
    authority: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    real_read = manager._read_state_with_sha256
    calls = 0

    def changing_read(
        path: Path, *, owner_uid: int
    ) -> tuple[dict[str, object], str]:
        nonlocal calls
        calls += 1
        payload, sha256 = real_read(path, owner_uid=owner_uid)
        if calls == 2:
            payload = dict(payload)
            payload["epoch_started_at"] = "2026-07-13T09:43:56.205Z"
            payload["epoch_started_ms"] = 1783935836205
        return payload, sha256

    monkeypatch.setattr(manager, "_read_state_with_sha256", changing_read)

    with pytest.raises(manager.PermitError, match="identity_changed"):
        _status(state_path)


def test_status_denies_while_issuer_lock_is_exclusive(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    descriptor = os.open(manager.LOCK_PATH, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(manager.PermitError, match="lock_busy"):
            _status(state_path)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@pytest.mark.parametrize("kind", ["mode", "symlink", "hardlink"])
def test_status_requires_trusted_stable_lock(
    authority: tuple[Path, Path], tmp_path: Path, kind: str
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    manager.LOCK_PATH.unlink()
    if kind == "mode":
        manager.LOCK_PATH.touch()
        manager.LOCK_PATH.chmod(0o664)
    elif kind == "symlink":
        target = tmp_path / "real-lock"
        target.touch(mode=0o644)
        manager.LOCK_PATH.symlink_to(target)
    else:
        target = tmp_path / "linked-lock"
        target.touch(mode=0o644)
        os.link(target, manager.LOCK_PATH)

    with pytest.raises(manager.PermitError, match="permit_lock_"):
        _status(state_path)


def test_reissue_refuses_handwritten_or_corrupt_existing_permit(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    manager.PERMIT_PATH.write_text('{"status":"allow"}\n', encoding="utf-8")
    before = manager.PERMIT_PATH.read_bytes()

    with pytest.raises(manager.PermitError, match="permit_schema_invalid"):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert manager.PERMIT_PATH.read_bytes() == before


def test_revoke_refuses_untrusted_permit_target(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    manager.PERMIT_PATH.chmod(0o666)

    with pytest.raises(manager.PermitError, match="permit_untrusted"):
        manager.revoke()

    assert manager.PERMIT_PATH.exists()


def test_cli_status_emits_bounded_non_secret_json(
    authority: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)

    assert (
        manager.main(
            [
                "status",
                "--state-path",
                str(state_path),
                "--state-owner-uid",
                str(os.geteuid()),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert len(output) < 4096
    payload = json.loads(output)
    assert payload["status"] == "valid"
    assert "state_path" not in payload
    assert "token" not in output.lower()


def test_issue_requires_exact_epoch_root_certificate_before_writing_permit(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    state = _state()
    _write_state(state_path, state)
    certificate_path, sidecar_path = manager._qualification_certificate_paths(
        int(state["epoch_started_ms"])
    )
    certificate_path.unlink()
    sidecar_path.unlink()

    with pytest.raises(
        manager.PermitError, match="vexp_qualification_certificate_unavailable"
    ):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert not manager.PERMIT_PATH.exists()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("missing_boot", "duration_invalid"),
        ("invalid_boot", "duration_invalid"),
        ("missing_start", "duration_invalid"),
        ("missing_end", "duration_invalid"),
        ("inexact_delta", "duration_invalid"),
        ("terminal_boot", "terminal_state_invalid"),
        ("terminal_start", "terminal_state_invalid"),
        ("terminal_end", "terminal_state_invalid"),
    ],
)
def test_certificate_v2_requires_exact_boot_and_monotonic_endpoints(
    change: str, reason: str
) -> None:
    state = _state()
    certificate = _certificate(state)
    terminal_state = dict(certificate["terminal_state"])
    certificate["terminal_state"] = terminal_state
    if change == "missing_boot":
        certificate.pop("qualification_boot_id")
    elif change == "invalid_boot":
        certificate["qualification_boot_id"] = "not-a-boot-id"
    elif change == "missing_start":
        certificate.pop("qualification_monotonic_started_ns")
    elif change == "missing_end":
        certificate.pop("qualification_monotonic_qualified_ns")
    elif change == "inexact_delta":
        certificate["qualification_monotonic_qualified_ns"] = (
            int(certificate["qualification_monotonic_qualified_ns"]) + 1
        )
    elif change == "terminal_boot":
        terminal_state["qualification_boot_id"] = (
            "11111111-1111-4111-8111-111111111111"
        )
    elif change == "terminal_start":
        terminal_state["qualification_monotonic_started_ns"] = 2_000_000_000
    else:
        terminal_state["qualification_monotonic_qualified_ns"] = (
            int(terminal_state["qualification_monotonic_qualified_ns"]) + 1
        )
    certificate.pop("identity")
    certificate["identity"] = (
        f"sha256:{manager._canonical_json_sha256(certificate)}"
    )

    with pytest.raises(manager.PermitError, match=reason):
        manager._validate_qualification_certificate(certificate, state=state)


def test_issue_plane_denies_when_reviewed_implementation_manifest_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "reviewed-implementation-manifest.json"
    monkeypatch.setattr(
        manager, "QUALIFICATION_IMPLEMENTATION_MANIFEST_PATH", missing
    )

    with pytest.raises(
        manager.PermitError,
        match="vexp_qualification_implementation_manifest_missing",
    ):
        REAL_REQUIRE_IMPLEMENTATION_MANIFEST(_certificate(_state()))


@pytest.mark.parametrize(
    ("target", "mode"),
    [
        ("root", 0o755),
        ("directory", 0o755),
        ("certificate", 0o644),
        ("sidecar", 0o644),
    ],
)
def test_issue_rejects_untrusted_certificate_authority_metadata(
    authority: tuple[Path, Path], target: str, mode: int
) -> None:
    state_path, _permit_parent = authority
    state = _state()
    _write_state(state_path, state)
    certificate_path, sidecar_path = manager._qualification_certificate_paths(
        int(state["epoch_started_ms"])
    )
    selected = {
        "root": manager.QUALIFICATION_CERTIFICATE_ROOT,
        "directory": manager.QUALIFICATION_CERTIFICATE_DIRECTORY,
        "certificate": certificate_path,
        "sidecar": sidecar_path,
    }[target]
    selected.chmod(mode)

    with pytest.raises(manager.PermitError, match="qualification_certificate"):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert not manager.PERMIT_PATH.exists()


def test_status_rejects_certificate_removed_after_permit_issue(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    state = _state()
    certificate_path, _sidecar_path = manager._qualification_certificate_paths(
        int(state["epoch_started_ms"])
    )
    certificate_path.unlink()

    with pytest.raises(
        manager.PermitError, match="vexp_qualification_certificate_unavailable"
    ):
        _status(state_path)


def test_status_rejects_well_formed_permit_with_wrong_certificate_binding(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path)
    permit = json.loads(manager.PERMIT_PATH.read_text(encoding="utf-8"))
    permit["qualification_certificate_sha256"] = "0" * 64
    raw = (
        json.dumps(permit, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    manager.PERMIT_PATH.write_text(raw, encoding="utf-8")
    manager.PERMIT_PATH.chmod(manager.PERMIT_MODE)
    commit = manager._permit_commit_payload(
        permit,
        permit_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
    manager.PERMIT_COMMIT_PATH.write_text(
        json.dumps(
            commit,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manager.PERMIT_COMMIT_PATH.chmod(manager.PERMIT_COMMIT_MODE)

    with pytest.raises(
        manager.PermitError, match="certificate_binding_mismatch"
    ):
        _status(state_path)


def _write_root_contract(path: Path, payload: dict[str, object]) -> str:
    raw = manager._canonical_record_bytes(payload)
    path.write_bytes(raw)
    path.chmod(manager.CANDIDATE_AUTHORITY_RECORD_MODE)
    return hashlib.sha256(raw).hexdigest()


def _install_current_predicate_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    generation: int = 1,
    previous_sha256: str | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, str], str]:
    root = tmp_path / "predicate"
    records = root / "records"
    root.mkdir(mode=manager.CURRENT_PREDICATE_DIRECTORY_MODE)
    records.mkdir(mode=manager.CURRENT_PREDICATE_DIRECTORY_MODE)
    root.chmod(manager.CURRENT_PREDICATE_DIRECTORY_MODE)
    records.chmod(manager.CURRENT_PREDICATE_DIRECTORY_MODE)
    trusted_producer_parent = tmp_path / "root-producers"
    trusted_producer_parent.mkdir(
        mode=manager.TRUSTED_ROOT_PRODUCER_DIRECTORY_MODE
    )
    trusted_producer_parent.chmod(manager.TRUSTED_ROOT_PRODUCER_DIRECTORY_MODE)
    current_predicate_producer = trusted_producer_parent / "current-predicate-attestor"
    current_predicate_producer.write_bytes(b"test current predicate attestor\n")
    current_predicate_producer.chmod(manager.TRUSTED_ROOT_PRODUCER_MODE)
    current_predicate_producer_sha256 = hashlib.sha256(
        current_predicate_producer.read_bytes()
    ).hexdigest()
    monkeypatch.setattr(manager, "ROOT_UID", os.geteuid())
    monkeypatch.setattr(manager, "ROOT_GID", os.getegid())
    monkeypatch.setattr(
        manager,
        "TRUSTED_ROOT_PRODUCER_INSTALL_PARENT",
        trusted_producer_parent,
    )
    monkeypatch.setattr(
        manager,
        "CURRENT_PREDICATE_PRODUCER_PATH",
        current_predicate_producer,
    )
    monkeypatch.setattr(manager, "CURRENT_PREDICATE_OWNER_UID", os.geteuid())
    monkeypatch.setattr(manager, "CURRENT_PREDICATE_OWNER_GID", os.getegid())
    monkeypatch.setattr(manager, "TRUSTED_AUTHORITY_STORAGE_PREFIX", tmp_path)
    monkeypatch.setattr(manager, "CURRENT_PREDICATE_ROOT", root)
    monkeypatch.setattr(manager, "CURRENT_PREDICATE_RECORD_DIRECTORY", records)
    monkeypatch.setattr(manager, "CURRENT_PREDICATE_POINTER_PATH", root / "current.json")
    monkeypatch.setattr(
        manager,
        "CURRENT_PREDICATE_PRODUCER_MANIFEST_PATH",
        root / "producer-manifest.json",
    )
    monkeypatch.setattr(
        manager,
        "_current_boot_id",
        lambda: "12345678-1234-4234-9234-123456789abc",
    )
    monkeypatch.setattr(manager, "_monotonic_ns", lambda: 10_000_000_000)
    state = _state()
    state_path = tmp_path / "state.json"
    state_sha256 = hashlib.sha256(
        (json.dumps(state, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()
    certificate = _certificate(state)
    qualification = {
        "schema": manager.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA,
        "identity": str(certificate["identity"]),
        "event_hash": "b" * 64,
        "sha256": "a" * 64,
    }
    _write_root_contract(
        root / "producer-manifest.json",
        {
            "contract_name": (
                manager.VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_CONTRACT_NAME
            ),
            "version": manager.VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_VERSION,
            "status": "reviewed",
            "producer_path": str(manager.CURRENT_PREDICATE_PRODUCER_PATH),
            "producer_sha256": current_predicate_producer_sha256,
        },
    )
    record = {
        "contract_name": manager.VEXP_CURRENT_PREDICATE_CONTRACT_NAME,
        "version": manager.VEXP_CURRENT_PREDICATE_VERSION,
        "status": "positive",
        "epoch_started_ms": state["epoch_started_ms"],
        "generation": generation,
        "observed_at": state["updated_at"],
        "recorded_at": state["updated_at"],
        "boot_id": "12345678-1234-4234-9234-123456789abc",
        "monotonic_ns": 9_000_000_000,
        "sentinel_state_path": str(state_path),
        "sentinel_state_owner_uid": os.geteuid(),
        "sentinel_state_sha256": state_sha256,
        "terminal_identity_sha256": manager._terminal_identity_sha256(state),
        "qualification_certificate_sha256": qualification["sha256"],
        "predicate_contract_sha256": state["predicate_contract_sha256"],
        "current_resources_healthy": True,
        "certification_blockers": [],
        "certification_deferments": [],
        "sentinel_producer_sha256": "1" * 64,
        "root_predicate_producer_sha256": current_predicate_producer_sha256,
        "previous_record_sha256": (
            "0" * 64 if generation == 1 else str(previous_sha256 or "f" * 64)
        ),
    }
    record_path = records / f"{state['epoch_started_ms']}-{generation}.json"
    record_sha256 = _write_root_contract(record_path, record)
    _write_root_contract(
        root / "current.json",
        {
            "contract_name": manager.VEXP_CURRENT_PREDICATE_POINTER_CONTRACT_NAME,
            "version": manager.VEXP_CURRENT_PREDICATE_POINTER_VERSION,
            "status": "published",
            "epoch_started_ms": state["epoch_started_ms"],
            "generation": generation,
            "record_path": str(record_path),
            "record_sha256": record_sha256,
        },
    )
    return state, certificate, qualification, state_sha256


def _append_current_predicate_record(state: Mapping[str, object]) -> Path:
    pointer_path = manager.CURRENT_PREDICATE_POINTER_PATH
    pointer = json.loads(pointer_path.read_bytes())
    previous_path = Path(str(pointer["record_path"]))
    previous = json.loads(previous_path.read_bytes())
    generation = int(pointer["generation"]) + 1
    record = {
        **previous,
        "generation": generation,
        "monotonic_ns": int(previous["monotonic_ns"]) + 1,
        "previous_record_sha256": str(pointer["record_sha256"]),
    }
    record_path = (
        manager.CURRENT_PREDICATE_RECORD_DIRECTORY
        / f"{state['epoch_started_ms']}-{generation}.json"
    )
    record_sha256 = _write_root_contract(record_path, record)
    pointer.update(
        {
            "generation": generation,
            "record_path": str(record_path),
            "record_sha256": record_sha256,
        }
    )
    _write_root_contract(pointer_path, pointer)
    return record_path


def _read_installed_current_predicate(
    *,
    tmp_path: Path,
    state: dict[str, object],
    certificate: dict[str, object],
    qualification: dict[str, str],
    state_sha256: str,
) -> dict[str, object]:
    return REAL_READ_CURRENT_PREDICATE(
        state=state,
        state_sha256=state_sha256,
        state_path=tmp_path / "state.json",
        state_owner_uid=os.geteuid(),
        certificate=certificate,
        qualification_certificate=qualification,
        now=NOW,
    )


def test_current_predicate_root_contract_binds_state_certificate_and_producers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, certificate, qualification, state_sha256 = (
        _install_current_predicate_contract(tmp_path, monkeypatch)
    )
    evidence = REAL_READ_CURRENT_PREDICATE(
        state=state,
        state_sha256=state_sha256,
        state_path=tmp_path / "state.json",
        state_owner_uid=os.geteuid(),
        certificate=certificate,
        qualification_certificate=qualification,
        now=NOW,
    )
    assert evidence["generation"] == 1
    assert evidence["sentinel_producer_sha256"] == "1" * 64
    assert evidence["root_predicate_producer_sha256"] == hashlib.sha256(
        manager.CURRENT_PREDICATE_PRODUCER_PATH.read_bytes()
    ).hexdigest()


def test_issue_denies_when_external_root_predicate_plumbing_is_absent(
    authority: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, _permit_parent = authority
    monkeypatch.setattr(
        manager, "_read_current_predicate_evidence", REAL_READ_CURRENT_PREDICATE
    )
    with pytest.raises(manager.PermitError, match="current_predicate"):
        _issue(state_path)
    assert not manager.PERMIT_PATH.exists()


def test_current_predicate_generation_requires_exact_previous_root_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, certificate, qualification, state_sha256 = (
        _install_current_predicate_contract(
            tmp_path, monkeypatch, generation=2, previous_sha256="f" * 64
        )
    )
    with pytest.raises(manager.PermitError, match="generation_chain_invalid"):
        REAL_READ_CURRENT_PREDICATE(
            state=state,
            state_sha256=state_sha256,
            state_path=tmp_path / "state.json",
            state_owner_uid=os.geteuid(),
            certificate=certificate,
            qualification_certificate=qualification,
            now=NOW,
        )


def test_current_predicate_full_chain_rejects_internal_generation_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, certificate, qualification, state_sha256 = (
        _install_current_predicate_contract(tmp_path, monkeypatch)
    )
    _append_current_predicate_record(state)
    _append_current_predicate_record(state)
    (
        manager.CURRENT_PREDICATE_RECORD_DIRECTORY
        / f"{state['epoch_started_ms']}-2.json"
    ).unlink()

    with pytest.raises(manager.PermitError, match="generation_chain_invalid"):
        _read_installed_current_predicate(
            tmp_path=tmp_path,
            state=state,
            certificate=certificate,
            qualification=qualification,
            state_sha256=state_sha256,
        )


@pytest.mark.parametrize("tamper", ["alternate_fork", "nonmaximal_head"])
def test_current_predicate_full_chain_rejects_fork_or_nonmaximal_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    state, certificate, qualification, state_sha256 = (
        _install_current_predicate_contract(tmp_path, monkeypatch)
    )
    _append_current_predicate_record(state)
    if tamper == "alternate_fork":
        fork = (
            manager.CURRENT_PREDICATE_RECORD_DIRECTORY
            / f"{state['epoch_started_ms']}-2.fork.json"
        )
        fork.write_bytes(b"{}\n")
        fork.chmod(manager.CURRENT_PREDICATE_RECORD_MODE)
    else:
        pointer_path = manager.CURRENT_PREDICATE_POINTER_PATH
        prior_pointer_raw = pointer_path.read_bytes()
        _append_current_predicate_record(state)
        pointer_path.write_bytes(prior_pointer_raw)
        pointer_path.chmod(manager.CURRENT_PREDICATE_RECORD_MODE)

    with pytest.raises(manager.PermitError, match="generation_chain_invalid"):
        _read_installed_current_predicate(
            tmp_path=tmp_path,
            state=state,
            certificate=certificate,
            qualification=qualification,
            state_sha256=state_sha256,
        )


def test_current_predicate_full_chain_rejects_rehashed_unhealthy_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, certificate, qualification, state_sha256 = (
        _install_current_predicate_contract(tmp_path, monkeypatch)
    )
    second_path = _append_current_predicate_record(state)
    third_path = _append_current_predicate_record(state)
    first_path = (
        manager.CURRENT_PREDICATE_RECORD_DIRECTORY
        / f"{state['epoch_started_ms']}-1.json"
    )
    first = json.loads(first_path.read_bytes())
    first["current_resources_healthy"] = False
    first_sha256 = _write_root_contract(first_path, first)
    second = json.loads(second_path.read_bytes())
    second["previous_record_sha256"] = first_sha256
    second_sha256 = _write_root_contract(second_path, second)
    third = json.loads(third_path.read_bytes())
    third["previous_record_sha256"] = second_sha256
    third_sha256 = _write_root_contract(third_path, third)
    pointer = json.loads(manager.CURRENT_PREDICATE_POINTER_PATH.read_bytes())
    pointer["record_sha256"] = third_sha256
    _write_root_contract(manager.CURRENT_PREDICATE_POINTER_PATH, pointer)

    with pytest.raises(manager.PermitError, match="generation_chain_invalid"):
        _read_installed_current_predicate(
            tmp_path=tmp_path,
            state=state,
            certificate=certificate,
            qualification=qualification,
            state_sha256=state_sha256,
        )


def test_current_predicate_full_chain_rejects_current_boot_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, certificate, qualification, state_sha256 = (
        _install_current_predicate_contract(tmp_path, monkeypatch)
    )
    _append_current_predicate_record(state)
    monkeypatch.setattr(
        manager,
        "_current_boot_id",
        lambda: "11111111-1111-4111-8111-111111111111",
    )

    with pytest.raises(manager.PermitError, match="generation_chain_invalid"):
        _read_installed_current_predicate(
            tmp_path=tmp_path,
            state=state,
            certificate=certificate,
            qualification=qualification,
            state_sha256=state_sha256,
        )


def _candidate_producer_manifest() -> dict[str, object]:
    attestor_sha256 = hashlib.sha256(
        manager.CANDIDATE_AUTHORITY_ATTESTOR_PATH.read_bytes()
    ).hexdigest()
    return {
        "contract_name": (
            manager.VEXP_CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_CONTRACT_NAME
        ),
        "version": manager.VEXP_CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_VERSION,
        "status": "reviewed",
        "attestor_path": str(manager.CANDIDATE_AUTHORITY_ATTESTOR_PATH),
        "attestor_sha256": attestor_sha256,
        "allowed_producers": [
            {"receipt_kind": "candidate_runtime", "producer_sha256": "d" * 64},
            {"receipt_kind": "image_build", "producer_sha256": "c" * 64},
        ],
    }


def test_candidate_seal_denies_without_external_root_boundary_events(
    authority: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, _permit_parent = authority
    _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    status = _status(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    candidate_path, candidate_sha, _image_path, _image_sha = (
        _write_candidate_seal_receipts(
            state_path.parent,
            candidate_status=status,
        )
    )
    monkeypatch.setattr(
        manager,
        "_read_candidate_operation_evidence",
        REAL_READ_CANDIDATE_OPERATION_EVIDENCE,
    )
    with pytest.raises(manager.PermitError, match="boundary_event_unavailable"):
        manager.seal_candidate(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            candidate_receipt_path=candidate_path,
            candidate_receipt_sha256=candidate_sha,
        )
    assert not (
        manager.CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY
        / f"{status['permit_sha256']}.json"
    ).exists()


def test_candidate_root_events_and_publication_are_required_and_revocable(
    authority: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, _permit_parent = authority
    status = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    issuance, _issuance_sha256 = manager._read_candidate_issuance_record(
        str(status["permit_sha256"])
    )
    _write_root_contract(
        manager.CANDIDATE_AUTHORITY_PRODUCER_MANIFEST_PATH,
        _candidate_producer_manifest(),
    )
    attestor_sha256 = str(_candidate_producer_manifest()["attestor_sha256"])
    predicate = dict(status["current_predicate"])
    resource = {
        "argv": ["fixture-candidate-runner", "compose-up"],
        "target": "fixture:candidate-project",
    }
    operation = {
        "boundary": "before_candidate_up",
        "operation": "compose_up",
        "resource": resource,
        "resource_sha256": manager._canonical_json_sha256(resource),
        "current_predicate_generation": predicate["generation"],
        "current_predicate_record_sha256": predicate["record_sha256"],
    }
    event_path = manager._candidate_boundary_event_path(
        permit_sha256=str(status["permit_sha256"]),
        receipt_kind="candidate_runtime",
        sequence=1,
    )
    event = {
        "contract_name": manager.VEXP_CANDIDATE_BOUNDARY_EVENT_CONTRACT_NAME,
        "version": manager.VEXP_CANDIDATE_BOUNDARY_EVENT_VERSION,
        "status": "succeeded",
        "receipt_kind": "candidate_runtime",
        "sequence": 1,
        "event_nonce": "1" * 64,
        "permit_sha256": status["permit_sha256"],
        "permit_commit_sha256": dict(status["permit_commit"])["sha256"],
        "epoch_started_ms": status["epoch_started_ms"],
        "qualification_certificate_sha256": status[
            "qualification_certificate_sha256"
        ],
        "current_predicate_generation": predicate["generation"],
        "current_predicate_record_sha256": dict(status["current_predicate"])[
            "record_sha256"
        ],
        "boundary": operation["boundary"],
        "operation": operation["operation"],
        "resource_sha256": operation["resource_sha256"],
        "producer_sha256": "d" * 64,
        "root_attestor_sha256": attestor_sha256,
        "boot_id": "12345678-1234-4234-9234-123456789abc",
        "opened_at": _timestamp(NOW),
        "closed_at": _timestamp(NOW),
        "opened_monotonic_ns": 8_000_000_000,
        "closed_monotonic_ns": 9_000_000_000,
        "deadline_monotonic_ns": 11_000_000_000,
        "previous_event_sha256": "0" * 64,
    }
    event_sha256 = _write_root_contract(event_path, event)
    operation_evidence = REAL_READ_CANDIDATE_OPERATION_EVIDENCE(
        issuance=issuance,
        receipt_kind="candidate_runtime",
        operations=[operation],
        producer_sha256="d" * 64,
        now=NOW,
    )
    assert operation_evidence["tail_sha256"] == event_sha256

    receipt_path = state_path.parent / "runtime.json"
    receipt_sha256 = "4" * 64
    publication_path = manager._candidate_publication_evidence_path(
        permit_sha256=str(status["permit_sha256"]),
        receipt_kind="candidate_runtime",
        receipt_sha256=receipt_sha256,
    )
    publication = {
        "contract_name": manager.VEXP_CANDIDATE_PUBLICATION_EVIDENCE_CONTRACT_NAME,
        "version": manager.VEXP_CANDIDATE_PUBLICATION_EVIDENCE_VERSION,
        "status": "published",
        "receipt_kind": "candidate_runtime",
        "permit_sha256": status["permit_sha256"],
        "permit_commit_sha256": dict(status["permit_commit"])["sha256"],
        "epoch_started_ms": status["epoch_started_ms"],
        "qualification_certificate_sha256": status[
            "qualification_certificate_sha256"
        ],
        "current_predicate_record_sha256": dict(status["current_predicate"])[
            "record_sha256"
        ],
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
        "producer_sha256": "d" * 64,
        "root_attestor_sha256": attestor_sha256,
        "operation_tail_sha256": event_sha256,
        "boot_id": "12345678-1234-4234-9234-123456789abc",
        "published_at": _timestamp(NOW),
        "published_monotonic_ns": 9_500_000_000,
        "deadline_monotonic_ns": 11_000_000_000,
    }
    publication_sha256 = _write_root_contract(publication_path, publication)
    _payload, observed_sha256 = REAL_READ_CANDIDATE_PUBLICATION_EVIDENCE(
        issuance=issuance,
        receipt_kind="candidate_runtime",
        receipt_path=str(receipt_path),
        receipt_sha256=receipt_sha256,
        producer_sha256="d" * 64,
        operation_evidence=operation_evidence,
        receipt_timestamp=_timestamp(NOW),
        now=NOW,
    )
    assert observed_sha256 == publication_sha256

    future_monotonic_publication = dict(publication)
    future_monotonic_publication["published_monotonic_ns"] = 10_500_000_000
    _write_root_contract(publication_path, future_monotonic_publication)
    with pytest.raises(manager.PermitError, match="publication_evidence_invalid"):
        REAL_READ_CANDIDATE_PUBLICATION_EVIDENCE(
            issuance=issuance,
            receipt_kind="candidate_runtime",
            receipt_path=str(receipt_path),
            receipt_sha256=receipt_sha256,
            producer_sha256="d" * 64,
            operation_evidence=operation_evidence,
            receipt_timestamp=_timestamp(NOW),
            now=NOW,
        )
    future_wall_publication = dict(publication)
    future_wall_publication["published_at"] = _timestamp(NOW + timedelta(seconds=1))
    _write_root_contract(publication_path, future_wall_publication)
    with pytest.raises(manager.PermitError, match="publication_evidence_invalid"):
        REAL_READ_CANDIDATE_PUBLICATION_EVIDENCE(
            issuance=issuance,
            receipt_kind="candidate_runtime",
            receipt_path=str(receipt_path),
            receipt_sha256=receipt_sha256,
            producer_sha256="d" * 64,
            operation_evidence=operation_evidence,
            receipt_timestamp=_timestamp(NOW),
            now=NOW,
        )
    _write_root_contract(publication_path, publication)
    monkeypatch.setattr(manager, "_monotonic_ns", lambda: 10_000_000_000)

    _write_root_contract(
        manager.CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY
        / f"{publication_sha256}.json",
        {"status": "revoked"},
    )
    with pytest.raises(manager.PermitError, match="publication_revoked"):
        REAL_READ_CANDIDATE_PUBLICATION_EVIDENCE(
            issuance=issuance,
            receipt_kind="candidate_runtime",
            receipt_path=str(receipt_path),
            receipt_sha256=receipt_sha256,
            producer_sha256="d" * 64,
            operation_evidence=operation_evidence,
            receipt_timestamp=_timestamp(NOW),
            now=NOW,
        )
    monkeypatch.setattr(manager, "_monotonic_ns", lambda: 12_000_000_000)
    with pytest.raises(manager.PermitError, match="publication_evidence_invalid"):
        REAL_READ_CANDIDATE_PUBLICATION_EVIDENCE(
            issuance=issuance,
            receipt_kind="candidate_runtime",
            receipt_path=str(receipt_path),
            receipt_sha256=receipt_sha256,
            producer_sha256="d" * 64,
            operation_evidence=operation_evidence,
            receipt_timestamp=_timestamp(NOW),
            now=NOW,
        )


def test_candidate_root_events_deny_overlapping_wall_and_monotonic_order(
    authority: tuple[Path, Path],
) -> None:
    state_path, _permit_parent = authority
    status = _issue(state_path, permit_mode=manager.CANDIDATE_PERMIT_MODE)
    issuance, _issuance_sha256 = manager._read_candidate_issuance_record(
        str(status["permit_sha256"])
    )
    attestor_sha256 = str(_candidate_producer_manifest()["attestor_sha256"])
    predicate = dict(status["current_predicate"])
    up_resource = {
        "argv": ["fixture-candidate-runner", "compose-up"],
        "target": "fixture:candidate-project",
    }
    exec_resource = {
        "argv": ["fixture-candidate-runner", "redis-ping"],
        "target": "fixture:candidate-api",
    }
    operations = [
        {
            "boundary": "before_candidate_up",
            "operation": "compose_up",
            "resource": up_resource,
            "resource_sha256": manager._canonical_json_sha256(up_resource),
            "current_predicate_generation": predicate["generation"],
            "current_predicate_record_sha256": predicate["record_sha256"],
        },
        {
            "boundary": "before_candidate_exec",
            "operation": "redis_ping",
            "resource": exec_resource,
            "resource_sha256": manager._canonical_json_sha256(exec_resource),
            "current_predicate_generation": predicate["generation"],
            "current_predicate_record_sha256": predicate["record_sha256"],
        },
    ]
    first = {
        "contract_name": manager.VEXP_CANDIDATE_BOUNDARY_EVENT_CONTRACT_NAME,
        "version": manager.VEXP_CANDIDATE_BOUNDARY_EVENT_VERSION,
        "status": "succeeded",
        "receipt_kind": "candidate_runtime",
        "sequence": 1,
        "event_nonce": "1" * 64,
        "permit_sha256": status["permit_sha256"],
        "permit_commit_sha256": dict(status["permit_commit"])["sha256"],
        "epoch_started_ms": status["epoch_started_ms"],
        "qualification_certificate_sha256": status[
            "qualification_certificate_sha256"
        ],
        "current_predicate_generation": operations[0][
            "current_predicate_generation"
        ],
        "current_predicate_record_sha256": operations[0][
            "current_predicate_record_sha256"
        ],
        "boundary": operations[0]["boundary"],
        "operation": operations[0]["operation"],
        "resource_sha256": operations[0]["resource_sha256"],
        "producer_sha256": "d" * 64,
        "root_attestor_sha256": attestor_sha256,
        "boot_id": "12345678-1234-4234-9234-123456789abc",
        "opened_at": _timestamp(NOW),
        "closed_at": _timestamp(NOW + timedelta(seconds=1)),
        "opened_monotonic_ns": 8_000_000_000,
        "closed_monotonic_ns": 9_000_000_000,
        "deadline_monotonic_ns": 11_000_000_000,
        "previous_event_sha256": "0" * 64,
    }
    first_path = manager._candidate_boundary_event_path(
        permit_sha256=str(status["permit_sha256"]),
        receipt_kind="candidate_runtime",
        sequence=1,
    )
    first_sha256 = _write_root_contract(first_path, first)
    second = {
        **first,
        "sequence": 2,
        "event_nonce": "2" * 64,
        "current_predicate_generation": operations[1][
            "current_predicate_generation"
        ],
        "current_predicate_record_sha256": operations[1][
            "current_predicate_record_sha256"
        ],
        "boundary": operations[1]["boundary"],
        "operation": operations[1]["operation"],
        "resource_sha256": operations[1]["resource_sha256"],
        "opened_at": _timestamp(NOW + timedelta(milliseconds=500)),
        "closed_at": _timestamp(NOW + timedelta(seconds=2)),
        "opened_monotonic_ns": 8_500_000_000,
        "closed_monotonic_ns": 9_500_000_000,
        "previous_event_sha256": first_sha256,
    }
    _write_root_contract(
        manager._candidate_boundary_event_path(
            permit_sha256=str(status["permit_sha256"]),
            receipt_kind="candidate_runtime",
            sequence=2,
        ),
        second,
    )

    with pytest.raises(manager.PermitError, match="boundary_evidence_invalid"):
        REAL_READ_CANDIDATE_OPERATION_EVIDENCE(
            issuance=issuance,
            receipt_kind="candidate_runtime",
            operations=operations,
            producer_sha256="d" * 64,
            now=NOW + timedelta(seconds=2),
        )
