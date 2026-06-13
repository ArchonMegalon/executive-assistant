#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def build_receipt(
    *,
    slug: str,
    base_url: str,
    output_dir: Path,
    direct_text: str,
    conversation_question: str,
    present_world_question: str,
    require_stt: bool,
) -> dict[str, Any]:
    report = voice_loop.validate_memorial_voice_loop(
        slug=slug,
        base_url=base_url,
        output_dir=output_dir,
        direct_text=direct_text,
        conversation_question=conversation_question,
        present_world_question=present_world_question,
        require_stt=require_stt,
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
    return {
        "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "git_head": _git_head(),
        "status": payload.get("status"),
        "slug": slug,
        "base_url": base_url.rstrip("/"),
        "require_stt": bool(require_stt),
        "direct_text": direct_text,
        "conversation_question": conversation_question,
        "present_world_question": present_world_question,
        "failed_codes": failed_codes,
        "warned_codes": warned_codes,
        "metrics": payload.get("metrics", {}),
        "artifacts": payload.get("artifacts", {}),
        "checks": payload.get("checks", []),
        "gold_claim_allowed": payload.get("status") == "pass",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the live memorial voice roundtrip exit-gate receipt.")
    parser.add_argument("--slug", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_SLUG", "manfred"))
    parser.add_argument("--base-url", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--output-dir", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_OUTPUT_DIR", "/tmp/memorial_voice_roundtrip_exit_gate"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--direct-text", default="Sprich ruhig weiter. Ich antworte dir direkt.")
    parser.add_argument("--conversation-question", default="Wie ist heute das Wetter?")
    parser.add_argument("--present-world-question", default="Wie ist das Wetter heute?")
    parser.add_argument("--allow-missing-stt", action="store_true")
    args = parser.parse_args(argv)

    receipt = build_receipt(
        slug=args.slug,
        base_url=args.base_url,
        output_dir=Path(args.output_dir),
        direct_text=args.direct_text,
        conversation_question=args.conversation_question,
        present_world_question=args.present_world_question,
        require_stt=not args.allow_missing_stt,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "output": str(output), "failed_codes": receipt["failed_codes"]}, ensure_ascii=False))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
