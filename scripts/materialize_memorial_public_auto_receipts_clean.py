#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_URL = ROOT.resolve().as_posix()
SYNC_ARTIFACTS = [
    Path(".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"),
    Path(".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"),
    Path(".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"),
    Path(".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json"),
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


def _http_status(url: str) -> tuple[int, str]:
    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=20.0) as response:
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(240).decode("utf-8", errors="replace")
            return status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(240).decode("utf-8", errors="replace")
        return int(exc.code or 0), body
    except Exception as exc:
        return 0, f"{type(exc).__name__}:{exc}"


def _preflight_failure(prefix: str, *, status: int, url: str, detail: str) -> str:
    normalized_detail = str(detail or "").strip()
    if status in {401, 403}:
        return (
            f"{prefix}:{status}:{url}:{normalized_detail[:160]}:"
            "public memorial origin is access-blocked; verify the memorial page and .json manifest are anonymously reachable "
            "or run the refresh through the same public edge/auth path the release uses"
        )
    if status == 404:
        return (
            f"{prefix}:{status}:{url}:{normalized_detail[:160]}:"
            "public memorial page or manifest was not found; verify the slug and republish the public memorial bundle before refreshing gold receipts"
        )
    return f"{prefix}:{status}:{url}:{normalized_detail[:160]}"


def _preflight_public_origin(*, base_url: str, slug: str) -> None:
    normalized_base = str(base_url or "").strip().rstrip("/")
    if not normalized_base:
        raise SystemExit("public_origin_missing")
    lowered = normalized_base.lower()
    if any(marker in lowered for marker in ("://127.0.0.1", "://localhost", "://0.0.0.0", "://[::1]")):
        raise SystemExit(f"public_origin_must_not_be_localhost:{normalized_base}")
    page_status, page_detail = _http_status(f"{normalized_base}/memorials/{slug}")
    if page_status != 200:
        raise SystemExit(
            _preflight_failure(
                "public_origin_page_unavailable",
                status=page_status,
                url=f"{normalized_base}/memorials/{slug}",
                detail=page_detail,
            )
        )
    json_status, json_detail = _http_status(f"{normalized_base}/memorials/{slug}.json")
    if json_status != 200:
        raise SystemExit(
            _preflight_failure(
                "public_origin_manifest_unavailable",
                status=json_status,
                url=f"{normalized_base}/memorials/{slug}.json",
                detail=json_detail,
            )
        )


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


def _run_clean_clone_command(cmd: list[str], clone_env: dict[str, str], outputs: tuple[Path, ...]) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="memorial-public-auto-") as temp_dir:
        clone_root = Path(temp_dir) / "repo"
        _run(["git", "clone", "--quiet", "--no-hardlinks", REPO_URL, str(clone_root)], cwd=ROOT, env=clone_env)
        _run(["git", "checkout", "--quiet", "HEAD"], cwd=clone_root, env=clone_env)
        _run(cmd, cwd=clone_root, env=clone_env)
        copied: list[str] = []
        for relpath in outputs:
            source = clone_root / relpath
            if not source.exists():
                continue
            destination = ROOT / relpath
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(relpath.as_posix())
        return copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the non-manual memorial public-origin receipts from clean clones without touching room-audio attestation proof."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--direct-min-f1", type=float, default=0.92)
    parser.add_argument("--conversation-min-f1", type=float, default=0.90)
    parser.add_argument("--browser-first-answer-ms", type=float, default=4500.0)
    parser.add_argument("--meaningful-browser-first-answer-ms", type=float, default=8000.0)
    parser.add_argument("--meaningful-prompt", default="Was war dir bei Gerechtigkeit wichtig?")
    args = parser.parse_args()
    args.python_bin = str((ROOT / args.python_bin)) if not os.path.isabs(args.python_bin) else args.python_bin

    _preflight_public_origin(base_url=args.base_url, slug=args.slug)

    clone_env = os.environ.copy()
    copied: list[str] = []
    for cmd, outputs in (
        (build_local_voice_receipt_command(args), (SYNC_ARTIFACTS[0],)),
        (build_voice_receipt_command(args), (SYNC_ARTIFACTS[1],)),
        (build_browser_receipt_command(args), (SYNC_ARTIFACTS[2],)),
        (build_meaningful_browser_receipt_command(args), (SYNC_ARTIFACTS[3],)),
    ):
        copied.extend(_run_clean_clone_command(cmd, clone_env, outputs))

    _run([args.python_bin, "scripts/materialize_whole_project_gold_map.py"], cwd=ROOT, env=clone_env)
    _run([args.python_bin, "scripts/materialize_project_mode_manifests.py"], cwd=ROOT, env=clone_env)
    _run([args.python_bin, "scripts/materialize_memorial_operator_status.py"], cwd=ROOT, env=clone_env)
    for relpath in SYNC_ARTIFACTS[4:]:
        if (ROOT / relpath).exists() and relpath.as_posix() not in copied:
            copied.append(relpath.as_posix())

    payload = {
        "status": "pass",
        "copied_artifacts": copied,
        "manual_room_audio_receipt_touched": False,
        "public_voice_receipt": ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        "public_browser_receipt": ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
        "public_meaningful_browser_receipt": ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
