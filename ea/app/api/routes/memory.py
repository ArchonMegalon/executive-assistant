from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.memory_candidates import router as memory_candidates_router
from app.api.routes.memory_governance import router as memory_governance_router
from app.api.routes.memory_graph import router as memory_graph_router
from app.api.routes.memory_operations import router as memory_operations_router
from app.api.routes.memory_reasoning import router as memory_reasoning_router

router = APIRouter(prefix="/v1/memory", tags=["memory"])
router.include_router(memory_candidates_router)
router.include_router(memory_graph_router)
router.include_router(memory_operations_router)
router.include_router(memory_governance_router)
router.include_router(memory_reasoning_router)
