from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_generated_release_artifacts_clean.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_generated_release_artifacts_clean", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generated_release_artifact_normalizer_ignores_host_runner_execution_fields() -> None:
    module = _load_module()
    head = {
        "status": "pass",
        "source_backed_journey_proof": {
            "as_of": "2026-05-31",
            "command": ".venv/bin/python -m pytest -q tests/test_product_browser_journeys.py",
            "cwd": "/docker/EA",
            "python_bin": ".venv/bin/python",
            "git_branch": "completion/absolute-product-finish",
            "output_excerpt": ["4 passed in 1.2s"],
            "exit_code": 0,
        },
    }
    hosted = {
        "status": "pass",
        "source_backed_journey_proof": {
            "as_of": "2026-06-01",
            "command": "/opt/hostedtoolcache/Python/3.12.*/bin/python -m pytest -q tests/test_product_browser_journeys.py",
            "cwd": "/home/runner/work/executive-assistant/executive-assistant",
            "python_bin": "/opt/hostedtoolcache/Python/3.12.*/bin/python",
            "git_branch": "main",
            "output_excerpt": ["4 passed in 1.0s"],
            "exit_code": 0,
        },
    }

    assert module._normalize(head) == module._normalize(hosted)


def test_generated_release_artifact_normalizer_preserves_semantic_status_drift() -> None:
    module = _load_module()

    assert module._normalize({"status": "pass"}) != module._normalize({"status": "blocked"})
