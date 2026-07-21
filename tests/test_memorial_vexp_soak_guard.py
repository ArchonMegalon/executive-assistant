from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import re
import socket
import stat
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Sequence
from unittest.mock import Mock

import pytest

from scripts import deploy_ea_memorial as deploy
from scripts import provision_memorial_gemini_oauth as oauth_provision
from scripts.deploy_ea_memorial import DeployError, MemorialDeployLane


NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
TEST_BOOT_ID = "01234567-89ab-4cde-8f01-23456789abcd"
TEST_MONOTONIC_NS = 600_000_000_000
TEST_ROOT_PREDICATE_PRODUCER_BYTES = b"test root predicate producer\n"
TEST_ROOT_PREDICATE_PRODUCER_SHA256 = hashlib.sha256(
    TEST_ROOT_PREDICATE_PRODUCER_BYTES
).hexdigest()
TEST_GEMINI_OAUTH_BYTES = (
    json.dumps(
        {
            "refresh_token": "soak-guard-oauth-secret",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "token_type": "Bearer",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n"
).encode("utf-8")


@pytest.fixture(autouse=True)
def _exercise_existing_soak_contract_past_incident_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deploy,
        "_require_credential_exposure_remediation",
        lambda: None,
    )


def _gemini_oauth_snapshot() -> oauth_provision.CredentialSnapshot:
    return oauth_provision.CredentialSnapshot(
        TEST_GEMINI_OAUTH_BYTES,
        oauth_provision.CredentialMetadata(
            schema=oauth_provision.CONTRACT,
            status="snapshotted",
            sha256=hashlib.sha256(TEST_GEMINI_OAUTH_BYTES).hexdigest(),
            size_bytes=len(TEST_GEMINI_OAUTH_BYTES),
            uid=os.geteuid(),
            gid=os.getegid(),
            mode="0600",
            device=1,
            inode=1,
        ),
    )


def _gemini_oauth_binding() -> dict[str, object]:
    with _gemini_oauth_snapshot() as snapshot:
        return MemorialDeployLane._gemini_oauth_binding_from_snapshot(snapshot)


class TestVexpMemorialMutationAuthority(deploy.VexpMemorialMutationAuthority):
    __test__ = False

    def __init__(
        self,
        *,
        state_path: Path,
        certificate_root: Path,
        certificate_directory: Path,
        certificate_owner_uid: int,
        certificate_owner_gid: int,
        permit_path: Path,
        permit_commit_path: Path,
        lock_path: Path,
        permit_owner_uid: int,
        permit_commit_owner_uid: int,
        lock_owner_uid: int,
        epoch_void_ledger_root: Path,
        epoch_void_ledger_owner_uid: int,
        epoch_void_ledger_owner_gid: int,
        current_predicate_trusted_parent: Path,
        current_predicate_root: Path,
        current_predicate_owner_uid: int,
        current_predicate_owner_gid: int,
        current_boot_id: str,
        monotonic_ns: Callable[[], int],
        utc_now: Callable[[], datetime],
    ) -> None:
        self._state_path = state_path
        self._certificate_root = certificate_root
        self._certificate_directory = certificate_directory
        self._certificate_owner_uid = certificate_owner_uid
        self._certificate_owner_gid = certificate_owner_gid
        self._permit_path = permit_path
        self._permit_commit_path = permit_commit_path
        self._lock_path = lock_path
        self._permit_owner_uid = permit_owner_uid
        self._permit_commit_owner_uid = permit_commit_owner_uid
        self._lock_owner_uid = lock_owner_uid
        self._epoch_void_ledger_root = epoch_void_ledger_root
        self._epoch_void_ledger_owner_uid = epoch_void_ledger_owner_uid
        self._epoch_void_ledger_owner_gid = epoch_void_ledger_owner_gid
        self._current_predicate_trusted_parent = (
            current_predicate_trusted_parent
        )
        self._current_predicate_root = current_predicate_root
        self._current_predicate_owner_uid = current_predicate_owner_uid
        self._current_predicate_owner_gid = current_predicate_owner_gid
        self._current_boot_id = current_boot_id
        self._monotonic_ns = monotonic_ns
        self._utc_now = utc_now

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
        return self._certificate_owner_uid

    @property
    def qualification_certificate_owner_gid(self) -> int:
        return self._certificate_owner_gid

    @property
    def mutation_permit_owner_uid(self) -> int:
        return self._permit_owner_uid

    @property
    def mutation_permit_owner_gid(self) -> int:
        return os.getegid()

    @property
    def mutation_permit_commit_path(self) -> Path:
        return self._permit_commit_path

    @property
    def mutation_permit_commit_owner_uid(self) -> int:
        return self._permit_commit_owner_uid

    @property
    def mutation_permit_commit_owner_gid(self) -> int:
        return os.getegid()

    @property
    def mutation_permit_lock_path(self) -> Path:
        return self._lock_path

    @property
    def mutation_permit_lock_owner_uid(self) -> int:
        return self._lock_owner_uid

    @property
    def mutation_permit_lock_owner_gid(self) -> int:
        return os.getegid()

    @property
    def mutation_authority_trusted_parent(self) -> Path:
        return self._permit_path.parent

    @property
    def mutation_authority_directory_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def mutation_authority_directory_owner_gid(self) -> int:
        return os.getegid()

    @property
    def epoch_void_ledger_root(self) -> Path:
        return self._epoch_void_ledger_root

    @property
    def epoch_void_ledger_owner_uid(self) -> int:
        return self._epoch_void_ledger_owner_uid

    @property
    def epoch_void_ledger_owner_gid(self) -> int:
        return self._epoch_void_ledger_owner_gid

    @property
    def current_predicate_trusted_parent(self) -> Path:
        return self._current_predicate_trusted_parent

    @property
    def current_predicate_root(self) -> Path:
        return self._current_predicate_root

    @property
    def current_predicate_records_directory(self) -> Path:
        return self._current_predicate_root / "records"

    @property
    def current_predicate_pointer_path(self) -> Path:
        return self._current_predicate_root / "current.json"

    @property
    def current_predicate_producer_manifest_path(self) -> Path:
        return self._current_predicate_root / "producer-manifest.json"

    @property
    def current_predicate_owner_uid(self) -> int:
        return self._current_predicate_owner_uid

    @property
    def current_predicate_owner_gid(self) -> int:
        return self._current_predicate_owner_gid

    @property
    def current_predicate_producer_path(self) -> Path:
        return self._current_predicate_trusted_parent / "vexp-current-predicate-attestor"

    @property
    def current_predicate_producer_trusted_parent(self) -> Path:
        return self._current_predicate_trusted_parent

    @property
    def current_predicate_producer_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def current_predicate_producer_owner_gid(self) -> int:
        return os.getegid()

    def current_boot_id(self) -> str:
        return self._current_boot_id

    def monotonic_ns(self) -> int:
        return self._monotonic_ns()

    def utc_now(self) -> datetime:
        return self._utc_now()


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
        raise AssertionError(f"unexpected command: {command!r}")


def _state(*, terminal: bool = False) -> dict[str, object]:
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
        "predicate_contract_sha256": "3" * 64,
        "probes_passed": 42,
    }


