#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PROFILES_ROOT = ROOT / "memorial_data" / "private_memorial_profiles"

def _load_compare_module() -> Any:
    module_path = Path(__file__).resolve().parent / "compare_memorial_ltd_voice_outputs.py"
    spec = importlib.util.spec_from_file_location(
        "compare_memorial_ltd_voice_outputs",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("compare_module_load_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    _COMPARE = _load_compare_module()
except Exception:  # pragma: no cover - import safety in unusual packaging setups
    _COMPARE = SimpleNamespace(compare_outputs=None)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    return number


def _voice_label_for_slug(slug: str) -> str:
    safe_slug = _safe_text(slug).lower()
    if safe_slug == "manfred":
        return "Manfred Hoza Memorial"
    base = " ".join(segment.capitalize() for segment in safe_slug.replace("_", "-").replace("-", " ").split())
    return f"{base} Memorial".strip() or "Memorial Voice Backup"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return dict(raw) if isinstance(raw, dict) else {}


def _voice_config_path(slug: str) -> Path:
    return (PRIVATE_PROFILES_ROOT / _safe_text(slug) / "tts_voice.json").resolve()


def _merge_backup_candidate(
    *,
    payload: dict[str, Any],
    slug: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(payload)
    backups = dict(merged.get("tts_backup_candidates") or {})
    existing = dict(backups.get("voicewave") or {})
    merged_back = {
        "status": _safe_text(candidate.get("status")) or existing.get("status") or "blocked",
        "reason": _safe_text(candidate.get("reason")),
        "detail": _safe_text(candidate.get("detail")),
        "average_similarity": _safe_float(candidate.get("average_similarity"), default=_safe_float(existing.get("average_similarity"), default=0.0)),
        "average_transcript_f1": _safe_float(candidate.get("average_transcript_f1"), default=_safe_float(existing.get("average_transcript_f1"), default=0.0)),
        "min_transcript_f1": _safe_float(candidate.get("min_transcript_f1"), default=_safe_float(existing.get("min_transcript_f1"), default=0.0)),
        "drift_prompts": list(candidate.get("drift_prompts") or existing.get("drift_prompts") or []),
    }
    if candidate.get("status") == "ready":
        merged_back["voice_label"] = _voice_label_for_slug(slug)
    merged_back["reason"] = merged_back["reason"] or (candidate.get("reason") and _safe_text(candidate.get("reason"))) or merged_back["reason"]
    backups["voicewave"] = merged_back
    merged["tts_backup_candidates"] = backups
    return merged


def _run_compare(
    *,
    slug: str,
    base_url: str,
    prompts: list[str],
    compare_output_dir: Path,
    compare_output_path: Path,
) -> dict[str, Any]:
    compare_outputs = getattr(_COMPARE, "compare_outputs", None)
    if not callable(compare_outputs):
        raise RuntimeError("compare_script_missing")
    compare_output_dir.mkdir(parents=True, exist_ok=True)
    compare_output_path.parent.mkdir(parents=True, exist_ok=True)
    report = compare_outputs(
        base_url=base_url,
        prompts=prompts,
        output_dir=compare_output_dir,
    )
    payload = {
        "generated_at": _utc_now(),
        "slug": _safe_text(slug),
        "base_url": _safe_text(base_url),
        "compare_output": report,
    }
    _write_json(compare_output_path, payload)
    return report


def run_refresh(
    *,
    slug: str,
    base_url: str,
    prompts: list[str],
    compare_output_dir: Path,
    compare_output_path: Path,
    apply_metadata: bool,
) -> dict[str, Any]:
    safe_slug = _safe_text(slug)
    if not safe_slug:
        raise ValueError("slug_missing")

    try:
        report = _run_compare(
            slug=safe_slug,
            base_url=base_url,
            prompts=prompts,
            compare_output_dir=compare_output_dir,
            compare_output_path=compare_output_path,
        )
        candidate = dict(report.get("voicewave_backup_candidate") or {})
        status = "blocked" if _safe_text(candidate.get("status")) == "blocked" else "ready"
    except Exception as exc:
        detail = _safe_text(exc)
        status = "blocked"
        reason = "compare_failed"
        candidate = {
            "status": "blocked",
            "reason": reason,
            "detail": detail or reason,
            "average_similarity": 0.0,
            "average_transcript_f1": 0.0,
            "min_transcript_f1": 0.0,
            "drift_prompts": [],
        }
        report = {"voicewave_backup_candidate": candidate}
        status = "blocked"

    result: dict[str, Any] = {
        "slug": safe_slug,
        "status": status,
        "winner": _safe_text(report.get("winner")),
        "voicewave_backup_candidate": dict(candidate),
        "applied_metadata": bool(apply_metadata),
        "compare_output_path": str(compare_output_path),
        "compare_output_exists": compare_output_path.is_file(),
    }

    if not apply_metadata:
        return result

    try:
        config_path = _voice_config_path(safe_slug)
        payload = _load_json(config_path) if config_path.is_file() else {}
        updated = _merge_backup_candidate(payload=payload, slug=safe_slug, candidate=candidate)
        if _safe_text(candidate.get("status")) == "ready":
            updated = dict(updated)
            updated["tts_backup_candidates"]["voicewave"]["voice_label"] = _voice_label_for_slug(safe_slug)
        _write_json(config_path, updated)
    except Exception as exc:
        result["status"] = "blocked" if result["status"] != "ready" else result["status"]
        result["metadata_write_error"] = _safe_text(exc)
        result["status"] = "blocked"
        result["applied_metadata"] = False
        return result

    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare LTD prompt output quality for unmixr and voicewave voice candidates."
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--compare-output-dir", default=str(ROOT / ".codex-studio" / "published" / "memorial_voicewave_backup"))
    parser.add_argument("--compare-output-path", default=str(ROOT / ".codex-studio" / "published" / "memorial_voicewave_backup" / "compare.generated.json"))
    parser.add_argument("--apply-metadata", action="store_true")
    parser.add_argument("--prompt-json")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    prompts = list(args.prompt)
    if not prompts and args.prompt_json:
        loaded = json.loads(args.prompt_json)
        prompts = list(loaded) if isinstance(loaded, list) else []
    elif not prompts:
        prompts = [
            "Ja. Ich bin da.",
            "Rechtlich muss man die Dinge sauber unterscheiden.",
            "Bitte schütze diesen Teil der Familie.",
        ]
    result = run_refresh(
        slug=args.slug,
        base_url=args.base_url,
        prompts=prompts,
        compare_output_dir=Path(args.compare_output_dir),
        compare_output_path=Path(args.compare_output_path),
        apply_metadata=bool(args.apply_metadata),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"ready", "ok"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
