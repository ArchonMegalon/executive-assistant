from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.api.routes import landing as shared
from app.api.routes import landing_deps as deps

router = APIRouter(tags=["landing-property"])


@router.get("/app/research/{candidate_ref}", response_class=HTMLResponse)
def property_research_packet(
    candidate_ref: str,
    request: deps.Request,
    container: deps.AppContainer = Depends(deps.get_container),
    context: deps.RequestContext = Depends(deps.get_request_context),
    run_id: str = Query(default=""),
    investment: int = Query(default=0),
) -> HTMLResponse:
    return shared.property_research_packet(
        candidate_ref=candidate_ref,
        request=request,
        container=container,
        context=context,
        run_id=run_id,
        investment=investment,
    )
