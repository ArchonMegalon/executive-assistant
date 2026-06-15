from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_container
from app.container import AppContainer

router = APIRouter(tags=["system"])


def _memorial_healthcheck_slug() -> str:
    return str(os.getenv("EA_HEALTHCHECK_MEMORIAL_SLUG") or "").strip()


def _probe_public_memorial_surface(slug: str) -> dict[str, object]:
    from app.api.routes.public_memorial_surface_support import _public_memorial_surface_probe

    started = time.perf_counter()
    probe = _public_memorial_surface_probe(slug)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not str(probe.get("person_name") or "").strip():
        raise HTTPException(status_code=503, detail="not_live:memorial_surface_probe_incomplete")
    return {
        "slug": slug,
        "voice_plugin": str(probe.get("voice_plugin") or ""),
        "audio_clip_count": int(probe.get("audio_clip_count") or 0),
        "elapsed_ms": round(elapsed_ms, 1),
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return await health()


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    slug = _memorial_healthcheck_slug()
    if not slug:
        return {"status": "live"}
    probe = _probe_public_memorial_surface(slug)
    return {
        "status": "live",
        "memorial_slug": str(probe["slug"]),
        "memorial_voice_plugin": str(probe["voice_plugin"]),
        "memorial_audio_clip_count": str(probe["audio_clip_count"]),
        "memorial_elapsed_ms": str(probe["elapsed_ms"]),
    }


@router.get("/health/ready")
async def health_ready(container: AppContainer = Depends(get_container)) -> dict[str, str]:
    ready, reason = container.readiness.check()
    if not ready:
        raise HTTPException(status_code=503, detail=f"not_ready:{reason}")
    return {"status": "ready", "reason": reason}


@router.get("/version")
async def version(container: AppContainer = Depends(get_container)) -> dict[str, str]:
    return {
        "app_name": container.settings.app_name,
        "version": container.settings.app_version,
        "role": container.settings.role,
        "storage_backend": container.settings.storage_backend,
    }
