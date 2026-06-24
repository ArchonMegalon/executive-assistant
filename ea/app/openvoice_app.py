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
    config = load_openvoice_service_config()
    base_tts_ready = True
    readiness_errors: list[str] = []
    if config.base_tts == "piper" and (not config.piper_bin or not config.piper_model):
        base_tts_ready = False
        readiness_errors.append("piper_not_configured")
    clone_ready = (config.converter_dir / "config.json").is_file() and (config.converter_dir / "checkpoint.pth").is_file()
    return (
        200 if base_tts_ready else 503,
        {
            "status": "ready" if base_tts_ready else "degraded",
            "service": "openvoice",
            "base_tts": config.base_tts,
            "base_tts_ready": base_tts_ready,
            "clone_ready": clone_ready,
            "base_voice_variants": get_openvoice_runtime().available_base_voice_variants(),
            "errors": readiness_errors,
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
        text = _clean_text(payload.text, max_len=_max_tts_text_len())
        lang = str(payload.lang or "de").strip() or "de"
        variant = str(payload.base_voice_variant or "default").strip() or "default"
        try:
            audio = get_openvoice_runtime().synthesize_base(
                text=text,
                lang=lang,
                base_voice_variant=variant,
            )
        except Exception as exc:
            raise _runtime_error(exc) from exc
        return _audio_response(audio)

    @app.post("/synthesize")
    async def synthesize(payload: SynthesizeRequest) -> Response:
        text = _clean_text(payload.text, max_len=_max_tts_text_len())
        voice_id = _clean_token(payload.voice_id, field_name="voice_id")
        lang = str(payload.lang or "de").strip() or "de"
        variant = str(payload.base_voice_variant or "default").strip() or "default"
        try:
            audio = get_openvoice_runtime().synthesize(
                voice_id=voice_id,
                text=text,
                lang=lang,
                base_voice_variant=variant,
            )
        except Exception as exc:
            raise _runtime_error(exc) from exc
        return _audio_response(audio)

    @app.post("/clone")
    async def clone_voice(request: Request) -> dict[str, object]:
        try:
            form = await request.form()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="multipart_parser_unavailable") from exc
        files = [value for key, value in form.multi_items() if str(key) == "files"]
        source_files = await _read_clone_files(files)
        slug = str(form.get("slug") or "")
        voice_label = str(form.get("voice_label") or "")
        voice_id = str(form.get("voice_id") or "")
        normalized_slug = _clean_token(slug or voice_id, field_name="slug", max_len=80)
        normalized_voice_id = _clean_token(voice_id or f"{normalized_slug}-openvoice", field_name="voice_id", max_len=120)
        normalized_label = str(voice_label or normalized_voice_id).strip()[:160] or normalized_voice_id
        try:
            manifest = get_openvoice_runtime().clone_voice(
                voice_id=normalized_voice_id,
                voice_label=normalized_label,
                source_files=source_files,
            )
        except Exception as exc:
            raise _runtime_error(exc) from exc
        return {
            "voice_id": str(manifest.get("voice_id") or normalized_voice_id),
            "voice_label": str(manifest.get("voice_label") or normalized_label),
            "sample_count": int(manifest.get("sample_count") or len(source_files)),
            "status": "ready",
        }

    return app


app = create_app()
