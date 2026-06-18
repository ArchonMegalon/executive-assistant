#!/usr/bin/env python3
from __future__ import annotations

import io
import hashlib
import json
import re
import struct
import sys
import time
import unicodedata
import wave
from pathlib import Path
from typing import Any

from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[1]
EA_APP_ROOT = REPO_ROOT / "ea"
if str(EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_APP_ROOT))

from app.api.routes import public_memorials
from app.product import service as product_service


FIXTURE_ROOT = Path("/docker/EA/tests/fixtures/memorial")
FIXTURE_MANIFEST = FIXTURE_ROOT / "stt_fixture_manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / ".codex-studio/published/memorial_stt_provider_benchmark.generated.json"


def _load_fixture_manifest(path: Path = FIXTURE_MANIFEST) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract_name") != "ea.memorial_stt_fixture_manifest":
        raise RuntimeError("invalid_stt_fixture_manifest_contract")
    return payload


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_fixture_entry(entry: dict[str, Any], *, fixture_root: Path = FIXTURE_ROOT) -> dict[str, Any]:
    required_fields = (
        "sample",
        "file",
        "origin",
        "speaker_consent",
        "allowed_purpose",
        "retention",
        "expected_text",
        "required_tokens",
        "sha256",
    )
    missing = [field for field in required_fields if not entry.get(field)]
    if missing:
        raise RuntimeError(f"stt_fixture_manifest_missing_fields:{entry.get('sample') or entry.get('file')}:{','.join(missing)}")
    path = fixture_root / str(entry["file"])
    payload = path.read_bytes()
    digest = _sha256_bytes(payload)
    if digest != str(entry.get("sha256") or "").strip():
        raise RuntimeError(f"stt_fixture_hash_mismatch:{entry['file']}")
    tokens = [str(token).strip() for token in list(entry.get("required_tokens") or []) if str(token).strip()]
    if not tokens:
        raise RuntimeError(f"stt_fixture_required_tokens_missing:{entry['sample']}")
    return {
        "sample": str(entry["sample"]),
        "file": str(entry["file"]),
        "payload": payload,
        "expected_text": str(entry["expected_text"]).strip(),
        "required_tokens": tokens,
        "language": str(entry.get("language") or "de").strip() or "de",
        "min_token_f1": float(entry.get("min_token_f1") or 0.6),
        "max_wer": float(entry.get("max_wer") or 0.5),
        "fixture_sha256": digest,
        "provenance": {
            "origin": str(entry.get("origin") or "").strip(),
            "speaker_consent": str(entry.get("speaker_consent") or "").strip(),
            "allowed_purpose": str(entry.get("allowed_purpose") or "").strip(),
            "retention": str(entry.get("retention") or "").strip(),
            "synthetic": bool(entry.get("synthetic")),
            "accent": str(entry.get("accent") or "").strip(),
        },
    }


def _fixture_specs() -> list[dict[str, Any]]:
    manifest = _load_fixture_manifest()
    return [_validate_fixture_entry(dict(entry)) for entry in list(manifest.get("fixtures") or []) if isinstance(entry, dict)]


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


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower().replace("ß", "ss"))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", stripped)


def _levenshtein(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_token in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_token in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (0 if left_token == right_token else 1),
                )
            )
        previous = current
    return previous[-1]


def _word_error_rate(expected_text: str, actual_text: str) -> float:
    expected = _tokens(expected_text)
    actual = _tokens(actual_text)
    if not expected:
        return 0.0 if not actual else 1.0
    return round(_levenshtein(expected, actual) / len(expected), 4)


def _token_f1(expected_text: str, actual_text: str) -> float:
    expected = _tokens(expected_text)
    actual = _tokens(actual_text)
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    remaining: dict[str, int] = {}
    for token in actual:
        remaining[token] = remaining.get(token, 0) + 1
    overlap = 0
    for token in expected:
        count = remaining.get(token, 0)
        if count <= 0:
            continue
        overlap += 1
        remaining[token] = count - 1
    precision = overlap / len(actual) if actual else 0.0
    recall = overlap / len(expected) if expected else 0.0
    if precision + recall <= 0:
        return 0.0
    return round((2 * precision * recall) / (precision + recall), 4)


def _required_tokens_present(required_tokens: list[str], actual_text: str) -> bool:
    actual = set(_tokens(actual_text))
    return all(_tokens(token)[0] in actual for token in required_tokens if _tokens(token))


def _usable(text: str) -> bool:
    repaired = public_memorials._repair_memorial_transcript_text(text)
    return bool(repaired) and not public_memorials._is_known_bad_memorial_subtitle_transcript(repaired)


def _score_text(text: str, spec: dict[str, Any]) -> dict[str, object]:
    repaired = public_memorials._repair_memorial_transcript_text(text)
    expected = str(spec.get("expected_text") or "").strip()
    required_tokens = [str(token) for token in list(spec.get("required_tokens") or [])]
    wer = _word_error_rate(expected, repaired)
    f1 = _token_f1(expected, repaired)
    intent_correct = _required_tokens_present(required_tokens, repaired)
    usable = _usable(repaired)
    passed = (
        usable
        and intent_correct
        and f1 >= float(spec.get("min_token_f1") or 0.6)
        and wer <= float(spec.get("max_wer") or 0.5)
    )
    return {
        "expected_text": expected,
        "required_tokens": required_tokens,
        "actual_text": repaired,
        "wer": wer,
        "token_f1": f1,
        "intent_correct": intent_correct,
        "usable": usable,
        "passed": passed,
        "min_token_f1": float(spec.get("min_token_f1") or 0.6),
        "max_wer": float(spec.get("max_wer") or 0.5),
    }


