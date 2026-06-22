from __future__ import annotations

import subprocess
from pathlib import Path

from app.services import release_materialization_service


ROOT = Path(__file__).resolve().parents[1]


def test_release_materialization_service_runs_expected_scripts_in_order(monkeypatch) -> None:
    calls: list[tuple[str, str, tuple[str, ...], dict[str, str] | None]] = []

    def fake_run_python(*, python_bin: str, step: release_materialization_service.ReleaseMaterializerStep) -> None:
        calls.append((python_bin, step.name, step.command, step.extra_env))

    monkeypatch.setattr(release_materialization_service, "_run_python", fake_run_python)

    release_materialization_service.materialize_release_assets(python_bin="/tmp/python")

    assert calls[0] == ("/tmp/python", "ea_browser_workflow_proof", ("scripts/materialize_ea_browser_workflow_proof.py",), None)
    assert calls[-1] == ("/tmp/python", "release_manifest", ("scripts/materialize_release_manifest.py",), None)
    assert any(
        name == "whole_project_gold_map" and command == ("scripts/materialize_whole_project_gold_map.py",) and env == {"PYTHONPATH": "ea"}
        for _, name, command, env in calls
    )
    assert any(
        name == "ea_provider_contract_receipts"
        and command == ("scripts/materialize_ea_provider_contract_receipts.py",)
        and env == {"PYTHONPATH": "ea"}
        for _, name, command, env in calls
    )
    assert any(
        name == "memorial_stt_provider_benchmark"
        and command == ("scripts/benchmark_memorial_stt_providers.py",)
        and env == {"PYTHONPATH": "ea"}
        for _, name, command, env in calls
    )
    assert any(
        name == "continuous_improvement_goal_posture"
        and command == ("scripts/materialize_continuous_improvement_goal_posture.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "teable_env_recovery_readiness"
        and command == ("scripts/materialize_teable_env_recovery_readiness.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "whatsapp_web_action_processor_readiness"
        and command == ("scripts/materialize_whatsapp_web_action_processor_readiness.py",)
        and env is None
        for _, name, command, env in calls
    )
    names = [name for _, name, _, _ in calls]
    assert names.index("telegram_video_delivery_receipt") < names.index("telegram_video_delivery_live_receipt")
    assert names.index("telegram_video_delivery_live_receipt") < names.index("whole_project_gold_map")
    assert names.index("ea_provider_contract_receipts") < names.index("whole_project_gold_map")
    assert names.index("whole_project_gold_map") < names.index("teable_env_recovery_readiness")
    assert names.index("teable_env_recovery_readiness") < names.index("whatsapp_web_action_processor_readiness")
    assert names.index("whatsapp_web_action_processor_readiness") < names.index("continuous_improvement_goal_posture")
    assert names.index("whole_project_gold_map") < names.index("continuous_improvement_goal_posture")
    assert names.index("memorial_stt_provider_benchmark") < names.index("memorial_operator_status")
    assert names.index("memorial_operator_status") < names.index("runtime_dependency_evidence")
    assert names.index("runtime_dependency_evidence") < names.index("release_manifest")


def test_materialize_release_bundle_help_resolves_service_import() -> None:
    result = subprocess.run(
        ["python3", "scripts/materialize_release_bundle.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Materialize the full EA release-truth bundle in one orchestrated pass." in result.stdout
