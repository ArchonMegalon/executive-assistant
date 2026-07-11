#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = _REPO_ROOT / "ea"
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from app.services import memorial_recovery_inventory as recovery  # noqa: E402


OPERATOR_RECEIPT_SCHEMA = "ea.memorial_recovery_inventory_operator_receipt.v1"
_ERROR_RE = re.compile(r"^memorial_recovery_inventory_[a-z0-9_]+$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_RECEIPT_FIELDS = {
    "schema",
    "memorial_slug",
    "payload_sha256",
    "inventory_file_sha256",
    "source_media_count",
    "archive_document_count",
    "private_context_present",
    "family_private_present",
    "family_public_present",
    "private_file_mode",
    "canonical_publication_state_included",
    "private_media_publication_performed",
    "valid",
    "mode",
    "dry_run",
    "files_in_inventory",
    "files_to_create",
    "files_existing",
    "files_created",
    "apply_confirmation_matched",
    "atomic_file_writes",
    "idempotent_merge",
    "canonical_publication_state_restored",
    "private_media_published",
}


def _optional_path(value: str) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser() if text else None


def _safe_receipt(payload: dict[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in sorted(_SAFE_RECEIPT_FIELDS) if key in payload}


def _error_code(exc: Exception) -> str:
    candidate = str(exc or "").strip()
    if _ERROR_RE.fullmatch(candidate):
        return candidate
    return "memorial_recovery_inventory_operation_failed"


def _add_roots(
    parser: argparse.ArgumentParser, *, include_public_archive: bool
) -> None:
    parser.add_argument("--private-root", default="")
    if include_public_archive:
        parser.add_argument("--public-root", default="")
        parser.add_argument("--archive-root", default="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize, verify, or safely restore a private memorial recovery inventory."
    )
    commands = parser.add_subparsers(dest="operation", required=True)

    materialize = commands.add_parser("materialize")
    materialize.add_argument("--slug", required=True)
    materialize.add_argument("--destination", required=True)
    _add_roots(materialize, include_public_archive=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--slug", required=True)
    verify.add_argument("--inventory", required=True)
    _add_roots(verify, include_public_archive=False)

    restore = commands.add_parser("restore")
    restore.add_argument("--slug", required=True)
    restore.add_argument("--inventory", required=True)
    restore.add_argument("--apply", action="store_true")
    restore.add_argument("--confirm-payload-sha", default="")
    _add_roots(restore, include_public_archive=True)
    return parser


def _run(args: argparse.Namespace) -> dict[str, object]:
    private_root = _optional_path(args.private_root)
    if args.operation == "materialize":
        return recovery.materialize_memorial_recovery_inventory(
            memorial_slug=args.slug,
            destination_path=args.destination,
            public_root=_optional_path(args.public_root),
            private_root=private_root,
            archive_root=_optional_path(args.archive_root),
        )
    if args.operation == "verify":
        return recovery.verify_memorial_recovery_inventory(
            inventory_path=args.inventory,
            expected_memorial_slug=args.slug,
            private_root=private_root,
        )
    confirmation = str(args.confirm_payload_sha or "").strip().lower()
    if args.apply:
        if not confirmation:
            raise ValueError("memorial_recovery_inventory_apply_confirmation_required")
        if not _DIGEST_RE.fullmatch(confirmation):
            raise ValueError("memorial_recovery_inventory_apply_confirmation_invalid")
    elif confirmation:
        raise ValueError("memorial_recovery_inventory_confirmation_requires_apply")
    return recovery.restore_memorial_recovery_inventory(
        inventory_path=args.inventory,
        expected_memorial_slug=args.slug,
        dry_run=not args.apply,
        confirmed_payload_sha256=confirmation,
        public_root=_optional_path(args.public_root),
        private_root=private_root,
        archive_root=_optional_path(args.archive_root),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except Exception as exc:
        payload = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "status": "fail",
            "operation": str(args.operation or ""),
            "error": {"code": _error_code(exc)},
            "inventory_body_included": False,
            "secret_material_included": False,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1
    payload = {
        "schema": OPERATOR_RECEIPT_SCHEMA,
        "status": "pass",
        "operation": str(args.operation or ""),
        "receipt": _safe_receipt(result),
        "inventory_body_included": False,
        "secret_material_included": False,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
