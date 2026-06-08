from __future__ import annotations

import argparse
import audioop
import io
import json
import math
import mimetypes
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from fastapi import HTTPException
import numpy as np
import requests

from app.api.routes.public_memorials import _memorial_transcribe_audio_blob
from app.services.memorial_openvoice import openvoice_clone_request, openvoice_synthesize_request_with_variant


DEFAULT_PROMPTS = [
    "Ich bin da. Erzaehl mir, was dich gerade bewegt.",
    "Rechtlich muss man die Dinge sauber unterscheiden, aber menschlich bleibe ich bei dir.",
]


def _private_profile_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_value = str(os.environ.get("EA_PRIVATE_MEMORIAL_PROFILE_DIR") or "").strip()
    if env_value:
        candidates.append(Path(env_value))
    candidates.extend(
        [
            Path("/data/memorial_data/private_memorial_profiles"),
            Path("/docker/EA/memorial_data/private_memorial_profiles"),
            Path("/mnt/pcloud/EA/private_memorial_profiles"),
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _resolve_private_profile_root(*, slug: str) -> Path:
    for candidate in _private_profile_dir_candidates():
        if (candidate / slug).is_dir():
            return candidate
    raise RuntimeError(f"private_profile_root_missing:{slug}")


def _voice_profile_dir(*, slug: str) -> Path:
    return _resolve_private_profile_root(slug=slug) / slug / "voice_profile"


def _voice_config_path(*, slug: str) -> Path:
    return _resolve_private_profile_root(slug=slug) / slug / "tts_voice.json"


def _optimization_dir(*, slug: str) -> Path:
    return _voice_profile_dir(slug=slug) / "optimization"


def _preview_dir(*, slug: str) -> Path:
    return _optimization_dir(slug=slug) / "previews"


def _candidate_cache_path(*, slug: str) -> Path:
    return _optimization_dir(slug=slug) / "candidate_cache.json"


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _ffprobe_duration_seconds(path: Path) -> float:
    completed = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return 0.0
    try:
        return max(0.0, float((completed.stdout or "0").strip() or "0"))
    except ValueError:
        return 0.0


def _extract_segment_to_wav(*, source: Path, start_seconds: float, duration_seconds: float, out_path: Path) -> None:
    completed = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{max(0.0, float(start_seconds)):.3f}",
            "-i",
            str(source),
            "-t",
            f"{max(0.4, float(duration_seconds)):.3f}",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not out_path.is_file():
        raise RuntimeError(f"segment_extract_failed:{source.name}:{completed.stderr.strip()[:180]}")


def _normalize_text(value: str) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    return "".join(ch for ch in text if ch.isalnum() or ch in {" ", "-", "_"}).strip()


def _score_transcript_self_speech(text: str) -> float:
    normalized = _normalize_text(text)
    if not normalized:
        return 0.0
    words = [item for item in normalized.replace("-", " ").split() if item]
    positives = {
        "ich",
        "mich",
        "mir",
        "mein",
        "meine",
        "meiner",
        "meinem",
        "meinen",
        "wir",
        "uns",
        "unser",
        "unsere",
    }
    negatives = {
        "amara",
        "community",
        "journalist",
        "journalistin",
        "outro",
        "moderator",
        "moderatorin",
        "interviewer",
        "interviewerin",
        "frage",
        "fragt",
        "sagt",
        "studio",
        "reporter",
        "beitrag",
        "sprecher",
        "kommentar",
        "untertitel",
    }
    positive_hits = sum(1 for word in words if word in positives)
    negative_hits = sum(1 for word in words if word in negatives)
    question_penalty = 1.2 if "?" in str(text or "") else 0.0
    length_bonus = min(len(words) / 24.0, 1.0)
    raw = (positive_hits * 1.6) + length_bonus - (negative_hits * 1.9) - question_penalty
    return max(0.0, min(1.0, 0.5 + (raw / 6.0)))


def _transcribe_audio_bytes(payload: bytes, *, content_type: str, slug: str, base_url: str) -> dict[str, object]:
    try:
        return _memorial_transcribe_audio_blob(payload=payload, content_type=content_type)
    except HTTPException as exc:
        if str(exc.detail or "") != "speech_transcriber_unavailable":
            raise
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    if not normalized_base_url:
        raise HTTPException(status_code=503, detail="speech_transcriber_unavailable")
    response = requests.post(
        f"{normalized_base_url}/memorials/{slug}/speech-transcribe",
        data=payload,
        headers={"content-type": content_type},
        timeout=120,
    )
    if response.status_code >= 400 or not response.ok:
        raise HTTPException(status_code=502, detail=f"speech_transcribe_http_failed:{response.status_code}")
    body = response.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="speech_transcribe_http_invalid_response")
    return body


def _list_source_audio_paths(*, slug: str) -> list[Path]:
    voice_profile_dir = _voice_profile_dir(slug=slug)
    if not voice_profile_dir.is_dir():
        return []
    disallowed_roots = {"curated", "generated_candidates", "loupe", "optimization"}
    derived_markers = (
        "bestof",
        "top3",
        "challenger",
        "openvoice-opt",
        "-cand-",
        "-00000s",
    )
    audio_paths: list[Path] = []
    for path in sorted(voice_profile_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in disallowed_roots for part in path.relative_to(voice_profile_dir).parts[:-1]):
            continue
        if path.suffix.lower() not in {".mp3", ".wav", ".m4a", ".mp4", ".aac", ".webm", ".ogg"}:
            continue
        if any(marker in path.name.lower() for marker in derived_markers):
            continue
        audio_paths.append(path)
    return audio_paths


def _tail_start_points(*, duration_seconds: float, tail_window_seconds: float, segment_seconds: float, step_seconds: float) -> list[float]:
    if duration_seconds <= 0:
        return [0.0]
    start_floor = max(0.0, duration_seconds - tail_window_seconds)
    start_ceiling = max(0.0, duration_seconds - segment_seconds - 2.0)
    starts: list[float] = []
    current = start_floor
    while current <= start_ceiling + 0.01:
        starts.append(round(current, 3))
        current += max(6.0, step_seconds)
    if not starts:
        starts.append(max(0.0, start_ceiling))
    return starts


def _collect_tail_candidates(
    *,
    slug: str,
    segment_seconds: float,
    tail_window_seconds: float,
    step_seconds: float,
    max_candidates: int,
    base_url: str,
) -> list[dict[str, object]]:
    work_dir = _optimization_dir(slug=slug) / "candidates"
    work_dir.mkdir(parents=True, exist_ok=True)
    cache = _load_candidate_cache(slug=slug)
    cache_changed = False
    ranked: list[dict[str, object]] = []
    for source_path in _list_source_audio_paths(slug=slug):
        duration_seconds = _ffprobe_duration_seconds(source_path)
        for start_seconds in _tail_start_points(
            duration_seconds=duration_seconds,
            tail_window_seconds=tail_window_seconds,
            segment_seconds=segment_seconds,
            step_seconds=step_seconds,
        ):
            segment_name = f"{source_path.stem}-{int(start_seconds):05d}s.wav"
            segment_path = work_dir / segment_name
            _extract_segment_to_wav(
                source=source_path,
                start_seconds=start_seconds,
                duration_seconds=segment_seconds,
                out_path=segment_path,
            )
            cache_key = f"{source_path.name}:{start_seconds:.3f}:{segment_seconds:.3f}"
            cached = cache.get(cache_key) or {}
            if (
                str(cached.get("segment_path") or "") == str(segment_path)
                and str(cached.get("transcript_text") or "").strip()
            ):
                ranked.append(dict(cached))
                continue
            payload = segment_path.read_bytes()
            transcript = _transcribe_audio_bytes(payload, content_type="audio/wav", slug=slug, base_url=base_url)
            transcript_text = str(transcript.get("transcript_text") or "").strip()
            transcript_score = _score_transcript_self_speech(transcript_text)
            tail_bias = 1.0 if duration_seconds <= 0 else min(1.0, start_seconds / max(duration_seconds, 1.0))
            total_score = (transcript_score * 0.82) + (tail_bias * 0.18)
            row = {
                "source_path": str(source_path),
                "segment_path": str(segment_path),
                "start_seconds": start_seconds,
                "duration_seconds": segment_seconds,
                "transcript_text": transcript_text,
                "transcript_score": round(transcript_score, 4),
                "tail_bias": round(tail_bias, 4),
                "score": round(total_score, 4),
            }
            ranked.append(row)
            cache[cache_key] = dict(row)
            cache_changed = True
    ranked.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    if cache_changed:
        _save_candidate_cache(slug=slug, cache=cache)
    return ranked[: max(1, int(max_candidates))]


def _candidate_sample_combinations(candidates: list[dict[str, object]], *, max_combinations: int) -> list[list[Path]]:
    sample_paths = [Path(str(item["segment_path"])) for item in candidates if str(item.get("segment_path") or "").strip()]
    combinations: list[list[Path]] = []
    blueprints = [
        [0],
        [0, 1],
        [0, 1, 2],
        [0, 2],
        [1],
        [1, 2],
        [2],
    ]
    seen: set[tuple[str, ...]] = set()
    for blueprint in blueprints:
        selection = [sample_paths[index] for index in blueprint if index < len(sample_paths)]
        if not selection:
            continue
        key = tuple(str(path) for path in selection)
        if key in seen:
            continue
        seen.add(key)
        combinations.append(selection)
        if len(combinations) >= max(1, int(max_combinations)):
            break
    return combinations


def _wav_metrics_from_bytes(payload: bytes) -> dict[str, float]:
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        raw = wav_file.readframes(frame_count)
    if channels > 1:
        raw = audioop.tomono(raw, sample_width, 0.5, 0.5)
    chunk_frames = max(1, int(sample_rate * 0.04))
    chunk_size = chunk_frames * sample_width
    rms_values: list[float] = []
    silent_frames = 0
    total_frames = 0
    for start in range(0, len(raw), chunk_size):
        chunk = raw[start:start + chunk_size]
        if not chunk:
            continue
        rms = float(audioop.rms(chunk, sample_width))
        rms_values.append(rms)
        total_frames += 1
        if rms < 450:
            silent_frames += 1
    duration_seconds = frame_count / float(sample_rate or 1)
    zero_crossings = 0
    previous = None
    for offset in range(0, len(raw) - sample_width + 1, sample_width):
        sample = int.from_bytes(raw[offset:offset + sample_width], "little", signed=True)
        if previous is not None and ((previous < 0 <= sample) or (previous > 0 >= sample)):
            zero_crossings += 1
        previous = sample
    mean_rms = sum(rms_values) / float(len(rms_values) or 1)
    spectral_metrics = _spectral_metrics(raw=raw, sample_width=sample_width, sample_rate=sample_rate)
    return {
        "duration_seconds": duration_seconds,
        "mean_rms": mean_rms,
        "speech_ratio": 1.0 - (silent_frames / float(total_frames or 1)),
        "zero_crossing_rate": zero_crossings / float(max(1, len(raw) // max(1, sample_width))),
        **spectral_metrics,
    }


def _wav_metrics_from_path(path: Path) -> dict[str, float]:
    return _wav_metrics_from_bytes(path.read_bytes())


def _pcm_float_array(*, raw: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        return (data - 128.0) / 128.0
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    raise RuntimeError(f"unsupported_sample_width:{sample_width}")


def _estimate_pitch_hz(frame: np.ndarray, sample_rate: int) -> float:
    centered = frame - float(np.mean(frame))
    energy = float(np.sqrt(np.mean(np.square(centered))) or 0.0)
    if energy < 0.01:
        return 0.0
    correlation = np.correlate(centered, centered, mode="full")[len(centered) - 1 :]
    min_lag = max(1, int(sample_rate / 280.0))
    max_lag = min(len(correlation) - 1, int(sample_rate / 70.0))
    if max_lag <= min_lag:
        return 0.0
    search = correlation[min_lag : max_lag + 1]
    if search.size == 0:
        return 0.0
    lag = int(np.argmax(search)) + min_lag
    if lag <= 0:
        return 0.0
    return float(sample_rate / lag)


def _spectral_metrics(*, raw: bytes, sample_width: int, sample_rate: int) -> dict[str, float]:
    samples = _pcm_float_array(raw=raw, sample_width=sample_width)
    if samples.size == 0:
        return {
            "pitch_hz": 0.0,
            "spectral_centroid": 0.0,
            "spectral_bandwidth": 0.0,
            "spectral_rolloff": 0.0,
            "spectral_flatness": 0.0,
            "low_energy_ratio": 0.0,
            "mid_energy_ratio": 0.0,
            "high_energy_ratio": 0.0,
        }
    frame_size = max(256, int(sample_rate * 0.04))
    hop_size = max(128, int(frame_size * 0.5))
    window = np.hanning(frame_size).astype(np.float32)
    centroid_values: list[float] = []
    bandwidth_values: list[float] = []
    rolloff_values: list[float] = []
    flatness_values: list[float] = []
    pitch_values: list[float] = []
    low_values: list[float] = []
    mid_values: list[float] = []
    high_values: list[float] = []
    freqs = np.fft.rfftfreq(frame_size, 1.0 / float(sample_rate or 1))
    low_mask = freqs < 500.0
    high_mask = freqs >= 2000.0
    mid_mask = (~low_mask) & (~high_mask)
    for start in range(0, max(1, samples.size - frame_size + 1), hop_size):
        frame = samples[start : start + frame_size]
        if frame.size < frame_size:
            break
        rms = float(np.sqrt(np.mean(np.square(frame))) or 0.0)
        if rms < 0.01:
            continue
        pitch = _estimate_pitch_hz(frame, sample_rate)
        if pitch > 0.0:
            pitch_values.append(pitch)
        spectrum = np.abs(np.fft.rfft(frame * window))
        power = np.square(spectrum) + 1e-9
        total_power = float(np.sum(power))
        if total_power <= 0.0:
            continue
        centroid = float(np.sum(freqs * power) / total_power)
        centroid_values.append(centroid)
        bandwidth = float(np.sqrt(np.sum(np.square(freqs - centroid) * power) / total_power))
        bandwidth_values.append(bandwidth)
        cumsum = np.cumsum(power)
        rolloff_idx = int(np.searchsorted(cumsum, total_power * 0.85))
        rolloff_idx = max(0, min(rolloff_idx, len(freqs) - 1))
        rolloff_values.append(float(freqs[rolloff_idx]))
        flatness_values.append(float(math.exp(np.mean(np.log(power))) / (np.mean(power) + 1e-9)))
        low_values.append(float(np.sum(power[low_mask]) / total_power))
        mid_values.append(float(np.sum(power[mid_mask]) / total_power))
        high_values.append(float(np.sum(power[high_mask]) / total_power))
    def _mean(values: list[float]) -> float:
        return float(sum(values) / float(len(values) or 1))
    return {
        "pitch_hz": _mean(pitch_values),
        "spectral_centroid": _mean(centroid_values),
        "spectral_bandwidth": _mean(bandwidth_values),
        "spectral_rolloff": _mean(rolloff_values),
        "spectral_flatness": _mean(flatness_values),
        "low_energy_ratio": _mean(low_values),
        "mid_energy_ratio": _mean(mid_values),
        "high_energy_ratio": _mean(high_values),
    }


def _text_similarity(expected: str, actual: str) -> float:
    left = {item for item in _normalize_text(expected).split() if item}
    right = {item for item in _normalize_text(actual).split() if item}
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right) or 1)


def _voice_feature_similarity(reference_metrics: dict[str, float], candidate_metrics: dict[str, float]) -> float:
    duration_delta = min(1.0, abs(reference_metrics["duration_seconds"] - candidate_metrics["duration_seconds"]) / 8.0)
    rms_delta = min(
        1.0,
        abs(math.log((reference_metrics["mean_rms"] + 1.0) / (candidate_metrics["mean_rms"] + 1.0))) / 1.4,
    )
    speech_delta = min(1.0, abs(reference_metrics["speech_ratio"] - candidate_metrics["speech_ratio"]))
    zcr_delta = min(1.0, abs(reference_metrics["zero_crossing_rate"] - candidate_metrics["zero_crossing_rate"]) / 0.12)
    pitch_delta = min(
        1.0,
        abs(reference_metrics.get("pitch_hz", 0.0) - candidate_metrics.get("pitch_hz", 0.0)) / 80.0,
    )
    centroid_delta = min(
        1.0,
        abs(reference_metrics.get("spectral_centroid", 0.0) - candidate_metrics.get("spectral_centroid", 0.0)) / 900.0,
    )
    bandwidth_delta = min(
        1.0,
        abs(reference_metrics.get("spectral_bandwidth", 0.0) - candidate_metrics.get("spectral_bandwidth", 0.0)) / 1200.0,
    )
    rolloff_delta = min(
        1.0,
        abs(reference_metrics.get("spectral_rolloff", 0.0) - candidate_metrics.get("spectral_rolloff", 0.0)) / 1400.0,
    )
    flatness_delta = min(
        1.0,
        abs(reference_metrics.get("spectral_flatness", 0.0) - candidate_metrics.get("spectral_flatness", 0.0)) / 0.12,
    )
    low_delta = min(
        1.0,
        abs(reference_metrics.get("low_energy_ratio", 0.0) - candidate_metrics.get("low_energy_ratio", 0.0)) / 0.25,
    )
    mid_delta = min(
        1.0,
        abs(reference_metrics.get("mid_energy_ratio", 0.0) - candidate_metrics.get("mid_energy_ratio", 0.0)) / 0.25,
    )
    high_delta = min(
        1.0,
        abs(reference_metrics.get("high_energy_ratio", 0.0) - candidate_metrics.get("high_energy_ratio", 0.0)) / 0.25,
    )
    total_delta = (
        (duration_delta * 0.08)
        + (rms_delta * 0.08)
        + (speech_delta * 0.08)
        + (zcr_delta * 0.08)
        + (pitch_delta * 0.16)
        + (centroid_delta * 0.16)
        + (bandwidth_delta * 0.12)
        + (rolloff_delta * 0.08)
        + (flatness_delta * 0.08)
        + (low_delta * 0.06)
        + (mid_delta * 0.05)
        + (high_delta * 0.05)
    )
    return max(0.0, 1.0 - total_delta)


def _clone_openvoice_candidate(*, slug: str, voice_id: str, sample_paths: list[Path]) -> str:
    return openvoice_clone_request(
        slug=slug,
        voice_label=f"{slug} optimized clone",
        sample_paths=sample_paths,
        voice_id=voice_id,
    )


def _evaluate_clone(
    *,
    voice_id: str,
    sample_paths: list[Path],
    selected_candidates: list[dict[str, object]],
    prompts: list[str],
    base_voice_variant: str,
    slug: str,
    base_url: str,
    iteration_index: int,
    reference_mimic_count: int,
) -> dict[str, object]:
    reference_metrics = [_wav_metrics_from_path(path) for path in sample_paths if path.is_file()]
    if not reference_metrics:
        raise RuntimeError("reference_metrics_missing")
    average_reference = {
        key: sum(item[key] for item in reference_metrics) / float(len(reference_metrics))
        for key in reference_metrics[0].keys()
    }
    prompt_results: list[dict[str, object]] = []
    prompt_total_score = 0.0
    iteration_preview_dir = _preview_dir(slug=slug) / f"iteration-{iteration_index:02d}-{voice_id}"
    iteration_preview_dir.mkdir(parents=True, exist_ok=True)
    copied_samples: list[str] = []
    for sample_index, sample_path in enumerate(sample_paths, start=1):
        sample_copy = iteration_preview_dir / f"reference-sample-{sample_index:02d}{sample_path.suffix or '.wav'}"
        _write_bytes(sample_copy, sample_path.read_bytes())
        copied_samples.append(str(sample_copy))
    for prompt in prompts:
        audio_bytes, content_type = openvoice_synthesize_request_with_variant(
            text=prompt,
            voice_id=voice_id,
            lang="de-AT",
            base_voice_variant=base_voice_variant,
        )
        extension = mimetypes.guess_extension(str(content_type or "audio/wav").split(";", 1)[0].strip().lower()) or ".wav"
        prompt_slug = _normalize_text(prompt).replace(" ", "-")[:48] or "sample"
        preview_path = iteration_preview_dir / f"{prompt_slug}{extension}"
        _write_bytes(preview_path, audio_bytes)
        transcription = _transcribe_audio_bytes(audio_bytes, content_type=content_type, slug=slug, base_url=base_url)
        transcript_text = str(transcription.get("transcript_text") or "").strip()
        roundtrip_score = _text_similarity(prompt, transcript_text)
        feature_score = _voice_feature_similarity(average_reference, _wav_metrics_from_bytes(audio_bytes))
        prompt_score = (roundtrip_score * 0.52) + (feature_score * 0.48)
        prompt_total_score += prompt_score
        prompt_results.append(
            {
                "prompt": prompt,
                "transcript_text": transcript_text,
                "roundtrip_score": round(roundtrip_score, 4),
                "feature_score": round(feature_score, 4),
                "score": round(prompt_score, 4),
                "preview_path": str(preview_path),
            }
        )
    reference_mimics: list[dict[str, object]] = []
    mimic_total_score = 0.0
    mimic_candidates = [
        item
        for item in selected_candidates
        if str(item.get("transcript_text") or "").strip()
        and len(str(item.get("transcript_text") or "").split()) >= 8
    ][: max(1, int(reference_mimic_count))]
    for mimic_index, candidate in enumerate(mimic_candidates, start=1):
        transcript_text = str(candidate.get("transcript_text") or "").strip()
        reference_path = Path(str(candidate.get("segment_path") or ""))
        if not reference_path.is_file() or not transcript_text:
            continue
        audio_bytes, content_type = openvoice_synthesize_request_with_variant(
            text=transcript_text,
            voice_id=voice_id,
            lang="de-AT",
            base_voice_variant=base_voice_variant,
        )
        extension = mimetypes.guess_extension(str(content_type or "audio/wav").split(";", 1)[0].strip().lower()) or ".wav"
        preview_path = iteration_preview_dir / f"mimic-reference-{mimic_index:02d}{extension}"
        _write_bytes(preview_path, audio_bytes)
        synthesized_metrics = _wav_metrics_from_bytes(audio_bytes)
        reference_metrics = _wav_metrics_from_path(reference_path)
        acoustic_similarity = _voice_feature_similarity(reference_metrics, synthesized_metrics)
        mimic_total_score += acoustic_similarity
        reference_mimics.append(
            {
                "reference_path": str(reference_path),
                "transcript_text": transcript_text,
                "score": round(acoustic_similarity, 4),
                "preview_path": str(preview_path),
            }
        )
    prompt_average = prompt_total_score / float(len(prompt_results) or 1)
    mimic_average = mimic_total_score / float(len(reference_mimics) or 1) if reference_mimics else 0.0
    aggregate_score = (mimic_average * 0.68) + (prompt_average * 0.32 if prompt_results else 0.0)
    return {
        "voice_id": voice_id,
        "score": round(aggregate_score, 4),
        "prompt_average_score": round(prompt_average, 4),
        "mimic_average_score": round(mimic_average, 4),
        "prompts": prompt_results,
        "reference_mimics": reference_mimics,
        "reference_metrics": {key: round(value, 4) for key, value in average_reference.items()},
        "preview_dir": str(iteration_preview_dir),
        "reference_sample_paths": copied_samples,
    }


def _load_existing_voice_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_candidate_cache(*, slug: str) -> dict[str, dict[str, object]]:
    path = _candidate_cache_path(slug=slug)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): dict(value) for key, value in payload.items() if isinstance(key, str) and isinstance(value, dict)}