def _certificate(state: Mapping[str, object]) -> dict[str, object]:
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
        "schema": deploy.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA,
        "sentinel_version": deploy.VEXP_SENTINEL_STATE_VERSION,
        "epoch_started_at": state["epoch_started_at"],
        "epoch_started_ms": state["epoch_started_ms"],
        "qualified_at": state["qualified_at"],
        "qualification_duration_ms": deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS,
        "qualification_monotonic_duration_ms": (
            deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS
        ),
        "qualification_boot_id": TEST_BOOT_ID,
        "qualification_monotonic_started_ns": 1_000_000_000,
        "qualification_monotonic_qualified_ns": (
            1_000_000_000
            + deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS * 1_000_000
        ),
        "active_chain": {
            "anchor": {**reset_event, "source": "sentinel"},
            "qualification_event": {**event, "source": "sentinel"},
            "tail_sequence": tail_event["sequence"],
            "tail_hash": tail_hash,
            "event_count": len(index),
            "index": index,
            "index_sha256": deploy._canonical_json_sha256(index),
        },
        "terminal_state": {
            "version": deploy.VEXP_SENTINEL_STATE_VERSION,
            "epoch_started_at": state["epoch_started_at"],
            "epoch_started_ms": state["epoch_started_ms"],
            "qualified_at": state["qualified_at"],
            "qualification_boot_id": TEST_BOOT_ID,
            "qualification_monotonic_started_ns": 1_000_000_000,
            "qualification_monotonic_qualified_ns": (
                1_000_000_000
                + deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS * 1_000_000
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
    certificate["identity"] = (
        f"sha256:{deploy._canonical_json_sha256(certificate)}"
    )
    return certificate


def _certificate_raw(state: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            _certificate(state),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _reseal_certificate(certificate: dict[str, object]) -> dict[str, object]:
    certificate.pop("identity", None)
    certificate["identity"] = (
        f"sha256:{deploy._canonical_json_sha256(certificate)}"
    )
    return certificate


def _certificate_evidence(state: Mapping[str, object]) -> dict[str, str]:
    certificate = _certificate(state)
    raw = _certificate_raw(state)
    return {
        "schema": str(certificate["schema"]),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "identity": str(certificate["identity"]),
        "event_hash": str(
            dict(dict(certificate["active_chain"])["qualification_event"])["hash"]
        ),
    }


def _permit(state: Mapping[str, object]) -> dict[str, object]:
    certificate = _certificate_evidence(state)
    return {
        "contract_name": deploy.VEXP_MUTATION_PERMIT_CONTRACT_NAME,
        "version": deploy.VEXP_MUTATION_PERMIT_VERSION,
        "status": "allow",
        "epoch_started_at": state["epoch_started_at"],
        "epoch_started_ms": state["epoch_started_ms"],
        "qualification_earliest_completion_at": state[
            "qualification_earliest_completion_at"
        ],
        "qualified_at": state["qualified_at"],
        "terminal_identity_sha256": deploy._vexp_terminal_identity_sha256(state),
        "qualification_certificate_schema": certificate["schema"],
        "qualification_certificate_sha256": certificate["sha256"],
        "qualification_certificate_identity": certificate["identity"],
        "qualification_certificate_event_hash": certificate["event_hash"],
        "issued_at": "2026-07-20T09:45:00.000Z",
        "expires_at": "2026-07-20T10:30:00.000Z",
        "mutation_boundaries": list(deploy.VEXP_MUTATION_BOUNDARIES),
    }


def _write_json(path: Path, payload: object, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(mode)


def _permit_commit(payload: Mapping[str, object], raw: bytes) -> dict[str, object]:
    return {
        "contract_name": deploy.VEXP_MUTATION_PERMIT_COMMIT_CONTRACT_NAME,
        "version": deploy.VEXP_MUTATION_PERMIT_COMMIT_VERSION,
        "status": "committed",
        "permit_sha256": hashlib.sha256(raw).hexdigest(),
        "permit_contract_name": payload.get("contract_name"),
        "permit_version": payload.get("version"),
        "epoch_started_at": payload.get("epoch_started_at"),
        "epoch_started_ms": payload.get("epoch_started_ms"),
        "terminal_identity_sha256": payload.get("terminal_identity_sha256"),
        "qualification_certificate_sha256": payload.get(
            "qualification_certificate_sha256"
        ),
        "issued_at": payload.get("issued_at"),
        "expires_at": payload.get("expires_at"),
    }


def _write_permit(
    lane: MemorialDeployLane,
    path: Path,
    payload: Mapping[str, object],
    *,
    mode: int = 0o644,
) -> None:
    _write_json(path, payload, mode=mode)
    _write_permit_commit(lane, payload, path.read_bytes())
    _maybe_write_current_predicate(lane)


def _write_permit_commit(
    lane: MemorialDeployLane,
    payload: Mapping[str, object],
    raw: bytes,
) -> None:
    _write_json(
        lane._vexp_mutation_authority.mutation_permit_commit_path,
        _permit_commit(payload, raw),
        mode=0o644,
    )


def _write_raw_permit(
    lane: MemorialDeployLane,
    path: Path,
    payload: Mapping[str, object],
    raw: bytes,
    *,
    mode: int = 0o644,
) -> None:
    path.write_bytes(raw)
    path.chmod(mode)
    _write_permit_commit(lane, payload, raw)
    _maybe_write_current_predicate(lane)


def _write_certificate(
    directory: Path,
    state: Mapping[str, object],
    *,
    certificate: Mapping[str, object] | None = None,
    mode: int = 0o640,
    sidecar: bytes | None = None,
) -> tuple[Path, Path]:
    raw = (
        (
            json.dumps(
                dict(certificate),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if certificate is not None
        else _certificate_raw(state)
    )
    certificate_path = directory / f"{state['epoch_started_ms']}.json"
    sidecar_path = certificate_path.with_suffix(".json.sha256")
    certificate_path.write_bytes(raw)
    certificate_path.chmod(mode)
    sidecar_path.write_bytes(
        sidecar
        if sidecar is not None
        else f"sha256:{hashlib.sha256(raw).hexdigest()}\n".encode("ascii")
    )
    sidecar_path.chmod(mode)
    return certificate_path, sidecar_path


def _write_current_predicate(lane: MemorialDeployLane) -> None:
    authority = lane._vexp_mutation_authority
    state_raw = authority.sentinel_state_path.read_bytes()
    state = json.loads(state_raw)
    certificate_path = (
        authority.qualification_certificate_directory
        / f"{state['epoch_started_ms']}.json"
    )
    certificate_raw = certificate_path.read_bytes()
    certificate = json.loads(certificate_raw)
    implementation = certificate["source_attestations"]["implementation"]
    root = authority.current_predicate_root
    records = authority.current_predicate_records_directory
    root.mkdir(mode=0o750, exist_ok=True)
    root.chmod(0o750)
    records.mkdir(mode=0o750, exist_ok=True)
    records.chmod(0o750)
    pointer_path = authority.current_predicate_pointer_path
    if pointer_path.exists():
        previous_pointer = json.loads(pointer_path.read_bytes())
        generation = int(previous_pointer["generation"]) + 1
        previous_record_sha256 = str(previous_pointer["record_sha256"])
    else:
        generation = 1
        previous_record_sha256 = "0" * 64
    now = authority.utc_now().isoformat().replace("+00:00", "Z")
    record = {
        "contract_name": deploy.VEXP_CURRENT_PREDICATE_CONTRACT_NAME,
        "version": deploy.VEXP_CURRENT_PREDICATE_VERSION,
        "status": "positive",
        "epoch_started_ms": state["epoch_started_ms"],
        "generation": generation,
        "observed_at": state["updated_at"],
        "recorded_at": now,
        "boot_id": authority.current_boot_id(),
        "monotonic_ns": authority.monotonic_ns() - 1_000_000 + generation,
        "sentinel_state_path": str(authority.sentinel_state_path),
        "sentinel_state_owner_uid": authority.sentinel_state_owner_uid,
        "sentinel_state_sha256": hashlib.sha256(state_raw).hexdigest(),
        "terminal_identity_sha256": deploy._vexp_terminal_identity_sha256(state),
        "qualification_certificate_sha256": hashlib.sha256(
            certificate_raw
        ).hexdigest(),
        "predicate_contract_sha256": state["predicate_contract_sha256"],
        "current_resources_healthy": state["current_resources_healthy"],
        "certification_blockers": state["certification_blockers"],
        "certification_deferments": state["certification_deferments"],
        "sentinel_producer_sha256": implementation["sentinel_executable"][
            "sha256"
        ],
        "root_predicate_producer_sha256": (
            TEST_ROOT_PREDICATE_PRODUCER_SHA256
        ),
        "previous_record_sha256": previous_record_sha256,
    }
    record_path = records / f"{state['epoch_started_ms']}-{generation}.json"
    record_raw = deploy._canonical_guard_json_bytes(record)
    record_path.write_bytes(record_raw)
    record_path.chmod(0o640)
    pointer = {
        "contract_name": deploy.VEXP_CURRENT_PREDICATE_POINTER_CONTRACT_NAME,
        "version": deploy.VEXP_CURRENT_PREDICATE_POINTER_VERSION,
        "status": "published",
        "epoch_started_ms": state["epoch_started_ms"],
        "generation": generation,
        "record_path": str(record_path),
        "record_sha256": hashlib.sha256(record_raw).hexdigest(),
    }
    pointer_path.write_bytes(deploy._canonical_guard_json_bytes(pointer))
    pointer_path.chmod(0o640)


def _maybe_write_current_predicate(lane: MemorialDeployLane) -> None:
    authority = lane._vexp_mutation_authority
    try:
        state_metadata = os.stat(
            authority.sentinel_state_path, follow_symlinks=False
        )
    except OSError:
        return
    if not stat.S_ISREG(state_metadata.st_mode):
        return
    try:
        state = json.loads(authority.sentinel_state_path.read_bytes())
        certificate_path = (
            authority.qualification_certificate_directory
            / f"{state['epoch_started_ms']}.json"
        )
        certificate_metadata = os.stat(certificate_path, follow_symlinks=False)
    except (OSError, KeyError, TypeError, ValueError):
        return
    if not stat.S_ISREG(certificate_metadata.st_mode):
        return
    _write_current_predicate(lane)


def _rewrite_current_predicate_record(
    lane: MemorialDeployLane,
    changes: Mapping[str, object],
) -> None:
    authority = lane._vexp_mutation_authority
    pointer_path = authority.current_predicate_pointer_path
    pointer = json.loads(pointer_path.read_bytes())
    record_path = Path(pointer["record_path"])
    record = json.loads(record_path.read_bytes())
    record.update(changes)
    record_raw = deploy._canonical_guard_json_bytes(record)
    record_path.write_bytes(record_raw)
    record_path.chmod(0o640)
    pointer["record_sha256"] = hashlib.sha256(record_raw).hexdigest()
    pointer_path.write_bytes(deploy._canonical_guard_json_bytes(pointer))
    pointer_path.chmod(0o640)


def _assert_fifo_rejected_immediately(
    path: Path,
    *,
    mode: int,
    reader: Callable[[], object],
    reason: str,
) -> None:
    os.mkfifo(path, mode)
    path.chmod(mode)
    stop_emergency_writer = threading.Event()
    emergency_delay = 0.75

    def emergency_writer() -> None:
        if stop_emergency_writer.wait(emergency_delay):
            return
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return
        os.close(descriptor)

    writer = threading.Thread(target=emergency_writer, daemon=True)
    writer.start()
    started = time.monotonic()
    try:
        with pytest.raises(DeployError, match=reason):
            reader()
    finally:
        elapsed = time.monotonic() - started
        stop_emergency_writer.set()
        writer.join(timeout=1)
    assert elapsed < emergency_delay / 2


def _lane(
    tmp_path: Path,
    *,
    state_path: Path | None = None,
    permit_path: Path | None = None,
    permit_commit_path: Path | None = None,
    lock_path: Path | None = None,
    permit_owner_uid: int | None = None,
    permit_commit_owner_uid: int | None = None,
    lock_owner_uid: int | None = None,
    epoch_void_ledger_root: Path | None = None,
    epoch_void_ledger_owner_uid: int | None = None,
    epoch_void_ledger_owner_gid: int | None = None,
    certificate_owner_uid: int | None = None,
    certificate_owner_gid: int | None = None,
    utc_now: Callable[[], datetime] = lambda: NOW,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    create_lock: bool = True,
    create_certificate: bool = True,
) -> tuple[MemorialDeployLane, NoCommandRunner, Path, Path]:
    tmp_path.chmod(0o755)
    root = tmp_path / "release"
    root.mkdir(exist_ok=True)
    runner = NoCommandRunner()
    resolved_state_path = state_path or tmp_path / "sentinel-state.json"
    resolved_permit_path = permit_path or tmp_path / "mutation-permit.json"
    resolved_permit_commit_path = (
        permit_commit_path or tmp_path / "mutation-permit.commit.json"
    )
    resolved_lock_path = lock_path or tmp_path / "mutation-permit.lock"
    resolved_epoch_void_ledger_root = (
        epoch_void_ledger_root or tmp_path / "epoch-void-ledger"
    )
    resolved_epoch_void_ledger_root.mkdir(exist_ok=True)
    resolved_epoch_void_ledger_root.chmod(0o750)
    certificate_root = tmp_path / "qualification-certificate"
    certificate_root.mkdir(exist_ok=True)
    certificate_root.chmod(0o750)
    certificate_directory = certificate_root / "certificates"
    certificate_directory.mkdir(exist_ok=True)
    certificate_directory.chmod(0o750)
    current_predicate_root = (
        tmp_path / "vexp-qualification-current-predicate"
    )
    current_predicate_root.mkdir(exist_ok=True)
    current_predicate_root.chmod(0o750)
    current_predicate_records = current_predicate_root / "records"
    current_predicate_records.mkdir(exist_ok=True)
    current_predicate_records.chmod(0o750)
    current_predicate_producer = tmp_path / "vexp-current-predicate-attestor"
    current_predicate_producer.write_bytes(TEST_ROOT_PREDICATE_PRODUCER_BYTES)
    current_predicate_producer.chmod(0o555)
    producer_manifest = {
        "contract_name": (
            deploy.VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_CONTRACT_NAME
        ),
        "version": deploy.VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_VERSION,
        "status": "reviewed",
        "producer_path": str(current_predicate_producer),
        "producer_sha256": TEST_ROOT_PREDICATE_PRODUCER_SHA256,
    }
    producer_manifest_path = current_predicate_root / "producer-manifest.json"
    producer_manifest_path.write_bytes(
        deploy._canonical_guard_json_bytes(producer_manifest)
    )
    producer_manifest_path.chmod(0o640)
    if create_certificate:
        _write_certificate(certificate_directory, _state(terminal=True))
    if create_lock:
        resolved_lock_path.touch()
        resolved_lock_path.chmod(0o644)
    lane = MemorialDeployLane(
        root=root,
        env={
            "EA_DEPLOYMENT_ID": "guard-test-001",
            "EA_MEMORIAL_RUNTIME_HOST_PATH": str(
                root / ".runtime" / "candidate-data"
            ),
        },
        runner=runner,
        monotonic=monotonic,
        sleep=sleep,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        durable_root_check=lambda _path: None,
        gemini_oauth_snapshot_factory=_gemini_oauth_snapshot,
    )
    lane._vexp_mutation_authority = TestVexpMemorialMutationAuthority(
        state_path=resolved_state_path,
        certificate_root=certificate_root,
        certificate_directory=certificate_directory,
        certificate_owner_uid=(
            os.geteuid()
            if certificate_owner_uid is None
            else certificate_owner_uid
        ),
        certificate_owner_gid=(
            os.getegid()
            if certificate_owner_gid is None
            else certificate_owner_gid
        ),
        permit_path=resolved_permit_path,
        permit_commit_path=resolved_permit_commit_path,
        lock_path=resolved_lock_path,
        permit_owner_uid=(
            os.geteuid() if permit_owner_uid is None else permit_owner_uid
        ),
        permit_commit_owner_uid=(
            os.geteuid()
            if permit_commit_owner_uid is None
            else permit_commit_owner_uid
        ),
        lock_owner_uid=(os.geteuid() if lock_owner_uid is None else lock_owner_uid),
        epoch_void_ledger_root=resolved_epoch_void_ledger_root,
        epoch_void_ledger_owner_uid=(
            os.geteuid()
            if epoch_void_ledger_owner_uid is None
            else epoch_void_ledger_owner_uid
        ),
        epoch_void_ledger_owner_gid=(
            os.getegid()
            if epoch_void_ledger_owner_gid is None
            else epoch_void_ledger_owner_gid
        ),
        current_predicate_trusted_parent=tmp_path,
        current_predicate_root=current_predicate_root,
        current_predicate_owner_uid=os.geteuid(),
        current_predicate_owner_gid=os.getegid(),
        current_boot_id=TEST_BOOT_ID,
        monotonic_ns=lambda: TEST_MONOTONIC_NS,
        utc_now=utc_now,
    )
    lane._require_reviewed_vexp_qualification_implementation_manifest = (  # type: ignore[method-assign]
        lambda _certificate: None
    )
    return lane, runner, resolved_state_path, resolved_permit_path


def _preflight_context(tmp_path: Path) -> dict[str, object]:
    return {
        "authority": {},
        "previous": {
            "working_dir": str(tmp_path / "previous"),
            "image_id": f"sha256:{'1' * 64}",
            "compose_config_files": [str(tmp_path / "docker-compose.yml")],
        },
        "candidate": {
            "reference": "ea-runtime:terminal-candidate",
            "image_id": f"sha256:{'2' * 64}",
        },
        "candidate_promotion": {"projection": {}},
        "rollback_render": {},
        "deployment_input_seal": {"seal_sha256": "4" * 64},
        "source_revision": "3" * 40,
        "public_origin": "https://myexternalbrain.com",
        "non_memorial_controls": {},
        "target_mounts": [],
        "gemini_oauth_binding": _gemini_oauth_binding(),
    }


def _install_preflight(lane: MemorialDeployLane, tmp_path: Path) -> None:
    context = _preflight_context(tmp_path)
    seal = {
        "release_source": {"source_revision": context["source_revision"]},
        "authority_sha256": deploy._canonical_json_sha256(context["authority"]),
        "previous_sha256": deploy._canonical_json_sha256(context["previous"]),
        "rollback_render_sha256": deploy._canonical_json_sha256(
            context["rollback_render"]
        ),
        "public_origin": context["public_origin"],
        "candidate": context["candidate"],
        "candidate_promotion_sha256": deploy._canonical_json_sha256(
            context["candidate_promotion"]
        ),
        "target_mounts_sha256": deploy._canonical_json_sha256(
            context["target_mounts"]
        ),
        "gemini_oauth": context["gemini_oauth_binding"],
    }
    context["predeploy_release_context_seal"] = seal
    lane.receipt["predeploy_release_context_seal"] = {
        "status": "sealed",
        "sha256": deploy._canonical_json_sha256(seal),
        "preimage": seal,
    }
    lane.preflight = Mock(return_value=context)  # type: ignore[method-assign]
    lane._require_deployment_input_seal = Mock()  # type: ignore[method-assign]
    lane._require_predeploy_release_context_current = Mock()  # type: ignore[method-assign]
    lane._capture_non_memorial_controls = Mock(return_value={})  # type: ignore[method-assign]
    lane.bind_source_snapshot_sha256 = "5" * 64
    lane._revalidate_bind_source_access = Mock()  # type: ignore[method-assign]
    lane._require_gemini_oauth_helper_name_absent = Mock(  # type: ignore[method-assign]
        return_value={
            "status": "pass",
            "boundary": "before_api_stop",
            "checked_at": "2026-07-20T00:00:00Z",
            "container_name": "mocked",
            "exact_name_absent": True,
            "helper_invocation_state": "not_started",
        }
    )
    lane._stop_api_for_gemini_oauth = Mock(  # type: ignore[method-assign]
        side_effect=lambda _previous, *, before_mutation: before_mutation(
            "before_stop_api_for_gemini_oauth"
        )
    )
    lane._provision_gemini_oauth = Mock(  # type: ignore[method-assign]
        side_effect=lambda *, candidate, previous, expected_binding, command,
        helper_container_name, runtime_root, before_mutation: (
            before_mutation("before_gemini_oauth_install")
        )
    )


def _install_postdeploy_success(lane: MemorialDeployLane) -> None:
    lane._wait_container = Mock(return_value={})  # type: ignore[method-assign]
    lane._verify_forward_api = Mock(return_value={})  # type: ignore[method-assign]
    lane._verify_deployed_surface = Mock()  # type: ignore[method-assign]
    lane._verify_candidate_origins = Mock()  # type: ignore[method-assign]
    lane._verify_non_memorial_controls = Mock()  # type: ignore[method-assign]
    lane._materialize_and_verify_release_evidence = Mock(  # type: ignore[method-assign]
        return_value={}
    )


def _receipt(lane: MemorialDeployLane) -> dict[str, object]:
    return json.loads(lane.receipt_path.read_text(encoding="utf-8"))


def test_default_permit_is_root_owned_public_read_only_path_under_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile_home = tmp_path / "home-override"
    monkeypatch.setenv("HOME", str(hostile_home))
    root = tmp_path / "release"
    root.mkdir()
    lane = MemorialDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "guard-default-001"},
        runner=NoCommandRunner(),
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        durable_root_check=lambda _path: None,
    )

    authority = lane._vexp_mutation_authority
    assert authority.mutation_permit_path == Path(
        "/run/ea/memorial-vexp-mutation-permit.json"
    )
    assert Path("/run") in authority.mutation_permit_path.parents
    assert authority.mutation_permit_owner_uid == 0
    assert authority.mutation_permit_owner_gid == 0
    assert authority.mutation_permit_commit_path == Path(
        "/run/ea/memorial-vexp-mutation-permit.commit.json"
    )
    assert authority.mutation_permit_commit_owner_uid == 0
    assert authority.mutation_permit_commit_owner_gid == 0
    assert authority.mutation_permit_lock_path == Path(
        "/run/ea/memorial-vexp-mutation-permit.lock"
    )
    assert authority.mutation_permit_lock_owner_uid == 0
    assert authority.mutation_permit_lock_owner_gid == 0
    assert authority.mutation_authority_trusted_parent == Path("/run")
    assert authority.mutation_authority_directory_owner_uid == 0
    assert authority.mutation_authority_directory_owner_gid == 0
    assert authority.sentinel_state_path == (
        Path(pwd.getpwuid(os.geteuid()).pw_dir)
        / ".local"
        / "state"
        / "vexp-sentinel"
        / "state.json"
    )
    assert hostile_home not in authority.sentinel_state_path.parents
    assert authority.qualification_certificate_root == Path(
        "/var/lib/vexp-qualification-certificate"
    )
    assert authority.qualification_certificate_directory == Path(
        "/var/lib/vexp-qualification-certificate/certificates"
    )
    assert authority.qualification_certificate_owner_uid == 0
    assert authority.qualification_certificate_owner_gid == 1000
    assert authority.epoch_void_ledger_root == Path(
        "/var/lib/vexp-qualification-epoch-voids"
    )
    assert authority.epoch_void_ledger_owner_uid == 0
    assert authority.epoch_void_ledger_owner_gid == 1000
    assert authority.current_predicate_trusted_parent == Path("/var/lib")
    assert authority.current_predicate_root == Path(
        "/var/lib/vexp-qualification-current-predicate"
    )
    assert authority.current_predicate_records_directory == Path(
        "/var/lib/vexp-qualification-current-predicate/records"
    )
    assert authority.current_predicate_pointer_path == Path(
        "/var/lib/vexp-qualification-current-predicate/current.json"
    )
    assert authority.current_predicate_producer_manifest_path == Path(
        "/var/lib/vexp-qualification-current-predicate/producer-manifest.json"
    )
    assert authority.current_predicate_owner_uid == 0
    assert authority.current_predicate_owner_gid == 1000
    assert deploy.TRUSTED_VEXP_CURRENT_PREDICATE_PRODUCER == Path(
        "/usr/local/libexec/vexp-current-predicate-attestor"
    )
    assert deploy.VEXP_MUTATION_PERMIT_VERSION == 2


def test_deploy_lane_constructor_rejects_authority_overrides(tmp_path: Path) -> None:
    root = tmp_path / "release"
    root.mkdir()

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        MemorialDeployLane(
            root=root,
            env={"EA_DEPLOYMENT_ID": "guard-fixed-authority-001"},
            utc_now=lambda: NOW,  # type: ignore[call-arg]
            durable_root_check=lambda _path: None,
        )


def test_missing_epoch_void_ledger_root_fails_closed(tmp_path: Path) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    root = lane._vexp_mutation_authority.epoch_void_ledger_root
    root.rmdir()

    with pytest.raises(
        DeployError, match="vexp_epoch_void_ledger_root_unavailable"
    ):
        lane._require_vexp_epoch_not_voided(_state(terminal=True))


@pytest.mark.parametrize("untrusted_kind", ["mode", "owner", "symlink", "file"])
def test_untrusted_epoch_void_ledger_root_fails_closed(
    tmp_path: Path, untrusted_kind: str
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(
        tmp_path,
        epoch_void_ledger_owner_uid=(
            os.geteuid() + 1 if untrusted_kind == "owner" else None
        ),
    )
    root = lane._vexp_mutation_authority.epoch_void_ledger_root
    if untrusted_kind == "mode":
        root.chmod(0o755)
    elif untrusted_kind == "symlink":
        real_root = tmp_path / "real-epoch-void-ledger"
        real_root.mkdir()
        real_root.chmod(0o750)
        root.rmdir()
        root.symlink_to(real_root, target_is_directory=True)
    elif untrusted_kind == "file":
        root.rmdir()
        root.touch()
        root.chmod(0o750)

    with pytest.raises(DeployError, match="vexp_epoch_void_ledger_root_untrusted"):
        lane._require_vexp_epoch_not_voided(_state(terminal=True))


def test_current_epoch_void_ledger_entry_permanently_denies_authority(
    tmp_path: Path,
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    entry = (
        lane._vexp_mutation_authority.epoch_void_ledger_root
        / f"{state['epoch_started_ms']}.json"
    )
    _write_json(entry, {"status": "void"}, mode=0o640)

    with pytest.raises(DeployError, match="vexp_qualification_epoch_voided"):
        lane._require_vexp_epoch_not_voided(state)


def test_prior_epoch_void_entry_does_not_void_current_epoch(tmp_path: Path) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    entry = (
        lane._vexp_mutation_authority.epoch_void_ledger_root
        / f"{int(state['epoch_started_ms']) - 1}.json"
    )
    _write_json(entry, {"status": "void"}, mode=0o640)

    lane._require_vexp_epoch_not_voided(state)


@pytest.mark.parametrize("untrusted_kind", ["missing", "mode", "symlink", "hardlink"])
def test_mutation_lease_requires_trusted_root_lock(
    tmp_path: Path, untrusted_kind: str
) -> None:
    lock_path = tmp_path / "mutation-permit.lock"
    if untrusted_kind == "mode":
        lock_path.touch()
        lock_path.chmod(0o664)
    elif untrusted_kind == "symlink":
        target = tmp_path / "real-mutation-permit.lock"
        target.touch()
        target.chmod(0o644)
        lock_path.symlink_to(target)
    elif untrusted_kind == "hardlink":
        target = tmp_path / "linked-mutation-permit.lock"
        target.touch()
        target.chmod(0o644)
        os.link(target, lock_path)
    lane, _runner, _state_path, _permit_path = _lane(
        tmp_path,
        lock_path=lock_path,
        create_lock=False,
    )

    with pytest.raises(DeployError, match="vexp_mutation_permit_lock_"):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            pass

    guard = _receipt(lane)["checks"][-1]
    assert guard["status"] == "fail"
    assert guard["reason"].startswith("vexp_mutation_permit_lock_")


def test_mutation_lease_fifo_lock_is_rejected_without_blocking(tmp_path: Path) -> None:
    lock_path = tmp_path / "mutation-permit.lock"
    lane, _runner, _state_path, _permit_path = _lane(
        tmp_path,
        lock_path=lock_path,
        create_lock=False,
    )

    def acquire() -> None:
        with lane._vexp_mutation_lease("before_ensure_redis"):
            pass

    _assert_fifo_rejected_immediately(
        lock_path,
        mode=0o644,
        reader=acquire,
        reason="vexp_mutation_permit_lock_untrusted",
    )


@pytest.mark.parametrize(
    ("flag", "reason"),
    [
        ("O_NOFOLLOW", "nofollow_unavailable"),
        ("O_NONBLOCK", "nonblock_unavailable"),
    ],
)
def test_mutation_lease_requires_safe_open_flag_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    reason: str,
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    monkeypatch.delattr(deploy.os, flag)

    with pytest.raises(DeployError, match=f"vexp_mutation_permit_lock_{reason}"):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            pass


def test_active_enforced_soak_blocks_without_permit_and_persists_receipt(
    tmp_path: Path,
) -> None:
    lane, runner, state_path, _permit_path = _lane(tmp_path)
    _write_json(state_path, _state(), mode=0o600)
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock()  # type: ignore[method-assign]

    with pytest.raises(DeployError, match="vexp_soak_mutation_blocked"):
        lane.deploy()

    assert runner.commands == []
    lane._ensure_redis.assert_not_called()
    receipt = _receipt(lane)
    assert receipt["status"] == "blocked_vexp_soak"
    assert receipt["failure"]["reason"] == "vexp_soak_mutation_blocked"
    guard = receipt["checks"][-1]
    assert guard["name"] == "vexp_soak_mutation_guard"
    assert guard["status"] == "blocked"
    assert guard["boundary"] == "before_ensure_redis"
    assert guard["reason"] == "active_enforced_soak"
    assert re.fullmatch(r"[0-9a-f]{64}", guard["state_sha256"])
    assert "permit_sha256" not in guard
    assert stat.S_IMODE(lane.receipt_path.stat().st_mode) == 0o600


def test_preflight_only_remains_available_without_state_or_permit(
    tmp_path: Path,
) -> None:
    lane, runner, _state_path, _permit_path = _lane(tmp_path)
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock()  # type: ignore[method-assign]

    receipt = lane.deploy(preflight_only=True)

    assert receipt["status"] == "preflight_only_pass"
    assert runner.commands == []
    lane._capture_non_memorial_controls.assert_not_called()
    lane._ensure_redis.assert_not_called()
    assert not any(
        check.get("name") == "vexp_soak_mutation_guard" for check in receipt["checks"]
    )


def test_preflight_defers_live_openapi_baseline_without_api_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane, runner, _state_path, _permit_path = _lane(tmp_path)
    (lane.root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    lane.control_tour_slug = deploy.REQUIRED_CONTROL_TOUR_SLUG
    previous = {
        "working_dir": str(tmp_path / "previous"),
        "image_id": f"sha256:{'1' * 64}",
        "compose_config_files": [str(tmp_path / "docker-compose.yml")],
    }
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane._release_source_metadata = Mock(  # type: ignore[method-assign]
        return_value={"source_revision": "3" * 40}
    )
    lane._detect_compose = Mock()  # type: ignore[method-assign]
    lane._previous_api = Mock(return_value=previous)  # type: ignore[method-assign]
    lane._configure_forward_topology = Mock()  # type: ignore[method-assign]
    lane._capture_deployment_input_seal = Mock(  # type: ignore[method-assign]
        return_value={"seal_sha256": "4" * 64}
    )
    lane._verify_rollback_renderability = Mock(return_value={})  # type: ignore[method-assign]
    lane._require_deployment_input_seal = Mock()  # type: ignore[method-assign]
    lane._bind_source_revision = Mock(return_value="3" * 40)  # type: ignore[method-assign]
    lane._resolve_candidate_image = Mock(return_value={})  # type: ignore[method-assign]
    lane._validate_candidate_promotion_receipt = Mock(return_value={})  # type: ignore[method-assign]
    lane._materialize_and_verify_release_evidence = Mock(  # type: ignore[method-assign]
        return_value={"public_origin": "https://myexternalbrain.com"}
    )
    lane._validate_compose = Mock(return_value=[])  # type: ignore[method-assign]
    lane._capture_predeploy_release_context_seal = Mock(  # type: ignore[method-assign]
        return_value={"schema": "test.predeploy.release-context.v1"}
    )
    lane._capture_openapi_control = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("public openapi must not be read in preflight")
    )
    lane._capture_internal_openapi_control = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("docker exec must not run in preflight")
    )

    context = lane.preflight()

    assert runner.commands == []
    assert context["non_memorial_controls"] == {}
    assert context["gemini_oauth_binding"] == _gemini_oauth_binding()
    assert lane.receipt["predeploy_non_memorial_controls"] == {
        "status": "deferred_to_authorized_transaction",
        "openapi_source": "deployed_api_container_app.openapi",
        "docker_exec_performed": False,
        "action_class": "deferred_read_only_non_mutating_probe",
        "live_mutation_performed": False,
    }
    lane._capture_openapi_control.assert_not_called()
    lane._capture_internal_openapi_control.assert_not_called()


def test_terminal_state_and_positive_permit_pass_all_forward_mutation_boundaries(
    tmp_path: Path,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    _install_postdeploy_success(lane)
    actions: list[str] = []
    lane._capture_non_memorial_controls = Mock(  # type: ignore[method-assign]
        side_effect=lambda **kwargs: (
            actions.append(
                "capture_internal_openapi"
                if kwargs == {"internal_openapi": True}
                else "capture_wrong_source"
            )
            or {}
        )
    )
    lane._ensure_redis = Mock(  # type: ignore[method-assign]
        side_effect=lambda *, before_mutation: (
            before_mutation("before_redis_create"),
            actions.append("ensure_redis"),
        )
    )

    def protect(
        _previous: Mapping[str, object],
        *,
        before_mutation: Callable[[str], None],
    ) -> str:
        before_mutation("before_protect_previous_image_tag")
        actions.append("protect_previous_image")
        return "ea-runtime:rollback-guard-test"

    lane._protect_previous_image = protect  # type: ignore[method-assign]
    lane._stop_api_for_gemini_oauth = Mock(  # type: ignore[method-assign]
        side_effect=lambda _previous, *, before_mutation: (
            before_mutation("before_stop_api_for_gemini_oauth"),
            actions.append("stop_api_for_gemini_oauth"),
        )
    )
    lane._provision_gemini_oauth = Mock(  # type: ignore[method-assign]
        side_effect=lambda *, candidate, previous, expected_binding, command,
        helper_container_name, runtime_root, before_mutation: (
            before_mutation("before_gemini_oauth_install"),
            actions.append("provision_gemini_oauth"),
        )
    )
    lane._recreate_api = Mock(  # type: ignore[method-assign]
        side_effect=lambda *, before_mutation: (
            before_mutation("before_recreate_api_up"),
            actions.append("recreate_api"),
        )
    )

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert actions == [
        "capture_internal_openapi",
        "ensure_redis",
        "protect_previous_image",
        "stop_api_for_gemini_oauth",
        "provision_gemini_oauth",
        "recreate_api",
    ]
    assert runner.commands == []
    guards = [
        check
        for check in receipt["checks"]
        if check.get("name") == "vexp_soak_mutation_guard"
    ]
    assert [guard["boundary"] for guard in guards] == [
        "before_ensure_redis",
        "before_protect_previous_image",
        "before_recreate_api",
        "before_recreate_api",
        "before_recreate_api",
    ]
    assert {guard["status"] for guard in guards} == {"pass"}
    assert {guard["permit_status"] for guard in guards} == {"allow"}
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", str(guard["state_sha256"])) for guard in guards
    )
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", str(guard["permit_sha256"])) for guard in guards
    )
    assert {guard["qualification_certificate_schema"] for guard in guards} == {
        deploy.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
    }
    assert all(
        re.fullmatch(
            r"[0-9a-f]{64}",
            str(guard["qualification_certificate_sha256"]),
        )
        for guard in guards
    )


def test_mounted_projection_digest_uses_fresh_api_exec_lease(
    tmp_path: Path,
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    actions: list[str] = []
    payload = {
        "projection_sha256": "a" * 64,
        "file_count": 1,
        "projection_bytes": 2,
    }

    @contextmanager
    def lease(boundary: str):
        actions.append(f"enter:{boundary}")
        yield
        actions.append(f"exit:{boundary}")

    lane._vexp_mutation_lease = lease  # type: ignore[method-assign]
    lane._run = Mock(  # type: ignore[method-assign]
        side_effect=lambda *_args, **_kwargs: (
            actions.append("docker_exec")
            or subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        )
    )

    assert lane._mounted_projection_digest(payload) == payload
    assert actions == [
        "enter:before_api_exec",
        "docker_exec",
        "exit:before_api_exec",
    ]


def test_candidate_verifiers_each_use_a_fresh_api_interaction_lease(
    tmp_path: Path,
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    actions: list[str] = []

    @contextmanager
    def lease(boundary: str):
        actions.append(f"enter:{boundary}")
        yield
        actions.append(f"exit:{boundary}")

    lane._vexp_mutation_lease = lease  # type: ignore[method-assign]
    lane._local_origin = Mock(return_value="http://127.0.0.1:8090")  # type: ignore[method-assign]
    lane._verify_candidate_origin = Mock(  # type: ignore[method-assign]
        side_effect=lambda **kwargs: (
            actions.append(f"verify:{kwargs['label']}")
            or {"origin": kwargs["label"], "status": "pass"}
        )
    )

    lane._verify_candidate_origins("https://myexternalbrain.com")

    assert actions == [
        "enter:before_api_interaction",
        "verify:local",
        "exit:before_api_interaction",
        "enter:before_api_interaction",
        "verify:public",
        "exit:before_api_interaction",
    ]


def test_shared_authorization_lease_is_held_across_each_exact_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    _install_postdeploy_success(lane)
    lock_path = lane._vexp_mutation_authority.mutation_permit_lock_path
    lease_observations: list[str] = []

    def require_shared_lease(action: str) -> None:
        descriptor = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        lease_observations.append(action)

    lane._ensure_redis = Mock(  # type: ignore[method-assign]
        side_effect=lambda *, before_mutation: (
            before_mutation("before_redis_create"),
            require_shared_lease("ensure_redis"),
        )
    )

    def protect(
        _previous: Mapping[str, object],
        *,
        before_mutation: Callable[[str], None],
    ) -> str:
        before_mutation("before_protect_previous_image_tag")
        require_shared_lease("protect_previous_image")
        return "ea-runtime:rollback-guard-test"

    lane._protect_previous_image = protect  # type: ignore[method-assign]
    lane._stop_api_for_gemini_oauth = Mock(  # type: ignore[method-assign]
        side_effect=lambda _previous, *, before_mutation: (
            before_mutation("before_stop_api_for_gemini_oauth"),
            require_shared_lease("stop_api_for_gemini_oauth"),
        )
    )
    lane._provision_gemini_oauth = Mock(  # type: ignore[method-assign]
        side_effect=lambda *, candidate, previous, expected_binding, command,
        helper_container_name, runtime_root, before_mutation: (
            before_mutation("before_gemini_oauth_install"),
            require_shared_lease("provision_gemini_oauth"),
        )
    )
    lane._recreate_api = Mock(  # type: ignore[method-assign]
        side_effect=lambda *, before_mutation: (
            before_mutation("before_recreate_api_up"),
            require_shared_lease("recreate_api"),
        )
    )

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert lease_observations == [
        "ensure_redis",
        "protect_previous_image",
        "stop_api_for_gemini_oauth",
        "provision_gemini_oauth",
        "recreate_api",
    ]
    descriptor = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def test_transaction_budget_denies_near_expiry_before_any_forward_mutation(
    tmp_path: Path,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    permit = _permit(state)
    permit["expires_at"] = "2026-07-20T10:18:29.000Z"
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, permit)
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock()  # type: ignore[method-assign]
    lane._protect_previous_image = Mock()  # type: ignore[method-assign]
    lane._recreate_api = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        DeployError, match="vexp_mutation_transaction_budget_insufficient"
    ):
        lane.deploy()

    assert runner.commands == []
    lane._capture_non_memorial_controls.assert_not_called()
    lane._ensure_redis.assert_not_called()
    lane._protect_previous_image.assert_not_called()
    lane._recreate_api.assert_not_called()
    receipt = _receipt(lane)
    assert receipt["preparation"]["pending_action"] == "mutation_transaction"
    assert receipt["preparation"]["preparation_side_effects_possible"] is False


def test_internal_openapi_baseline_failure_denies_before_forward_mutation(
    tmp_path: Path,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    lane._capture_non_memorial_controls = Mock(  # type: ignore[method-assign]
        side_effect=DeployError("deployed_api_internal_openapi_snapshot_failed")
    )
    lane._ensure_redis = Mock()  # type: ignore[method-assign]
    lane._protect_previous_image = Mock()  # type: ignore[method-assign]
    lane._recreate_api = Mock()  # type: ignore[method-assign]

    with pytest.raises(
        DeployError, match="deployed_api_internal_openapi_snapshot_failed"
    ):
        lane.deploy()

    assert runner.commands == []
    lane._capture_non_memorial_controls.assert_called_once_with(
        internal_openapi=True
    )
    lane._ensure_redis.assert_not_called()
    lane._protect_previous_image.assert_not_called()
    lane._recreate_api.assert_not_called()
    receipt = _receipt(lane)
    assert receipt["preparation"]["pending_action"] == "mutation_transaction"
    assert receipt["preparation"]["preparation_side_effects_possible"] is False


def test_1800_second_permit_admits_one_bound_transaction_budget(
    tmp_path: Path,
) -> None:
    monotonic_now = [4000.0]
    lane, _runner, state_path, permit_path = _lane(
        tmp_path,
        monotonic=lambda: monotonic_now[0],
    )
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    lock_path = lane._vexp_mutation_authority.mutation_permit_lock_path

    with lane._vexp_mutation_transaction("before_ensure_redis"):
        assert lane._vexp_transaction_forward_deadline == pytest.approx(4900.0)
        assert lane._vexp_transaction_deadline == pytest.approx(5110.0)
        assert lane._remaining_vexp_mutation_seconds() == pytest.approx(900.0)
        descriptor = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        with lane._vexp_mutation_lease("before_ensure_redis"):
            pass
        lane._require_vexp_mutation_transaction_current(
            "before_ensure_redis"
        )

    assert lane._vexp_transaction_deadline is None
    assert lane._vexp_transaction_phase is None


def test_transaction_reserves_full_rollback_window_at_forward_deadline(
    tmp_path: Path,
) -> None:
    monotonic_now = [6000.0]
    lane, _runner, state_path, permit_path = _lane(
        tmp_path,
        monotonic=lambda: monotonic_now[0],
    )
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))

    with lane._vexp_mutation_transaction("before_ensure_redis"):
        monotonic_now[0] += deploy.MAX_VEXP_MUTATION_TRANSACTION_FORWARD_SECONDS
        lane._enter_vexp_mutation_transaction_rollback()
        assert lane._vexp_transaction_phase == "rollback"
        assert lane._remaining_vexp_mutation_seconds() == pytest.approx(
            deploy.MAX_VEXP_MUTATION_TRANSACTION_ROLLBACK_SECONDS
        )


def test_transaction_rejects_same_window_permit_rewrite_before_action_yield(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    permit = _permit(state)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, permit)
    action = Mock()

    with lane._vexp_mutation_transaction("before_ensure_redis"):
        rewritten = dict(permit)
        rewritten["issued_at"] = "2026-07-20T09:46:00.000Z"
        _write_permit(lane, permit_path, rewritten)
        with pytest.raises(
            DeployError,
            match="vexp_mutation_transaction_authority_changed",
        ):
            with lane._vexp_mutation_lease("before_ensure_redis"):
                action()

    action.assert_not_called()


def test_action_crossing_permit_expiry_is_not_accepted_as_complete(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    lane, _runner, state_path, permit_path = _lane(tmp_path, utc_now=lambda: clock[0])
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    actions: list[str] = []

    def ensure(*, before_mutation: Callable[[str], None]) -> None:
        before_mutation("before_redis_create")
        actions.append("ensure_redis")
        clock[0] = datetime(2026, 7, 20, 10, 31, tzinfo=UTC)

    lane._ensure_redis = ensure  # type: ignore[method-assign]
    lane._protect_previous_image = Mock()  # type: ignore[method-assign]
    lane._recreate_api = Mock()  # type: ignore[method-assign]

    with pytest.raises(DeployError, match="vexp_mutation_action_deadline_exceeded"):
        lane.deploy()

    assert actions == ["ensure_redis"]
    lane._protect_previous_image.assert_not_called()
    lane._recreate_api.assert_not_called()
    receipt = _receipt(lane)
    assert receipt["status"] == "failed_during_preparation"
    assert receipt["preparation"]["completed_actions"] == []
    assert receipt["preparation"]["active_action"] == "ensure_redis"
    assert receipt["preparation"]["api_runtime_state"] == "unchanged"
    assert receipt["rollback"] == {
        "status": "not_required",
        "reason": "api_unchanged",
    }


def test_mutation_lease_deadline_uses_action_maximum_and_is_cleared(
    tmp_path: Path,
) -> None:
    monotonic_now = [1000.0]
    lane, _runner, state_path, permit_path = _lane(
        tmp_path,
        monotonic=lambda: monotonic_now[0],
    )
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))

    with lane._vexp_mutation_lease("before_ensure_redis"):
        assert lane._vexp_mutation_deadline == pytest.approx(
            monotonic_now[0] + deploy.MAX_VEXP_MUTATION_ACTION_SECONDS
        )
        assert lane._vexp_mutation_expires_at == datetime(
            2026, 7, 20, 10, 30, tzinfo=UTC
        )

    assert lane._vexp_mutation_deadline is None
    assert lane._vexp_mutation_expires_at is None


def test_mutation_lease_deadline_is_capped_by_permit_remaining_lifetime(
    tmp_path: Path,
) -> None:
    monotonic_now = [2000.0]
    lane, _runner, state_path, permit_path = _lane(
        tmp_path,
        monotonic=lambda: monotonic_now[0],
    )
    state = _state(terminal=True)
    permit = _permit(state)
    permit["expires_at"] = "2026-07-20T10:00:45.000Z"
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, permit)

    with lane._vexp_mutation_lease("before_ensure_redis"):
        assert lane._vexp_mutation_deadline == pytest.approx(2045.0)
        assert lane._remaining_vexp_mutation_seconds() == pytest.approx(45.0)


def test_nested_mutation_leases_are_rejected_and_outer_deadline_is_cleared(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))

    with lane._vexp_mutation_lease("before_ensure_redis"):
        with pytest.raises(DeployError, match="vexp_mutation_action_lease_nested"):
            with lane._vexp_mutation_lease("before_protect_previous_image"):
                pass

    assert lane._vexp_mutation_deadline is None
    assert lane._vexp_mutation_expires_at is None


def test_monotonic_deadline_stops_command_before_injected_runner(
    tmp_path: Path,
) -> None:
    monotonic_now = [3000.0]
    lane, runner, state_path, permit_path = _lane(
        tmp_path,
        monotonic=lambda: monotonic_now[0],
    )
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))

    with pytest.raises(DeployError, match="vexp_mutation_action_deadline_exceeded"):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            monotonic_now[0] += deploy.MAX_VEXP_MUTATION_ACTION_SECONDS
            lane._run(["docker", "start", "ea-redis"])

    assert runner.commands == []
    assert lane._vexp_mutation_deadline is None
    assert lane._vexp_mutation_expires_at is None


