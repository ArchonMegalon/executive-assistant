#!/usr/bin/env python3
"""Run one bounded 1min STT check against an existing audiobook canary.

This lane never synthesizes audio, imports into Audiobookshelf, publishes, or
sends a channel message.  It permits at most one asset upload and one STT
inference, discards the raw provider response and transcript, and emits only
private, portable evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

CONTRACT_NAME = "ea.audiobook_supplemental_stt_validation.v2"
POINTER_CONTRACT_NAME = "ea.audiobook_supplemental_stt_pointer.v2"
INVENTORY_CONTRACT_NAME = "ea.audiobook_supplemental_stt_inventory.v2"
FIXTURE_CONTRACT_NAME = "ea.audiobook_live_canary_fixture.v1"
FIXTURE_LANGUAGE = "en"
FIXTURE_LANGUAGE_TAG = "en-US"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_M4B_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
FORBIDDEN_OUTPUT_ROOTS = (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm"))


class ProviderModule(Protocol):
    def _pocket_onemin_api_keys(self) -> tuple[str, ...]: ...

    def _onemin_asset_upload(
        self,
        *,
        api_key: str,
        filename: str,
        content_type: str,
        payload: bytes,
    ) -> dict[str, object]: ...

    def _onemin_speech_to_text(
        self,
        *,
        api_key: str,
        audio_path: str,
        language: str,
    ) -> dict[str, object]: ...

    def _onemin_transcript_text(self, value: object) -> str: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _read_regular_file(path: Path, *, max_bytes: int, reason: str) -> bytes:
    if not path.is_absolute():
        raise ValueError(f"{reason}_path_not_absolute")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, os.getuid()}
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size < 1
            or before.st_size > max_bytes
        ):
            raise ValueError(f"{reason}_file_untrusted")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError(f"{reason}_file_changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        identity = lambda item: (
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise ValueError(f"{reason}_file_changed")
        return b"".join(chunks)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _require_private_output_dir(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("output_dir_not_absolute")
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("output_dir_not_private")
    resolved = path.resolve(strict=True)
    for temporary_root in FORBIDDEN_OUTPUT_ROOTS:
        if resolved == temporary_root or temporary_root in resolved.parents:
            raise ValueError("output_dir_not_durable")
    if any(path.iterdir()):
        raise ValueError("output_dir_not_empty")


def _write_private_bytes(path: Path, value: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_private_json(path: Path, value: object) -> None:
    _write_private_bytes(path, _canonical_json_bytes(value))


def _git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _source_text(manifest: dict[str, Any]) -> str:
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("fixture_manifest_chapters_invalid")
    values: list[str] = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise ValueError("fixture_manifest_chapter_invalid")
        text = chapter.get("canonical_expected_text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("fixture_manifest_source_text_invalid")
        expected_digest = str(chapter.get("canonical_expected_text_sha256") or "")
        if _sha256_bytes(text.encode("utf-8")) != expected_digest:
            raise ValueError("fixture_manifest_source_text_digest_mismatch")
        values.append(text)
    return "\n".join(values)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9\u00c0-\u024f]{2,}", value.lower())


def _extract_sample(*, source: Path, output: Path) -> None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-t",
            "30",
            str(output),
        ],
        check=False,
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError("sample_extract_failed")


def _safe_used_credit(response: dict[str, object]) -> dict[str, int]:
    record = response.get("aiRecord")
    if not isinstance(record, dict):
        return {}
    team_user = record.get("teamUser")
    if not isinstance(team_user, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("creditLimit", "usedCredit"):
        value = team_user.get(key)
        if type(value) is int and value >= 0:
            result[f"aiRecord.teamUser.{key}"] = value
    return result


def _result_text(provider: ProviderModule, response: dict[str, object]) -> str:
    record = response.get("aiRecord")
    if not isinstance(record, dict) or str(record.get("status") or "").strip().upper() != "SUCCESS":
        return ""
    detail = record.get("aiRecordDetail")
    if not isinstance(detail, dict):
        return ""
    # The documented feature result lives in resultObject. Do not choose
    # between two independently populated transcript-bearing fields because a
    # disagreement would make the scored transcript ambiguous.
    if detail.get("responseObject") not in (None, "", [], {}):
        return ""
    result_object = detail.get("resultObject")
    if not isinstance(result_object, list) or len(result_object) != 1:
        return ""
    return provider._onemin_transcript_text(result_object)


def run_recheck(
    *,
    m4b_path: Path,
    manifest_path: Path,
    provider: ProviderModule,
    expected_artifact_sha256: str,
    expected_manifest_sha256: str,
    expected_code_commit: str,
    paid_call_authorized: bool,
    generated_at: str | None = None,
) -> dict[str, object]:
    if paid_call_authorized is not True:
        raise ValueError("one_paid_stt_call_not_authorized")
    expected_artifact = str(expected_artifact_sha256 or "").strip().lower()
    expected_manifest = str(expected_manifest_sha256 or "").strip().lower()
    expected_commit = str(expected_code_commit or "").strip().lower()
    if not DIGEST_HEX_RE.fullmatch(expected_artifact):
        raise ValueError("expected_artifact_sha256_invalid")
    if not DIGEST_HEX_RE.fullmatch(expected_manifest):
        raise ValueError("expected_manifest_sha256_invalid")
    if not REVISION_RE.fullmatch(expected_commit):
        raise ValueError("expected_code_commit_invalid")
    head = _git_value("rev-parse", "HEAD")
    tree = _git_value("rev-parse", "HEAD^{tree}")
    dirty = bool(_git_value("status", "--porcelain=v1", "--untracked-files=all"))
    if head != expected_commit or not REVISION_RE.fullmatch(tree) or dirty:
        raise ValueError("source_state_not_exact_and_clean")
    m4b_bytes = _read_regular_file(m4b_path, max_bytes=MAX_M4B_BYTES, reason="m4b")
    manifest_bytes = _read_regular_file(
        manifest_path, max_bytes=MAX_MANIFEST_BYTES, reason="fixture_manifest"
    )
    if _sha256_bytes(m4b_bytes) != expected_artifact:
        raise ValueError("artifact_sha256_mismatch")
    if _sha256_bytes(manifest_bytes) != expected_manifest:
        raise ValueError("fixture_manifest_sha256_mismatch")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("fixture_manifest_json_invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("fixture_manifest_json_invalid")
    if manifest.get("contract_name") != FIXTURE_CONTRACT_NAME:
        raise ValueError("fixture_manifest_contract_invalid")
    if (
        manifest.get("language") != FIXTURE_LANGUAGE
        or manifest.get("language_tag") != FIXTURE_LANGUAGE_TAG
    ):
        raise ValueError("fixture_manifest_language_invalid")
    source_text = _source_text(manifest)
    source_tokens = _tokens(source_text)
    source_token_set = set(source_tokens)
    language = FIXTURE_LANGUAGE

    upload_attempts = 0
    inference_attempts = 0
    transcript = ""
    used_credit: dict[str, int] = {}
    safe_error = ""
    sample_sha256 = ""
    sample_size = 0
    keys = provider._pocket_onemin_api_keys()
    if not keys or not str(keys[0] or "").strip():
        safe_error = "onemin_api_key_unavailable"
    else:
        api_key = str(keys[0]).strip()
        try:
            with tempfile.TemporaryDirectory(prefix="ea-audiobook-stt-recheck-") as temp:
                source_copy = Path(temp) / "canary-source.m4b"
                source_copy.write_bytes(m4b_bytes)
                source_copy.chmod(0o600)
                sample_path = Path(temp) / "canary-sample.wav"
                _extract_sample(source=source_copy, output=sample_path)
                sample_bytes = sample_path.read_bytes()
                sample_sha256 = _sha256_bytes(sample_bytes)
                sample_size = len(sample_bytes)
                upload_attempts = 1
                uploaded = provider._onemin_asset_upload(
                    api_key=api_key,
                    filename="audiobook-canary-sample.wav",
                    content_type="audio/wav",
                    payload=sample_bytes,
                )
                asset = uploaded.get("asset")
                file_content = uploaded.get("fileContent")
                audio_path = ""
                if isinstance(file_content, dict):
                    audio_path = str(file_content.get("path") or "").strip()
                if not audio_path and isinstance(asset, dict):
                    audio_path = str(asset.get("key") or "").strip()
                if not audio_path:
                    raise RuntimeError("onemin_asset_missing_path")
                inference_attempts = 1
                response = provider._onemin_speech_to_text(
                    api_key=api_key,
                    audio_path=audio_path,
                    language=language,
                )
                used_credit = _safe_used_credit(response)
                transcript = _result_text(provider, response)
                if not transcript:
                    raise RuntimeError("onemin_transcript_not_authoritative")
        except Exception as exc:
            safe_error = type(exc).__name__

    transcript_tokens = _tokens(transcript)
    transcript_unique = set(transcript_tokens)
    token_overlap = (
        sum(1 for token in transcript_tokens if token in source_token_set)
        / float(len(transcript_tokens))
        if transcript_tokens
        else 0.0
    )
    unique_overlap = (
        len(transcript_unique & source_token_set) / float(len(transcript_unique))
        if transcript_unique
        else 0.0
    )
    final_head = _git_value("rev-parse", "HEAD")
    final_tree = _git_value("rev-parse", "HEAD^{tree}")
    final_dirty = bool(
        _git_value("status", "--porcelain=v1", "--untracked-files=all")
    )
    source_state_stable = (
        final_head == head
        and final_tree == tree
        and final_head == expected_commit
        and not final_dirty
    )
    if not source_state_stable and not safe_error:
        safe_error = "source_state_changed_during_recheck"
    passed = (
        not safe_error
        and len(transcript_tokens) >= 8
        and token_overlap >= 0.55
        and unique_overlap >= 0.55
        and upload_attempts == 1
        and inference_attempts == 1
    )
    return {
        "contract_name": CONTRACT_NAME,
        # This receipt closes only the machine STT sub-gate. Human listening,
        # normal intake, delivery, and playback acceptance remain outstanding,
        # so its overall status must never become pass.
        "status": "review_required",
        "machine_stt_status": "pass" if passed else "fail",
        "generated_at": generated_at or _utc_now(),
        "definition_of_done_met": False,
        "machine_stt_gate_passed": passed,
        "human_listened_acceptance_present": False,
        "delivery_authorized": False,
        "one_paid_stt_call_authorized": True,
        "code_commit": head if REVISION_RE.fullmatch(head) else "",
        "code_tree": tree if REVISION_RE.fullmatch(tree) else "",
        "code_worktree_clean": not final_dirty,
        "source_state_stable_across_paid_boundary": source_state_stable,
        "artifact_sha256": _sha256_bytes(m4b_bytes),
        "artifact_size_bytes": len(m4b_bytes),
        "fixture_manifest_sha256": _sha256_bytes(manifest_bytes),
        "input_bindings_match_expected": True,
        "fixture_contract": FIXTURE_CONTRACT_NAME,
        "source_language": FIXTURE_LANGUAGE,
        "source_language_tag": FIXTURE_LANGUAGE_TAG,
        "source_text_sha256": _sha256_bytes(source_text.encode("utf-8")),
        "source_token_count": len(source_tokens),
        "sample": {
            "sha256": sample_sha256,
            "size_bytes": sample_size,
            "extractor_seek_mode": "full_short_canary_audio_stream",
            "persisted": False,
        },
        "transcriber": "1min.ai/whisper-1",
        "transcription_status": "transcribed" if transcript else "unavailable",
        "transcription_error_class": safe_error,
        "transcript_sha256": _sha256_bytes(transcript.encode("utf-8")) if transcript else "",
        "transcript_token_count": len(transcript_tokens),
        "book_token_overlap": round(token_overlap, 4),
        "book_unique_token_overlap": round(unique_overlap, 4),
        "minimum_book_token_overlap": 0.55,
        "minimum_transcript_tokens": 8,
        "threshold_lowered": False,
        "provider_usage": {
            "asset_upload_network_request_count": upload_attempts,
            "stt_inference_network_request_count": inference_attempts,
            "maximum_asset_upload_network_request_count": 1,
            "maximum_stt_inference_network_request_count": 1,
            "credit_snapshot": used_credit,
        },
        "privacy": {
            "api_key_exposed": False,
            "raw_provider_ids_exposed": False,
            "raw_provider_response_persisted": False,
            "raw_transcript_persisted": False,
            "absolute_host_paths_exposed": False,
        },
        "side_effects": {
            "audio_regenerated": False,
            "unmixr_request": False,
            "audiobookshelf_import": False,
            "public_share": False,
            "telegram_or_whatsapp_send": False,
            "deploy_or_container_change": False,
            "webhook": False,
        },
    }


def write_bundle(*, output_dir: Path, receipt: dict[str, object]) -> dict[str, object]:
    _require_private_output_dir(output_dir)
    validation_path = output_dir / "validation.json"
    _write_private_json(validation_path, receipt)
    validation_bytes = validation_path.read_bytes()
    inventory = {
        "contract_name": INVENTORY_CONTRACT_NAME,
        "entry_count": 1,
        "entries": [
            {
                "path": "validation.json",
                "classification": "supplemental_stt_validation_receipt",
                "mode": "0600",
                "size_bytes": len(validation_bytes),
                "sha256": _sha256_bytes(validation_bytes),
            }
        ],
    }
    inventory_path = output_dir / "INVENTORY.json"
    _write_private_json(inventory_path, inventory)
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = _sha256_bytes(inventory_bytes)
    _write_private_bytes(
        output_dir / "INVENTORY.sha256",
        f"{inventory_sha256}  INVENTORY.json\n".encode("ascii"),
    )
    pointer = {
        "contract_name": POINTER_CONTRACT_NAME,
        "status": "review_required",
        "machine_stt_gate_passed": receipt.get("machine_stt_gate_passed") is True,
        "code_commit": receipt.get("code_commit"),
        "artifact_sha256": receipt.get("artifact_sha256"),
        "portable_relative_paths_only": True,
        "absolute_host_paths_exposed": False,
        "raw_provider_ids_exposed": False,
        "raw_provider_response_persisted": False,
        "raw_transcript_persisted": False,
        "inventory": {
            "path": "INVENTORY.json",
            "sha256": inventory_sha256,
        },
        "validation": {
            "path": "validation.json",
            "sha256": _sha256_bytes(validation_bytes),
        },
    }
    _write_private_json(output_dir / "POINTER.json", pointer)
    return pointer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m4b", required=True, type=Path)
    parser.add_argument("--fixture-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected-artifact-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-code-commit", required=True)
    parser.add_argument(
        "--authorize-one-paid-stt-call",
        action="store_true",
        help="Authorize at most one 1min asset upload and one STT inference.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        # Validate the evidence destination before any provider call so an
        # invalid or non-durable directory cannot consume credit and then lose
        # the resulting receipt.
        _require_private_output_dir(args.output_dir)
        from app.product import service as provider

        receipt = run_recheck(
            m4b_path=args.m4b,
            manifest_path=args.fixture_manifest,
            provider=provider,
            expected_artifact_sha256=args.expected_artifact_sha256,
            expected_manifest_sha256=args.expected_manifest_sha256,
            expected_code_commit=args.expected_code_commit,
            paid_call_authorized=bool(args.authorize_one_paid_stt_call),
        )
        pointer = write_bundle(output_dir=args.output_dir, receipt=receipt)
    except Exception as exc:
        result = {
            "contract_name": POINTER_CONTRACT_NAME,
            "status": "review_required",
            "safe_error_class": type(exc).__name__,
            "network_request_count_unknown": True,
            "delivery_authorized": False,
        }
        print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
        return 2
    print(json.dumps(pointer, indent=2 if args.pretty else None, sort_keys=True))
    # Exit success means the bounded operation and machine sub-gate passed; the
    # emitted overall status intentionally remains review_required.
    return 0 if pointer.get("machine_stt_gate_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
