from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "memorial_recovery_inventory.py"
_SECRET = "CLI_SECRET_MUST_NOT_LEAK"


def _roots(tmp_path: Path, name: str) -> tuple[Path, Path, Path]:
    base = tmp_path / name
    public = base / "public"
    private = base / "private"
    archive = base / "archive"
    public.mkdir(parents=True)
    private.mkdir(parents=True)
    archive.mkdir(parents=True)
    return public, private, archive


def _inventory_path(
    private_root: Path, filename: str = "flagship.inventory.json"
) -> Path:
    return private_root / "manfred" / "recovery_snapshots" / filename


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR", None)
    env.pop("EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR", None)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_recovery_cli_materialize_verify_and_default_dry_run_then_confirmed_apply(
    tmp_path: Path,
) -> None:
    source_public, source_private, source_archive = _roots(tmp_path, "source")
    source_inventory = _inventory_path(source_private)
    materialized = _run(
        "materialize",
        "--slug",
        "manfred",
        "--destination",
        str(source_inventory),
        "--public-root",
        str(source_public),
        "--private-root",
        str(source_private),
        "--archive-root",
        str(source_archive),
    )
    assert materialized.returncode == 0, materialized.stdout
    materialized_payload = _payload(materialized)
    assert materialized_payload["status"] == "pass"
    assert materialized_payload["operation"] == "materialize"
    assert materialized_payload["inventory_body_included"] is False
    assert materialized_payload["secret_material_included"] is False
    assert "content_base64" not in materialized.stdout
    assert "audio_assets" not in materialized.stdout
    assert _SECRET not in materialized.stdout
    assert materialized_payload["receipt"]["private_context_present"] is False
    payload_sha = str(materialized_payload["receipt"]["payload_sha256"])

    target_public, target_private, target_archive = _roots(tmp_path, "target")
    target_inventory = _inventory_path(target_private)
    target_inventory.parent.mkdir(parents=True)
    shutil.copyfile(source_inventory, target_inventory)
    target_inventory.chmod(0o600)

    verified = _run(
        "verify",
        "--slug",
        "manfred",
        "--inventory",
        str(target_inventory),
        "--private-root",
        str(target_private),
    )
    assert verified.returncode == 0, verified.stdout
    verified_receipt = _payload(verified)["receipt"]
    assert verified_receipt["valid"] is True
    assert verified_receipt["contribution_sources_verified"] is False

    dry_run = _run(
        "restore",
        "--slug",
        "manfred",
        "--inventory",
        str(target_inventory),
        "--public-root",
        str(target_public),
        "--private-root",
        str(target_private),
        "--archive-root",
        str(target_archive),
    )
    assert dry_run.returncode == 0, dry_run.stdout
    dry_payload = _payload(dry_run)
    assert dry_payload["receipt"]["dry_run"] is True
    assert dry_payload["receipt"]["files_created"] == 0
    references = target_private / "manfred" / "recovery_inventory.references.json"
    assert not references.exists()

    applied = _run(
        "restore",
        "--slug",
        "manfred",
        "--inventory",
        str(target_inventory),
        "--public-root",
        str(target_public),
        "--private-root",
        str(target_private),
        "--archive-root",
        str(target_archive),
        "--apply",
        "--confirm-payload-sha",
        payload_sha,
    )
    assert applied.returncode == 0, applied.stdout
    applied_payload = _payload(applied)
    assert applied_payload["receipt"]["dry_run"] is False
    assert applied_payload["receipt"]["apply_confirmation_matched"] is True
    assert applied_payload["receipt"]["files_created"] == 1
    assert references.is_file()

    repeated = _run(
        "restore",
        "--slug",
        "manfred",
        "--inventory",
        str(target_inventory),
        "--public-root",
        str(target_public),
        "--private-root",
        str(target_private),
        "--archive-root",
        str(target_archive),
        "--apply",
        "--confirm-payload-sha",
        payload_sha,
    )
    assert repeated.returncode == 0, repeated.stdout
    assert _payload(repeated)["receipt"]["files_created"] == 0


def test_recovery_cli_apply_requires_explicit_payload_sha_confirmation(
    tmp_path: Path,
) -> None:
    public, private, archive = _roots(tmp_path, "confirmation")
    inventory = _inventory_path(private)
    created = _run(
        "materialize",
        "--slug",
        "manfred",
        "--destination",
        str(inventory),
        "--public-root",
        str(public),
        "--private-root",
        str(private),
        "--archive-root",
        str(archive),
    )
    assert created.returncode == 0

    missing = _run(
        "restore",
        "--slug",
        "manfred",
        "--inventory",
        str(inventory),
        "--private-root",
        str(private),
        "--apply",
    )
    assert missing.returncode == 1
    missing_payload = _payload(missing)
    assert missing_payload["status"] == "fail"
    assert missing_payload["error"] == {
        "code": "memorial_recovery_inventory_apply_confirmation_required"
    }
    assert "payload" not in missing.stdout

    invalid = _run(
        "restore",
        "--slug",
        "manfred",
        "--inventory",
        str(inventory),
        "--private-root",
        str(private),
        "--apply",
        "--confirm-payload-sha",
        _SECRET,
    )
    assert invalid.returncode == 1
    assert _payload(invalid)["error"] == {
        "code": "memorial_recovery_inventory_apply_confirmation_invalid"
    }
    assert _SECRET not in invalid.stdout


