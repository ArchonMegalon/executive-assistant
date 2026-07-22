from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.services.audiobook_tts.budget_ledger import (
    AccountBalance,
    BudgetLedgerError,
    VocalLabBudgetLedger,
)


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
CREDENTIAL_BINDING_SHA256 = "a" * 64


def _ledger(tmp_path: Path, **changes: object) -> VocalLabBudgetLedger:
    tmp_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_path.chmod(0o700)
    values: dict[str, object] = {
        "credential_binding_sha256": CREDENTIAL_BINDING_SHA256,
        "minimum_account_reserve": 3000,
        "maximum_points_per_job": 1000,
        "maximum_segments_per_job": 10,
        "allow_topup_points": False,
    }
    values.update(changes)
    return VocalLabBudgetLedger(tmp_path / "coordinator", **values)  # type: ignore[arg-type]


def _reserve(
    ledger: VocalLabBudgetLedger,
    *,
    key: str = "key-1",
    fingerprint: str = "f" * 64,
    estimated: int = 10,
    monthly: int = 10000,
    topup: int = 0,
    job: str = "job-1",
):  # type: ignore[no-untyped-def]
    return ledger.reserve(
        job_id=job,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        points_estimated=estimated,
        balance=AccountBalance(monthly_points=monthly, topup_points=topup),
        observed_at=NOW,
    )


def _post_known(
    ledger: VocalLabBudgetLedger,
    *,
    key: str = "key-1",
    fingerprint: str = "f" * 64,
):  # type: ignore[no-untyped-def]
    reservation = _reserve(ledger, key=key, fingerprint=fingerprint)
    ledger.mark_post_started(reservation.reservation_id, started_at=NOW)
    return ledger.record_generation(reservation.reservation_id, "generation-1")


def _rewrite_payload(ledger: VocalLabBudgetLedger, payload: dict[str, Any]) -> None:
    ledger.path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    ledger.path.chmod(0o600)


