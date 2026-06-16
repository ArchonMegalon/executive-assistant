from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ReleaseMaterializerStep:
    name: str
    command: tuple[str, ...]
    extra_env: dict[str, str] | None = None


DEFAULT_RELEASE_MATERIALIZERS: tuple[ReleaseMaterializerStep, ...] = (
    ReleaseMaterializerStep("ea_browser_workflow_proof", ("scripts/materialize_ea_browser_workflow_proof.py",)),
    ReleaseMaterializerStep("ea_flagship_release_gate", ("scripts/materialize_ea_flagship_release_gate.py",)),
    ReleaseMaterializerStep("weekly_product_pulse", ("scripts/materialize_weekly_product_pulse.py",)),
    ReleaseMaterializerStep("project_mode_manifests", ("scripts/materialize_project_mode_manifests.py",)),
    ReleaseMaterializerStep("whole_project_gold_map", ("scripts/materialize_whole_project_gold_map.py",), extra_env={"PYTHONPATH": "ea"}),
    ReleaseMaterializerStep("memorial_phrase_bank", ("scripts/materialize_memorial_phrase_bank.py",)),
    ReleaseMaterializerStep("memorial_operator_status", ("scripts/materialize_memorial_operator_status.py",)),
)


def materialize_release_assets(*, python_bin: str = sys.executable) -> None:
    for step in DEFAULT_RELEASE_MATERIALIZERS:
        _run_python(python_bin=python_bin, step=step)


def _run_python(*, python_bin: str, step: ReleaseMaterializerStep) -> None:
    import os

    env = os.environ.copy()
    if step.extra_env:
        env.update(step.extra_env)
    proc = subprocess.run(
        [python_bin, *step.command],
        cwd=str(ROOT),
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
