from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint

CONTRACT_NAME = "ea.telegram_audiobook_live_readiness_checklist.v1"
REQUIRED_LIVE_PROOF = {
    "real Telegram audiobook source upload",
    "three Telegram voice samples delivered with Use this/Dismiss controls",
    "operator-selected voice callback applied",
    "M4B rendered and imported into Audiobookshelf",
    "Audiobookshelf scan completed",
    "public share link sent back to Telegram",
    "sanitized live delivery receipt materialized",
    "separate human playback acceptance captured",
}
DISCOVERY_ENV_VARS = {
    "voice_catalog_configured": {
        "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED",
        "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES",
    },
    "unmixr_cinematic_narration_enabled": {
        "EA_AUDIOBOOK_CINEMATIC_NARRATION",
    },
    "voice_catalog_audition_ready": {
        "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED",
        "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_TARGET_COUNT",
        "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES",
    },
}
REQUIRED_READY_VOICE_KEYS = {"unmixr_cinematic_narration_enabled"}


Runner = Callable[..., object]


def _load_json(path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}
    return parsed if isinstance(parsed, dict) else {"_load_error": "receipt_not_object"}


def _verify_source_state(receipt: dict[str, object], issues: list[str]) -> None:
    if receipt.get("head_semantics") != "source_state":
        issues.append("live_readiness_head_semantics_missing")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("live_readiness_source_state_fingerprint_semantics_missing")
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    current_head = resolve_source_state_head(ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(ROOT)
    if not recorded_head:
        issues.append("live_readiness_source_git_head_missing")
    elif recorded_head != current_head and recorded_fingerprint != current_fingerprint:
        issues.append("live_readiness_source_git_head_stale")
    if not recorded_fingerprint:
        issues.append("live_readiness_source_state_fingerprint_missing")
    elif recorded_fingerprint != current_fingerprint:
        issues.append("live_readiness_source_state_fingerprint_stale")


def _section_item(receipt: dict[str, object], section: str, key: str) -> dict[str, object]:
    section_obj = receipt.get(section)
    if not isinstance(section_obj, dict):
        return {}
    for row in list(section_obj.get("items") or []):
        if isinstance(row, dict) and row.get("key") == key:
            return row
    return {}


def _privacy_issues(receipt: dict[str, object]) -> list[str]:
    issues: list[str] = []
    privacy = receipt.get("privacy")
    if not isinstance(privacy, dict):
        return ["live_readiness_privacy_missing"]
    for key in (
        "env_values_exposed",
        "raw_provider_voice_ids_exposed",
        "raw_public_share_url_included",
        "raw_storage_paths_included",
        "raw_telegram_chat_id_included",
    ):
        if privacy.get(key) is not False:
            issues.append(f"live_readiness_privacy_flag_not_false:{key}")
    return issues


def _run_text_probe(command: Sequence[str], runner: Runner | None) -> tuple[int, str, str]:
    if runner is None:
        proc = subprocess.run(list(command), text=True, capture_output=True, check=False)
    else:
        proc = runner(list(command), text=True, capture_output=True, check=False)
    return (
        int(getattr(proc, "returncode", 1)),
        str(getattr(proc, "stdout", "") or ""),
        str(getattr(proc, "stderr", "") or ""),
    )


def _verify_deployed_runtime(*, runtime_container: str, runner: Runner | None = None) -> dict[str, object]:
    issues: list[str] = []
    probes = {
        "telegram_channels": (
            "/app/app/api/routes/channels.py",
            "/app/ea/app/api/routes/channels.py",
        ),
        "audiobook_pipeline": (
            "/app/app/services/audiobook_epub_pipeline.py",
            "/app/ea/app/services/audiobook_epub_pipeline.py",
        ),
    }
    results: dict[str, object] = {}
    for key, paths in probes.items():
        path_expr = repr(list(paths))
        code, stdout, stderr = _run_text_probe(
            [
                "docker",
                "exec",
                runtime_container,
                "python",
                "-c",
                (
                    "from pathlib import Path\n"
                    f"paths = {path_expr}\n"
                    "for raw in paths:\n"
                    "    path = Path(raw)\n"
                    "    if path.is_file():\n"
                    "        print(path.read_text(encoding='utf-8', errors='replace'))\n"
                    "        raise SystemExit(0)\n"
                    "raise SystemExit('deployed_runtime_file_missing')\n"
                ),
            ],
            runner,
        )
        text = stdout if code == 0 else stderr
        results[key] = {"returncode": code, "text_sha256_present": bool(text)}
        if code != 0:
            issues.append(f"deployed_runtime_probe_failed:{key}")
            continue
        if key == "telegram_channels":
            if "dismiss the rest get the next batch" in text:
                issues.append("deployed_runtime_old_audiobook_dismiss_workflow_present:telegram_channels")
            if "_telegram_audiobook_voice_sample_subset" not in text or "replacement audiobook voice" not in text:
                issues.append("deployed_runtime_immediate_replacement_missing:telegram_channels")
        else:
            if "refill_pending" not in text or "replacement_candidate_keys" not in text:
                issues.append("deployed_runtime_immediate_replacement_missing:audiobook_pipeline")
            if "author_gender_signal" not in text:
                issues.append("deployed_runtime_author_gender_signal_missing:audiobook_pipeline")
    return {
        "status": "fail" if issues else "pass",
        "runtime_container": runtime_container,
        "issues": issues,
        "probes": results,
    }


def verify_telegram_audiobook_live_readiness(
    receipt_path: Path,
    *,
    runtime_container: str | None = None,
    require_deployed_runtime: bool = False,
    runner: Runner | None = None,
) -> dict[str, object]:
    receipt = _load_json(receipt_path)
    issues: list[str] = []
    if receipt.get("_load_error"):
        issues.append("live_readiness_receipt_unreadable")
    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append("live_readiness_contract_name_mismatch")
    _verify_source_state(receipt, issues)
    if receipt.get("live_delivery_claim_allowed") is not False:
        issues.append("live_readiness_delivery_claim_overclaim")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("live_readiness_goal_completion_overclaim")
    issues.extend(_privacy_issues(receipt))
    required = set(str(item) for item in list(receipt.get("required_live_proof_after_readiness") or []))
    if not REQUIRED_LIVE_PROOF.issubset(required):
        issues.append("live_readiness_required_live_proof_incomplete")
    for key, required_vars in DISCOVERY_ENV_VARS.items():
        item = _section_item(receipt, "voice_samples", key)
        env_vars = set(str(value) for value in list(item.get("env_var_names") or []))
        if not required_vars.issubset(env_vars):
            issues.append(f"live_readiness_discovery_env_vars_missing:{key}")
        if key in REQUIRED_READY_VOICE_KEYS and item and str(item.get("status") or "") != "ready":
            issues.append(f"live_readiness_critical_voice_item_blocked:{key}")
    for section in ("voice_samples", "delivery"):
        section_obj = receipt.get(section)
        if not isinstance(section_obj, dict):
            issues.append(f"live_readiness_section_missing:{section}")
            continue
        for row in list(section_obj.get("items") or []):
            if isinstance(row, dict) and row.get("env_values_exposed") is not False:
                issues.append(f"live_readiness_item_env_values_exposed:{section}:{row.get('key')}")

    deployed_runtime: dict[str, object] = {"status": "skipped"}
    if require_deployed_runtime:
        deployed_runtime = _verify_deployed_runtime(runtime_container=runtime_container or "ea-api", runner=runner)
        issues.extend(list(deployed_runtime.get("issues") or []))

    return {
        "contract_name": "ea.telegram_audiobook_live_readiness_verification.v1",
        "status": "fail" if issues else "pass",
        "issues": issues,
        "receipt_path": receipt_path.as_posix(),
        "deployed_runtime": deployed_runtime,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, default=ROOT / ".codex-studio" / "published" / "telegram_audiobook_live_readiness.generated.json")
    parser.add_argument("--runtime-container", default="")
    parser.add_argument("--require-deployed-runtime", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    result = verify_telegram_audiobook_live_readiness(
        args.receipt,
        runtime_container=args.runtime_container or None,
        require_deployed_runtime=args.require_deployed_runtime,
    )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
