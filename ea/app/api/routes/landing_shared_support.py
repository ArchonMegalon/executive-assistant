from __future__ import annotations

import json
from pathlib import Path

from app.container import AppContainer
from app.product.commercial import workspace_plan_for_mode


def _repo_root() -> Path:
    resolved = Path(__file__).resolve()
    for candidate in (resolved.parents[4], resolved.parents[3], Path("/app"), Path.cwd()):
        if (candidate / ".codex-design").exists() or (candidate / "PRODUCT_BOUNDARY.md").is_file():
            return candidate
    return resolved.parents[4]


def _load_project_mode_payloads() -> tuple[dict[str, object], dict[str, object]]:
    root = _repo_root()
    try:
        modes = json.loads((root / ".codex-design/product/PROJECT_MODES.generated.json").read_text(encoding="utf-8"))
    except Exception:
        modes = {"contract_name": "ea.project_modes", "modes": []}
    try:
        show = json.loads((root / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json").read_text(encoding="utf-8"))
    except Exception:
        show = {"contract_name": "ea.show_surface_manifest", "demo_mode": "ea_core"}
    return (dict(modes) if isinstance(modes, dict) else {"modes": []}, dict(show) if isinstance(show, dict) else {})


def _workspace_plan(container: AppContainer, *, principal_id: str):
    status = container.onboarding.status(principal_id=principal_id)
    workspace = dict(status.get("workspace") or {})
    return workspace_plan_for_mode(str(workspace.get("mode") or "personal"))


def _expected_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()


def _default_operator_id_for_browser(container: AppContainer, *, principal_id: str) -> str:
    operators = container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=1)
    if not operators:
        return ""
    return str(operators[0].operator_id or "").strip()


def _app_live_feed(container: AppContainer, *, principal_id: str) -> dict[str, object]:
    approvals = container.orchestrator.list_pending_approvals_for_principal(
        principal_id=principal_id,
        limit=6,
    )
    human_tasks = container.orchestrator.list_human_tasks(
        principal_id=principal_id,
        status="pending",
        limit=6,
    )
    pending_delivery = container.channel_runtime.list_pending_delivery(
        limit=6,
        principal_id=principal_id,
    )
    return {
        "approvals": approvals,
        "human_tasks": human_tasks,
        "pending_delivery": pending_delivery,
    }
