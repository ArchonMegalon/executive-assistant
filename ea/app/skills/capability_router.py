from __future__ import annotations

from app.skills.capability_registry import capability_or_raise, capabilities_for_task


_TASK_PRIORITY: dict[str, tuple[str, ...]] = {
    "travel_rescue": ("oneair", "avomap", "browseract"),
    "collect_structured_intake": ("involve_me", "metasurvey", "apix_drive"),
    "guided_intake": ("involve_me", "metasurvey", "apix_drive"),
    "compile_prompt_pack": ("prompting_systems", "paperguide", "vizologi"),
    "polish_human_tone": ("undetectable",),
    "generate_multimodal_support_asset": ("one_min_ai", "ai_magicx", "peekshot"),
}


def build_capability_plan(task_type: str, preferred: str | None = None) -> dict[str, object]:
    task = str(task_type or "").strip().lower()
    if not task:
        return {"ok": False, "status": "missing_task_type"}

    candidates = list(capabilities_for_task(task))
    if not candidates:
        return {
            "ok": False,
            "status": "no_capability_for_task",
            "task_type": task,
            "primary": None,
            "fallbacks": [],
            "candidates": [],
        }

    pref = str(preferred or "").strip().lower()
    ranked = list(_TASK_PRIORITY.get(task, tuple(candidates)))
    for cap in candidates:
        if cap not in ranked:
            ranked.append(cap)
    if pref and pref in candidates:
        ranked = [pref] + [x for x in ranked if x != pref]

    primary = ranked[0]
    fallbacks = [x for x in ranked[1:] if x in candidates]
    cap = capability_or_raise(primary)
    return {
        "ok": True,
        "status": "planned",
        "task_type": task,
        "primary": cap.key,
        "primary_invocation_method": cap.invocation_method,
        "fallbacks": fallbacks,
        "candidates": candidates,
    }


__all__ = ["build_capability_plan"]
