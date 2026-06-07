#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_QUESTIONS = [
    "Was war dir bei Gerechtigkeit wichtig?",
    "Wie soll ich mit dem Schach umgehen?",
    "Bist du wirklich Manfred?",
]
DEFAULT_DIFFICULT_QUESTION = "Was haettest du ueber Schuld in der Familie gesagt?"
FORBIDDEN_PUBLIC_HTML_MARKERS = [
    "Originalaufnahmen",
    "Belegte Erinnerungen",
    "Archiv lesen",
    "Stimmvergleich und Feedback",
]
REQUIRED_PUBLIC_HTML_MARKERS = [
    "Sprich mit der Erinnerung",
    "Tippen, sprechen, kurz warten, einfach weiterreden",
]
FORBIDDEN_META_TOKENS = ("ich bin ein llm", "sprachmodell", "language model", "als ki", "chatbot")


@dataclass
class Check:
    status: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RehearsalReport:
    slug: str
    base_url: str
    checks: list[Check] = field(default_factory=list)

    def add(self, status: str, code: str, message: str, **detail: Any) -> None:
        self.checks.append(Check(status=status, code=code, message=message, detail=detail))

    @property
    def failed(self) -> bool:
        return any(check.status == "fail" for check in self.checks)

    @property
    def warned(self) -> bool:
        return any(check.status == "warn" for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "status": "fail" if self.failed else ("warn" if self.warned else "pass"),
            "checks": [
                {"status": item.status, "code": item.code, "message": item.message, "detail": item.detail}
                for item in self.checks
            ],
        }

    def print_markdown(self) -> None:
        print(f"# Memorial Demo Rehearsal: {self.slug}\n")
        print(f"Base URL: `{self.base_url}`")
        print(f"Overall: **{self.as_dict()['status'].upper()}**\n")
        for item in self.checks:
            icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(item.status, "INFO")
            print(f"- `{icon}` `{item.code}` {item.message}")
            if item.detail:
                print(f"  `{json.dumps(item.detail, ensure_ascii=False, sort_keys=True)}`")


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html, audio/*, */*",
    }
    if extra:
        headers.update(extra)
    return headers


