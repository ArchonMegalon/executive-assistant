#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "ea/_completion/aiwritebook/canary"
DEFAULT_SOURCE = DEFAULT_OUTPUT_DIR / "AIWRITEBOOK_CANARY_SOURCE.md"
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "AIWRITEBOOK_CANARY_MANIFEST.generated.json"
CONTRACT = "ea.aiwritebook.synthetic_canary"
FIXTURE_ID = "aiwritebook-chronicle-export-canary-v1"
MARKER = "EA-AIWRITEBOOK-CANARY-2026-08-11-7F3C"
FILE_MODE = 0o600


SOURCE_TEXT = f"""# The Quiet Signal

Fixture ID: `{FIXTURE_ID}`

Content marker: `{MARKER}`

## Chapter 1: A Light in the Rain

Rain traced silver lines across the empty station window. Mara set a small brass
compass on the table and waited for its needle to settle. It pointed east, toward
the old relay tower where a single amber light blinked at exact thirty-second
intervals.

Jon arrived carrying two cups of tea and a folded paper map. Neither of them used
a real address, a real person, or a real event in their notes. This was a test of
formatting and export fidelity, nothing more.

They compared the map with the compass, marked a harmless route in blue pencil,
and agreed on a simple rule: if the light changed rhythm, they would return home.
The light stayed steady. They finished their tea, packed the map, and left the
station exactly as they had found it.

## Export note

Preserve the title, chapter heading, paragraphs, fixture ID, and content marker.
Do not add names, biographical details, campaign material, images, or external
links. Export this synthetic text as PDF, EPUB, and DOCX.
"""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_manifest(source_name: str, source_bytes: bytes) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": CONTRACT,
        "contract_version": 1,
        "fixture_id": FIXTURE_ID,
        "title": "The Quiet Signal",
        "content_marker": MARKER,
        "source": {
            "filename": source_name,
            "sha256": _sha256(source_bytes),
            "size_bytes": len(source_bytes),
        },
        "data_classification": {
            "synthetic": True,
            "contains_personal_data": False,
            "contains_campaign_data": False,
            "contains_customer_data": False,
            "contains_copied_third_party_text": False,
        },
        "rights": {
            "basis": "original_synthetic_repository_canary_text",
            "spdx_license_expression": "CC0-1.0",
        },
        "requested_run": {
            "chapter_count": 1,
            "writing_model": "gemini",
            "cover": False,
            "translation": False,
            "audiobook": False,
            "expected_exports": ["pdf", "epub", "docx"],
        },
        "credit_budget": {
            "declared_outline_credits": 3,
            "declared_writing_credits": 15,
            "expected_total_credits": 18,
            "maximum_approved_credits": 18,
        },
        "execution_boundary": {
            "operator_required": True,
            "unattended_browser_automation_allowed": False,
            "approval_required_before_upload": True,
            "approval_required_before_generation": True,
            "approval_required_before_credit_spend": True,
            "publication_allowed": False,
            "external_send_allowed": False,
        },
    }
    payload["manifest_sha256"] = _sha256(_canonical_json(payload))
    return payload


def _assert_output(path: Path, *, replace: bool) -> None:
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink():
            raise RuntimeError(f"output_parent_symlink_not_allowed:{path.name}")
    if path.is_symlink():
        raise RuntimeError(f"output_symlink_not_allowed:{path.name}")
    if path.exists():
        if not path.is_file():
            raise RuntimeError(f"output_not_regular_file:{path.name}")
        if not replace:
            raise FileExistsError(f"output_exists_use_replace:{path.name}")


def _write_file(path: Path, payload: bytes, *, replace: bool) -> None:
    _assert_output(path, replace=replace)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp = Path(raw_temp)
    try:
        os.fchmod(descriptor, FILE_MODE)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            _assert_output(path, replace=True)
            os.replace(temp, path)
        else:
            os.link(temp, path, follow_symlinks=False)
            temp.unlink()
        os.chmod(path, FILE_MODE, follow_symlinks=False)
    finally:
        temp.unlink(missing_ok=True)


def materialize(
    *,
    source_path: Path = DEFAULT_SOURCE,
    manifest_path: Path = DEFAULT_MANIFEST,
    replace: bool = False,
) -> dict[str, Any]:
    source = Path(source_path)
    manifest = Path(manifest_path)
    if source.absolute() == manifest.absolute():
        raise ValueError("source_and_manifest_paths_must_differ")
    _assert_output(source, replace=replace)
    _assert_output(manifest, replace=replace)
    source_bytes = SOURCE_TEXT.encode("utf-8")
    manifest_payload = build_manifest(source.name, source_bytes)
    _write_file(source, source_bytes, replace=replace)
    try:
        _write_file(manifest, _canonical_json(manifest_payload), replace=replace)
    except BaseException:
        if not replace:
            source.unlink(missing_ok=True)
        raise
    return manifest_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a deterministic, rights-safe AIWriteBook export canary.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    payload = materialize(source_path=args.source, manifest_path=args.manifest, replace=args.replace)
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
