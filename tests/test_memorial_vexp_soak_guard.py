from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Sequence
from unittest.mock import Mock

import pytest

from scripts import deploy_ea_memorial as deploy
from scripts.deploy_ea_memorial import DeployError, MemorialDeployLane


NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)


class TestVexpMemorialMutationAuthority(deploy.VexpMemorialMutationAuthority):
    __test__ = False

    def __init__(
        self,
        *,
        state_path: Path,
        permit_path: Path,
        lock_path: Path,
        permit_owner_uid: int,
        lock_owner_uid: int,
        utc_now: Callable[[], datetime],
    ) -> None:
        self._state_path = state_path
        self._permit_path = permit_path
        self._lock_path = lock_path
        self._permit_owner_uid = permit_owner_uid
        self._lock_owner_uid = lock_owner_uid
        self._utc_now = utc_now

    @property
    def sentinel_state_path(self) -> Path:
        return self._state_path

    @property
    def mutation_permit_path(self) -> Path:
        return self._permit_path

    @property
    def mutation_permit_owner_uid(self) -> int:
        return self._permit_owner_uid

    @property
    def mutation_permit_lock_path(self) -> Path:
        return self._lock_path

    @property
    def mutation_permit_lock_owner_uid(self) -> int:
        return self._lock_owner_uid

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
        "probes_passed": 42,
    }


def _permit(state: Mapping[str, object]) -> dict[str, object]:
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
        "issued_at": "2026-07-20T09:45:00.000Z",
        "expires_at": "2026-07-20T10:30:00.000Z",
        "mutation_boundaries": list(deploy.VEXP_MUTATION_BOUNDARIES),
    }


def _write_json(path: Path, payload: object, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(mode)


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
    lock_path: Path | None = None,
    permit_owner_uid: int | None = None,
    lock_owner_uid: int | None = None,
    utc_now: Callable[[], datetime] = lambda: NOW,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    create_lock: bool = True,
) -> tuple[MemorialDeployLane, NoCommandRunner, Path, Path]:
    root = tmp_path / "release"
    root.mkdir(exist_ok=True)
    runner = NoCommandRunner()
    resolved_state_path = state_path or tmp_path / "sentinel-state.json"
    resolved_permit_path = permit_path or tmp_path / "mutation-permit.json"
    resolved_lock_path = lock_path or tmp_path / "mutation-permit.lock"
    if create_lock:
        resolved_lock_path.touch()
        resolved_lock_path.chmod(0o644)
    lane = MemorialDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "guard-test-001"},
        runner=runner,
        monotonic=monotonic,
        sleep=sleep,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        durable_root_check=lambda _path: None,
    )
    lane._vexp_mutation_authority = TestVexpMemorialMutationAuthority(
        state_path=resolved_state_path,
        permit_path=resolved_permit_path,
        lock_path=resolved_lock_path,
        permit_owner_uid=(
            os.geteuid() if permit_owner_uid is None else permit_owner_uid
        ),
        lock_owner_uid=(os.geteuid() if lock_owner_uid is None else lock_owner_uid),
        utc_now=utc_now,
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
        "deployment_input_seal": {"seal_sha256": "4" * 64},
        "source_revision": "3" * 40,
        "public_origin": "https://myexternalbrain.com",
        "non_memorial_controls": {},
        "target_mounts": [],
    }


def _install_preflight(lane: MemorialDeployLane, tmp_path: Path) -> None:
    lane.preflight = Mock(return_value=_preflight_context(tmp_path))  # type: ignore[method-assign]
    lane._require_deployment_input_seal = Mock()  # type: ignore[method-assign]
    lane.bind_source_snapshot_sha256 = "5" * 64
    lane._revalidate_bind_source_access = Mock()  # type: ignore[method-assign]


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
) -> None:
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
    assert authority.mutation_permit_lock_path == Path(
        "/run/ea/memorial-vexp-mutation-permit.lock"
    )
    assert authority.mutation_permit_lock_owner_uid == 0
    assert authority.sentinel_state_path == (
        Path.home() / ".local" / "state" / "vexp-sentinel" / "state.json"
    )


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
    lane._ensure_redis.assert_not_called()
    assert not any(
        check.get("name") == "vexp_soak_mutation_guard" for check in receipt["checks"]
    )


