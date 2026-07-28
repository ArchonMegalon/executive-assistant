from __future__ import annotations

import argparse
import concurrent.futures
from collections import Counter
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import wave
from pathlib import Path

from fastapi import HTTPException
from app.api.routes import public_memorials as memorial_routes
from app.services.memorial_openvoice import unmixr_synthesize_request


DEFAULT_PROMPTS = [
    "Worum geht es?",
    "Klar. Worum geht es?",
    "Ich höre zu. Lass dir Zeit.",
    "Weiß ich nicht.",
    "Weiß ich nicht mehr.",
]
FEATURE_SCREEN_PROMPT = "Ich höre zu. Worum geht es?"
DEFAULT_PROVIDER_LANGUAGE = "de"
DEFAULT_TAKES_PER_PROMPT = 3
DEFAULT_PRONUNCIATION_DICT = {"klar": "klaar", "Klar": "Klaar"}

DEFAULT_COMBOS = [
    {"speaking_rate": "medium", "speaking_pitch": "low", "speaking_volume": "high"},
    {"speaking_rate": "low", "speaking_pitch": "medium", "speaking_volume": "high"},
    {"speaking_rate": "medium", "speaking_pitch": "medium", "speaking_volume": "high"},
]
_PROSODY_LEVELS = ("low", "medium", "high")
DEFAULT_POSTPROCESS_PROFILES = [""]
DEFAULT_SHORTLIST_TOP_K = 3


