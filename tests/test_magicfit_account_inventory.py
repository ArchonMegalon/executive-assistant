from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "materialize_magicfit_account_inventory.py"
    spec = importlib.util.spec_from_file_location("materialize_magicfit_account_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_magicfit_account_inventory_tracks_configured_accounts_without_secrets(tmp_path: Path) -> None:
    module = _load_script()
    ltds = tmp_path / "LTDs.md"
    ltds.write_text(
        """
| `MagicFit` | `License Tier 5` | `3 accounts` | `Owned` |  | `Tier 4` | local only | Accounts reported as `magicfit-a@example.test`, `magicfit-b@example.test`, and `magicfit-c@example.test`; secrets stay local. |
""".strip(),
        encoding="utf-8",
    )
    provider_receipt = tmp_path / "provider.json"
    provider_receipt.write_text(
        json.dumps({"account": {"account_user": "magicfit-a@example.test"}}),
        encoding="utf-8",
    )
    output = tmp_path / "inventory.json"

    receipt = module.build_inventory(
        ltds_path=ltds,
        provider_receipt_path=provider_receipt,
        output_path=output,
        depleted_account="magicfit-b@example.test",
        accounts=("magicfit-a@example.test", "magicfit-b@example.test", "magicfit-c@example.test"),
    )

    assert output.is_file()
    assert receipt["contract_name"] == "executive_assistant.magicfit_account_inventory.v1"
    assert receipt["account_count"] == 3
    assert receipt["functioning_account_count_user_reported"] == 3
    assert receipt["depleted_account_count_user_reported"] == 1
    assert receipt["usable_for_new_render_count_user_reported"] == 2
    assert receipt["inventory_recorded_in_ltds"] is True
    rendered = json.dumps(receipt)
    assert "forbidden-secret" not in rendered
    rows = {row["account_user"]: row for row in receipt["accounts"]}
    assert rows["magicfit-a@example.test"]["used_for_existing_provider_proof"] is True
    assert rows["magicfit-b@example.test"]["credit_state"] == "depleted"
    assert rows["magicfit-c@example.test"]["credential_committed"] is False


def test_magicfit_account_inventory_cli_uses_configured_ltd_inventory(tmp_path: Path, monkeypatch) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "materialize_magicfit_account_inventory.py"
    ltds = tmp_path / "LTDs.md"
    ltds.write_text(
        "| `MagicFit` | `License Tier 5` | `2 accounts` | `Owned` |  | `Tier 4` | local only | Accounts reported as `magicfit-one@example.test` and `magicfit-two@example.test`; secrets stay local. |\n",
        encoding="utf-8",
    )
    output = tmp_path / "inventory.json"
    provider_receipt = tmp_path / "missing-provider-receipt.json"
    monkeypatch.setenv("CHUMMER_EA_MAGICFIT_ACCOUNT_EMAILS", "magicfit-one@example.test,magicfit-two@example.test")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--ltds",
            str(ltds),
            "--provider-receipt",
            str(provider_receipt),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert body["account_count"] == 2
    assert receipt["inventory_recorded_in_ltds"] is True
    assert receipt["existing_provider_proof_account"] == ""


def test_magicfit_account_use_receipts_default_to_pending_without_secrets(tmp_path: Path, monkeypatch) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "materialize_magicfit_account_use_receipts.py"
    output_dir = tmp_path / "magicfit"
    monkeypatch.setenv("CHUMMER_EA_MAGICFIT_ACCOUNT_EMAILS", "magicfit-one@example.test,magicfit-two@example.test")
    result = subprocess.run(
        [sys.executable, str(script), "--output-dir", str(output_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["receipt_count"] == 2
    assert body["asset_provenance_claim_allowed_count"] == 0
    receipts = sorted(output_dir.glob("MAGICFIT_ACCOUNT_USE_*.generated.json"))
    assert len(receipts) == 2
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in receipts)
    assert "pending_account_use" in rendered
    assert "asset_provenance_claim_allowed" in rendered
    assert "magicfit-one@example.test" not in rendered
    assert "magicfit-two@example.test" not in rendered


def test_magicfit_scripts_do_not_default_to_real_account_emails() -> None:
    root = Path(__file__).resolve().parents[1]
    rendered = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "scripts/materialize_magicfit_account_inventory.py",
            "scripts/materialize_magicfit_account_use_receipts.py",
            "scripts/verify_magicfit_provider.py",
            "scripts/materialize_magicfit_provider_completion.py",
            "scripts/run_magicfit_provider_bakeoff.py",
            "scripts/verify_magicfit_public_safety.py",
            "scripts/verify_magicfit_motion_and_people_action.py",
            "scripts/final_magicfit_provider_adapter_verdict.py",
            "scripts/verify_magicfit_design_boundary.py",
        )
    )

    forbidden = (
        "tibor.girschele" + "@gmail.com",
        "the.girscheles" + "@gmail.com",
        "archon.megalon" + "@gmail.com",
    )
    for account in forbidden:
        assert account not in rendered
    host_specific_run_services = "/docker/" + "chummercomplete/" + "chummer.run-services"
    host_specific_magicfit_completion = "/docker/" + "chummercomplete/" + "_completion/magicfit_provider"
    assert host_specific_run_services not in rendered
    assert host_specific_magicfit_completion not in rendered
