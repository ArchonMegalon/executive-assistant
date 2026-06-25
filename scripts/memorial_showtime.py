#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import scripts.memorial_demo_rehearsal as rehearsal
import scripts.memorial_flagship_preflight as preflight
import scripts.memorial_launch_snapshot as snapshot
import scripts.validate_memorial_voice_loop as voice_loop
import scripts.verify_memorial_video_call_avatar_ready as avatar_ready

_OPTIONAL_AVATAR_WARN_CODES = {
    "avatar_disabled_label_missing",
    "avatar_manifest_missing",
    "avatar_video_not_published",
}


@dataclass
class Step:
    name: str
    command: list[str]
    cwd: str
    gate: str
    parse_json_status: bool = False
    output_path_arg: str = ""


@dataclass
class ShowtimeResult:
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
class ShowtimeReport:
    slug: str
    base_url: str
    started_at_epoch: int
    output_dir: str
    results: list[ShowtimeResult] = field(default_factory=list)

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
            "results": [
                {
                    **asdict(item),
                    "effective_status": item.effective_status,
                }
                for item in self.results
            ],
        }


def _extract_json_payload(result: ShowtimeResult, output_path_arg: str = "") -> dict[str, object]:
    if output_path_arg:
        return json.loads(Path(output_path_arg).read_text(encoding="utf-8"))
    return json.loads(result.stdout_tail or "{}")


def _semantic_from_payload(payload: dict[str, object]) -> tuple[str, dict[str, object]]:
    status = str(payload.get("status") or "pass")
    findings = [dict(item) for item in list(payload.get("findings") or payload.get("checks") or []) if isinstance(item, dict)]
    results = [dict(item) for item in list(payload.get("results") or payload.get("commands") or []) if isinstance(item, dict)]
    warn_codes = [str(item.get("code") or "") for item in findings if str(item.get("status") or "") == "warn"]
    warn_steps = [str(item.get("name") or "") for item in results if str(item.get("effective_status") or item.get("semantic_status") or "") == "warn"]
    warn_commands = [
        " ".join(item.get("command") or [])
        for item in results
        if str(item.get("semantic_status") or "") == "warn"
    ]
    if not warn_commands:
        for item in results:
            detail = dict(item.get("semantic_detail") or {})
            for command in list(detail.get("warn_commands") or []):
                if command not in warn_commands:
                    warn_commands.append(str(command))
            for code in list(detail.get("warn_codes") or []):
                if code not in warn_codes:
                    warn_codes.append(str(code))
    return status, {"warn_codes": warn_codes, "warn_steps": warn_steps, "warn_commands": warn_commands, "command_count": len(results), "finding_count": len(findings)}


