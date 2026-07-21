from __future__ import annotations

import os
import pwd
import subprocess
from types import SimpleNamespace
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import Mock

import pytest

from scripts import deploy_ea_memorial as deploy
from scripts import deploy_ea_memorial_joint as joint
from scripts import ea_memorial_recovery_interlock as interlock


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


def _journal_path(tmp_path: Path) -> Path:
    return (
        tmp_path
        / interlock.NORMALIZATION_RECOVERY_STATE_DIRECTORY
        / interlock.NORMALIZATION_RECOVERY_JOURNAL_FILENAME
    )


def _private_state_directory(path: Path) -> None:
    path.parent.mkdir(mode=0o700)
    path.parent.chmod(0o700)


def _release_root(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    env_file = root / ".env"
    env_file.write_text("# test only\n", encoding="utf-8")
    env_file.chmod(0o600)
    return root


def test_interlock_accepts_only_proven_absence(tmp_path: Path) -> None:
    journal = _journal_path(tmp_path)

    interlock.require_normalization_recovery_absent(journal)
    _private_state_directory(journal)
    interlock.require_normalization_recovery_absent(journal)


def test_default_journal_uses_release_owner_account_not_home_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _release_root(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "attacker-selected-home"))

    selected = interlock.default_normalization_recovery_journal_path(
        operator_anchor=root
    )

    assert selected.parent.parent == Path(pwd.getpwuid(os.geteuid()).pw_dir)
    assert str(tmp_path / "attacker-selected-home") not in str(selected)


