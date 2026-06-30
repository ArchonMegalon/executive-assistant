#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/pocket_audio_archive_receipt.generated.json"
CONTRACT_NAME = "ea.pocket_audio_archive_receipt.v1"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_pocket_audio_archive as pocket_verifier  # noqa: E402


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _source_state_fields(root: Path) -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(root),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(root),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _compact_failure(value: object, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sanitized_archive_files(raw: dict[str, Any]) -> dict[str, Any]:
    archive_root = str(raw.get("archive_root") or "").strip()
    return {
        "archive_root_present": bool(archive_root),
        "archive_root_sha256": _sha256_text(archive_root),
        "archive_root_exists": bool(raw.get("archive_root_exists")),
        "audio_file_total": _safe_int(raw.get("audio_file_total")),
        "metadata_json_total": _safe_int(raw.get("metadata_json_total")),
        "raw_archive_root_exposed": False,
    }


def build_receipt(
    *,
    archive_root: Path,
    index_rows: list[dict[str, Any]],
    completion_rows: list[dict[str, Any]],
    db_probe_error: str = "",
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    verification = pocket_verifier.build_receipt(
        archive_root=archive_root,
        index_rows=index_rows,
        completion_rows=completion_rows,
        db_probe_error=db_probe_error,
    )
    failures = [_compact_failure(item) for item in list(verification.get("failures") or []) if str(item).strip()]
    receipt = {
        "contract_name": CONTRACT_NAME,
        **_source_state_fields(root),
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_pocket_audio_archive_receipt.py",
        "output_path": output_path.as_posix(),
        "status": "pass" if str(verification.get("status") or "").strip() == "pass" else "blocked",
        "claim": (
            "Pocket.ai audio transcript ingest is usable only when local archive metadata and index evidence prove "
            "non-dismissed recordings have transcripts without exposing raw transcript text."
        ),
        "archive_files": _sanitized_archive_files(dict(verification.get("archive_files") or {})),
        "archive_metadata": dict(verification.get("archive_metadata") or {}),
        "database_index": dict(verification.get("database_index") or {}),
        "latest_backfill": dict(verification.get("latest_backfill") or {}),
        "latest_completion": dict(verification.get("latest_completion") or {}),
        "db_probe_status": str(verification.get("db_probe_status") or "").strip(),
        "db_probe_error_present": bool(str(verification.get("db_probe_error") or "").strip()),
        "db_probe_error_sha256": _sha256_text(verification.get("db_probe_error")),
        "evidence_mode": str(verification.get("evidence_mode") or "").strip(),
        "failure_count": len(failures),
        "failures": failures,
        "transcript_ingest_ready": str(verification.get("status") or "").strip() == "pass",
        "next_action": "maintain_pocket_ai_audio_transcript_archive"
        if str(verification.get("status") or "").strip() == "pass"
        else "sync_pocket_ai_audio_transcripts",
        "privacy": {
            "raw_transcript_text_exposed": False,
            "raw_payload_exposed": False,
            "raw_archive_root_exposed": False,
            "raw_recording_ids_exposed": False,
            "raw_credential_exposed": False,
            "archive_root_hashed": True,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _load_runtime_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    try:
        index_rows = pocket_verifier.load_index_rows(
            container=args.postgres_container,
            user=args.postgres_user,
            database=args.postgres_db,
        )
        completion_rows = pocket_verifier.load_completion_rows(
            container=args.postgres_container,
            user=args.postgres_user,
            database=args.postgres_db,
        )
        return index_rows, completion_rows, ""
    except Exception as exc:
        return [], [], _compact_failure(str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a redacted Pocket.ai audio transcript archive receipt.")
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path(os.environ.get("EA_POCKET_AUDIO_ARCHIVE_ROOT") or pocket_verifier.DEFAULT_ARCHIVE_ROOT),
    )
    parser.add_argument("--postgres-container", default=os.environ.get("EA_POSTGRES_CONTAINER") or "ea-db")
    parser.add_argument("--postgres-user", default=os.environ.get("POSTGRES_USER") or "postgres")
    parser.add_argument("--postgres-db", default=os.environ.get("POSTGRES_DB") or "ea_smoke_runtime")
    parser.add_argument("--output", "--out", dest="output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    index_rows, completion_rows, db_probe_error = _load_runtime_rows(args)
    receipt = build_receipt(
        archive_root=args.archive_root,
        index_rows=index_rows,
        completion_rows=completion_rows,
        db_probe_error=db_probe_error,
        output_path=args.output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
