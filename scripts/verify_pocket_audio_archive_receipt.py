#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/pocket_audio_archive_receipt.generated.json"
CONTRACT_NAME = "ea.pocket_audio_archive_receipt.v1"


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_RECEIPT) -> list[str]:
    receipt = _json(path)
    issues: list[str] = []
    if not receipt:
        return [f"missing or invalid receipt: {path.as_posix()}"]
    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append("contract_name mismatch")
    if not str(receipt.get("generated_at") or "").strip():
        issues.append("generated_at missing")
    if not str(receipt.get("source_git_head") or "").strip():
        issues.append("source_git_head missing")
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must be source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics mismatch")
    current_head = resolve_source_state_head(ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(ROOT)
    source_head = str(receipt.get("source_git_head") or "").strip()
    source_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    if source_head and current_head and source_head != current_head and source_fingerprint != current_fingerprint:
        issues.append("source state stale")
    if not source_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif current_fingerprint and source_fingerprint != current_fingerprint:
        issues.append("source_state_fingerprint stale")
    status = str(receipt.get("status") or "").strip()
    if status not in {"pass", "blocked"}:
        issues.append("status must be pass or blocked")
    privacy = dict(receipt.get("privacy") or {})
    for key in (
        "raw_transcript_text_exposed",
        "raw_payload_exposed",
        "raw_archive_root_exposed",
        "raw_recording_ids_exposed",
        "raw_credential_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must be false")
    if privacy.get("archive_root_hashed") is not True:
        issues.append("privacy.archive_root_hashed must be true")
    archive_files = dict(receipt.get("archive_files") or {})
    if archive_files.get("raw_archive_root_exposed") is not False:
        issues.append("archive_files.raw_archive_root_exposed must be false")
    if "archive_root" in archive_files:
        issues.append("archive_files must not expose archive_root")
    if not str(archive_files.get("archive_root_sha256") or "").strip():
        issues.append("archive_files.archive_root_sha256 missing")
    if int(archive_files.get("audio_file_total") or 0) < 0:
        issues.append("archive_files.audio_file_total cannot be negative")
    if int(archive_files.get("metadata_json_total") or 0) < 0:
        issues.append("archive_files.metadata_json_total cannot be negative")
    database_index = dict(receipt.get("database_index") or {})
    if int(receipt.get("failure_count") or 0) != len(list(receipt.get("failures") or [])):
        issues.append("failure_count must equal failures length")
    if status == "pass":
        if int(database_index.get("latest_non_dismissed_missing_transcript_total") or 0) != 0:
            issues.append("pass receipt cannot have non-dismissed Pocket rows missing transcripts")
        if receipt.get("transcript_ingest_ready") is not True:
            issues.append("pass receipt requires transcript_ingest_ready=true")
        if int(receipt.get("failure_count") or 0) != 0:
            issues.append("pass receipt requires failure_count=0")
        if str(receipt.get("next_action") or "").strip() != "maintain_pocket_ai_audio_transcript_archive":
            issues.append("pass receipt next_action must maintain archive")
    else:
        if str(receipt.get("next_action") or "").strip() != "sync_pocket_ai_audio_transcripts":
            issues.append("blocked receipt next_action must sync transcripts")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the redacted Pocket.ai audio transcript archive receipt.")
    parser.add_argument("receipt", nargs="?", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {
        "contract_name": "ea.pocket_audio_archive_receipt.verify.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
