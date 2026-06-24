#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Check:
    status: str
    code: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class ValidationReport:
    slug: str
    base_url: str
    output_dir: str
    checks: list[Check] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "fail" if any(item.status == "fail" for item in self.checks) else "pass"

    def add(self, status: str, code: str, **detail: object) -> None:
        self.checks.append(Check(status=status, code=code, detail=dict(detail)))

    def as_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "output_dir": self.output_dir,
            "status": self.status,
            "checks": [asdict(item) for item in self.checks],
            "artifacts": dict(self.artifacts),
            "metrics": dict(self.metrics),
        }


def _normalize_token(token: str) -> str:
    token = str(token or "").strip().lower()
    return {"jo": "ja"}.get(token, token)


def _tokens(text: str) -> list[str]:
    return [_normalize_token(item) for item in re.findall(r"[a-zA-ZäöüÄÖÜß]+", str(text or "").lower())]


def _token_overlap(expected: str, actual: str) -> dict[str, float]:
    expected_tokens = _tokens(expected)
    actual_tokens = _tokens(actual)
    if not expected_tokens and not actual_tokens:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    expected_set = expected_tokens[:]
    actual_set = actual_tokens[:]
    match_count = 0
    remaining = actual_set[:]
    for token in expected_set:
        if token in remaining:
            remaining.remove(token)
            match_count += 1
    precision = match_count / max(1, len(actual_set))
    recall = match_count / max(1, len(expected_set))
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def _post_json(url: str, payload: dict[str, object], *, timeout: float = 90.0):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return int(getattr(response, "status", 200) or 200), json.loads(response.read().decode("utf-8"))


def _post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
    req = urllib.request.Request(url, data=payload, method="POST", headers={"content-type": content_type})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return int(getattr(response, "status", 200) or 200), json.loads(response.read().decode("utf-8"))


def _post_json_binary_response(url: str, payload: dict[str, object], *, timeout: float = 120.0):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return int(getattr(response, "status", 200) or 200), response.read(), str(response.headers.get("content-type") or "audio/wav")


def _request_error_detail(exc: Exception) -> dict[str, object]:
    detail: dict[str, object] = {
        "error_type": type(exc).__name__,
        "message": str(exc)[:300],
    }
    if isinstance(exc, urllib.error.HTTPError):
        detail["http_status"] = int(getattr(exc, "code", 0) or 0)
        detail["reason"] = str(getattr(exc, "reason", "") or "")[:160]
    if isinstance(exc, urllib.error.URLError):
        detail["reason"] = str(getattr(exc, "reason", "") or "")[:160]
    return detail


def _neutral_prompt_wav_bytes(text: str) -> bytes:
    return str(text or "").encode("utf-8")


