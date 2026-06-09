#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
EA_DIR = SCRIPT_DIR.parent
REPO_ROOT = EA_DIR.parent

GateLevel = Literal["required", "warning", "info"]


@dataclass
class StepResult:
    name: str
    command: list[str]
    cwd: str
    gate: GateLevel
    returncode: int
    duration_ms: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    semantic_status: str = ""
    semantic_detail: dict[str, Any] = field(default_factory=dict)

    @property
    def command_passed(self) -> bool:
        return self.returncode == 0

    @property
    def semantic_level(self) -> str:
        if self.semantic_status in {"pass", "warn", "fail"}:
            return self.semantic_status
        return "pass" if self.command_passed else "fail"

    @property
    def effective_status(self) -> str:
        if self.gate == "info":
            return "info"
        if not self.command_passed:
            return "fail" if self.gate == "required" else "warn"
        if self.semantic_level == "fail":
            return "fail" if self.gate == "required" else "warn"
        if self.semantic_level == "warn":
            return "warn"
        return "pass"


@dataclass
class RoomReport:
    slug: str
    base_url: str
    output_dir: str
    started_at_epoch: int
    results: list[StepResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def failed_required(self) -> bool:
        return any(item.effective_status == "fail" for item in self.results)

    @property
    def warned(self) -> bool:
        return any(item.effective_status == "warn" for item in self.results)

    @property
    def status(self) -> str:
        if self.failed_required:
            return "fail"
        if self.warned:
            return "warn"
        return "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "output_dir": self.output_dir,
            "started_at_epoch": self.started_at_epoch,
            "status": self.status,
            "notes": self.notes,
            "results": [
                {
                    "name": item.name,
                    "command": item.command,
                    "cwd": item.cwd,
                    "gate": item.gate,
                    "returncode": item.returncode,
                    "duration_ms": item.duration_ms,
                    "stdout_tail": item.stdout_tail,
                    "stderr_tail": item.stderr_tail,
                    "semantic_status": item.semantic_status,
                    "semantic_detail": item.semantic_detail,
                    "effective_status": item.effective_status,
                }
                for item in self.results
            ],
        }

    def markdown(self) -> str:
        lines = [
            "# Memorial Room Ready Report",
            "",
            f"Slug: `{self.slug}`",
            f"Base URL: `{self.base_url}`",
            f"Status: **{self.status.upper()}**",
            f"Output: `{self.output_dir}`",
            "",
            "## Results",
            "",
        ]
        for item in self.results:
            lines.append(f"- `{item.effective_status.upper()}` **{item.name}** ({item.returncode}) in {item.duration_ms} ms")
            lines.append(f"  - gate: `{item.gate}`")
            lines.append(f"  - command: `{' '.join(item.command)}`")
            if item.semantic_status:
                lines.append(f"  - semantic status: `{item.semantic_status}`")
            if item.semantic_detail:
                lines.append(f"  - semantic detail: `{json.dumps(item.semantic_detail, ensure_ascii=False, sort_keys=True)}`")
            if item.stderr_tail and item.effective_status in {"fail", "warn"}:
                lines.append("  - stderr:")
                lines.append("    ```text")
                lines.extend("    " + line for line in item.stderr_tail.splitlines()[-12:])
                lines.append("    ```")
        if self.notes:
            lines.extend(["", "## Notes", ""])
            lines.extend(f"- {note}" for note in self.notes)
        return "\n".join(lines)


def _extract_json_payload(*, stdout_text: str, output_path: Path | None = None) -> dict[str, Any]:
    if output_path and output_path.is_file():
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    try:
        payload = json.loads((stdout_text or "").strip() or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _semantic_from_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    status = str(payload.get("status") or "").lower()
    if status not in {"pass", "warn", "fail"}:
        return "", {}
    detail: dict[str, Any] = {}
    if isinstance(payload.get("checks"), list):
        detail["check_count"] = len(payload["checks"])
        warn_codes = [item.get("code") for item in payload["checks"] if isinstance(item, dict) and item.get("status") == "warn"]
        fail_codes = [item.get("code") for item in payload["checks"] if isinstance(item, dict) and item.get("status") == "fail"]
        if warn_codes:
            detail["warn_codes"] = warn_codes
        if fail_codes:
            detail["fail_codes"] = fail_codes
    if isinstance(payload.get("findings"), list):
        detail["finding_count"] = len(payload["findings"])
        warn_codes = [item.get("code") for item in payload["findings"] if isinstance(item, dict) and item.get("status") == "warn"]
        fail_codes = [item.get("code") for item in payload["findings"] if isinstance(item, dict) and item.get("status") == "fail"]
        if warn_codes:
            detail["warn_codes"] = warn_codes
        if fail_codes:
            detail["fail_codes"] = fail_codes
    if isinstance(payload.get("results"), list):
        detail["result_count"] = len(payload["results"])
        effective_warns = [item.get("name") for item in payload["results"] if isinstance(item, dict) and item.get("effective_status") == "warn"]
        effective_fails = [item.get("name") for item in payload["results"] if isinstance(item, dict) and item.get("effective_status") == "fail"]
        if effective_warns:
            detail["warn_steps"] = effective_warns
        if effective_fails:
            detail["fail_steps"] = effective_fails
    return status, detail


def run(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    gate: GateLevel,
    timeout: int,
    output_path: Path | None = None,
) -> StepResult:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        result = StepResult(
            name=name,
            command=command,
            cwd=str(cwd),
            gate=gate,
            returncode=int(proc.returncode),
            duration_ms=int((time.time() - started) * 1000),
            stdout_tail=(proc.stdout or "")[-12000:],
            stderr_tail=(proc.stderr or "")[-12000:],
        )
    except Exception as exc:
        return StepResult(
            name=name,
            command=command,
            cwd=str(cwd),
            gate=gate,
            returncode=-1,
            duration_ms=int((time.time() - started) * 1000),
            stderr_tail=f"{type(exc).__name__}: {exc}",
        )
    payload = _extract_json_payload(stdout_text=result.stdout_tail, output_path=output_path)
    result.semantic_status, result.semantic_detail = _semantic_from_payload(payload)
    return result


def latest_audio(output_dir: Path, slug: str, *, newer_than_epoch: float | None = None) -> Path | None:
    candidates = sorted(
        list(output_dir.glob(f"{slug}-demo-tts.*")) + list(output_dir.glob("*demo-tts.*")),
        key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
        reverse=True,
    )
    for candidate in candidates:
        if newer_than_epoch is None or candidate.stat().st_mtime >= newer_than_epoch:
            return candidate
    return None


def write_report(report: RoomReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "room_ready_report.json").write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "room_ready_report.md").write_text(report.markdown() + "\n", encoding="utf-8")


