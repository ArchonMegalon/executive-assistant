#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    return resolve_source_state_head(ROOT)


def _git_dirty() -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return True
    return bool(proc.stdout.strip()) if proc.returncode == 0 else True


def _source_tree_fingerprint() -> str:
    generated_prefixes = (
        ".codex-design/product/",
        ".codex-studio/published/",
    )
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    digest = hashlib.sha256()
    for relpath in sorted(line.strip() for line in proc.stdout.splitlines() if line.strip()):
        if relpath.startswith(generated_prefixes):
            continue
        path = ROOT / relpath
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_local_base_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in ("://127.0.0.1", "://localhost", "://0.0.0.0", "://[::1]"))


def build_receipt(args: argparse.Namespace) -> dict[str, object]:
    source_git_head = _git_head()
    checks = {
        "actual_device_checked": bool(args.actual_device_checked),
        "actual_speaker_checked": bool(args.actual_speaker_checked),
        "first_syllable_not_clipped": bool(args.first_syllable_not_clipped),
        "intelligibility_confirmed": bool(args.intelligibility_confirmed),
        "answer_text_fallback_visible": bool(args.answer_text_fallback_visible),
        "no_internet_search_confirmed": bool(args.no_internet_search_confirmed),
    }
    failed_codes = [f"{key}_missing" for key, value in checks.items() if value is not True]
    if not str(args.reviewer or "").strip():
        failed_codes.append("reviewer_missing")
    attestation_id = str(getattr(args, "manual_attestation_id", "") or "").strip()
    attestation_signed_at = str(getattr(args, "manual_attestation_signed_at", "") or "").strip()
    if not attestation_id:
        failed_codes.append("manual_attestation_id_missing")
    if not attestation_signed_at:
        failed_codes.append("manual_attestation_signed_at_missing")
    if bool(args.require_public_origin) and _is_local_base_url(str(args.base_url or "")):
        failed_codes.append("public_origin_required")
    dirty_worktree = _git_dirty()
    if dirty_worktree:
        failed_codes.append("dirty_worktree")
    status = "pass" if not failed_codes else "fail"
    return {
        "contract_name": "ea.memorial_room_audio_public_origin",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_memorial_room_audio_receipt.py",
        "proof_type": "manual_room_attestation",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
        "source_tree_fingerprint": _source_tree_fingerprint(),
        "dirty_worktree": dirty_worktree,
        "status": status,
        "base_url": str(args.base_url or "").rstrip("/"),
        "slug": str(args.slug or "manfred"),
        "require_public_origin": bool(args.require_public_origin),
        "reviewer": str(args.reviewer or "").strip(),
        "device_label": str(args.device_label or "").strip(),
        "speaker_label": str(args.speaker_label or "").strip(),
        "room_label": str(args.room_label or "").strip(),
        "checks": checks,
        "manual_attestation": {
            "attestation_id": attestation_id,
            "signed_at": attestation_signed_at,
            "source": str(getattr(args, "manual_attestation_source", "") or "operator_room_review").strip()
            or "operator_room_review",
            "ci_must_not_auto_assert": True,
        },
        "notes": str(args.notes or "").strip(),
        "failed_codes": failed_codes,
        "gold_claim_allowed": status == "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the manual room/device playback receipt for memorial public-origin gold.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--device-label", default="")
    parser.add_argument("--speaker-label", default="")
    parser.add_argument("--room-label", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--manual-attestation-id", default="")
    parser.add_argument("--manual-attestation-signed-at", default="")
    parser.add_argument("--manual-attestation-source", default="operator_room_review")
    parser.add_argument("--require-public-origin", action="store_true")
    parser.add_argument("--actual-device-checked", action="store_true")
    parser.add_argument("--actual-speaker-checked", action="store_true")
    parser.add_argument("--first-syllable-not-clipped", action="store_true")
    parser.add_argument("--intelligibility-confirmed", action="store_true")
    parser.add_argument("--answer-text-fallback-visible", action="store_true")
    parser.add_argument("--no-internet-search-confirmed", action="store_true")
    args = parser.parse_args()

    receipt = build_receipt(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "output": str(output), "failed_codes": receipt["failed_codes"]}, ensure_ascii=False))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