def _save_candidate_cache(*, slug: str, cache: dict[str, dict[str, object]]) -> Path:
    path = _candidate_cache_path(slug=slug)
    _write_json(path, cache)
    return path


def _write_preview_index(*, slug: str, iterations: list[dict[str, object]], best_voice_id: str) -> Path:
    path = _preview_dir(slug=slug) / "README.md"
    lines = [
        f"# {slug} OpenVoice Optimization Previews",
        "",
        f"Winner: `{best_voice_id}`",
        "",
    ]
    for iteration in iterations:
        lines.append(f"## Iteration {iteration['iteration']} · `{iteration['voice_id']}` · score {iteration['score']}")
        lines.append("")
        for sample_path in iteration.get("sample_paths", []):
            lines.append(f"- Reference sample: `{sample_path}`")
        evaluation = iteration.get("evaluation") or {}
        for prompt_row in evaluation.get("prompts", []):
            lines.append(
                "- Preview: "
                f"`{prompt_row.get('preview_path', '')}` "
                f"(roundtrip {prompt_row.get('roundtrip_score')}, feature {prompt_row.get('feature_score')})"
            )
            lines.append(f"  transcript: {prompt_row.get('transcript_text', '')}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def _write_voice_config(
    *,
    slug: str,
    best_voice_id: str,
    best_iteration: dict[str, object],
    selected_candidates: list[dict[str, object]],
    base_voice_variant: str,
) -> Path:
    path = _voice_config_path(slug=slug)
    payload = _load_existing_voice_config(path)
    sample_note = ", ".join(Path(str(item.get("segment_path") or "")).name for item in selected_candidates[:3])
    payload.update(
        {
            "tts_plugin": "openvoice_local",
            "tts_mode": "openvoice_local",
            "tts_plugin_voice_id": best_voice_id,
            "voice_profile_id": best_voice_id,
            "voice_label": "Manfred Hoza · optimierter OpenVoice-Klon",
            "lang": "de-AT",
            "rate": float(payload.get("rate") or 0.92),
            "pitch": float(payload.get("pitch") or 0.92),
            "volume": float(payload.get("volume") or 1.0),
            "tts_base_voice_variant": base_voice_variant,
            "consent_basis": str(payload.get("consent_basis") or "generic_or_owner_consented_voice"),
            "synthetic_voice_clone_of_memorial_person": True,
            "notes": (
                "OpenVoice-Optimierung aus spaeten YouTube-Interviewsegmenten. "
                f"Gewinner {best_voice_id} mit Score {best_iteration.get('score')} "
                f"mit Basisvariante {base_voice_variant} aus {sample_note}."
            ),
        }
    )
    _write_json(path, payload)
    return path


