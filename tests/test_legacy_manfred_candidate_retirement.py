from __future__ import annotations

import contextlib
import json
import stat
from pathlib import Path

import pytest

from scripts import retire_legacy_manfred_memorial_candidate as legacy


IMAGE_ID = "sha256:" + "1" * 64
OTHER_IMAGE_ID = "sha256:" + "2" * 64


def _container(
    identifier: str,
    *,
    project: str,
    service: str,
    image_id: str,
    running: bool = True,
    health: str = "healthy",
) -> dict[str, object]:
    return {
        "id": identifier,
        "project": project,
        "service": service,
        "image_id": image_id,
        "running": running,
        "health": health,
    }


def _inventory(
    *,
    include_legacy: bool = True,
    legacy_image_id: str = IMAGE_ID,
) -> tuple[dict[str, object], ...]:
    rows = [
        _container(
            "e" * 64,
            project=legacy.LIVE_COMPOSE_PROJECT,
            service="ea-api",
            image_id=OTHER_IMAGE_ID,
        )
    ]
    if include_legacy:
        rows.extend(
            [
                _container(
                    character * 64,
                    project=legacy.LEGACY_PROJECT,
                    service=service,
                    image_id=(
                        legacy_image_id
                        if service in {"api", "gateway"}
                        else OTHER_IMAGE_ID
                    ),
                )
                for service, character in zip(
                    ("api", "gateway", "postgres", "redis"),
                    ("a", "b", "c", "d"),
                    strict=True,
                )
            ]
        )
    return tuple(rows)


@contextlib.contextmanager
def _fleet_lock(**_kwargs: object):
    yield {"scope": "ea_manfred_candidate_fleet", "exclusive": True}


def _audit(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: tuple[tuple[dict[str, object], ...], ...],
    *,
    apply: bool = False,
    registry_entries: list[dict[str, object]] | None = None,
    output_receipt: Path | None = None,
) -> dict[str, object]:
    observed = iter(snapshots)
    monkeypatch.setattr(legacy, "hold_candidate_fleet_lock", _fleet_lock)
    monkeypatch.setattr(legacy, "_container_inventory", lambda: next(observed))
    monkeypatch.setattr(
        legacy,
        "_registered_candidate_entries",
        lambda _path: list(registry_entries or []),
    )
    return legacy.audit_legacy_candidate(
        project=legacy.LEGACY_PROJECT,
        expected_image_id=IMAGE_ID,
        registry_path=Path("/unused/registry.json"),
        lock_path=Path("/unused/fleet.lock"),
        output_receipt=output_receipt,
        apply=apply,
        sample_spacing_seconds=1,
        sleep=lambda _seconds: None,
    )


def test_module_imports_without_removed_cleanup_helpers() -> None:
    assert legacy.RECEIPT_SCHEMA.endswith(".v2")
    assert legacy.retire_legacy_candidate is legacy.audit_legacy_candidate
    assert not hasattr(legacy, "_run")
    assert not hasattr(legacy, "_remove_stack")
    assert not hasattr(legacy, "_remove_image_if_still_eligible")


def test_dry_run_observes_stable_exact_legacy_candidate_without_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _inventory()

    report = _audit(monkeypatch, (snapshot, snapshot))

    assert report["status"] == "pass"
    assert report["mode"] == "dry_run"
    assert report["controller_posture"] == "observation_only"
    assert report["candidate_state"] == "observed_identity_stable"
    assert report["candidate_present"] is True
    assert report["candidate_identity_stable"] is True
    assert report["legacy_candidate"]["services"] == [
        "api",
        "gateway",
        "postgres",
        "redis",
    ]
    assert report["live_identity_unchanged"] is True
    assert report["docker_access"] == "read_only"
    assert report["destructive_apply_supported"] is False
    assert report["automatic_retirement_authorized"] is False
    assert report["retirement_authorized"] is False
    assert report["mutation_performed"] is False
    assert report["mutations_performed"] == 0


def test_apply_request_is_explicitly_blocked_and_performs_no_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _inventory()

    report = _audit(monkeypatch, (snapshot, snapshot), apply=True)

    assert report["status"] == "blocked"
    assert report["mode"] == "apply_requested"
    assert report["apply_block_reason"] == (
        "manfred_legacy_candidate_audit_destructive_apply_unavailable"
    )
    assert report["candidate_state"] == "observed_identity_stable"
    assert report["mutation_performed"] is False
    assert report["mutations_performed"] == 0


def test_identity_change_is_quarantined_without_failing_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _inventory()
    changed_rows = [dict(row) for row in initial]
    target = next(
        row
        for row in changed_rows
        if row["project"] == legacy.LEGACY_PROJECT and row["service"] == "redis"
    )
    target["id"] = "f" * 64

    report = _audit(monkeypatch, (initial, tuple(changed_rows)))

    assert report["status"] == "pass"
    assert report["candidate_state"] == "quarantined_identity_unstable"
    assert report["candidate_identity_stable"] is False
    assert report["retirement_observation_complete"] is False
    assert report["retirement_authorized"] is False


