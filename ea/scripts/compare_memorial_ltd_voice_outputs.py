from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.memorial_openvoice import unmixr_synthesize_request

ENV_FILES = (
    ROOT / ".env",
    ROOT.parent / ".env",
)


DEFAULT_PROMPTS = [
    "Ja. Ich bin da.",
    "Rechtlich muss man die Dinge sauber unterscheiden.",
]


def _prime_env_from_files() -> None:
    for env_file in ENV_FILES:
        if not env_file.is_file():
            continue
        for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip()


_prime_env_from_files()


def _load_optimizer_module():
    script_path = Path(__file__).with_name("optimize_memorial_openvoice_clone.py")
    spec = importlib.util.spec_from_file_location("optimize_memorial_openvoice_clone", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("optimizer_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_OPTIMIZER = _load_optimizer_module()


def _render_voicewave(*, text: str, audio_output: Path, json_output: Path, screenshot_output: Path) -> bytes:
    login_email = str(os.environ.get("VOICEWAVE_LOGIN_EMAIL") or "").strip()
    login_password = str(os.environ.get("VOICEWAVE_LOGIN_PASSWORD") or "").strip()
    if not login_email or not login_password:
        raise RuntimeError("voicewave_login_missing")
    script = Path("/docker/EA/scripts/voicewave_memorial_voice.py")
    completed = subprocess.run(
        [
            "python3",
            str(script),
            "render",
            "--voice-label",
            "Manfred Hoza Memorial",
            "--text",
            text,
            "--login-email",
            login_email,
            "--login-password",
            login_password,
            "--output",
            str(json_output),
            "--audio-output",
            str(audio_output),
            "--screenshot-output",
            str(screenshot_output),
            "--timeout-seconds",
            "240",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not audio_output.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()[:400]
        raise RuntimeError(f"voicewave_render_failed:{detail or completed.returncode}")
    return audio_output.read_bytes()


def _ensure_wav_bytes(*, payload: bytes, content_type: str) -> bytes:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return payload
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    with tempfile.TemporaryDirectory(prefix="memorial-ltd-compare-") as temp_dir:
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
            detail = (completed.stderr or "").strip()[:300]
            raise RuntimeError(f"audio_convert_failed:{detail or completed.returncode}")
        return output_path.read_bytes()


def _compare_prompt(*, prompt: str, base_url: str, output_dir: Path) -> dict[str, object]:
    reference = Path("/docker/EA/memorial_data/private_memorial_profiles/manfred/voice_profile/optimization/candidates/oSQ9FhFc4YI-01440s-28.wav")
    reference_metrics = _OPTIMIZER._wav_metrics_from_bytes(reference.read_bytes())
    unmixr_row: dict[str, object]
    try:
        unmixr_audio, unmixr_content_type = unmixr_synthesize_request(
            text=prompt,
            voice_id="558a4e6f-b80b-474d-a48b-09bd46c4f9eb",
            lang="de-AT",
            speaking_rate="medium",
            speaking_pitch="medium",
            speaking_volume="low",
        )
        unmixr_wav = _ensure_wav_bytes(payload=unmixr_audio, content_type=unmixr_content_type)
        unmixr_transcript = _OPTIMIZER._transcribe_audio_bytes(unmixr_wav, content_type="audio/wav", slug="manfred", base_url=base_url)
        unmixr_similarity = _OPTIMIZER._voice_feature_similarity(reference_metrics, _OPTIMIZER._wav_metrics_from_bytes(unmixr_wav))
        unmixr_transcript_text = str(unmixr_transcript.get("transcript_text") or unmixr_transcript.get("text") or "").strip()
        unmixr_overlap = _OPTIMIZER._token_overlap(prompt, unmixr_transcript_text)
        unmixr_row = {
            "similarity": round(float(unmixr_similarity), 4),
            "transcript_text": unmixr_transcript_text,
            "transcript_f1": round(float(unmixr_overlap.get("f1") or 0.0), 4),
            "status": "ok",
        }
    except Exception as exc:
        unmixr_row = {
            "similarity": 0.0,
            "transcript_text": "",
            "transcript_f1": 0.0,
            "status": "blocked",
            "detail": str(exc)[:300],
        }

    voicewave_audio_path = output_dir / f"voicewave-{_OPTIMIZER._normalize_text(prompt).replace(' ', '_') or 'sample'}.wav"
    voicewave_json_path = output_dir / f"{voicewave_audio_path.stem}.json"
    voicewave_png_path = output_dir / f"{voicewave_audio_path.stem}.png"
    voicewave_audio = _render_voicewave(
        text=prompt,
        audio_output=voicewave_audio_path,
        json_output=voicewave_json_path,
        screenshot_output=voicewave_png_path,
    )
    voicewave_transcript = _OPTIMIZER._transcribe_audio_bytes(voicewave_audio, content_type="audio/wav", slug="manfred", base_url=base_url)
    voicewave_similarity = _OPTIMIZER._voice_feature_similarity(reference_metrics, _OPTIMIZER._wav_metrics_from_bytes(voicewave_audio))
    voicewave_transcript_text = str(voicewave_transcript.get("transcript_text") or voicewave_transcript.get("text") or "").strip()
    voicewave_overlap = _OPTIMIZER._token_overlap(prompt, voicewave_transcript_text)
    return {
        "prompt": prompt,
        "unmixr": unmixr_row,
        "voicewave": {
            "similarity": round(float(voicewave_similarity), 4),
            "transcript_text": voicewave_transcript_text,
            "transcript_f1": round(float(voicewave_overlap.get("f1") or 0.0), 4),
            "audio_path": voicewave_audio_path.as_posix(),
        },
    }


def _voicewave_backup_candidate(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {
            "status": "blocked",
            "reason": "no_rows",
            "average_similarity": 0.0,
            "average_transcript_f1": 0.0,
            "min_transcript_f1": 0.0,
            "drift_prompts": [],
        }
    similarity_values = [float((row.get("voicewave") or {}).get("similarity") or 0.0) for row in rows]
    f1_values = [float((row.get("voicewave") or {}).get("transcript_f1") or 0.0) for row in rows]
    drift_prompts = [
        str(row.get("prompt") or "")
        for row in rows
        if float((row.get("voicewave") or {}).get("transcript_f1") or 0.0) < 0.82
    ]
    average_similarity = sum(similarity_values) / float(len(similarity_values) or 1)
    average_transcript_f1 = sum(f1_values) / float(len(f1_values) or 1)
    min_transcript_f1 = min(f1_values) if f1_values else 0.0
    ready = average_similarity >= 0.58 and average_transcript_f1 >= 0.9 and min_transcript_f1 >= 0.82 and not drift_prompts
    return {
        "status": "ready" if ready else "blocked",
        "reason": "" if ready else "voicewave_backup_gate_failed",
        "average_similarity": round(average_similarity, 4),
        "average_transcript_f1": round(average_transcript_f1, 4),
        "min_transcript_f1": round(min_transcript_f1, 4),
        "drift_prompts": drift_prompts,
    }


def compare_outputs(*, base_url: str, prompts: list[str], output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [_compare_prompt(prompt=prompt, base_url=base_url, output_dir=output_dir) for prompt in prompts]
    unmixr_available_rows = [item for item in rows if str((item.get("unmixr") or {}).get("status") or "ok") == "ok"]
    unmixr_average = sum(float(item["unmixr"]["similarity"]) for item in unmixr_available_rows) / float(len(unmixr_available_rows) or 1)
    voicewave_average = sum(float(item["voicewave"]["similarity"]) for item in rows) / float(len(rows) or 1)
    unmixr_transcript_average = sum(float(item["unmixr"]["transcript_f1"]) for item in unmixr_available_rows) / float(len(unmixr_available_rows) or 1)
    voicewave_transcript_average = sum(float(item["voicewave"]["transcript_f1"]) for item in rows) / float(len(rows) or 1)
    unmixr_status = "ok" if unmixr_available_rows else "blocked"
    return {
        "base_url": base_url,
        "prompts": rows,
        "averages": {
            "unmixr_similarity": round(unmixr_average, 4),
            "voicewave_similarity": round(voicewave_average, 4),
            "unmixr_transcript_f1": round(unmixr_transcript_average, 4),
            "voicewave_transcript_f1": round(voicewave_transcript_average, 4),
        },
        "unmixr_status": unmixr_status,
        "winner": "unmixr" if unmixr_status == "ok" and unmixr_average >= voicewave_average else ("voicewave" if voicewave_average > 0 else "unavailable"),
        "voicewave_backup_candidate": _voicewave_backup_candidate(rows),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare current memorial LTD voice outputs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--output-dir", default="/tmp/memorial_ltd_compare")
    parser.add_argument("--output", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    prompts = [str(item).strip() for item in list(args.prompt or []) if str(item).strip()] or list(DEFAULT_PROMPTS)
    report = compare_outputs(
        base_url=str(args.base_url or "http://127.0.0.1:8090").strip() or "http://127.0.0.1:8090",
        prompts=prompts,
        output_dir=Path(str(args.output_dir or "/tmp/memorial_ltd_compare")).expanduser(),
    )
    output = str(args.output or "").strip()
    if output:
        output_path = Path(output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
