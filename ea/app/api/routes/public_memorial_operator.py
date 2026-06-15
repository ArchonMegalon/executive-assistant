from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.api.routes.landing_public_support import templates

from app.api.routes.public_memorial_operator_support import (
    _collect_memorial_public_audio_paths,
    _extract_personal_memory_request_context,
    _load_memorial,
    _load_personal_memory_store,
    _load_private_profile,
    _load_voice_ab_config,
    _load_voice_ab_pool,
    _load_voice_ab_ratings,
    _load_voice_config,
    _memorial_operator_status_path,
    _memorial_phrase_bank_path,
    _payload_with_slug,
    _personal_memory_public_status,
    _profile_clip_assets_for_memorial,
    _public_memorial_client_key,
    _public_memorial_error_response,
    _public_memorial_operator_surfaces_enabled,
    _public_voice_ab_variant_payload,
    _public_voice_config_payload,
    _public_voice_profile_payload,
    _public_voice_profile_summary,
    _record_voice_ab_rating,
    _require_public_memorial_operator_surface_enabled,
    _require_public_memorial_write_access,
    _require_voice_consent,
    _safe_slug,
    _safe_tts_plugin_id,
    _save_voice_config_payload,
    _text,
    _voice_ab_analysis,
    _voice_ab_dimension_spec,
    _voice_ab_finalize_options,
    _voice_ab_finalize_winner,
    _voice_ab_maintain_pool,
    _voice_ab_normalize_dimensions,
    _voice_ab_pool_status,
    _voice_ab_variant_choice,
    _normalize_voice_build_payload,
    _openvoice_clone_from_memorial,
    _public_voice_profile_summary,
    build_memorial_voice_profile,
    load_memorial_voice_profile,
    openvoice_clone_request,
    unmixr_clone_request,
    OPENVOICE_TTS_PLUGIN_ID,
    UNMIXR_TTS_PLUGIN_ID,
    _TTS_MAX_CLONE_FILES,
)


router = APIRouter(tags=["public-memorial-operator"])


@router.get("/memorials/{slug}/operator-status")
def public_memorial_operator_status(slug: str, request: Request) -> JSONResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    status_path = _memorial_operator_status_path()
    phrase_bank_path = _memorial_phrase_bank_path()
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="memorial_operator_status_unavailable") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail="memorial_operator_status_unavailable")
    response_payload = dict(payload)
    response_payload["slug"] = _safe_slug(slug)
    response_payload["status_path"] = str(status_path)
    response_payload["phrase_bank_path"] = str(phrase_bank_path)
    response_payload["actions"] = {
        "refresh_operator_status": "make materialize-memorial-operator-status",
        "refresh_phrase_bank": "make materialize-memorial-phrase-bank",
        "record_room_audio_proof_clean": "make materialize-memorial-room-audio-gold-clean",
    }
    return JSONResponse(response_payload, headers={"Cache-Control": "no-store"})


