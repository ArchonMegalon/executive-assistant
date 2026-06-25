from __future__ import annotations

import concurrent.futures
import html
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

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
    _public_voice_profile_summary,
    build_memorial_voice_profile,
    load_memorial_voice_profile,
    unmixr_clone_request,
    UNMIXR_TTS_PLUGIN_ID,
    _TTS_MAX_CLONE_FILES,
)
from app.api.routes import public_memorials as shared_memorials


router = APIRouter(tags=["public-memorial-operator"])

_PRIVATE_JSON_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}
_PRIVATE_HTML_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "X-Robots-Tag": "noindex, nofollow",
}
_PUBLIC_MEMORIAL_OPERATOR_MAX_BODY_BYTES = 96_000
_PUBLIC_MEMORIAL_OPERATOR_RATE_BUCKET = "operator_route_write"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_RELEASE_AUTHORITY_STATUS_PATH = _REPO_ROOT / ".codex-studio" / "published" / "release_authority_status.generated.json"
_RELEASE_MANIFEST_PATH = _REPO_ROOT / ".codex-studio" / "published" / "release_manifest.generated.json"
_MEMORIAL_ROUTE_PROBE_TIMEOUT_SECONDS = 3.0


def _enforce_operator_mutation_limits(
    request: Request,
    *,
    bucket: str,
    body: dict[str, object] | None = None,
) -> None:
    content_length = shared_memorials._content_length_or_zero(request)
    if content_length > _PUBLIC_MEMORIAL_OPERATOR_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request_payload_too_large")
    context = _extract_personal_memory_request_context(request=request, body=body or {})
    shared_memorials._enforce_public_memorial_rate_limit(bucket, request=request, context=context)


def _private_json_response(content: dict[str, object], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content, headers=_PRIVATE_JSON_HEADERS, status_code=status_code)


def _private_error_response(status_code: int, detail: str) -> JSONResponse:
    return _public_memorial_error_response(status_code, _text(detail, "request_failed"))


def _private_html_error_response(status_code: int, detail: str) -> HTMLResponse:
    safe_detail = html.escape(_text(detail, "request_failed"), quote=True)
    return HTMLResponse(
        (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Memorial operator access required</title>"
            "<style>"
            ":root{color-scheme:light;--ink:#251c17;--ink-soft:#5f5146;--line:rgba(73,56,41,.15);--paper:rgba(255,251,246,.96);"
            "--shadow:0 24px 60px rgba(68,49,31,.12);--accent:#8e6847;}"
            "*{box-sizing:border-box;}body{margin:0;min-height:100vh;font-family:\"Avenir Next\",\"Segoe UI\",\"Helvetica Neue\",sans-serif;"
            "color:var(--ink);background:linear-gradient(180deg,#f7efe7 0%,#eee1d4 52%,#f8f2eb 100%);display:flex;align-items:center;justify-content:center;padding:24px;}"
            "main{width:min(760px,100%);background:var(--paper);border:1px solid var(--line);border-radius:28px;padding:32px 30px;box-shadow:var(--shadow);}"
            "h1{margin:0 0 14px;font-family:\"Iowan Old Style\",\"Palatino Linotype\",Georgia,serif;font-size:clamp(2rem,5vw,3rem);line-height:1.04;}"
            "p{margin:0 0 12px;line-height:1.6;color:var(--ink-soft);}strong{color:var(--ink);}code{display:inline-block;padding:2px 7px;border-radius:999px;background:rgba(75,58,43,.08);color:var(--ink);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em;}"
            ".kicker{display:inline-block;margin-bottom:14px;font-size:.82rem;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);}"
            "</style></head><body><main><div class=\"kicker\">Memorial Operator</div><h1>Memorial operator access required</h1>"
            "<p>This private memorial review surface is available only with operator access.</p>"
            f"<p>Detail: <code>{safe_detail}</code></p>"
            "<p>Verify that operator surfaces are enabled and that you are using the current write token before retrying.</p>"
            "</main></body></html>"
        ),
        status_code=status_code,
        headers=dict(_PRIVATE_HTML_HEADERS),
    )


