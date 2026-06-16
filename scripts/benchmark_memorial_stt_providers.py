#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import struct
import sys
import time
import wave
from pathlib import Path

from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[1]
EA_APP_ROOT = REPO_ROOT / "ea"
if str(EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_APP_ROOT))

from app.api.routes import public_memorials
from app.product import service as product_service


FIXTURE_ROOT = Path("/docker/EA/tests/fixtures/memorial")


def _wav_pcm16_samples(payload: bytes) -> tuple[int, list[int]]:
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        sample_rate = int(wav_file.getframerate() or 16_000)
        raw = wav_file.readframes(int(wav_file.getnframes() or 0))
    samples = [sample for (sample,) in struct.iter_unpack("<h", raw[: len(raw) - (len(raw) % 2)])]
    return sample_rate, samples


def _wav_from_samples(samples: list[int], *, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return buffer.getvalue()


def _hostile(payload: bytes) -> bytes:
    sample_rate, samples = _wav_pcm16_samples(payload)
    amplified = [max(-32768, min(32767, int(sample * 1.18))) for sample in samples]
    delay_samples = max(1, int(sample_rate * 0.076))
    echoed = list(amplified)
    for index, sample in enumerate(amplified):
        delayed_index = index + delay_samples
        if delayed_index < len(echoed):
            echoed[delayed_index] = max(-32768, min(32767, echoed[delayed_index] + int(sample * 0.22)))
    noise = [132, -132, 66, -66]
    mixed = [max(-32768, min(32767, sample + noise[index % len(noise)])) for index, sample in enumerate(echoed)]
    factor = 1.35
    target_len = max(1, int(len(mixed) / factor))
    sped = [mixed[min(len(mixed) - 1, int(index * factor))] for index in range(target_len)]
    return _wav_from_samples(sped, sample_rate=sample_rate)


def _usable(text: str) -> bool:
    repaired = public_memorials._repair_memorial_transcript_text(text)
    return bool(repaired) and not public_memorials._is_known_bad_memorial_subtitle_transcript(repaired)


def _run_shadow(payload: bytes) -> dict[str, object]:
    started = time.perf_counter()
    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=payload,
        content_type="audio/wav",
        primary_transcript="",
        primary_transcriber="",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    text = public_memorials._repair_memorial_transcript_text(result.get("transcript_text"))
    return {
        "status": result.get("status"),
        "text": text,
        "usable": _usable(text),
        "ms": round(elapsed_ms, 1),
        "reason": result.get("reason", ""),
    }


def _run_onemin_sample(payload: bytes) -> dict[str, object]:
    keys = product_service._pocket_onemin_api_keys()[: public_memorials._memorial_onemin_max_key_attempts()]
    if not keys:
        return {"status": "unavailable", "detail": "no_keys"}
    errors: list[str] = []
    for api_key in keys:
        try:
            started = time.perf_counter()
            uploaded = product_service._onemin_asset_upload(
                api_key=api_key,
                filename="memorial-speech.wav",
                content_type="audio/wav",
                payload=payload,
            )
            asset = dict(uploaded.get("asset") or {}) if isinstance(uploaded.get("asset"), dict) else {}
            file_content = dict(uploaded.get("fileContent") or {}) if isinstance(uploaded.get("fileContent"), dict) else {}
            audio_path = str(file_content.get("path") or asset.get("key") or "").strip()
            transcribed = product_service._onemin_speech_to_text(api_key=api_key, audio_path=audio_path, language="de")
            ai_record = dict(transcribed.get("aiRecord") or {}) if isinstance(transcribed.get("aiRecord"), dict) else {}
            ai_detail = dict(ai_record.get("aiRecordDetail") or {}) if isinstance(ai_record.get("aiRecordDetail"), dict) else {}
            text = public_memorials._repair_memorial_transcript_text(
                product_service._extract_transcript_text(ai_detail.get("responseObject"))
                or product_service._extract_transcript_text(ai_detail.get("resultObject"))
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "status": "ok" if text else "empty",
                "text": text,
                "usable": _usable(text),
                "ms": round(elapsed_ms, 1),
            }
        except Exception as exc:
            errors.append(str(exc)[:180])
    return {"status": "error", "detail": errors[:3], "sampled_keys": len(keys)}


def _run_full_runtime(payload: bytes) -> dict[str, object]:
    started = time.perf_counter()
    try:
        result = public_memorials._memorial_transcribe_audio_blob(payload=payload, content_type="audio/wav")
    except HTTPException as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "http_error",
            "text": "",
            "usable": False,
            "ms": round(elapsed_ms, 1),
            "transcriber": "",
            "detail": str(exc.detail),
        }
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    text = public_memorials._repair_memorial_transcript_text(result.get("transcript_text"))
    return {
        "status": result.get("transcription_status"),
        "text": text,
        "usable": _usable(text),
        "ms": round(elapsed_ms, 1),
        "transcriber": result.get("transcriber", ""),
        "detail": result.get("detail", ""),
    }


def main() -> int:
    base_contact = (FIXTURE_ROOT / "contact_opening_captured.wav").read_bytes()
    base_retry = (FIXTURE_ROOT / "rescue_stt_retry_captured.wav").read_bytes()
    samples = {
        "contact": base_contact,
        "contact_hostile": _hostile(base_contact),
        "stt_retry": base_retry,
        "stt_retry_hostile": _hostile(base_retry),
    }
    availability = {
        "shadow_provider": public_memorials._text(
            __import__("os").environ.get("EA_MEMORIAL_SHADOW_STT_PROVIDER"),
            "blipai",
        )
        or "blipai",
        "cartesia_configured": bool(public_memorials._memorial_cartesia_api_key()),
        "onemin_key_count": len(product_service._pocket_onemin_api_keys()),
        "onemin_max_key_attempts": public_memorials._memorial_onemin_max_key_attempts(),
    }
    rows = []
    for name, payload in samples.items():
        rows.append(
            {
                "sample": name,
                "shadow": _run_shadow(payload),
                "onemin_sample": _run_onemin_sample(payload),
                "full_runtime": _run_full_runtime(payload),
            }
        )
    print(json.dumps({"availability": availability, "rows": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
