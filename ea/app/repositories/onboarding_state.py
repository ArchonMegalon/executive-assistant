from __future__ import annotations

import uuid
from typing import Dict, Protocol

from app.domain.models import OnboardingState, now_utc_iso


class OnboardingStateRepository(Protocol):
    def upsert_state(
        self,
        *,
        principal_id: str,
        onboarding_id: str | None = None,
        workspace_name: str = "",
        workspace_mode: str = "personal",
        region: str = "",
        language: str = "",
        timezone: str = "",
        selected_channels: tuple[str, ...] = (),
        privacy_preferences_json: dict[str, object] | None = None,
        channel_preferences_json: dict[str, object] | None = None,
        brief_preview_json: dict[str, object] | None = None,
        status: str = "draft",
    ) -> OnboardingState:
        ...

    def get_for_principal(self, principal_id: str) -> OnboardingState | None:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"draft", "started", "in_progress", "ready_for_brief", "completed"}:
        return raw
    return "draft"


class InMemoryOnboardingStateRepository:
    def __init__(self) -> None:
        self._rows_by_principal: Dict[str, OnboardingState] = {}

    def upsert_state(
        self,
        *,
        principal_id: str,
        onboarding_id: str | None = None,
        workspace_name: str = "",
        workspace_mode: str = "personal",
        region: str = "",
        language: str = "",
        timezone: str = "",
        selected_channels: tuple[str, ...] = (),
        privacy_preferences_json: dict[str, object] | None = None,
        channel_preferences_json: dict[str, object] | None = None,
        brief_preview_json: dict[str, object] | None = None,
        status: str = "draft",
    ) -> OnboardingState:
        principal = str(principal_id or "").strip()
        if not principal:
            raise ValueError("principal_id_required")
        now = now_utc_iso()
        existing = self._rows_by_principal.get(principal)
        row = OnboardingState(
            onboarding_id=str(onboarding_id or (existing.onboarding_id if existing else "")).strip() or str(uuid.uuid4()),
            principal_id=principal,
            workspace_name=str(
                workspace_name if workspace_name != "" else (existing.workspace_name if existing else "")
            ).strip(),
            workspace_mode=str(
                workspace_mode if workspace_mode != "" else (existing.workspace_mode if existing else "personal")
            ).strip()
            or "personal",
            region=str(region if region != "" else (existing.region if existing else "")).strip(),
            language=str(language if language != "" else (existing.language if existing else "")).strip(),
            timezone=str(timezone if timezone != "" else (existing.timezone if existing else "")).strip(),
            selected_channels=tuple(str(v).strip().lower() for v in selected_channels if str(v).strip())
            if selected_channels
            else (existing.selected_channels if existing else ()),
            privacy_preferences_json=dict(
                privacy_preferences_json
                if privacy_preferences_json is not None
                else (existing.privacy_preferences_json if existing else {})
            ),
            channel_preferences_json=dict(
                channel_preferences_json
                if channel_preferences_json is not None
                else (existing.channel_preferences_json if existing else {})
            ),
            brief_preview_json=dict(
                brief_preview_json if brief_preview_json is not None else (existing.brief_preview_json if existing else {})
            ),
            status=_normalize_status(status if status != "" else (existing.status if existing else "draft")),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._rows_by_principal[principal] = row
        return row

    def get_for_principal(self, principal_id: str) -> OnboardingState | None:
        return self._rows_by_principal.get(str(principal_id or "").strip())