def _fallback_operator_gold_status(*, slug: str, detail: str) -> dict[str, object]:
    message = _text(detail, "memorial_operator_status_unavailable")
    return {
        "current_label": "Memorial operator status unavailable",
        "status": "blocked",
        "public_voice_receipt": "unknown",
        "public_browser_receipt": "unknown",
        "public_browser_meaningful_receipt": "unknown",
        "room_audio_receipt": "unknown",
        "whole_project_gold": "unknown",
        "workflow_backing": {"status": "unknown"},
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
        "source_dirty_omitted_count": 0,
        "source_dirty_status_sha256": "",
        "source_dirty_summary": {
            "status": "unknown",
            "total_count": 0,
            "visible_count": 0,
            "omitted_count": 0,
            "category_count": 0,
            "categories": [],
            "operator_hint": "Status artifact unavailable; materialize operator status before source cleanup.",
        },
        "source_dirty_verifier": {
            "contract_name": "ea.source_dirty_groups_verifier.v1",
            "status": "missing",
            "issues": ["operator_status_artifact_missing"],
            "source_dirty_status": "unknown",
            "source_dirty_count": 0,
            "category_count": 0,
        },
        "source_cleanup": {
            "status": "missing",
            "source_worktree_dirty": False,
            "source_dirty_count": 0,
            "source_dirty_omitted_count": 0,
            "source_dirty_status_sha256": "",
            "summary_status": "unknown",
            "category_count": 0,
            "top_categories": [],
            "category_drilldown_commands": [],
            "handoff_commands": [
                "make materialize-memorial-operator-status",
            ],
            "verifier_status": "missing",
            "verifier_issues": ["operator_status_artifact_missing"],
            "next_action": "materialize_memorial_operator_status",
            "next_command": "make materialize-memorial-operator-status",
        },
        "memorial_public_gold_next_action": "materialize_memorial_operator_status",
        "memorial_public_gold_next_command": "make materialize-memorial-operator-status",
        "spoken_conversation_stt": {
            "status": "blocked",
            "production_provider": "",
            "top_candidate_provider": "",
            "ground_truth_fixture_mode": "",
            "next_action": "make materialize-memorial-operator-status",
            "scoring": {
                "production_eligible_rule": "",
                "redacted_text_fields": True,
            },
        },
        "spoken_conversation_tts": {
            "status": "blocked",
            "premium_status": "blocked",
            "next_action": "make materialize-memorial-operator-status",
        },
        "room_audio_attestation_packet": {
            "status": "unknown",
            "receipt_path": "",
            "operator_command": "make materialize-memorial-operator-status",
            "receipt_command_template": "",
            "required_check_ids": [],
            "required_cli_flags": [],
            "required_env_keys": [],
            "required_env": {},
            "operator_steps": [],
        },
        "room_audio_receipt_detail": {
            "status": "unknown",
            "receipt_path": "",
            "next_action": "make materialize-memorial-operator-status",
            "missing_checks": [],
            "missing_check_ids": [],
            "missing_input_hints": [],
            "failed_codes": [],
        },
        "public_voice_receipt_semantics": {
            "label": "Memorial public voice provenance proof",
            "transcriber_mode": "",
        },
        "readiness": {"current_head": ""},
        "evidence_heads": {
            "whole_project_map": "",
            "public_voice_receipt": "",
            "public_browser_receipt": "",
            "public_meaningful_browser_receipt": "",
            "room_audio_receipt": "",
        },
        "route_probe": {
            "configured_public_origin": "",
            "public_origin_source": "",
            "local_runtime": {"url": "", "status_code": 0, "status": "unknown", "detail": ""},
            "public_origin_runtime": {"url": "", "status_code": 0, "status": "unknown", "detail": ""},
            "next_action": "materialize_release_authority_and_probe_memorial_origin",
        },
        "operator_notes": [
            f"Status artifact unavailable for {slug}.",
            f"Detail: {message}",
            "Run make materialize-memorial-operator-status and refresh this page.",
        ],
    }