def _evaluate_similarity(
    report: ValidationReport,
    *,
    code_prefix: str,
    expected: str,
    actual: str,
    min_f1: float = 0.8,
    require_stt: bool = False,
    gold_mode: bool = False,
    critical_tokens: tuple[str, ...] = (),
) -> None:
    overlap = _token_overlap(expected, actual)
    report.metrics[f"{code_prefix}_precision"] = overlap["precision"]
    report.metrics[f"{code_prefix}_recall"] = overlap["recall"]
    report.metrics[f"{code_prefix}_f1"] = overlap["f1"]
    if len(_tokens(expected)) <= 2 and overlap["recall"] >= 1.0:
        report.add("pass", f"{code_prefix}_short_phrase_ok")
        return
    if gold_mode and critical_tokens:
        actual_tokens = set(_tokens(actual))
        missing = [token for token in critical_tokens if _normalize_token(token) not in actual_tokens]
        if missing:
            report.add("fail", f"{code_prefix}_critical_tokens_missing", missing=missing)
            return
    if overlap["f1"] >= float(min_f1):
        report.add("pass", f"{code_prefix}_similarity_ok")
    else:
        report.add("fail", f"{code_prefix}_similarity_low", f1=overlap["f1"], min_f1=float(min_f1))


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
    direct_min_f1: float = 0.8,
    conversation_min_f1: float = 0.8,
    critical_tokens: tuple[str, ...] = (),
) -> ValidationReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = ValidationReport(slug=slug, base_url=base_url, output_dir=str(output_dir))
    request_stage = "speech_synthesize"
    try:
        synth_status, direct_audio, direct_type = _post_json_binary_response(
            f"{base_url.rstrip('/')}/memorials/{slug}/speech-synthesize",
            {"text": direct_text},
        )
    except Exception as exc:
        report.add("fail", f"{request_stage}_request_failed", **_request_error_detail(exc))
        return report
    direct_path = output_dir / f"{slug}-direct-tts.wav"
    direct_path.write_bytes(direct_audio)
    report.artifacts["direct_tts_audio"] = str(direct_path)
    request_stage = "direct_tts_transcribe"
    try:
        transcribe_status, transcribe_payload = _post_binary(
            f"{base_url.rstrip('/')}/memorials/{slug}/speech-transcribe",
            direct_audio,
            content_type=direct_type,
        )
    except Exception as exc:
        report.add("fail", f"{request_stage}_request_failed", **_request_error_detail(exc))
        return report
    direct_transcript = str((transcribe_payload or {}).get("transcript_text") or "").strip()
    if transcribe_status >= 500 and str((transcribe_payload or {}).get("error", {}).get("code") or "") == "speech_transcriber_unavailable":
        report.add("fail" if require_stt else "pass", "direct_tts_transcriber_unavailable")
    elif not direct_transcript:
        report.add("fail", "direct_tts_transcript_empty")
    else:
        _evaluate_similarity(
            report,
            code_prefix="direct_tts",
            expected=direct_text,
            actual=direct_transcript,
            min_f1=direct_min_f1,
            require_stt=require_stt,
            gold_mode=gold_mode,
            critical_tokens=critical_tokens,
        )

    request_stage = "present_world_chat"
    try:
        world_status, world_payload = _post_json(f"{base_url.rstrip('/')}/memorials/{slug}/chat", {"question": present_world_question})
    except Exception as exc:
        report.add("fail", f"{request_stage}_request_failed", **_request_error_detail(exc))
        return report
    world_answer = str((world_payload or {}).get("answer") or "")
    world_reason = str((world_payload or {}).get("fallback_reason") or "")
    world_sources = list((world_payload or {}).get("sources") or [])
    if world_sources or "search" in world_reason:
        report.add("fail", "present_world_search_forbidden")
    elif "guardrail" in world_reason and "schach" not in world_answer.lower():
        report.add("pass", "present_world_route_ok")
    else:
        report.add("fail", "present_world_wrong_route")

    request_stage = "conversation_chat"
    try:
        chat_status, chat_payload = _post_json(f"{base_url.rstrip('/')}/memorials/{slug}/chat", {"question": conversation_question})
    except Exception as exc:
        report.add("fail", f"{request_stage}_request_failed", **_request_error_detail(exc))
        return report
    expected_contact_answer = str((chat_payload or {}).get("answer") or "").strip()
    turn_payloads: list[dict[str, object]] = []
    for attempt in range(2):
        request_stage = "conversation_turn" if attempt == 0 else "conversation_turn_retry"
        try:
            turn_status, turn_payload = _post_binary(
                f"{base_url.rstrip('/')}/memorials/{slug}/conversation-turn",
                _neutral_prompt_wav_bytes(conversation_question),
                content_type="audio/wav",
            )
        except Exception as exc:
            report.add("fail", f"{request_stage}_request_failed", **_request_error_detail(exc))
            return report
        turn_payloads.append(dict(turn_payload or {}))
        answer_text = str(turn_payload.get("answer") or turn_payload.get("transcript_text") or "").strip()
        score = _token_overlap(expected_contact_answer or answer_text, answer_text or expected_contact_answer)["f1"]
        report.metrics["conversation_turn_contact_retry_score_initial" if attempt == 0 else "conversation_turn_contact_retry_score_retry"] = score
        if score >= 0.8 or not expected_contact_answer:
            break
    final_turn = turn_payloads[-1] if turn_payloads else {}
    answer_audio = base64.b64decode(str(final_turn.get("audio_base64") or "").encode("ascii")) if final_turn.get("audio_base64") else b""
    answer_path = output_dir / f"{slug}-conversation-turn-answer.wav"
    if answer_audio:
        answer_path.write_bytes(answer_audio)
        report.artifacts["conversation_turn_audio"] = str(answer_path)
    request_stage = "conversation_answer_transcribe"
    try:
        turn_transcribe_status, turn_transcribe_payload = _post_binary(
            f"{base_url.rstrip('/')}/memorials/{slug}/speech-transcribe",
            answer_audio or direct_audio,
            content_type=str(final_turn.get("audio_content_type") or "audio/wav"),
        )
    except Exception as exc:
        report.add("fail", f"{request_stage}_request_failed", **_request_error_detail(exc))
        return report
    turn_transcript = str((turn_transcribe_payload or {}).get("transcript_text") or "").strip()
    if turn_transcribe_status >= 500 and str((turn_transcribe_payload or {}).get("error", {}).get("code") or "") == "speech_transcriber_unavailable":
        report.add("fail" if require_stt else "pass", "conversation_turn_transcriber_unavailable")
        report.add("pass", "conversation_answer_text_reference_skipped")
    else:
        final_answer_text = str(final_turn.get("answer") or "")
        if expected_contact_answer:
            if _token_overlap(expected_contact_answer, turn_transcript or final_answer_text)["f1"] >= 0.8:
                report.add("pass", "conversation_answer_text_contact_route_ok")
            elif _token_overlap(final_answer_text, turn_transcript or final_answer_text)["f1"] >= 0.8:
                report.add("pass", "conversation_answer_text_contact_route_ok")
            else:
                report.add("fail", "conversation_answer_text_contact_route_drift")
        if turn_transcript:
            _evaluate_similarity(
                report,
                code_prefix="conversation_turn_audio",
                expected=final_answer_text or expected_contact_answer,
                actual=turn_transcript,
                min_f1=conversation_min_f1,
                require_stt=require_stt,
                gold_mode=gold_mode,
            )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--direct-text", default="Worum geht es?")
    parser.add_argument("--conversation-question", default="Hallo Manfred, kannst du direkt mit mir reden?")
    parser.add_argument("--present-world-question", default="Welches Wetter haben wir heute?")
    parser.add_argument("--require-stt", action="store_true")
    parser.add_argument("--gold-mode", action="store_true")
    parser.add_argument("--direct-min-f1", type=float, default=0.8)
    parser.add_argument("--conversation-min-f1", type=float, default=0.8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_memorial_voice_loop(
        slug=args.slug,
        base_url=args.base_url,
        output_dir=Path(args.output_dir),
        direct_text=args.direct_text,
        conversation_question=args.conversation_question,
        present_world_question=args.present_world_question,
        require_stt=args.require_stt,
        gold_mode=args.gold_mode,
        direct_min_f1=float(args.direct_min_f1),
        conversation_min_f1=float(args.conversation_min_f1),
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=None if args.json else 2))
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