def test_recovery_cli_accepts_separate_contribution_roots(tmp_path: Path) -> None:
    source_public, source_private, source_archive = _roots(tmp_path, "cli-split-source")
    source_public_contributions = tmp_path / "cli-source-contributions" / "public"
    source_private_contributions = tmp_path / "cli-source-contributions" / "private"
    private_ledger = {
        "schema": "ea.memorial_family_contributions.private.v1",
        "slug": "manfred",
        "created_at": "2026-07-11T08:00:00Z",
        "updated_at": "2026-07-11T08:00:00Z",
        "contributions": [],
    }
    public_projection = {
        "schema": "ea.memorial_family_contributions.public.v1",
        "slug": "manfred",
        "generated_at": "2026-07-11T08:00:00Z",
        "memory_cards": [],
    }
    private_path = (
        source_private_contributions / "manfred" / "family_contributions.json"
    )
    public_path = (
        source_public_contributions / "manfred" / "family_contributions.public.json"
    )
    private_path.parent.mkdir(parents=True)
    public_path.parent.mkdir(parents=True)
    private_path.write_text(json.dumps(private_ledger), encoding="utf-8")
    public_path.write_text(json.dumps(public_projection), encoding="utf-8")
    private_path.chmod(0o600)
    public_path.chmod(0o644)
    inventory = _inventory_path(source_private_contributions, "split.inventory.json")

    materialized = _run(
        "materialize",
        "--slug",
        "manfred",
        "--destination",
        str(inventory),
        "--public-root",
        str(source_public),
        "--private-root",
        str(source_private),
        "--archive-root",
        str(source_archive),
        "--public-contribution-root",
        str(source_public_contributions),
        "--private-contribution-root",
        str(source_private_contributions),
    )
    assert materialized.returncode == 0, materialized.stdout
    materialized_payload = _payload(materialized)
    assert materialized_payload["receipt"]["family_private_present"] is True
    assert materialized_payload["receipt"]["family_public_present"] is True
    payload_sha = str(materialized_payload["receipt"]["payload_sha256"])
    verified = _run(
        "verify",
        "--slug",
        "manfred",
        "--inventory",
        str(inventory),
        "--public-root",
        str(source_public),
        "--private-root",
        str(source_private),
        "--public-contribution-root",
        str(source_public_contributions),
        "--private-contribution-root",
        str(source_private_contributions),
    )
    assert verified.returncode == 0, verified.stdout
    assert _payload(verified)["receipt"]["contribution_sources_verified"] is True

    target_public, target_private, target_archive = _roots(tmp_path, "cli-split-target")
    target_public_contributions = tmp_path / "cli-target-contributions" / "public"
    target_private_contributions = tmp_path / "cli-target-contributions" / "private"
    target_inventory = _inventory_path(
        target_private_contributions,
        "split.inventory.json",
    )
    target_inventory.parent.mkdir(parents=True)
    shutil.copyfile(inventory, target_inventory)
    target_inventory.chmod(0o600)

    restored = _run(
        "restore",
        "--slug",
        "manfred",
        "--inventory",
        str(target_inventory),
        "--public-root",
        str(target_public),
        "--private-root",
        str(target_private),
        "--archive-root",
        str(target_archive),
        "--public-contribution-root",
        str(target_public_contributions),
        "--private-contribution-root",
        str(target_private_contributions),
        "--apply",
        "--confirm-payload-sha",
        payload_sha,
    )
    assert restored.returncode == 0, restored.stdout
    restored_private = (
        target_private_contributions / "manfred" / "family_contributions.json"
    )
    restored_public = (
        target_public_contributions / "manfred" / "family_contributions.public.json"
    )
    assert stat.S_IMODE(restored_private.stat().st_mode) == 0o600
    assert stat.S_IMODE(restored_public.stat().st_mode) == 0o644
    assert not (target_private / "manfred" / "family_contributions.json").exists()
    assert not (target_public / "manfred" / "family_contributions.public.json").exists()


def test_recovery_cli_sanitizes_inventory_errors_and_never_prints_body(
    tmp_path: Path,
) -> None:
    _public, private, _archive = _roots(tmp_path, "sanitized")
    inventory = _inventory_path(private, f"{_SECRET}.json")
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({"secret_body": _SECRET}), encoding="utf-8")
    inventory.chmod(0o600)

    result = _run(
        "verify",
        "--slug",
        "manfred",
        "--inventory",
        str(inventory),
        "--private-root",
        str(private),
    )
    assert result.returncode == 1
    payload = _payload(result)
    assert payload["status"] == "fail"
    assert payload["error"] == {"code": "memorial_recovery_inventory_invalid"}
    assert payload["inventory_body_included"] is False
    assert payload["secret_material_included"] is False
    assert _SECRET not in result.stdout
    assert "secret_body" not in result.stdout
