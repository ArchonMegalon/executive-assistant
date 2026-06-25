from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.api.errors import install_error_handlers
from app.services.openvoice_runtime import get_openvoice_runtime, load_openvoice_service_config


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _clean_text(value: object, *, max_len: int, field_name: str = "text") -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field_name}_missing")
    if len(text) > max_len:
        raise HTTPException(status_code=413, detail=f"{field_name}_too_long")
    return text


def _clean_token(value: object, *, field_name: str, max_len: int = 120) -> str:
    token = str(value or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail=f"{field_name}_missing")
    if len(token) > max_len:
        raise HTTPException(status_code=413, detail=f"{field_name}_too_long")
    return token


def _runtime_error(detail: BaseException) -> HTTPException:
    message = str(detail or type(detail).__name__).strip() or "openvoice_runtime_failed"
    if isinstance(detail, ValueError):
        return HTTPException(status_code=400, detail=message)
    if message in {"voice_id_not_found"}:
        return HTTPException(status_code=404, detail=message)
    if message.startswith(("openvoice_python_missing", "openvoice_checkpoint_missing", "piper_not_configured")):
        return HTTPException(status_code=503, detail=message)
    if message.startswith(("voice_profile_samples_unusable", "voice_id_invalid")):
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=502, detail=message)


def _audio_response(audio: bytes) -> Response:
    if not audio:
        raise HTTPException(status_code=502, detail="openvoice_empty_audio")
    return Response(content=audio, media_type="audio/wav")


def _max_tts_text_len() -> int:
    return _env_int("OPENVOICE_MAX_TTS_TEXT_LEN", 3000, minimum=1, maximum=20_000)


def _max_clone_files() -> int:
    return _env_int("OPENVOICE_MAX_CLONE_FILES", 4, minimum=1, maximum=20)


def _max_upload_bytes() -> int:
    return _env_int("OPENVOICE_MAX_UPLOAD_BYTES", 20 * 1024 * 1024, minimum=1024, maximum=200 * 1024 * 1024)


def _max_total_upload_bytes() -> int:
    return _env_int(
        "OPENVOICE_MAX_TOTAL_UPLOAD_BYTES",
        48 * 1024 * 1024,
        minimum=1024,
        maximum=400 * 1024 * 1024,
    )


class SynthesizeBaseRequest(BaseModel):
    text: str
    lang: str = "de"
    base_voice_variant: str = "default"


class SynthesizeRequest(SynthesizeBaseRequest):
    voice_id: str


async def _read_clone_files(files: list[object]) -> list[tuple[str, bytes]]:
    if not files:
        raise HTTPException(status_code=400, detail="clone_files_missing")
    if len(files) > _max_clone_files():
        raise HTTPException(status_code=413, detail="too_many_clone_files")
    max_file_bytes = _max_upload_bytes()
    max_total_bytes = _max_total_upload_bytes()
    total_bytes = 0
    source_files: list[tuple[str, bytes]] = []
    for index, upload in enumerate(files, start=1):
        read = getattr(upload, "read", None)
        if not callable(read):
            raise HTTPException(status_code=400, detail=f"clone_file_invalid:{index}")
        try:
            payload = await read()
        finally:
            close = getattr(upload, "close", None)
            if callable(close):
                await close()
        if not payload:
            raise HTTPException(status_code=400, detail=f"clone_file_empty:{index}")
        if len(payload) > max_file_bytes:
            raise HTTPException(status_code=413, detail=f"clone_file_too_large:{index}")
        total_bytes += len(payload)
        if total_bytes > max_total_bytes:
            raise HTTPException(status_code=413, detail="clone_upload_too_large")
        filename = str(getattr(upload, "filename", "") or f"sample-{index}.bin").strip() or f"sample-{index}.bin"
        source_files.append((filename, payload))
    return source_files


def _ready_payload() -> tuple[int, dict[str, Any]]:
    return (
        200,
        {
            "status": "ready",
            "service": "openvoice",
            "role": "stt_only_policy_enforced",
            "tts_allowed": False,
            "clone_allowed": False,
            "tts_disabled_reason": "openvoice_tts_disabled_by_policy",
            "errors": [],
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(title="EA OpenVoice", version="1.0", docs_url=None, redoc_url=None)
    install_error_handlers(app)

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "live", "service": "openvoice"}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        status_code, payload = _ready_payload()
        return JSONResponse(status_code=status_code, content=payload)

    @app.post("/synthesize-base")
    async def synthesize_base(payload: SynthesizeBaseRequest) -> Response:
        raise HTTPException(status_code=403, detail="openvoice_tts_disabled_by_policy")

    @app.post("/synthesize")
    async def synthesize(payload: SynthesizeRequest) -> Response:
        raise HTTPException(status_code=403, detail="openvoice_tts_disabled_by_policy")

    @app.post("/clone")
    async def clone_voice(request: Request) -> dict[str, object]:
        raise HTTPException(status_code=403, detail="openvoice_tts_disabled_by_policy")

    return app


app = create_app()
