#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_URL = ROOT.resolve().as_posix()
SYNC_ARTIFACTS = [
    Path(".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"),
    Path(".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"),
    Path(".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"),
    Path(".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json"),
    Path(".codex-studio/published/memorial_room_audio_public_origin.generated.json"),
    Path(".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"),
    Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"),
    Path(".codex-design/product/PROJECT_MODES.generated.json"),
    Path(".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"),
]


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SystemExit(f"command_failed:{' '.join(cmd)}:{detail[:800]}")


def build_local_voice_receipt_command(args: argparse.Namespace) -> list[str]:
    return [
        args.python_bin,
        "scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "--base-url",
        args.base_url,
        "--slug",
        args.slug,
        "--output",
        ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
    ]


def build_voice_receipt_command(args: argparse.Namespace) -> list[str]:
    return [
        args.python_bin,
        "scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "--base-url",
        args.base_url,
        "--slug",
        args.slug,
        "--gold-mode",
        "--require-public-origin",
        "--direct-min-f1",
        str(args.direct_min_f1),
        "--conversation-min-f1",
        str(args.conversation_min_f1),
        "--critical-token",
        "worum",
        "--critical-token",
        "geht",
        "--critical-token",
        "es",
        "--output",
        ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
    ]


def build_browser_receipt_command(args: argparse.Namespace) -> list[str]:
    return [
        args.python_bin,
        "scripts/measure_memorial_live_browser.py",
        "--base-url",
        args.base_url,
        "--slug",
        args.slug,
        "--real-stt",
        "--exit-gate",
        "--gold-mode",
        "--require-public-origin",
        "--max-first-answer-ms",
        str(args.browser_first_answer_ms),
        "--output",
        ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ]


def build_meaningful_browser_receipt_command(args: argparse.Namespace) -> list[str]:
    return [
        args.python_bin,
        "scripts/measure_memorial_live_browser.py",
        "--base-url",
        args.base_url,
        "--slug",
        args.slug,
        "--prompt-text",
        args.meaningful_prompt,
        "--text-prompt",
        "--exit-gate",
        "--gold-mode",
        "--require-public-origin",
        "--max-first-answer-ms",
        str(args.meaningful_browser_first_answer_ms),
        "--output",
        ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
    ]


def build_room_receipt_command(args: argparse.Namespace) -> list[str]:
    return [
        args.python_bin,
        "scripts/materialize_memorial_room_audio_receipt.py",
        "--base-url",
        args.base_url,
        "--slug",
        args.slug,
        "--reviewer",
        args.reviewer,
        "--device-label",
        args.device_label,
        "--speaker-label",
        args.speaker_label,
        "--room-label",
        args.room_label,
        "--notes",
        args.notes,
        "--require-public-origin",
        "--actual-device-checked",
        "--actual-speaker-checked",
        "--first-syllable-not-clipped",
        "--intelligibility-confirmed",
        "--answer-text-fallback-visible",
        "--no-internet-search-confirmed",
    ]


def _copy_artifacts_from_clean_clone(clean_root: Path, destination_root: Path, relpaths: list[Path] | tuple[Path, ...] | None = None) -> list[str]:
    copied: list[str] = []
    for relpath in relpaths or SYNC_ARTIFACTS:
        source = clean_root / relpath
        if not source.exists():
            continue
        destination = destination_root / relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(relpath.as_posix())
    return copied


def _run_clean_clone_command(cmd: list[str], clone_env: dict[str, str], outputs: tuple[Path, ...]) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="memorial-public-gold-") as temp_dir:
        clone_root = Path(temp_dir) / "repo"
        _run(["git", "clone", "--quiet", "--no-hardlinks", REPO_URL, str(clone_root)], cwd=ROOT, env=clone_env)
        _run(["git", "checkout", "--quiet", "HEAD"], cwd=clone_root, env=clone_env)
        _run(cmd, cwd=clone_root, env=clone_env)
        return _copy_artifacts_from_clean_clone(clone_root, ROOT, outputs)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the full memorial public-origin gold receipt set from clean clones."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--device-label", default="")
    parser.add_argument("--speaker-label", default="")
    parser.add_argument("--room-label", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--direct-min-f1", type=float, default=0.92)
    parser.add_argument("--conversation-min-f1", type=float, default=0.90)
    parser.add_argument("--browser-first-answer-ms", type=float, default=4500.0)
    parser.add_argument("--meaningful-browser-first-answer-ms", type=float, default=8000.0)
    parser.add_argument("--meaningful-prompt", default="Was war dir bei Gerechtigkeit wichtig?")
    parser.add_argument("--python-bin", default="python3")
    args = parser.parse_args()
    args.python_bin = str((ROOT / args.python_bin)) if not os.path.isabs(args.python_bin) else args.python_bin

    clone_env = os.environ.copy()
    copied: list[str] = []
    for cmd, outputs in (
        (build_local_voice_receipt_command(args), (SYNC_ARTIFACTS[0],)),
        (build_voice_receipt_command(args), (SYNC_ARTIFACTS[1],)),
        (build_browser_receipt_command(args), (SYNC_ARTIFACTS[2],)),
        (build_meaningful_browser_receipt_command(args), (SYNC_ARTIFACTS[3],)),
        (build_room_receipt_command(args), (SYNC_ARTIFACTS[4],)),
    ):
        copied.extend(_run_clean_clone_command(cmd, clone_env, outputs))
    _run([args.python_bin, "scripts/materialize_whole_project_gold_map.py"], cwd=ROOT, env=clone_env)
    _run([args.python_bin, "scripts/materialize_project_mode_manifests.py"], cwd=ROOT, env=clone_env)
    _run([args.python_bin, "scripts/materialize_memorial_operator_status.py"], cwd=ROOT, env=clone_env)
    for relpath in SYNC_ARTIFACTS[5:]:
        if (ROOT / relpath).exists() and relpath.as_posix() not in copied:
            copied.append(relpath.as_posix())

    payload = {
        "status": "pass",
        "copied_artifacts": copied,
        "public_voice_receipt": ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        "public_browser_receipt": ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
        "public_meaningful_browser_receipt": ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
        "room_receipt": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
