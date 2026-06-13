#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
PUBLIC_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
GENERATED_RECEIPT_PATHS = {
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    if not recorded or not current_head:
        return False
    if recorded == current_head:
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{recorded}..{current_head}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    changed = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return bool(changed) and changed <= GENERATED_RECEIPT_PATHS


def _is_local_base_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in ("://127.0.0.1", "://localhost", "://0.0.0.0", "://[::1]"))


def _metric(receipt: dict[str, Any], key: str) -> float:
    try:
        return float(dict(receipt.get("metrics") or {}).get(key) or 0.0)
    except Exception:
        return 0.0


def _check_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
    public_required: bool,
    direct_min_f1: float,
    conversation_min_f1: float,
) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["receipt_missing_or_invalid"]
    if receipt.get("contract_name") != "ea.memorial_voice_roundtrip_exit_gate":
        issues.append("contract_name_invalid")
    if str(receipt.get("status") or "").strip().lower() != "pass":
        issues.append("receipt_status_not_pass")
    if current_head and not _fresh_enough(str(receipt.get("git_head") or ""), current_head=current_head):
        issues.append("receipt_stale_relative_to_current_head")
    if bool(receipt.get("dirty_worktree")):
        issues.append("receipt_generated_from_dirty_worktree")
    if receipt.get("failed_codes"):
        issues.append("receipt_failed_codes_present")
    if receipt.get("warned_codes"):
        issues.append("receipt_warned_codes_present")
    if public_required:
        if _is_local_base_url(str(receipt.get("base_url") or "")):
            issues.append("public_origin_required_not_localhost")
        if receipt.get("gold_mode") is not True:
            issues.append("public_gold_receipt_must_use_gold_mode")
        if receipt.get("require_public_origin") is not True:
            issues.append("public_gold_receipt_must_require_public_origin")
        if receipt.get("gold_claim_allowed") is not True:
            issues.append("public_gold_claim_not_allowed_by_receipt")
    if _metric(receipt, "direct_tts_f1") < direct_min_f1:
        issues.append("direct_tts_f1_below_gold_threshold")
    if _metric(receipt, "conversation_turn_audio_f1") < conversation_min_f1:
        issues.append("conversation_turn_audio_f1_below_gold_threshold")
    checks = list(receipt.get("checks") or [])
    check_codes = {str(item.get("code") or "") for item in checks if isinstance(item, dict)}
    if "present_world_route_ok" not in check_codes:
        issues.append("local_source_current_world_check_missing")
    serialized = json.dumps(receipt, ensure_ascii=False).lower()
    if "present_world_search" in serialized:
        issues.append("present_world_search_reference_forbidden")
    return issues


def main() -> int:
    current_head = _git_head()
    local = _json(LOCAL_RECEIPT)
    local_issues = _check_receipt(
        local,
        current_head=current_head,
        public_required=False,
        direct_min_f1=0.90,
        conversation_min_f1=0.90,
    )

    public_receipt_path = Path(os.getenv("MEMORIAL_PUBLIC_VOICE_RECEIPT") or PUBLIC_RECEIPT)
    public = _json(public_receipt_path)
    public_issues = _check_receipt(
        public,
        current_head=current_head,
        public_required=True,
        direct_min_f1=0.92,
        conversation_min_f1=0.90,
    )

    status = "pass" if not local_issues and not public_issues else "blocked"
    payload = {
        "status": status,
        "current_head": current_head,
        "local_release_receipt": LOCAL_RECEIPT.as_posix(),
        "local_release_issues": local_issues,
        "public_gold_receipt": public_receipt_path.as_posix(),
        "public_gold_issues": public_issues,
        "memorial_voice_gold_claim_allowed": status == "pass",
        "labels": {
            "local_receipt": "Memorial voice release-candidate proof",
            "public_receipt": "Memorial voice gold proof",
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