def test_permit_expiry_stops_command_before_injected_runner(tmp_path: Path) -> None:
    wall_now = [NOW]
    lane, runner, state_path, permit_path = _lane(
        tmp_path,
        utc_now=lambda: wall_now[0],
    )
    state = _state(terminal=True)
    permit = _permit(state)
    permit["expires_at"] = "2026-07-20T10:00:20.000Z"
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, permit)

    with pytest.raises(DeployError, match="vexp_mutation_action_deadline_exceeded"):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            wall_now[0] += timedelta(seconds=20)
            lane._run(["docker", "start", "ea-redis"])

    assert runner.commands == []
    assert lane._vexp_mutation_deadline is None
    assert lane._vexp_mutation_expires_at is None


def test_real_subprocess_timeout_is_bounded_and_error_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_now = [4000.0]
    lane, _runner, state_path, permit_path = _lane(
        tmp_path,
        monotonic=lambda: monotonic_now[0],
    )
    lane.runner = deploy.SubprocessRunner()
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    observed: dict[str, object] = {}

    def timeout_run(args: Sequence[str], **kwargs: object) -> None:
        observed["args"] = list(args)
        observed["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(
            cmd=["private-command", "private-token"],
            timeout=float(kwargs["timeout"]),
            output="private-output",
            stderr="private-stderr",
        )

    monkeypatch.setattr(deploy.subprocess, "run", timeout_run)

    with pytest.raises(DeployError) as caught:
        with lane._vexp_mutation_lease("before_ensure_redis"):
            lane._run(["docker", "private-token"])

    assert str(caught.value) == "command_timeout:docker"
    assert "private" not in str(caught.value)
    assert 0 < float(observed["timeout"]) <= deploy.MAX_VEXP_MUTATION_ACTION_SECONDS
    assert lane._vexp_mutation_deadline is None
    assert lane._vexp_mutation_expires_at is None


