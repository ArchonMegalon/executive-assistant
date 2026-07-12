#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.memorial_narration_cast_resolution import (  # noqa: E402
    MAX_PRIVATE_ARTIFACT_BYTES,
    REQUIRED_REVIEW_SCOPE,
    build_memorial_narration_cast_review,
    cast_resolution_safe_receipt,
    cast_review_safe_receipt,
    read_json_artifact,
    read_signing_secret,
    resolve_memorial_narration_cast,
    verify_memorial_narration_cast,
    write_json_artifact,
)


def _add_signing_secret_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--signing-secret-file", type=Path)
    group.add_argument(
        "--signing-secret-env",
        default="EA_MEMORIAL_NARRATION_REVIEW_SIGNING_SECRET",
        help="Environment variable containing the HMAC review secret.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve and review a memorial narration cast without provider calls."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser(
        "resolve", help="Build a private, provider-free cast resolution."
    )
    resolve_parser.add_argument("--work-package", type=Path, required=True)
    resolve_parser.add_argument("--voice-profile", type=Path, required=True)
    resolve_parser.add_argument("--speaker-mappings", type=Path)
    resolve_parser.add_argument("--speaker-profiles", type=Path)
    resolve_parser.add_argument("--memorial-manifest", type=Path)
    resolve_parser.add_argument("--output", type=Path, required=True)
    resolve_parser.add_argument("--receipt-output", type=Path)

    review_parser = subparsers.add_parser(
        "review",
        help=(
            "Create a signed, hash-bound cast-mapping review. This does not "
            "attest listening or authorize synthesis."
        ),
    )
    review_parser.add_argument("--resolution", type=Path, required=True)
    review_parser.add_argument("--reviewer", required=True)
    review_parser.add_argument(
        "--status", choices=("approved", "rejected"), default="approved"
    )
    review_parser.add_argument("--scope", default=REQUIRED_REVIEW_SCOPE)
    review_parser.add_argument("--reviewed-at", default="")
    review_parser.add_argument("--expires-at", required=True)
    review_parser.add_argument("--revoked", action="store_true")
    review_parser.add_argument("--note", default="")
    review_parser.add_argument("--output", type=Path, required=True)
    review_parser.add_argument("--receipt-output", type=Path)
    _add_signing_secret_arguments(review_parser)

    verify_parser = subparsers.add_parser(
        "verify", help="Verify current consent, resolution, and signed review."
    )
    verify_parser.add_argument("--work-package", type=Path, required=True)
    verify_parser.add_argument("--voice-profile", type=Path, required=True)
    verify_parser.add_argument("--resolution", type=Path, required=True)
    verify_parser.add_argument("--review", type=Path, required=True)
    verify_parser.add_argument("--speaker-mappings", type=Path)
    verify_parser.add_argument("--speaker-profiles", type=Path)
    verify_parser.add_argument("--memorial-manifest", type=Path)
    verify_parser.add_argument("--receipt-output", type=Path)
    _add_signing_secret_arguments(verify_parser)
    return parser


def _secret(args: argparse.Namespace) -> bytes:
    if args.signing_secret_file is not None:
        return read_signing_secret(args.signing_secret_file)
    env_name = str(args.signing_secret_env or "").strip()
    value = str(os.getenv(env_name) or "")
    if not value:
        raise ValueError("review_signing_secret_missing")
    return value.encode("utf-8")


def _paths_distinct(private_path: Path, receipt_path: Path | None) -> None:
    if receipt_path is None:
        return
    if os.path.abspath(os.fspath(private_path)) == os.path.abspath(
        os.fspath(receipt_path)
    ):
        raise ValueError("private_and_receipt_output_paths_must_be_distinct")


def _read_private(path: Path) -> dict[str, object]:
    return read_json_artifact(
        path,
        private=True,
        max_bytes=MAX_PRIVATE_ARTIFACT_BYTES,
    )


def _write_receipt(path: Path | None, receipt: dict[str, object]) -> None:
    if path is not None:
        write_json_artifact(path, receipt, private=False)


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _resolve(args: argparse.Namespace) -> int:
    _paths_distinct(args.output, args.receipt_output)
    work_package = _read_private(args.work_package)
    voice_profile = _read_private(args.voice_profile)
    mappings: object = None
    if args.speaker_mappings is not None:
        mappings = _read_private(args.speaker_mappings)
    speaker_profiles = (
        _read_private(args.speaker_profiles)
        if args.speaker_profiles is not None
        else None
    )
    memorial_manifest = (
        _read_private(args.memorial_manifest)
        if args.memorial_manifest is not None
        else None
    )
    resolution = resolve_memorial_narration_cast(
        work_package=work_package,
        voice_profile=voice_profile,
        speaker_voice_mappings=mappings,
        current_speaker_profiles=speaker_profiles,
        current_memorial_manifest=memorial_manifest,
    )
    write_json_artifact(args.output, resolution, private=True)
    receipt = cast_resolution_safe_receipt(resolution)
    _write_receipt(args.receipt_output, receipt)
    _emit(receipt)
    return 0 if resolution.get("status") == "ready_for_mapping_review" else 1


def _review(args: argparse.Namespace) -> int:
    _paths_distinct(args.output, args.receipt_output)
    resolution = _read_private(args.resolution)
    review = build_memorial_narration_cast_review(
        resolution=resolution,
        reviewer=args.reviewer,
        signing_secret=_secret(args),
        status=args.status,
        scope=args.scope,
        reviewed_at=args.reviewed_at,
        expires_at=args.expires_at,
        revoked=args.revoked,
        note=args.note,
    )
    write_json_artifact(args.output, review, private=True)
    receipt = cast_review_safe_receipt(review)
    _write_receipt(args.receipt_output, receipt)
    _emit(receipt)
    return 0 if review.get("approved") is True else 1


def _verify(args: argparse.Namespace) -> int:
    work_package = _read_private(args.work_package)
    voice_profile = _read_private(args.voice_profile)
    resolution = _read_private(args.resolution)
    review = _read_private(args.review)
    mappings: object = None
    if args.speaker_mappings is not None:
        mappings = _read_private(args.speaker_mappings)
    speaker_profiles = (
        _read_private(args.speaker_profiles)
        if args.speaker_profiles is not None
        else None
    )
    memorial_manifest = (
        _read_private(args.memorial_manifest)
        if args.memorial_manifest is not None
        else None
    )
    receipt = verify_memorial_narration_cast(
        work_package=work_package,
        resolution=resolution,
        review=review,
        voice_profile=voice_profile,
        signing_secret=_secret(args),
        speaker_voice_mappings=mappings,
        current_speaker_profiles=speaker_profiles,
        current_memorial_manifest=memorial_manifest,
    )
    _write_receipt(args.receipt_output, receipt)
    _emit(receipt)
    return 0 if receipt.get("cast_mapping_reviewed") is True else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "resolve":
            return _resolve(args)
        if args.command == "review":
            return _review(args)
        if args.command == "verify":
            return _verify(args)
        raise ValueError("command_not_supported")
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {
                "status": "blocked",
                "reason": str(exc) or type(exc).__name__,
                "synthesis_authorized": False,
                "raw_voice_ids_exposed": False,
                "sensitive_trait_values_exposed": False,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