def _operator_actions() -> dict[str, str]:
    return {
        "refresh_operator_status": "make materialize-memorial-operator-status",
        "refresh_phrase_bank": "make materialize-memorial-phrase-bank",
        "refresh_public_auto_receipts_clean": "make materialize-memorial-public-auto-receipts-clean",
        "prepare_room_audio_attestation_packet": "make materialize-memorial-room-audio-attestation-packet",
        "record_room_audio_proof_clean": "make materialize-memorial-room-audio-gold-clean",
    }


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _release_public_origin_record() -> tuple[str, str]:
    for path in (_RELEASE_AUTHORITY_STATUS_PATH, _RELEASE_MANIFEST_PATH):
        payload = _read_json(path)
        public_origin = _text(payload.get("public_origin"), "").strip()
        public_origin_source = _text(payload.get("public_origin_source"), "").strip()
        if public_origin:
            return public_origin.rstrip("/"), public_origin_source
    return "", ""


def _probe_url(url: str, *, timeout_seconds: float = 5.0) -> dict[str, object]:
    if not str(url or "").strip():
        return {"url": "", "status_code": 0, "status": "missing", "detail": "url_missing"}
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200) or 200)
            body = response.read(160).decode("utf-8", errors="replace")
            return {
                "url": url,
                "status_code": status_code,
                "status": "pass" if status_code == 200 else "blocked",
                "detail": body[:160],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(160).decode("utf-8", errors="replace")
        return {
            "url": url,
            "status_code": int(exc.code or 0),
            "status": "blocked",
            "detail": body[:160],
        }
    except Exception as exc:
        return {
            "url": url,
            "status_code": 0,
            "status": "blocked",
            "detail": f"{type(exc).__name__}:{exc}"[:160],
        }


def _probe_urls(urls: list[str], *, timeout_seconds: float = 5.0) -> dict[str, dict[str, object]]:
    candidates = [str(url or "").strip() for url in urls]
    candidates = [url for url in candidates if url]
    if not candidates:
        return {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(candidates)))
    futures = {
        executor.submit(_probe_url, url, timeout_seconds=timeout_seconds): url for url in candidates
    }
    results: dict[str, dict[str, object]] = {}
    try:
        completed, _pending = concurrent.futures.wait(
            set(futures.keys()), timeout=timeout_seconds, return_when=concurrent.futures.ALL_COMPLETED
        )
        for future in completed:
            url = futures[future]
            try:
                result = future.result(timeout=0)
            except Exception as exc:  # pragma: no cover - extreme executor failure path
                result = {
                    "url": url,
                    "status_code": 0,
                    "status": "blocked",
                    "detail": f"{type(exc).__name__}:{exc}"[:160],
                }
            results[url] = result
        for future, url in futures.items():
            if url not in results:
                results[url] = {
                    "url": url,
                    "status_code": 0,
                    "status": "timeout",
                    "detail": "probe_timeout",
                }
        return results
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)


def _route_probe_next_action(*, local_probe: dict[str, object], public_probe: dict[str, object], public_origin: str) -> str:
    public_detail = str(public_probe.get("detail") or "").lower()
    public_status_code = int(public_probe.get("status_code") or 0)
    local_status_code = int(local_probe.get("status_code") or 0)
    if not public_origin:
        return "materialize_release_authority_and_record_memorial_public_origin"
    if public_status_code == 403 and "1010" in public_detail:
        return "allow_memorial_route_through_edge_firewall"
    if public_status_code == 404:
        return "publish_memorial_route_to_public_origin"
    if local_status_code == 404:
        return "enable_memorial_project_mode_in_runtime"
    if str(public_probe.get("status")) == "pass" and str(local_probe.get("status")) == "pass":
        return "public_memorial_route_reachable"
    return "inspect_memorial_route_probe_failures"