def default_output_dir(slug: str) -> Path:
    return Path(os.getenv("MEMORIAL_ROOM_READY_OUTPUT_DIR") or f"/tmp/memorial_room_ready_{slug}_{int(time.time())}")


def avatar_video_check_command(*, slug: str, base_url: str) -> list[str]:
    return [
        sys.executable,
        "scripts/verify_memorial_video_call_avatar_ready.py",
        "--slug",
        slug,
        "--base-url",
        base_url,
        "--json",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Final room-readiness runner for the memorial presentation.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--questions", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--skip-showtime", action="store_true")
    parser.add_argument("--skip-audio-probe", action="store_true")
    parser.add_argument("--skip-avatar-video-check", action="store_true")
    parser.add_argument("--skip-exit-gates", action="store_true")
    parser.add_argument("--optional-exit-gates", action="store_true")
    parser.add_argument("--launch-mode", action="store_true")
    parser.add_argument("--avatar-required", action="store_true")
    parser.add_argument("--avatar-optional", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    started_at_epoch = int(time.time())
    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(args.slug).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    report = RoomReport(
        slug=args.slug,
        base_url=args.base_url,
        output_dir=str(output_dir),
        started_at_epoch=started_at_epoch,
    )

    showtime_result: StepResult | None = None
    if not args.skip_showtime:
        showtime_output = output_dir / "showtime_report.json"
        showtime_command = [
            sys.executable,
            "scripts/memorial_showtime.py",
            "--slug",
            args.slug,
            "--base-url",
            args.base_url,
            "--output-dir",
            str(output_dir),
        ]
        if args.questions:
            showtime_command.extend(["--questions", args.questions])
        if args.skip_exit_gates:
            showtime_command.append("--skip-exit-gates")
        if args.optional_exit_gates:
            showtime_command.append("--optional-exit-gates")
        if args.launch_mode:
            showtime_command.append("--launch-mode")
        if args.avatar_required:
            showtime_command.append("--avatar-required")
        if args.avatar_optional:
            showtime_command.append("--avatar-optional")
        showtime_result = run(
            "showtime",
            showtime_command,
            cwd=EA_DIR,
            gate="required",
            timeout=900,
            output_path=showtime_output,
        )
        report.results.append(showtime_result)
        write_report(report, output_dir)
        if showtime_result.effective_status == "fail":
            report.notes.append("Showtime failed; room-ready does not trust stale audio artifacts after a failed run.")

    if not args.skip_audio_probe:
        if showtime_result and showtime_result.effective_status == "fail":
            report.results.append(
                StepResult(
                    name="audio_probe",
                    command=[sys.executable, "scripts/memorial_audio_probe.py"],
                    cwd=str(EA_DIR),
                    gate="required",
                    returncode=1,
                    duration_ms=0,
                    stderr_tail="Skipped because showtime failed; no fresh room-ready audio may be trusted.",
                    semantic_status="fail",
                    semantic_detail={"reason": "showtime_failed"},
                )
            )
        else:
            fresh_audio = latest_audio(output_dir, args.slug, newer_than_epoch=float(started_at_epoch))
            if fresh_audio is None:
                report.results.append(
                    StepResult(
                        name="audio_probe",
                        command=[sys.executable, "scripts/memorial_audio_probe.py"],
                        cwd=str(EA_DIR),
                        gate="required",
                        returncode=1,
                        duration_ms=0,
                        stderr_tail="No fresh demo TTS audio file found in output directory for this room-ready run.",
                        semantic_status="fail",
                        semantic_detail={"reason": "fresh_audio_missing"},
                    )
                )
            else:
                probe_json = output_dir / "audio_probe.json"
                probe_md = output_dir / "audio_probe.md"
                probe_result = run(
                    "audio_probe",
                    [
                        sys.executable,
                        "scripts/memorial_audio_probe.py",
                        str(fresh_audio),
                        "--json",
                        "--json-output",
                        str(probe_json),
                        "--markdown-output",
                        str(probe_md),
                    ],
                    cwd=EA_DIR,
                    gate="required",
                    timeout=120,
                    output_path=probe_json,
                )
                report.results.append(probe_result)
                report.notes.append(f"Audio probe target: {fresh_audio}")

    if args.optional_exit_gates and not args.skip_avatar_video_check:
        avatar_result = run(
            "avatar_video_call_status",
            avatar_video_check_command(slug=args.slug, base_url=args.base_url),
            cwd=EA_DIR,
            gate="warning",
            timeout=120,
        )
        report.results.append(avatar_result)

    write_report(report, output_dir)
    rendered = json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else str(output_dir / "room_ready_report.md")
    print(rendered)
    return 1 if report.failed_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