def optimize_openvoice_clone(
    *,
    slug: str,
    max_candidates: int,
    max_combinations: int,
    max_iterations: int,
    segment_seconds: float,
    tail_window_seconds: float,
    step_seconds: float,
    accept_threshold: float,
    base_voice_variants: list[str],
    apply_best: bool,
    prompts: list[str],
    base_url: str,
    reference_mimic_count: int,
) -> dict[str, object]:
    candidates = _collect_tail_candidates(
        slug=slug,
        segment_seconds=segment_seconds,
        tail_window_seconds=tail_window_seconds,
        step_seconds=step_seconds,
        max_candidates=max_candidates,
        base_url=base_url,
    )
    if not candidates:
        raise RuntimeError("voice_tail_candidates_missing")
    combinations = _candidate_sample_combinations(candidates, max_combinations=max_combinations)
    if not combinations:
        raise RuntimeError("voice_candidate_combinations_missing")
    iterations: list[dict[str, object]] = []
    best_iteration: dict[str, object] | None = None
    iteration_index = 0
    normalized_variants = [str(item).strip() for item in base_voice_variants if str(item).strip()]
    if not normalized_variants:
        normalized_variants = ["balanced"]
    for sample_paths in combinations:
        selected_candidates = [
            item for item in candidates if Path(str(item.get("segment_path") or "")) in set(sample_paths)
        ]
        for base_voice_variant in normalized_variants:
            iteration_index += 1
            if iteration_index > max_iterations:
                break
            voice_id = f"{slug}-openvoice-opt-{iteration_index:02d}"
            cloned_voice_id = _clone_openvoice_candidate(slug=slug, voice_id=voice_id, sample_paths=sample_paths)
            evaluation = _evaluate_clone(
                voice_id=cloned_voice_id,
                sample_paths=sample_paths,
                selected_candidates=selected_candidates,
                prompts=prompts,
                base_voice_variant=base_voice_variant,
                slug=slug,
                base_url=base_url,
                iteration_index=iteration_index,
                reference_mimic_count=reference_mimic_count,
            )
            iteration_payload = {
                "iteration": iteration_index,
                "voice_id": cloned_voice_id,
                "base_voice_variant": base_voice_variant,
                "score": round(
                    (float(evaluation.get("score") or 0.0) * 0.8)
                    + (sum(float(item.get("transcript_score") or 0.0) for item in selected_candidates) / float(len(selected_candidates) or 1) * 0.2),
                    4,
                ),
                "raw_evaluation_score": evaluation.get("score"),
                "sample_paths": [str(path) for path in sample_paths],
                "selected_candidates": selected_candidates,
                "evaluation": evaluation,
            }
            iterations.append(iteration_payload)
            if best_iteration is None or float(iteration_payload["score"]) > float(best_iteration["score"]):
                best_iteration = iteration_payload
            if float(iteration_payload["score"]) >= accept_threshold:
                break
        if iteration_index >= max_iterations:
            break
        if best_iteration is not None and float(best_iteration["score"]) >= accept_threshold:
            break
    if best_iteration is None:
        raise RuntimeError("voice_optimization_no_winner")
    report = {
        "slug": slug,
        "accept_threshold": accept_threshold,
        "base_voice_variant": base_voice_variant,
        "candidate_count": len(candidates),
        "selected_candidate_count": len(best_iteration["selected_candidates"]),
        "iterations": iterations,
        "best_iteration": best_iteration,
        "applied_config_path": "",
    }
    if apply_best:
        config_path = _write_voice_config(
            slug=slug,
            best_voice_id=str(best_iteration["voice_id"]),
            best_iteration=best_iteration,
            selected_candidates=list(best_iteration["selected_candidates"]),
            base_voice_variant=str(best_iteration.get("base_voice_variant") or normalized_variants[0]),
        )
        report["applied_config_path"] = str(config_path)
    preview_index_path = _write_preview_index(
        slug=slug,
        iterations=iterations,
        best_voice_id=str(best_iteration["voice_id"]),
    )
    report["preview_index_path"] = str(preview_index_path)
    report_path = _optimization_dir(slug=slug) / "openvoice_optimization_report.json"
    _write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize the memorial OpenVoice clone against late YouTube interview tails.")
    parser.add_argument("slug", nargs="?", default="manfred")
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument("--max-combinations", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--segment-seconds", type=float, default=22.0)
    parser.add_argument("--tail-window-seconds", type=float, default=240.0)
    parser.add_argument("--step-seconds", type=float, default=18.0)
    parser.add_argument("--accept-threshold", type=float, default=0.74)
    parser.add_argument("--base-voice-variant", default="balanced,high")
    parser.add_argument("--base-url", default=os.environ.get("EA_MEMORIAL_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--reference-mimic-count", type=int, default=2)
    parser.add_argument("--no-apply", action="store_true")
    parser.add_argument("--prompt", action="append", dest="prompts")
    args = parser.parse_args()
    prompts = [item.strip() for item in (args.prompts or DEFAULT_PROMPTS) if str(item).strip()]
    base_voice_variants = [
        item.strip()
        for item in str(args.base_voice_variant or "balanced").split(",")
        if item.strip()
    ]
    try:
        report = optimize_openvoice_clone(
            slug=args.slug,
            max_candidates=max(1, args.max_candidates),
            max_combinations=max(1, args.max_combinations),
            max_iterations=max(1, args.max_iterations),
            segment_seconds=max(6.0, args.segment_seconds),
            tail_window_seconds=max(30.0, args.tail_window_seconds),
            step_seconds=max(6.0, args.step_seconds),
            accept_threshold=max(0.1, min(0.99, args.accept_threshold)),
            base_voice_variants=base_voice_variants,
            apply_best=not args.no_apply,
            prompts=prompts,
            base_url=str(args.base_url or "").strip(),
            reference_mimic_count=max(1, int(args.reference_mimic_count or 1)),
        )
    except HTTPException as exc:
        raise SystemExit(str(exc.detail))
    except Exception as exc:
        raise SystemExit(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
