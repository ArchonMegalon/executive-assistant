#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import memorial_audio_probe as audio_probe
except ModuleNotFoundError:  # pragma: no cover - import shape depends on invocation mode
    from scripts import memorial_audio_probe as audio_probe


_HTTP_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 EA-Memorial-Validator/1.0"
)


def _pure_python_prompt_wav_bytes(text: str) -> bytes:
    sample_rate = 16000
    amplitude = 14000
    segments = max(4, min(18, len(str(text or "").split()) * 2))
    segment_frames = int(sample_rate * 0.16)
    silence_frames = int(sample_rate * 0.035)
    frames = bytearray()
    for index in range(segments):
        frequency = 280.0 + float((index % 5) * 62)
        for frame_index in range(segment_frames):
            envelope = min(1.0, frame_index / max(1, int(sample_rate * 0.02)))
            tail = min(1.0, (segment_frames - frame_index) / max(1, int(sample_rate * 0.03)))
            gain = min(envelope, tail)
            sample = int(amplitude * gain * math.sin((2.0 * math.pi * frequency * frame_index) / sample_rate))
            frames.extend(struct.pack("<h", sample))
        frames.extend(b"\x00\x00" * silence_frames)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def _neutral_prompt_wav_bytes(text: str) -> bytes:
    espeak_bin = shutil.which("espeak-ng")
    ffmpeg_bin = shutil.which("ffmpeg")
    if not espeak_bin or not ffmpeg_bin:
        return _pure_python_prompt_wav_bytes(text)
    with tempfile.TemporaryDirectory(prefix="memorial-voice-loop-") as tmpdir:
        tmp_path = Path(tmpdir)
        raw_wav = tmp_path / "prompt.raw.wav"
        normalized_wav = tmp_path / "prompt.16k.wav"
        subprocess.run(
            [
                espeak_bin,
                "-v",
                "de",
                "-s",
                "155",
                "-p",
                "44",
                "-w",
                str(raw_wav),
                text,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(raw_wav),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(normalized_wav),
            ],
            check=True,
            capture_output=True,
        )
        return normalized_wav.read_bytes()


def _normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _post_json(url: str, payload: dict[str, Any], *, timeout: float = 90.0) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return int(getattr(response, "status", 0) or 0), json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload_dict = json.loads(body or "{}")
        except Exception:
            payload_dict = {"detail": body}
        return int(exc.code), payload_dict
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return 0, {"detail": f"request_failed:{type(exc).__name__}:{str(exc)[:180]}"}


def _post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": content_type,
            "Accept": "application/json",
            "User-Agent": _HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return int(getattr(response, "status", 0) or 0), json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload_dict = json.loads(body or "{}")
        except Exception:
            payload_dict = {"detail": body}
        return int(exc.code), payload_dict
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return 0, {"detail": f"request_failed:{type(exc).__name__}:{str(exc)[:180]}"}


def _post_json_binary_response(url: str, payload: dict[str, Any], *, timeout: float = 120.0) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/wav,application/octet-stream",
            "User-Agent": _HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                int(getattr(response, "status", 0) or 0),
                response.read(),
                str(response.headers.get("Content-Type") or "application/octet-stream"),
            )
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(), str(exc.headers.get("Content-Type") or "application/json")
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return 0, f"request_failed:{type(exc).__name__}:{str(exc)[:180]}".encode("utf-8"), "text/plain"


def _normalize_compare_text(value: str) -> str:
    lowered = str(value or "").lower().replace("ß", "ss")
    lowered = (
        lowered.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("á", "a")
        .replace("à", "a")
        .replace("é", "e")
        .replace("è", "e")
    )
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    tokens: list[str] = []
    for token in lowered.split():
        if token == "jo":
            tokens.append("ja")
            continue
        tokens.append(token)
    return " ".join(tokens)


def _token_overlap(expected: str, actual: str) -> dict[str, float]:
    expected_tokens = _normalize_compare_text(expected).split()
    actual_tokens = _normalize_compare_text(actual).split()
    if not expected_tokens or not actual_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    expected_set = set(expected_tokens)
    actual_set = set(actual_tokens)
    shared = expected_set & actual_set
    precision = len(shared) / max(1, len(actual_set))
    recall = len(shared) / max(1, len(expected_set))
    if precision + recall <= 0:
        f1 = 0.0
    else:
        f1 = (2.0 * precision * recall) / (precision + recall)
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _critical_tokens_missing(actual: str, critical_tokens: tuple[str, ...]) -> list[str]:
    actual_tokens = set(_normalize_compare_text(actual).split())
    missing: list[str] = []
    for token in critical_tokens:
        normalized = _normalize_compare_text(token)
        if normalized and normalized not in actual_tokens:
            missing.append(token)
    return missing


