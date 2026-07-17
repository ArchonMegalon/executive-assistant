from __future__ import annotations

import subprocess
from pathlib import Path

from app.services import release_materialization_service
from scripts import verify_generated_release_artifacts_clean


ROOT = Path(__file__).resolve().parents[1]


def test_release_materialization_service_runs_expected_scripts_in_order(monkeypatch) -> None:
    calls: list[tuple[str, str, tuple[str, ...], dict[str, str] | None]] = []

    def fake_run_python(*, python_bin: str, step: release_materialization_service.ReleaseMaterializerStep) -> None:
        calls.append((python_bin, step.name, step.command, step.extra_env))

    monkeypatch.setattr(release_materialization_service, "_run_python", fake_run_python)

    release_materialization_service.materialize_release_assets(python_bin="/tmp/python")

    assert calls[0] == ("/tmp/python", "ea_browser_workflow_proof", ("scripts/materialize_ea_browser_workflow_proof.py",), None)
    assert calls[-1] == ("/tmp/python", "memorial_operator_status", ("scripts/materialize_memorial_operator_status.py",), None)
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
        name == "mymedia_alexa_readiness"
        and command == ("scripts/materialize_mymedia_alexa_readiness.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "whatsapp_web_action_processor_readiness"
        and command == ("scripts/materialize_whatsapp_web_action_processor_readiness.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "proactive_ooda_operator_status"
        and command == ("scripts/materialize_proactive_ooda_operator_status.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "proactive_ooda_gold_acceptance"
        and command == ("scripts/materialize_proactive_ooda_gold_acceptance.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "deploy_context"
        and command == ("scripts/materialize_deploy_context.py",)
        and env is None
        for _, name, command, env in calls
    )
    names = [name for _, name, _, _ in calls]
    assert names.index("memorial_spatial_tour_public_origin") < names.index("project_mode_manifests")
    assert names.index("memorial_spatial_tour_public_origin") < names.index("whole_project_gold_map")
    assert names.index("project_mode_manifests") < names.index("whole_project_gold_map")
    assert names.index("whole_project_gold_map") < names.index("memorial_operator_status")
    assert names.index("telegram_video_delivery_receipt") < names.index("telegram_video_delivery_live_receipt")
    assert names.index("telegram_video_delivery_live_receipt") < names.index("whole_project_gold_map")
    assert names.index("ea_provider_contract_receipts") < names.index("whole_project_gold_map")
    assert names.index("teable_env_recovery_readiness") < names.index("mymedia_alexa_readiness")
    assert names.index("mymedia_alexa_readiness") < names.index("whatsapp_web_action_processor_readiness")
    assert names.index("whatsapp_web_action_processor_readiness") < names.index("proactive_ooda_operator_status")
    assert names.index("proactive_ooda_operator_status") < names.index("proactive_ooda_gold_acceptance")
    assert names.index("proactive_ooda_gold_acceptance") < names.index("continuous_improvement_goal_posture")
    assert names.index("mymedia_alexa_readiness") < names.index("continuous_improvement_goal_posture")
    assert names.index("whatsapp_web_action_processor_readiness") < names.index("continuous_improvement_goal_posture")
    assert names.index("memorial_stt_provider_benchmark") < names.index("memorial_operator_status")
    assert names.index("continuous_improvement_goal_posture") < names.index("deploy_context")
    assert names.index("runtime_dependency_evidence") < names.index("deploy_context")
    assert names.index("deploy_context") < names.index("release_manifest")
    assert names.index("release_manifest") < names.index("release_authority_status")
    assert names.index("release_authority_status") < names.index("ea_flagship_release_gate")
    assert names.index("ea_flagship_release_gate") < names.index("weekly_product_pulse")
    assert names.index("weekly_product_pulse") < names.index("whole_project_gold_map")
    assert names.index("whole_project_gold_map") < names.index("memorial_operator_status")


def test_materialize_release_bundle_help_resolves_service_import() -> None:
    result = subprocess.run(
        ["python3", "scripts/materialize_release_bundle.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Materialize the full EA release-truth bundle in one orchestrated pass." in result.stdout


def test_generated_clean_verifier_preserves_release_materializer_order() -> None:
    release_commands = [step.command for step in release_materialization_service._steps()]
    verifier_commands = list(verify_generated_release_artifacts_clean.MATERIALIZER_COMMANDS)

    assert len(verifier_commands) == len(set(verifier_commands))
    assert verifier_commands == [
        command for command in release_commands if command in verifier_commands
    ]
    assert (
        Path(
            ".codex-studio/published/"
            "memorial_spatial_tour_public_origin.generated.json"
        )
        in verify_generated_release_artifacts_clean.GENERATED_ARTIFACTS
    )
