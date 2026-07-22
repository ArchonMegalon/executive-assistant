from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import time
from typing import Any


MANFRED_REALTIME_READINESS_CONTRACT = "ea.manfred_realtime_conversation_readiness.v1"
MANFRED_REALTIME_READINESS_GENERATOR = (
    "ea/scripts/materialize_manfred_realtime_conversation_readiness.py"
)
MEMORIAL_VOICE_RELEASE_MAX_AGE_SECONDS = 24 * 60 * 60


def _blocked(reason: str, *, receipt_status: str = "") -> dict[str, object]:
    return {
        "allowed": False,
        "status": "blocked",
        "reason": reason,
        "receipt_status": receipt_status,
    }


def _parse_timestamp(value: object) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _sha256(value: object) -> bool:
    raw = str(value or "").strip().lower()
    return len(raw) == 64 and all(character in "0123456789abcdef" for character in raw)


def evaluate_memorial_voice_release(
    *,
    slug: str,
    receipt_path: str | Path,
    now: float | None = None,
    max_age_seconds: float = MEMORIAL_VOICE_RELEASE_MAX_AGE_SECONDS,
) -> dict[str, object]:
    """Evaluate the final production voice/realtime release boundary.

    The aggregate readiness receipt intentionally stops at review readiness. A
    production runtime may enable speech only after a separate human-reviewed
    transition has added the explicit, digest-bound enablement fields checked
    here. Missing or ambiguous evidence always blocks.
    """

    normalized_slug = str(slug or "").strip().lower()
    if normalized_slug != "manfred":
        return _blocked("release_receipt_not_configured")

    path = Path(receipt_path)
    try:
        target_stat = path.lstat()
    except OSError:
        return _blocked("release_receipt_missing")
    if stat.S_ISLNK(target_stat.st_mode):
        return _blocked("release_receipt_symlink")
    if not stat.S_ISREG(target_stat.st_mode):
        return _blocked("release_receipt_not_regular")
    if stat.S_IMODE(target_stat.st_mode) & 0o077:
        return _blocked("release_receipt_permissions_unsafe")

    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _blocked("release_receipt_invalid")
    if not isinstance(payload, dict):
        return _blocked("release_receipt_invalid")

    receipt_status = str(payload.get("status") or "").strip()
    if payload.get("contract_name") != MANFRED_REALTIME_READINESS_CONTRACT:
        return _blocked("release_receipt_contract_mismatch", receipt_status=receipt_status)
    if payload.get("generated_by") != MANFRED_REALTIME_READINESS_GENERATOR:
        return _blocked("release_receipt_generator_mismatch", receipt_status=receipt_status)
    if str(payload.get("memorial_slug") or "").strip().lower() != normalized_slug:
        return _blocked("release_receipt_slug_unbound", receipt_status=receipt_status)

    generated_at = _parse_timestamp(payload.get("generated_at"))
    checked_at = time.time() if now is None else float(now)
    if generated_at is None or generated_at > checked_at + 60:
        return _blocked("release_receipt_timestamp_invalid", receipt_status=receipt_status)
    if max_age_seconds <= 0 or checked_at - generated_at > max_age_seconds:
        return _blocked("release_receipt_stale", receipt_status=receipt_status)

    if payload.get("evidence_source") != "receipt_aggregation":
        return _blocked("release_receipt_evidence_unverified", receipt_status=receipt_status)
    if receipt_status != "ready_for_realtime_conversation_review":
        return _blocked("release_prerequisites_blocked", receipt_status=receipt_status)
    if payload.get("ready_for_realtime_conversation_review") is not True:
        return _blocked("release_prerequisites_blocked", receipt_status=receipt_status)
    if list(payload.get("blocked_checks") or []):
        return _blocked("release_prerequisites_blocked", receipt_status=receipt_status)

    explicit_claims = (
        "runtime_enablement_allowed",
        "voice_authority_verified",
        "realtime_conversation_claim_allowed",
        "premium_spoken_claim_allowed",
    )
    if any(payload.get(field) is not True for field in explicit_claims):
        return _blocked("release_human_acceptance_missing", receipt_status=receipt_status)

    digest_bindings = (
        "operator_acceptance_receipt_sha256",
        "voice_authority_receipt_sha256",
        "deployed_source_sha256",
    )
    if any(not _sha256(payload.get(field)) for field in digest_bindings):
        return _blocked("release_digest_binding_missing", receipt_status=receipt_status)

    return {
        "allowed": True,
        "status": "released",
        "reason": "",
        "receipt_status": receipt_status,
    }