def _load_optimizer_module():
    script_path = Path(__file__).with_name("optimize_memorial_openvoice_clone.py")
    spec = importlib.util.spec_from_file_location("optimize_memorial_openvoice_clone", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("optimizer_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_OPTIMIZER = _load_optimizer_module()


def _optimization_root(*, slug: str) -> Path:
    return _OPTIMIZER._optimization_dir(slug=slug)


def _reference_path(*, slug: str) -> Path:
    path = _optimization_root(slug=slug) / "candidates" / "oSQ9FhFc4YI-01440s-28.wav"
    if not path.is_file():
        raise RuntimeError(f"reference_missing:{path}")
    return path


def _existing_candidates(*, slug: str) -> list[str]:
    report_path = _optimization_root(slug=slug) / "unmixr_existing_clone_comparison_report.json"
    if not report_path.is_file():
        raise RuntimeError(f"candidate_report_missing:{report_path}")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else []
    candidates: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        voice_id = str((row or {}).get("voice_id") or "").strip()
        if voice_id and voice_id not in candidates:
            candidates.append(voice_id)
    if not candidates:
        raise RuntimeError("candidate_voice_ids_missing")
    return candidates


def _prosody_combos(*, exhaustive: bool) -> list[dict[str, str]]:
    if not exhaustive:
        return [dict(item) for item in DEFAULT_COMBOS]
    combos: list[dict[str, str]] = []
    for rate in _PROSODY_LEVELS:
        for pitch in _PROSODY_LEVELS:
            for volume in _PROSODY_LEVELS:
                combos.append(
                    {
                        "speaking_rate": rate,
                        "speaking_pitch": pitch,
                        "speaking_volume": volume,
                    }
                )
    return combos


def _postprocess_profiles(*, configured: list[str] | None = None) -> list[str]:
    requested = [str(item or "").strip() for item in list(configured or [])]
    normalized = [item for item in requested if item or item == ""]
    if not normalized:
        return list(DEFAULT_POSTPROCESS_PROFILES)
    deduped: list[str] = []
    for item in normalized:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _candidate_identity(
    *,
    voice_id: str,
    combo: dict[str, str],
    postprocess_profile: str,
) -> tuple[str, str, str, str, str]:
    return (
        str(voice_id or "").strip(),
        str(combo.get("speaking_rate") or "").strip(),
        str(combo.get("speaking_pitch") or "").strip(),
        str(combo.get("speaking_volume") or "").strip(),
        str(postprocess_profile or "").strip(),
    )


def _convert_audio_to_wav(*, payload: bytes, content_type: str) -> bytes:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return payload
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    with tempfile.TemporaryDirectory(prefix="memorial-unmixr-") as temp_dir:
        input_path = Path(temp_dir) / "input.bin"
        output_path = Path(temp_dir) / "output.wav"
        input_path.write_bytes(payload)
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            detail = (completed.stderr or "").strip()[:200]
            raise RuntimeError(f"ffmpeg_convert_failed:{detail or 'unknown'}")
        return output_path.read_bytes()


def _wav_duration_seconds(payload: bytes) -> float:
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        return float(wav_file.getnframes()) / float(max(1, wav_file.getframerate()))


def _text_overlap(expected: str, actual: str) -> float:
    return float(_OPTIMIZER._text_similarity(expected, actual))


def _normalize_transcript_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^\wäöüß]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _transcript_metrics(expected: str, actual: str) -> dict[str, object]:
    expected_text = _normalize_transcript_text(expected)
    actual_text = _normalize_transcript_text(actual)
    expected_tokens = expected_text.split()
    actual_tokens = actual_text.split()
    expected_counts = Counter(expected_tokens)
    actual_counts = Counter(actual_tokens)
    matched = sum((expected_counts & actual_counts).values())
    precision = matched / float(len(actual_tokens) or 1)
    recall = matched / float(len(expected_tokens) or 1)
    f1 = (
        (2.0 * precision * recall) / (precision + recall)
        if precision + recall > 0
        else 0.0
    )
    missing_counts = expected_counts - actual_counts
    missing_tokens = [
        token
        for token in expected_tokens
        for _ in range(int(missing_counts.get(token, 0)))
    ]
    return {
        "normalized_expected": expected_text,
        "normalized_actual": actual_text,
        "exact_match": bool(expected_text and expected_text == actual_text),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "missing_tokens": missing_tokens,
    }


def _candidate_audio_path(
    *,
    output_dir: Path,
    voice_id: str,
    prompt: str,
    take_index: int,
) -> Path:
    voice_token = hashlib.sha256(str(voice_id).encode("utf-8")).hexdigest()[:12]
    prompt_token = hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()[:10]
    return (
        output_dir
        / f"candidate-{voice_token}"
        / f"prompt-{prompt_token}-take-{max(1, int(take_index)):02d}.wav"
    )


def _write_private_candidate_audio(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise RuntimeError("candidate_audio_path_unsafe")
    path.parent.chmod(0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError("candidate_audio_private_write_failed") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    path.chmod(0o600, follow_symlinks=False)


def _row_rank_key(row: dict[str, object]) -> tuple[int, float, float, float]:
    gate = dict(row.get("quality_gate") or {})
    return (
        1 if str(gate.get("status") or "") == "pass" else 0,
        float(gate.get("exact_take_rate") or 0.0),
        float(row.get("average_text_f1") or 0.0),
        float(row.get("average_feature_similarity") or 0.0),
    )


def _recommended_config(winner: dict[str, object] | None) -> dict[str, object]:
    row = dict(winner or {})
    voice_id = str(row.get("voice_id") or "").strip()
    if not voice_id:
        return {}
    return {
        "tts_plugin": "unmixr_clone",
        "tts_plugin_voice_id": voice_id,
        "voice_profile_id": voice_id,
        "voice_label": "Manfred Hoza · Unmixr-Klon",
        "tts_base_voice_variant": "unmixr",
        "provider_language": DEFAULT_PROVIDER_LANGUAGE,
        "unmixr_account_slot": str(row.get("unmixr_account_slot") or "").strip(),
        "unmixr_speaking_rate": str(row.get("speaking_rate") or "").strip(),
        "unmixr_speaking_pitch": str(row.get("speaking_pitch") or "").strip(),
        "unmixr_speaking_volume": str(row.get("speaking_volume") or "").strip(),
        "unmixr_pronunciation_dict": dict(DEFAULT_PRONUNCIATION_DICT),
        "tts_postprocess_profile": str(
            row.get("tts_postprocess_profile") or ""
        ).strip(),
    }


def _unmixr_throttle_payload(exc: BaseException) -> dict[str, object] | None:
    if not isinstance(exc, HTTPException):
        return None
    if int(getattr(exc, "status_code", 0) or 0) != 502:
        return None
    detail = str(getattr(exc, "detail", "") or "").strip()
    if ":429" not in detail and "throttled" not in detail.lower():
        return None
    retry_after_seconds = 0
    digits = []
    for token in detail.replace(".", " ").replace(":", " ").split():
        if token.isdigit():
            digits.append(int(token))
    if digits:
        retry_after_seconds = max(digits)
    return {
        "status": "throttled",
        "detail": detail,
        "retry_after_seconds": retry_after_seconds,
    }


def _apply_memorial_unmixr_postprocess(
    *,
    payload: bytes,
    content_type: str,
    postprocess_profile: str,
    lead_in_ms: int,
    tail_silence_ms: int,
) -> tuple[bytes, str]:
    filters = memorial_routes._speech_postprocess_filters_for_config(
        memorial_routes.UNMIXR_TTS_PLUGIN_ID,
        {"tts_postprocess_profile": str(postprocess_profile or "").strip()},
    )
    return memorial_routes._pad_speech_audio_lead_in(
        payload=payload,
        content_type=content_type,
        silence_ms=max(0, int(lead_in_ms or 0)),
        tail_silence_ms=max(0, int(tail_silence_ms or 0)),
        extra_filters=filters,
    )


def _evaluate_candidate_prompt(
    *,
    slug: str,
    voice_id: str,
    prompt: str,
    take_index: int,
    combo: dict[str, str],
    reference_metrics: dict[str, float],
    base_url: str,
    timeout_seconds: float,
    postprocess_profile: str,
    feature_only: bool,
    lead_in_ms: int,
    tail_silence_ms: int,
    provider_language: str,
    pronunciation_dict: dict[str, str],
    audio_output_dir: Path | None,
    account_slot: str,
) -> dict[str, object]:
    def _work() -> dict[str, object]:
        try:
            audio, content_type = unmixr_synthesize_request(
                text=prompt,
                voice_id=voice_id,
                lang=provider_language,
                speaking_rate=str(combo.get("speaking_rate") or "").strip() or None,
                speaking_pitch=str(combo.get("speaking_pitch") or "").strip() or None,
                speaking_volume=str(combo.get("speaking_volume") or "").strip() or None,
                pronunciation_dict=pronunciation_dict,
                account_slot=account_slot or None,
            )
        except Exception as exc:
            throttle = _unmixr_throttle_payload(exc)
            if throttle is not None:
                return {
                    "prompt": prompt,
                    "take": max(1, int(take_index)),
                    "tts_postprocess_profile": str(postprocess_profile or "").strip(),
                    "feature_similarity": 0.0,
                    "text_similarity": 0.0,
                    "text_f1": 0.0,
                    "exact_match": False,
                    "score": 0.0,
                    "duration_seconds": 0.0,
                    "transcript_text": "",
                    "content_type": "",
                    "status": "throttled",
                    "provider_detail": str(throttle.get("detail") or ""),
                    "retry_after_seconds": int(throttle.get("retry_after_seconds") or 0),
                }
            raise
        wav_bytes, wav_content_type = _apply_memorial_unmixr_postprocess(
            payload=audio,
            content_type=content_type,
            postprocess_profile=postprocess_profile,
            lead_in_ms=lead_in_ms,
            tail_silence_ms=tail_silence_ms,
        )
        wav_bytes = _convert_audio_to_wav(payload=wav_bytes, content_type=wav_content_type)
        audio_path = ""
        audio_sha256 = hashlib.sha256(wav_bytes).hexdigest()
        if audio_output_dir is not None and not feature_only:
            private_audio_path = _candidate_audio_path(
                output_dir=audio_output_dir,
                voice_id=voice_id,
                prompt=prompt,
                take_index=take_index,
            )
            _write_private_candidate_audio(private_audio_path, wav_bytes)
            audio_path = private_audio_path.as_posix()
        transcript_payload = _OPTIMIZER._transcribe_audio_bytes(
            wav_bytes,
            content_type="audio/wav",
            slug=slug,
            base_url=base_url,
        ) if not feature_only else {}
        transcript_text = (
            str(
                transcript_payload.get("text")
                or transcript_payload.get("transcript_text")
                or ""
            ).strip()
            if not feature_only
            else ""
        )
        candidate_metrics = dict(_OPTIMIZER._wav_metrics_from_bytes(wav_bytes) or {})
        duration_seconds = _wav_duration_seconds(wav_bytes)
        candidate_metrics.setdefault("duration_seconds", duration_seconds)
        scored_reference_metrics = dict(reference_metrics or {})
        scored_reference_metrics.setdefault("duration_seconds", 0.0)
        feature_similarity = float(
            _OPTIMIZER._voice_feature_similarity(
                scored_reference_metrics,
                candidate_metrics,
            )
        )
        transcript_metrics = _transcript_metrics(prompt, transcript_text)
        text_similarity = _text_overlap(prompt, transcript_text) if transcript_text else 0.0
        text_f1 = float(transcript_metrics["f1"])
        score = (
            feature_similarity
            if feature_only
            else ((feature_similarity * 0.35) + (text_f1 * 0.65))
        )
        return {
            "prompt": prompt,
            "take": max(1, int(take_index)),
            "tts_postprocess_profile": str(postprocess_profile or "").strip(),
            "feature_similarity": round(feature_similarity, 4),
            "text_similarity": round(text_similarity, 4),
            "text_f1": round(text_f1, 4),
            "exact_match": bool(transcript_metrics["exact_match"]),
            "normalized_expected": transcript_metrics["normalized_expected"],
            "normalized_actual": transcript_metrics["normalized_actual"],
            "missing_tokens": list(transcript_metrics["missing_tokens"]),
            "score": round(score, 4),
            "duration_seconds": round(duration_seconds, 3),
            "transcript_text": transcript_text,
            "content_type": "audio/wav",
            "audio_path": audio_path,
            "audio_sha256": audio_sha256,
            "status": "ok",
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_work)
        effective_timeout = max(0.001, float(timeout_seconds or 0.0))
        try:
            return future.result(timeout=effective_timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"candidate_prompt_timeout:{effective_timeout:g}s") from exc


def compare_unmixr_clones(
    *,
    slug: str,
    base_url: str,
    voice_ids: list[str],
    prompts: list[str],
    combos: list[dict[str, str]],
    postprocess_profiles: list[str] | None = None,
    output_path: Path | None = None,
    resume: bool = False,
    max_rows: int = 0,
    prompt_timeout_seconds: float = 90.0,
    feature_only: bool = False,
    lead_in_ms: int = 0,
    tail_silence_ms: int = 0,
    takes_per_prompt: int = 1,
    provider_language: str = DEFAULT_PROVIDER_LANGUAGE,
    pronunciation_dict: dict[str, str] | None = None,
    audio_output_dir: Path | None = None,
    account_slots_by_voice: dict[str, str] | None = None,
) -> dict[str, object]:
    postprocess_profiles = _postprocess_profiles(configured=postprocess_profiles)
    effective_takes = 1 if feature_only else max(1, int(takes_per_prompt or 1))
    effective_language = str(provider_language or DEFAULT_PROVIDER_LANGUAGE).strip() or DEFAULT_PROVIDER_LANGUAGE
    effective_pronunciation = dict(
        DEFAULT_PRONUNCIATION_DICT
        if pronunciation_dict is None
        else pronunciation_dict
    )
    effective_account_slots = {
        str(voice_id).strip(): str(slot_name).strip()
        for voice_id, slot_name in dict(account_slots_by_voice or {}).items()
        if str(voice_id).strip() and str(slot_name).strip()
    }
    reference_metrics = _OPTIMIZER._wav_metrics_from_bytes(_reference_path(slug=slug).read_bytes())
    rows: list[dict[str, object]] = []
    winner: dict[str, object] | None = None
    seen_keys: set[tuple[str, str, str, str, str]] = set()

    def _row_key(row: dict[str, object]) -> tuple[str, str, str, str, str]:
        return (
            str(row.get("voice_id") or "").strip(),
            str(row.get("speaking_rate") or "").strip(),
            str(row.get("speaking_pitch") or "").strip(),
            str(row.get("speaking_volume") or "").strip(),
            str(row.get("tts_postprocess_profile") or "").strip(),
        )

    def _write_checkpoint() -> None:
        if output_path is None:
            return
        promotable_winner = (
            winner
            if feature_only
            or str(dict((winner or {}).get("quality_gate") or {}).get("status") or "")
            == "pass"
            else None
        )
        payload = {
            "slug": slug,
            "base_url": base_url,
            "reference_path": str(_reference_path(slug=slug)),
            "rows": rows,
            "winner": winner,
            "recommended_config": _recommended_config(promotable_winner),
            "completed_rows": len(rows),
            "requested_rows": len(voice_ids) * len(combos) * len(postprocess_profiles),
            "complete": len(rows) >= (len(voice_ids) * len(combos) * len(postprocess_profiles)),
            "feature_only": bool(feature_only),
            "lead_in_ms": int(max(0, lead_in_ms)),
            "tail_silence_ms": int(max(0, tail_silence_ms)),
            "takes_per_prompt": effective_takes,
            "provider_language": effective_language,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if resume and output_path is not None and output_path.is_file():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        existing_rows = existing.get("rows") if isinstance(existing, dict) else []
        for row in existing_rows if isinstance(existing_rows, list) else []:
            if not isinstance(row, dict):
                continue
            rows.append(row)
            seen_keys.add(_row_key(row))
            if winner is None or _row_rank_key(row) > _row_rank_key(winner):
                winner = row

    rows_evaluated = 0
    for voice_id in voice_ids:
        for combo in combos:
            for postprocess_profile in postprocess_profiles:
                row_identity = (
                    str(voice_id or "").strip(),
                    str(combo.get("speaking_rate") or "").strip(),
                    str(combo.get("speaking_pitch") or "").strip(),
                    str(combo.get("speaking_volume") or "").strip(),
                    str(postprocess_profile or "").strip(),
                )
                if row_identity in seen_keys:
                    continue
                if max_rows > 0 and rows_evaluated >= max_rows:
                    _write_checkpoint()
                    return {
                        "slug": slug,
                        "base_url": base_url,
                        "reference_path": str(_reference_path(slug=slug)),
                        "rows": rows,
                        "winner": winner,
                        "recommended_config": _recommended_config(winner),
                        "completed_rows": len(rows),
                        "requested_rows": len(voice_ids) * len(combos) * len(postprocess_profiles),
                        "complete": False,
                        "feature_only": bool(feature_only),
                        "lead_in_ms": int(max(0, lead_in_ms)),
                        "tail_silence_ms": int(max(0, tail_silence_ms)),
                        "takes_per_prompt": effective_takes,
                        "provider_language": effective_language,
                    }
                prompt_rows = []
                for prompt in prompts:
                    for take_index in range(1, effective_takes + 1):
                        prompt_rows.append(
                            _evaluate_candidate_prompt(
                                slug=slug,
                                voice_id=voice_id,
                                prompt=prompt,
                                take_index=take_index,
                                combo=combo,
                                reference_metrics=reference_metrics,
                                base_url=base_url,
                                timeout_seconds=prompt_timeout_seconds,
                                postprocess_profile=postprocess_profile,
                                feature_only=feature_only,
                                lead_in_ms=lead_in_ms,
                                tail_silence_ms=tail_silence_ms,
                                provider_language=effective_language,
                                pronunciation_dict=effective_pronunciation,
                                audio_output_dir=audio_output_dir,
                                account_slot=effective_account_slots.get(
                                    str(voice_id or "").strip(),
                                    "",
                                ),
                            )
                        )
                throttled_prompt = next(
                    (
                        item
                        for item in prompt_rows
                        if str(item.get("status") or "").strip().lower() == "throttled"
                    ),
                    None,
                )
                if isinstance(throttled_prompt, dict):
                    _write_checkpoint()
                    return {
                        "slug": slug,
                        "base_url": base_url,
                        "reference_path": str(_reference_path(slug=slug)),
                        "rows": rows,
                        "winner": winner,
                        "recommended_config": _recommended_config(winner),
                        "completed_rows": len(rows),
                        "requested_rows": len(voice_ids) * len(combos) * len(postprocess_profiles),
                        "complete": False,
                        "feature_only": bool(feature_only),
                        "lead_in_ms": int(max(0, lead_in_ms)),
                        "tail_silence_ms": int(max(0, tail_silence_ms)),
                        "takes_per_prompt": effective_takes,
                        "provider_language": effective_language,
                        "blocked": {
                            "status": "throttled",
                            "voice_id": str(voice_id or "").strip(),
                            "speaking_rate": str(combo.get("speaking_rate") or "").strip(),
                            "speaking_pitch": str(combo.get("speaking_pitch") or "").strip(),
                            "speaking_volume": str(combo.get("speaking_volume") or "").strip(),
                            "tts_postprocess_profile": str(postprocess_profile or "").strip(),
                            "prompt": str(throttled_prompt.get("prompt") or "").strip(),
                            "retry_after_seconds": int(throttled_prompt.get("retry_after_seconds") or 0),
                            "provider_detail": str(throttled_prompt.get("provider_detail") or ""),
                        },
                    }
                average_score = sum(float(item.get("score") or 0.0) for item in prompt_rows) / float(len(prompt_rows) or 1)
                average_feature_similarity = sum(float(item.get("feature_similarity") or 0.0) for item in prompt_rows) / float(len(prompt_rows) or 1)
                average_text_f1 = sum(float(item.get("text_f1") or 0.0) for item in prompt_rows) / float(len(prompt_rows) or 1)
                average_duration_seconds = sum(float(item.get("duration_seconds") or 0.0) for item in prompt_rows) / float(len(prompt_rows) or 1)
                exact_takes = sum(1 for item in prompt_rows if item.get("exact_match") is True)
                prompt_stability = []
                for prompt in prompts:
                    takes = [
                        item
                        for item in prompt_rows
                        if str(item.get("prompt") or "") == prompt
                    ]
                    exact_count = sum(
                        1 for item in takes if item.get("exact_match") is True
                    )
                    prompt_stability.append(
                        {
                            "prompt": prompt,
                            "exact_takes": exact_count,
                            "required_takes": effective_takes,
                            "status": (
                                "not_evaluated"
                                if feature_only
                                else (
                                    "pass"
                                    if exact_count == effective_takes
                                    else "fail"
                                )
                            ),
                        }
                    )
                quality_gate = {
                    "status": (
                        "not_evaluated"
                        if feature_only
                        else (
                            "pass"
                            if prompt_stability
                            and all(
                                str(item.get("status") or "") == "pass"
                                for item in prompt_stability
                            )
                            else "fail"
                        )
                    ),
                    "exact_takes": exact_takes,
                    "required_exact_takes": len(prompts) * effective_takes,
                    "exact_take_rate": round(
                        exact_takes / float((len(prompts) * effective_takes) or 1),
                        4,
                    ),
                    "prompts": prompt_stability,
                }
                row = {
                    "voice_id": voice_id,
                    "speaking_rate": str(combo.get("speaking_rate") or "").strip(),
                    "speaking_pitch": str(combo.get("speaking_pitch") or "").strip(),
                    "speaking_volume": str(combo.get("speaking_volume") or "").strip(),
                    "tts_postprocess_profile": str(postprocess_profile or "").strip(),
                    "unmixr_account_slot": effective_account_slots.get(
                        str(voice_id or "").strip(),
                        "",
                    ),
                    "average_score": round(average_score, 4),
                    "average_feature_similarity": round(average_feature_similarity, 4),
                    "average_text_f1": round(average_text_f1, 4),
                    "average_duration_seconds": round(average_duration_seconds, 3),
                    "quality_gate": quality_gate,
                    "prompts": prompt_rows,
                }
                rows.append(row)
                seen_keys.add(_row_key(row))
                rows_evaluated += 1
                if winner is None or _row_rank_key(row) > _row_rank_key(winner):
                    winner = row
                _write_checkpoint()
    if winner is None:
        raise RuntimeError("no_unmixr_candidates_evaluated")
    promotion_passed = (
        feature_only
        or str(dict(winner.get("quality_gate") or {}).get("status") or "") == "pass"
    )
    report = {
        "slug": slug,
        "base_url": base_url,
        "reference_path": str(_reference_path(slug=slug)),
        "rows": rows,
        "winner": winner,
        "completed_rows": len(rows),
        "requested_rows": len(voice_ids) * len(combos) * len(postprocess_profiles),
        "feature_only": bool(feature_only),
        "lead_in_ms": int(max(0, lead_in_ms)),
        "tail_silence_ms": int(max(0, tail_silence_ms)),
        "takes_per_prompt": effective_takes,
        "provider_language": effective_language,
        "complete": True,
        "recommended_config": _recommended_config(
            winner if promotion_passed else None
        ),
    }
    if not promotion_passed:
        report["blocked"] = {
            "status": "quality_gate_failed",
            "code": "unstable_product_phrases",
            "quality_gate": dict(winner.get("quality_gate") or {}),
        }
    return report


def compare_unmixr_clones_two_stage(
    *,
    slug: str,
    base_url: str,
    voice_ids: list[str],
    prompts: list[str],
    combos: list[dict[str, str]],
    postprocess_profiles: list[str] | None = None,
    shortlist_top_k: int = DEFAULT_SHORTLIST_TOP_K,
    feature_output_path: Path | None = None,
    final_output_path: Path | None = None,
    prompt_timeout_seconds: float = 90.0,
    lead_in_ms: int = 0,
    tail_silence_ms: int = 0,
    takes_per_prompt: int = DEFAULT_TAKES_PER_PROMPT,
    provider_language: str = DEFAULT_PROVIDER_LANGUAGE,
    pronunciation_dict: dict[str, str] | None = None,
    audio_output_dir: Path | None = None,
    account_slots_by_voice: dict[str, str] | None = None,
) -> dict[str, object]:
    shortlisted_count = max(1, int(shortlist_top_k or DEFAULT_SHORTLIST_TOP_K))
    feature_report = compare_unmixr_clones(
        slug=slug,
        base_url=base_url,
        voice_ids=voice_ids,
        prompts=[FEATURE_SCREEN_PROMPT],
        combos=combos,
        postprocess_profiles=postprocess_profiles,
        output_path=feature_output_path,
        resume=False,
        max_rows=0,
        prompt_timeout_seconds=prompt_timeout_seconds,
        feature_only=True,
        lead_in_ms=lead_in_ms,
        tail_silence_ms=tail_silence_ms,
        takes_per_prompt=1,
        provider_language=provider_language,
        pronunciation_dict=pronunciation_dict,
        audio_output_dir=None,
        account_slots_by_voice=account_slots_by_voice,
    )
    feature_rows = sorted(
        [row for row in list(feature_report.get("rows") or []) if isinstance(row, dict)],
        key=lambda row: float(row.get("average_score") or 0.0),
        reverse=True,
    )
    shortlisted_rows = feature_rows[:shortlisted_count]
    if not shortlisted_rows:
        raise RuntimeError("no_unmixr_shortlist_candidates")
    reranked_rows: list[dict[str, object]] = []
    blocked_reports: list[dict[str, object]] = []
    for shortlist_index, shortlist_row in enumerate(shortlisted_rows, start=1):
        combo = {
            "speaking_rate": str(
                shortlist_row.get("speaking_rate") or ""
            ).strip(),
            "speaking_pitch": str(
                shortlist_row.get("speaking_pitch") or ""
            ).strip(),
            "speaking_volume": str(
                shortlist_row.get("speaking_volume") or ""
            ).strip(),
        }
        candidate_audio_dir = (
            audio_output_dir / f"shortlist-{shortlist_index:02d}"
            if audio_output_dir is not None
            else None
        )
        candidate_report = compare_unmixr_clones(
            slug=slug,
            base_url=base_url,
            voice_ids=[str(shortlist_row.get("voice_id") or "").strip()],
            prompts=prompts,
            combos=[combo],
            postprocess_profiles=[
                str(shortlist_row.get("tts_postprocess_profile") or "").strip()
            ],
            output_path=None,
            resume=False,
            max_rows=0,
            prompt_timeout_seconds=prompt_timeout_seconds,
            feature_only=False,
            lead_in_ms=lead_in_ms,
            tail_silence_ms=tail_silence_ms,
            takes_per_prompt=max(2, int(takes_per_prompt or DEFAULT_TAKES_PER_PROMPT)),
            provider_language=provider_language,
            pronunciation_dict=pronunciation_dict,
            audio_output_dir=candidate_audio_dir,
            account_slots_by_voice=account_slots_by_voice,
        )
        reranked_rows.extend(
            row
            for row in list(candidate_report.get("rows") or [])
            if isinstance(row, dict)
        )
        if isinstance(candidate_report.get("blocked"), dict):
            blocked_reports.append(dict(candidate_report["blocked"]))
    reranked_rows.sort(key=_row_rank_key, reverse=True)
    if not reranked_rows:
        raise RuntimeError("no_unmixr_reranked_candidates")
    winner = next(
        (
            row
            for row in reranked_rows
            if str(dict(row.get("quality_gate") or {}).get("status") or "")
            == "pass"
        ),
        None,
    )
    report = {
        "slug": slug,
        "base_url": base_url,
        "reference_path": str(_reference_path(slug=slug)),
        "strategy": "two_stage",
        "shortlist_top_k": shortlisted_count,
        "feature_shortlist_rows": shortlisted_rows,
        "rows": reranked_rows,
        "winner": winner or {},
        "completed_rows": len(reranked_rows),
        "requested_rows": len(reranked_rows),
        "complete": True,
        "takes_per_prompt": max(
            2, int(takes_per_prompt or DEFAULT_TAKES_PER_PROMPT)
        ),
        "provider_language": str(
            provider_language or DEFAULT_PROVIDER_LANGUAGE
        ).strip()
        or DEFAULT_PROVIDER_LANGUAGE,
        "rendered_final_candidates": len(shortlisted_rows),
        "recommended_config": _recommended_config(winner),
    }
    if winner is None:
        report["blocked"] = {
            "status": "quality_gate_failed",
            "code": "no_stable_product_phrase_candidate",
            "candidate_failures": blocked_reports,
        }
    if final_output_path is not None:
        final_output_path.parent.mkdir(parents=True, exist_ok=True)
        final_output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare existing Unmixr memorial clones and recommend the best live config.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--voice-id", action="append", default=[])
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--postprocess-profile", action="append", default=[])
    parser.add_argument("--exhaustive-prosody", action="store_true")
    parser.add_argument("--feature-only", action="store_true")
    parser.add_argument("--two-stage", action="store_true")
    parser.add_argument("--shortlist-top-k", type=int, default=DEFAULT_SHORTLIST_TOP_K)
    parser.add_argument(
        "--takes-per-prompt",
        type=int,
        default=DEFAULT_TAKES_PER_PROMPT,
    )
    parser.add_argument("--provider-language", default=DEFAULT_PROVIDER_LANGUAGE)
    parser.add_argument("--audio-output-dir", default="")
    parser.add_argument("--lead-in-ms", type=int, default=0)
    parser.add_argument("--tail-silence-ms", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--prompt-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--output", default="")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    slug = str(args.slug or "manfred").strip() or "manfred"
    base_url = str(args.base_url or "http://127.0.0.1:8090").strip() or "http://127.0.0.1:8090"
    voice_ids = [str(item).strip() for item in list(args.voice_id or []) if str(item).strip()] or _existing_candidates(slug=slug)
    prompts = [str(item).strip() for item in list(args.prompt or []) if str(item).strip()] or list(DEFAULT_PROMPTS)
    output = str(args.output or "").strip()
    audio_output_dir = (
        Path(str(args.audio_output_dir)).expanduser()
        if str(args.audio_output_dir or "").strip()
        else None
    )
    combos = _prosody_combos(exhaustive=bool(args.exhaustive_prosody))
    profiles = _postprocess_profiles(configured=list(args.postprocess_profile or []))
    if bool(args.two_stage):
        feature_output_path = None
        if output:
            requested = Path(output)
            feature_output_path = requested.with_name(f"{requested.stem}.feature{requested.suffix or '.json'}")
        report = compare_unmixr_clones_two_stage(
            slug=slug,
            base_url=base_url,
            voice_ids=voice_ids,
            prompts=prompts,
            combos=combos,
            postprocess_profiles=profiles,
            shortlist_top_k=max(1, int(args.shortlist_top_k or DEFAULT_SHORTLIST_TOP_K)),
            feature_output_path=feature_output_path,
            final_output_path=Path(output) if output else None,
            prompt_timeout_seconds=max(1.0, float(args.prompt_timeout_seconds or 90.0)),
            lead_in_ms=max(0, int(args.lead_in_ms or 0)),
            tail_silence_ms=max(0, int(args.tail_silence_ms or 0)),
            takes_per_prompt=max(
                2, int(args.takes_per_prompt or DEFAULT_TAKES_PER_PROMPT)
            ),
            provider_language=str(
                args.provider_language or DEFAULT_PROVIDER_LANGUAGE
            ).strip()
            or DEFAULT_PROVIDER_LANGUAGE,
            pronunciation_dict=dict(DEFAULT_PRONUNCIATION_DICT),
            audio_output_dir=audio_output_dir,
        )
    else:
        report = compare_unmixr_clones(
            slug=slug,
            base_url=base_url,
            voice_ids=voice_ids,
            prompts=prompts,
            combos=combos,
            postprocess_profiles=profiles,
            output_path=Path(output) if output else None,
            resume=bool(args.resume),
            max_rows=max(0, int(args.max_rows or 0)),
            prompt_timeout_seconds=max(1.0, float(args.prompt_timeout_seconds or 90.0)),
            feature_only=bool(args.feature_only),
            lead_in_ms=max(0, int(args.lead_in_ms or 0)),
            tail_silence_ms=max(0, int(args.tail_silence_ms or 0)),
            takes_per_prompt=max(1, int(args.takes_per_prompt or 1)),
            provider_language=str(
                args.provider_language or DEFAULT_PROVIDER_LANGUAGE
            ).strip()
            or DEFAULT_PROVIDER_LANGUAGE,
            pronunciation_dict=dict(DEFAULT_PRONUNCIATION_DICT),
            audio_output_dir=audio_output_dir,
        )
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
