from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from app.services.memorial_openvoice import unmixr_synthesize_request


DEFAULT_PROMPTS = [
    "Ja. Ich bin da.",
    "Erzaehl mir, was dich gerade bewegt.",
    "Rechtlich muss man die Dinge sauber unterscheiden.",
]

DEFAULT_COMBOS = [
    {"speaking_rate": "medium", "speaking_pitch": "low", "speaking_volume": "high"},
    {"speaking_rate": "low", "speaking_pitch": "medium", "speaking_volume": "high"},
    {"speaking_rate": "medium", "speaking_pitch": "medium", "speaking_volume": "high"},
]
_PROSODY_LEVELS = ("low", "medium", "high")


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


def _evaluate_candidate_prompt(
    *,
    slug: str,
    voice_id: str,
    prompt: str,
    combo: dict[str, str],
    reference_metrics: dict[str, float],
    base_url: str,
    timeout_seconds: float,
) -> dict[str, object]:
    def _work() -> dict[str, object]:
        audio, content_type = unmixr_synthesize_request(
            text=prompt,
            voice_id=voice_id,
            lang="de-AT",
            speaking_rate=str(combo.get("speaking_rate") or "").strip() or None,
            speaking_pitch=str(combo.get("speaking_pitch") or "").strip() or None,
            speaking_volume=str(combo.get("speaking_volume") or "").strip() or None,
        )
        wav_bytes = _convert_audio_to_wav(payload=audio, content_type=content_type)
        transcript_payload = _OPTIMIZER._transcribe_audio_bytes(
            wav_bytes,
            content_type="audio/wav",
            slug=slug,
            base_url=base_url,
        )
        transcript_text = str(
            transcript_payload.get("text")
            or transcript_payload.get("transcript_text")
            or ""
        ).strip()
        feature_similarity = float(
            _OPTIMIZER._voice_feature_similarity(
                reference_metrics,
                _OPTIMIZER._wav_metrics_from_bytes(wav_bytes),
            )
        )
        text_similarity = _text_overlap(prompt, transcript_text) if transcript_text else 0.0
        duration_seconds = _wav_duration_seconds(wav_bytes)
        score = (feature_similarity * 0.85) + (text_similarity * 0.15)
        return {
            "prompt": prompt,
            "feature_similarity": round(feature_similarity, 4),
            "text_similarity": round(text_similarity, 4),
            "score": round(score, 4),
            "duration_seconds": round(duration_seconds, 3),
            "transcript_text": transcript_text,
            "content_type": str(content_type or ""),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_work)
        try:
            return future.result(timeout=max(1.0, float(timeout_seconds or 0.0)))
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"candidate_prompt_timeout:{int(max(1.0, float(timeout_seconds or 0.0)))}s") from exc