def test_terminal_state_and_positive_permit_pass_all_three_mutation_boundaries(
    tmp_path: Path,
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_json(permit_path, _permit(state), mode=0o644)
    _install_preflight(lane, tmp_path)
    _install_postdeploy_success(lane)
    actions: list[str] = []
    lane._ensure_redis = Mock(  # type: ignore[method-assign]
        side_effect=lambda: actions.append("ensure_redis")
    )

    def protect(_previous: Mapping[str, object]) -> str:
        actions.append("protect_previous_image")
        return "ea-runtime:rollback-guard-test"

    lane._protect_previous_image = protect  # type: ignore[method-assign]
    lane._recreate_api = Mock(  # type: ignore[method-assign]
        side_effect=lambda: actions.append("recreate_api")
    )

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert actions == ["ensure_redis", "protect_previous_image", "recreate_api"]
    assert runner.commands == []
    guards = [
        check
        for check in receipt["checks"]
        if check.get("name") == "vexp_soak_mutation_guard"
    ]
    assert [guard["boundary"] for guard in guards] == list(
        deploy.VEXP_MUTATION_BOUNDARIES
    )
    assert {guard["status"] for guard in guards} == {"pass"}
    assert {guard["permit_status"] for guard in guards} == {"allow"}
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", str(guard["state_sha256"])) for guard in guards
    )
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", str(guard["permit_sha256"])) for guard in guards
    )