def _memorial_route_probe(slug: str) -> dict[str, object]:
    public_origin, public_origin_source = _release_public_origin_record()
    local_port = str(os.getenv("EA_PORT") or "8090").strip() or "8090"
    local_url = f"http://127.0.0.1:{local_port}/memorials/{_safe_slug(slug)}"
    public_url = f"{public_origin}/memorials/{_safe_slug(slug)}" if public_origin else ""
    probe_targets = [local_url]
    if public_url:
        probe_targets.append(public_url)
    probe_results = _probe_urls(probe_targets, timeout_seconds=_MEMORIAL_ROUTE_PROBE_TIMEOUT_SECONDS)
    local_probe = probe_results.get(local_url) or _probe_url(local_url)
    public_probe = (
        probe_results.get(public_url)
        if public_url
        else {"url": "", "status_code": 0, "status": "missing", "detail": "public_origin_missing"}
    )
    return {
        "configured_public_origin": public_origin,
        "public_origin_source": public_origin_source,
        "local_runtime": local_probe,
        "public_origin_runtime": public_probe,
        "next_action": _route_probe_next_action(local_probe=local_probe, public_probe=public_probe, public_origin=public_origin),
    }


def _runtime_readiness_probe_failed_payload(*, slug: str, exc: Exception) -> dict[str, object]:
    return {
        "slug": _safe_slug(slug),
        "status": "degraded",
        "interaction_mode": "unavailable",
        "surface_ready": False,
        "spoken_voice_ready": False,
        "realtime_ready": False,
        "ready": False,
        "readiness_checked_at": 0.0,
        "readiness_expires_at": 0.0,
        "readiness_ttl_remaining_seconds": 0.0,
        "readiness_ttl_state": "not_ready",
        "readiness_refresh_recommended": False,
        "degraded_reasons": ["runtime_readiness_probe_failed"],
        "next_actions": ["inspect_memorial_runtime_readiness"],
        "operator_attention_recommended": True,
        "operator_action_required": True,
        "detail": str(exc)[:200],
        "warmup": {
            "status": "unknown",
            "warm": False,
            "inflight": False,
            "completed_at": 0.0,
            "expires_at": 0.0,
            "ttl_remaining_seconds": 0.0,
            "started_at": 0.0,
            "errors": [],
            "voice_ready": False,
            "voice_inflight": False,
            "voice_started_at": 0.0,
            "voice_age_seconds": 0.0,
            "voice_prewarm_stale": False,
            "voice_completed_at": 0.0,
            "voice_duration_seconds": 0.0,
            "voice_completed_age_seconds": 0.0,
            "voice_expires_at": 0.0,
            "voice_ttl_remaining_seconds": 0.0,
            "voice_errors": [],
            "voice_required": False,
            "voice_recovery": {
                "attempted": False,
                "scheduled": False,
                "reason": "",
                "at": 0.0,
                "age_seconds": 0.0,
            },
        },
        "surface_probe": {},
        "voice": {
            "tts_plugin": "",
            "tts_plugin_enabled": False,
            "voice_profile_ready": False,
        },
        "models": {
            "conversation_model": "",
            "realtime_backend": "",
        },
        "operator_write_configured": False,
    }


def _enrich_operator_status_payload(
    *,
    slug: str,
    payload: dict[str, object],
    status_path,
    phrase_bank_path,
) -> dict[str, object]:
    response_payload = dict(payload)
    response_payload["slug"] = _safe_slug(slug)
    response_payload["status_artifact"] = status_path.name
    response_payload["phrase_bank_artifact"] = phrase_bank_path.name
    if _operator_debug_paths_enabled():
        response_payload["status_path"] = str(status_path)
        response_payload["phrase_bank_path"] = str(phrase_bank_path)
    try:
        response_payload["readiness"] = shared_memorials._memorial_runtime_readiness(slug)
    except Exception as exc:
        response_payload["readiness"] = _runtime_readiness_probe_failed_payload(slug=slug, exc=exc)
    response_payload["route_probe"] = _memorial_route_probe(slug)
    response_payload["actions"] = _operator_actions()
    return response_payload