def compare_unmixr_clones(
    *,
    slug: str,
    base_url: str,
    voice_ids: list[str],
    prompts: list[str],
    combos: list[dict[str, str]],
    output_path: Path | None = None,
    resume: bool = False,
    max_rows: int = 0,
    prompt_timeout_seconds: float = 90.0,
) -> dict[str, object]:
    reference_metrics = _OPTIMIZER._wav_metrics_from_bytes(_reference_path(slug=slug).read_bytes())
    rows: list[dict[str, object]] = []
    winner: dict[str, object] | None = None
    seen_keys: set[tuple[str, str, str, str]] = set()

    def _row_key(row: dict[str, object]) -> tuple[str, str, str, str]:
        return (
            str(row.get("voice_id") or "").strip(),
            str(row.get("speaking_rate") or "").strip(),
            str(row.get("speaking_pitch") or "").strip(),
            str(row.get("speaking_volume") or "").strip(),
        )

    def _write_checkpoint() -> None:
        if output_path is None:
            return
        payload = {
            "slug": slug,
            "base_url": base_url,
            "reference_path": str(_reference_path(slug=slug)),
            "rows": rows,
            "winner": winner,
            "recommended_config": {
                "tts_plugin": "unmixr_clone",
                "tts_plugin_voice_id": str((winner or {}).get("voice_id") or "").strip(),
                "voice_profile_id": str((winner or {}).get("voice_id") or "").strip(),
                "voice_label": "Manfred Hoza · Unmixr-Klon",
                "tts_base_voice_variant": "unmixr",
                "unmixr_speaking_rate": str((winner or {}).get("speaking_rate") or "").strip(),
                "unmixr_speaking_pitch": str((winner or {}).get("speaking_pitch") or "").strip(),
                "unmixr_speaking_volume": str((winner or {}).get("speaking_volume") or "").strip(),
            },
            "completed_rows": len(rows),
            "requested_rows": len(voice_ids) * len(combos),
            "complete": len(rows) >= (len(voice_ids) * len(combos)),
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
            if winner is None or float(row.get("average_score") or 0.0) > float(winner.get("average_score") or 0.0):
                winner = row

    rows_evaluated = 0
    for voice_id in voice_ids:
        for combo in combos:
            row_identity = (
                str(voice_id or "").strip(),
                str(combo.get("speaking_rate") or "").strip(),
                str(combo.get("speaking_pitch") or "").strip(),
                str(combo.get("speaking_volume") or "").strip(),
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
                    "recommended_config": {
                        "tts_plugin": "unmixr_clone",
                        "tts_plugin_voice_id": str((winner or {}).get("voice_id") or "").strip(),
                        "voice_profile_id": str((winner or {}).get("voice_id") or "").strip(),
                        "voice_label": "Manfred Hoza · Unmixr-Klon",
                        "tts_base_voice_variant": "unmixr",
                        "unmixr_speaking_rate": str((winner or {}).get("speaking_rate") or "").strip(),
                        "unmixr_speaking_pitch": str((winner or {}).get("speaking_pitch") or "").strip(),
                        "unmixr_speaking_volume": str((winner or {}).get("speaking_volume") or "").strip(),
                    },
                    "completed_rows": len(rows),
                    "requested_rows": len(voice_ids) * len(combos),
                    "complete": False,
                }
            prompt_rows = [
                _evaluate_candidate_prompt(
                    slug=slug,
                    voice_id=voice_id,
                    prompt=prompt,
                    combo=combo,
                    reference_metrics=reference_metrics,
                    base_url=base_url,
                    timeout_seconds=prompt_timeout_seconds,
                )
                for prompt in prompts
            ]
            average_score = sum(float(item.get("score") or 0.0) for item in prompt_rows) / float(len(prompt_rows) or 1)
            average_feature_similarity = sum(float(item.get("feature_similarity") or 0.0) for item in prompt_rows) / float(len(prompt_rows) or 1)
            average_duration_seconds = sum(float(item.get("duration_seconds") or 0.0) for item in prompt_rows) / float(len(prompt_rows) or 1)
            row = {
                "voice_id": voice_id,
                "speaking_rate": str(combo.get("speaking_rate") or "").strip(),
                "speaking_pitch": str(combo.get("speaking_pitch") or "").strip(),
                "speaking_volume": str(combo.get("speaking_volume") or "").strip(),
                "average_score": round(average_score, 4),
                "average_feature_similarity": round(average_feature_similarity, 4),
                "average_duration_seconds": round(average_duration_seconds, 3),
                "prompts": prompt_rows,
            }
            rows.append(row)
            seen_keys.add(_row_key(row))
            rows_evaluated += 1
            if winner is None or float(row["average_score"]) > float(winner["average_score"]):
                winner = row
            _write_checkpoint()
    if winner is None:
        raise RuntimeError("no_unmixr_candidates_evaluated")
    return {
        "slug": slug,
        "base_url": base_url,
        "reference_path": str(_reference_path(slug=slug)),
        "rows": rows,
        "winner": winner,
        "completed_rows": len(rows),
        "requested_rows": len(voice_ids) * len(combos),
        "complete": True,
        "recommended_config": {
            "tts_plugin": "unmixr_clone",
            "tts_plugin_voice_id": str(winner.get("voice_id") or "").strip(),
            "voice_profile_id": str(winner.get("voice_id") or "").strip(),
            "voice_label": "Manfred Hoza · Unmixr-Klon",
            "tts_base_voice_variant": "unmixr",
            "unmixr_speaking_rate": str(winner.get("speaking_rate") or "").strip(),
            "unmixr_speaking_pitch": str(winner.get("speaking_pitch") or "").strip(),
            "unmixr_speaking_volume": str(winner.get("speaking_volume") or "").strip(),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare existing Unmixr memorial clones and recommend the best live config.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--voice-id", action="append", default=[])
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--exhaustive-prosody", action="store_true")
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
    report = compare_unmixr_clones(
        slug=slug,
        base_url=base_url,
        voice_ids=voice_ids,
        prompts=prompts,
        combos=_prosody_combos(exhaustive=bool(args.exhaustive_prosody)),
        output_path=Path(output) if output else None,
        resume=bool(args.resume),
        max_rows=max(0, int(args.max_rows or 0)),
        prompt_timeout_seconds=max(1.0, float(args.prompt_timeout_seconds or 90.0)),
    )
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