def test_wait_loop_never_sleeps_past_permit_expiry(tmp_path: Path) -> None:
    monotonic_now = [5000.0]
    wall_now = [NOW]
    sleeps: list[float] = []

    def bounded_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        monotonic_now[0] += seconds
        wall_now[0] += timedelta(seconds=seconds)

    lane, _runner, state_path, permit_path = _lane(
        tmp_path,
        utc_now=lambda: wall_now[0],
        monotonic=lambda: monotonic_now[0],
        sleep=bounded_sleep,
    )
    state = _state(terminal=True)
    permit = _permit(state)
    permit["expires_at"] = "2026-07-20T10:00:00.250Z"
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, permit)
    lane._container_ready = Mock(return_value=(False, {}))  # type: ignore[method-assign]

    with pytest.raises(DeployError, match="vexp_mutation_action_deadline_exceeded"):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            lane._wait_container(deploy.REDIS_SERVICE, require_health=True)

    assert sleeps == [pytest.approx(0.25)]
    assert lane._vexp_mutation_deadline is None
    assert lane._vexp_mutation_expires_at is None


def test_partial_ensure_redis_failure_records_attempt_without_completion(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock(  # type: ignore[method-assign]
        side_effect=DeployError("redis_partial_failure")
    )
    lane._protect_previous_image = Mock()  # type: ignore[method-assign]
    lane._recreate_api = Mock()  # type: ignore[method-assign]
    lane._rollback = Mock()  # type: ignore[method-assign]

    with pytest.raises(DeployError, match="redis_partial_failure"):
        lane.deploy()

    lane._protect_previous_image.assert_not_called()
    lane._recreate_api.assert_not_called()
    lane._rollback.assert_not_called()
    receipt = _receipt(lane)
    assert receipt["status"] == "failed_during_preparation"
    assert receipt["preparation"] == {
        "status": "failed_during_action",
        "attempted_actions": ["ensure_redis"],
        "completed_actions": [],
        "pending_action": None,
        "active_action": "ensure_redis",
        "preparation_side_effects_possible": True,
        "api_mutation_started": False,
        "api_runtime_state": "unchanged",
        "rollback_required": False,
    }
    assert receipt["rollback"] == {
        "status": "not_required",
        "reason": "api_unchanged",
    }


def test_partial_image_protection_failure_distinguishes_attempted_and_completed(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock()  # type: ignore[method-assign]
    lane._protect_previous_image = Mock(  # type: ignore[method-assign]
        side_effect=DeployError("image_protection_partial_failure")
    )
    lane._recreate_api = Mock()  # type: ignore[method-assign]
    lane._rollback = Mock()  # type: ignore[method-assign]

    with pytest.raises(DeployError, match="image_protection_partial_failure"):
        lane.deploy()

    lane._recreate_api.assert_not_called()
    lane._rollback.assert_not_called()
    receipt = _receipt(lane)
    assert receipt["status"] == "failed_during_preparation"
    assert receipt["preparation"]["attempted_actions"] == [
        "ensure_redis",
        "protect_previous_image",
    ]
    assert receipt["preparation"]["completed_actions"] == ["ensure_redis"]
    assert receipt["preparation"]["active_action"] == "protect_previous_image"
    assert receipt["preparation"]["preparation_side_effects_possible"] is True
    assert receipt["preparation"]["api_mutation_started"] is False
    assert receipt["preparation"]["api_runtime_state"] == "unchanged"
    assert receipt["rollback"]["status"] == "not_required"


def test_api_mutation_start_is_persisted_before_recreate_and_rollback_preserved(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock()  # type: ignore[method-assign]
    lane._protect_previous_image = Mock(  # type: ignore[method-assign]
        return_value="ea-runtime:rollback-guard-test"
    )
    observed_before_recreate: dict[str, object] = {}

    def fail_recreate(*, before_mutation: Callable[[str], None]) -> None:
        before_mutation("before_recreate_api_up")
        observed_before_recreate.update(_receipt(lane)["preparation"])
        raise DeployError("api_recreate_partial_failure")

    lane._recreate_api = fail_recreate  # type: ignore[method-assign]
    lane._rollback = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass", "restored_image_id": "sha256:prior"}
    )

    with pytest.raises(
        DeployError,
        match="deployment_failed_rolled_back:api_recreate_partial_failure",
    ):
        lane.deploy()

    assert observed_before_recreate["api_mutation_started"] is True
    assert observed_before_recreate["api_runtime_state"] == "mutation_possible"
    assert observed_before_recreate["attempted_actions"] == [
        "ensure_redis",
        "protect_previous_image",
        "stop_api_for_gemini_oauth",
        "provision_gemini_oauth",
    ]
    assert observed_before_recreate["completed_actions"] == [
        "ensure_redis",
        "protect_previous_image",
        "stop_api_for_gemini_oauth",
        "provision_gemini_oauth",
    ]
    lane._rollback.assert_called_once()
    receipt = _receipt(lane)
    assert receipt["status"] == "failed_rolled_back"
    assert receipt["preparation"]["api_mutation_started"] is True
    assert receipt["preparation"]["api_runtime_state"] == "restored_by_rollback"
    guards = [
        check
        for check in receipt["checks"]
        if check.get("name") == "vexp_soak_mutation_guard"
    ]
    assert [guard["boundary"] for guard in guards] == [
        "before_ensure_redis",
        "before_protect_previous_image",
        "before_recreate_api",
        "before_recreate_api",
        "before_recreate_api",
    ]


@pytest.mark.parametrize("remove_after", ["ensure_redis", "protect_previous_image"])
def test_permit_is_re_read_at_each_boundary_before_api_mutation(
    tmp_path: Path, remove_after: str
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _install_preflight(lane, tmp_path)
    actions: list[str] = []

    def ensure(*, before_mutation: Callable[[str], None]) -> None:
        before_mutation("before_redis_create")
        actions.append("ensure_redis")
        if remove_after == "ensure_redis":
            permit_path.unlink()

    def protect(
        _previous: Mapping[str, object],
        *,
        before_mutation: Callable[[str], None],
    ) -> str:
        before_mutation("before_protect_previous_image_tag")
        actions.append("protect_previous_image")
        if remove_after == "protect_previous_image":
            permit_path.unlink()
        return "ea-runtime:rollback-guard-test"

    lane._ensure_redis = ensure  # type: ignore[method-assign]
    lane._protect_previous_image = protect  # type: ignore[method-assign]
    lane._recreate_api = Mock()  # type: ignore[method-assign]
    lane._rollback = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("rollback must not run before API mutation")
    )

    with pytest.raises(DeployError, match="vexp_mutation_permit_unavailable"):
        lane.deploy()

    assert runner.commands == []
    lane._recreate_api.assert_not_called()
    lane._rollback.assert_not_called()
    expected = (
        ["ensure_redis"]
        if remove_after == "ensure_redis"
        else ["ensure_redis", "protect_previous_image"]
    )
    assert actions == expected
    receipt = _receipt(lane)
    assert receipt["status"] == "failed_during_preparation"
    assert receipt["preparation"] == {
        "status": "failed_during_action",
        "attempted_actions": expected,
        "completed_actions": (
            []
            if remove_after == "ensure_redis"
            else ["ensure_redis"]
        ),
        "pending_action": None,
        "active_action": remove_after,
        "preparation_side_effects_possible": True,
        "api_mutation_started": False,
        "api_runtime_state": "unchanged",
        "rollback_required": False,
    }
    assert receipt["rollback"]["status"] == "not_required"
    assert receipt["rollback"]["reason"] == "api_unchanged"


def test_terminal_identity_digest_ignores_mutable_sentinel_metrics() -> None:
    first = _state(terminal=True)
    second = {**first, "updated_at": "2026-07-20T10:01:00.000Z", "probes_passed": 99}

    assert deploy._vexp_terminal_identity_sha256(first) == (
        deploy._vexp_terminal_identity_sha256(second)
    )


@pytest.mark.parametrize(
    ("change_kind", "reason"),
    [
        ("phase", "vexp_sentinel_state_not_terminal_after_permit"),
        ("epoch", "vexp_sentinel_terminal_identity_changed_after_permit"),
    ],
)
def test_terminal_state_change_after_permit_read_denies_before_mutation(
    tmp_path: Path, change_kind: str, reason: str
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    initial = _state(terminal=True)
    changed = dict(initial)
    if change_kind == "phase":
        changed["qualification_phase"] = "enforced_soak"
    else:
        changed["epoch_started_at"] = "2026-07-13T09:43:56.207Z"
        changed["epoch_started_ms"] = 1783935836207
    _write_json(state_path, initial, mode=0o600)
    _write_permit(lane, permit_path, _permit(initial))
    real_read_permit = lane._read_trusted_vexp_mutation_permit

    def read_permit_then_change_state() -> tuple[dict[str, object], str]:
        permit = real_read_permit()
        _write_json(state_path, changed, mode=0o600)
        return permit

    lane._read_trusted_vexp_mutation_permit = (  # type: ignore[method-assign]
        read_permit_then_change_state
    )
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock()  # type: ignore[method-assign]

    with pytest.raises(DeployError, match=reason):
        lane.deploy()

    assert runner.commands == []
    lane._ensure_redis.assert_not_called()
    guard = _receipt(lane)["checks"][-1]
    assert guard["reason"] == reason
    assert guard["state_sha256"] == hashlib.sha256(state_path.read_bytes()).hexdigest()


def test_mutable_metrics_change_during_validation_requires_new_root_predicate(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    initial = _state(terminal=True)
    changed = {
        **initial,
        "updated_at": "2026-07-20T09:59:15.000Z",
        "probes_passed": 99,
    }
    _write_json(state_path, initial, mode=0o600)
    _write_permit(lane, permit_path, _permit(initial))
    real_read_permit = lane._read_trusted_vexp_mutation_permit

    def read_permit_then_update_metrics() -> tuple[dict[str, object], str]:
        permit = real_read_permit()
        _write_json(state_path, changed, mode=0o600)
        return permit

    lane._read_trusted_vexp_mutation_permit = (  # type: ignore[method-assign]
        read_permit_then_update_metrics
    )

    with pytest.raises(
        DeployError, match="vexp_current_predicate_wall_clock_invalid"
    ):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            pass

    guard = _receipt(lane)["checks"][-1]
    assert guard["status"] == "fail"
    assert guard["reason"] == "vexp_current_predicate_wall_clock_invalid"
    assert guard["state_sha256"] == hashlib.sha256(state_path.read_bytes()).hexdigest()
    assert guard["current_predicate"]["generation"] == 1


def test_mutable_sentinel_updates_require_fresh_root_predicate_generation(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    first = _state(terminal=True)
    _write_json(state_path, first, mode=0o600)
    _write_permit(lane, permit_path, _permit(first))

    lane._require_vexp_mutation_permitted("before_ensure_redis")
    second = {
        **first,
        "updated_at": "2026-07-20T09:59:15.000Z",
        "probes_passed": 99,
    }
    _write_json(state_path, second, mode=0o600)
    with pytest.raises(
        DeployError, match="vexp_current_predicate_wall_clock_invalid"
    ):
        lane._require_vexp_mutation_permitted("before_protect_previous_image")
    _write_current_predicate(lane)
    lane._require_vexp_mutation_permitted("before_protect_previous_image")

    guards = _receipt(lane)["checks"]
    assert len(guards) == 3
    assert [guard["status"] for guard in guards] == ["pass", "fail", "pass"]
    assert guards[0]["state_sha256"] != guards[2]["state_sha256"]
    assert (
        guards[0]["terminal_identity_sha256"]
        == guards[2]["terminal_identity_sha256"]
    )
    assert guards[0]["current_predicate"]["generation"] == 1
    assert guards[2]["current_predicate"]["generation"] == 2


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"epoch_started_ms": 1783935836207},
            "vexp_current_predicate_record_contract_invalid",
        ),
        (
            {"boot_id": "11111111-1111-4111-8111-111111111111"},
            "vexp_current_predicate_boot_id_invalid",
        ),
        (
            {"monotonic_ns": 1},
            "vexp_current_predicate_monotonic_clock_invalid",
        ),
        (
            {
                "observed_at": "2026-07-20T09:54:59.999Z",
                "recorded_at": "2026-07-20T09:54:59.999Z",
            },
            "vexp_current_predicate_wall_clock_invalid",
        ),
        (
            {"sentinel_state_sha256": "0" * 64},
            "vexp_current_predicate_binding_invalid",
        ),
        (
            {"qualification_certificate_sha256": "0" * 64},
            "vexp_current_predicate_binding_invalid",
        ),
        (
            {"sentinel_producer_sha256": "0" * 64},
            "vexp_current_predicate_binding_invalid",
        ),
        (
            {"root_predicate_producer_sha256": "0" * 64},
            "vexp_current_predicate_binding_invalid",
        ),
        (
            {"current_resources_healthy": False},
            "vexp_current_predicate_binding_invalid",
        ),
    ],
)
def test_root_current_predicate_exact_bindings_fail_closed(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _rewrite_current_predicate_record(lane, changes)

    with pytest.raises(DeployError, match=reason):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    assert runner.commands == []
    assert _receipt(lane)["checks"][-1]["reason"] == reason


def test_root_current_predicate_missing_or_noncanonical_pointer_denies(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    pointer_path = lane._vexp_mutation_authority.current_predicate_pointer_path
    pointer = json.loads(pointer_path.read_bytes())
    pointer_path.write_text(
        json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pointer_path.chmod(0o640)

    with pytest.raises(
        DeployError, match="vexp_current_predicate_pointer_not_canonical"
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    pointer_path.unlink()
    with pytest.raises(
        DeployError, match="vexp_current_predicate_pointer_unavailable"
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


def test_root_current_predicate_requires_trusted_directory_chain_and_manifest(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    authority = lane._vexp_mutation_authority
    manifest_path = authority.current_predicate_producer_manifest_path
    manifest = json.loads(manifest_path.read_bytes())
    manifest["status"] = "unreviewed"
    manifest_path.write_bytes(deploy._canonical_guard_json_bytes(manifest))
    manifest_path.chmod(0o640)

    with pytest.raises(
        DeployError,
        match="vexp_current_predicate_producer_manifest_contract_invalid",
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    manifest["status"] = "reviewed"
    manifest_path.write_bytes(deploy._canonical_guard_json_bytes(manifest))
    manifest_path.chmod(0o640)
    authority.current_predicate_root.chmod(0o770)
    with pytest.raises(
        DeployError, match="vexp_current_predicate_directory_chain_untrusted"
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


def test_root_current_predicate_generation_chain_is_exact(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _write_current_predicate(lane)
    records = lane._vexp_mutation_authority.current_predicate_records_directory
    previous = records / f"{state['epoch_started_ms']}-1.json"
    previous.write_bytes(previous.read_bytes() + b" ")
    previous.chmod(0o640)

    with pytest.raises(
        DeployError, match="vexp_current_predicate_generation_invalid"
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


def test_deploy_current_predicate_full_chain_rejects_internal_gap(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _write_current_predicate(lane)
    _write_current_predicate(lane)
    records = lane._vexp_mutation_authority.current_predicate_records_directory
    (records / f"{state['epoch_started_ms']}-2.json").unlink()

    with pytest.raises(DeployError, match="generation_invalid"):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


@pytest.mark.parametrize("tamper", ["alternate_fork", "nonmaximal_head"])
def test_deploy_current_predicate_full_chain_rejects_fork_or_nonmaximal_head(
    tmp_path: Path, tamper: str
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _write_current_predicate(lane)
    authority = lane._vexp_mutation_authority
    if tamper == "alternate_fork":
        fork = (
            authority.current_predicate_records_directory
            / f"{state['epoch_started_ms']}-2.fork.json"
        )
        fork.write_bytes(b"{}\n")
        fork.chmod(0o640)
    else:
        pointer_path = authority.current_predicate_pointer_path
        prior_pointer_raw = pointer_path.read_bytes()
        _write_current_predicate(lane)
        pointer_path.write_bytes(prior_pointer_raw)
        pointer_path.chmod(0o640)

    with pytest.raises(DeployError, match="generation_invalid"):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


def test_deploy_current_predicate_full_chain_rejects_rehashed_unhealthy_root(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _write_current_predicate(lane)
    _write_current_predicate(lane)
    authority = lane._vexp_mutation_authority
    records = authority.current_predicate_records_directory
    first_path = records / f"{state['epoch_started_ms']}-1.json"
    second_path = records / f"{state['epoch_started_ms']}-2.json"
    third_path = records / f"{state['epoch_started_ms']}-3.json"
    first = json.loads(first_path.read_bytes())
    first["current_resources_healthy"] = False
    first_raw = deploy._canonical_guard_json_bytes(first)
    first_path.write_bytes(first_raw)
    first_path.chmod(0o640)
    second = json.loads(second_path.read_bytes())
    second["previous_record_sha256"] = hashlib.sha256(first_raw).hexdigest()
    second_raw = deploy._canonical_guard_json_bytes(second)
    second_path.write_bytes(second_raw)
    second_path.chmod(0o640)
    third = json.loads(third_path.read_bytes())
    third["previous_record_sha256"] = hashlib.sha256(second_raw).hexdigest()
    third_raw = deploy._canonical_guard_json_bytes(third)
    third_path.write_bytes(third_raw)
    third_path.chmod(0o640)
    pointer_path = authority.current_predicate_pointer_path
    pointer = json.loads(pointer_path.read_bytes())
    pointer["record_sha256"] = hashlib.sha256(third_raw).hexdigest()
    pointer_path.write_bytes(deploy._canonical_guard_json_bytes(pointer))
    pointer_path.chmod(0o640)

    with pytest.raises(DeployError, match="binding_invalid"):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


def test_deploy_current_predicate_full_chain_rejects_current_boot_change(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    _write_current_predicate(lane)
    authority = lane._vexp_mutation_authority
    assert isinstance(authority, TestVexpMemorialMutationAuthority)
    authority._current_boot_id = "11111111-1111-4111-8111-111111111111"

    with pytest.raises(DeployError, match="boot_id_invalid"):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


def test_root_current_predicate_receipt_summary_is_exact_and_safe(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))

    lane._require_vexp_mutation_permitted("before_ensure_redis")

    guard = _receipt(lane)["checks"][-1]
    summary = guard["current_predicate"]
    assert set(summary) == deploy.VEXP_CURRENT_PREDICATE_STATUS_KEYS
    assert summary["status"] == "positive"
    assert summary["sentinel_producer_sha256"] == "1" * 64
    assert summary["root_predicate_producer_sha256"] == (
        TEST_ROOT_PREDICATE_PRODUCER_SHA256
    )
    assert "sentinel_state_path" not in summary


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"updated_at": None}, "vexp_sentinel_updated_at_invalid"),
        (
            {"updated_at": "2026-07-20T09:54:59.999Z"},
            "vexp_sentinel_state_stale",
        ),
        (
            {"updated_at": "2026-07-20T10:00:30.001Z"},
            "vexp_sentinel_state_from_future",
        ),
        (
            {"current_resources_healthy": False},
            "vexp_sentinel_resources_unhealthy",
        ),
        (
            {"current_resources_healthy": None},
            "vexp_sentinel_resources_unhealthy",
        ),
        (
            {"certification_blockers": ["probe:failed"]},
            "vexp_sentinel_certification_blockers_present",
        ),
        (
            {"certification_blockers": None},
            "vexp_sentinel_certification_blockers_present",
        ),
    ],
)
def test_terminal_sentinel_liveness_is_mandatory_before_permit_use(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    permit = _permit(state)
    state.update(changes)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, permit)

    with pytest.raises(DeployError, match=reason):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    assert runner.commands == []
    assert _receipt(lane)["checks"][-1]["reason"] == reason


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"updated_at": "2026-07-20T09:54:59.999Z"},
            "vexp_sentinel_state_stale",
        ),
        (
            {"current_resources_healthy": False},
            "vexp_sentinel_resources_unhealthy",
        ),
        (
            {"certification_blockers": ["probe:failed"]},
            "vexp_sentinel_certification_blockers_present",
        ),
    ],
)
def test_liveness_regression_during_permit_validation_denies_mutation(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    initial = _state(terminal=True)
    changed = {**initial, **changes}
    _write_json(state_path, initial, mode=0o600)
    _write_permit(lane, permit_path, _permit(initial))
    real_read_permit = lane._read_trusted_vexp_mutation_permit

    def read_permit_then_regress_liveness() -> tuple[dict[str, object], str]:
        permit = real_read_permit()
        _write_json(state_path, changed, mode=0o600)
        return permit

    lane._read_trusted_vexp_mutation_permit = (  # type: ignore[method-assign]
        read_permit_then_regress_liveness
    )

    with pytest.raises(DeployError, match=reason):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            pass

    assert runner.commands == []
    assert _receipt(lane)["checks"][-1]["reason"] == reason


def test_terminal_state_without_positive_permit_fails_closed(tmp_path: Path) -> None:
    lane, runner, state_path, _permit_path = _lane(tmp_path)
    _write_json(state_path, _state(terminal=True), mode=0o600)

    with pytest.raises(
        DeployError, match="vexp_current_predicate_pointer_unavailable"
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    assert runner.commands == []
    assert _receipt(lane)["checks"][-1]["status"] == "fail"


def test_terminal_state_and_permit_without_root_certificate_fail_closed(
    tmp_path: Path,
) -> None:
    lane, runner, state_path, permit_path = _lane(
        tmp_path, create_certificate=False
    )
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))

    with pytest.raises(
        DeployError, match="vexp_qualification_certificate_unavailable"
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    assert runner.commands == []
    guard = _receipt(lane)["checks"][-1]
    assert guard["status"] == "fail"
    assert guard["reason"] == "vexp_qualification_certificate_unavailable"
    assert "permit_sha256" not in guard


def test_exact_root_certificate_and_sidecar_are_independently_accepted(
    tmp_path: Path,
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)

    certificate, evidence = lane._read_trusted_vexp_qualification_certificate(
        state
    )

    assert certificate["schema"] == deploy.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
    assert evidence == _certificate_evidence(state)


def test_post_qualification_nonfatal_tail_preserves_qualification_event_binding(
    tmp_path: Path,
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)

    certificate, evidence = lane._read_trusted_vexp_qualification_certificate(
        state
    )

    active_chain = certificate["active_chain"]
    assert isinstance(active_chain, dict)
    qualification_event = active_chain["qualification_event"]
    assert isinstance(qualification_event, dict)
    terminal_state = certificate["terminal_state"]
    assert isinstance(terminal_state, dict)
    assert evidence["event_hash"] == qualification_event["hash"]
    assert evidence["event_hash"] != active_chain["tail_hash"]
    assert terminal_state["last_event_hash"] == active_chain["tail_hash"]


def test_current_state_predicate_contract_must_match_root_certificate(
    tmp_path: Path,
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    state["predicate_contract_sha256"] = "0" * 64

    with pytest.raises(
        DeployError, match="predicate_contract_binding_invalid"
    ):
        lane._read_trusted_vexp_qualification_certificate(state)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("schema", "contract_invalid"),
        ("duration", "duration_invalid"),
        ("monotonic", "duration_invalid"),
        ("event", "chain_invalid"),
        ("index", "chain_invalid"),
        ("terminal", "terminal_state_invalid"),
        ("predicate", "predicate_contract_binding_invalid"),
        ("attestation", "attestations_invalid"),
        ("seal", "seal_invalid"),
    ],
)
def test_certificate_v2_critical_contract_fails_closed(
    tmp_path: Path, change: str, reason: str
) -> None:
    lane, runner, _state_path, _permit_path = _lane(
        tmp_path, create_certificate=False
    )
    state = _state(terminal=True)
    certificate = _certificate(state)
    if change == "schema":
        certificate["schema"] = "ea.vexp_qualification_certificate.v1"
    elif change == "duration":
        certificate["qualification_duration_ms"] = (
            deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS - 1
        )
    elif change == "monotonic":
        certificate["qualification_monotonic_duration_ms"] = (
            deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS - 1
        )
    elif change == "event":
        active_chain = certificate["active_chain"]
        assert isinstance(active_chain, dict)
        qualification_event = active_chain["qualification_event"]
        assert isinstance(qualification_event, dict)
        qualification_event["event"] = "wrong_event"
    elif change == "index":
        active_chain = certificate["active_chain"]
        assert isinstance(active_chain, dict)
        active_chain["index_sha256"] = "0" * 64
    elif change == "terminal":
        terminal_state = certificate["terminal_state"]
        assert isinstance(terminal_state, dict)
        terminal_state["certification_blockers"] = ["blocked"]
    elif change == "predicate":
        terminal_state = certificate["terminal_state"]
        assert isinstance(terminal_state, dict)
        terminal_state["predicate_contract_sha256"] = "0" * 64
    elif change == "attestation":
        attestations = certificate["source_attestations"]
        assert isinstance(attestations, dict)
        attestations["implementation"] = {}
    else:
        seal = certificate["seal"]
        assert isinstance(seal, dict)
        seal["docker_socket_used"] = True
    _reseal_certificate(certificate)
    directory = lane._vexp_mutation_authority.qualification_certificate_directory
    _write_certificate(directory, state, certificate=certificate)

    with pytest.raises(DeployError, match=reason):
        lane._read_trusted_vexp_qualification_certificate(state)

    assert runner.commands == []


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
def test_deploy_certificate_v2_requires_exact_boot_and_monotonic_endpoints(
    tmp_path: Path, change: str, reason: str
) -> None:
    lane, runner, _state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)
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
    _reseal_certificate(certificate)

    with pytest.raises(DeployError, match=reason):
        lane._validate_vexp_qualification_certificate(certificate, state=state)

    assert runner.commands == []


def test_deploy_plane_denies_when_reviewed_implementation_manifest_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane, runner, _state_path, _permit_path = _lane(tmp_path)
    missing = tmp_path / "reviewed-implementation-manifest.json"
    monkeypatch.setattr(
        deploy, "VEXP_QUALIFICATION_IMPLEMENTATION_MANIFEST_PATH", missing
    )

    with pytest.raises(
        DeployError,
        match="vexp_qualification_implementation_manifest_missing",
    ):
        MemorialDeployLane._require_reviewed_vexp_qualification_implementation_manifest(
            lane, _certificate(_state(terminal=True))
        )

    assert runner.commands == []


@pytest.mark.parametrize(
    "sidecar",
    [
        b"0" * 64 + b"\n",
        b"sha256:" + b"0" * 64,
        b"SHA256:" + b"0" * 64 + b"\n",
        b"sha256:" + b"0" * 64 + b"\n",
    ],
)
def test_certificate_sidecar_is_exact_and_content_bound(
    tmp_path: Path, sidecar: bytes
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(
        tmp_path, create_certificate=False
    )
    state = _state(terminal=True)
    _write_certificate(
        lane._vexp_mutation_authority.qualification_certificate_directory,
        state,
        sidecar=sidecar,
    )

    with pytest.raises(
        DeployError, match="vexp_qualification_certificate_sidecar_invalid"
    ):
        lane._read_trusted_vexp_qualification_certificate(state)


@pytest.mark.parametrize("target", ["root", "directory", "certificate", "sidecar"])
def test_certificate_authority_metadata_is_fail_closed(
    tmp_path: Path, target: str
) -> None:
    lane, _runner, _state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    authority = lane._vexp_mutation_authority
    certificate_path = (
        authority.qualification_certificate_directory
        / f"{state['epoch_started_ms']}.json"
    )
    selected = {
        "root": authority.qualification_certificate_root,
        "directory": authority.qualification_certificate_directory,
        "certificate": certificate_path,
        "sidecar": certificate_path.with_suffix(".json.sha256"),
    }[target]
    selected.chmod(0o755 if target in {"root", "directory"} else 0o644)

    with pytest.raises(DeployError, match="vexp_qualification_certificate_"):
        lane._read_trusted_vexp_qualification_certificate(state)


def test_certificate_change_between_independent_reads_denies_before_mutation(
    tmp_path: Path,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, _permit(state))
    real_read = lane._read_trusted_vexp_qualification_certificate
    reads = 0

    def read_then_remove(
        selected_state: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, str]]:
        nonlocal reads
        result = real_read(selected_state)
        reads += 1
        if reads == 1:
            certificate_path = (
                lane._vexp_mutation_authority.qualification_certificate_directory
                / f"{state['epoch_started_ms']}.json"
            )
            certificate_path.unlink()
        return result

    lane._read_trusted_vexp_qualification_certificate = (  # type: ignore[method-assign]
        read_then_remove
    )

    with pytest.raises(
        DeployError, match="vexp_qualification_certificate_unavailable"
    ):
        with lane._vexp_mutation_lease("before_ensure_redis"):
            raise AssertionError("mutation body must not run")

    assert reads == 1
    assert runner.commands == []


@pytest.mark.parametrize("untrusted_kind", ["mode", "symlink", "hardlink"])
def test_sentinel_requires_0600_regular_single_link_nofollow_file(
    tmp_path: Path, untrusted_kind: str
) -> None:
    state_path = tmp_path / "sentinel-state.json"
    if untrusted_kind == "mode":
        _write_json(state_path, _state(terminal=True), mode=0o640)
    elif untrusted_kind == "symlink":
        target = tmp_path / "real-state.json"
        _write_json(target, _state(terminal=True), mode=0o600)
        state_path.symlink_to(target)
    else:
        target = tmp_path / "linked-state.json"
        _write_json(target, _state(terminal=True), mode=0o600)
        os.link(target, state_path)
    lane, _runner, _state_path, _permit_path = _lane(tmp_path, state_path=state_path)

    with pytest.raises(DeployError):
        lane._read_trusted_vexp_sentinel_state()


def test_exact_0600_sentinel_file_is_accepted(tmp_path: Path) -> None:
    lane, _runner, state_path, _permit_path = _lane(tmp_path)
    _write_json(state_path, _state(terminal=True), mode=0o600)

    payload, digest = lane._read_trusted_vexp_sentinel_state()

    assert payload["version"] == 6
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_sentinel_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    lane, _runner, state_path, _permit_path = _lane(tmp_path)

    _assert_fifo_rejected_immediately(
        state_path,
        mode=0o600,
        reader=lane._read_trusted_vexp_sentinel_state,
        reason="vexp_sentinel_state_untrusted",
    )


@pytest.mark.parametrize(
    ("flag", "reason"),
    [
        ("O_NOFOLLOW", "nofollow_unavailable"),
        ("O_NONBLOCK", "nonblock_unavailable"),
    ],
)
def test_sentinel_read_requires_safe_open_flag_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    reason: str,
) -> None:
    lane, _runner, state_path, _permit_path = _lane(tmp_path)
    _write_json(state_path, _state(terminal=True), mode=0o600)
    monkeypatch.delattr(deploy.os, flag)

    with pytest.raises(DeployError, match=f"vexp_sentinel_state_{reason}"):
        lane._read_trusted_vexp_sentinel_state()


def test_sentinel_atomic_read_rejects_path_identity_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane, _runner, state_path, _permit_path = _lane(tmp_path)
    _write_json(state_path, _state(terminal=True), mode=0o600)
    real_identity = deploy._trusted_file_identity
    calls = 0

    def unstable_identity(metadata: os.stat_result) -> tuple[int, ...]:
        nonlocal calls
        calls += 1
        identity = real_identity(metadata)
        if calls == 3:
            return (*identity[:-1], identity[-1] + 1)
        return identity

    monkeypatch.setattr(deploy, "_trusted_file_identity", unstable_identity)

    with pytest.raises(DeployError, match="vexp_sentinel_state_changed_during_read"):
        lane._read_trusted_vexp_sentinel_state()


@pytest.mark.parametrize("untrusted_kind", ["mode", "symlink", "hardlink"])
def test_permit_requires_0644_regular_single_link_nofollow_file(
    tmp_path: Path, untrusted_kind: str
) -> None:
    state = _state(terminal=True)
    permit_path = tmp_path / "mutation-permit.json"
    lane, _runner, _state_path, _permit_path = _lane(
        tmp_path, permit_path=permit_path
    )
    if untrusted_kind == "mode":
        _write_permit(lane, permit_path, _permit(state), mode=0o664)
    elif untrusted_kind == "symlink":
        target = tmp_path / "real-permit.json"
        _write_permit(lane, target, _permit(state))
        permit_path.symlink_to(target)
    else:
        target = tmp_path / "linked-permit.json"
        _write_permit(lane, target, _permit(state))
        os.link(target, permit_path)

    with pytest.raises(DeployError):
        lane._read_trusted_vexp_mutation_permit()


def test_permit_root_owner_requirement_is_injectable_without_root(
    tmp_path: Path,
) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(
        tmp_path, permit_owner_uid=os.geteuid() + 1
    )
    _write_permit(lane, permit_path, _permit(state))

    with pytest.raises(DeployError, match="vexp_mutation_permit_untrusted"):
        lane._read_trusted_vexp_mutation_permit()


def test_exact_0644_permit_with_injected_owner_is_accepted(tmp_path: Path) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    _write_permit(lane, permit_path, _permit(state))

    payload, digest = lane._read_trusted_vexp_mutation_permit()

    assert payload["status"] == "allow"
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_permit_without_committed_marker_is_never_consumable(tmp_path: Path) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    _write_json(permit_path, _permit(state), mode=0o644)

    with pytest.raises(
        DeployError, match="vexp_mutation_permit_commit_unavailable"
    ):
        lane._read_trusted_vexp_mutation_permit()


@pytest.mark.parametrize("untrusted_kind", ["mode", "symlink", "hardlink"])
def test_permit_commit_marker_requires_trusted_regular_single_link_file(
    tmp_path: Path,
    untrusted_kind: str,
) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    _write_permit(lane, permit_path, _permit(state))
    commit_path = lane._vexp_mutation_authority.mutation_permit_commit_path
    raw = commit_path.read_bytes()
    commit_path.unlink()
    if untrusted_kind == "mode":
        commit_path.write_bytes(raw)
        commit_path.chmod(0o664)
    elif untrusted_kind == "symlink":
        target = tmp_path / "real-permit-commit.json"
        target.write_bytes(raw)
        target.chmod(0o644)
        commit_path.symlink_to(target)
    else:
        target = tmp_path / "linked-permit-commit.json"
        target.write_bytes(raw)
        target.chmod(0o644)
        os.link(target, commit_path)

    with pytest.raises(
        DeployError,
        match=r"vexp_mutation_permit_commit_(?:unavailable|untrusted)",
    ):
        lane._read_trusted_vexp_mutation_permit()


@pytest.mark.parametrize(
    "change",
    [
        {"status": "prepared"},
        {"permit_sha256": "0" * 64},
        {"epoch_started_ms": 1783935836207},
        {"unexpected": True},
    ],
)
def test_permit_commit_contract_and_binding_fail_closed(
    tmp_path: Path,
    change: dict[str, object],
) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    payload = _permit(state)
    _write_permit(lane, permit_path, payload)
    commit_path = lane._vexp_mutation_authority.mutation_permit_commit_path
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    commit.update(change)
    _write_json(commit_path, commit, mode=0o644)

    with pytest.raises(
        DeployError,
        match=r"vexp_mutation_permit_commit_(?:schema|contract|binding)_invalid",
    ):
        lane._read_trusted_vexp_mutation_permit()


def test_permit_rewrite_after_commit_marker_is_not_consumable(tmp_path: Path) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    payload = _permit(state)
    _write_permit(lane, permit_path, payload)
    payload["expires_at"] = "2026-07-20T10:29:00.000Z"
    _write_json(permit_path, payload, mode=0o644)

    with pytest.raises(
        DeployError, match="vexp_mutation_permit_commit_binding_invalid"
    ):
        lane._read_trusted_vexp_mutation_permit()


def test_permit_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    payload = _permit(_state(terminal=True))
    _write_permit_commit(lane, payload, b"untrusted-special-file")

    _assert_fifo_rejected_immediately(
        permit_path,
        mode=0o644,
        reader=lane._read_trusted_vexp_mutation_permit,
        reason="vexp_mutation_permit_untrusted",
    )


@pytest.mark.parametrize("guard_kind", ["sentinel", "permit"])
def test_guard_rejects_unix_domain_socket_file(tmp_path: Path, guard_kind: str) -> None:
    special_path = tmp_path / ("s" if guard_kind == "sentinel" else "p")
    lane, _runner, _state_path, _permit_path = _lane(
        tmp_path,
        state_path=special_path if guard_kind == "sentinel" else None,
        permit_path=special_path if guard_kind == "permit" else None,
    )
    mode = 0o600 if guard_kind == "sentinel" else 0o644
    reader = (
        lane._read_trusted_vexp_sentinel_state
        if guard_kind == "sentinel"
        else lane._read_trusted_vexp_mutation_permit
    )
    if guard_kind == "permit":
        payload = _permit(_state(terminal=True))
        _write_permit_commit(lane, payload, b"untrusted-special-file")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(special_path))
        special_path.chmod(mode)
        with pytest.raises(DeployError, match=r"_(?:unavailable|untrusted)$"):
            reader()


@pytest.mark.parametrize(
    ("flag", "reason"),
    [
        ("O_NOFOLLOW", "nofollow_unavailable"),
        ("O_NONBLOCK", "nonblock_unavailable"),
    ],
)
def test_permit_read_requires_safe_open_flag_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    reason: str,
) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    _write_permit(lane, permit_path, _permit(state))
    monkeypatch.delattr(deploy.os, flag)

    with pytest.raises(
        DeployError,
        match=rf"vexp_mutation_permit(?:_commit)?_{reason}",
    ):
        lane._read_trusted_vexp_mutation_permit()


def test_permit_atomic_read_rejects_path_identity_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    _write_permit(lane, permit_path, _permit(state))
    real_identity = deploy._trusted_file_identity
    calls = 0

    def unstable_identity(metadata: os.stat_result) -> tuple[int, ...]:
        nonlocal calls
        calls += 1
        identity = real_identity(metadata)
        if calls == 3:
            return (*identity[:-1], identity[-1] + 1)
        return identity

    monkeypatch.setattr(deploy, "_trusted_file_identity", unstable_identity)

    with pytest.raises(
        DeployError,
        match="vexp_mutation_permit_commit_changed_during_read",
    ):
        lane._read_trusted_vexp_mutation_permit()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"contract_name": "wrong"}, "contract_invalid"),
        ({"version": 1}, "version_invalid"),
        ({"version": True}, "version_invalid"),
        ({"status": "deny"}, "not_positive"),
        ({"mutation_boundaries": []}, "boundaries_invalid"),
        ({"epoch_started_at": "2026-07-13T09:43:56.207Z"}, "terminal_binding"),
        ({"epoch_started_ms": 1783935836207}, "terminal_binding"),
        (
            {"qualification_earliest_completion_at": "2026-07-20T09:43:57.206Z"},
            "terminal_binding",
        ),
        ({"qualified_at": "2026-07-20T09:43:57.206Z"}, "terminal_binding"),
        ({"terminal_identity_sha256": "0" * 64}, "identity_digest"),
        (
            {"qualification_certificate_schema": "ea.vexp_qualification_certificate.v1"},
            "certificate_binding_invalid",
        ),
        (
            {"qualification_certificate_sha256": "0" * 64},
            "certificate_binding_mismatch",
        ),
        (
            {"qualification_certificate_identity": f"sha256:{'0' * 64}"},
            "certificate_binding_mismatch",
        ),
        (
            {"qualification_certificate_event_hash": "0" * 64},
            "certificate_binding_mismatch",
        ),
        ({"issued_at": "not-a-time"}, "issued_at_invalid"),
        ({"expires_at": "not-a-time"}, "expires_at_invalid"),
        (
            {
                "issued_at": "2026-07-20T09:43:00.000Z",
                "expires_at": "2026-07-20T10:00:00.000Z",
            },
            "validity_invalid",
        ),
        ({"expires_at": "2026-07-20T09:45:00.000Z"}, "validity_invalid"),
        ({"expires_at": "2026-07-20T10:46:00.000Z"}, "validity_invalid"),
        (
            {
                "issued_at": "2026-07-20T10:01:00.000Z",
                "expires_at": "2026-07-20T10:30:00.000Z",
            },
            "not_current",
        ),
        ({"expires_at": "2026-07-20T09:59:59.999Z"}, "not_current"),
    ],
)
def test_permit_schema_terminal_binding_and_freshness_fail_closed(
    tmp_path: Path, changes: dict[str, object], reason: str
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    payload = _permit(state)
    payload.update(changes)
    _write_json(state_path, state, mode=0o600)
    _write_permit(lane, permit_path, payload)

    with pytest.raises(DeployError, match=reason):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    assert runner.commands == []


@pytest.mark.parametrize("schema_change", ["missing", "extra", "duplicate"])
def test_permit_schema_is_exact_and_duplicate_keys_are_rejected(
    tmp_path: Path, schema_change: str
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    payload = _permit(state)
    _write_json(state_path, state, mode=0o600)
    if schema_change == "missing":
        payload.pop("status")
        _write_permit(lane, permit_path, payload)
    elif schema_change == "extra":
        payload["unexpected"] = True
        _write_permit(lane, permit_path, payload)
    else:
        raw = json.dumps(payload).replace(
            '"contract_name":',
            '"contract_name":"duplicate","contract_name":',
            1,
        )
        _write_raw_permit(
            lane,
            permit_path,
            payload,
            (raw + "\n").encode("utf-8"),
        )

    expected = "json_invalid" if schema_change == "duplicate" else "schema_invalid"
    with pytest.raises(DeployError, match=expected):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


@pytest.mark.parametrize("permit_kind", ["missing", "partial_json", "oversized"])
def test_missing_partial_or_oversized_permit_fails_closed(
    tmp_path: Path, permit_kind: str
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    _write_json(state_path, _state(terminal=True), mode=0o600)
    if permit_kind == "partial_json":
        permit_path.write_bytes(b'{"version": 1')
        permit_path.chmod(0o644)
    elif permit_kind == "oversized":
        permit_path.write_bytes(b"{" + b" " * deploy.MAX_VEXP_MUTATION_PERMIT_BYTES)
        permit_path.chmod(0o644)

    with pytest.raises(DeployError):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 5},
        {"version": True},
        {"epoch_started_ms": 1783935836205},
        {"epoch_started_at": "2026-07-13T09:43:56.206001Z"},
        {"qualification_phase": "qualified", "qualified_at": None},
        {"qualification_earliest_completion_at": None},
        {"qualification_earliest_completion_at": "2026-07-20T09:43:56.205Z"},
        {"qualified_at": "2026-07-20T09:43:56.205Z"},
    ],
)
def test_invalid_or_contradictory_terminal_state_fails_before_permit(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    lane, runner, state_path, _permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    state.update(changes)
    _write_json(state_path, state, mode=0o600)

    with pytest.raises(DeployError):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    assert runner.commands == []


def test_unknown_mutation_boundary_fails_closed_without_file_reads(
    tmp_path: Path,
) -> None:
    lane, runner, _state_path, _permit_path = _lane(tmp_path)

    with pytest.raises(DeployError, match="vexp_mutation_boundary_invalid"):
        lane._require_vexp_mutation_permitted("before_unknown_mutation")

    assert runner.commands == []
