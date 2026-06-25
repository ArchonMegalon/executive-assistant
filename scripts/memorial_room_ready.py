#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import scripts.memorial_audio_probe as audio_probe
import scripts.memorial_showtime as showtime

_OPTIONAL_AVATAR_WARN_CODES = {
    "avatar_disabled_label_missing",
    "avatar_manifest_missing",
    "avatar_video_not_published",
}


def latest_audio(root: Path, slug: str, newer_than_epoch: float = 0.0) -> Path | None:
    suffix_rank = {".wav": 0, ".mp3": 1}
    candidates = sorted(
        (item for item in root.glob(f"{slug}-demo-tts.*") if item.is_file()),
        key=lambda item: (item.stat().st_mtime_ns, suffix_rank.get(item.suffix.lower(), 0), item.name),
    )
    if not candidates:
        return None
    newest = candidates[-1]
    return newest if newest.stat().st_mtime >= newer_than_epoch else None


@dataclass
class StepResult:
    name: str
    command: list[str]
    cwd: str
    gate: str
    returncode: int
    duration_ms: int
    stdout_tail: str = ""
    semantic_status: str = "pass"
    semantic_detail: dict[str, object] = field(default_factory=dict)

    @property
    def effective_status(self) -> str:
        if self.returncode != 0 or self.semantic_status == "fail":
            return "fail"
        warn_codes = set(self.semantic_detail.get("warn_codes") or [])
        warn_commands = [str(item) for item in list(self.semantic_detail.get("warn_commands") or [])]
        if self.semantic_status == "warn":
            if warn_commands and all("verify_memorial_video_call_avatar_ready.py" in item for item in warn_commands):
                return "pass"
            if warn_codes and not (warn_codes - _OPTIONAL_AVATAR_WARN_CODES):
                return "pass"
            if not warn_codes or warn_codes - _OPTIONAL_AVATAR_WARN_CODES:
                return "warn"
        return "pass"


@dataclass
class RoomReport:
    slug: str
    base_url: str
    output_dir: str
    started_at_epoch: int
    results: list[StepResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        values = [item.effective_status for item in self.results]
        if "fail" in values:
            return "fail"
        if "warn" in values:
            return "warn"
        return "pass"

    def as_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "output_dir": self.output_dir,
            "status": self.status,
            "results": [{**asdict(item), "effective_status": item.effective_status} for item in self.results],
        }


def _semantic_from_payload(payload: dict[str, object]) -> tuple[str, dict[str, object]]:
    status = str(payload.get("status") or "pass")
    findings = [dict(item) for item in list(payload.get("findings") or []) if isinstance(item, dict)]
    results = [dict(item) for item in list(payload.get("results") or []) if isinstance(item, dict)]
    warn_codes = [str(item.get("code") or "") for item in findings if str(item.get("status") or "") == "warn"]
    warn_steps = [str(item.get("name") or "") for item in results if str(item.get("effective_status") or "") == "warn"]
    warn_commands: list[str] = []
    for item in results:
        detail = dict(item.get("semantic_detail") or {})
        for command in list(detail.get("warn_commands") or []):
            if command not in warn_commands:
                warn_commands.append(str(command))
        for code in list(detail.get("warn_codes") or []):
            if code not in warn_codes:
                warn_codes.append(str(code))
    return status, {"warn_codes": warn_codes, "warn_steps": warn_steps, "warn_commands": warn_commands}


def avatar_video_check_command(*, slug: str, base_url: str) -> list[str]:
    return ["python3", "scripts/verify_memorial_video_call_avatar_ready.py", "--slug", slug, "--base-url", base_url, "--json"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--questions", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--skip-exit-gates", action="store_true")
    parser.add_argument("--launch-mode", action="store_true")
    parser.add_argument("--avatar-required", action="store_true")
    parser.add_argument("--avatar-optional", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    showtime_args = argparse.Namespace(
        slug=args.slug,
        base_url=args.base_url,
        questions=args.questions,
        skip_tts=False,
        skip_chat=False,
        skip_unit_contracts=False if args.launch_mode else True,
        skip_snapshot=False,
        skip_exit_gates=args.skip_exit_gates,
        optional_exit_gates=bool(args.avatar_required or args.avatar_optional),
        avatar_required=args.avatar_required,
        avatar_optional=args.avatar_optional,
        allow_missing_stt=False,
        launch_mode=args.launch_mode,
        output_dir=str(output_dir),
    )
    payload = showtime.run_showtime(showtime_args)
    report = RoomReport(slug=args.slug, base_url=args.base_url, output_dir=str(output_dir), started_at_epoch=0)
    status, detail = _semantic_from_payload(payload)
    report.results.append(StepResult("showtime", ["python3", "scripts/memorial_showtime.py"], str(output_dir), "required", 0 if payload.get("status") in {"pass", "warn"} else 1, 1, json.dumps(payload), status, detail))
    if args.avatar_required or args.avatar_optional:
        avatar_step = next((item for item in list(payload.get("results") or []) if str(item.get("name") or "") == "avatar_video_call_status"), None)
        if isinstance(avatar_step, dict):
            report.results.append(
                StepResult(
                    "avatar_video_call_status",
                    avatar_video_check_command(slug=args.slug, base_url=args.base_url),
                    str(output_dir),
                    "required" if args.avatar_required else "warning",
                    0 if str(avatar_step.get("effective_status") or "") in {"pass", "warn"} else 1,
                    1,
                    str(avatar_step.get("stdout_tail") or ""),
                    str(avatar_step.get("semantic_status") or "pass"),
                    dict(avatar_step.get("semantic_detail") or {}),
                )
            )
    audio_path = latest_audio(output_dir, args.slug)
    if audio_path is None:
        raise SystemExit("missing_demo_audio")
    audio_report = audio_probe.analyze_audio(audio_path, threshold=0.012, min_duration=1.2, min_lead_silence=0.12, min_tail_silence=0.20, min_rms=0.004, max_clip_ratio=0.004)
    audio_payload = audio_report.as_dict()
    (output_dir / "audio_probe.json").write_text(json.dumps(audio_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "audio_probe.md").write_text(f"# Audio Probe\n\nStatus: {audio_payload['status']}\n", encoding="utf-8")
    report.results.append(StepResult("audio_probe", ["python3", "scripts/memorial_audio_probe.py", str(audio_path), "--json"], str(output_dir), "required", 0 if audio_payload["status"] in {"pass", "warn"} else 1, 1, json.dumps(audio_payload), audio_payload["status"], _semantic_from_payload(audio_payload)[1]))
    room_payload = report.as_dict()
    (output_dir / "room_ready_report.json").write_text(json.dumps(room_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "room_ready_report.md").write_text(f"# Room Ready\n\nStatus: {room_payload['status']}\n", encoding="utf-8")
    print(json.dumps(room_payload, ensure_ascii=False, indent=None if args.json else 2))
    return 0 if room_payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
