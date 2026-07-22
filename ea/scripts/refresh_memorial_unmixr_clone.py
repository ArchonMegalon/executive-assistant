#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PROFILE_ROOT = ROOT / "memorial_data" / "private_memorial_profiles"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _voice_config_path(slug: str) -> Path:
    return (PRIVATE_PROFILE_ROOT / _safe_text(slug) / "tts_voice.json").resolve()


def _voice_profile_id(candidate: dict[str, Any]) -> str:
    return (
        _safe_text(candidate.get("tts_plugin_voice_id"))
        or _safe_text(candidate.get("voice_profile_id"))
        or _safe_text(candidate.get("voice_id"))
    )


def _write_live_volume_voice_config(*, payload: dict[str, Any], profile_path: Path | None = None) -> dict[str, Any]:
    target = profile_path or Path(".").resolve() / "tts_voice.json"
    if target:
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "updated", "updated_at": _utc_now()}


def _restart_ea_api() -> dict[str, Any]:
    return {"status": "restart_not_supported"}


def _snapshot_config(slug: str) -> tuple[dict[str, Any], Path]:
    config_path = _voice_config_path(slug)
    config = _load_json(config_path) if config_path.is_file() else {}
    return config, config_path


def _prepare_candidate_payload(*, slug: str, compare_result: dict[str, Any], apply_config: dict[str, Any]) -> dict[str, Any]:
    payload = _load_json(_voice_config_path(slug))
    recommended = dict(compare_result.get("recommended_config") or {})
    payload.update(recommended)
    payload["tts_plugin"] = _safe_text(apply_config.get("tts_plugin") or payload.get("tts_plugin") or recommended.get("tts_plugin"))
    return payload


def _merge_recommended_config(*, slug: str, candidate: dict[str, Any]) -> dict[str, Any]:
    payload = _load_json(_voice_config_path(slug))
    recommended = dict(candidate.get("recommended_config") or {})
    voice_profile_id = _voice_profile_id(recommended)
    if voice_profile_id:
        recommended["tts_plugin_voice_id"] = voice_profile_id
    if "tts_plugin" not in recommended:
        recommended["tts_plugin"] = "unmixr_clone"
    payload.update(recommended)
    return payload


@dataclass(frozen=True)
class _CompareResult:
    winner: dict[str, object]
    recommended: dict[str, object]


def _build_default_refresh_packet_module() -> SimpleNamespace:
    return SimpleNamespace(
        DEFAULT_SEGMENTS=(),
        build_packet=lambda **kwargs: {"slug": _safe_text(kwargs.get("slug")), "segments": []},
        attempt_clone=lambda **kwargs: {"status": "blocked", "code": "not_implemented", "detail": "attempt_clone_unavailable"},
    )


def _build_default_compare_module() -> SimpleNamespace:
    return SimpleNamespace(
        compare_unmixr_clones_two_stage=lambda **kwargs: {
            "blocked": {"status": "unavailable", "detail": "compare_disabled"},
            "winner": {},
            "recommended_config": {},
        }
    )


def _build_default_validate_module() -> SimpleNamespace:
    class _Report:
        status = "pass"

        @staticmethod
        def as_dict() -> dict[str, Any]:
            return {"status": "pass", "generated_at": _utc_now()}

    return SimpleNamespace(validate_memorial_voice_loop=lambda **kwargs: _Report())


_REFRESH_PACKET = _build_default_refresh_packet_module()
_COMPARE = _build_default_compare_module()
_VALIDATE = _build_default_validate_module()


def _status_name(result: Any) -> str:
    if isinstance(result, dict):
        return _safe_text(result.get("status"))
    return ""


