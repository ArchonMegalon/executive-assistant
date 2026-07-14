from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from scripts import deploy_ea_memorial as deploy


LIVE_EPOCH_MS = 1_783_991_012_617
LIVE_EXPIRATION_MS = 1_784_520_839_000
LIVE_CHECKED_AT_MS = 1_783_996_805_000
DO_NOT_LEAK = "vexp-token-material-must-not-appear"


def _timestamp(milliseconds: int) -> str:
    return deploy._utc_timestamp_from_ms(milliseconds)


def _state(
    *,
    epoch_ms: int,
    initial_expiration_ms: int,
    observed_expiration_ms: int,
    checked_at_ms: int,
    renewal_count: int,
    renewed_in_epoch: bool,
    phase: str = "enforced_soak",
) -> dict[str, object]:
    required_end_ms = epoch_ms + deploy.VEXP_CERTIFICATION_SOAK_SECONDS * 1000
    return {
        "version": deploy.VEXP_SENTINEL_STATE_VERSION,
        "updated_at": _timestamp(checked_at_ms),
        "epoch_started_at": _timestamp(epoch_ms),
        "epoch_started_ms": epoch_ms,
        "epoch_initial_fresh_exp_ms": initial_expiration_ms,
        "last_observed_fresh_exp_ms": observed_expiration_ms,
        "fresh_token_renewals": renewal_count,
        "fresh_token_renewed_in_epoch": renewed_in_epoch,
        "last_license": {
            "renewed": renewed_in_epoch,
            "fresh_expiration_ms": observed_expiration_ms,
            "fresh_expiration_at": _timestamp(observed_expiration_ms),
        },
        "qualification_phase": phase,
        "qualified_at": (
            _timestamp(required_end_ms) if phase == "qualified" else None
        ),
        "certification_blockers": (
            []
            if renewed_in_epoch
            else ["license:fresh_token_not_renewed"]
        ),
        # Deliberately ignored input proves receipts are projections, not copies.
        "fresh_token": DO_NOT_LEAK,
    }


def _live_insufficient_state() -> dict[str, object]:
    state = _state(
        epoch_ms=LIVE_EPOCH_MS,
        initial_expiration_ms=LIVE_EXPIRATION_MS,
        observed_expiration_ms=LIVE_EXPIRATION_MS,
        checked_at_ms=LIVE_CHECKED_AT_MS,
        renewal_count=0,
        renewed_in_epoch=False,
    )
    state["certification_blockers"] = [
        "daemon:swap_pressure_pending",
        "host_codex:swap_pressure_pending",
        "license:fresh_token_not_renewed",
    ]
    return state


def _current_live_insufficient_state() -> dict[str, object]:
    state = _live_insufficient_state()
    state["updated_at"] = _timestamp(int(time.time() * 1000))
    return state


