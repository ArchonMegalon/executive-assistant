from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, require_operator_context
from app.container import AppContainer
from app.services.memorial_memory import memorial_memory_principal_id, seed_memorial_source_memories
from app.api.routes.public_memorials import _load_memorial, _load_private_profile

router = APIRouter(tags=['memory'])


class MemorialSeedIn(BaseModel):
    memorial_slug: str = Field(min_length=1, max_length=80)
    reviewer: str = Field(default='memorial-source-seed', max_length=200)


class MemorialSeedOut(BaseModel):
    memorial_slug: str
    principal_id: str
    created: int
    created_keys: list[str]
    processed_total: int


@router.post('/memorial-seed', response_model=MemorialSeedOut, dependencies=[Depends(require_operator_context)])
def seed_memorial_memory(
    body: MemorialSeedIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> MemorialSeedOut:
    memorial = _load_memorial(body.memorial_slug)
    private_profile = _load_private_profile(body.memorial_slug)
    principal_id = memorial_memory_principal_id(body.memorial_slug, memorial)
    if not principal_id:
        raise HTTPException(status_code=400, detail='memorial_principal_missing')
    result = seed_memorial_source_memories(
        memory_runtime=container.memory_runtime,
        principal_id=principal_id,
        memorial_slug=body.memorial_slug,
        memorial_payload=memorial,
        private_profile=private_profile,
        reviewer=body.reviewer,
    )
    return MemorialSeedOut(**result)
