from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.routes import public_memorials as shared_memorials
from app.api.routes.public_memorial_operator_support import (
    _extract_personal_memory_request_context,
    _load_memorial,
    _public_memorial_error_response,
    _require_public_memorial_operator_surface_enabled,
    _require_public_memorial_write_access,
    _safe_slug,
)
from app.services.memorial_family_contributions import (
    MemorialContributionError,
    approve_family_contribution,
    approve_family_contribution_public_proposal,
    build_family_contribution_recovery_receipt,
    correct_family_contribution,
    get_family_contribution_for_management,
    get_family_contribution_status,
    list_family_contributions_for_operator,
    propose_family_contribution_public_version,
    reject_family_contribution,
    reject_family_contribution_public_proposal,
    request_family_contribution_erasure,
    submit_family_contribution,
    unpublish_family_contribution,
    withdraw_family_contribution,
)


router = APIRouter(tags=["public-memorial-contributions"])

_MAX_CONTRIBUTION_BODY_BYTES = 16_384
_PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}


def _private_response(content: dict[str, object], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=content, status_code=status_code, headers=dict(_PRIVATE_HEADERS))


def _error_status(code: str) -> int:
    if code in {"memorial_not_found", "memorial_contribution_not_found"}:
        return 404
    if code == "memorial_contribution_unauthorized":
        return 403
    if code in {
        "memorial_contribution_not_reviewable",
        "memorial_contribution_not_rejectable",
        "memorial_contribution_not_unpublishable",
        "memorial_contribution_publication_consent_required",
        "memorial_contribution_store_full",
        "memorial_contribution_history_full",
        "memorial_contribution_withdrawn",
        "memorial_contribution_not_proposable",
        "memorial_contribution_proposal_missing",
        "memorial_contribution_proposal_stale",
        "memorial_contribution_proposal_not_decidable",
        "memorial_contribution_proposal_not_approved",
        "memorial_contribution_proposal_payload_mismatch",
        "memorial_contribution_erasure_pending",
    }:
        return 409
    if code in {
        "memorial_contribution_path_invalid",
        "memorial_contribution_store_invalid",
        "memorial_contribution_store_unavailable",
    }:
        return 503
    return 400


def _contribution_error(exc: MemorialContributionError) -> JSONResponse:
    return _public_memorial_error_response(_error_status(exc.code), exc.code)


async def _read_bounded_json(request: Request) -> dict[str, object]:
    media_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="memorial_contribution_json_required")
    content_length = shared_memorials._content_length_or_zero(request)
    if content_length > _MAX_CONTRIBUTION_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request_payload_too_large")
    raw = await request.body()
    if len(raw) > _MAX_CONTRIBUTION_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request_payload_too_large")
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    return payload


def _enforce_rate_limit(request: Request, *, bucket: str, body: dict[str, object] | None = None) -> None:
    context = _extract_personal_memory_request_context(request=request, body=body or {})
    shared_memorials._enforce_public_memorial_rate_limit(bucket, request=request, context=context)


def _require_operator(slug: str, request: Request) -> dict[str, object]:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    return memorial


@router.post("/memorials/{slug}/contributions", status_code=201)
async def submit_public_memorial_family_contribution(slug: str, request: Request) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _load_memorial(safe_slug)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="family_contribution_submit",
        )
        payload = await _read_bounded_json(request)
        record, manage_token = await run_in_threadpool(
            submit_family_contribution,
            slug=safe_slug,
            payload=payload,
        )
        recovery_receipt = build_family_contribution_recovery_receipt(
            slug=safe_slug,
            record=record,
            manage_token=manage_token,
        )
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": "pending_review",
                "visibility": "private",
                "submitted_at": str(record.get("submitted_at") or ""),
                "manage_token": manage_token,
                "manage_token_header": "x-memorial-contribution-token",
                "recovery_receipt": recovery_receipt,
            },
            status_code=201,
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(503, "memorial_contribution_store_unavailable")