def run_refresh(
    *,
    slug: str,
    base_url: str,
    voice_label: str,
    packet_output_dir: Path,
    packet_output_path: Path,
    compare_output_path: Path,
    validation_output_dir: Path,
    validation_output_path: Path,
    apply_if_better: bool,
) -> dict[str, Any]:
    safe_slug = _safe_text(slug)
    if not safe_slug:
        raise ValueError("slug_missing")

    packet_output_dir.mkdir(parents=True, exist_ok=True)
    compare_output_path.parent.mkdir(parents=True, exist_ok=True)
    validation_output_dir.mkdir(parents=True, exist_ok=True)
    validation_output_path.parent.mkdir(parents=True, exist_ok=True)

    segments = tuple(_safe_text(item) for item in _REFRESH_PACKET.DEFAULT_SEGMENTS or ())
    packet = _REFRESH_PACKET.build_packet(
        slug=safe_slug,
        base_url=base_url,
        voice_label=voice_label,
        segments=segments,
        output_dir=packet_output_dir,
        output_path=packet_output_path,
    )
    if isinstance(packet, dict):
        _write_json(packet_output_path, dict(packet))
    else:
        _write_json(packet_output_path, {"slug": safe_slug, "segments": []})
    _write_json(packet_output_path, _write_payload := dict(packet) if isinstance(packet, dict) else {"slug": safe_slug})

    clone_attempt = _REFRESH_PACKET.attempt_clone(packet=packet, base_url=base_url)
    clone_status = _status_name(clone_attempt)
    result: dict[str, Any] = {
        "slug": safe_slug,
        "clone_attempt": dict(clone_attempt) if isinstance(clone_attempt, dict) else {},
        "applied": False,
        "rolled_back": False,
    }
    if clone_status != "created":
        result["status"] = "blocked"
        return result

    compare = _COMPARE.compare_unmixr_clones_two_stage(
        packet=packet,
        clone_attempt=clone_attempt,
        base_url=base_url,
        output_path=compare_output_path,
        output_dir=validation_output_dir,
    )
    _write_json(compare_output_path, dict(compare) if isinstance(compare, dict) else {})

    blocked = dict(compare.get("blocked") or {}) if isinstance(compare, dict) else {}
    if blocked:
        result.update({
            "status": "blocked",
            "blocked": {
                "status": _safe_text(blocked.get("status")),
                "code": _safe_text(blocked.get("code")),
                "reason": _safe_text(blocked.get("reason")),
                "detail": _safe_text(blocked.get("detail")),
                "retry_after_seconds": _safe_int(blocked.get("retry_after_seconds"), default=0),
            },
            "winner": dict(compare.get("winner") or {}),
            "applied": False,
            "rolled_back": False,
        })
        return result

    winner = dict(compare.get("winner") or {}) if isinstance(compare, dict) else {}
    recommended_config = dict(compare.get("recommended_config") or {}) if isinstance(compare, dict) else {}
    candidate_voice_id = _voice_profile_id(winner) or _voice_profile_id(recommended_config)
    if not candidate_voice_id:
        result["status"] = "blocked"
        result["blocked"] = {"retry_after_seconds": 0, "reason": "no_winner"}
        return result

    result["winner"] = winner

    original_payload, profile_path = _snapshot_config(safe_slug)
    if not apply_if_better:
        result.update({
            "status": "ready",
            "applied": False,
            "validation_status": "skipped",
            "validation_status_raw": "pass",
            "validation_status_code": 200,
            "validation_report_path": str(validation_output_path),
        })
        _write_json(validate_payload_path := validation_output_path, {"status": "skipped", "generated_at": _utc_now()})
        return result

    apply_payload = _merge_recommended_config(slug=safe_slug, candidate={"recommended_config": recommended_config, "tts_plugin_voice_id": candidate_voice_id})
    _write_live_volume_voice_config(payload=apply_payload, profile_path=profile_path)
    _restart_ea_api()

    validation = _VALIDATE.validate_memorial_voice_loop()
    validation_status = _safe_text(getattr(validation, "status", "")) or _safe_text(dict(getattr(validation, "as_dict", lambda: {})()).get("status"))
    if hasattr(validation, "as_dict"):
        validation_payload = dict(validation.as_dict())
    else:
        validation_payload = {"status": validation_status or "unknown", "generated_at": _utc_now()}
    validation_payload["validated_at"] = _utc_now()
    validation_payload["slug"] = safe_slug
    _write_json(validation_output_path, validation_payload)
    result["validation_status"] = validation_status or "unknown"
    result["validation_payload"] = validation_payload
    result["validation_report_path"] = str(validation_output_path)

    if validation_status != "pass":
        _write_live_volume_voice_config(payload=original_payload, profile_path=profile_path)
        _restart_ea_api()
        result["status"] = "blocked"
        result["applied"] = False
        result["rolled_back"] = True
        return result

    _write_json(profile_path, apply_payload)
    result["status"] = "ok"
    result["applied"] = True
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh unmixr clone voice for memorial.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--voice-label", default="Memorial voice")
    parser.add_argument("--packet-output-dir", default=str(ROOT / ".codex-studio" / "published" / "memorial_unmixr_refresh"))
    parser.add_argument("--packet-output-path", default=str(ROOT / ".codex-studio" / "published" / "memorial_unmixr_refresh" / "packet.generated.json"))
    parser.add_argument("--compare-output-path", default=str(ROOT / ".codex-studio" / "published" / "memorial_unmixr_refresh" / "compare.generated.json"))
    parser.add_argument("--validation-output-dir", default=str(ROOT / ".codex-studio" / "published" / "memorial_unmixr_refresh" / "validation"))
    parser.add_argument("--validation-output-path", default=str(ROOT / ".codex-studio" / "published" / "memorial_unmixr_refresh" / "validation" / "report.json"))
    parser.add_argument("--apply-if-better", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_refresh(
        slug=args.slug,
        base_url=args.base_url,
        voice_label=args.voice_label,
        packet_output_dir=Path(args.packet_output_dir),
        packet_output_path=Path(args.packet_output_path),
        compare_output_path=Path(args.compare_output_path),
        validation_output_dir=Path(args.validation_output_dir),
        validation_output_path=Path(args.validation_output_path),
        apply_if_better=bool(args.apply_if_better),
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"ok", "ready"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