def test_ledger_is_atomic_owner_only_and_public_projection_redacts_private_values(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    known = _post_known(ledger)
    charged = ledger.reconcile_charge(known.reservation_id, points_used=9)
    complete = ledger.commit_materialized(
        charged.reservation_id,
        output_sha256="d" * 64,
    )

    assert complete.status == "complete"
    assert ledger.path.stat().st_mode & 0o777 == 0o600
    stored = json.loads(ledger.path.read_text())
    row = stored["reservations"][known.reservation_id]
    assert row["points_used"] == 9
    assert row["generation_id_private"] == "generation-1"
    assert stored["last_observed_balance"]["monthly_points"] == 10000

    projection = ledger.public_projection()
    rendered = json.dumps(projection)
    assert projection["exact_balance_exposed"] is False
    assert projection["raw_generation_ids_exposed"] is False
    assert "generation-1" not in rendered
    assert "key-1" not in rendered


def test_unknown_charge_blocks_same_request_and_entire_account(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    reservation = _reserve(ledger)
    ledger.mark_post_started(reservation.reservation_id, started_at=NOW)
    ledger.mark_unknown(reservation.reservation_id)

    with pytest.raises(BudgetLedgerError) as same:
        _reserve(ledger)
    assert same.value.code == "budget_request_charge_unknown"
    assert same.value.charge_state == "unknown"

    with pytest.raises(BudgetLedgerError) as account:
        _reserve(ledger, key="key-2", fingerprint="e" * 64)
    assert account.value.code == "budget_account_charge_unknown"
    assert account.value.charge_state == "unknown"


def test_generation_known_and_charged_pending_resume_without_new_post(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    known = _post_known(ledger)
    resumed = _reserve(ledger)
    assert resumed.status == "generation_known"
    assert resumed.generation_id_private == "generation-1"

    ledger.reconcile_charge(known.reservation_id, points_used=9)
    charged = _reserve(ledger)
    assert charged.status == "charged_pending_materialization"
    assert charged.points_used == 9


def test_completed_request_cannot_be_regenerated(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    known = _post_known(ledger)
    ledger.reconcile_charge(known.reservation_id, points_used=9)
    ledger.commit_materialized(known.reservation_id, output_sha256="d" * 64)
    with pytest.raises(BudgetLedgerError) as caught:
        _reserve(ledger)
    assert caught.value.code == "budget_request_already_completed"
    assert caught.value.charge_state == "charged"


def test_only_never_posted_reservation_may_be_released(
    tmp_path: Path,
) -> None:
    never_posted = _ledger(tmp_path / "never-posted")
    reserved = _reserve(never_posted)
    assert never_posted.release_known_uncharged(reserved.reservation_id).status == "released"
    assert _reserve(never_posted).status == "reserved"

    post_started = _ledger(tmp_path / "post-started")
    reservation = _reserve(post_started)
    post_started.mark_post_started(reservation.reservation_id, started_at=NOW)
    with pytest.raises(BudgetLedgerError) as submitted:
        post_started.release_known_uncharged(reservation.reservation_id)
    assert submitted.value.code == "budget_reservation_state_invalid"

    generation_known = _ledger(tmp_path / "generation-known")
    known = _post_known(generation_known)
    with pytest.raises(BudgetLedgerError) as identified:
        generation_known.release_known_uncharged(known.reservation_id)
    assert identified.value.code == "budget_reservation_state_invalid"


@pytest.mark.parametrize(
    "state",
    [
        "reserved",
        "post_started",
        "generation_known",
        "charged_pending_materialization",
        "complete",
        "complete_budget_violation",
        "unknown",
    ],
)
def test_duplicate_fingerprint_is_blocked_across_every_nonreleased_state(
    tmp_path: Path, state: str
) -> None:
    ledger = _ledger(tmp_path / state)
    reservation = _reserve(ledger)
    if state != "reserved":
        ledger.mark_post_started(reservation.reservation_id, started_at=NOW)
    if state in {
        "generation_known",
        "charged_pending_materialization",
        "complete",
        "complete_budget_violation",
    }:
        ledger.record_generation(reservation.reservation_id, "generation-1")
    if state in {"charged_pending_materialization", "complete"}:
        ledger.reconcile_charge(reservation.reservation_id, points_used=9)
    if state == "complete":
        ledger.commit_materialized(reservation.reservation_id, output_sha256="d" * 64)
    if state == "complete_budget_violation":
        with pytest.raises(BudgetLedgerError):
            ledger.reconcile_charge(reservation.reservation_id, points_used=11)
    if state == "unknown":
        ledger.mark_unknown(reservation.reservation_id)

    with pytest.raises(BudgetLedgerError) as caught:
        _reserve(ledger, key="key-2")
    assert caught.value.code == "duplicate_synthesis_fingerprint"


def test_same_idempotency_key_cannot_bind_a_different_fingerprint(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _reserve(ledger)
    with pytest.raises(BudgetLedgerError) as caught:
        _reserve(ledger, fingerprint="e" * 64)
    assert caught.value.code == "idempotency_key_reused"


def test_existing_reserved_request_rechecks_fresh_balance_and_estimate(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    _reserve(ledger)
    with pytest.raises(BudgetLedgerError) as balance:
        _reserve(ledger, monthly=3009)
    assert balance.value.code == "budget_account_reserve_reached"
    with pytest.raises(BudgetLedgerError) as estimate:
        _reserve(ledger, estimated=11)
    assert estimate.value.code == "budget_reservation_estimate_changed"


def test_nonlowerable_reserve_job_segment_and_topup_policies(tmp_path: Path) -> None:
    with pytest.raises(BudgetLedgerError) as reserve_policy:
        _ledger(tmp_path / "bad-reserve", minimum_account_reserve=2999)
    assert reserve_policy.value.code == "budget_policy_invalid"
    with pytest.raises(BudgetLedgerError) as bool_policy:
        _ledger(tmp_path / "bad-bool", allow_topup_points=1)
    assert bool_policy.value.code == "budget_policy_invalid"

    account = _ledger(tmp_path / "account")
    with pytest.raises(BudgetLedgerError) as account_error:
        _reserve(account, estimated=101, monthly=3100)
    assert account_error.value.code == "budget_account_reserve_reached"

    ceiling = _ledger(tmp_path / "ceiling", maximum_points_per_job=20)
    _reserve(ceiling, estimated=15)
    with pytest.raises(BudgetLedgerError) as job_error:
        _reserve(ceiling, key="key-2", fingerprint="e" * 64, estimated=6)
    assert job_error.value.code == "budget_job_point_ceiling_reached"

    segment = _ledger(tmp_path / "segment", maximum_segments_per_job=1)
    _reserve(segment)
    with pytest.raises(BudgetLedgerError) as segment_error:
        _reserve(segment, key="key-2", fingerprint="e" * 64)
    assert segment_error.value.code == "budget_job_segment_ceiling_reached"

    denied = _ledger(tmp_path / "topup-denied")
    with pytest.raises(BudgetLedgerError) as topup_denied:
        _reserve(denied, estimated=50, monthly=3020, topup=10000)
    assert topup_denied.value.code == "budget_account_reserve_reached"
    with pytest.raises(BudgetLedgerError) as topup_enabled:
        _ledger(tmp_path / "topup-enabled", allow_topup_points=True)
    assert topup_enabled.value.code == "budget_policy_invalid"


def test_exact_overrun_is_charged_persisted_and_opens_circuit(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    known = _post_known(ledger)
    with pytest.raises(BudgetLedgerError) as caught:
        ledger.reconcile_charge(known.reservation_id, points_used=11)
    assert caught.value.code == "provider_points_exceeded_reservation"
    assert caught.value.charge_state == "charged"
    projection = ledger.public_projection()
    assert projection["circuit_breaker_status"] == "open"
    assert projection["reservation_status_counts"] == {
        "complete_budget_violation": 1
    }


def test_generation_identifier_is_private_valid_and_immutable(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    reservation = _reserve(ledger)
    ledger.mark_post_started(reservation.reservation_id, started_at=NOW)
    with pytest.raises(BudgetLedgerError) as invalid:
        ledger.record_generation(reservation.reservation_id, "bad id")
    assert invalid.value.code == "provider_generation_id_invalid"

    ledger.record_generation(reservation.reservation_id, "generation-1")
    with pytest.raises(BudgetLedgerError) as immutable:
        ledger.record_generation(reservation.reservation_id, "generation-2")
    assert immutable.value.code == "provider_generation_id_immutable"


def test_account_global_rate_limit_is_durable_across_ledger_instances(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    ledger.record_request_started(started_at=NOW, requests_per_minute=30)
    reloaded = _ledger(tmp_path)
    with pytest.raises(BudgetLedgerError) as caught:
        reloaded.record_request_started(
            started_at=NOW + timedelta(seconds=1),
            requests_per_minute=30,
        )
    assert caught.value.code == "provider_local_rate_limited"
    assert caught.value.retry_after_seconds == 1
    reloaded.record_request_started(
        started_at=NOW + timedelta(seconds=2),
        requests_per_minute=30,
    )


def test_credential_derives_one_canonical_cross_job_coordinator(
    tmp_path: Path,
) -> None:
    first = _ledger(tmp_path)
    second = _ledger(tmp_path)
    assert first.path == second.path
    assert CREDENTIAL_BINDING_SHA256 in first.path.name
    _reserve(first, job="job-a", key="key-a", fingerprint="a" * 64, estimated=600)
    with pytest.raises(BudgetLedgerError) as account_reserve:
        _reserve(
            second,
            job="job-b",
            key="key-b",
            fingerprint="b" * 64,
            estimated=500,
            monthly=4000,
        )
    assert account_reserve.value.code == "budget_account_reserve_reached"

    projection = second.public_projection()
    rendered = json.dumps(projection)
    assert projection["credential_binding_exposed"] is False
    assert projection["provider_spend_authority"] == (
        "denied_without_verified_balance_partition"
    )
    assert CREDENTIAL_BINDING_SHA256 not in rendered


def test_coordinator_rejects_alternate_credential_root_and_topup_authority(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    ledger.assert_scope(
        credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
        canonical_account_state_root=ledger.account_state_root,
    )
    with pytest.raises(BudgetLedgerError) as credential:
        ledger.assert_scope(
            credential_binding_sha256="b" * 64,
            canonical_account_state_root=ledger.account_state_root,
        )
    assert credential.value.code == "budget_coordinator_scope_mismatch"
    with pytest.raises(BudgetLedgerError) as root:
        ledger.assert_scope(
            credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            canonical_account_state_root=tmp_path / "alternate",
        )
    assert root.value.code == "budget_coordinator_scope_mismatch"
    with pytest.raises(BudgetLedgerError) as relative:
        VocalLabBudgetLedger(
            Path("relative"),
            credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
        )
    assert relative.value.code == "budget_coordinator_root_invalid"


def test_three_consecutive_upstream_failures_open_durable_circuit(
    tmp_path: Path,
) -> None:
    first = _ledger(tmp_path)
    second = _ledger(tmp_path)
    first.record_upstream_failure()
    second.record_provider_success()
    assert first.public_projection()["consecutive_upstream_failures"] == 0
    for _ in range(3):
        second.record_upstream_failure()
    projection = first.public_projection()
    assert projection["consecutive_upstream_failures"] == 3
    assert projection["circuit_breaker_status"] == "open"
    with pytest.raises(BudgetLedgerError) as blocked:
        _reserve(first, key="new", fingerprint="c" * 64)
    assert blocked.value.code == "budget_circuit_breaker_open"


@pytest.mark.parametrize(
    "case",
    [
        "root_extra",
        "version_bool",
        "policy_string",
        "balance_bool",
        "rate_bool",
        "reservation_extra",
        "estimated_bool",
        "used_string",
        "status_unknown_value",
        "generation_hash_mismatch",
        "naive_timestamp",
    ],
)
def test_deep_ledger_schema_rejects_type_confusion_and_private_tampering(
    tmp_path: Path, case: str
) -> None:
    ledger = _ledger(tmp_path / case)
    reservation = _reserve(ledger)
    payload = json.loads(ledger.path.read_text())
    row = payload["reservations"][reservation.reservation_id]
    if case == "root_extra":
        payload["unexpected"] = False
    elif case == "version_bool":
        payload["version"] = True
    elif case == "policy_string":
        payload["policy"]["minimum_account_reserve"] = "3000"
    elif case == "balance_bool":
        payload["last_observed_balance"]["monthly_points"] = True
    elif case == "rate_bool":
        payload["rate_limit"]["last_request_started_at"] = False
    elif case == "reservation_extra":
        row["provider_secret"] = "private"
    elif case == "estimated_bool":
        row["points_estimated"] = True
    elif case == "used_string":
        row["points_used"] = "0"
    elif case == "status_unknown_value":
        row["status"] = "pending"
    elif case == "generation_hash_mismatch":
        row["status"] = "generation_known"
        row["generation_id_private"] = "generation-1"
        row["generation_id_sha256"] = "b" * 64
    elif case == "naive_timestamp":
        row["updated_at"] = "2026-07-22T10:00:00"
    _rewrite_payload(ledger, payload)

    with pytest.raises(BudgetLedgerError) as caught:
        ledger.public_projection()
    assert caught.value.code == "budget_ledger_invalid"
    assert "private" not in repr(caught.value)


def test_file_lock_parent_symlink_and_hardlink_attacks_fail_closed(
    tmp_path: Path,
) -> None:
    bad_mode = _ledger(tmp_path / "mode")
    _reserve(bad_mode)
    bad_mode.path.chmod(0o644)
    with pytest.raises(BudgetLedgerError) as mode:
        bad_mode.public_projection()
    assert mode.value.code == "budget_ledger_file_unsafe"

    hardlinked = _ledger(tmp_path / "hardlink")
    _reserve(hardlinked)
    os.link(hardlinked.path, hardlinked.path.parent / "other.json")
    with pytest.raises(BudgetLedgerError) as link:
        hardlinked.public_projection()
    assert link.value.code == "budget_ledger_file_unsafe"

    lock_attack = _ledger(tmp_path / "lock")
    lock_attack.path.parent.mkdir(parents=True, mode=0o700)
    lock_attack.path.parent.chmod(0o700)
    target = lock_attack.path.parent / "target"
    target.write_text("x")
    target.chmod(0o600)
    (lock_attack.path.parent / f"{lock_attack.path.name}.lock").symlink_to(target)
    with pytest.raises(BudgetLedgerError) as lock:
        lock_attack.public_projection()
    assert lock.value.code in {
        "budget_ledger_lock_unavailable",
        "budget_ledger_lock_unsafe",
    }

    real = tmp_path / "real-parent"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias-parent"
    alias.symlink_to(real, target_is_directory=True)
    symlinked = VocalLabBudgetLedger(
        alias,
        credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
        minimum_account_reserve=3000,
    )
    with pytest.raises(BudgetLedgerError) as parent:
        symlinked.public_projection()
    assert parent.value.code == "budget_ledger_path_unsafe"


def test_invalid_balance_timestamp_and_policy_types_fail_before_write(
    tmp_path: Path,
) -> None:
    with pytest.raises(BudgetLedgerError):
        AccountBalance(monthly_points=True)  # type: ignore[arg-type]
    ledger = _ledger(tmp_path)
    with pytest.raises(BudgetLedgerError) as timestamp:
        ledger.reserve(
            job_id="job",
            idempotency_key="key",
            request_fingerprint="f" * 64,
            points_estimated=1,
            balance=AccountBalance(monthly_points=10000),
            observed_at=datetime(2026, 7, 22, 10, 0),
        )
    assert timestamp.value.code == "budget_balance_timestamp_invalid"