@router.get("/memorials/{slug}/contributions/{contribution_id}/status")
def public_memorial_family_contribution_status(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _load_memorial(safe_slug)
        _enforce_rate_limit(request, bucket="family_contribution_manage")
        status = get_family_contribution_status(
            slug=safe_slug,
            contribution_id=contribution_id,
            manage_token=str(
                request.headers.get("x-memorial-contribution-token") or ""
            ),
        )
        return _private_response(status)
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(
            503, "memorial_contribution_store_unavailable"
        )


@router.get("/memorials/{slug}/contributions/{contribution_id}/manage")
def manage_public_memorial_family_contribution(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _load_memorial(safe_slug)
        _enforce_rate_limit(request, bucket="family_contribution_manage")
        management = get_family_contribution_for_management(
            slug=safe_slug,
            contribution_id=contribution_id,
            manage_token=str(
                request.headers.get("x-memorial-contribution-token") or ""
            ),
        )
        return _private_response(management)
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(
            503, "memorial_contribution_store_unavailable"
        )


@router.get("/memorials/{slug}/contributions/operator")
def review_public_memorial_family_contributions(slug: str, request: Request) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _require_operator(safe_slug, request)
        rows = list_family_contributions_for_operator(slug=safe_slug)
        return _private_response({"slug": safe_slug, "contributions": rows})
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(503, "memorial_contribution_store_unavailable")


@router.post("/memorials/{slug}/contributions/{contribution_id}/propose")
async def propose_public_memorial_family_contribution_version(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _require_operator(safe_slug, request)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="operator_route_write",
        )
        payload = await _read_bounded_json(request)
        record = await run_in_threadpool(
            propose_family_contribution_public_version,
            slug=safe_slug,
            contribution_id=contribution_id,
            payload=payload,
        )
        proposal = dict(record.get("public_proposal") or {})
        binding = dict(record.get("public_proposal_binding") or {})
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or ""),
                "public_proposal": {
                    "source_label": str(proposal.get("source_label") or ""),
                    "title": str(proposal.get("title") or ""),
                    "body": str(proposal.get("body") or ""),
                    "sha256": str(binding.get("sha256") or ""),
                    "proposed_at": str(binding.get("proposed_at") or ""),
                },
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(
            503, "memorial_contribution_store_unavailable"
        )


@router.post(
    "/memorials/{slug}/contributions/{contribution_id}/proposal/approve"
)
async def approve_public_memorial_family_contribution_proposal(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    return await _decide_public_memorial_family_contribution_proposal(
        slug=slug,
        contribution_id=contribution_id,
        request=request,
        decision="approved",
    )


@router.post(
    "/memorials/{slug}/contributions/{contribution_id}/proposal/reject"
)
async def reject_public_memorial_family_contribution_proposal(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    return await _decide_public_memorial_family_contribution_proposal(
        slug=slug,
        contribution_id=contribution_id,
        request=request,
        decision="rejected",
    )


async def _decide_public_memorial_family_contribution_proposal(
    *,
    slug: str,
    contribution_id: str,
    request: Request,
    decision: str,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _load_memorial(safe_slug)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="family_contribution_manage",
        )
        payload = await _read_bounded_json(request)
        decide = (
            approve_family_contribution_public_proposal
            if decision == "approved"
            else reject_family_contribution_public_proposal
        )
        record = await run_in_threadpool(
            decide,
            slug=safe_slug,
            contribution_id=contribution_id,
            manage_token=str(
                request.headers.get("x-memorial-contribution-token") or ""
            ),
            payload=payload,
        )
        binding = dict(record.get("public_proposal_binding") or {})
        stored_decision = dict(record.get("public_proposal_decision") or {})
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or ""),
                "proposal_sha256": str(binding.get("sha256") or ""),
                "decision": str(stored_decision.get("decision") or ""),
                "decided_at": str(stored_decision.get("decided_at") or ""),
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(
            503, "memorial_contribution_store_unavailable"
        )


@router.post("/memorials/{slug}/contributions/{contribution_id}/approve")
async def approve_public_memorial_family_contribution(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _require_operator(safe_slug, request)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="operator_route_write",
        )
        payload = await _read_bounded_json(request)
        record = await run_in_threadpool(
            approve_family_contribution,
            slug=safe_slug,
            contribution_id=contribution_id,
            payload=payload,
        )
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or ""),
                "published_at": str(record.get("published_at") or ""),
                "proposal_sha256": str(
                    dict(record.get("public_proposal_binding") or {}).get(
                        "sha256"
                    )
                    or ""
                ),
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(503, "memorial_contribution_store_unavailable")


@router.post("/memorials/{slug}/contributions/{contribution_id}/correct")
async def correct_public_memorial_family_contribution(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _load_memorial(safe_slug)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="family_contribution_manage",
        )
        payload = await _read_bounded_json(request)
        record = await run_in_threadpool(
            correct_family_contribution,
            slug=safe_slug,
            contribution_id=contribution_id,
            manage_token=str(request.headers.get("x-memorial-contribution-token") or ""),
            payload=payload,
        )
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or ""),
                "public_removed": True,
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(503, "memorial_contribution_store_unavailable")


