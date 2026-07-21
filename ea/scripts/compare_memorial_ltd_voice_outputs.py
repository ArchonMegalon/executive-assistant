#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / ".codex-studio" / "published" / "memorial_voicewave_backup"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    if number != number:
        return default
    return number


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_tokens(value: str) -> set[str]:
    text = _safe_text(value).lower()
    if not text:
        return set()
    return {token for token in text.replace(".", " ").replace(",", " ").split() if token}


def _f1(a: str, b: str) -> float:
    set_a = _normalized_tokens(a)
    set_b = _normalized_tokens(b)
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    if not intersection:
        return 0.0
    return (2 * len(intersection)) / (len(set_a) + len(set_b))


def _normalize_row(prompt: str, row: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
    unmixr = row.get("unmixr") if isinstance(row.get("unmixr"), dict) else {}
    voicewave = row.get("voicewave") if isinstance(row.get("voicewave"), dict) else {}
    prompt_text = _safe_text(prompt)
    unmixr_transcript = _safe_text(unmixr.get("transcript_text"))
    voicewave_transcript = _safe_text(voicewave.get("transcript_text"))
    unmixr_similarity = _safe_float(unmixr.get("similarity"))
    voicewave_similarity = _safe_float(voicewave.get("similarity"))
    unmixr_transcript_f1 = _safe_float(unmixr.get("transcript_f1"), default=_f1(prompt_text, unmixr_transcript))
    voicewave_transcript_f1 = _safe_float(
        voicewave.get("transcript_f1"),
        default=_f1(prompt_text, voicewave_transcript),
    )
    unmixr_status = _safe_text(unmixr.get("status") or "ok")
    if not unmixr_status:
        unmixr_status = "ok"
    voicewave_status = _safe_text(voicewave.get("status") or "ok")
    if not voicewave_status:
        voicewave_status = "ok"
    unmixr_detail = _safe_text(unmixr.get("detail"))
    voicewave_detail = _safe_text(voicewave.get("detail"))
    return {
        "prompt": prompt_text,
        "unmixr_similarity": unmixr_similarity,
        "unmixr_transcript_text": unmixr_transcript,
        "unmixr_transcript_f1": unmixr_transcript_f1,
        "unmixr_status": unmixr_status,
        "unmixr_detail": unmixr_detail,
        "voicewave_similarity": voicewave_similarity,
        "voicewave_transcript_text": voicewave_transcript,
        "voicewave_transcript_f1": voicewave_transcript_f1,
        "voicewave_audio_path": str(output_dir / "voicewave.wav") if not _safe_text(voicewave.get("audio_path")) else str(
            Path(_safe_text(voicewave.get("audio_path"))
            )
        ),
        "voicewave_status": voicewave_status,
        "voicewave_detail": voicewave_detail,
    }


def _compare_prompt(*, prompt: str, base_url: str, output_dir: Path) -> dict[str, Any]:
    # This function is intentionally conservative and side-effect free by default.
    # Production operators may replace it with richer HTTP-backed comparison logic.
    prompt_text = _safe_text(prompt)
    return {
        "prompt": prompt_text,
        "unmixr": {
            "status": "ok",
            "similarity": 0.0,
            "transcript_text": prompt_text,
            "transcript_f1": _f1(prompt_text, prompt_text),
        },
        "voicewave": {
            "status": "ok",
            "similarity": 0.0,
            "transcript_text": prompt_text,
            "transcript_f1": _f1(prompt_text, prompt_text),
            "audio_path": str(output_dir / "voicewave.wav"),
        },
    }


def _winner(unmixr_similarity: float, voicewave_similarity: float, *, unmixr_blocked: bool, voicewave_blocked: bool) -> str:
    if unmixr_blocked and not voicewave_blocked:
        return "voicewave"
    if voicewave_blocked and not unmixr_blocked:
        return "unmixr"
    if voicewave_similarity > unmixr_similarity:
        return "voicewave"
    if unmixr_similarity > voicewave_similarity:
        return "unmixr"
    return "unmixr"


def _drift_threshold() -> float:
    return 0.9


def _backup_candidate_status(voicewave_similarity: float, voicewave_transcript_f1: float, drift_prompts: list[str]) -> tuple[str, str]:
    if voicewave_similarity >= 0.6 and voicewave_transcript_f1 >= _drift_threshold():
        return "ready", ""
    reason = "voicewave_backup_gate_failed"
    return "blocked", reason


def compare_outputs(*, base_url: str, prompts: list[str], output_dir: Path) -> dict[str, Any]:
    prompts_safe = [_safe_text(item) for item in prompts or [] if _safe_text(item)]
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for prompt in prompts_safe:
        raw = _compare_prompt(prompt=prompt, base_url=base_url, output_dir=output_root)
        normalized = _normalize_row(prompt=prompt, row=raw if isinstance(raw, dict) else {}, output_dir=output_root)
        rows.append(normalized)

    if not rows:
        return {
            "winner": "unmixr",
            "unmixr_status": "blocked",
            "averages": {
                "unmixr_similarity": 0.0,
                "voicewave_similarity": 0.0,
                "unmixr_transcript_f1": 0.0,
                "voicewave_transcript_f1": 0.0,
            },
            "voicewave_backup_candidate": {
                "status": "blocked",
                "reason": "no_prompts",
                "average_similarity": 0.0,
                "average_transcript_f1": 0.0,
                "min_transcript_f1": 0.0,
                "drift_prompts": [],
            },
        }

    unmixr_statuses = [row.get("unmixr_status") for row in rows]
    voicewave_statuses = [row.get("voicewave_status") for row in rows]
    average_unmixr_similarity = sum(float(row.get("unmixr_similarity") or 0.0) for row in rows) / len(rows) if rows else 0.0
    average_voicewave_similarity = sum(float(row.get("voicewave_similarity") or 0.0) for row in rows) / len(rows) if rows else 0.0
    average_unmixr_transcript_f1 = sum(float(row.get("unmixr_transcript_f1") or 0.0) for row in rows) / len(rows) if rows else 0.0
    average_voicewave_transcript_f1 = sum(float(row.get("voicewave_transcript_f1") or 0.0) for row in rows) / len(rows) if rows else 0.0

    drift_prompts = [row.get("prompt", "") for row in rows if float(row.get("voicewave_transcript_f1") or 0.0) < _drift_threshold()]
    min_voicewave_transcript_f1 = min((float(row.get("voicewave_transcript_f1") or 0.0) for row in rows), default=0.0)
    unmixr_blocked = any(status == "blocked" for status in unmixr_statuses)
    voicewave_blocked = any(status == "blocked" for status in voicewave_statuses)

    winner = _winner(
        average_unmixr_similarity,
        average_voicewave_similarity,
        unmixr_blocked=unmixr_blocked,
        voicewave_blocked=voicewave_blocked,
    )

    candidate_status, candidate_reason = _backup_candidate_status(
        voicewave_similarity=average_voicewave_similarity,
        voicewave_transcript_f1=average_voicewave_transcript_f1,
        drift_prompts=drift_prompts,
    )

    return {
            "winner": winner,
        "unmixr_status": "blocked" if unmixr_blocked else "ok",
        "averages": {
            "unmixr_similarity": round(average_unmixr_similarity, 3),
            "voicewave_similarity": round(average_voicewave_similarity, 3),
            "unmixr_transcript_f1": round(average_unmixr_transcript_f1, 3),
            "voicewave_transcript_f1": round(average_voicewave_transcript_f1, 3),
        },
        "voicewave_backup_candidate": {
            "status": candidate_status,
            "reason": candidate_reason,
            "average_similarity": round(average_voicewave_similarity, 3),
            "average_transcript_f1": round(average_voicewave_transcript_f1, 3),
            "min_transcript_f1": round(min_voicewave_transcript_f1, 3),
            "drift_prompts": drift_prompts,
        },
    }


def materialize_compare_report(*, base_url: str, prompts: list[str], output_dir: Path, output_path: Path) -> dict[str, Any]:
    report = compare_outputs(base_url=base_url, prompts=prompts, output_dir=output_dir)
    payload = {
        "generated_at": _utc_now(),
        "contract_name": "ea.compare_memorial_ltd_voice_outputs.v1",
        "base_url": _safe_text(base_url),
        "prompts_count": len([p for p in prompts or [] if _safe_text(p)]),
        "compare": report,
    }
    report_path = Path(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def run_compare(
    *,
    base_url: str,
    prompts: list[str],
    output_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    payload = compare_outputs(base_url=base_url, prompts=prompts, output_dir=output_dir)
    output = materialize_compare_report(
        base_url=base_url,
        prompts=prompts,
        output_dir=output_dir,
        output_path=output_path,
    )
    output["compare"] = payload
    return output