def _write_state(path: Path, state: Mapping[str, object], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(mode)


class NoCommandRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        self.calls.append(list(args))
        raise AssertionError("token coverage must fail before any command")


def test_live_token_expiry_fails_exact_certification_coverage() -> None:
    evidence = deploy._vexp_certification_token_coverage(
        _live_insufficient_state(),
        state_sha256="a" * 64,
        checked_at_ms=LIVE_CHECKED_AT_MS,
        state_file_mtime_ns=LIVE_CHECKED_AT_MS * 1_000_000,
    )

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "fresh_token_coverage_insufficient"
    assert evidence["certification_required_end_at"] == "2026-07-21T01:03:32.617Z"
    assert evidence["fresh_token_expiration_at"] == "2026-07-20T04:13:59.000Z"
    assert evidence["coverage_shortfall_seconds"] == 74_973.617
    assert evidence["fresh_token_renewal_observed"] is False
    assert evidence["promotion_authorized"] is False
    assert evidence["credential_material_included"] is False
    assert evidence["secrets_included"] is False
    assert not any(
        "Restore" in instruction for instruction in evidence["operator_guidance"]
    )
    assert DO_NOT_LEAK not in json.dumps(evidence, sort_keys=True)


def test_coverage_pass_requires_renewal_and_full_window() -> None:
    checked_at_ms = 1_800_000_000_000
    epoch_ms = checked_at_ms - 24 * 60 * 60 * 1000
    initial_expiration_ms = checked_at_ms + 2 * 24 * 60 * 60 * 1000
    observed_expiration_ms = epoch_ms + 8 * 24 * 60 * 60 * 1000
    evidence = deploy._vexp_certification_token_coverage(
        _state(
            epoch_ms=epoch_ms,
            initial_expiration_ms=initial_expiration_ms,
            observed_expiration_ms=observed_expiration_ms,
            checked_at_ms=checked_at_ms,
            renewal_count=1,
            renewed_in_epoch=True,
        ),
        state_sha256="b" * 64,
        checked_at_ms=checked_at_ms,
        state_file_mtime_ns=checked_at_ms * 1_000_000,
    )

    assert evidence["status"] == "pass"
    assert evidence["token_coverage_safe"] is True
    assert evidence["coverage_margin_seconds"] == 86_400
    assert evidence["coverage_shortfall_seconds"] == 0
    assert evidence["fresh_token_renewal_observed"] is True
    assert evidence["qualification_phase"] == "enforced_soak"
    assert evidence["promotion_authorized"] is False
    assert evidence["operator_action_required"] is False
    assert DO_NOT_LEAK not in json.dumps(evidence, sort_keys=True)


def test_stale_qualified_snapshot_cannot_pass_with_future_expiry() -> None:
    checked_at_ms = 1_800_000_000_000
    epoch_ms = checked_at_ms - 8 * 24 * 60 * 60 * 1000
    state = _state(
        epoch_ms=epoch_ms,
        initial_expiration_ms=epoch_ms + 2 * 24 * 60 * 60 * 1000,
        observed_expiration_ms=checked_at_ms + 30 * 24 * 60 * 60 * 1000,
        checked_at_ms=epoch_ms + deploy.VEXP_CERTIFICATION_SOAK_SECONDS * 1000,
        renewal_count=1,
        renewed_in_epoch=True,
        phase="qualified",
    )

    evidence = deploy._vexp_certification_token_coverage(
        state,
        state_sha256="f" * 64,
        checked_at_ms=checked_at_ms,
        state_file_mtime_ns=checked_at_ms * 1_000_000,
    )

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_state_invalid"
    assert "sentinel_state_stale" in evidence["issues"]
    assert evidence["token_coverage_safe"] is False


def test_license_blocker_prevents_token_coverage_pass() -> None:
    checked_at_ms = 1_800_000_000_000
    epoch_ms = checked_at_ms - 24 * 60 * 60 * 1000
    state = _state(
        epoch_ms=epoch_ms,
        initial_expiration_ms=checked_at_ms + 2 * 24 * 60 * 60 * 1000,
        observed_expiration_ms=epoch_ms + 8 * 24 * 60 * 60 * 1000,
        checked_at_ms=checked_at_ms,
        renewal_count=1,
        renewed_in_epoch=True,
    )
    state["certification_blockers"] = ["license:provider_check_pending"]

    evidence = deploy._vexp_certification_token_coverage(
        state,
        state_sha256="d" * 64,
        checked_at_ms=checked_at_ms,
        state_file_mtime_ns=checked_at_ms * 1_000_000,
    )

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "license_certification_blocked"
    assert "license_certification_blocker_present" in evidence["issues"]
    assert evidence["token_coverage_safe"] is False
    assert evidence["promotion_authorized"] is False
    assert evidence["certification_blockers"] == []
    assert evidence["unprojected_certification_blocker_count"] == 1
    assert "provider_check_pending" not in json.dumps(evidence, sort_keys=True)


def test_renewed_state_rejects_not_renewed_blocker_as_inconsistent() -> None:
    checked_at_ms = 1_800_000_000_000
    epoch_ms = checked_at_ms - 24 * 60 * 60 * 1000
    state = _state(
        epoch_ms=epoch_ms,
        initial_expiration_ms=checked_at_ms + 2 * 24 * 60 * 60 * 1000,
        observed_expiration_ms=epoch_ms + 8 * 24 * 60 * 60 * 1000,
        checked_at_ms=checked_at_ms,
        renewal_count=1,
        renewed_in_epoch=True,
    )
    state["certification_blockers"] = ["license:fresh_token_not_renewed"]

    evidence = deploy._vexp_certification_token_coverage(
        state,
        state_sha256="e" * 64,
        checked_at_ms=checked_at_ms,
        state_file_mtime_ns=checked_at_ms * 1_000_000,
    )

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_state_invalid"
    assert "license_renewal_blocker_state_inconsistent" in evidence["issues"]


@pytest.mark.parametrize(
    ("mutation", "expected_issue"),
    [
        (
            lambda state: state["last_license"].__setitem__(  # type: ignore[union-attr]
                "fresh_expiration_ms", LIVE_EXPIRATION_MS + 1
            ),
            "last_license_fresh_expiration_mismatch",
        ),
        (
            lambda state: state.__setitem__("fresh_token_renewed_in_epoch", True),
            "fresh_token_renewal_state_inconsistent",
        ),
        (
            lambda state: state.__setitem__("qualification_phase", []),
            "qualification_phase_invalid",
        ),
    ],
)
def test_inconsistent_sentinel_metadata_fails_closed(
    mutation,  # type: ignore[no-untyped-def]
    expected_issue: str,
) -> None:
    state = _live_insufficient_state()
    mutation(state)
    evidence = deploy._vexp_certification_token_coverage(
        state,
        state_sha256="c" * 64,
        checked_at_ms=LIVE_CHECKED_AT_MS,
        state_file_mtime_ns=LIVE_CHECKED_AT_MS * 1_000_000,
    )

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_state_invalid"
    assert expected_issue in evidence["issues"]
    assert "fresh_token_expiration_at" not in evidence
    assert DO_NOT_LEAK not in json.dumps(evidence, sort_keys=True)


def test_trusted_reader_rejects_loose_mode_and_symlink(tmp_path: Path) -> None:
    loose = tmp_path / "loose.json"
    _write_state(loose, _live_insufficient_state(), mode=0o644)
    with pytest.raises(
        deploy.DeployError, match="^vexp_sentinel_state_file_untrusted$"
    ):
        deploy._read_trusted_vexp_sentinel_state(loose)

    target = tmp_path / "target.json"
    _write_state(target, _live_insufficient_state())
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(deploy.DeployError, match="^vexp_sentinel_state_unavailable$"):
        deploy._read_trusted_vexp_sentinel_state(linked)

    unsafe_parent = tmp_path / "unsafe-parent"
    unsafe_parent.mkdir(mode=0o755)
    unsafe_parent.chmod(0o755)
    unsafe = unsafe_parent / "state.json"
    unsafe.write_text(
        json.dumps(_live_insufficient_state()) + "\n", encoding="utf-8"
    )
    unsafe.chmod(0o600)
    with pytest.raises(
        deploy.DeployError, match="^vexp_sentinel_state_parent_untrusted$"
    ):
        deploy._read_trusted_vexp_sentinel_state(unsafe)


def test_gate_persists_secret_free_operator_receipt(tmp_path: Path) -> None:
    sentinel = tmp_path / "state.json"
    _write_state(sentinel, _current_live_insufficient_state())
    receipt_dir = tmp_path / "receipts"
    lane = deploy.MemorialDeployLane(
        root=tmp_path,
        env={"EA_DEPLOYMENT_ID": "memorial-token-test"},
        runner=NoCommandRunner(),
        receipt_dir=receipt_dir,
        global_lock_path=tmp_path / "global.lock",
        vexp_sentinel_state_path=sentinel,
        durable_root_check=lambda _root: None,
    )

    with pytest.raises(
        deploy.DeployError,
        match="^vexp_certification_token_coverage_insufficient$",
    ):
        lane._require_vexp_certification_token_coverage("preflight_entry")

    receipt = lane.receipt_path.read_text(encoding="utf-8")
    payload = json.loads(receipt)
    assert DO_NOT_LEAK not in receipt
    assert payload["vexp_certification_token_coverage"]["status"] == "fail"
    assert payload["vexp_certification_token_coverage"][
        "coverage_shortfall_seconds"
    ] == 74_973.617
    assert payload["vexp_certification_token_coverage"][
        "credential_material_included"
    ] is False
    assert stat.S_IMODE(lane.receipt_path.stat().st_mode) == 0o600


def test_preflight_fails_token_coverage_before_any_command(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    sentinel = tmp_path / "state.json"
    _write_state(sentinel, _current_live_insufficient_state())
    runner = NoCommandRunner()
    lane = deploy.MemorialDeployLane(
        root=tmp_path,
        env={
            "EA_DEPLOYMENT_ID": "memorial-token-preflight",
            "EA_MEMORIAL_CONTROL_TOUR_SLUG": deploy.REQUIRED_CONTROL_TOUR_SLUG,
        },
        runner=runner,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        vexp_sentinel_state_path=sentinel,
        durable_root_check=lambda _root: None,
    )

    with pytest.raises(
        deploy.DeployError,
        match="^vexp_certification_token_coverage_insufficient$",
    ):
        lane.preflight()

    assert runner.calls == []
    assert json.loads(lane.receipt_path.read_text(encoding="utf-8"))[
        "status"
    ] == "preflight"
    assert os.lstat(sentinel).st_nlink == 1