def test_invalid_legacy_health_is_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [dict(row) for row in _inventory()]
    target = next(
        row
        for row in rows
        if row["project"] == legacy.LEGACY_PROJECT and row["service"] == "api"
    )
    target["health"] = "starting"
    snapshot = tuple(rows)

    report = _audit(monkeypatch, (snapshot, snapshot))

    assert report["candidate_state"] == "quarantined_identity_unstable"
    assert report["legacy_candidate"] == {
        "present": True,
        "qualified": False,
        "error": "manfred_legacy_candidate_audit_health_invalid",
    }
    assert report["mutation_performed"] is False


def test_live_project_change_aborts_the_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _inventory()
    changed_rows = [dict(row) for row in initial]
    live = next(
        row for row in changed_rows if row["project"] == legacy.LIVE_COMPOSE_PROJECT
    )
    live["image_id"] = IMAGE_ID

    with pytest.raises(
        RuntimeError,
        match="manfred_legacy_candidate_audit_live_identity_changed",
    ):
        _audit(monkeypatch, (initial, tuple(changed_rows)))


def test_managed_image_reference_is_reported_and_never_authorizes_retirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _inventory()
    registry_entries = [
        {
            "project": "ea-manfred-candidate-managed1234",
            "image_id": IMAGE_ID,
        }
    ]

    report = _audit(
        monkeypatch,
        (snapshot, snapshot),
        registry_entries=registry_entries,
    )

    assert report["registry"] == {
        "legacy_receipt_count": 0,
        "expected_image_referenced_by_managed_projects": [
            "ea-manfred-candidate-managed1234"
        ],
        "expected_image_exclusively_legacy": False,
    }
    assert report["retirement_authorized"] is False


def test_absent_legacy_candidate_is_a_stable_read_only_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _inventory(include_legacy=False)

    report = _audit(monkeypatch, (snapshot, snapshot))

    assert report["candidate_state"] == "absent"
    assert report["candidate_present"] is False
    assert report["candidate_identity_stable"] is True
    assert report["retirement_observation_complete"] is True
    assert report["mutation_performed"] is False


def test_private_receipt_is_no_replace_and_mode_0600(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot = _inventory()
    receipt = tmp_path / "legacy-audit.v2.json"

    report = _audit(
        monkeypatch,
        (snapshot, snapshot),
        output_receipt=receipt,
    )

    assert json.loads(receipt.read_text(encoding="utf-8")) == report
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    with pytest.raises(
        RuntimeError,
        match="manfred_legacy_candidate_audit_receipt_path_invalid",
    ):
        legacy._atomic_receipt(receipt, report)


def test_skip_if_busy_returns_receipt_without_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextlib.contextmanager
    def busy(**_kwargs: object):
        yield None

    monkeypatch.setattr(legacy, "hold_candidate_fleet_lock", busy)
    monkeypatch.setattr(
        legacy,
        "_container_inventory",
        lambda: pytest.fail("busy lane must not inspect Docker"),
    )
    monkeypatch.setattr(
        legacy,
        "_registered_candidate_entries",
        lambda _path: pytest.fail("busy lane must not read registry metadata"),
    )

    report = legacy.audit_legacy_candidate(
        project=legacy.LEGACY_PROJECT,
        expected_image_id=IMAGE_ID,
        skip_if_busy=True,
    )

    assert report["status"] == "skipped"
    assert report["candidate_state"] == "not_observed"
    assert report["sample_count"] == 0
    assert report["mutation_performed"] is False


@pytest.mark.parametrize(
    ("project", "image_id", "error"),
    [
        ("ea", IMAGE_ID, "project_invalid"),
        (legacy.LEGACY_PROJECT, "sha256:bad", "image_id_invalid"),
    ],
)
def test_invalid_target_identity_is_rejected_before_locks(
    monkeypatch: pytest.MonkeyPatch,
    project: str,
    image_id: str,
    error: str,
) -> None:
    monkeypatch.setattr(
        legacy,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: pytest.fail("invalid identity reached fleet lock"),
    )
    with pytest.raises(RuntimeError, match=error):
        legacy.audit_legacy_candidate(
            project=project,
            expected_image_id=image_id,
        )


def test_cli_retains_apply_as_fail_closed_boundary() -> None:
    arguments = legacy.build_parser().parse_args(
        [
            "--project",
            legacy.LEGACY_PROJECT,
            "--expected-image-id",
            IMAGE_ID,
            "--apply",
        ]
    )

    assert arguments.apply is True
    assert arguments.receipt is None
    assert arguments.sample_spacing_seconds == 5.0