def build_steps(args: argparse.Namespace, output_dir: Path) -> list[Step]:
    steps = [
        Step("filesystem_preflight", ["python3", "scripts/memorial_flagship_preflight.py", args.slug], str(output_dir), "required", True),
        Step("live_preflight", ["python3", "scripts/memorial_flagship_preflight.py", args.slug, "--base-url", args.base_url, "--json"], str(output_dir), "required", True),
        Step("live_demo_rehearsal", ["python3", "scripts/memorial_demo_rehearsal.py", args.slug, "--base-url", args.base_url, "--questions", args.questions or "", "--save-audio-dir", str(output_dir), "--json"], str(output_dir), "required", True),
        Step("voice_roundtrip_validation", ["python3", "scripts/validate_memorial_voice_loop.py", "--slug", args.slug, "--base-url", args.base_url, "--output-dir", str(output_dir), "--json"], str(output_dir), "required", True, str(output_dir / "voice_loop_report.json")),
        Step("launch_snapshot", ["python3", "scripts/memorial_launch_snapshot.py", args.slug, "--base-url", args.base_url, "--questions", args.questions or "", "--output", str(output_dir / f"{args.slug}_launch_snapshot.json")], str(output_dir), "required", True, str(output_dir / f"{args.slug}_launch_snapshot.json")),
    ]
    if getattr(args, "skip_exit_gates", False) is not True:
        steps.append(Step("full_exit_gates", ["bash", "scripts/memorial_flagship_exit_gates.sh"], str(output_dir), "required"))
    if getattr(args, "optional_exit_gates", False) or getattr(args, "avatar_required", False) or getattr(args, "avatar_optional", False):
        steps.append(
            Step(
                "avatar_video_call_status",
                ["python3", "scripts/verify_memorial_video_call_avatar_ready.py", "--base-url", args.base_url, "--slug", args.slug, "--json"],
                str(output_dir),
                "required" if getattr(args, "avatar_required", False) else "warning",
                True,
            )
        )
    if getattr(args, "allow_missing_stt", False):
        steps[3].command = [item for item in steps[3].command if item != "--require-stt"]
    else:
        steps[3].command.insert(-1, "--require-stt")
    return steps


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_showtime(args: argparse.Namespace) -> dict[str, object]:
    if args.launch_mode and (args.skip_tts or args.skip_chat or args.skip_unit_contracts or args.skip_snapshot):
        raise SystemExit("--launch-mode forbids skip flags")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = ShowtimeReport(slug=args.slug, base_url=args.base_url, started_at_epoch=0, output_dir=str(output_dir))
    preflight_report = preflight.Report(slug=args.slug)
    preflight.check_filesystem(args.slug, preflight_report)
    report.results.append(ShowtimeResult("filesystem_preflight", ["python3", "scripts/memorial_flagship_preflight.py", args.slug], str(output_dir), "required", 0 if preflight_report.status in {"pass", "warn"} else 1, 1, json.dumps(preflight_report.as_dict()), preflight_report.status, _semantic_from_payload(preflight_report.as_dict())[1]))
    live_preflight = preflight.Report(slug=args.slug)
    preflight.check_live(args.slug, live_preflight, args.base_url)
    report.results.append(ShowtimeResult("live_preflight", ["python3", "scripts/memorial_flagship_preflight.py", args.slug, "--base-url", args.base_url, "--json"], str(output_dir), "required", 0 if live_preflight.status in {"pass", "warn"} else 1, 1, json.dumps(live_preflight.as_dict()), live_preflight.status, _semantic_from_payload(live_preflight.as_dict())[1]))
    rehearsal_report = rehearsal.run_rehearsal(slug=args.slug, base_url=args.base_url, questions_path=args.questions, save_audio_dir=str(output_dir))
    rehearsal_payload = rehearsal_report.as_dict()
    report.results.append(ShowtimeResult("live_demo_rehearsal", ["python3", "scripts/memorial_demo_rehearsal.py"], str(output_dir), "required", 0 if rehearsal_payload["status"] in {"pass", "warn"} else 1, 1, json.dumps(rehearsal_payload), rehearsal_payload["status"], _semantic_from_payload(rehearsal_payload)[1]))
    voice_report = voice_loop.validate_memorial_voice_loop(slug=args.slug, base_url=args.base_url, output_dir=output_dir, direct_text="Worum geht es?", conversation_question="Hallo Manfred, kannst du direkt mit mir reden?", require_stt=not args.allow_missing_stt)
    voice_payload = voice_report.as_dict()
    _write_json(output_dir / "voice_loop_report.json", voice_payload)
    report.results.append(ShowtimeResult("voice_roundtrip_validation", ["python3", "scripts/validate_memorial_voice_loop.py"], str(output_dir), "required", 0 if voice_payload["status"] == "pass" else 1, 1, json.dumps(voice_payload), voice_payload["status"], _semantic_from_payload(voice_payload)[1]))
    snapshot_payload = snapshot.build_snapshot(slug=args.slug, base_url=args.base_url, questions=args.questions)
    _write_json(output_dir / f"{args.slug}_launch_snapshot.json", snapshot_payload)
    report.results.append(ShowtimeResult("launch_snapshot", ["python3", "scripts/memorial_launch_snapshot.py"], str(output_dir), "required", 0 if snapshot_payload["status"] in {"pass", "warn"} else 1, 1, json.dumps(snapshot_payload), snapshot_payload["status"], _semantic_from_payload(snapshot_payload)[1]))
    if args.optional_exit_gates or args.avatar_required or args.avatar_optional:
        avatar_payload = avatar_ready.run_check(base_url=args.base_url, slug=args.slug).as_dict()
        report.results.append(ShowtimeResult("avatar_video_call_status", ["python3", "scripts/verify_memorial_video_call_avatar_ready.py"], str(output_dir), "required" if args.avatar_required else "warning", 0 if avatar_payload["status"] in {"pass", "warn"} else 1, 1, json.dumps(avatar_payload), avatar_payload["status"], _semantic_from_payload(avatar_payload)[1]))
    payload = report.as_dict()
    _write_json(output_dir / "showtime_report.json", payload)
    (output_dir / "showtime_report.md").write_text(f"# Memorial Showtime\n\nStatus: {payload['status']}\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--questions", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--skip-unit-contracts", action="store_true")
    parser.add_argument("--skip-snapshot", action="store_true")
    parser.add_argument("--skip-exit-gates", action="store_true")
    parser.add_argument("--optional-exit-gates", action="store_true")
    parser.add_argument("--avatar-required", action="store_true")
    parser.add_argument("--avatar-optional", action="store_true")
    parser.add_argument("--allow-missing-stt", action="store_true")
    parser.add_argument("--launch-mode", action="store_true")
    args = parser.parse_args()
    payload = run_showtime(args)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
