from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "verify_runtime_supply_chain.py"
    spec = importlib.util.spec_from_file_location("verify_runtime_supply_chain", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_supply_chain_verifier_passes_for_current_tree() -> None:
    module = _load_module()

    result = module.verify()

    assert result["contract_name"] == "ea.runtime_supply_chain.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []


def test_runtime_supply_chain_cli_returns_pass_json() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify_runtime_supply_chain.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    body = json.loads(completed.stdout)
    assert body["status"] == "pass"
    assert body["issues"] == []
