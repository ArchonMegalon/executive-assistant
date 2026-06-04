from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, require_operator_context, resolve_principal_id
from app.container import AppContainer
from app.services.memorial_memory import ingest_memorial_mail_archive, memorial_memory_principal_id

router = APIRouter(tags=['memory'])


class MemorialMailImportIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    memorial_slug: str = Field(min_length=1, max_length=80)
    source_path: str = Field(min_length=1, max_length=4000)
    mailbox_format: str = Field(default='auto', max_length=20)
    source_label: str = Field(default='', max_length=400)
    reviewer: str = Field(default='memorial-mail-import', max_length=200)
    sensitivity: str = Field(default='private', max_length=40)
    max_messages: int = Field(default=5000, ge=1, le=50000)


class MemorialMailImportOut(BaseModel):
    memorial_slug: str
    principal_id: str
    source_path: str
    mailbox_format: str
    imported: int
    skipped: int
    processed_total: int
    new_message_keys: list[str]


@router.post('/memorial-mail-import', response_model=MemorialMailImportOut, dependencies=[Depends(require_operator_context)])
def import_memorial_mail_archive(
    body: MemorialMailImportIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> MemorialMailImportOut:
    requested_principal = body.principal_id or memorial_memory_principal_id(body.memorial_slug)
    principal_id = resolve_principal_id(requested_principal, context) if body.principal_id else requested_principal
    try:
        result = ingest_memorial_mail_archive(
            memory_runtime=container.memory_runtime,
            principal_id=principal_id,
            memorial_slug=body.memorial_slug,
            source_path=body.source_path,
            mailbox_format=body.mailbox_format,
            reviewer=body.reviewer,
            source_label=body.source_label,
            sensitivity=body.sensitivity,
            max_messages=body.max_messages,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or 'mail_source_missing') from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or 'invalid_mail_import_request') from exc
    return MemorialMailImportOut(**result)
