from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from scripts import cleanup_manfred_memorial_candidates as retention


def test_policy_free_retention_contract_is_quarantine_only() -> None:
    report = retention._base_report(apply=False)

    assert report["schema"] == "ea.manfred_memorial_candidate_retention.v3"
    assert report["mode"] == "dry_run"
    assert report["controller_posture"] == "quarantine_only"
    assert report["destructive_apply_supported"] is False
    assert report["automatic_retirement_authorized"] is False
    assert report["mutation_performed"] is False
    assert report["docker_access"] == "read_only"


def test_removed_destructive_controller_api_is_not_reintroduced() -> None:
    for name in (
        "_apply_plan",
        "_mutation_targets",
        "_remove_image_if_still_eligible",
        "_run",
        "retain_candidates",
    ):
        assert not hasattr(retention, name)


@pytest.mark.parametrize(
    "argv",
    [
        ["docker", "container", "ls", "--all", "--quiet", "--no-trunc"],
        ["docker", "container", "inspect", "a" * 64],
        ["docker", "image", "inspect", "sha256:" + "b" * 64],
    ],
)
def test_read_only_docker_commands_are_explicitly_allowed(argv: list[str]) -> None:
    assert retention._read_only_docker_command(argv) is True


@pytest.mark.parametrize(
    "argv",
    [
        ["docker", "container", "rm", "a" * 64],
        ["docker", "image", "rm", "sha256:" + "b" * 64],
        ["docker", "system", "prune", "--force"],
        ["docker", "compose", "down"],
        ["docker", "volume", "rm", "candidate-data"],
    ],
)
def test_mutating_docker_commands_are_rejected(argv: list[str]) -> None:
    assert retention._read_only_docker_command(argv) is False


def test_run_docker_rejects_mutation_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retention.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("mutation reached subprocess"),
    )

    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_retention_command_forbidden",
    ):
        retention._run_docker(["docker", "container", "rm", "a" * 64])


def test_apply_request_remains_fail_closed_at_cli_boundary() -> None:
    arguments = retention.build_parser().parse_args(["--apply"])

    assert arguments.apply is True
    assert arguments.sample_spacing_seconds == 5.0


def test_busy_fleet_lock_skips_without_registry_or_docker_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextlib.contextmanager
    def busy(**_kwargs: object):
        yield None

    monkeypatch.setattr(retention, "hold_candidate_fleet_lock", busy)
    monkeypatch.setattr(
        retention,
        "registered_candidate_receipt_postures",
        lambda **_kwargs: pytest.fail("busy lane read registry"),
    )
    monkeypatch.setattr(
        retention,
        "_container_inventory",
        lambda: pytest.fail("busy lane reached Docker"),
    )

    report = retention.evaluate_retention(
        registry_path=Path("/unused/registry.json"),
        lock_path=Path("/unused/fleet.lock"),
        skip_if_busy=True,
    )

    assert report["status"] == "skipped"
    assert report["skip_reason"] == "manfred_candidate_fleet_lock_held"
    assert report["mutation_performed"] is False


def test_main_returns_two_for_blocked_apply(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        retention,
        "evaluate_retention",
        lambda **_kwargs: {
            **retention._base_report(apply=True),
            "status": "blocked",
            "apply_block_reason": (
                "manfred_candidate_retention_destructive_apply_not_implemented"
            ),
        },
    )

    assert retention.main(["--apply"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["mutation_performed"] is False
