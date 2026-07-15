from __future__ import annotations

import json
from pathlib import Path
import re

from app.container import AppContainer
from app.product.commercial import workspace_plan_for_mode
from app.services.operator_access import (
    first_operator_access_profile,
)

_OPERATOR_BOOTSTRAP_SLUG_RE = re.compile(r"[^a-z0-9]+")


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
    operators = container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=25)
    selected = first_operator_access_profile(operators)
    if selected is None:
        return ""
    return str(selected.operator_id or "").strip()


def operator_bootstrap_needed(container: AppContainer, *, principal_id: str) -> bool:
    operators = container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=25)
    return first_operator_access_profile(operators) is None


def operator_bootstrap_defaults(*, principal_id: str, access_email: str = "") -> dict[str, str]:
    email_hint = str(access_email or _principal_email_hint(principal_id)).strip().lower()
    operator_id = (
        str(principal_id or "").strip()
        if email_hint and _principal_email_hint(principal_id) == email_hint
        else _operator_id_from_email(email_hint) if email_hint else _operator_id_from_principal(principal_id)
    )
    display_name = _display_name_from_email(email_hint) if email_hint else "Workspace Operator"
    return {
        "email_hint": email_hint,
        "operator_id": operator_id,
        "display_name": display_name,
    }


def bootstrap_initial_operator_profile(
    container: AppContainer,
    *,
    principal_id: str,
    access_email: str = "",
    operator_id: str = "",
    display_name: str = "",
    notes: str = "",
):
    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal:
        raise ValueError("principal_id_required")
    defaults = operator_bootstrap_defaults(principal_id=normalized_principal, access_email=access_email)
    resolved_operator_id = str(operator_id or defaults["operator_id"]).strip()
    resolved_display_name = str(display_name or defaults["display_name"]).strip()
    if not resolved_operator_id:
        raise ValueError("operator_id_required")
    if not resolved_display_name:
        raise ValueError("display_name_required")
    status = container.onboarding.status(principal_id=normalized_principal)
    workspace = dict(status.get("workspace") or {})
    plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
    if plan.entitlements.operator_seats < 1:
        raise ValueError("operator_seat_limit_reached")
    email_hint = str(defaults.get("email_hint") or "").strip()
    default_notes = "Bootstrapped the first operator profile for this workspace."
    if email_hint:
        default_notes = f"{default_notes} Email hint: {email_hint}."
    profile = container.orchestrator.bootstrap_operator_profile(
        principal_id=normalized_principal,
        operator_id=resolved_operator_id,
        display_name=resolved_display_name,
        roles=("operator", "reviewer"),
        trust_tier="standard",
        status="active",
        notes=str(notes or default_notes).strip() or default_notes,
    )
    if profile is None:
        raise ValueError("operator_profile_bootstrap_not_allowed")
    return profile


def _principal_email_hint(principal_id: str) -> str:
    normalized = str(principal_id or "").strip()
    if normalized.startswith("cf-email:"):
        candidate = normalized.partition(":")[2].strip().lower()
        if "@" in candidate:
            return candidate
    return ""


def _display_name_from_email(value: str) -> str:
    normalized = str(value or "").strip().lower()
    local = normalized.split("@", 1)[0] if "@" in normalized else normalized
    parts = [part for part in re.split(r"[._+-]+", local) if part]
    label = " ".join(part[:1].upper() + part[1:] for part in parts)
    return label or "Workspace Operator"


def _operator_id_from_email(value: str) -> str:
    normalized = str(value or "").strip().lower()
    local = normalized.split("@", 1)[0] if "@" in normalized else normalized
    slug = _OPERATOR_BOOTSTRAP_SLUG_RE.sub("-", local).strip("-")
    return f"operator-{slug or 'workspace'}"


def _operator_id_from_principal(value: str) -> str:
    normalized = str(value or "").strip().lower().replace(":", "-")
    slug = _OPERATOR_BOOTSTRAP_SLUG_RE.sub("-", normalized).strip("-")
    return f"operator-{slug or 'workspace'}"


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
