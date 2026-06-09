from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def _load_module(script_name: str):
    import sys

    script_path = Path(__file__).with_name(script_name)
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_unavailable:{script_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_COMPARE = _load_module("compare_memorial_ltd_voice_outputs.py")


def _voice_config_path(slug: str) -> Path:
    return Path("/docker/EA/memorial_data/private_memorial_profiles") / slug / "tts_voice.json"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _voicewave_backup_payload(*, compare_report: dict[str, object]) -> dict[str, object]:
    candidate = dict(compare_report.get("voicewave_backup_candidate") or {})
    averages = dict(compare_report.get("averages") or {})
    return {
        "provider": "voicewave",
        "voice_label": "Manfred Hoza Memorial",
        "status": str(candidate.get("status") or "blocked"),
        "reason": str(candidate.get("reason") or ""),
        "average_similarity": float(candidate.get("average_similarity") or 0.0),
        "average_transcript_f1": float(candidate.get("average_transcript_f1") or 0.0),
        "min_transcript_f1": float(candidate.get("min_transcript_f1") or 0.0),
        "drift_prompts": list(candidate.get("drift_prompts") or []),
        "winner": str(compare_report.get("winner") or ""),
        "unmixr_similarity": float(averages.get("unmixr_similarity") or 0.0),
        "voicewave_similarity": float(averages.get("voicewave_similarity") or 0.0),
        "unmixr_transcript_f1": float(averages.get("unmixr_transcript_f1") or 0.0),
        "voicewave_transcript_f1": float(averages.get("voicewave_transcript_f1") or 0.0),
    }


def run_refresh(
    *,
    slug: str,
    base_url: str,
    prompts: list[str],
    compare_output_dir: Path,
    compare_output_path: Path,
    apply_metadata: bool,
) -> dict[str, object]:
    try:
        compare_report = _COMPARE.compare_outputs(
            base_url=base_url,
            prompts=prompts or list(_COMPARE.DEFAULT_PROMPTS),
            output_dir=compare_output_dir,
        )
    except Exception as exc:
        result = {
            "slug": slug,
            "base_url": base_url,
            "compare_path": compare_output_path.as_posix(),
            "voicewave_backup_candidate": {
                "provider": "voicewave",
                "voice_label": "Manfred Hoza Memorial",
                "status": "blocked",
                "reason": "compare_failed",
                "detail": str(exc)[:300],
            },
            "applied_metadata": False,
            "status": "blocked",
        }
        if apply_metadata:
            config_path = _voice_config_path(slug)
            config = _load_json(config_path)
            backup_candidates = dict(config.get("tts_backup_candidates") or {})
            backup_candidates["voicewave"] = dict(result["voicewave_backup_candidate"])
            config["tts_backup_candidates"] = backup_candidates
            _write_json(config_path, config)
            result["applied_metadata"] = True
            result["voice_config_path"] = config_path.as_posix()
        _write_json(compare_output_path, result)
        return result
    _write_json(compare_output_path, compare_report)
    result = {
        "slug": slug,
        "base_url": base_url,
        "compare_path": compare_output_path.as_posix(),
        "voicewave_backup_candidate": _voicewave_backup_payload(compare_report=compare_report),
        "applied_metadata": False,
    }
    if apply_metadata:
        config_path = _voice_config_path(slug)
        config = _load_json(config_path)
        backup_candidates = dict(config.get("tts_backup_candidates") or {})
        backup_candidates["voicewave"] = dict(result["voicewave_backup_candidate"])
        config["tts_backup_candidates"] = backup_candidates
        _write_json(config_path, config)
        result["applied_metadata"] = True
        result["voice_config_path"] = config_path.as_posix()
    result["status"] = str((result["voicewave_backup_candidate"] or {}).get("status") or "blocked")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate and persist a validated VoiceWave backup candidate for a memorial voice.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--output-dir", default="/tmp/manfred_voicewave_backup")
    parser.add_argument("--output", default="")
    parser.add_argument("--apply-metadata", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(str(args.output_dir or "/tmp/manfred_voicewave_backup")).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(str(args.output or "")).expanduser() if str(args.output or "").strip() else output_dir / "voicewave_backup.generated.json"
    prompts = [str(item).strip() for item in list(args.prompt or []) if str(item).strip()]
    result = run_refresh(
        slug=str(args.slug or "manfred").strip() or "manfred",
        base_url=str(args.base_url or "http://127.0.0.1:8090").strip() or "http://127.0.0.1:8090",
        prompts=prompts,
        compare_output_dir=output_dir / "compare",
        compare_output_path=output_dir / "compare.generated.json",
        apply_metadata=bool(args.apply_metadata),
    )
    _write_json(output_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
