#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts import sync_env_to_teable
except ModuleNotFoundError:  # pragma: no cover - script execution path
    import sync_env_to_teable  # type: ignore[no-redef]

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/teable_env_recovery_proof.generated.json"
DEFAULT_TABLE_NAME = "ea_environment_secrets_recovery"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(path: Path) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path) -> str:
    return resolve_source_worktree_fingerprint(path)


def _sha256_text(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _sanitize_env_files(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sanitized.append(
            {
                "scope": str(row.get("scope") or "").strip(),
                "path_sha256": _sha256_text(row.get("path")),
                "path_recorded": bool(str(row.get("path") or "").strip()),
                "restored": _int_value(row.get("restored")),
                "hash_verified": _int_value(row.get("hash_verified")),
                "hash_mismatch_count": _int_value(row.get("hash_mismatch_count")),
                "backup_created": bool(row.get("backup_created")),
                "mode": str(row.get("mode") or "").strip(),
            }
        )
    return sanitized


def _sanitize_referenced_files(payload: dict[str, Any]) -> dict[str, Any]:
    modes = []
    for row in list(payload.get("modes") or []):
        if not isinstance(row, dict):
            continue
        modes.append(
            {
                "path_sha256": _sha256_text(row.get("path")),
                "mode": str(row.get("mode") or "").strip(),
            }
        )
    return {
        "restored": _int_value(payload.get("restored")),
        "hash_verified": _int_value(payload.get("hash_verified")),
        "hash_mismatch_count": _int_value(payload.get("hash_mismatch_count")),
        "backup_count": _int_value(payload.get("backup_count")),
        "path_count": _int_value(payload.get("path_count")),
        "path_sha256": [_sha256_text(path) for path in list(payload.get("paths") or []) if str(path or "").strip()],
        "modes": modes,
    }


def build_teable_env_recovery_proof(
    *,
    root: Path = ROOT,
    output_path: Path = DEFAULT_OUTPUT,
    base_url: str = "",
    api_key: str = "",
    table_id: str = "",
    table_name: str = DEFAULT_TABLE_NAME,
    host_profile: str = "ea-prod",
    generated_at: str | None = None,
) -> dict[str, Any]:
    seeded_api_key = str(api_key or os.environ.get("TEABLE_API_KEY") or "").strip()
    if not seeded_api_key:
        raise SystemExit("teable_seeded_api_key_required")
    resolved_base_url = str(base_url or os.environ.get("TEABLE_BASE_URL") or sync_env_to_teable.DEFAULT_BASE_URL).strip().rstrip("/")
    resolved_table_id = str(table_id or "").strip()
    resolved_table_name = str(table_name or DEFAULT_TABLE_NAME).strip() or DEFAULT_TABLE_NAME
    discovery_mode = "explicit_table_id"
    if not resolved_table_id:
        resolved_table_id = sync_env_to_teable.discover_table_id(
            base_url=resolved_base_url,
            api_key=seeded_api_key,
            table_name=resolved_table_name,
        )
        discovery_mode = "discovered_by_name"
    if not resolved_table_id:
        raise SystemExit("teable_table_id_missing")

    drill_root = Path(tempfile.mkdtemp(prefix="ea-teable-fresh-host-proof-"))
    try:
        result = sync_env_to_teable.recover_from_teable(
            base_url=resolved_base_url,
            api_key=seeded_api_key,
            table_id=resolved_table_id,
            root_env_path=drill_root / ".env",
            local_env_path=drill_root / ".env.local",
            service_env_path=drill_root / "ea" / ".env",
            host_profile=host_profile,
            backup_existing=False,
        )
        raw_proof = dict(result.get("recovery_proof") or {})
        verification = dict(raw_proof.get("verification") or {})
        status = (
            "pass"
            if str(result.get("status") or "").strip() == "recovered" and str(verification.get("status") or "").strip() == "pass"
            else "blocked"
        )
        receipt = {
            "contract_name": "ea.teable_env_recovery_proof.v1",
            "generated_at": generated_at or _utc_now(),
            "generated_by": "scripts/materialize_teable_env_recovery_proof.py",
            "source_git_head": _git_head(root),
            "head_semantics": "source_state",
            "source_state_fingerprint": _source_fingerprint(root),
            "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
            "output_path": str(output_path if output_path.is_absolute() else output_path.as_posix()),
            "status": status,
            "recovery_status": str(result.get("status") or "").strip(),
            "host_profile": str(raw_proof.get("host_profile") or host_profile).strip() or host_profile,
            "fresh_host_api_key_source": "process_env",
            "table_discovery_mode": discovery_mode,
            "table_id_sha256": _sha256_text(resolved_table_id),
            "table_name": resolved_table_name,
            "secret_values_redacted": True,
            "drill_output_removed": False,
            "env_files": _sanitize_env_files(list(raw_proof.get("env_files") or [])),
            "referenced_files": _sanitize_referenced_files(dict(raw_proof.get("referenced_files") or {})),
            "verification": {
                "status": str(verification.get("status") or "").strip(),
                "expected_rows": _int_value(verification.get("expected_rows")),
                "same_hash": _int_value(verification.get("same_hash")),
                "missing_count": _int_value(verification.get("missing_count")),
                "different_hash_count": _int_value(verification.get("different_hash_count")),
                "missing_secret_value_count": _int_value(verification.get("missing_secret_value_count")),
                "extra_restorable_count": _int_value(verification.get("extra_restorable_count")),
            },
            "privacy": {
                "raw_paths_exposed": False,
                "raw_table_id_exposed": False,
                "raw_api_key_exposed": False,
                "secret_values_exposed": False,
            },
            "rules": [
                "This receipt proves a fresh-host-style Teable recovery run into a throwaway private directory and keeps secret values redacted.",
                "Do not treat this receipt as license to store recovery truth outside Teable and mirrored evidence surfaces.",
                "Delete throwaway recovery outputs after verification so the mirrored receipt keeps the proof while the secret material is removed from disk.",
            ],
        }
    finally:
        if drill_root.is_dir():
            shutil.rmtree(drill_root)
    receipt["drill_output_removed"] = True
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a sanitized fresh-host Teable recovery proof receipt.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-url", default=str(os.environ.get("TEABLE_BASE_URL") or "").strip())
    parser.add_argument("--api-key", default=str(os.environ.get("TEABLE_API_KEY") or "").strip())
    parser.add_argument("--table-id", default=str(os.environ.get("EA_ENV_TEABLE_TABLE_ID") or "").strip())
    parser.add_argument("--table-name", default=str(os.environ.get("EA_ENV_TEABLE_TABLE_NAME") or DEFAULT_TABLE_NAME).strip())
    parser.add_argument("--host-profile", default=str(os.environ.get("EA_ENV_TEABLE_HOST_PROFILE") or "ea-prod").strip() or "ea-prod")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    output_path = args.output if args.output.is_absolute() else args.root / args.output
    receipt = build_teable_env_recovery_proof(
        root=args.root,
        output_path=output_path,
        base_url=args.base_url,
        api_key=args.api_key,
        table_id=args.table_id,
        table_name=args.table_name,
        host_profile=args.host_profile,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
