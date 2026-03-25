from __future__ import annotations

from app.services.tool_runtime import ToolRuntimeService

TELEGRAM_IDENTITY_CONNECTOR = "telegram_identity"
TELEGRAM_OFFICIAL_BOT_CONNECTOR = "telegram_official_bot"


class TelegramIdentityService:
    def __init__(self, tool_runtime: ToolRuntimeService) -> None:
        self._tool_runtime = tool_runtime

    def stage_identity(
        self,
        principal_id: str,
        telegram_ref: str,
        identity_mode: str,
        history_mode: str,
        assistant_surfaces: tuple[str, ...],
    ):
        surfaces = tuple(sorted({str(v).strip().lower() for v in assistant_surfaces if str(v).strip()}))
        binding = self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=TELEGRAM_IDENTITY_CONNECTOR,
            external_account_ref=telegram_ref,
            scope_json={"assistant_surfaces": list(surfaces)},
            auth_metadata_json={
                "identity_mode": str(identity_mode or "login_widget").strip() or "login_widget",
                "history_mode": str(history_mode or "future_only").strip() or "future_only",
                "status": "guided_manual",
            },
            status="guided",
        )
        return binding


class TelegramBotOnboardingService:
    def __init__(self, tool_runtime: ToolRuntimeService) -> None:
        self._tool_runtime = tool_runtime

    def link_official_bot(self, principal_id: str, bot_handle: str, install_surfaces: tuple[str, ...], default_chat_ref: str):
        surfaces = tuple(sorted({str(v).strip().lower() for v in install_surfaces if str(v).strip()}))
        return self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=TELEGRAM_OFFICIAL_BOT_CONNECTOR,
            external_account_ref=bot_handle,
            scope_json={"install_surfaces": list(surfaces)},
            auth_metadata_json={
                "default_chat_ref": str(default_chat_ref or "").strip(),
                "status": "bot_link_requested",
            },
            status="planned",
        )
