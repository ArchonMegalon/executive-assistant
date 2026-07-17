#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_ARTIFACTS = (
    Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"),
    Path(".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"),
    Path(".codex-design/product/MEMORIAL_PHRASE_BANK.manfred.generated.json"),
    Path(".codex-design/product/PROJECT_MODES.generated.json"),
    Path(".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"),
    Path(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"),
    Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"),
    Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"),
    Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
    Path(".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"),
    Path(".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"),
    Path(".codex-studio/published/memorial_spatial_tour_public_origin.generated.json"),
    Path(".codex-studio/published/mymedia_alexa_readiness.generated.json"),
    Path(".codex-studio/published/teable_env_recovery_readiness.generated.json"),
    Path(".codex-studio/published/telegram_video_delivery_operator.generated.json"),
    Path(".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"),
)
MATERIALIZER_COMMANDS = (
    ("scripts/materialize_ea_browser_workflow_proof.py",),
    ("scripts/materialize_memorial_spatial_tour_public_origin.py",),
    ("scripts/materialize_project_mode_manifests.py",),
    ("scripts/materialize_telegram_video_delivery_receipt.py",),
    ("scripts/materialize_memorial_phrase_bank.py",),
    ("scripts/materialize_teable_env_recovery_readiness.py",),
    ("scripts/materialize_mymedia_alexa_readiness.py",),
    ("scripts/materialize_whatsapp_web_action_processor_readiness.py",),
    ("scripts/materialize_proactive_ooda_operator_status.py",),
    ("scripts/materialize_proactive_ooda_gold_acceptance.py",),
    ("scripts/materialize_continuous_improvement_goal_posture.py",),
    ("scripts/materialize_ea_flagship_release_gate.py",),
    ("scripts/materialize_weekly_product_pulse.py",),
    ("scripts/materialize_whole_project_gold_map.py",),
    ("scripts/materialize_memorial_operator_status.py",),
)
VOLATILE_KEYS = {
    "available_bytes",
    "available_gb",
    "generated_at",
    "as_of",
    "created_at",
    "observed_at",
    "current_head",
    "evidence_heads",
    "mtime_utc",
    "size_bytes",
    "sha256",
    "duration_seconds",
    "git_branch",
    "git_head",
    "source_path",
    "resolved_path",
    "git_repo_root",
    "command",
    "cwd",
    "output_excerpt",
    "python_bin",
    "review_due",
    "run_id",
    "source_tree_fingerprint",
    "state_age_seconds",
    "state_updated_at",
    "sidecar_last_qr_at",
}


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if (
                key in VOLATILE_KEYS
                or key_str in VOLATILE_KEYS
                or key_str.endswith("_git_head")
                or key_str.endswith("_ms")
                or key_str.endswith("_ms_max")
                or key_str.endswith("_ms_min")
                or key_str.endswith("_ms_total")
                or key_str.endswith("_ms_std")
                or key_str.endswith("_updated_at")
                or key_str.endswith("_observed_at")
                or key_str.endswith("_age_seconds")
            ):
                continue
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _load_worktree(path: Path) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_text(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _run_materializers() -> None:
    for command in MATERIALIZER_COMMANDS:
        subprocess.run(
            [sys.executable, *command],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


def main() -> int:
    original_text_by_path: dict[Path, str] = {}
    original_payload_by_path: dict[Path, Any] = {}
    for path in GENERATED_ARTIFACTS:
        try:
            original_text_by_path[path] = _load_text(path)
            original_payload_by_path[path] = json.loads(original_text_by_path[path])
        except Exception as exc:
            print(f"{path}: unable to load generated artifact before materialization: {exc}", file=sys.stderr)
            return 1

    try:
        _run_materializers()
    except Exception as exc:
        print(f"materializers failed: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = []
    semantically_clean: list[Path] = []
    for path in GENERATED_ARTIFACTS:
        try:
            baseline_payload = original_payload_by_path[path]
            worktree_payload = _load_worktree(path)
        except Exception as exc:
            failures.append(f"{path}: unable to load generated artifact: {exc}")
            continue
        if _normalize(baseline_payload) != _normalize(worktree_payload):
            failures.append(f"{path}: semantic drift after materialization")
        else:
            semantically_clean.append(path)

    for path in semantically_clean:
        (ROOT / path).write_text(original_text_by_path[path], encoding="utf-8")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("generated release artifacts are semantically clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
