from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_container
from app.container import AppContainer

router = APIRouter(tags=["system"])


def _memorial_healthcheck_slug() -> str:
    return str(os.getenv("EA_HEALTHCHECK_MEMORIAL_SLUG") or "").strip()


def _probe_public_memorial_html(slug: str) -> dict[str, object]:
    from app.api.routes import public_memorials

    started = time.perf_counter()
    payload = public_memorials._load_memorial(slug)
    private_profile = public_memorials._load_private_profile(slug)
    html = public_memorials._memorial_html(payload, private_profile=private_profile, hostname="127.0.0.1")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if len(str(html or "")) < 1000:
        raise HTTPException(status_code=503, detail="not_live:memorial_html_too_small")
    return {
        "slug": slug,
        "html_bytes": len(html),
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
    probe = _probe_public_memorial_html(slug)
    return {
        "status": "live",
        "memorial_slug": str(probe["slug"]),
        "memorial_html_bytes": str(probe["html_bytes"]),
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
