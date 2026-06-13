from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_joggai_provider.py"
    spec = importlib.util.spec_from_file_location("verify_joggai_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_joggai_provider_receipt_is_candidate_only_and_api_off(tmp_path: Path) -> None:
    module = _load_script()
    ltds = tmp_path / "LTDs.md"
    ltds.write_text(
        """
| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `JoggAI` | `License Tier 4 / Team updates` | `1 account` | `Owned` | | `Tier 4` | Pending | Candidate memorial render provider only. |
""".strip(),
        encoding="utf-8",
    )
    output = tmp_path / "JOGGAI_PROVIDER_VERIFICATION.generated.json"

    receipt = module.build_receipt(ltds_path=ltds, output_path=output)

    assert output.is_file()
    assert receipt["contract_name"] == "executive_assistant.joggai_provider_verification.v1"
    assert receipt["provider_key"] == "joggai"
    assert receipt["verdict"] == "CANDIDATE_ONLY"
    assert receipt["provider_ready"] is False
    assert receipt["runtime_enabled"] is False
    assert receipt["api_available"] is False
    assert receipt["manual_workflow_allowed"] is True
    assert receipt["default_env"] == {
        "EA_MEMORIAL_JOGGAI_MODE": "manual",
        "EA_MEMORIAL_JOGGAI_ENABLED": "0",
        "EA_MEMORIAL_JOGGAI_API_ENABLED": "0",
    }
    assert receipt["checks"]["inventory_recorded"] is True
    assert {"live_memorial_conversation", "private_memory_auto_processing", "direct_public_publish"} <= set(
        receipt["forbidden_uses"]
    )


def test_verify_joggai_provider_cli_writes_receipt(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_joggai_provider.py"
    output = tmp_path / "receipt.json"
    result = subprocess.run(
        [sys.executable, str(script), "--ltds", "/docker/EA/LTDs.md", "--output", str(output)],
        cwd="/docker/EA",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert body["status"] == "warn"
    assert body["verdict"] == "CANDIDATE_ONLY"
    assert body["receipt_type"] == "inventory_only"
    assert body["provider_ready"] is False
    assert receipt["checks"]["inventory_recorded"] is True