def _elapsed_ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000.0))


def _speech_transcriber_unavailable(status_code: int, payload: dict[str, Any]) -> bool:
    if int(status_code) != 503:
        return False
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    values = [
        payload.get("detail"),
        error.get("code") if isinstance(error, dict) else "",
        error.get("message") if isinstance(error, dict) else "",
        error.get("details") if isinstance(error, dict) else "",
    ]
    return any(str(value or "").strip() == "speech_transcriber_unavailable" for value in values)


def _contact_turn_candidate_score(
    payload: dict[str, Any],
    *,
    reference_answer: str,
    conversation_question: str,
) -> tuple[int, float, float]:
    answer_text = str(payload.get("answer") or "")
    transcript_text = str(payload.get("transcript_text") or "")
    fallback_reason = str(payload.get("fallback_reason") or "")
    reference_overlap = _token_overlap(reference_answer, answer_text)
    transcript_overlap = _token_overlap(conversation_question, transcript_text)
    score = 0
    if fallback_reason == "direct_contact_opening":
        score += 80
    if "hallo manfred" in _normalize_compare_text(transcript_text):
        score += 20
    score += int(round(reference_overlap["f1"] * 100))
    score += int(round(transcript_overlap["f1"] * 25))
    return score, float(reference_overlap["f1"]), float(transcript_overlap["f1"])


@dataclass
class ValidationCheck:
    status: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    slug: str
    base_url: str
    output_dir: str
    checks: list[ValidationCheck] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add(self, status: str, code: str, message: str, **detail: Any) -> None:
        self.checks.append(ValidationCheck(status=status, code=code, message=message, detail=detail))

    @property
    def failed(self) -> bool:
        return any(item.status == "fail" for item in self.checks)

    @property
    def warned(self) -> bool:
        return any(item.status == "warn" for item in self.checks)

    @property
    def status(self) -> str:
        if self.failed:
            return "fail"
        if self.warned:
            return "warn"
        return "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "output_dir": self.output_dir,
            "status": self.status,
            "artifacts": self.artifacts,
            "metrics": self.metrics,
            "checks": [
                {
                    "status": item.status,
                    "code": item.code,
                    "message": item.message,
                    "detail": item.detail,
                }
                for item in self.checks
            ],
        }


def _save_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _evaluate_similarity(
    report: ValidationReport,
    *,
    code_prefix: str,
    expected: str,
    actual: str,
    min_f1: float = 0.82,
    gold_mode: bool = False,
    critical_tokens: tuple[str, ...] = (),
) -> None:
    overlap = _token_overlap(expected, actual)
    report.metrics[f"{code_prefix}_expected_chars"] = len(expected)
    report.metrics[f"{code_prefix}_actual_chars"] = len(actual)
    report.metrics[f"{code_prefix}_f1"] = overlap["f1"]
    if not _normalize_compare_text(actual):
        report.add("fail", f"{code_prefix}_transcript_empty", "No transcript came back from speech-to-text.", expected=expected, actual=actual)
        return
    missing_critical_tokens = _critical_tokens_missing(actual, critical_tokens) if gold_mode else []
    if missing_critical_tokens:
        report.add(
            "fail",
            f"{code_prefix}_critical_tokens_missing",
            "Transcript dropped or substituted critical memorial-gold words.",
            expected=expected,
            actual=actual,
            missing_tokens=missing_critical_tokens,
            **overlap,
        )
        return
    expected_tokens = _normalize_compare_text(expected).split()
    actual_tokens = set(_normalize_compare_text(actual).split())
    if 0 < len(expected_tokens) <= 2 and all(token in actual_tokens for token in expected_tokens):
        report.add(
            "pass",
            f"{code_prefix}_short_phrase_ok",
            "Transcript contains the complete expected short phrase.",
            expected=expected,
            actual=actual,
            **overlap,
        )
        return
    if gold_mode:
        if overlap["f1"] >= min_f1:
            report.add(
                "pass",
                f"{code_prefix}_gold_similarity_ok",
                "Transcript meets the stricter memorial-gold similarity threshold.",
                expected=expected,
                actual=actual,
                min_f1=min_f1,
                **overlap,
            )
            return
        report.add(
            "fail",
            f"{code_prefix}_gold_similarity_bad",
            "Transcript does not meet the stricter memorial-gold similarity threshold.",
            expected=expected,
            actual=actual,
            min_f1=min_f1,
            **overlap,
        )
        return
    if overlap["f1"] >= 0.82:
        report.add("pass", f"{code_prefix}_similarity_ok", "Transcript matches the expected spoken content closely.", expected=expected, actual=actual, **overlap)
        return
    if overlap["f1"] >= 0.6:
        report.add("warn", f"{code_prefix}_similarity_soft", "Transcript is usable but drifts from the expected spoken content.", expected=expected, actual=actual, **overlap)
        return
    report.add("fail", f"{code_prefix}_similarity_bad", "Transcript diverges too far from the expected spoken content.", expected=expected, actual=actual, **overlap)


