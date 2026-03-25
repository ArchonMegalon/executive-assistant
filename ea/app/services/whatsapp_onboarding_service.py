from __future__ import annotations

from app.services.tool_runtime import ToolRuntimeService

WHATSAPP_BUSINESS_CONNECTOR = "whatsapp_business"
WHATSAPP_EXPORT_CONNECTOR = "whatsapp_export"


class WhatsAppEmbeddedSignupService:
    def __init__(self, tool_runtime: ToolRuntimeService) -> None:
        self._tool_runtime = tool_runtime

    def start_business_onboarding(self, principal_id: str, phone_number: str, business_name: str, import_history_now: bool):
        external_ref = str(phone_number or "").strip() or principal_id
        return self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=WHATSAPP_BUSINESS_CONNECTOR,
            external_account_ref=external_ref,
            scope_json={"import_history_now": bool(import_history_now)},
            auth_metadata_json={
                "business_name": str(business_name or "").strip(),
                "status": "planned_business",
            },
            status="planned",
        )


class WhatsAppHistoryImportService:
    def __init__(self, tool_runtime: ToolRuntimeService) -> None:
        self._tool_runtime = tool_runtime

    def plan_export_ingest(self, principal_id: str, export_label: str, selected_chat_labels: tuple[str, ...], include_media: bool):
        external_ref = str(export_label or "").strip() or principal_id
        chats = tuple(str(v).strip() for v in selected_chat_labels if str(v).strip())
        return self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=WHATSAPP_EXPORT_CONNECTOR,
            external_account_ref=external_ref,
            scope_json={"selected_chat_labels": list(chats), "include_media": bool(include_media)},
            auth_metadata_json={"status": "export_planned"},
            status="planned",
        )


class ChatExportIngestionService:
    def __init__(self, tool_runtime: ToolRuntimeService) -> None:
        self._tool_runtime = tool_runtime

    def ack_import(self, principal_id: str, binding_id: str, imported_message_count: int, status: str):
        for binding in self._tool_runtime.list_connector_bindings(principal_id=principal_id, limit=200):
            if binding.connector_name != WHATSAPP_EXPORT_CONNECTOR:
                continue
            if binding.binding_id == binding_id:
                return self._tool_runtime.set_connector_binding_status(
                    binding_id=binding.binding_id,
                    status=str(status or "imported").strip(),
                )
        return None