def _operator_debug_paths_enabled() -> bool:
    return str(os.getenv("EA_PUBLIC_MEMORIAL_OPERATOR_DEBUG_PATHS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@router.get("/memorials/{slug}/operator-status")
def public_memorial_operator_status(slug: str, request: Request) -> JSONResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        status_path = _memorial_operator_status_path()
        phrase_bank_path = _memorial_phrase_bank_path()
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception as exc:
            response_payload = _enrich_operator_status_payload(
                slug=slug,
                payload=_fallback_operator_gold_status(slug=slug, detail="memorial_operator_status_unavailable"),
                status_path=status_path,
                phrase_bank_path=phrase_bank_path,
            )
            return _private_json_response(response_payload, status_code=503)
        if not isinstance(payload, dict):
            response_payload = _enrich_operator_status_payload(
                slug=slug,
                payload=_fallback_operator_gold_status(slug=slug, detail="memorial_operator_status_unavailable"),
                status_path=status_path,
                phrase_bank_path=phrase_bank_path,
            )
            return _private_json_response(response_payload, status_code=503)
        response_payload = _enrich_operator_status_payload(
            slug=slug,
            payload=payload,
            status_path=status_path,
            phrase_bank_path=phrase_bank_path,
        )
        return _private_json_response(response_payload)
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.get("/admin/memorials/{slug}/gold", response_class=HTMLResponse)
def public_memorial_operator_gold_page(slug: str, request: Request) -> HTMLResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        status_path = _memorial_operator_status_path()
        phrase_bank_path = _memorial_phrase_bank_path()
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            payload = _fallback_operator_gold_status(slug=slug, detail="memorial_operator_status_unavailable")
        if not isinstance(payload, dict):
            payload = _fallback_operator_gold_status(slug=slug, detail="memorial_operator_status_unavailable")
        payload = _enrich_operator_status_payload(
            slug=slug,
            payload=payload,
            status_path=status_path,
            phrase_bank_path=phrase_bank_path,
        )
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
        for header_name, header_value in _PRIVATE_HTML_HEADERS.items():
            response.headers[header_name] = header_value
        return response
    except HTTPException as exc:
        return _private_html_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.get("/memorials/{slug}/voice-config")
def public_memorial_voice_config(slug: str, request: Request) -> JSONResponse:
    try:
        memorial = _load_memorial(slug)
        if _public_memorial_operator_surfaces_enabled():
            _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        return _private_json_response(_public_voice_config_payload(slug, _load_voice_config(slug)))
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.get("/memorials/{slug}/voice-ab")
async def public_memorial_voice_ab(slug: str, request: Request) -> JSONResponse:
    try:
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
        return _private_json_response(
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
            },
        )
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.post("/memorials/{slug}/voice-ab/rate")
async def public_memorial_voice_ab_rate(slug: str, request: Request) -> JSONResponse:
    try:
        _load_memorial(slug)
        body = await request.json()
    except HTTPException:
        return _private_error_response(400, "invalid_json")
    try:
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        _enforce_operator_mutation_limits(request, bucket=_PUBLIC_MEMORIAL_OPERATOR_RATE_BUCKET, body=body)
        context = _extract_personal_memory_request_context(request=request, body=body)
        choice = _text(body.get("choice"), "").lower()
        approved_variant = _text(body.get("approved_variant"), "").lower()
        if approved_variant and not bool(context.get("personal_memory_enabled")):
            return _private_error_response(400, "personal_memory_required_for_voice_approval")
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
        return _private_json_response(
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
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.post("/memorials/{slug}/voice-ab-admin/finalize")
async def public_memorial_voice_ab_admin_finalize(slug: str, request: Request) -> JSONResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid_json") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        _enforce_operator_mutation_limits(request, bucket=_PUBLIC_MEMORIAL_OPERATOR_RATE_BUCKET, body=body)
        ratings = _voice_ab_finalize_winner(slug, winner=_text(body.get("winner_variant"), ""))
        return _private_json_response(
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
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.get("/memorials/{slug}/voice-ab-admin")
async def public_memorial_voice_ab_admin(slug: str, request: Request) -> JSONResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        ratings = _load_voice_ab_ratings(slug)
        pool = _load_voice_ab_pool(slug)
        return _private_json_response(
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
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.post("/memorials/{slug}/voice-ab-admin/maintain")
async def public_memorial_voice_ab_admin_maintain(slug: str, request: Request) -> JSONResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        _enforce_operator_mutation_limits(request, bucket=_PUBLIC_MEMORIAL_OPERATOR_RATE_BUCKET)
        maintenance = _voice_ab_maintain_pool(slug)
        ratings = _load_voice_ab_ratings(slug)
        return _private_json_response(
            {
                "status": "ok",
                "round": int(ratings.get("round", 1) or 1),
                "pool": maintenance.get("pool", {}),
                "retired_voices": maintenance.get("retired_voices", []),
                "built_challenger": maintenance.get("built_challenger", {}),
                "analysis": _voice_ab_analysis(slug, ratings),
            }
        )
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.post("/memorials/{slug}/voice-config")
async def public_memorial_voice_config_update(slug: str, request: Request) -> JSONResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        payload = await request.json()
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))
    except Exception as exc:
        return _private_error_response(400, "invalid_json")
    try:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        _enforce_operator_mutation_limits(request, bucket=_PUBLIC_MEMORIAL_OPERATOR_RATE_BUCKET, body=payload)
        _save_voice_config_payload(slug=slug, payload=payload)
        return _private_json_response(_load_voice_config(slug))
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.get("/memorials/{slug}/voice-profile")
def public_memorial_voice_profile(slug: str, request: Request) -> JSONResponse:
    try:
        memorial = _load_memorial(slug)
        summary = _public_voice_profile_summary(slug)
        if _public_memorial_operator_surfaces_enabled() and not bool(summary.get("voice_profile_ready")):
            _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        return _private_json_response(_public_voice_profile_payload(summary))
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.post("/memorials/{slug}/voice-profile/build")
async def public_memorial_voice_profile_build(slug: str, request: Request) -> JSONResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        _require_voice_consent(_payload_with_slug(slug, memorial), "profile_build")
        payload = await request.json()
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))
    except Exception as exc:
        return _private_error_response(400, "invalid_json")
    try:
        if not isinstance(payload, dict):
            payload = {}
        youtube_urls, youtube_query, youtube_limit = _normalize_voice_build_payload(payload)
        _enforce_operator_mutation_limits(request, bucket=_PUBLIC_MEMORIAL_OPERATOR_RATE_BUCKET, body=payload)
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
        return _private_json_response(_public_voice_profile_summary(slug))
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))


