from __future__ import annotations

import fcntl
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import manfred_candidate_vexp_authority as candidate_authority


NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)


def _status_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "valid",
        "contract_name": (
            candidate_authority.CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME
        ),
        "epoch_started_ms": 1783935836206,
        "qualified_at": "2026-07-20T09:43:56.206Z",
        "issued_at": "2026-07-20T09:45:00.000Z",
        "expires_at": "2026-07-20T10:15:00.000Z",
        "terminal_identity_sha256": "1" * 64,
        "qualification_certificate_schema": (
            candidate_authority.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
        ),
        "qualification_certificate_sha256": "2" * 64,
        "qualification_certificate_identity": f"sha256:{'3' * 64}",
        "qualification_certificate_event_hash": "4" * 64,
        "permit_sha256": "5" * 64,
        "permit_commit": {
            "contract_name": candidate_authority.PERMIT_COMMIT_CONTRACT_NAME,
            "version": candidate_authority.PERMIT_COMMIT_VERSION,
            "status": "committed",
            "sha256": "6" * 64,
        },
        "epoch_void_ledger": {
            "root": str(candidate_authority.EPOCH_VOID_LEDGER_ROOT),
            "entry": str(
                candidate_authority.EPOCH_VOID_LEDGER_ROOT
                / "1783935836206.json"
            ),
            "entry_present": False,
            "root_trusted": True,
        },
        "current_predicate": {
            "contract_name": candidate_authority.CURRENT_PREDICATE_CONTRACT_NAME,
            "version": candidate_authority.CURRENT_PREDICATE_VERSION,
            "status": "positive",
            "epoch_started_ms": 1783935836206,
            "generation": 7,
            "record_sha256": "7" * 64,
            "boot_id": "12345678-1234-4234-9234-123456789abc",
            "monotonic_ns": 10_000_000_000,
            "sentinel_producer_sha256": "8" * 64,
            "root_predicate_producer_sha256": "9" * 64,
        },
        "candidate_evidence": {
            "attestor_sha256": "a" * 64,
            "producer_manifest_sha256": "b" * 64,
        },
        "mutation_boundaries": list(
            candidate_authority.CANDIDATE_VEXP_MUTATION_BOUNDARIES
        ),
    }
    payload.update(changes)
    return payload


def _completed(
    payload: dict[str, object] | None = None,
    *,
    returncode: int = 0,
) -> subprocess.CompletedProcess[bytes]:
    stdout = b""
    stderr = b"permit_error:denied\n" if returncode else b""
    if payload is not None:
        stdout = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    return subprocess.CompletedProcess(
        args=["manager", "status"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _authority(
    tmp_path: Path,
    *,
    invoker: candidate_authority.StatusInvoker | None = None,
    monotonic: object | None = None,
) -> tuple[candidate_authority.CandidateVexpMutationAuthority, Path]:
    tmp_path.chmod(0o755)
    lock_path = tmp_path / "permit.lock"
    lock_path.touch(mode=candidate_authority.LOCK_MODE)
    lock_path.chmod(candidate_authority.LOCK_MODE)
    state_path = tmp_path / "state.json"
    authority = candidate_authority.CandidateVexpMutationAuthority(
        state_path=state_path,
        state_owner_uid=os.geteuid(),
        lock_path=lock_path,
        lock_owner_uid=os.geteuid(),
        lock_owner_gid=os.getegid(),
        authority_trusted_parent=tmp_path,
        authority_directory_owner_uid=os.geteuid(),
        authority_directory_owner_gid=os.getegid(),
        manager_path=Path("/trusted/manager"),
        python_path=Path("/trusted/python3"),
        utc_now=lambda: NOW,
        monotonic=(monotonic if callable(monotonic) else lambda: 100.0),
        status_invoker=invoker or (lambda _argv, _env: _completed(_status_payload())),
    )
    return authority, lock_path


def test_current_candidate_authority_is_reported_without_secrets(
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def invoke(
        argv: object,
        environment: object,
    ) -> subprocess.CompletedProcess[bytes]:
        observed["argv"] = argv
        observed["environment"] = environment
        return _completed(_status_payload())

    authority, _lock_path = _authority(tmp_path, invoker=invoke)

    evidence = authority.require_current()

    assert evidence["status"] == "pass"
    assert evidence["boundary"] == "candidate_entry"
    assert evidence["contract_name"] == (
        candidate_authority.CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME
    )
    assert evidence["permit_commit"]["status"] == "committed"
    assert evidence["epoch_void_ledger"]["entry_present"] is False
    assert "--permit-mode" in observed["argv"]
    assert observed["argv"][-1] == candidate_authority.CANDIDATE_PERMIT_MODE
    assert observed["environment"] == {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    }


def test_mutation_holds_shared_coordination_lock(tmp_path: Path) -> None:
    authority, lock_path = _authority(tmp_path)

    with authority.mutation(
        "before_candidate_up",
        minimum_validity_seconds=60,
    ) as lease:
        assert lease.command_timeout(30) == 30
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)


@pytest.mark.parametrize(
    "stderr",
    [
        b"permit_error:vexp_sentinel_state_not_terminal\n",
        b"permit_error:vexp_mutation_permit_unavailable\n",
        b"permit_error:vexp_mutation_permit_not_current\n",
        b"permit_error:vexp_mutation_permit_contract_invalid\n",
    ],
)
def test_manager_denial_fails_closed(tmp_path: Path, stderr: bytes) -> None:
    def deny(
        _argv: object,
        _environment: object,
    ) -> subprocess.CompletedProcess[bytes]:
        result = _completed(returncode=2)
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=stderr,
        )

    authority, _lock_path = _authority(tmp_path, invoker=deny)

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="authority_denied",
    ):
        authority.require_current()


