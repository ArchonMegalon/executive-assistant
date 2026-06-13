#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.materialize_memorial_voice_roundtrip_exit_gate import build_receipt  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _metric(receipt: dict[str, Any], key: str) -> float | None:
    try:
        value = receipt.get("metrics", {}).get(key)
        return float(value)
    except Exception:
        return None


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(statistics.fmean(values), 4),
    }


def _timing_summary(receipts: list[dict[str, Any]], key: str) -> dict[str, float | None]:
    values = [value for receipt in receipts if (value := _metric(receipt, key)) is not None]
    return _summary(values)


def run_stability_gate(
    *,
    slug: str,
    base_url: str,
    output_dir: Path,
    runs: int,
    require_stt: bool,
    gold_mode: bool = False,
    require_public_origin: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    for index in range(1, runs + 1):
        receipt = build_receipt(
            slug=slug,
            base_url=base_url,
            output_dir=output_dir / f"run-{index:02d}",
            direct_text="Das kann ich nicht sagen.",
            conversation_question="Was ist der aktuelle Stand?",
            present_world_question="Wie ist das Wetter heute?",
            require_stt=require_stt,
            gold_mode=gold_mode,
            require_public_origin=require_public_origin,
            critical_tokens=("kann", "nicht", "sagen") if gold_mode else (),
        )
        receipts.append(receipt)

    failed_runs = [
        {
            "run": index,
            "status": receipt.get("status"),
            "failed_codes": list(receipt.get("failed_codes") or []),
            "warned_codes": list(receipt.get("warned_codes") or []),
        }
        for index, receipt in enumerate(receipts, start=1)
        if str(receipt.get("status") or "").lower() != "pass"
    ]
    direct_f1 = [value for receipt in receipts if (value := _metric(receipt, "direct_tts_f1")) is not None]
    conversation_f1 = [
        value
        for receipt in receipts
        if (value := _metric(receipt, "conversation_turn_audio_f1")) is not None
    ]
    return {
        "contract_name": "ea.memorial_voice_stability_gate",
        "generated_at": _utc_now(),
        "slug": slug,
        "base_url": base_url.rstrip("/"),
        "runs_required": runs,
        "runs_completed": len(receipts),
        "status": "pass" if not failed_runs and len(receipts) == runs else "fail",
        "gold_mode": bool(gold_mode),
        "require_public_origin": bool(require_public_origin),
        "failed_runs": failed_runs,
        "direct_tts_f1": _summary(direct_f1),
        "conversation_turn_audio_f1": _summary(conversation_f1),
        "latency_ms": {
            "speech_synthesize": _timing_summary(receipts, "speech_synthesize_ms"),
            "speech_transcribe": _timing_summary(receipts, "speech_transcribe_ms"),
            "chat_reference": _timing_summary(receipts, "chat_reference_ms"),
            "present_world_chat": _timing_summary(receipts, "present_world_chat_ms"),
            "synthetic_prompt_synthesize": _timing_summary(receipts, "synthetic_prompt_synthesize_ms"),
            "conversation_turn_total": _timing_summary(receipts, "conversation_turn_total_ms"),
            "conversation_answer_transcribe": _timing_summary(receipts, "conversation_answer_transcribe_ms"),
        },
        "receipts": receipts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated live memorial voice roundtrip checks.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/memorial_voice_stability_gate"))
    parser.add_argument("--output", type=Path, default=Path("/tmp/memorial_voice_stability_gate.generated.json"))
    parser.add_argument("--allow-missing-stt", action="store_true")
    parser.add_argument("--gold-mode", action="store_true")
    parser.add_argument("--require-public-origin", action="store_true")
    args = parser.parse_args()
    runs = max(1, int(args.runs or 1))
    payload = run_stability_gate(
        slug=args.slug,
        base_url=args.base_url,
        output_dir=args.output_dir,
        runs=runs,
        require_stt=not args.allow_missing_stt,
        gold_mode=bool(args.gold_mode),
        require_public_origin=bool(args.require_public_origin),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "runs_completed": payload["runs_completed"],
                "failed_runs": payload["failed_runs"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
