#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
EA_DIR = SCRIPT_DIR.parent
REPO_ROOT = EA_DIR.parent
ROOT_EXIT_GATES = REPO_ROOT / "scripts" / "memorial_flagship_exit_gates.sh"

GateLevel = Literal["required", "warning", "info"]
OPTIONAL_AVATAR_WARNING_CODES = {
    "avatar_disabled_label_missing",
    "avatar_disabled_detail_unclear",
    "avatar_manifest_missing",
    "avatar_video_not_published",
}


def _is_optional_avatar_warning(detail: dict[str, Any]) -> bool:
    fail_codes = [str(item or "") for item in list(detail.get("fail_codes") or [])]
    fail_commands = [str(item or "") for item in list(detail.get("fail_commands") or [])]
    if fail_codes or fail_commands:
        return False
    warn_codes = {str(item or "") for item in list(detail.get("warn_codes") or []) if str(item or "")}
    warn_commands = [str(item or "") for item in list(detail.get("warn_commands") or [])]
    if warn_codes and warn_codes.issubset(OPTIONAL_AVATAR_WARNING_CODES):
        return True
    return bool(warn_commands) and all("verify_memorial_video_call_avatar_ready.py" in item for item in warn_commands)


@dataclass
class ShowtimeStep:
    name: str
    command: list[str]
    cwd: Path
    gate: GateLevel = "required"
    timeout: int = 240
    parse_json_status: bool = False
    output_path_arg: str | None = None


@dataclass
class ShowtimeResult:
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
        status = str(self.semantic_status or "").lower()
        if status in {"pass", "warn", "fail"}:
            return status
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
            if _is_optional_avatar_warning(self.semantic_detail):
                return "pass"
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
    def failed_required(self) -> bool:
        return any(result.effective_status == "fail" for result in self.results)

    @property
    def warned(self) -> bool:
        return any(result.effective_status == "warn" for result in self.results)

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
            "started_at_epoch": self.started_at_epoch,
            "status": self.status,
            "output_dir": self.output_dir,
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
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
            f"# Memorial Showtime Report: {self.slug}",
            "",
            f"Base URL: `{self.base_url or 'not provided'}`",
            f"Status: **{self.status.upper()}**",
            f"Output directory: `{self.output_dir}`",
            "",
            "## Steps",
            "",
        ]
        for item in self.results:
            lines.append(f"- `{item.effective_status.upper()}` **{item.name}** `{item.returncode}` in {item.duration_ms} ms")
            lines.append(f"  - gate: `{item.gate}`")
            lines.append(f"  - cwd: `{item.cwd}`")
            lines.append(f"  - command: `{' '.join(item.command)}`")
            if item.semantic_status:
                lines.append(f"  - semantic status: `{item.semantic_status}`")
            if item.semantic_detail:
                lines.append(f"  - semantic detail: `{json.dumps(item.semantic_detail, ensure_ascii=False, sort_keys=True)}`")
            if item.stderr_tail and item.effective_status in {"fail", "warn"}:
                lines.append("  - stderr tail:")
                lines.append("    ```text")
                lines.extend("    " + line for line in item.stderr_tail.splitlines()[-12:])
                lines.append("    ```")
            if item.stdout_tail and item.effective_status in {"fail", "warn"}:
                lines.append("  - stdout tail:")
                lines.append("    ```text")
                lines.extend("    " + line for line in item.stdout_tail.splitlines()[-12:])
                lines.append("    ```")
        lines.extend(
            [
                "",
                "## Decision",
                "",
                "PASS = present live.",
                "WARN = present only if the warning is understood and accepted.",
                "FAIL = do not present live.",
                "",
            ]
        )
        return "\n".join(lines)


