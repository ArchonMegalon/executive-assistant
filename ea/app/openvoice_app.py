from __future__ import annotations

import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from app.services.openvoice_runtime import get_openvoice_runtime


app = FastAPI(title="EA OpenVoice Sidecar", version="1.0.0")
_MAX_CLONE_FILES = max(1, min(int(os.environ.get("OPENVOICE_MAX_CLONE_FILES", "4")), 8))
_MAX_UPLOAD_BYTES = max(1024 * 1024, int(os.environ.get("OPENVOICE_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))))
_MAX_TOTAL_UPLOAD_BYTES = max(_MAX_UPLOAD_BYTES, int(os.environ.get("OPENVOICE_MAX_TOTAL_UPLOAD_BYTES", str(48 * 1024 * 1024))))
_MAX_TTS_TEXT_LEN = max(32, min(int(os.environ.get("OPENVOICE_MAX_TTS_TEXT_LEN", "3000")), 12000))


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_simple_id(value: str, *, field_name: str) -> str:
    normalized = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"-", "_"})
    normalized = normalized[:80].strip("-_")
    if not normalized:
        raise HTTPException(status_code=400, detail=f"{field_name}_invalid")
    return normalized


def _runtime_readiness_payload() -> dict[str, object]:
    runtime = get_openvoice_runtime()
    config = runtime.config
    converter_config = config.converter_dir / "config.json"
    converter_checkpoint = config.converter_dir / "checkpoint.pth"
    source_ok = runtime.openvoice_source_dir().joinpath("openvoice", "models.py").is_file()
    ready = bool(source_ok and converter_config.is_file() and converter_checkpoint.is_file())
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "base_dir": str(config.base_dir),
        "checkpoint_root": str(config.checkpoint_root),
        "converter_dir": str(config.converter_dir),
        "device": config.device,
        "base_tts": config.base_tts,
        "base_voice_variants": runtime.available_base_voice_variants(),
        "base_voice_default_variant": config.piper_default_variant,
        "source_dir": str(runtime.openvoice_source_dir()),
        "source_present": source_ok,
        "converter_config_present": converter_config.is_file(),
        "converter_checkpoint_present": converter_checkpoint.is_file(),
    }


@app.get("/health/live")
def health_live() -> JSONResponse:
    return JSONResponse(_runtime_readiness_payload())


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    payload = _runtime_readiness_payload()
    if not bool(payload.get("ready")):
        raise HTTPException(status_code=503, detail=payload)
    return JSONResponse(payload)


@app.post("/clone")
async def clone_voice(
    slug: str = Form(...),
    voice_label: str = Form(...),
    voice_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=400, detail="voice_profile_no_samples")
    if len(files) > _MAX_CLONE_FILES:
        raise HTTPException(status_code=400, detail="voice_profile_too_many_samples")
    normalized_slug = _normalize_simple_id(slug, field_name="slug")
    normalized_voice_id = _normalize_simple_id(voice_id, field_name="voice_id")
    normalized_voice_label = _normalize_text(voice_label)[:120]
    if not normalized_voice_label:
        raise HTTPException(status_code=400, detail="voice_label_missing")
    runtime = get_openvoice_runtime()
    payload_files: list[tuple[str, bytes]] = []
    total_bytes = 0
    try:
        for upload in files:
            payload = await upload.read()
            total_bytes += len(payload)
            if len(payload) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="voice_profile_sample_too_large")
            if total_bytes > _MAX_TOTAL_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="voice_profile_total_too_large")
            payload_files.append((str(upload.filename or "sample.bin"), payload))
        payload = runtime.clone_voice(
            voice_id=normalized_voice_id,
            voice_label=normalized_voice_label,
            source_files=payload_files,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        for upload in files:
            await upload.close()
    return JSONResponse({"slug": normalized_slug, **payload})


@app.post("/synthesize")
async def synthesize(payload: dict[str, object]) -> Response:
    text = _normalize_text(payload.get("text"))
    voice_id = _normalize_simple_id(str(payload.get("voice_id") or ""), field_name="voice_id")
    lang = str(payload.get("lang") or "de").strip() or "de"
    base_voice_variant = _normalize_simple_id(str(payload.get("base_voice_variant") or "default"), field_name="base_voice_variant")
    if not text:
        raise HTTPException(status_code=400, detail="tts_text_missing")
    if len(text) > _MAX_TTS_TEXT_LEN:
        raise HTTPException(status_code=400, detail="tts_text_too_long")
    runtime = get_openvoice_runtime()
    try:
        audio = runtime.synthesize(
            voice_id=voice_id,
            text=text,
            lang=lang,
            base_voice_variant=base_voice_variant,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "voice_id_not_found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=503, detail=detail) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
