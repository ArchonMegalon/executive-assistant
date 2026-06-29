from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ReleaseMaterializerStep:
    name: str
    command: tuple[str, ...]
    extra_env: dict[str, str] | None = None


def _steps() -> tuple[ReleaseMaterializerStep, ...]:
    return (
        ReleaseMaterializerStep(
            name="ea_browser_workflow_proof",
            command=("scripts/materialize_ea_browser_workflow_proof.py",),
        ),
        ReleaseMaterializerStep(
            name="project_mode_manifests",
            command=("scripts/materialize_project_mode_manifests.py",),
        ),
        ReleaseMaterializerStep(
            name="ea_flagship_release_gate",
            command=("scripts/materialize_ea_flagship_release_gate.py",),
        ),
        ReleaseMaterializerStep(
            name="weekly_product_pulse",
            command=("scripts/materialize_weekly_product_pulse.py",),
        ),
        ReleaseMaterializerStep(
            name="telegram_video_delivery_receipt",
            command=("scripts/materialize_telegram_video_delivery_receipt.py",),
            extra_env={"PYTHONPATH": "ea"},
        ),
        ReleaseMaterializerStep(
            name="telegram_video_delivery_live_receipt",
            command=("scripts/materialize_telegram_video_delivery_live_receipt.py",),
            extra_env={"PYTHONPATH": "ea"},
        ),
        ReleaseMaterializerStep(
            name="memorial_phrase_bank",
            command=("scripts/materialize_memorial_phrase_bank.py",),
        ),
        ReleaseMaterializerStep(
            name="ea_provider_contract_receipts",
            command=("scripts/materialize_ea_provider_contract_receipts.py",),
            extra_env={"PYTHONPATH": "ea"},
        ),
        ReleaseMaterializerStep(
            name="whole_project_gold_map",
            command=("scripts/materialize_whole_project_gold_map.py",),
            extra_env={"PYTHONPATH": "ea"},
        ),
        ReleaseMaterializerStep(
            name="teable_env_recovery_readiness",
            command=("scripts/materialize_teable_env_recovery_readiness.py",),
        ),
        ReleaseMaterializerStep(
            name="whatsapp_web_action_processor_readiness",
            command=("scripts/materialize_whatsapp_web_action_processor_readiness.py",),
        ),
        ReleaseMaterializerStep(
            name="proactive_ooda_operator_status",
            command=("scripts/materialize_proactive_ooda_operator_status.py",),
        ),
        ReleaseMaterializerStep(
            name="proactive_ooda_gold_acceptance",
            command=("scripts/materialize_proactive_ooda_gold_acceptance.py",),
        ),
        ReleaseMaterializerStep(
            name="continuous_improvement_goal_posture",
            command=("scripts/materialize_continuous_improvement_goal_posture.py",),
        ),
        ReleaseMaterializerStep(
            name="memorial_stt_provider_benchmark",
            command=("scripts/benchmark_memorial_stt_providers.py",),
            extra_env={"PYTHONPATH": "ea"},
        ),
        ReleaseMaterializerStep(
            name="memorial_operator_status",
            command=("scripts/materialize_memorial_operator_status.py",),
        ),
        ReleaseMaterializerStep(
            name="runtime_dependency_evidence",
            command=("scripts/materialize_runtime_dependency_evidence.py",),
        ),
        ReleaseMaterializerStep(
            name="deploy_context",
            command=("scripts/materialize_deploy_context.py",),
        ),
        ReleaseMaterializerStep(
            name="release_manifest",
            command=("scripts/materialize_release_manifest.py",),
        ),
        ReleaseMaterializerStep(
            name="release_authority_status",
            command=("scripts/materialize_release_authority_status.py",),
        ),
    )


def _run_python(*, python_bin: str, step: ReleaseMaterializerStep) -> None:
    env = os.environ.copy()
    if step.extra_env:
        env.update(step.extra_env)
    subprocess.run(
        [python_bin, *step.command],
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
    )


def materialize_release_assets(*, python_bin: str = "python3") -> None:
    for step in _steps():
        _run_python(python_bin=python_bin, step=step)