def _extract_json_payload(result: ShowtimeResult, *, output_path_arg: str | None = None) -> dict[str, Any]:
    if output_path_arg:
        try:
            path = Path(output_path_arg)
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    try:
        payload = json.loads(result.stdout_tail.strip() or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _semantic_from_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    status = str(payload.get("status") or "").lower()
    if status not in {"pass", "warn", "fail"}:
        return "", {}
    detail: dict[str, Any] = {}
    if "findings" in payload and isinstance(payload["findings"], list):
        detail["finding_count"] = len(payload["findings"])
        detail["warn_codes"] = [item.get("code") for item in payload["findings"] if isinstance(item, dict) and item.get("status") == "warn"]
        detail["fail_codes"] = [item.get("code") for item in payload["findings"] if isinstance(item, dict) and item.get("status") == "fail"]
        if not detail["warn_codes"]:
            detail.pop("warn_codes")
        if not detail["fail_codes"]:
            detail.pop("fail_codes")
    if "checks" in payload and isinstance(payload["checks"], list):
        detail["check_count"] = len(payload["checks"])
        detail["warn_codes"] = [item.get("code") for item in payload["checks"] if isinstance(item, dict) and item.get("status") == "warn"]
        detail["fail_codes"] = [item.get("code") for item in payload["checks"] if isinstance(item, dict) and item.get("status") == "fail"]
        if not detail["warn_codes"]:
            detail.pop("warn_codes")
        if not detail["fail_codes"]:
            detail.pop("fail_codes")
    if "commands" in payload and isinstance(payload["commands"], list):
        detail["command_count"] = len(payload["commands"])
        warn_commands = [
            " ".join(str(part) for part in list(item.get("command") or [])[:2])
            for item in payload["commands"]
            if isinstance(item, dict) and str(item.get("semantic_status") or "").lower() == "warn"
        ]
        fail_commands = [
            " ".join(str(part) for part in list(item.get("command") or [])[:2])
            for item in payload["commands"]
            if isinstance(item, dict)
            and (str(item.get("semantic_status") or "").lower() == "fail" or int(item.get("returncode") or 0) != 0)
        ]
        if warn_commands:
            detail["warn_commands"] = warn_commands
        if fail_commands:
            detail["fail_commands"] = fail_commands
    return status, detail


def run_step(step: ShowtimeStep) -> ShowtimeResult:
    started = time.time()
    try:
        proc = subprocess.run(
            step.command,
            cwd=str(step.cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=step.timeout,
            check=False,
        )
        result = ShowtimeResult(
            name=step.name,
            command=step.command,
            cwd=str(step.cwd),
            gate=step.gate,
            returncode=int(proc.returncode),
            duration_ms=int((time.time() - started) * 1000),
            stdout_tail=(proc.stdout or "")[-12000:],
            stderr_tail=(proc.stderr or "")[-12000:],
        )
    except Exception as exc:
        return ShowtimeResult(
            name=step.name,
            command=step.command,
            cwd=str(step.cwd),
            gate=step.gate,
            returncode=-1,
            duration_ms=int((time.time() - started) * 1000),
            stderr_tail=f"{type(exc).__name__}: {exc}",
        )
    if step.parse_json_status:
        payload = _extract_json_payload(result, output_path_arg=step.output_path_arg)
        semantic_status, semantic_detail = _semantic_from_payload(payload)
        result.semantic_status = semantic_status
        result.semantic_detail = semantic_detail
    return result


def default_output_dir(slug: str) -> Path:
    return Path(os.getenv("MEMORIAL_SHOWTIME_OUTPUT_DIR") or f"/tmp/memorial_showtime_{slug}_{int(time.time())}")


def build_steps(args: argparse.Namespace, output_dir: Path) -> list[ShowtimeStep]:
    py = sys.executable
    questions = Path(args.questions).resolve() if args.questions else (REPO_ROOT / "examples" / "demo_questions.manfred.json")
    base_url = str(args.base_url or "").strip()

    steps: list[ShowtimeStep] = [
        ShowtimeStep("git_head", ["git", "rev-parse", "HEAD"], REPO_ROOT, gate="required", timeout=30),
        ShowtimeStep("git_status", ["git", "status", "--short"], REPO_ROOT, gate="info", timeout=30),
        ShowtimeStep(
            "filesystem_preflight",
            [py, "scripts/memorial_flagship_preflight.py", args.slug, "--json"],
            EA_DIR,
            gate="required",
            timeout=180,
            parse_json_status=True,
        ),
    ]

    if not args.skip_unit_contracts:
        steps.append(
            ShowtimeStep(
                "unit_contracts",
                [
                    py,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_memorial_archive_registry_public.py",
                    "tests/test_memorial_demo_rehearsal_contracts.py",
                    "tests/test_memorial_flagship_preflight.py",
                    "tests/test_memorial_security_contracts.py",
                    "tests/test_providers_api_contracts.py",
                    "tests/test_memorial_showtime_contracts.py",
                    "-k",
                    "memorial",
                ],
                REPO_ROOT,
                gate="required",
                timeout=300,
            )
        )

    if base_url:
        steps.append(
            ShowtimeStep(
                "live_preflight",
                [py, "scripts/memorial_flagship_preflight.py", args.slug, "--base-url", base_url, "--json"],
                EA_DIR,
                gate="required",
                timeout=240,
                parse_json_status=True,
            )
        )

        if args.avatar_required or args.avatar_optional:
            steps.append(
                ShowtimeStep(
                    "avatar_video_call_status",
                    [
                        py,
                        "scripts/verify_memorial_video_call_avatar_ready.py",
                        "--slug",
                        args.slug,
                        "--base-url",
                        base_url,
                        "--json",
                    ],
                    EA_DIR,
                    gate="required" if args.avatar_required else "warning",
                    timeout=120,
                    parse_json_status=True,
                )
            )

        rehearsal = [
            py,
            "scripts/memorial_demo_rehearsal.py",
            args.slug,
            "--base-url",
            base_url,
            "--questions",
            str(questions),
            "--save-audio-dir",
            str(output_dir),
            "--json",
        ]
        if args.skip_tts:
            rehearsal.append("--skip-tts")
        if args.skip_chat:
            rehearsal.append("--skip-chat")
        steps.append(
            ShowtimeStep(
                "live_demo_rehearsal",
                rehearsal,
                EA_DIR,
                gate="required",
                timeout=360,
                parse_json_status=True,
            )
        )

        voice_loop_output = output_dir / "voice_loop_report.json"
        voice_loop_command = [
            py,
            "scripts/validate_memorial_voice_loop.py",
            "--slug",
            args.slug,
            "--base-url",
            base_url,
            "--output-dir",
            str(output_dir / "voice_loop"),
            "--json",
            "--output",
            str(voice_loop_output),
        ]
        if not bool(getattr(args, "allow_missing_stt", False)):
            voice_loop_command.append("--require-stt")
        steps.append(
            ShowtimeStep(
                "voice_roundtrip_validation",
                voice_loop_command,
                EA_DIR,
                gate="required",
                timeout=360,
                parse_json_status=True,
                output_path_arg=str(voice_loop_output),
            )
        )

        if not args.skip_snapshot:
            snapshot_output = output_dir / f"{args.slug}_launch_snapshot.json"
            snapshot = [
                py,
                "scripts/memorial_launch_snapshot.py",
                args.slug,
                "--base-url",
                base_url,
                "--questions",
                str(questions),
                "--output",
                str(snapshot_output),
            ]
            steps.append(
                ShowtimeStep(
                    "launch_snapshot",
                    snapshot,
                    EA_DIR,
                    gate="required",
                    timeout=360,
                    parse_json_status=True,
                    output_path_arg=str(snapshot_output),
                )
            )
    else:
        steps.append(
            ShowtimeStep(
                "live_checks_skipped",
                [py, "-c", "print('No --base-url supplied; live rehearsal skipped')"],
                EA_DIR,
                gate="info",
                timeout=15,
            )
        )

    if not args.skip_exit_gates:
        if ROOT_EXIT_GATES.is_file():
            env_command = ["bash", "-lc", f"MEMORIAL_FLAGSHIP_BASE_URL={base_url!r} {str(ROOT_EXIT_GATES)}"]
            gate: GateLevel = "warning" if args.optional_exit_gates else "required"
            steps.append(ShowtimeStep("full_exit_gates", env_command, REPO_ROOT, gate=gate, timeout=600))
        else:
            steps.append(
                ShowtimeStep(
                    "exit_gates_missing",
                    [py, "-c", f"print('Exit gate script missing: {ROOT_EXIT_GATES}')"],
                    REPO_ROOT,
                    gate="warning",
                    timeout=15,
                )
            )

    return steps


def write_report(report: ShowtimeReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "showtime_report.json").write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "showtime_report.md").write_text(report.markdown() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-command showtime runner for the Manfred memorial presentation.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", default=os.getenv("MEMORIAL_FLAGSHIP_BASE_URL", ""))
    parser.add_argument("--questions", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--skip-unit-contracts", action="store_true")
    parser.add_argument("--skip-snapshot", action="store_true")
    parser.add_argument("--skip-exit-gates", action="store_true")
    parser.add_argument("--optional-exit-gates", action="store_true", help="Treat root exit-gate runner failure as warning rather than hard fail.")
    parser.add_argument("--allow-missing-stt", action="store_true", help="Allow offline rehearsals to skip STT transcript proof.")
    parser.add_argument("--launch-mode", action="store_true")
    parser.add_argument("--avatar-required", action="store_true")
    parser.add_argument("--avatar-optional", action="store_true")
    parser.add_argument("--stop-on-fail", action="store_true")
    args = parser.parse_args(argv)

    if args.avatar_required and args.avatar_optional:
        parser.error("--avatar-required and --avatar-optional are mutually exclusive")
    if args.launch_mode:
        if not str(args.base_url or "").strip():
            parser.error("--launch-mode requires --base-url")
        if args.skip_tts or args.skip_chat or args.skip_unit_contracts or args.skip_snapshot:
            parser.error("--launch-mode forbids skip flags")
        if args.optional_exit_gates:
            parser.error("--launch-mode forbids --optional-exit-gates")
        if args.allow_missing_stt:
            parser.error("--launch-mode forbids --allow-missing-stt")
        if not args.avatar_required and not args.avatar_optional:
            parser.error("--launch-mode requires explicit avatar gate mode via --avatar-required or --avatar-optional")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(args.slug).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    report = ShowtimeReport(
        slug=args.slug,
        base_url=str(args.base_url or "").strip(),
        started_at_epoch=int(time.time()),
        output_dir=str(output_dir),
    )

    for step in build_steps(args, output_dir):
        result = run_step(step)
        report.results.append(result)
        write_report(report, output_dir)
        print(f"{result.effective_status.upper()} {step.name} -> {result.returncode}")
        if args.stop_on_fail and result.effective_status == "fail":
            break

    write_report(report, output_dir)
    print(output_dir / "showtime_report.md")
    return 1 if report.failed_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
