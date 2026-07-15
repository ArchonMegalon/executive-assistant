from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Callable

import pytest

from scripts import deploy_ea_memorial as deploy


WINDOW_SECONDS = 7 * 24 * 60 * 60
EPOCH_MS = 1_800_000_000_000
DEFERRED_MS = 120_000
UPDATED_MS = EPOCH_MS + DEFERRED_MS + 30_000
CHECKED_MS = UPDATED_MS + 1_000
STATE_SHA256 = "a" * 64


def _timestamp(value_ms: int) -> str:
    seconds, milliseconds = divmod(value_ms, 1000)
    return (
        datetime.fromtimestamp(seconds, tz=UTC)
        .replace(microsecond=milliseconds * 1000)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _v6_state() -> dict[str, object]:
    required_end_ms = EPOCH_MS + DEFERRED_MS + WINDOW_SECONDS * 1000
    initial_expiration_ms = required_end_ms + 60_000
    observed_expiration_ms = required_end_ms + 3_600_000
    return {
        "version": 6,
        "epoch_started_ms": EPOCH_MS,
        "epoch_started_at": _timestamp(EPOCH_MS),
        "updated_at": _timestamp(UPDATED_MS),
        "epoch_initial_fresh_exp_ms": initial_expiration_ms,
        "last_observed_fresh_exp_ms": observed_expiration_ms,
        "fresh_token_renewals": 1,
        "fresh_token_renewed_in_epoch": True,
        "last_license": {
            "fresh_expiration_ms": observed_expiration_ms,
            "fresh_expiration_at": _timestamp(observed_expiration_ms),
            "renewed": True,
        },
        "qualification_phase": "enforced_soak",
        "qualified_at": None,
        "certification_blockers": [],
        "qualification_deferred_ms": DEFERRED_MS,
        "qualification_deferred_total_ms": DEFERRED_MS,
        "qualification_effective_elapsed_ms": 30_000,
        "qualification_earliest_completion_at": _timestamp(required_end_ms),
        "qualification_deferred_reasons": [],
        "qualification_deferred_since_at": None,
        "qualification_deferred_since_monotonic_ms": None,
        "apparmor_qualification_ready": True,
        "epoch_apparmor_enforced": True,
        "current_resources_healthy": True,
        "resource_samples_attempted": 8,
        "resource_samples_passed": 7,
    }


def _coverage(
    state: dict[str, object],
    *,
    checked_at_ms: int = CHECKED_MS,
    state_file_mtime_ms: int = UPDATED_MS,
) -> dict[str, object]:
    return deploy._vexp_certification_token_coverage(
        state,
        state_sha256=STATE_SHA256,
        checked_at_ms=checked_at_ms,
        state_file_mtime_ns=state_file_mtime_ms * 1_000_000,
        required_window_seconds=WINDOW_SECONDS,
    )


def test_current_v6_authorizes_token_coverage_before_wall_clock_soak_completion() -> None:
    evidence = _coverage(_v6_state())

    assert CHECKED_MS < evidence["certification_required_end_ms"]
    assert evidence["status"] == "pass"
    assert evidence["token_coverage_safe"] is True
    assert evidence["state_version"] == 6
    assert evidence["current_state_version"] == 6
    assert evidence["supported_state_versions"] == [5, 6]
    assert evidence["resource_samples_attempted"] == 8
    assert evidence["resource_samples_passed"] == 7


def test_current_unrenewed_v6_remains_blocked() -> None:
    state = _v6_state()
    initial_expiration_ms = int(state["epoch_initial_fresh_exp_ms"])
    state["last_observed_fresh_exp_ms"] = initial_expiration_ms
    state["fresh_token_renewals"] = 0
    state["fresh_token_renewed_in_epoch"] = False
    state["certification_blockers"] = ["license:fresh_token_not_renewed"]
    state["last_license"] = {
        "fresh_expiration_ms": initial_expiration_ms,
        "fresh_expiration_at": _timestamp(initial_expiration_ms),
        "renewed": False,
    }

    evidence = _coverage(state)

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "fresh_token_renewal_required"
    assert "fresh_token_renewal_not_observed_in_epoch" in evidence["issues"]
    assert "license_certification_blocker_present" in evidence["issues"]


@pytest.mark.parametrize(
    ("field", "delta_ms"),
    [
        ("qualification_earliest_completion_at", -1),
        ("qualification_earliest_completion_at", 1),
        ("qualification_effective_elapsed_ms", -1),
        ("qualification_effective_elapsed_ms", 1),
    ],
)
def test_v6_timestamp_consistency_accepts_one_millisecond_rounding_tolerance(
    field: str, delta_ms: int
) -> None:
    state = _v6_state()
    if field == "qualification_earliest_completion_at":
        required_end_ms = EPOCH_MS + DEFERRED_MS + WINDOW_SECONDS * 1000
        state[field] = _timestamp(required_end_ms + delta_ms)
    else:
        state[field] = 30_000 + delta_ms

    evidence = _coverage(state)

    assert evidence["status"] == "pass"
    assert evidence["token_coverage_safe"] is True


@pytest.mark.parametrize(
    ("field", "expected_issue"),
    [
        ("apparmor_qualification_ready", "apparmor_qualification_not_ready"),
        ("current_resources_healthy", "current_resources_unhealthy"),
    ],
)
def test_v6_false_qualification_health_evidence_blocks_promotion(
    field: str, expected_issue: str
) -> None:
    state = _v6_state()
    state[field] = False

    evidence = _coverage(state)

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_qualification_preconditions_not_ready"
    assert expected_issue in evidence["issues"]
    assert evidence["token_coverage_safe"] is False


def test_v6_epoch_without_apparmor_enforcement_blocks_promotion() -> None:
    state = _v6_state()
    state["apparmor_qualification_ready"] = False
    state["epoch_apparmor_enforced"] = False

    evidence = _coverage(state)

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_qualification_preconditions_not_ready"
    assert "apparmor_not_enforced_in_epoch" in evidence["issues"]
    assert evidence["token_coverage_safe"] is False


def test_v6_expired_token_blocks_even_after_valid_renewal_and_coverage() -> None:
    state = _v6_state()
    expiration_ms = int(state["last_observed_fresh_exp_ms"])
    checked_at_ms = expiration_ms + 1_000
    updated_at_ms = checked_at_ms - 1_000
    state["updated_at"] = _timestamp(updated_at_ms)
    state["qualification_effective_elapsed_ms"] = (
        updated_at_ms - EPOCH_MS - DEFERRED_MS
    )

    evidence = _coverage(
        state,
        checked_at_ms=checked_at_ms,
        state_file_mtime_ms=updated_at_ms,
    )

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "fresh_token_expired"
    assert evidence["issues"] == ["fresh_token_expired"]
    assert evidence["token_coverage_safe"] is False


def test_v6_license_blocker_fails_closed_despite_otherwise_valid_renewal() -> None:
    state = _v6_state()
    state["certification_blockers"] = ["license:account_hold"]

    evidence = _coverage(state)

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "license_certification_blocked"
    assert "license_certification_blocker_present" in evidence["issues"]
    assert evidence["token_coverage_safe"] is False


def test_v6_deferred_time_extends_required_token_coverage_end() -> None:
    state = _v6_state()
    expiration_ms = EPOCH_MS + WINDOW_SECONDS * 1000 + 60_000
    state["epoch_initial_fresh_exp_ms"] = EPOCH_MS + 1_000
    state["last_observed_fresh_exp_ms"] = expiration_ms
    state["last_license"] = {
        "fresh_expiration_ms": expiration_ms,
        "fresh_expiration_at": _timestamp(expiration_ms),
        "renewed": True,
    }

    evidence = _coverage(state)

    expected_end_ms = EPOCH_MS + DEFERRED_MS + WINDOW_SECONDS * 1000
    assert evidence["certification_required_end_ms"] == expected_end_ms
    assert evidence["status"] == "fail"
    assert evidence["reason"] == "fresh_token_coverage_insufficient"
    assert evidence["coverage_shortfall_seconds"] == 60.0


@pytest.mark.parametrize(
    ("mutate", "expected_issue"),
    [
        (
            lambda state: state.__setitem__(
                "qualification_earliest_completion_at",
                _timestamp(EPOCH_MS + DEFERRED_MS + WINDOW_SECONDS * 1000 + 2),
            ),
            "qualification_earliest_completion_inconsistent",
        ),
        (
            lambda state: state.__setitem__(
                "qualification_effective_elapsed_ms", 30_002
            ),
            "qualification_effective_elapsed_inconsistent",
        ),
        (
            lambda state: state.update(
                qualification_deferred_reasons=["daemon:swap_pressure_pending"]
            ),
            "qualification_deferred_since_at_invalid",
        ),
        (
            lambda state: state.__setitem__("apparmor_qualification_ready", "true"),
            "apparmor_qualification_ready_invalid",
        ),
        (
            lambda state: state.__setitem__("qualification_deferred_ms", True),
            "qualification_deferred_ms_invalid",
        ),
        (
            lambda state: state.__setitem__("resource_samples_passed", 9),
            "resource_sample_counts_inconsistent",
        ),
    ],
)
def test_v6_malformed_or_contradictory_state_fails_closed(
    mutate: Callable[[dict[str, object]], object], expected_issue: str
) -> None:
    state = deepcopy(_v6_state())
    mutate(state)

    evidence = _coverage(state)

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_state_invalid"
    assert expected_issue in evidence["issues"]
    assert evidence["token_coverage_safe"] is False


@pytest.mark.parametrize(
    ("mutate", "expected_issue"),
    [
        (
            lambda state: (
                state.pop("resource_samples_attempted"),
                state.pop("resource_samples_passed"),
            ),
            "resource_sample_counts_incomplete",
        ),
        (
            lambda state: state.pop("resource_samples_attempted"),
            "resource_sample_counts_incomplete",
        ),
        (
            lambda state: state.pop("resource_samples_passed"),
            "resource_sample_counts_incomplete",
        ),
        (
            lambda state: state.update(
                resource_samples_attempted=0,
                resource_samples_passed=0,
            ),
            "resource_samples_attempted_invalid",
        ),
        (
            lambda state: state.update(
                resource_samples_attempted=1,
                resource_samples_passed=0,
            ),
            "resource_samples_passed_invalid",
        ),
        (
            lambda state: state.update(
                resource_samples_attempted=3,
                resource_samples_passed=4,
            ),
            "resource_sample_counts_inconsistent",
        ),
        (
            lambda state: state.update(resource_samples_attempted=True),
            "resource_samples_attempted_invalid",
        ),
        (
            lambda state: state.update(resource_samples_passed=True),
            "resource_samples_passed_invalid",
        ),
    ],
)
def test_v6_requires_positive_coherent_resource_sample_evidence(
    mutate: Callable[[dict[str, object]], object], expected_issue: str
) -> None:
    state = deepcopy(_v6_state())
    mutate(state)

    evidence = _coverage(state)

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_state_invalid"
    assert expected_issue in evidence["issues"]
    assert evidence["token_coverage_safe"] is False


def test_supported_v5_state_retains_original_coverage_contract() -> None:
    state = _v6_state()
    state["version"] = 5
    for field in (
        "qualification_deferred_ms",
        "qualification_deferred_total_ms",
        "qualification_effective_elapsed_ms",
        "qualification_earliest_completion_at",
        "qualification_deferred_reasons",
        "qualification_deferred_since_at",
        "qualification_deferred_since_monotonic_ms",
        "apparmor_qualification_ready",
        "epoch_apparmor_enforced",
        "current_resources_healthy",
        "resource_samples_attempted",
        "resource_samples_passed",
    ):
        state.pop(field)
    original_required_end_ms = EPOCH_MS + WINDOW_SECONDS * 1000
    state["epoch_initial_fresh_exp_ms"] = original_required_end_ms + 60_000
    state["last_observed_fresh_exp_ms"] = original_required_end_ms + 3_600_000
    state["last_license"] = {
        "fresh_expiration_ms": original_required_end_ms + 3_600_000,
        "fresh_expiration_at": _timestamp(original_required_end_ms + 3_600_000),
        "renewed": True,
    }

    evidence = _coverage(state)

    assert evidence["status"] == "pass"
    assert evidence["state_version"] == 5
    assert evidence["certification_required_end_ms"] == original_required_end_ms
    assert evidence["qualification_deferred_total_ms"] == 0


def test_v6_active_deferred_reason_blocks_even_when_other_evidence_passes() -> None:
    state = _v6_state()
    state["qualification_deferred_reasons"] = ["daemon:swap_pressure_pending"]
    state["qualification_deferred_since_at"] = _timestamp(UPDATED_MS - 1_000)
    state["qualification_deferred_since_monotonic_ms"] = 42_000

    evidence = _coverage(state)

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_qualification_preconditions_not_ready"
    assert "qualification_currently_deferred" in evidence["issues"]
    assert evidence["token_coverage_safe"] is False