def test_default_journal_rejects_group_or_world_writable_account_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _release_root(tmp_path)
    unsafe_home = tmp_path / "unsafe-home"
    unsafe_home.mkdir()
    unsafe_home.chmod(0o777)
    monkeypatch.setattr(
        interlock.pwd,
        "getpwuid",
        lambda _uid: SimpleNamespace(pw_dir=str(unsafe_home)),
    )

    with pytest.raises(
        interlock.MemorialRecoveryInterlockError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        interlock.default_normalization_recovery_journal_path(
            operator_anchor=root
        )


def test_interlock_revalidates_account_home_mode_at_use_boundary(
    tmp_path: Path,
) -> None:
    account_home = tmp_path / "account-home"
    account_home.mkdir(mode=0o700)
    account_home.chmod(0o700)
    journal = (
        account_home
        / interlock.NORMALIZATION_RECOVERY_STATE_DIRECTORY
        / interlock.NORMALIZATION_RECOVERY_JOURNAL_FILENAME
    )
    interlock.require_normalization_recovery_absent(journal)

    account_home.chmod(0o777)

    with pytest.raises(
        interlock.MemorialRecoveryInterlockError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        interlock.require_normalization_recovery_absent(journal)


@pytest.mark.parametrize(
    "path",
    (
        None,
        Path(interlock.NORMALIZATION_RECOVERY_JOURNAL_FILENAME),
        Path("/") / interlock.NORMALIZATION_RECOVERY_JOURNAL_FILENAME,
    ),
)
def test_interlock_malformed_paths_fail_with_domain_error(
    path: Path | None,
) -> None:
    with pytest.raises(
        interlock.MemorialRecoveryInterlockError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        interlock.require_normalization_recovery_absent(path)


def test_missing_ancestor_is_revalidated_before_accepting_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal_path(tmp_path)
    real_revalidate = interlock._revalidate_absence_from_root
    injected = False

    def inject_before_revalidation(**kwargs: object) -> None:
        nonlocal injected
        if not injected:
            injected = True
            _private_state_directory(journal)
            journal.write_bytes(b"raced-recovery\n")
            journal.chmod(0o600)
        real_revalidate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        interlock,
        "_revalidate_absence_from_root",
        inject_before_revalidation,
    )

    with pytest.raises(
        interlock.MemorialRecoveryInterlockError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        interlock.require_normalization_recovery_absent(journal)

    assert injected is True
    assert journal.read_bytes() == b"raced-recovery\n"


@pytest.mark.parametrize("entry_kind", ("regular", "symlink", "fifo", "hardlink"))
def test_interlock_blocks_every_present_entry_without_changing_it(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    journal = _journal_path(tmp_path)
    _private_state_directory(journal)
    victim = tmp_path / "victim"
    victim.write_bytes(b"owned-recovery-state\n")
    if entry_kind == "regular":
        journal.write_bytes(b"active-recovery\n")
    elif entry_kind == "symlink":
        journal.symlink_to(victim)
    elif entry_kind == "fifo":
        os.mkfifo(journal, 0o600)
    else:
        os.link(victim, journal)
    before_victim = victim.read_bytes()
    before_entry = journal.lstat()

    with pytest.raises(
        interlock.MemorialRecoveryInterlockError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        interlock.require_normalization_recovery_absent(journal)

    after_entry = journal.lstat()
    assert (after_entry.st_dev, after_entry.st_ino, after_entry.st_mode) == (
        before_entry.st_dev,
        before_entry.st_ino,
        before_entry.st_mode,
    )
    assert victim.read_bytes() == before_victim
    if entry_kind == "regular":
        assert journal.read_bytes() == b"active-recovery\n"


@pytest.mark.parametrize("attack", ("public_parent", "symlink_parent"))
def test_interlock_blocks_indeterminate_state_directory(
    tmp_path: Path,
    attack: str,
) -> None:
    journal = _journal_path(tmp_path)
    if attack == "public_parent":
        _private_state_directory(journal)
        journal.parent.chmod(0o755)
    else:
        target = tmp_path / "target-state"
        target.mkdir(mode=0o700)
        journal.parent.symlink_to(target, target_is_directory=True)

    with pytest.raises(
        interlock.MemorialRecoveryInterlockError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        interlock.require_normalization_recovery_absent(journal)


def test_scoped_api_deploy_blocks_active_normalization_before_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal_path(tmp_path)
    _private_state_directory(journal)
    journal.write_bytes(b"do-not-consume\n")
    journal.chmod(0o600)
    root = _release_root(tmp_path)
    monkeypatch.setattr(
        deploy,
        "default_normalization_recovery_journal_path",
        lambda *, operator_anchor: journal,
    )
    runner = NoCommandRunner()
    lane = deploy.MemorialDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "normalization-interlock-api-001"},
        runner=runner,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        durable_root_check=lambda _path: None,
    )
    lane.preflight = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("preflight must remain blocked")
    )

    with pytest.raises(
        deploy.DeployError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        lane.deploy(preflight_only=True)

    lane.preflight.assert_not_called()
    assert runner.commands == []
    assert journal.read_bytes() == b"do-not-consume\n"


def test_joint_deploy_blocks_active_normalization_before_its_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal_path(tmp_path)
    _private_state_directory(journal)
    journal.write_bytes(b"do-not-consume\n")
    journal.chmod(0o600)
    root = _release_root(tmp_path)
    monkeypatch.setattr(
        deploy,
        "default_normalization_recovery_journal_path",
        lambda *, operator_anchor: journal,
    )
    runner = NoCommandRunner()
    lane = joint.JointMemorialIngressDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "normalization-interlock-joint-001"},
        runner=runner,
        receipt_dir=tmp_path / "joint-receipts",
        ingress_receipt_dir=tmp_path / "ingress-receipts",
        global_lock_path=tmp_path / "global.lock",
        recovery_journal_path=(
            tmp_path / "joint-state" / joint.JOINT_RECOVERY_JOURNAL_FILENAME
        ),
        durable_root_check=lambda _path: None,
    )
    lane._recover_interrupted_transaction = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("joint recovery must remain blocked")
    )
    lane.preflight = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("preflight must remain blocked")
    )

    with pytest.raises(
        deploy.DeployError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        lane.deploy(preflight_only=True)

    lane._recover_interrupted_transaction.assert_not_called()
    lane.preflight.assert_not_called()
    assert runner.commands == []
    assert journal.read_bytes() == b"do-not-consume\n"
