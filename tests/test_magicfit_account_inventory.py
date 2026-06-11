from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "materialize_magicfit_account_inventory.py"
    spec = importlib.util.spec_from_file_location("materialize_magicfit_account_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_magicfit_account_inventory_tracks_three_accounts_without_secrets(tmp_path: Path) -> None:
    module = _load_script()
    ltds = tmp_path / "LTDs.md"
    ltds.write_text(
        """
| `MagicFit` | `License Tier 5` | `3 accounts` | `Owned` |  | `Tier 4` | local only | Accounts reported as `tibor.girschele@gmail.com`, `the.girscheles@gmail.com`, and `archon.megalon@gmail.com`; secrets stay local. |
""".strip(),
        encoding="utf-8",
    )
    provider_receipt = tmp_path / "provider.json"
    provider_receipt.write_text(
        json.dumps({"account": {"account_user": "tibor.girschele@gmail.com"}}),
        encoding="utf-8",
    )
    output = tmp_path / "inventory.json"

    receipt = module.build_inventory(
        ltds_path=ltds,
        provider_receipt_path=provider_receipt,
        output_path=output,
        depleted_account="the.girscheles@gmail.com",
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
    assert rows["tibor.girschele@gmail.com"]["used_for_existing_provider_proof"] is True
    assert rows["the.girscheles@gmail.com"]["credit_state"] == "depleted"
    assert rows["archon.megalon@gmail.com"]["credential_committed"] is False


def test_magicfit_account_inventory_cli_uses_current_ltd_inventory(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "materialize_magicfit_account_inventory.py"
    output = tmp_path / "inventory.json"
    result = subprocess.run(
        [sys.executable, str(script), "--output", str(output)],
        cwd="/docker/EA",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert body["account_count"] == 3
    assert receipt["inventory_recorded_in_ltds"] is True
    assert receipt["existing_provider_proof_account"] in {"", "tibor.girschele@gmail.com"}
