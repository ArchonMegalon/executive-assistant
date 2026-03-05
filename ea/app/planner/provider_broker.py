from __future__ import annotations

import json
import os
from typing import Any

from app.planner.provider_registry import provider_or_raise
from app.planner.task_registry import task_or_none


def _base_score(task_priority: tuple[str, ...], capability_key: str) -> int:
    key = str(capability_key or "").strip().lower()
    if not key:
        return -999
    if key in task_priority:
        return 100 - task_priority.index(key) * 10
    return 40


def _policy_adjustment(capability_key: str) -> int:
    cap = provider_or_raise(capability_key)
    bonus = 0
    if cap.blocking:
        bonus -= 10
    if cap.user_visible:
        bonus += 2
    if cap.invocation_method == "api":
        bonus += 1
    if cap.invocation_method == "webhook":
        bonus += 0
    return bonus


def _history_adjustment_map() -> dict[str, int]:
    raw = str(os.getenv("EA_PROVIDER_HISTORY_SCORE_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in payload.items():
        k = str(key or "").strip().lower()
        if not k:
            continue
        try:
            score = int(value)
        except Exception:
            continue
        out[k] = max(-100, min(100, score))
    return out


def rank_task_capabilities(
    *,
    task_type: str,
    candidates: list[str],
    preferred: str | None = None,
) -> list[dict[str, Any]]:
    task = str(task_type or "").strip().lower()
    pref = str(preferred or "").strip().lower()
    contract = task_or_none(task)
    task_priority = tuple(contract.provider_priority if contract else tuple())
    history_scores = _history_adjustment_map()
    out: list[dict[str, Any]] = []
    for cap_key in [str(x or "").strip().lower() for x in candidates if str(x or "").strip()]:
        score = _base_score(task_priority, cap_key) + _policy_adjustment(cap_key)
        reasons: list[str] = []
        if cap_key in task_priority:
            reasons.append("task_priority")
        else:
            reasons.append("task_fallback")
        if pref and cap_key == pref:
            score += 120
            reasons.append("preferred_override")
        history_bonus = int(history_scores.get(cap_key, 0))
        if history_bonus:
            score += history_bonus
            reasons.append(f"history_adjustment:{history_bonus:+d}")
        cap = provider_or_raise(cap_key)
        reasons.append(f"budget:{cap.budget_policy}")
        reasons.append(f"fallback:{cap.fallback_policy}")
        out.append(
            {
                "capability": cap.key,
                "score": int(score),
                "reasons": reasons,
            }
        )
    out.sort(key=lambda row: (int(row.get("score") or 0), str(row.get("capability") or "")), reverse=True)
    return out


__all__ = ["rank_task_capabilities"]
