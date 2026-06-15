#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
EA_SCRIPTS = EA_DIR / "scripts"
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"

if str(EA_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(EA_SCRIPTS))
if str(EA_DIR) not in sys.path:
    sys.path.insert(0, str(EA_DIR))

import validate_memorial_voice_loop as voice_loop  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except Exception:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_dirty() -> bool:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except Exception:
        return True
    return bool(proc.stdout.strip()) if proc.returncode == 0 else True


def _source_tree_fingerprint() -> str:
    import subprocess

    generated_prefixes = (
        ".codex-design/product/",
        ".codex-studio/published/",
    )
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    digest = hashlib.sha256()
    for relpath in sorted(line.strip() for line in proc.stdout.splitlines() if line.strip()):
        if relpath.startswith(generated_prefixes):
            continue
        path = ROOT / relpath
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_local_base_url(base_url: str) -> bool:
    lowered = str(base_url or "").strip().lower()
    return any(
        marker in lowered
        for marker in (
            "://127.0.0.1",
            "://localhost",
            "://0.0.0.0",
            "://[::1]",
        )
    )


def build_receipt(
    *,
    slug: str,
    base_url: str,
    output_dir: Path,
    direct_text: str,
    conversation_question: str,
    present_world_question: str,
    require_stt: bool,
    gold_mode: bool = False,
    require_public_origin: bool = False,
    direct_min_f1: float = 0.92,
    conversation_min_f1: float = 0.90,
    max_conversation_turn_ms: float = 4500.0,
    max_speech_transcribe_ms: float = 2500.0,
    critical_tokens: tuple[str, ...] = (),
) -> dict[str, Any]:
    report = voice_loop.validate_memorial_voice_loop(
        slug=slug,
        base_url=base_url,
        output_dir=output_dir,
        direct_text=direct_text,
        conversation_question=conversation_question,
        present_world_question=present_world_question,
        require_stt=require_stt,
        gold_mode=gold_mode,
        direct_min_f1=direct_min_f1,
        conversation_min_f1=conversation_min_f1,
        critical_tokens=critical_tokens,
    )
    payload = report.as_dict()
    failed_codes = [
        str(item.get("code") or "")
        for item in payload.get("checks", [])
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "fail"
    ]
    warned_codes = [
        str(item.get("code") or "")
        for item in payload.get("checks", [])
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "warn"
    ]
    if require_public_origin and _is_local_base_url(base_url):
        failed_codes.append("public_origin_required")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "public_origin_required",
                "message": "Memorial-gold voice proof requires a public or staging origin, not localhost.",
                "detail": {"base_url": base_url.rstrip("/")},
            }
        )
        payload["status"] = "fail"
    metrics = dict(payload.get("metrics") or {})
    try:
        conversation_turn_total_ms = float(metrics.get("conversation_turn_total_ms") or 0.0)
    except Exception:
        conversation_turn_total_ms = 0.0
    try:
        speech_transcribe_ms = float(metrics.get("speech_transcribe_ms") or 0.0)
    except Exception:
        speech_transcribe_ms = 0.0
    if gold_mode and conversation_turn_total_ms > float(max_conversation_turn_ms):
        failed_codes.append("conversation_turn_total_ms_above_gold_threshold")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "conversation_turn_total_ms_above_gold_threshold",
                "message": "Memorial-gold voice proof exceeded the conversation-turn latency threshold.",
                "detail": {
                    "conversation_turn_total_ms": conversation_turn_total_ms,
                    "max_allowed_ms": float(max_conversation_turn_ms),
                },
            }
        )
        payload["status"] = "fail"
    if gold_mode and speech_transcribe_ms > float(max_speech_transcribe_ms):
        failed_codes.append("speech_transcribe_ms_above_gold_threshold")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "speech_transcribe_ms_above_gold_threshold",
                "message": "Memorial-gold voice proof exceeded the speech-transcribe latency threshold.",
                "detail": {
                    "speech_transcribe_ms": speech_transcribe_ms,
                    "max_allowed_ms": float(max_speech_transcribe_ms),
                },
            }
        )
        payload["status"] = "fail"
    dirty_worktree = _git_dirty()
    if gold_mode and dirty_worktree:
        failed_codes.append("dirty_worktree")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "dirty_worktree",
                "message": "Memorial-gold voice proof requires a clean worktree.",
                "detail": {},
            }
        )
        payload["status"] = "fail"
    source_git_head = _git_head()
    return {
        "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
        "source_tree_fingerprint": _source_tree_fingerprint(),
        "dirty_worktree": dirty_worktree,
        "status": payload.get("status"),
        "slug": slug,
        "base_url": base_url.rstrip("/"),
        "require_stt": bool(require_stt),
        "gold_mode": bool(gold_mode),
        "require_public_origin": bool(require_public_origin),
        "direct_min_f1": float(direct_min_f1),
        "conversation_min_f1": float(conversation_min_f1),
        "max_conversation_turn_ms": float(max_conversation_turn_ms),
        "max_speech_transcribe_ms": float(max_speech_transcribe_ms),
        "critical_tokens": list(critical_tokens),
        "direct_text": direct_text,
        "conversation_question": conversation_question,
        "present_world_question": present_world_question,
        "failed_codes": failed_codes,
        "warned_codes": warned_codes,
        "metrics": payload.get("metrics", {}),
        "artifacts": payload.get("artifacts", {}),
        "checks": payload.get("checks", []),
        "gold_claim_allowed": bool(gold_mode) and payload.get("status") == "pass" and not dirty_worktree,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the live memorial voice roundtrip exit-gate receipt.")
    parser.add_argument("--slug", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_SLUG", "manfred"))
    parser.add_argument("--base-url", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--output-dir", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_OUTPUT_DIR", "/tmp/memorial_voice_roundtrip_exit_gate"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--direct-text",
        default="Worum geht es?",
    )
    parser.add_argument("--conversation-question", default="Hallo Manfred, kannst du jetzt mit mir sprechen?")
    parser.add_argument("--present-world-question", default="Welches Wetter haben wir heute?")
    parser.add_argument("--allow-missing-stt", action="store_true")
    parser.add_argument("--gold-mode", action="store_true")
    parser.add_argument("--require-public-origin", action="store_true")
    parser.add_argument("--direct-min-f1", type=float, default=0.92)
    parser.add_argument("--conversation-min-f1", type=float, default=0.90)
    parser.add_argument("--max-conversation-turn-ms", type=float, default=float(os.getenv("MEMORIAL_GOLD_MAX_CONVERSATION_TURN_MS", "4500")))
    parser.add_argument("--max-speech-transcribe-ms", type=float, default=float(os.getenv("MEMORIAL_GOLD_MAX_SPEECH_TRANSCRIBE_MS", "2500")))
    parser.add_argument("--critical-token", action="append", default=[])
    args = parser.parse_args(argv)

    receipt = build_receipt(
        slug=args.slug,
        base_url=args.base_url,
        output_dir=Path(args.output_dir),
        direct_text=args.direct_text,
        conversation_question=args.conversation_question,
        present_world_question=args.present_world_question,
        require_stt=not args.allow_missing_stt,
        gold_mode=bool(args.gold_mode),
        require_public_origin=bool(args.require_public_origin),
        direct_min_f1=float(args.direct_min_f1),
        conversation_min_f1=float(args.conversation_min_f1),
        max_conversation_turn_ms=float(args.max_conversation_turn_ms),
        max_speech_transcribe_ms=float(args.max_speech_transcribe_ms),
        critical_tokens=tuple(str(token) for token in args.critical_token),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "output": str(output), "failed_codes": receipt["failed_codes"]}, ensure_ascii=False))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
