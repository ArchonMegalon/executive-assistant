#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_MANIFEST = (
    ROOT / ".codex-studio/published/release_manifest.generated.json"
)
DEFAULT_PROJECT_MODES = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
MANFRED_COMPOSITE_CANDIDATE_COMPOSE = (
    "deploy/manfred-memorial/docker-compose.candidate.yml"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def _normalize_mode(raw: str) -> str:
    return str(raw or "").strip().upper().replace("-", "_")


def _basename(path: str) -> str:
    return Path(str(path or "").strip()).name


def validate_release_contract(
    *,
    release_manifest: dict[str, Any],
    project_modes: dict[str, Any],
    requested_mode: str,
    enabled_modes: list[str],
    compose_overrides: list[str],
    manfred_composite_candidate_observed: bool = False,
) -> list[str]:
    issues: list[str] = []
    requested = _normalize_mode(requested_mode)
    enabled = [_normalize_mode(mode) for mode in enabled_modes if _normalize_mode(mode)]
    enabled_set = set(enabled)
    mode_keys = {
        _normalize_mode(str(item.get("key") or ""))
        for item in list(project_modes.get("modes") or [])
        if isinstance(item, dict)
    }
    if release_manifest.get("contract_name") != "ea.release_manifest.v1":
        issues.append("release_manifest_contract_invalid")
    if requested not in mode_keys:
        issues.append(f"unknown_requested_mode:{requested}")
    manifest_mode = _normalize_mode(str(release_manifest.get("project_mode") or ""))
    if manifest_mode != requested:
        issues.append(
            f"manifest_mode_mismatch:{manifest_mode or 'missing'}!={requested}"
        )
    manifest_enabled = [
        _normalize_mode(str(item))
        for item in list(release_manifest.get("enabled_project_modes") or [])
        if _normalize_mode(str(item))
    ]
    if set(manifest_enabled) != enabled_set:
        issues.append("manifest_enabled_modes_mismatch")
    if requested not in enabled_set:
        issues.append("requested_mode_not_enabled")

    override_basenames = {
        _basename(item) for item in compose_overrides if str(item).strip()
    }
    manifest_compose_files = {
        str(item).strip().replace("\\", "/")
        for item in list(release_manifest.get("compose_files") or [])
        if str(item).strip()
    }
    manifest_compose_overrides = {
        str(item).strip().replace("\\", "/")
        for item in list(release_manifest.get("compose_overrides") or [])
        if str(item).strip()
    }
    manfred_composite_candidate = (
        manfred_composite_candidate_observed is True
        and requested == "MEMORIAL"
        and enabled_set == {"MEMORIAL", "PROPERTY"}
        and manifest_compose_files == {MANFRED_COMPOSITE_CANDIDATE_COMPOSE}
        and not manifest_compose_overrides
        and not override_basenames
    )
    has_memorial = "docker-compose.memorial.yml" in override_basenames
    has_provider_lab = "docker-compose.provider-lab.yml" in override_basenames
    has_property = "docker-compose.property.yml" in override_basenames

    if (
        "MEMORIAL" in enabled_set
        and not has_memorial
        and not manfred_composite_candidate
    ):
        issues.append("memorial_mode_missing_override")
    if "PROVIDER_LAB" in enabled_set and not has_provider_lab:
        issues.append("provider_lab_mode_missing_override")
    if (
        "PROPERTY" in enabled_set
        and not has_property
        and not manfred_composite_candidate
    ):
        issues.append("property_mode_missing_override")

    if requested == "EA_CORE":
        if enabled_set != {"EA_CORE"}:
            issues.append("ea_core_must_not_mix_planes")
        if has_memorial or has_provider_lab or has_property:
            issues.append("ea_core_override_leak")
    if requested == "MEMORIAL" and not has_memorial and not manfred_composite_candidate:
        issues.append("memorial_primary_requires_memorial_override")
    if requested == "PROVIDER_LAB" and not has_provider_lab:
        issues.append("provider_lab_primary_requires_provider_override")
    if requested == "PROPERTY" and not has_property:
        issues.append("property_primary_requires_property_override")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST
    )
    parser.add_argument("--project-modes", type=Path, default=DEFAULT_PROJECT_MODES)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--enabled-mode", action="append", default=[])
    parser.add_argument("--compose-override", action="append", default=[])
    args = parser.parse_args()

    release_manifest = _load_json(args.release_manifest)
    project_modes = _load_json(args.project_modes)
    enabled_modes = list(args.enabled_mode or [])
    if not enabled_modes:
        enabled_modes = [args.mode]
    issues = validate_release_contract(
        release_manifest=release_manifest,
        project_modes=project_modes,
        requested_mode=args.mode,
        enabled_modes=enabled_modes,
        compose_overrides=list(args.compose_override or []),
    )
    if issues:
        raise SystemExit("release_manifest_runtime_mode_invalid:" + ",".join(issues))
    print(
        json.dumps(
            {
                "status": "pass",
                "mode": _normalize_mode(args.mode),
                "enabled_modes": [_normalize_mode(item) for item in enabled_modes],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