@router.post("/memorials/{slug}/contributions/{contribution_id}/reject")
async def reject_public_memorial_family_contribution(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _require_operator(safe_slug, request)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="operator_route_write",
        )
        payload = await _read_bounded_json(request)
        record = await run_in_threadpool(
            reject_family_contribution,
            slug=safe_slug,
            contribution_id=contribution_id,
            payload=payload,
        )
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or ""),
                "rejected_at": str(record.get("rejected_at") or ""),
                "public_removed": True,
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(
            503, "memorial_contribution_store_unavailable"
        )


@router.post("/memorials/{slug}/contributions/{contribution_id}/unpublish")
async def unpublish_public_memorial_family_contribution(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _require_operator(safe_slug, request)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="operator_route_write",
        )
        payload = await _read_bounded_json(request)
        record = await run_in_threadpool(
            unpublish_family_contribution,
            slug=safe_slug,
            contribution_id=contribution_id,
            payload=payload,
        )
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or ""),
                "unpublished_at": str(record.get("unpublished_at") or ""),
                "public_removed": True,
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(
            503, "memorial_contribution_store_unavailable"
        )


@router.post("/memorials/{slug}/contributions/{contribution_id}/withdraw")
async def withdraw_public_memorial_family_contribution(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _load_memorial(safe_slug)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="family_contribution_manage",
        )
        payload = await _read_bounded_json(request)
        record = await run_in_threadpool(
            withdraw_family_contribution,
            slug=safe_slug,
            contribution_id=contribution_id,
            manage_token=str(request.headers.get("x-memorial-contribution-token") or ""),
            reason=payload.get("reason"),
        )
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or ""),
                "public_removed": True,
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(503, "memorial_contribution_store_unavailable")


@router.post(
    "/memorials/{slug}/contributions/{contribution_id}/erasure-request"
)
async def request_public_memorial_family_contribution_erasure(
    slug: str,
    contribution_id: str,
    request: Request,
) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        _load_memorial(safe_slug)
        await run_in_threadpool(
            _enforce_rate_limit,
            request,
            bucket="family_contribution_manage",
        )
        payload = await _read_bounded_json(request)
        record = await run_in_threadpool(
            request_family_contribution_erasure,
            slug=safe_slug,
            contribution_id=contribution_id,
            manage_token=str(
                request.headers.get("x-memorial-contribution-token") or ""
            ),
            confirmation=payload.get("confirm_permanent_erasure_request"),
            reason=payload.get("reason"),
        )
        erasure_request = dict(record.get("erasure_request") or {})
        return _private_response(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "status": str(record.get("status") or ""),
                "visibility": str(record.get("visibility") or "private"),
                "erasure_request": {
                    "state": str(erasure_request.get("state") or ""),
                    "requested_at": str(
                        erasure_request.get("requested_at") or ""
                    ),
                    "public_removed": erasure_request.get("public_removed")
                    is True,
                    "permanent_erasure_completed": erasure_request.get(
                        "permanent_erasure_completed"
                    )
                    is True,
                },
            }
        )
    except HTTPException as exc:
        return _public_memorial_error_response(exc.status_code, str(exc.detail))
    except MemorialContributionError as exc:
        return _contribution_error(exc)
    except OSError:
        return _public_memorial_error_response(
            503, "memorial_contribution_store_unavailable"
        )
