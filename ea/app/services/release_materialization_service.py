from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


DEFAULT_RELEASE_MATERIALIZERS: tuple[list[str], ...] = (
    ["scripts/materialize_ea_browser_workflow_proof.py"],
    ["scripts/materialize_ea_flagship_release_gate.py"],
    ["scripts/materialize_weekly_product_pulse.py"],
    ["scripts/materialize_project_mode_manifests.py"],
    ["scripts/materialize_whole_project_gold_map.py"],
    ["scripts/materialize_memorial_phrase_bank.py"],
    ["scripts/materialize_memorial_operator_status.py"],
)


def materialize_release_assets(*, python_bin: str = sys.executable) -> None:
    for command in DEFAULT_RELEASE_MATERIALIZERS:
        env = None
        if command[-1] == "scripts/materialize_whole_project_gold_map.py":
            env = {"PYTHONPATH": "ea"}
        _run_python(python_bin=python_bin, command=command, extra_env=env)


def _run_python(*, python_bin: str, command: list[str], extra_env: dict[str, str] | None = None) -> None:
    import os

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [python_bin, *command],
        cwd=str(ROOT),
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
