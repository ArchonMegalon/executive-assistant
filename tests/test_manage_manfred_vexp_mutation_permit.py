from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import manage_manfred_vexp_mutation_permit as manager


NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)


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


@pytest.fixture
def authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    authority_parent = tmp_path / "run"
    authority_parent.mkdir()
    permit_parent = authority_parent / "ea"
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
    monkeypatch.setattr(manager, "LOCK_PATH", permit_parent / "permit.lock")
    monkeypatch.setattr(manager, "_utc_now_datetime", lambda: NOW)
    monkeypatch.setattr(manager, "_verify_trusted_execution_path", lambda: None)
    state_path = tmp_path / "state.json"
    _write_certificate(_state())
    return state_path, permit_parent


def _issue(state_path: Path, payload: object | None = None) -> dict[str, object]:
    _write_state(state_path, _state() if payload is None else payload)
    return manager.issue(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        ttl_seconds=900,
    )


def _status(state_path: Path) -> dict[str, object]:
    return manager.status(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
    )


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
    assert manager.LOCK_PATH == consumer.DEFAULT_VEXP_MUTATION_PERMIT_LOCK_PATH
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

    permit_status = _status(state_path)
    assert permit_status["status"] == "valid"
    assert permit_status["permit_sha256"] == issued["permit_sha256"]
    assert manager.LOCK_PATH.stat().st_ino == lock_inode

    revoked = manager.revoke()
    assert revoked == {
        "status": "revoked",
        "permit_sha256": issued["permit_sha256"],
    }
    assert not manager.PERMIT_PATH.exists()
    assert manager.LOCK_PATH.is_file()


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


@pytest.mark.parametrize("operation", ["issue", "revoke"])
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
        else:
            manager.revoke()


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
    real_read = manager._read_state
    calls = 0

    def changing_read(path: Path, *, owner_uid: int) -> dict[str, object]:
        nonlocal calls
        calls += 1
        payload = real_read(path, owner_uid=owner_uid)
        if calls == 4:
            payload = dict(payload)
            if postwrite_change == "epoch":
                payload["epoch_started_at"] = "2026-07-13T09:43:56.205Z"
                payload["epoch_started_ms"] = 1783935836205
            else:
                payload["updated_at"] = _timestamp(
                    NOW - timedelta(minutes=5, milliseconds=1)
                )
        return payload

    monkeypatch.setattr(manager, "_read_state", changing_read)

    reason = "identity_changed" if postwrite_change == "epoch" else "updated_at_stale"
    with pytest.raises(manager.PermitError, match=reason):
        manager.issue(
            state_path=state_path,
            state_owner_uid=os.geteuid(),
            ttl_seconds=900,
        )

    assert calls == 4
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
    real_read = manager._read_state
    calls = 0

    def changing_read(path: Path, *, owner_uid: int) -> dict[str, object]:
        nonlocal calls
        calls += 1
        payload = real_read(path, owner_uid=owner_uid)
        if calls == 2:
            payload = dict(payload)
            payload["epoch_started_at"] = "2026-07-13T09:43:56.205Z"
            payload["epoch_started_ms"] = 1783935836205
        return payload

    monkeypatch.setattr(manager, "_read_state", changing_read)

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

    with pytest.raises(
        manager.PermitError, match="certificate_binding_mismatch"
    ):
        _status(state_path)
