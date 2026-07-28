from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module(script_name: str):
    import importlib.util

    script_path = Path(__file__).with_name(script_name)
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_unavailable:{script_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_REFRESH_PACKET = _load_module("prepare_memorial_unmixr_refresh_packet.py")
_COMPARE = _load_module("compare_memorial_unmixr_clones.py")
_VALIDATE = _load_module("validate_memorial_voice_loop.py")
_RUNTIME_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")


def _voice_config_path(slug: str) -> Path:
    return (
        _REFRESH_PACKET.private_profile_dir()
        / _REFRESH_PACKET._safe_slug(slug)
        / "tts_voice.json"
    )


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_runtime_reference(value: object) -> str:
    configured = str(value or "").strip()
    match = _RUNTIME_PLACEHOLDER_RE.fullmatch(configured)
    if match is None:
        return configured
    env_name = match.group(1)
    resolved = str(os.environ.get(env_name) or "").strip()
    if resolved:
        return resolved
    try:
        resolved = subprocess.check_output(
            [
                "docker",
                "exec",
                "ea-api",
                "sh",
                "-lc",
                f'printf %s "${{{env_name}}}"',
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        resolved = ""
    return resolved


def _write_voice_config(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_live_volume_voice_config(*, slug: str, payload: dict[str, object]) -> dict[str, object]:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        "ea_ea_memorial_data:/data",
        "python:3.12-alpine",
        "python",
        "-c",
        (
            "import json; from pathlib import Path; "
            f"path=Path('/data/private_memorial_profiles/{slug}/tts_voice.json'); "
            "path.parent.mkdir(parents=True, exist_ok=True); "
            f"path.write_text({json.dumps(json.dumps(payload, ensure_ascii=False, indent=2))}, encoding='utf-8')"
        ),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return {
            "status": "failed",
            "detail": (completed.stderr or completed.stdout or "").strip()[:300],
        }
    return {"status": "updated"}


def _restart_ea_api() -> dict[str, object]:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "up",
            "-d",
            "--build",
            "--force-recreate",
            "ea-api",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "status": "failed",
            "detail": (completed.stderr or completed.stdout or "").strip()[:300],
        }
    return {"status": "restarted"}


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
    segment_paths: list[Path] | None = None,
    account_slot: str = "",
) -> dict[str, object]:
    slug = _REFRESH_PACKET._safe_slug(slug)
    selected_segments = (
        [Path(item).expanduser() for item in segment_paths]
        if segment_paths
        else _REFRESH_PACKET.configured_default_segment_paths(slug)
    )
    missing_segments = [path for path in selected_segments if not path.is_file()]
    if missing_segments:
        return {
            "slug": slug,
            "base_url": base_url,
            "status": "blocked",
            "code": "segment_missing",
            "missing_segment": missing_segments[0].name,
        }
    packet = _REFRESH_PACKET.build_packet(
        slug=slug,
        voice_label=voice_label,
        segment_paths=selected_segments,
        output_dir=packet_output_dir,
    )
    current_config_path = _voice_config_path(slug)
    if not current_config_path.is_file():
        packet["clone_attempt"] = {
            "status": "blocked",
            "code": "current_voice_config_missing",
        }
        packet_output_path.parent.mkdir(parents=True, exist_ok=True)
        packet_output_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "slug": slug,
            "base_url": base_url,
            "status": "blocked",
            "code": "current_voice_config_missing",
            "packet_path": packet_output_path.as_posix(),
        }
    current_config = _load_json(current_config_path)
    current_voice_id = _resolve_runtime_reference(
        current_config.get("tts_plugin_voice_id")
    )
    if not current_voice_id:
        packet["clone_attempt"] = {
            "status": "blocked",
            "code": "current_voice_id_unresolved",
        }
        packet_output_path.parent.mkdir(parents=True, exist_ok=True)
        packet_output_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "slug": slug,
            "base_url": base_url,
            "status": "blocked",
            "code": "current_voice_id_unresolved",
            "packet_path": packet_output_path.as_posix(),
        }
    packet["clone_attempt"] = _REFRESH_PACKET.attempt_clone(
        slug=slug,
        voice_label=voice_label,
        segment_paths=selected_segments,
        account_slot=str(account_slot or "").strip(),
    )
    packet_output_path.parent.mkdir(parents=True, exist_ok=True)
    packet_output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")

    result: dict[str, object] = {
        "slug": slug,
        "base_url": base_url,
        "packet_path": packet_output_path.as_posix(),
        "clone_attempt": packet.get("clone_attempt") or {},
    }
    attempt = result["clone_attempt"]
    if str((attempt or {}).get("status") or "") != "created":
        result["status"] = "blocked"
        return result

    new_voice_id = str((attempt or {}).get("voice_id") or "").strip()
    new_account_slot = str(
        (attempt or {}).get("account_slot")
        or account_slot
        or ""
    ).strip()
    current_account_slot = str(
        current_config.get("unmixr_account_slot")
        or "UNMIXR_API_KEY"
    ).strip()
    previous_config = dict(current_config)
    compare_report = _COMPARE.compare_unmixr_clones_two_stage(
        slug=slug,
        base_url=base_url,
        voice_ids=[current_voice_id, new_voice_id],
        prompts=list(_COMPARE.DEFAULT_PROMPTS),
        combos=_COMPARE._prosody_combos(exhaustive=False),
        postprocess_profiles=["unmixr_raw_preserve", "unmixr_natural_minimal", "unmixr_natural_soft"],
        shortlist_top_k=3,
        feature_output_path=compare_output_path.with_name(f"{compare_output_path.stem}.feature{compare_output_path.suffix or '.json'}"),
        final_output_path=compare_output_path,
        prompt_timeout_seconds=20.0,
        lead_in_ms=0,
        tail_silence_ms=0,
        takes_per_prompt=_COMPARE.DEFAULT_TAKES_PER_PROMPT,
        provider_language=_COMPARE.DEFAULT_PROVIDER_LANGUAGE,
        pronunciation_dict=dict(_COMPARE.DEFAULT_PRONUNCIATION_DICT),
        audio_output_dir=compare_output_path.parent / "audio",
        account_slots_by_voice={
            current_voice_id: current_account_slot,
            new_voice_id: new_account_slot,
        },
    )
    compare_output_path.parent.mkdir(parents=True, exist_ok=True)
    compare_output_path.write_text(json.dumps(compare_report, ensure_ascii=False, indent=2), encoding="utf-8")
    result["compare_path"] = compare_output_path.as_posix()
    result["winner"] = compare_report.get("winner") or {}
    result["applied"] = False
    if isinstance(compare_report.get("blocked"), dict):
        result["status"] = "blocked"
        result["blocked"] = compare_report.get("blocked") or {}
        return result

    winner_voice_id = str((compare_report.get("winner") or {}).get("voice_id") or "").strip()
    if apply_if_better and winner_voice_id == new_voice_id:
        recommended = dict(compare_report.get("recommended_config") or {})
        current_config.update(recommended)
        current_config["notes"] = (
            "Aktive Memorial-Stimme ist jetzt genau ein Unmixr-Klon. "
            "Diese Konfiguration stammt aus dem automatisierten Refresh-Clone-Vergleich."
        )
        _write_voice_config(_voice_config_path(slug), current_config)
        result["live_volume_write"] = _write_live_volume_voice_config(slug=slug, payload=current_config)
        result["ea_api_restart"] = _restart_ea_api()
        result["applied"] = True
        validation_report = _VALIDATE.validate_memorial_voice_loop(
            slug=slug,
            base_url=base_url,
            output_dir=validation_output_dir,
            direct_text="Klar. Worum geht es?",
            conversation_question="Hallo Manfred.",
        )
        validation_output_path.parent.mkdir(parents=True, exist_ok=True)
        validation_output_path.write_text(json.dumps(validation_report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        result["validation_path"] = validation_output_path.as_posix()
        result["validation_status"] = validation_report.status
        if str(validation_report.status or "").strip().lower() != "pass":
            _write_voice_config(_voice_config_path(slug), previous_config)
            result["rollback_live_volume_write"] = _write_live_volume_voice_config(slug=slug, payload=previous_config)
            result["rollback_ea_api_restart"] = _restart_ea_api()
            result["applied"] = False
            result["rolled_back"] = True
            result["status"] = "blocked"
            return result
    result["status"] = "ok"
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attempt a fresh memorial Unmixr clone refresh and optionally apply it if it wins.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--voice-label", default="Manfred Hoza Memorial Refresh")
    parser.add_argument("--segment", action="append", default=[])
    parser.add_argument("--account-slot", default="")
    parser.add_argument("--apply-if-better", action="store_true")
    parser.add_argument("--output-dir", default="/tmp/manfred_unmixr_refresh_run")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(str(args.output_dir or "/tmp/manfred_unmixr_refresh_run")).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(str(args.output or "")).expanduser() if str(args.output or "").strip() else output_dir / "refresh.generated.json"
    segment_values = [
        str(item).strip()
        for item in list(args.segment or [])
        if str(item).strip()
    ]
    result = run_refresh(
        slug=_REFRESH_PACKET._safe_slug(args.slug or "manfred"),
        base_url=str(args.base_url or "http://127.0.0.1:8090").strip() or "http://127.0.0.1:8090",
        voice_label=str(args.voice_label or "Manfred Hoza Memorial Refresh").strip() or "Manfred Hoza Memorial Refresh",
        packet_output_dir=output_dir / "packet",
        packet_output_path=output_dir / "packet" / "packet.generated.json",
        compare_output_path=output_dir / "compare.generated.json",
        validation_output_dir=output_dir / "validation",
        validation_output_path=output_dir / "validation" / "report.json",
        apply_if_better=bool(args.apply_if_better),
        segment_paths=[Path(item).expanduser() for item in segment_values] or None,
        account_slot=str(args.account_slot or "").strip(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