def test_expired_permit_fails_closed(tmp_path: Path) -> None:
    authority, _lock_path = _authority(
        tmp_path,
        invoker=lambda _argv, _env: _completed(
            _status_payload(expires_at="2026-07-20T10:00:00.000Z")
        ),
    )

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="authority_not_current",
    ):
        authority.require_current()


def test_authority_change_after_action_fails_closed(tmp_path: Path) -> None:
    calls = 0

    def changing(
        _argv: object,
        _environment: object,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return _completed(
            _status_payload(permit_sha256=("5" if calls == 1 else "6") * 64)
        )

    authority, _lock_path = _authority(tmp_path, invoker=changing)

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="authority_changed",
    ):
        with authority.mutation(
            "before_candidate_restart",
            minimum_validity_seconds=60,
        ):
            pass


def test_lock_replacement_after_action_fails_closed(tmp_path: Path) -> None:
    authority, lock_path = _authority(tmp_path)

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="lock_changed",
    ):
        with authority.mutation(
            "before_candidate_image_build",
            minimum_validity_seconds=60,
        ):
            lock_path.unlink()
            lock_path.touch(mode=candidate_authority.LOCK_MODE)
            lock_path.chmod(candidate_authority.LOCK_MODE)


def test_lock_replacement_after_failed_action_still_fails_closed(
    tmp_path: Path,
) -> None:
    authority, lock_path = _authority(tmp_path)

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="lock_changed",
    ) as raised:
        with authority.mutation(
            "before_candidate_image_build",
            minimum_validity_seconds=60,
        ):
            lock_path.unlink()
            lock_path.touch(mode=candidate_authority.LOCK_MODE)
            lock_path.chmod(candidate_authority.LOCK_MODE)
            raise RuntimeError("candidate_build_failed")

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "candidate_build_failed"


def test_authority_change_after_failed_action_still_fails_closed(
    tmp_path: Path,
) -> None:
    calls = 0

    def changing(
        _argv: object,
        _environment: object,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return _completed(
            _status_payload(permit_sha256=("5" if calls == 1 else "6") * 64)
        )

    authority, _lock_path = _authority(tmp_path, invoker=changing)

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="authority_changed",
    ) as raised:
        with authority.mutation(
            "before_candidate_restart",
            minimum_validity_seconds=60,
        ):
            raise RuntimeError("candidate_restart_failed")

    assert calls == 2
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "candidate_restart_failed"


def test_expired_deadline_after_failed_action_still_fails_closed(
    tmp_path: Path,
) -> None:
    monotonic_values = iter((100.0, 999.0))
    authority, _lock_path = _authority(
        tmp_path,
        monotonic=lambda: next(monotonic_values),
    )

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="action_authority_expired",
    ) as raised:
        with authority.mutation(
            "before_candidate_up",
            minimum_validity_seconds=60,
        ):
            raise RuntimeError("candidate_up_failed")

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "candidate_up_failed"


def test_invalid_boundary_never_invokes_manager(tmp_path: Path) -> None:
    calls = 0

    def invoke(
        _argv: object,
        _environment: object,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return _completed(_status_payload())

    authority, _lock_path = _authority(tmp_path, invoker=invoke)

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="boundary_invalid",
    ):
        with authority.mutation("before_api_up", minimum_validity_seconds=60):
            pass

    assert calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"permit_commit": {"status": "committed"}},
        {
            "permit_commit": {
                "contract_name": candidate_authority.PERMIT_COMMIT_CONTRACT_NAME,
                "version": candidate_authority.PERMIT_COMMIT_VERSION,
                "status": "prepared",
                "sha256": "6" * 64,
            }
        },
        {
            "epoch_void_ledger": {
                "root": str(candidate_authority.EPOCH_VOID_LEDGER_ROOT),
                "entry": str(
                    candidate_authority.EPOCH_VOID_LEDGER_ROOT
                    / "1783935836206.json"
                ),
                "entry_present": True,
                "root_trusted": True,
            }
        },
        {
            "epoch_void_ledger": {
                "root": str(candidate_authority.EPOCH_VOID_LEDGER_ROOT),
                "entry": str(
                    candidate_authority.EPOCH_VOID_LEDGER_ROOT
                    / "1783935836205.json"
                ),
                "entry_present": False,
                "root_trusted": True,
            }
        },
    ],
)
def test_commit_and_void_ledger_status_tampering_fails_closed(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    authority, _lock_path = _authority(
        tmp_path,
        invoker=lambda _argv, _env: _completed(_status_payload(**changes)),
    )

    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="status_invalid",
    ):
        authority.require_current()


def test_production_factory_accepts_only_canonical_live_state() -> None:
    authority = candidate_authority.candidate_vexp_authority(
        state_path=candidate_authority.DEFAULT_SENTINEL_STATE_PATH,
        state_owner_uid=os.geteuid(),
    )

    assert authority.state_path == candidate_authority.DEFAULT_SENTINEL_STATE_PATH
    assert authority.state_owner_uid == os.geteuid()


def test_production_factory_rejects_operator_selected_state_snapshot(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        candidate_authority.CandidateAuthorityError,
        match="canonical_state_required",
    ):
        candidate_authority.candidate_vexp_authority(
            state_path=tmp_path / "copied-terminal-state.json",
            state_owner_uid=os.geteuid(),
        )
