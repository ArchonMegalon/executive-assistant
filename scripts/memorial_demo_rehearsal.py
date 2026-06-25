#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS = [
    "Hallo Manfred, kannst du direkt mit mir reden?",
    "Worum geht es?",
]
DEFAULT_DIFFICULT = "Was ist mit Schuld und Schach in der Familie passiert?"


@dataclass
class Check:
    status: str
    code: str
    detail: str = ""


@dataclass
class RehearsalReport:
    slug: str
    base_url: str
    checks: list[Check] = field(default_factory=list)

    def add(self, status: str, code: str, detail: str = "") -> None:
        self.checks.append(Check(status=status, code=code, detail=detail))

    def as_dict(self) -> dict[str, object]:
        status = "pass"
        if any(item.status == "fail" for item in self.checks):
            status = "fail"
        elif any(item.status == "warn" for item in self.checks):
            status = "warn"
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "status": status,
            "checks": [asdict(item) for item in self.checks],
        }


def load_questions(path: str) -> tuple[list[str], str]:
    if not str(path or "").strip():
        return list(DEFAULT_QUESTIONS), DEFAULT_DIFFICULT
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = [str(item).strip() for item in list(payload.get("questions") or []) if str(item).strip()]
    difficult = str(payload.get("difficult_question") or DEFAULT_DIFFICULT).strip() or DEFAULT_DIFFICULT
    return questions or list(DEFAULT_QUESTIONS), difficult


def request(url: str, *, retries: int = 0, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    attempt = 0
    last_exc: Exception | None = None
    while attempt <= retries:
        try:
            req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
            with urllib.request.urlopen(req, timeout=30.0) as response:
                return int(getattr(response, "status", 200) or 200), dict(getattr(response, "headers", {}) or {}), response.read()
        except TimeoutError as exc:
            last_exc = exc
            attempt += 1
            if attempt > retries:
                raise
    raise last_exc or RuntimeError("request_failed")


def _json_request(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    status, _headers, raw = request(
        url,
        method="POST",
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    parsed = json.loads(raw.decode("utf-8")) if raw else {}
    return status, dict(parsed) if isinstance(parsed, dict) else {}


def _save_audio(output_dir: Path, slug: str, payload: bytes) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{slug}-demo-tts.wav"
    target.write_bytes(payload)
    return target


def run_rehearsal(*, slug: str, base_url: str, questions_path: str, save_audio_dir: str = "") -> RehearsalReport:
    report = RehearsalReport(slug=slug, base_url=base_url)
    questions, difficult = load_questions(questions_path)
    page_status, _headers, page = request(f"{base_url.rstrip('/')}/memorials/{slug}")
    if page_status == 200:
        report.add("pass", "landing_available")
    else:
        report.add("fail", "landing_unavailable", str(page_status))
        return report
    status, answer_payload = _json_request(f"{base_url.rstrip('/')}/memorials/{slug}/chat", {"question": questions[0]})
    if status == 200 and str(answer_payload.get("answer") or "").strip():
        report.add("pass", "chat_answer_ok")
    else:
        report.add("fail", "chat_answer_missing")
    diff_status, diff_payload = _json_request(f"{base_url.rstrip('/')}/memorials/{slug}/chat", {"question": difficult})
    if diff_status == 200 and str(diff_payload.get("fallback_reason") or "").strip():
        report.add("pass", "difficult_memory_guarded")
    else:
        report.add("warn", "difficult_memory_guardrail_unclear")
    tts_status, _tts_headers, tts_raw = request(
        f"{base_url.rstrip('/')}/memorials/{slug}/speech-synthesize",
        method="POST",
        body=json.dumps({"text": "Hallo Manfred"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    if tts_status == 200 and tts_raw.startswith(b"RIFF"):
        report.add("pass", "tts_demo_audio_ok")
        if save_audio_dir:
            _save_audio(Path(save_audio_dir), slug, tts_raw)
            report.add("pass", "tts_demo_audio_saved")
    else:
        report.add("fail", "tts_demo_audio_failed")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--questions", default="")
    parser.add_argument("--save-audio-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_rehearsal(
        slug=args.slug,
        base_url=args.base_url,
        questions_path=args.questions,
        save_audio_dir=args.save_audio_dir,
    )
    payload = report.as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.json else 2))
    return 0 if payload["status"] in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
