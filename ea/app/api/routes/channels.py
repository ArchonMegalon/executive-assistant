from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import get_container, require_operator_context
from app.channels.telegram.adapter import TelegramObservationAdapter
from app.container import AppContainer
from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR, TELEGRAM_OFFICIAL_BOT_CONNECTOR

router = APIRouter(prefix="/v1/channels", tags=["channels"], dependencies=[Depends(require_operator_context)])
_telegram = TelegramObservationAdapter()


def _resolve_telegram_principal(container: AppContainer, chat_id: str) -> str:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return ""
    matches: list[str] = []
    for connector_name in (TELEGRAM_OFFICIAL_BOT_CONNECTOR, TELEGRAM_IDENTITY_CONNECTOR):
        for binding in container.tool_runtime.list_connector_bindings_for_connector(connector_name, limit=500):
            normalized_status = str(binding.status or "").strip().lower()
            if normalized_status in {"disabled", "inactive", "archived"}:
                continue
            metadata = dict(binding.auth_metadata_json or {})
            default_chat_ref = str(metadata.get("default_chat_ref") or "").strip()
            external_account_ref = str(binding.external_account_ref or "").strip()
            if normalized_chat_id in {default_chat_ref, external_account_ref}:
                matches.append(binding.principal_id)
    principals = sorted({principal_id for principal_id in matches if str(principal_id or "").strip()})
    if len(principals) == 1:
        return principals[0]
    if len(principals) > 1:
        raise HTTPException(status_code=409, detail="telegram_binding_ambiguous")
    return ""


class TelegramUpdateIn(BaseModel):
    update: dict[str, object] = Field(default_factory=dict)


class TelegramIngestOut(BaseModel):
    observation_id: str
    principal_id: str
    channel: str
    event_type: str
    created_at: str


@router.post("/telegram/ingest")
def ingest_telegram(
    body: TelegramUpdateIn,
    container: AppContainer = Depends(get_container),
) -> TelegramIngestOut:
    fields = _telegram.to_observation_fields(body.update)
    chat_id = str(fields.get("chat_id") or "").strip()
    principal_id = _resolve_telegram_principal(container, chat_id)
    if not principal_id:
        raise HTTPException(status_code=404, detail="telegram_binding_not_found")
    event = container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel=_telegram.channel,
        event_type=str(fields.get("event_type") or "telegram.update"),
        payload=dict(fields.get("payload") or {}),
        source_id=str(fields.get("source_id") or ""),
        external_id=str(fields.get("external_id") or ""),
        dedupe_key=str(fields.get("dedupe_key") or ""),
    )
    return TelegramIngestOut(
        observation_id=event.observation_id,
        principal_id=event.principal_id,
        channel=event.channel,
        event_type=event.event_type,
        created_at=event.created_at,
    )
