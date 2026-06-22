#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_MANIFEST = ROOT / ".codex-studio/published/release_manifest.generated.json"

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


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def _normalize_mode(raw: str) -> str:
    return str(raw or "").strip().upper().replace("-", "_")


def _owned_modes_for_artifact(path: str) -> set[str]:
    owned: set[str] = set()
    normalized = str(path or "").strip()
    for mode, prefixes in _MODE_PREFIXES.items():
        if any(normalized.startswith(prefix) for prefix in prefixes):
            owned.add(mode)
    return owned


def validate_artifact_plane(
    *,
    release_manifest: dict[str, Any],
    enabled_modes: list[str],
) -> list[str]:
    issues: list[str] = []
    enabled = {_normalize_mode(mode) for mode in enabled_modes if _normalize_mode(mode)}
    enabled.add("EA_CORE")
    artifacts = [str(item) for item in list(release_manifest.get("artifact_set") or []) if str(item).strip()]
    if not artifacts:
        issues.append("artifact_set_empty")
        return issues
    for artifact in artifacts:
        if any(artifact.startswith(prefix) for prefix in _CORE_ALWAYS_ALLOWED_PREFIXES):
            continue
        owned_modes = _owned_modes_for_artifact(artifact)
        if not owned_modes:
            continue
        if not owned_modes <= enabled:
            issues.append(f"artifact_outside_enabled_modes:{artifact}:{','.join(sorted(owned_modes))}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--enabled-mode", action="append", default=[])
    args = parser.parse_args()

    release_manifest = _load_json(args.release_manifest)
    enabled_modes = list(args.enabled_mode or [])
    if not enabled_modes:
        enabled_modes = [str(release_manifest.get("project_mode") or "EA_CORE")]
    issues = validate_artifact_plane(release_manifest=release_manifest, enabled_modes=enabled_modes)
    if issues:
        raise SystemExit("release_manifest_artifact_plane_invalid:" + ",".join(issues))
    print(json.dumps({"status": "pass", "enabled_modes": [_normalize_mode(item) for item in enabled_modes]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