@router.post("/memorials/{slug}/voice-clone")
async def public_memorial_voice_clone(slug: str, request: Request) -> JSONResponse:
    try:
        _require_public_memorial_operator_surface_enabled()
        memorial = _load_memorial(slug)
        _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
        _require_voice_consent(_payload_with_slug(slug, memorial), "clone")
        body = await request.json()
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))
    except Exception:
        return _private_error_response(400, "invalid_json")
    try:
        if not isinstance(body, dict):
            body = {}
        _enforce_operator_mutation_limits(request, bucket=_PUBLIC_MEMORIAL_OPERATOR_RATE_BUCKET, body=body)
        memory_person_name = _text(memorial.get("person_name"), "Memorial")
        requested_plugin = UNMIXR_TTS_PLUGIN_ID
        voice_label = _text(
            body.get("voice_label"),
            _text(body.get("label"), f"{memory_person_name} Unmixr"),
        )
        sample_paths = _profile_clip_assets_for_memorial(slug=slug)
        if not sample_paths:
            raise HTTPException(status_code=400, detail="voice_profile_no_samples")
        cloned_voice_id = unmixr_clone_request(
            slug=slug,
            voice_label=voice_label,
            sample_paths=sample_paths[:_TTS_MAX_CLONE_FILES],
        )
        _save_voice_config_payload(
            slug=slug,
            payload={
                "tts_plugin": requested_plugin,
                "tts_plugin_voice_id": cloned_voice_id,
            },
        )
        return _private_json_response(_load_voice_config(slug))
    except HTTPException as exc:
        return _private_error_response(exc.status_code, _text(exc.detail, "request_failed"))