def validate_memorial_voice_loop(
    *,
    slug: str,
    base_url: str,
    output_dir: Path,
    direct_text: str,
    conversation_question: str,
    present_world_question: str = "Welches Wetter haben wir heute?",
    require_stt: bool = False,
    gold_mode: bool = False,
    direct_min_f1: float = 0.92,
    conversation_min_f1: float = 0.90,
    critical_tokens: tuple[str, ...] = (),
) -> ValidationReport:
    normalized_base_url = _normalize_base_url(base_url)
    report = ValidationReport(slug=slug, base_url=normalized_base_url, output_dir=str(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    synth_status, synth_audio, synth_content_type = _post_json_binary_response(
        f"{normalized_base_url}/memorials/{urllib.parse.quote(slug)}/speech-synthesize",
        {"text": direct_text},
    )
    report.metrics["speech_synthesize_ms"] = _elapsed_ms(started)
    if synth_status != 200 or not synth_audio:
        report.add("fail", "direct_tts_failed", "Direct speech synthesis did not return audio.", status_code=synth_status)
        return report
    direct_audio_path = output_dir / f"{slug}-direct-tts.wav"
    _save_bytes(direct_audio_path, synth_audio)
    report.artifacts["direct_tts_audio"] = str(direct_audio_path)

    direct_audio_probe = audio_probe.analyze_audio(
        direct_audio_path,
        threshold=0.012,
        min_duration=0.6,
        min_lead_silence=0.01,
        min_tail_silence=0.04,
        min_rms=0.0015,
        max_clip_ratio=0.02,
    )
    report.metrics["direct_tts_audio_status"] = direct_audio_probe.status
    if direct_audio_probe.failed:
        report.add("fail", "direct_tts_audio_bad", "Synthesized audio failed basic signal checks.", findings=direct_audio_probe.as_dict())
    elif direct_audio_probe.warned:
        report.add("warn", "direct_tts_audio_warn", "Synthesized audio is usable but acoustically rough.", findings=direct_audio_probe.as_dict())
    else:
        report.add("pass", "direct_tts_audio_ok", "Synthesized audio passed signal checks.")

    transcriber_available = True
    started = time.perf_counter()
    transcribe_status, transcribe_payload = _post_binary(
        f"{normalized_base_url}/memorials/{urllib.parse.quote(slug)}/speech-transcribe",
        synth_audio,
        content_type=synth_content_type,
    )
    report.metrics["speech_transcribe_ms"] = _elapsed_ms(started)
    if transcribe_status != 200:
        if _speech_transcriber_unavailable(transcribe_status, transcribe_payload):
            transcriber_available = False
            status = "fail" if require_stt else "info"
            report.add(
                status,
                "direct_tts_transcriber_unavailable",
                "Speech-to-text is not configured; synthesized output transcript proof cannot be completed.",
                status_code=transcribe_status,
                payload=transcribe_payload,
            )
        else:
            report.add("fail", "direct_tts_transcribe_failed", "Speech-to-text could not read synthesized output.", status_code=transcribe_status, payload=transcribe_payload)
            return report
    else:
        direct_transcript = str(transcribe_payload.get("transcript_text") or "")
        report.metrics["direct_tts_transcriber"] = str(transcribe_payload.get("transcriber") or "")
        _evaluate_similarity(
            report,
            code_prefix="direct_tts",
            expected=direct_text,
            actual=direct_transcript,
            min_f1=direct_min_f1,
            gold_mode=gold_mode,
            critical_tokens=critical_tokens,
        )

    started = time.perf_counter()
    chat_status, chat_payload = _post_json(
        f"{normalized_base_url}/memorials/{urllib.parse.quote(slug)}/chat",
        {"question": conversation_question},
    )
    report.metrics["chat_reference_ms"] = _elapsed_ms(started)
    if chat_status != 200:
        report.add("fail", "chat_reference_failed", "Reference chat answer could not be generated.", status_code=chat_status, payload=chat_payload)
        return report
    reference_answer = str(chat_payload.get("answer") or "")
    if not _normalize_compare_text(reference_answer):
        report.add("fail", "chat_reference_empty", "Reference chat answer came back empty.")
        return report
    report.metrics["reference_answer_chars"] = len(reference_answer)
    if any(token in _normalize_compare_text(reference_answer) for token in ("schach", "familie", "familien")):
        report.add(
            "fail",
            "chat_reference_domain_drift",
            "Reference chat answer drifted into the wrong domain.",
            question=conversation_question,
            answer=reference_answer,
        )
        return report

    started = time.perf_counter()
    present_status, present_payload = _post_json(
        f"{normalized_base_url}/memorials/{urllib.parse.quote(slug)}/chat",
        {"question": present_world_question},
    )
    report.metrics["present_world_chat_ms"] = _elapsed_ms(started)
    if present_status != 200:
        report.add(
            "fail",
            "present_world_reference_failed",
            "Present-world reference answer could not be generated.",
            status_code=present_status,
            payload=present_payload,
        )
        return report
    present_answer = str(present_payload.get("answer") or "")
    present_reason = str(present_payload.get("fallback_reason") or "")
    present_policy = str(present_payload.get("current_world_policy") or "")
    report.metrics["present_world_answer_chars"] = len(present_answer)
    if present_reason == "present_world_search":
        report.add(
            "fail",
            "present_world_search_forbidden",
            "Memorial present-world questions must stay local-source-only and cannot use internet search.",
            question=present_world_question,
            answer=present_answer,
        )
        return report
    if present_reason != "present_world_guardrail":
        report.add(
            "fail",
            "present_world_wrong_route",
            "Present-world question did not route through the dedicated current-world handling.",
            question=present_world_question,
            fallback_reason=present_reason,
            answer=present_answer,
        )
        return report
    if present_policy != "local_memories_and_conversation_only_no_internet_search":
        report.add(
            "fail",
            "present_world_policy_not_local_only",
            "Memorial current-world handling must explicitly stay local-source-only.",
            question=present_world_question,
            fallback_reason=present_reason,
            current_world_policy=present_policy,
            answer=present_answer,
        )
        return report
    if present_payload.get("sources"):
        report.add(
            "fail",
            "present_world_sources_forbidden",
            "Memorial current-world handling must not return internet/current-world sources.",
            question=present_world_question,
            sources=present_payload.get("sources"),
            answer=present_answer,
        )
        return report
    normalized_present_answer = _normalize_compare_text(present_answer)
    has_unknown_boundary = (
        all(token in normalized_present_answer for token in ("kann", "man", "nicht", "sagen"))
        or all(token in normalized_present_answer for token in ("weiß", "nicht"))
        or all(token in normalized_present_answer for token in ("weiss", "nicht"))
    )
    has_memory_boundary = (
        any(token in normalized_present_answer for token in ("erinnerung", "erinnerungen"))
        and "nicht" in normalized_present_answer
        and "sagen" in normalized_present_answer
    )
    has_no_memory_boundary = (
        ("erinnerung" in normalized_present_answer and "keine" in normalized_present_answer)
        or all(token in normalized_present_answer for token in ("weiß", "nicht"))
        or all(token in normalized_present_answer for token in ("weiss", "nicht"))
    )
    has_weather_boundary = (
        "wetter" in normalized_present_answer
        and "nicht" in normalized_present_answer
        and any(token in normalized_present_answer for token in ("sehe", "sehen"))
    )
    if not (has_unknown_boundary or has_memory_boundary or has_no_memory_boundary or has_weather_boundary):
        report.add(
            "fail",
            "present_world_missing_memory_boundary",
            "Present-world answer did not clearly stay inside local-memory boundaries.",
            question=present_world_question,
            answer=present_answer,
        )
        return report
    if any(token in normalized_present_answer for token in ("schach", "familie", "familien", "mehr", "vergessen")):
        report.add(
            "fail",
            "present_world_domain_drift",
            "Present-world answer drifted into memorial archive content.",
            question=present_world_question,
            answer=present_answer,
        )
        return report
    report.add(
        "pass",
        "present_world_route_ok",
        "Present-world question stayed on the dedicated direct-answer route.",
        question=present_world_question,
        fallback_reason=present_reason,
    )

    started = time.perf_counter()
    try:
        prompt_audio = _neutral_prompt_wav_bytes(conversation_question)
        prompt_status = 200 if prompt_audio else 0
        prompt_content_type = "audio/wav"
    except Exception as exc:
        prompt_status = 0
        prompt_audio = b""
        prompt_content_type = "audio/wav"
        prompt_error = f"{type(exc).__name__}:{str(exc)[:180]}"
    else:
        prompt_error = ""
    report.metrics["synthetic_prompt_synthesize_ms"] = _elapsed_ms(started)
    report.metrics["synthetic_prompt_source"] = "local_neutral_prompt"
    if prompt_status != 200 or not prompt_audio:
        report.add("fail", "synthetic_prompt_failed", "Could not synthesize the synthetic question loop prompt.", status_code=prompt_status, detail=prompt_error)
        return report
    prompt_audio_path = output_dir / f"{slug}-synthetic-question.wav"
    _save_bytes(prompt_audio_path, prompt_audio)
    report.artifacts["synthetic_question_audio"] = str(prompt_audio_path)

    started = time.perf_counter()
    turn_status, turn_payload = _post_binary(
        f"{normalized_base_url}/memorials/{urllib.parse.quote(slug)}/conversation-turn",
        prompt_audio,
        content_type=prompt_content_type,
    )
    report.metrics["conversation_turn_total_ms"] = _elapsed_ms(started)
    if turn_status != 200:
        report.add("fail", "conversation_turn_failed", "Conversation turn did not return a valid response.", status_code=turn_status, payload=turn_payload)
        return report
    if _normalize_compare_text(reference_answer) in {
        _normalize_compare_text("Ja. Sag es mir."),
        _normalize_compare_text("Ich höre dich. Sag es mir in Ruhe."),
    }:
        first_score, _, _ = _contact_turn_candidate_score(
            dict(turn_payload),
            reference_answer=reference_answer,
            conversation_question=conversation_question,
        )
        if first_score < 120:
            retry_started = time.perf_counter()
            retry_status, retry_payload = _post_binary(
                f"{normalized_base_url}/memorials/{urllib.parse.quote(slug)}/conversation-turn",
                prompt_audio,
                content_type=prompt_content_type,
            )
            report.metrics["conversation_turn_retry_ms"] = _elapsed_ms(retry_started)
            if retry_status == 200 and isinstance(retry_payload, dict):
                retry_score, _, _ = _contact_turn_candidate_score(
                    dict(retry_payload),
                    reference_answer=reference_answer,
                    conversation_question=conversation_question,
                )
                report.metrics["conversation_turn_contact_retry_score_initial"] = first_score
                report.metrics["conversation_turn_contact_retry_score_retry"] = retry_score
                if retry_score > first_score:
                    turn_payload = retry_payload
    answer_text = str(turn_payload.get("answer") or "")
    encoded_audio = str(turn_payload.get("audio_base64") or "")
    answer_audio_bytes = base64.b64decode(encoded_audio) if encoded_audio else b""
    if not answer_audio_bytes:
        report.add("fail", "conversation_turn_audio_missing", "Conversation turn returned no answer audio.", answer_text=answer_text)
        return report
    turn_transcript_text = str(turn_payload.get("transcript_text") or "")
    if turn_transcript_text:
        report.metrics["conversation_turn_transcript_chars"] = len(turn_transcript_text)
        report.artifacts["conversation_turn_transcript_text"] = turn_transcript_text
    answer_audio_path = output_dir / f"{slug}-conversation-turn-answer.wav"
    _save_bytes(answer_audio_path, answer_audio_bytes)
    report.artifacts["conversation_turn_audio"] = str(answer_audio_path)

    answer_audio_probe = audio_probe.analyze_audio(
        answer_audio_path,
        threshold=0.012,
        min_duration=0.6,
        min_lead_silence=0.01,
        min_tail_silence=0.04,
        min_rms=0.0015,
        max_clip_ratio=0.02,
    )
    report.metrics["conversation_turn_audio_status"] = answer_audio_probe.status
    if answer_audio_probe.failed:
        report.add("fail", "conversation_turn_audio_bad", "Conversation-turn answer audio failed signal checks.", findings=answer_audio_probe.as_dict())
    elif answer_audio_probe.warned:
        report.add("warn", "conversation_turn_audio_warn", "Conversation-turn answer audio is usable but acoustically rough.", findings=answer_audio_probe.as_dict())
    else:
        report.add("pass", "conversation_turn_audio_ok", "Conversation-turn answer audio passed signal checks.")

    if not transcriber_available:
        report.add(
            "info",
            "conversation_answer_text_reference_skipped",
            "Conversation answer text was not compared with the chat reference because speech-to-text is not configured.",
            reference_answer=reference_answer,
            answer_text=answer_text,
        )
    elif _normalize_compare_text(answer_text) == _normalize_compare_text(reference_answer):
        report.add("pass", "conversation_answer_text_ok", "Conversation-turn answer text matches the reference chat answer.")
    else:
        _evaluate_similarity(
            report,
            code_prefix="conversation_answer_text",
            expected=reference_answer,
            actual=answer_text,
            min_f1=conversation_min_f1,
            gold_mode=gold_mode,
            critical_tokens=critical_tokens,
        )

    started = time.perf_counter()
    answer_transcribe_status, answer_transcribe_payload = _post_binary(
        f"{normalized_base_url}/memorials/{urllib.parse.quote(slug)}/speech-transcribe",
        answer_audio_bytes,
        content_type=str(turn_payload.get("audio_content_type") or "audio/wav"),
    )
    report.metrics["conversation_answer_transcribe_ms"] = _elapsed_ms(started)
    if answer_transcribe_status != 200:
        if _speech_transcriber_unavailable(answer_transcribe_status, answer_transcribe_payload):
            status = "fail" if require_stt else "info"
            report.add(
                status,
                "conversation_turn_transcriber_unavailable",
                "Speech-to-text is not configured; conversation answer transcript proof cannot be completed.",
                status_code=answer_transcribe_status,
                payload=answer_transcribe_payload,
            )
        else:
            report.add("fail", "conversation_turn_transcribe_failed", "Speech-to-text could not read the returned conversation audio.", status_code=answer_transcribe_status, payload=answer_transcribe_payload)
        return report
    answer_transcript = str(answer_transcribe_payload.get("transcript_text") or "")
    report.metrics["conversation_turn_transcriber"] = str(answer_transcribe_payload.get("transcriber") or "")
    _evaluate_similarity(
        report,
        code_prefix="conversation_turn_audio",
        expected=answer_text,
        actual=answer_transcript,
        min_f1=conversation_min_f1,
        gold_mode=gold_mode,
        critical_tokens=critical_tokens,
    )

    return report


def _write_optional(path: str, content: str) -> None:
    if path:
        Path(path).write_text(content + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate memorial voice output with round-trip STT loops.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--direct-text", default="Ja. Sag es mir.")
    parser.add_argument("--conversation-question", default="Hallo Manfred, kannst du jetzt mit mir sprechen?")
    parser.add_argument("--present-world-question", default="Welches Wetter haben wir heute?")
    parser.add_argument("--require-stt", action="store_true", help="Fail when live speech-to-text is unavailable.")
    parser.add_argument("--gold-mode", action="store_true", help="Use stricter memorial-gold voice thresholds and critical-token checks.")
    parser.add_argument("--direct-min-f1", type=float, default=0.92)
    parser.add_argument("--conversation-min-f1", type=float, default=0.90)
    parser.add_argument("--critical-token", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--markdown-output", default="")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir or f"/tmp/memorial_voice_loop_{args.slug}")
    report = validate_memorial_voice_loop(
        slug=args.slug,
        base_url=args.base_url,
        output_dir=output_dir,
        direct_text=args.direct_text,
        conversation_question=args.conversation_question,
        present_world_question=args.present_world_question,
        require_stt=args.require_stt,
        gold_mode=args.gold_mode,
        direct_min_f1=float(args.direct_min_f1),
        conversation_min_f1=float(args.conversation_min_f1),
        critical_tokens=tuple(str(token) for token in args.critical_token),
    )
    payload = json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
    markdown = "\n".join(
        [
            "# Memorial Voice Validation",
            "",
            f"Slug: `{report.slug}`",
            f"Base URL: `{report.base_url}`",
            f"Status: **{report.status.upper()}**",
            f"Output: `{report.output_dir}`",
            "",
            "## Checks",
            "",
            *[
                f"- `{item.status.upper()}` `{item.code}` {item.message}"
                + (f" `{json.dumps(item.detail, ensure_ascii=False, sort_keys=True)}`" if item.detail else "")
                for item in report.checks
            ],
        ]
    )
    _write_optional(args.json_output, payload)
    _write_optional(args.markdown_output, markdown)
    if args.output:
        _write_optional(args.output, payload if args.json else markdown)
    print(payload if args.json else markdown)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
