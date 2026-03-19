from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.memory_runtime import MemoryRuntimeService


@dataclass(frozen=True)
class CognitiveLoadState:
    principal_id: str
    state: str
    messages_last_15m: int
    observed_at: str
    interruption_budget_state: str


class CognitiveLoadService:
    def __init__(
        self,
        *,
        count_recent_for_principal,
        memory_runtime: MemoryRuntimeService,
        focus_message_threshold: int = 10,
        recovery_minutes: int = 5,
    ) -> None:
        self._count_recent_for_principal = count_recent_for_principal
        self._memory_runtime = memory_runtime
        self._focus_message_threshold = max(1, int(focus_message_threshold or 10))
        self._recovery_minutes = max(1, int(recovery_minutes or 5))

    def refresh_for_principal(
        self,
        principal_id: str,
        *,
        scope: str = "default",
        now: datetime | None = None,
    ) -> CognitiveLoadState:
        resolved_principal = str(principal_id or "").strip()
        observed_at = now or datetime.now(timezone.utc)
        since = (observed_at - timedelta(minutes=15)).isoformat()
        count = int(self._count_recent_for_principal(resolved_principal, since=since) or 0)
        if count > self._focus_message_threshold:
            budget = self._memory_runtime.exhaust_interruption_budget(
                principal_id=resolved_principal,
                scope=scope,
                notes="high_velocity_focus",
            )
            state = "high_velocity_focus"
        else:
            budget = self._memory_runtime.restore_interruption_budget_gradually(
                principal_id=resolved_principal,
                scope=scope,
                recovery_minutes=self._recovery_minutes,
                notes="focus_budget_restored",
            )
            state = "normal"
        budget_state = "exhausted" if int(budget.used_minutes or 0) >= int(budget.budget_minutes or 0) else "available"
        return CognitiveLoadState(
            principal_id=resolved_principal,
            state=state,
            messages_last_15m=count,
            observed_at=observed_at.isoformat(),
            interruption_budget_state=budget_state,
        )
