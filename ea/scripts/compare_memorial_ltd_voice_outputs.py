from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

from app.services.memorial_openvoice import unmixr_synthesize_request


DEFAULT_PROMPTS = [
    "Ja. Ich bin da.",
    "Rechtlich muss man die Dinge sauber unterscheiden.",
]


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
    return {
        "prompt": prompt,
        "unmixr": {
            "similarity": round(float(unmixr_similarity), 4),
            "transcript_text": str(unmixr_transcript.get("transcript_text") or unmixr_transcript.get("text") or "").strip(),
        },
        "voicewave": {
            "similarity": round(float(voicewave_similarity), 4),
            "transcript_text": str(voicewave_transcript.get("transcript_text") or voicewave_transcript.get("text") or "").strip(),
            "audio_path": voicewave_audio_path.as_posix(),
        },
    }


def compare_outputs(*, base_url: str, prompts: list[str], output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [_compare_prompt(prompt=prompt, base_url=base_url, output_dir=output_dir) for prompt in prompts]
    unmixr_average = sum(float(item["unmixr"]["similarity"]) for item in rows) / float(len(rows) or 1)
    voicewave_average = sum(float(item["voicewave"]["similarity"]) for item in rows) / float(len(rows) or 1)
    return {
        "base_url": base_url,
        "prompts": rows,
        "averages": {
            "unmixr_similarity": round(unmixr_average, 4),
            "voicewave_similarity": round(voicewave_average, 4),
        },
        "winner": "unmixr" if unmixr_average >= voicewave_average else "voicewave",
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
