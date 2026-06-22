#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_URL = ROOT.resolve().as_posix()
ROOM_RECEIPT_REL = Path(".codex-studio/published/memorial_room_audio_public_origin.generated.json")
SYNC_ARTIFACTS = [
    ROOM_RECEIPT_REL,
    Path(".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"),
    Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"),
    Path(".codex-design/product/PROJECT_MODES.generated.json"),
    Path(".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"),
]


def _run(cmd: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(cmd, cwd=cwd, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SystemExit(f"command_failed:{' '.join(cmd)}:{detail[:500]}")


def build_room_receipt_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        "python3",
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
        "--manual-attestation-id",
        args.manual_attestation_id,
        "--manual-attestation-signed-at",
        args.manual_attestation_signed_at,
        "--manual-attestation-source",
        args.manual_attestation_source,
        "--require-public-origin",
        "--actual-device-checked",
        "--actual-speaker-checked",
        "--first-syllable-not-clipped",
        "--intelligibility-confirmed",
        "--answer-text-fallback-visible",
        "--no-internet-search-confirmed",
        "--normal-spoken-turn-confirmed",
        "--interruption-behavior-confirmed",
        "--retry-path-confirmed",
    ]
    return cmd


def _copy_artifacts_from_clean_clone(clean_root: Path, destination_root: Path) -> list[str]:
    copied: list[str] = []
    for relpath in SYNC_ARTIFACTS:
        source = clean_root / relpath
        if not source.exists():
            continue
        destination = destination_root / relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(relpath.as_posix())
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the manual memorial room/device receipt from a clean clone so unrelated worktree drift does not poison the receipt."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--device-label", default="")
    parser.add_argument("--speaker-label", default="")
    parser.add_argument("--room-label", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--manual-attestation-id", required=True)
    parser.add_argument("--manual-attestation-signed-at", required=True)
    parser.add_argument("--manual-attestation-source", default="operator_room_review")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="memorial-room-audio-gold-") as temp_dir:
        clone_root = Path(temp_dir) / "repo"
        _run(["git", "clone", "--quiet", "--no-hardlinks", REPO_URL, str(clone_root)], cwd=ROOT)
        _run(["git", "checkout", "--quiet", "HEAD"], cwd=clone_root)
        _run(build_room_receipt_command(args), cwd=clone_root)
        _run(["python3", "scripts/materialize_memorial_operator_status.py"], cwd=clone_root)
        _run(["python3", "scripts/materialize_whole_project_gold_map.py"], cwd=clone_root)
        _run(["python3", "scripts/materialize_project_mode_manifests.py"], cwd=clone_root)
        copied = _copy_artifacts_from_clean_clone(clone_root, ROOT)

    payload = {
        "status": "pass",
        "copied_artifacts": copied,
        "room_receipt": ROOM_RECEIPT_REL.as_posix(),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