def _attach_score(result: dict[str, object], spec: dict[str, Any]) -> dict[str, object]:
    scored = dict(result)
    scored.update(_score_text(str(scored.get("text") or ""), spec))
    return scored


def _run_shadow(payload: bytes, spec: dict[str, Any]) -> dict[str, object]:
    started = time.perf_counter()
    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=payload,
        content_type="audio/wav",
        primary_transcript="",
        primary_transcriber="",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    text = public_memorials._repair_memorial_transcript_text(result.get("transcript_text"))
    return _attach_score({
        "status": result.get("status"),
        "text": text,
        "ms": round(elapsed_ms, 1),
        "reason": result.get("reason", ""),
    }, spec)


def _run_onemin_sample(payload: bytes, spec: dict[str, Any]) -> dict[str, object]:
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
            return _attach_score({
                "status": "ok" if text else "empty",
                "text": text,
                "ms": round(elapsed_ms, 1),
            }, spec)
        except Exception as exc:
            errors.append(str(exc)[:180])
    return {"status": "error", "detail": errors[:3], "sampled_keys": len(keys)}


def _run_full_runtime(payload: bytes, spec: dict[str, Any]) -> dict[str, object]:
    started = time.perf_counter()
    try:
        result = public_memorials._memorial_transcribe_audio_blob(payload=payload, content_type="audio/wav")
    except HTTPException as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return _attach_score({
            "status": "http_error",
            "text": "",
            "ms": round(elapsed_ms, 1),
            "transcriber": "",
            "detail": str(exc.detail),
        }, spec)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    text = public_memorials._repair_memorial_transcript_text(result.get("transcript_text"))
    return _attach_score({
        "status": result.get("transcription_status"),
        "text": text,
        "ms": round(elapsed_ms, 1),
        "transcriber": result.get("transcriber", ""),
        "detail": result.get("detail", ""),
    }, spec)


def _provider_summary(rows: list[dict[str, object]], provider_key: str) -> dict[str, object]:
    scored = [dict(row.get(provider_key) or {}) for row in rows]
    pass_count = sum(1 for row in scored if row.get("passed") is True)
    scored_count = sum(1 for row in scored if "token_f1" in row)
    avg_f1 = round(sum(float(row.get("token_f1") or 0.0) for row in scored) / scored_count, 4) if scored_count else 0.0
    avg_wer = round(sum(float(row.get("wer") or 1.0) for row in scored) / scored_count, 4) if scored_count else 1.0
    intent_count = sum(1 for row in scored if row.get("intent_correct") is True)
    latencies = [float(row.get("ms") or 0.0) for row in scored if float(row.get("ms") or 0.0) > 0]
    return {
        "provider": provider_key,
        "passed_samples": pass_count,
        "sample_count": len(scored),
        "intent_correct_samples": intent_count,
        "avg_token_f1": avg_f1,
        "avg_wer": avg_wer,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "production_eligible": pass_count == len(scored) and len(scored) > 0,
    }


def _rank_providers(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries = [_provider_summary(rows, key) for key in ("full_runtime", "shadow", "onemin_sample")]
    return sorted(
        summaries,
        key=lambda item: (
            int(item["passed_samples"]),
            int(item["intent_correct_samples"]),
            float(item["avg_token_f1"]),
            -float(item["avg_wer"]),
            -float(item["avg_latency_ms"]),
        ),
        reverse=True,
    )


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark memorial STT providers against ground-truth captured fixtures.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    samples: list[dict[str, Any]] = []
    for spec in _fixture_specs():
        if spec["sample"] == "technical_retry":
            continue
        samples.append({**spec, "variant": "captured", "payload": spec["payload"]})
        samples.append({**spec, "sample": f"{spec['sample']}_hostile", "variant": "hostile", "payload": _hostile(spec["payload"])})
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
    for spec in samples:
        payload = bytes(spec["payload"])
        rows.append(
            {
                "sample": spec["sample"],
                "variant": spec["variant"],
                "fixture": spec["file"],
                "fixture_sha256": spec["fixture_sha256"],
                "provenance": spec["provenance"],
                "shadow": _run_shadow(payload, spec),
                "onemin_sample": _run_onemin_sample(payload, spec),
                "full_runtime": _run_full_runtime(payload, spec),
            }
        )
    report = {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "status": "pass" if any(row.get("production_eligible") for row in _rank_providers(rows)) else "blocked",
        "scoring": {
            "pass_rule": "usable transcript + required tokens present + token_f1 >= sample min + WER <= sample max",
            "known_bad_non_empty_text_is_not_enough": True,
        },
        "availability": availability,
        "provider_ranking": _rank_providers(rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
