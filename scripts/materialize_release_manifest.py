from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess  # nosec B404
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "release_manifest.generated.json"

# Mirrors the runtime artifact plane ownership map used by verifier scripts.
_CORE_ALWAYS_ALLOWED_PREFIXES = (
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF",
    ".codex-studio/published/HERTA_WHATSAPP_PACING_LIVE_PROOF",
    ".codex-studio/published/NEXT90_",
    ".codex-studio/published/QUEUE.generated",
    ".codex-studio/published/ea_audiobook_",
    ".codex-studio/published/ea_continuous_improvement_goal_posture",
    ".codex-studio/published/ea_executive_assistant_",
    ".codex-studio/published/ea_office_loop_goal",
    ".codex-studio/published/release_manifest.generated",
    ".codex-studio/published/teable_env_recovery_readiness",
    ".codex-studio/published/telegram_audiobook_",
    ".codex-studio/published/telegram_video_delivery_",
    ".codex-studio/published/whatsapp_audiobook_",
    ".codex-studio/published/whatsapp_web_action_processor_readiness",
)

_MODE_PREFIXES = {
    "MEMORIAL": (
        ".codex-studio/published/manfred_",
        ".codex-studio/published/memorial_",
    ),
    "PROVIDER_LAB": (
        ".codex-studio/published/NEWSROOM_EDITORIAL_PACKET",
        ".codex-studio/published/active_media_ltd_goal_bundle",
        ".codex-studio/published/cinematic_narration_continuity_demo",
        ".codex-studio/published/ea_promo_",
    ),
    "CHUMMER_RELEASE_CONTROL": (
        ".codex-studio/published/CHUMMER5A_",
        ".codex-studio/published/ea_whole_project_",
    ),
    "PROPERTY": (
        ".codex-studio/published/property",
        ".codex-studio/published/tour",
    ),
}


def _normalize_mode_for_scope(raw: str) -> str:
    return str(raw or "").strip().upper().replace("-", "_")


def _owned_modes_for_artifact(path: str) -> set[str]:
    owned: set[str] = set()
    normalized = str(path or "").strip()
    for mode, prefixes in _MODE_PREFIXES.items():
        if any(normalized.startswith(prefix) for prefix in prefixes):
            owned.add(mode)
    return owned


def _artifact_in_scope(*, artifact_path: str, enabled_modes: list[str]) -> bool:
    if any(artifact_path.startswith(prefix) for prefix in _CORE_ALWAYS_ALLOWED_PREFIXES):
        return True
    owned_modes = _owned_modes_for_artifact(artifact_path)
    if not owned_modes:
        return True
    enabled_mode_set = {
        _normalize_mode_for_scope(mode)
        for mode in enabled_modes
        if _normalize_mode_for_scope(mode)
    }
    return owned_modes <= enabled_mode_set