def request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, method=method, data=body, headers=_headers(headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.status), {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request_failed:{type(exc).__name__}:{exc}") from exc


def json_request(url: str, payload: dict[str, Any], *, timeout: int = 30) -> tuple[int, dict[str, Any]]:
    http_status, _, raw = request(
        url,
        method="POST",
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=timeout,
    )
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        parsed = {"raw": raw.decode("utf-8", errors="replace")[:500]}
    return http_status, parsed if isinstance(parsed, dict) else {"raw": parsed}


def normalize(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def check_landing(report: RehearsalReport, *, base: str, slug: str) -> None:
    http_status, headers, raw = request(f"{base}/memorials/{urllib.parse.quote(slug)}", timeout=20)
    text = raw.decode("utf-8", errors="replace")
    if http_status != 200:
        report.add("fail", "landing_unavailable", "Landing page did not return 200.", http_status=http_status)
        return
    report.add("pass", "landing_available", "Landing page returned 200.", bytes=len(raw))

    for marker in REQUIRED_PUBLIC_HTML_MARKERS:
        if marker in text:
            report.add("pass", "landing_required_copy_present", "Required flagship copy is present.", marker=marker)
        else:
            report.add("fail", "landing_required_copy_missing", "Required flagship copy is missing.", marker=marker)

    for marker in FORBIDDEN_PUBLIC_HTML_MARKERS:
        if marker in text:
            report.add(
                "fail",
                "landing_forbidden_section_visible",
                "A removed/non-flagship public section appears on landing page.",
                marker=marker,
            )
        else:
            report.add("pass", "landing_forbidden_section_absent", "Removed/non-flagship section is absent.", marker=marker)

    cache_control = headers.get("cache-control", "")
    if "no-store" in cache_control:
        report.add("pass", "landing_no_store", "Landing page is served no-store.", cache_control=cache_control)
    else:
        report.add("warn", "landing_cache_policy", "Landing page cache policy is not no-store.", cache_control=cache_control)


def check_public_contracts(report: RehearsalReport, *, base: str, slug: str) -> None:
    http_status, _, _ = request(f"{base}/memorials/files/{urllib.parse.quote(slug)}/memorial.json", timeout=15)
    if http_status == 404:
        report.add("pass", "raw_manifest_blocked", "Raw memorial.json is blocked through public file route.")
    else:
        report.add("fail", "raw_manifest_exposed", "Raw memorial.json did not return 404.", http_status=http_status)

    http_status, _, raw = request(f"{base}/memorials/{urllib.parse.quote(slug)}.json", timeout=15)
    if http_status != 200:
        report.add("fail", "public_json_unavailable", "Public memorial JSON did not return 200.", http_status=http_status)
    else:
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            payload = {}
        forbidden = [
            "write_token",
            "write_tokens",
            "admin_token",
            "management_token",
            "owner_token",
            "tts_plugin_voice_id",
            "voice_consent",
        ]
        leaked = [key for key in forbidden if isinstance(payload, dict) and payload.get(key)]
        if leaked:
            report.add("fail", "public_json_sensitive_leak", "Public JSON exposes sensitive keys.", keys=leaked)
        else:
            report.add("pass", "public_json_sanitized", "Public JSON does not expose obvious sensitive keys.")

    http_status, payload = json_request(
        f"{base}/memorials/{urllib.parse.quote(slug)}/speech-synthesize",
        {"text": "Test", "tts_plugin_voice_id": "must-not-be-accepted"},
        timeout=20,
    )
    if http_status in {400, 403}:
        report.add("pass", "tts_override_rejected", "Public TTS rejects client-supplied voice-id override.", http_status=http_status)
    else:
        report.add(
            "fail",
            "tts_override_not_rejected",
            "Public TTS did not reject voice-id override payload.",
            http_status=http_status,
            response=payload,
        )


def check_chat(report: RehearsalReport, *, base: str, slug: str, questions: list[str], difficult_question: str) -> None:
    for question in questions:
        started = time.time()
        http_status, payload = json_request(
            f"{base}/memorials/{urllib.parse.quote(slug)}/chat",
            {"question": question},
            timeout=45,
        )
        elapsed_ms = int((time.time() - started) * 1000)
        answer = normalize(str(payload.get("answer") or ""))
        if http_status != 200:
            report.add("fail", "chat_failed", "Grounded chat question failed.", question=question, http_status=http_status, response=payload)
            continue
        if not answer:
            report.add("fail", "chat_empty_answer", "Grounded chat returned an empty answer.", question=question, elapsed_ms=elapsed_ms)
            continue
        lowered = answer.lower()
        if any(token in lowered for token in FORBIDDEN_META_TOKENS):
            report.add("fail", "chat_meta_self_reference", "Answer leaked model/AI self-reference.", question=question, answer=answer[:240])
        else:
            report.add(
                "pass",
                "chat_answer_ok",
                "Grounded chat returned a memorial-style answer.",
                question=question,
                elapsed_ms=elapsed_ms,
                preview=answer[:180],
            )

    http_status, payload = json_request(
        f"{base}/memorials/{urllib.parse.quote(slug)}/chat",
        {"question": difficult_question},
        timeout=45,
    )
    answer = normalize(str(payload.get("answer") or ""))
    if http_status != 200:
        report.add(
            "fail",
            "difficult_memory_chat_failed",
            "Difficult-memory guardrail question failed.",
            http_status=http_status,
            response=payload,
        )
        return
    fallback_reason = str(payload.get("fallback_reason") or "")
    if fallback_reason == "difficult_memory_guardrail" or "keine ich-form-rekonstruktion" in answer.lower() or "quellengebunden" in answer.lower():
        report.add("pass", "difficult_memory_guarded", "Difficult-memory question is guarded by default.", preview=answer[:220])
    else:
        report.add(
            "warn",
            "difficult_memory_guardrail_unclear",
            "Difficult-memory answer did not clearly show the default guardrail.",
            preview=answer[:260],
        )


def check_tts(report: RehearsalReport, *, base: str, slug: str, output_dir: Path | None) -> None:
    http_status, headers, raw = request(
        f"{base}/memorials/{urllib.parse.quote(slug)}/speech-synthesize",
        method="POST",
        body=json.dumps(
            {
                "text": "Rechtlich ist es so, dass man die Dinge sauber auseinanderhalten muss.",
                "personal_memory_enabled": False,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/*, application/json"},
        timeout=60,
    )
    content_type = headers.get("content-type", "")
    if http_status != 200:
        preview = raw.decode("utf-8", errors="replace")[:400]
        report.add("fail", "tts_demo_failed", "Demo TTS request failed.", http_status=http_status, content_type=content_type, response=preview)
        return
    if not raw or len(raw) < 256:
        report.add("fail", "tts_demo_audio_too_small", "Demo TTS returned too little audio.", bytes=len(raw), content_type=content_type)
        return
    if "audio" not in content_type:
        report.add("warn", "tts_demo_content_type_unexpected", "Demo TTS returned a non-audio content type.", content_type=content_type, bytes=len(raw))
    else:
        report.add("pass", "tts_demo_audio_ok", "Demo TTS returned audio.", content_type=content_type, bytes=len(raw))

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".wav"
        if "mpeg" in content_type or "mp3" in content_type:
            suffix = ".mp3"
        elif "ogg" in content_type:
            suffix = ".ogg"
        out = output_dir / f"{slug}-demo-tts{suffix}"
        out.write_bytes(raw)
        report.add("pass", "tts_demo_audio_saved", "Demo TTS audio saved for rehearsal playback.", path=str(out))


def load_questions(path: str) -> tuple[list[str], str]:
    if not path:
        return DEFAULT_QUESTIONS, DEFAULT_DIFFICULT_QUESTION
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = [str(item).strip() for item in list(payload.get("questions") or []) if str(item).strip()]
    difficult = str(payload.get("difficult_question") or DEFAULT_DIFFICULT_QUESTION).strip()
    return questions or DEFAULT_QUESTIONS, difficult or DEFAULT_DIFFICULT_QUESTION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live demo rehearsal smoke test for the memorial flagship presentation.")
    parser.add_argument("slug", help="memorial slug, e.g. manfred")
    parser.add_argument("--base-url", required=True, help="Live base URL, e.g. https://myexternalbrain.com")
    parser.add_argument("--questions", default="", help="JSON file with questions and difficult_question")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--save-audio-dir", default="", help="Save demo TTS audio to this directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    report = RehearsalReport(slug=args.slug, base_url=base)

    try:
        check_landing(report, base=base, slug=args.slug)
        check_public_contracts(report, base=base, slug=args.slug)
        questions, difficult = load_questions(args.questions)
        if not args.skip_chat:
            check_chat(report, base=base, slug=args.slug, questions=questions, difficult_question=difficult)
        if not args.skip_tts:
            check_tts(report, base=base, slug=args.slug, output_dir=Path(args.save_audio_dir) if args.save_audio_dir else None)
    except Exception as exc:
        report.add("fail", "rehearsal_exception", "Rehearsal script crashed.", error=f"{type(exc).__name__}: {exc}")

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        report.print_markdown()

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