def test_shared_authorization_lease_is_held_across_each_exact_mutation(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_json(permit_path, _permit(state), mode=0o644)
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
        side_effect=lambda: require_shared_lease("ensure_redis")
    )

    def protect(_previous: Mapping[str, object]) -> str:
        require_shared_lease("protect_previous_image")
        return "ea-runtime:rollback-guard-test"

    lane._protect_previous_image = protect  # type: ignore[method-assign]
    lane._recreate_api = Mock(  # type: ignore[method-assign]
        side_effect=lambda: require_shared_lease("recreate_api")
    )

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert lease_observations == [
        "ensure_redis",
        "protect_previous_image",
        "recreate_api",
    ]
    descriptor = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def test_action_crossing_permit_expiry_is_not_accepted_as_complete(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    lane, _runner, state_path, permit_path = _lane(tmp_path, utc_now=lambda: clock[0])
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_json(permit_path, _permit(state), mode=0o644)
    _install_preflight(lane, tmp_path)
    actions: list[str] = []

    def ensure() -> None:
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
    _write_json(permit_path, _permit(state), mode=0o644)

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
    _write_json(permit_path, permit, mode=0o644)

    with lane._vexp_mutation_lease("before_ensure_redis"):
        assert lane._vexp_mutation_deadline == pytest.approx(2045.0)
        assert lane._remaining_vexp_mutation_seconds() == pytest.approx(45.0)


def test_nested_mutation_leases_are_rejected_and_outer_deadline_is_cleared(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_json(permit_path, _permit(state), mode=0o644)

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
    _write_json(permit_path, _permit(state), mode=0o644)

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
    _write_json(permit_path, permit, mode=0o644)

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
    _write_json(permit_path, _permit(state), mode=0o644)
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
    _write_json(permit_path, permit, mode=0o644)
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
    _write_json(permit_path, _permit(state), mode=0o644)
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
    _write_json(permit_path, _permit(state), mode=0o644)
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
    _write_json(permit_path, _permit(state), mode=0o644)
    _install_preflight(lane, tmp_path)
    lane._ensure_redis = Mock()  # type: ignore[method-assign]
    lane._protect_previous_image = Mock(  # type: ignore[method-assign]
        return_value="ea-runtime:rollback-guard-test"
    )
    observed_before_recreate: dict[str, object] = {}

    def fail_recreate() -> None:
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
    ]
    assert observed_before_recreate["completed_actions"] == [
        "ensure_redis",
        "protect_previous_image",
    ]
    lane._rollback.assert_called_once()
    receipt = _receipt(lane)
    assert receipt["status"] == "failed_rolled_back"
    assert receipt["preparation"]["api_mutation_started"] is True
    assert receipt["preparation"]["api_runtime_state"] == "restored_by_rollback"


@pytest.mark.parametrize("remove_after", ["ensure_redis", "protect_previous_image"])
def test_permit_is_re_read_at_each_boundary_before_api_mutation(
    tmp_path: Path, remove_after: str
) -> None:
    lane, runner, state_path, permit_path = _lane(tmp_path)
    state = _state(terminal=True)
    _write_json(state_path, state, mode=0o600)
    _write_json(permit_path, _permit(state), mode=0o644)
    _install_preflight(lane, tmp_path)
    actions: list[str] = []

    def ensure() -> None:
        actions.append("ensure_redis")
        if remove_after == "ensure_redis":
            permit_path.unlink()

    def protect(_previous: Mapping[str, object]) -> str:
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
    assert receipt["status"] == "failed_after_preparation"
    assert receipt["preparation"] == {
        "status": "failed_before_api_mutation",
        "attempted_actions": expected,
        "completed_actions": expected,
        "pending_action": (
            "protect_previous_image"
            if remove_after == "ensure_redis"
            else "recreate_api"
        ),
        "active_action": None,
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
    _write_json(permit_path, _permit(initial), mode=0o644)
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


def test_mutable_metrics_change_during_validation_passes_and_records_final_state(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    initial = _state(terminal=True)
    changed = {
        **initial,
        "updated_at": "2026-07-20T10:00:15.000Z",
        "probes_passed": 99,
    }
    _write_json(state_path, initial, mode=0o600)
    _write_json(permit_path, _permit(initial), mode=0o644)
    real_read_permit = lane._read_trusted_vexp_mutation_permit

    def read_permit_then_update_metrics() -> tuple[dict[str, object], str]:
        permit = real_read_permit()
        _write_json(state_path, changed, mode=0o600)
        return permit

    lane._read_trusted_vexp_mutation_permit = (  # type: ignore[method-assign]
        read_permit_then_update_metrics
    )

    with lane._vexp_mutation_lease("before_ensure_redis"):
        pass

    guard = _receipt(lane)["checks"][-1]
    assert guard["status"] == "pass"
    assert guard["state_sha256"] == hashlib.sha256(state_path.read_bytes()).hexdigest()
    assert guard["terminal_identity_sha256"] == (
        deploy._vexp_terminal_identity_sha256(initial)
    )


def test_mutable_sentinel_updates_do_not_invalidate_terminal_permit(
    tmp_path: Path,
) -> None:
    lane, _runner, state_path, permit_path = _lane(tmp_path)
    first = _state(terminal=True)
    _write_json(state_path, first, mode=0o600)
    _write_json(permit_path, _permit(first), mode=0o644)

    lane._require_vexp_mutation_permitted("before_ensure_redis")
    second = {
        **first,
        "updated_at": "2026-07-20T10:00:15.000Z",
        "probes_passed": 99,
    }
    _write_json(state_path, second, mode=0o600)
    lane._require_vexp_mutation_permitted("before_protect_previous_image")

    guards = _receipt(lane)["checks"]
    assert len(guards) == 2
    assert {guard["status"] for guard in guards} == {"pass"}
    assert guards[0]["state_sha256"] != guards[1]["state_sha256"]
    assert (
        guards[0]["terminal_identity_sha256"] == (guards[1]["terminal_identity_sha256"])
    )


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
    _write_json(permit_path, permit, mode=0o644)

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
    _write_json(permit_path, _permit(initial), mode=0o644)
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

    with pytest.raises(DeployError, match="vexp_mutation_permit_unavailable"):
        lane._require_vexp_mutation_permitted("before_ensure_redis")

    assert runner.commands == []
    assert _receipt(lane)["checks"][-1]["status"] == "fail"


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
    if untrusted_kind == "mode":
        _write_json(permit_path, _permit(state), mode=0o664)
    elif untrusted_kind == "symlink":
        target = tmp_path / "real-permit.json"
        _write_json(target, _permit(state), mode=0o644)
        permit_path.symlink_to(target)
    else:
        target = tmp_path / "linked-permit.json"
        _write_json(target, _permit(state), mode=0o644)
        os.link(target, permit_path)
    lane, _runner, _state_path, _permit_path = _lane(tmp_path, permit_path=permit_path)

    with pytest.raises(DeployError):
        lane._read_trusted_vexp_mutation_permit()


def test_permit_root_owner_requirement_is_injectable_without_root(
    tmp_path: Path,
) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(
        tmp_path, permit_owner_uid=os.geteuid() + 1
    )
    _write_json(permit_path, _permit(state), mode=0o644)

    with pytest.raises(DeployError, match="vexp_mutation_permit_untrusted"):
        lane._read_trusted_vexp_mutation_permit()


def test_exact_0644_permit_with_injected_owner_is_accepted(tmp_path: Path) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    _write_json(permit_path, _permit(state), mode=0o644)

    payload, digest = lane._read_trusted_vexp_mutation_permit()

    assert payload["status"] == "allow"
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_permit_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    lane, _runner, _state_path, permit_path = _lane(tmp_path)

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
    _write_json(permit_path, _permit(state), mode=0o644)
    monkeypatch.delattr(deploy.os, flag)

    with pytest.raises(DeployError, match=f"vexp_mutation_permit_{reason}"):
        lane._read_trusted_vexp_mutation_permit()


def test_permit_atomic_read_rejects_path_identity_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(terminal=True)
    lane, _runner, _state_path, permit_path = _lane(tmp_path)
    _write_json(permit_path, _permit(state), mode=0o644)
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

    with pytest.raises(DeployError, match="vexp_mutation_permit_changed_during_read"):
        lane._read_trusted_vexp_mutation_permit()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"contract_name": "wrong"}, "contract_invalid"),
        ({"version": 2}, "version_invalid"),
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
    _write_json(permit_path, payload, mode=0o644)

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
        _write_json(permit_path, payload, mode=0o644)
    elif schema_change == "extra":
        payload["unexpected"] = True
        _write_json(permit_path, payload, mode=0o644)
    else:
        raw = json.dumps(payload).replace(
            '"contract_name":',
            '"contract_name":"duplicate","contract_name":',
            1,
        )
        permit_path.write_text(raw + "\n", encoding="utf-8")
        permit_path.chmod(0o644)

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