def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(*args: str) -> str:
    completed = subprocess.run(  # nosec B603,B607
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _artifacts() -> list[str]:
    enabled_modes = _enabled_project_modes()
    enabled_mode_set = {
        _normalize_mode_for_scope(mode)
        for mode in enabled_modes
        if _normalize_mode_for_scope(mode)
    }
    published_root = ROOT / ".codex-studio" / "published"
    if not published_root.is_dir():
        return []
    artifacts = []
    for path in sorted(
        path.relative_to(ROOT).as_posix()
        for path in published_root.rglob("*")
        if path.is_file()
    ):
        if _artifact_in_scope(artifact_path=path, enabled_modes=list(enabled_mode_set)):
            artifacts.append(path)
    return artifacts


def _split_csv_env(name: str) -> list[str]:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return []
    values: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        value = str(part).strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _public_origin() -> tuple[str, str]:
    for env_name in (
        "EA_PUBLIC_APP_BASE_URL",
        "PROPERTYQUARRY_PUBLIC_BASE_URL",
        "EA_PUBLIC_ORIGIN",
        "PUBLIC_ORIGIN",
    ):
        value = str(os.environ.get(env_name) or "").strip().rstrip("/")
        if value:
            return value, env_name
    return "", "missing"


def _deployment_id(commit_sha: str, generated_at: str) -> tuple[str, str]:
    explicit = str(
        os.environ.get("EA_DEPLOYMENT_ID")
        or os.environ.get("DEPLOYMENT_ID")
        or os.environ.get("RENDER_GIT_COMMIT")
        or ""
    ).strip()
    if explicit:
        return explicit, "explicit"
    stamp = generated_at.replace(":", "").replace("-", "").replace(".", "").replace("T", "T")
    commit_fragment = (commit_sha[:12] if commit_sha else "unknowncommit") or "unknowncommit"
    return f"local-{stamp}-{commit_fragment}", "local_fallback"


def _normalize_mode(raw: str, *, default: str = "EA_CORE") -> str:
    normalized = str(raw or "").strip().upper().replace("-", "_")
    return normalized or default


def _enabled_project_modes() -> list[str]:
    configured = str(os.environ.get("EA_DEPLOY_ENABLED_MODES") or os.environ.get("EA_DEPLOY_ENABLED_PROJECT_MODES") or "").strip()
    if configured:
        seen: set[str] = set()
        modes: list[str] = []
        for part in configured.split(","):
            mode = _normalize_mode(part, default="")
            if mode and mode not in seen:
                seen.add(mode)
                modes.append(mode)
        if modes:
            return modes
    return [_normalize_mode(os.environ.get("EA_DEPLOY_PRIMARY_MODE") or os.environ.get("EA_DEPLOY_PROJECT_MODE") or "EA_CORE")]


def _tracking_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")


def _dirty_worktree() -> bool:
    return bool(_git("status", "--short"))


def build_manifest(*, output_path: Path = DEFAULT_OUTPUT, generated_at: str | None = None) -> dict[str, object]:
    generated = generated_at or _now_iso()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    commit_sha = _git("rev-parse", "HEAD")
    tracking_branch = _tracking_branch()
    dirty_worktree = _dirty_worktree()
    project_mode = _normalize_mode(os.environ.get("EA_DEPLOY_PRIMARY_MODE") or os.environ.get("EA_DEPLOY_PROJECT_MODE") or "EA_CORE")
    enabled_project_modes = _enabled_project_modes()
    compose_files = _split_csv_env("EA_DEPLOY_COMPOSE_FILES")
    compose_overrides = _split_csv_env("EA_DEPLOY_COMPOSE_OVERRIDES")
    release_label = str(
        os.environ.get("EA_RELEASE_LABEL")
        or os.environ.get("RELEASE_LABEL")
        or (commit_sha[:12] if commit_sha else "")
    ).strip()
    deployment_id, deployment_id_source = _deployment_id(commit_sha, generated)
    public_origin, public_origin_source = _public_origin()
    git_remote_origin = _git("remote", "get-url", "origin")
    manifest: dict[str, Any] = {
        "contract_name": "ea.release_manifest.v1",
        "generated_at": generated,
        "generated_by": "scripts/materialize_release_manifest.py",
        "repository": ROOT.name,
        "branch": branch,
        "tracking_branch": tracking_branch,
        "commit_sha": commit_sha,
        "dirty_worktree": dirty_worktree,
        "deployment_id": deployment_id,
        "deployment_id_source": deployment_id_source,
        "public_origin": public_origin,
        "public_origin_source": public_origin_source,
        "git_remote_origin": git_remote_origin,
        "project_mode": project_mode,
        "enabled_project_modes": enabled_project_modes,
        "compose_files": compose_files,
        "compose_overrides": compose_overrides,
        "artifact_set": _artifacts(),
        "release_label": release_label,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "--out", dest="output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    manifest = build_manifest(output_path=args.output)
    if args.pretty:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