@router.get("/admin/memorials/{slug}/gold", response_class=HTMLResponse)
def public_memorial_operator_gold_page(slug: str, request: Request) -> HTMLResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    status_path = _memorial_operator_status_path()
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="memorial_operator_status_unavailable") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail="memorial_operator_status_unavailable")
    response = templates.TemplateResponse(
        request,
        "admin_memorial_gold.html",
        {
            "request": request,
            "slug": _safe_slug(slug),
            "memorial": memorial,
            "status_path": str(status_path),
            "operator_status": payload,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/memorials/{slug}/voice-config")
def public_memorial_voice_config(slug: str) -> JSONResponse:
    return JSONResponse(_public_voice_config_payload(slug, _load_voice_config(slug)))


@router.get("/memorials/{slug}/voice-ab")
async def public_memorial_voice_ab(slug: str, request: Request) -> JSONResponse:
    _load_memorial(slug)
    context = _extract_personal_memory_request_context(request=request)
    config = _load_voice_ab_config(slug)
    ratings = _load_voice_ab_ratings(slug)
    analysis = _voice_ab_analysis(slug, ratings)
    can_write = False
    try:
        _require_public_memorial_write_access(slug=slug, request=request)
        can_write = True
    except HTTPException:
        can_write = False
    return JSONResponse(
        {
            "variants": [_public_voice_ab_variant_payload(dict(item or {})) for item in list(config.get("variants") or [])],
            "sample_text": _text(config.get("sample_text"), "Rechtlich ist es so, dass man die Dinge sauber auseinanderhalten muss."),
            "dimension_spec": _voice_ab_dimension_spec(),
            "personal_memory": _personal_memory_public_status(slug=slug, context=context),
            "selected_variant": _text(_load_personal_memory_store(slug=slug, scope=_text(context.get("scope"), "")).get("approved_voice_choice"), "") if _text(context.get("scope"), "") else "",
            "totals": ratings.get("effective_totals", ratings.get("totals", {})),
            "raw_totals": ratings.get("totals", {}),
            "round": int(ratings.get("round", 1) or 1),
            "pool": _voice_ab_pool_status(slug),
            "analysis": analysis,
            "admin": {
                "can_write": can_write,
                "finalize": _voice_ab_finalize_options(ratings),
            },
        }
    )


@router.post("/memorials/{slug}/voice-ab/rate")
async def public_memorial_voice_ab_rate(slug: str, request: Request) -> JSONResponse:
    _load_memorial(slug)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    context = _extract_personal_memory_request_context(request=request, body=body)
    from app.api.routes.public_memorials import _enforce_public_memorial_rate_limit

    _enforce_public_memorial_rate_limit("voice_ab_rate", request=request, context=context)
    choice = _text(body.get("choice"), "").lower()
    approved_variant = _text(body.get("approved_variant"), "").lower()
    if approved_variant and not bool(context.get("personal_memory_enabled")):
        return _public_memorial_error_response(400, "personal_memory_required_for_voice_approval")
    ratings = _record_voice_ab_rating(
        slug=slug,
        context=context,
        choice=choice,
        approved_variant=approved_variant if approved_variant in {"a", "b"} else "",
        note=_text(body.get("note"), ""),
        dedupe_key=_public_memorial_client_key(request=request, context=context),
        dimensions=_voice_ab_normalize_dimensions(body.get("dimensions")),
    )
    analysis = _voice_ab_analysis(slug, ratings)
    can_write = False
    try:
        _require_public_memorial_write_access(slug=slug, request=request)
        can_write = True
    except HTTPException:
        can_write = False
    return JSONResponse(
        {
            "status": "ok",
            "totals": ratings.get("effective_totals", ratings.get("totals", {})),
            "raw_totals": ratings.get("totals", {}),
            "round": int(ratings.get("round", 1) or 1),
            "pool": _voice_ab_pool_status(slug),
            "personal_memory": _personal_memory_public_status(slug=slug, context=context),
            "analysis": analysis,
            "admin": {
                "can_write": can_write,
                "finalize": _voice_ab_finalize_options(ratings),
            },
        }
    )


@router.post("/memorials/{slug}/voice-ab-admin/finalize")
async def public_memorial_voice_ab_admin_finalize(slug: str, request: Request) -> JSONResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    ratings = _voice_ab_finalize_winner(slug, winner=_text(body.get("winner_variant"), ""))
    return JSONResponse(
        {
            "status": "ok",
            "round": int(ratings.get("round", 1) or 1),
            "totals": ratings.get("effective_totals", ratings.get("totals", {})),
            "raw_totals": ratings.get("totals", {}),
            "pool": _voice_ab_pool_status(slug),
            "analysis": _voice_ab_analysis(slug, ratings),
            "admin": {
                "can_write": True,
                "finalize": _voice_ab_finalize_options(ratings),
            },
        }
    )


@router.get("/memorials/{slug}/voice-ab-admin")
async def public_memorial_voice_ab_admin(slug: str, request: Request) -> JSONResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    ratings = _load_voice_ab_ratings(slug)
    pool = _load_voice_ab_pool(slug)
    return JSONResponse(
        {
            "round": int(ratings.get("round", 1) or 1),
            "totals": ratings.get("effective_totals", ratings.get("totals", {})),
            "raw_totals": ratings.get("totals", {}),
            "rounds": ratings.get("rounds", []),
            "pool": _voice_ab_pool_status(slug),
            "analysis": _voice_ab_analysis(slug, ratings),
            "pool_config": {
                "current_index": int(pool.get("current_index", 0) or 0),
                "challenger_count": len([item for item in pool.get("challengers", []) if isinstance(item, dict)]),
            },
        }
    )


@router.post("/memorials/{slug}/voice-ab-admin/maintain")
async def public_memorial_voice_ab_admin_maintain(slug: str, request: Request) -> JSONResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    maintenance = _voice_ab_maintain_pool(slug)
    ratings = _load_voice_ab_ratings(slug)
    return JSONResponse(
        {
            "status": "ok",
            "round": int(ratings.get("round", 1) or 1),
            "pool": maintenance.get("pool", {}),
            "retired_voices": maintenance.get("retired_voices", []),
            "built_challenger": maintenance.get("built_challenger", {}),
            "analysis": _voice_ab_analysis(slug, ratings),
        }
    )


@router.post("/memorials/{slug}/voice-config")
async def public_memorial_voice_config_update(slug: str, request: Request) -> JSONResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    _save_voice_config_payload(slug=slug, payload=payload)
    return JSONResponse(_load_voice_config(slug))


@router.get("/memorials/{slug}/voice-profile")
def public_memorial_voice_profile(slug: str) -> JSONResponse:
    _load_memorial(slug)
    return JSONResponse(_public_voice_profile_payload(_public_voice_profile_summary(slug)))


@router.post("/memorials/{slug}/voice-profile/build")
async def public_memorial_voice_profile_build(slug: str, request: Request) -> JSONResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    _require_voice_consent(_payload_with_slug(slug, memorial), "profile_build")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(payload, dict):
        payload = {}
    youtube_urls, youtube_query, youtube_limit = _normalize_voice_build_payload(payload)
    public_paths = _collect_memorial_public_audio_paths(memorial, slug)
    if not public_paths and not youtube_urls and not youtube_query:
        raise HTTPException(status_code=400, detail="voice_profile_no_source")
    try:
        build_memorial_voice_profile(
            slug=slug,
            public_audio_paths=public_paths,
            youtube_query=youtube_query,
            youtube_urls=youtube_urls,
            youtube_limit=youtube_limit,
        )
    except RuntimeError as exc:
        detail = str(exc)
        raise HTTPException(status_code=400, detail=detail) from exc
    return JSONResponse(_public_voice_profile_summary(slug))


@router.post("/memorials/{slug}/voice-clone")
async def public_memorial_voice_clone(slug: str, request: Request) -> JSONResponse:
    _require_public_memorial_operator_surface_enabled()
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    _require_voice_consent(_payload_with_slug(slug, memorial), "clone")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        body = {}
    memory_person_name = _text(memorial.get("person_name"), "Memorial")
    requested_plugin = _safe_tts_plugin_id(_text(body.get("tts_plugin"), _text(body.get("tts_mode"), UNMIXR_TTS_PLUGIN_ID)))
    voice_label = _text(
        body.get("voice_label"),
        _text(body.get("label"), f"{memory_person_name} {'Unmixr' if requested_plugin == UNMIXR_TTS_PLUGIN_ID else 'OpenVoice'}"),
    )
    if requested_plugin == UNMIXR_TTS_PLUGIN_ID:
        sample_paths = _profile_clip_assets_for_memorial(slug=slug)
        if not sample_paths:
            raise HTTPException(status_code=400, detail="voice_profile_no_samples")
        cloned_voice_id = unmixr_clone_request(
            slug=slug,
            voice_label=voice_label,
            sample_paths=sample_paths[:_TTS_MAX_CLONE_FILES],
        )
    else:
        requested_plugin = OPENVOICE_TTS_PLUGIN_ID
        cloned_voice_id = _openvoice_clone_from_memorial(slug=slug, voice_label=voice_label)
    _save_voice_config_payload(
        slug=slug,
        payload={
            "tts_plugin": requested_plugin,
            "tts_plugin_voice_id": cloned_voice_id,
        },
    )
    return JSONResponse(_load_voice_config(slug))
