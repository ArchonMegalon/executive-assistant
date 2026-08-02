from __future__ import annotations

from pathlib import Path

from app.api.routes import landing_console, workspace_view_models
from app.domain.office.surfaces import OfficeSurfacePayload
from app.services import office_surface_service, release_materialization_service
from app.services.office_surface_service import build_workspace_section_payload




def test_continuous_improvement_goal_keeps_scope_gap_audit_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "whole-project scope gap audit goal" in goal_text
    assert "build, run, remember, explain, publish" in goal_text
    assert "privacy/retention, telemetry/slos" in goal_text
    assert "owner-boundary pressure" in goal_text


def test_continuous_improvement_goal_keeps_acceptance_evidence_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "real-world executive assistant acceptance evidence goal" in goal_text
    assert "one real morning brief is accepted as worth reading" in goal_text
    assert "raw private context, actor identity, and object references stay out" in goal_text
    assert "partial evidence must reduce the remaining blocker list" in goal_text


def test_continuous_improvement_goal_keeps_paid_assistant_ooda_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "smart paid human assistant" in goal_text
    assert "paid-human-assistant-grade ooda loop" in goal_text
    assert "filled carts" in goal_text
    assert "inspect live sites" in goal_text
    assert "decision-ready packet the user can approve, dismiss, or defer in seconds" in goal_text
    assert "do not stop at a raw link dump" in goal_text
    assert "approval-ready handoff" in goal_text
    assert "staged link, approval state, delivery route, blockers, and follow-through receipt" in goal_text
    assert "resume later without repeating research" in goal_text
    assert "teable as an admin projection" in goal_text
    assert "pocket.ai or other consented audio transcript stream" in goal_text
    assert "audit before delivery" in goal_text
    assert "provider/category fit" in goal_text
    assert "1200 wien" in goal_text
    assert "gmail draft" in goal_text
    assert "telegram is an action surface, not a progress log" in goal_text
    assert "stale-approval cleanup" in goal_text


def test_continuous_improvement_goal_keeps_media_acceptance_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "whole-project media acceptance goal" in goal_text
    assert "epub audiobooks are not done when the m4b exists" in goal_text
    assert "voice auditions must keep replacing dismissed voices immediately" in goal_text
    assert "promo videos are not done when an mp4 exists" in goal_text
    assert "generated, delivered, listened, accepted, published, and human-reviewed" in goal_text




def test_office_surface_payload_roundtrip_preserves_core_contracts() -> None:
    payload = OfficeSurfacePayload.from_mapping(
        {
            "title": "Morning Memo",
            "summary": "What changed first.",
            "stats": [{"label": "Queue items", "value": "4"}],
            "cards": [
                {
                    "eyebrow": "Top priorities",
                    "title": "What deserves attention first",
                    "body": "Start on the ranked work.",
                    "items": [{"title": "Follow up", "detail": "Board chair", "tag": "Priority"}],
                }
            ],
            "console_form": {"kind": "capture"},
            "activation_banner": {"body": "Open Today first."},
        }
    )

    rendered = payload.as_template_payload()

    assert rendered["title"] == "Morning Memo"
    assert rendered["summary"] == "What changed first."
    assert rendered["stats"] == [{"label": "Queue items", "value": "4"}]
    assert rendered["cards"][0]["title"] == "What deserves attention first"
    assert rendered["console_form"] == {"kind": "capture"}
    assert rendered["activation_banner"] == {"body": "Open Today first."}




def test_workspace_view_models_resolve_office_sections_from_service_layer() -> None:
    assert workspace_view_models.workspace_section_payload is build_workspace_section_payload


def test_landing_console_routes_use_console_support_module() -> None:
    assert landing_console.app_shell.__module__ == "app.api.routes.landing_console"
    globals_map = getattr(landing_console.app_shell, "__globals__", {})
    support = globals_map.get("support")
    assert support is not None
    assert getattr(support, "__name__", "") == "app.api.routes.landing_console_support"
    assert "shared" not in globals_map






def test_office_surface_service_no_longer_depends_on_workspace_route_module() -> None:
    assert office_surface_service._row.__module__ == "app.services.office_surface_rows"


def test_release_materialization_service_runs_only_ea_owned_steps(monkeypatch) -> None:
    calls: list[tuple[str, str, tuple[str, ...], dict[str, str] | None]] = []

    def fake_run_python(*, python_bin: str, step: release_materialization_service.ReleaseMaterializerStep) -> None:
        calls.append((python_bin, step.name, step.command, step.extra_env))

    monkeypatch.setattr(release_materialization_service, "_run_python", fake_run_python)
    release_materialization_service.materialize_release_assets(python_bin="/tmp/python")

    names = [name for _, name, _, _ in calls]
    assert names[0] == "ea_browser_workflow_proof"
    assert names[-1] == "whole_project_gold_map"
    assert "ea_provider_contract_receipts" in names
    assert "runtime_dependency_evidence" in names
    assert names.index("release_manifest") < names.index("release_authority_status")
    assert names.index("weekly_product_pulse") < names.index("whole_project_gold_map")
    assert all("memorial" not in name.lower() for name in names)
    assert all("memorial" not in " ".join(command).lower() for _, _, command, _ in calls)
