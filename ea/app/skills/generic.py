from __future__ import annotations

from typing import Any, Callable

from app.skills.capability_router import build_capability_plan


def build_generic_skill_handler(
    skill_key: str,
    capabilities: tuple[str, ...],
    *,
    planning_task_type: str | None = None,
) -> Callable[..., dict[str, Any]]:
    key = str(skill_key or "").strip().lower()
    caps = tuple(str(x or "").strip().lower() for x in capabilities if str(x or "").strip())
    task_type = str(planning_task_type or key).strip().lower()

    def _run_operation(
        *,
        operation: str,
        tenant: str,
        chat_id: int,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preferred = str((payload or {}).get("preferred_capability") or "").strip().lower() or None
        plan = build_capability_plan(task_type, preferred=preferred)
        return {
            "ok": False,
            "status": "not_implemented",
            "skill": key,
            "task_type": task_type,
            "operation": str(operation or "").strip().lower(),
            "tenant": str(tenant or ""),
            "chat_id": int(chat_id),
            "payload": dict(payload or {}),
            "capabilities": list(caps),
            "plan": plan,
            "message": "Skill contract exists but implementation is pending.",
        }

    return _run_operation


__all__ = ["build_generic_skill_handler"]
