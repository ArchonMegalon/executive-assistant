from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any

from app.domain.outreach.recipient_basis import recipient_basis_policy


CONTRACT_NAME = "ea.sendr_campaign_packet.v1"

CAMPAIGN_TYPES = frozenset(
    {
        "FOUNDER_DEMO_OUTREACH",
        "TRUST_AND_APPROVAL_CAMPAIGN",
        "GOOGLE_WORKSPACE_WORKFLOW",
        "TRIAL_ONBOARDING_NUDGE",
        "PARTNER_OUTREACH",
        "CONTENT_LAUNCH_PROMOTION",
    }
)

DEFAULT_TARGET_AUDIENCE = {
    "FOUNDER_DEMO_OUTREACH": "founders and operators with Gmail/Calendar overload",
    "TRUST_AND_APPROVAL_CAMPAIGN": "privacy-conscious operators who need review-before-send",
    "GOOGLE_WORKSPACE_WORKFLOW": "Gmail-heavy executives and operators",
    "TRIAL_ONBOARDING_NUDGE": "warm leads and trial users with a clear relationship basis",
    "PARTNER_OUTREACH": "workflow consultants, operator communities, and integration partners",
    "CONTENT_LAUNCH_PROMOTION": "contacts with an approved basis for public EA content updates",
}

ALLOWED_CLAIMS = (
    "EA is built around Gmail and Calendar first.",
    "EA produces a morning brief, queue, commitments, drafts, and evidence.",
    "Sensitive outbound actions remain review-gated.",
    "EA drafts and organizes; the operator approves sensitive actions.",
)

FORBIDDEN_CLAIMS = (
    "EA sends autonomously without review.",
    "EA replaces the executive.",
    "EA replaces a human assistant.",
    "EA reads all systems by default.",
    "EA is a broad multichannel agent platform on first visit.",
    "EA guarantees inbox zero.",
    "EA guarantees perfect follow-up.",
)

DESIGN_SOURCE_PATHS = (
    ".codex-design/ea/VISION.md",
    ".codex-design/ea/FIRST_VALUE_JOURNEY.md",
    ".codex-design/ea/COPY_PRINCIPLES.md",
    ".codex-design/ea/LTD_INTEGRATION_MAP.md",
)


def _repo_root() -> Path:
    resolved = Path(__file__).resolve()
    for candidate in (resolved.parents[3], resolved.parents[2], Path.cwd(), Path("/app")):
        if (candidate / ".codex-design" / "ea").is_dir() or (candidate / "LTDs.md").is_file():
            return candidate
    return resolved.parents[3]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sendr_source_material(root: Path | None = None) -> list[dict[str, str]]:
    resolved_root = root or _repo_root()
    rows: list[dict[str, str]] = []
    for relative_path in DESIGN_SOURCE_PATHS:
        path = resolved_root / relative_path
        if not path.is_file():
            continue
        rows.append(
            {
                "path": relative_path,
                "sha256": _sha256_file(path),
                "classification": "approved_public",
            }
        )
    return rows


def build_sendr_campaign_packet(
    *,
    campaign_type: str,
    packet_id: str,
    target_audience: str | None = None,
    expires_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    normalized_campaign_type = str(campaign_type or "").strip().upper()
    if normalized_campaign_type not in CAMPAIGN_TYPES:
        raise ValueError(f"unsupported_sendr_campaign_type:{campaign_type}")
    normalized_packet_id = str(packet_id or "").strip()
    if not normalized_packet_id:
        raise ValueError("sendr_packet_id_required")
    expiry = expires_at or (datetime.now(UTC) + timedelta(days=14)).isoformat().replace("+00:00", "Z")
    policy = recipient_basis_policy()
    return {
        "contract_name": CONTRACT_NAME,
        "packet_id": normalized_packet_id,
        "campaign_type": normalized_campaign_type,
        "project": "executive_assistant",
        "owner": "ea_growth",
        "target_audience": target_audience or DEFAULT_TARGET_AUDIENCE[normalized_campaign_type],
        "jurisdiction_policy": "b2b_outreach_review_required",
        "provider": "sendr",
        "license_tier": "AppSumo Tier 4",
        "source_material": sendr_source_material(root),
        "allowed_claims": list(ALLOWED_CLAIMS),
        "forbidden_claims": list(FORBIDDEN_CLAIMS),
        "recipient_policy": {
            "allowed_recipient_basis": policy["allowed_recipient_basis"],
            "forbidden_recipient_basis": policy["forbidden_recipient_basis"],
        },
        "channels": {
            "email": True,
            "linkedin": True,
            "whatsapp": False,
        },
        "sendr_features_allowed": {
            "lead_finder": True,
            "data_enrichment": True,
            "personalized_pages": True,
            "dynamic_video": True,
            "sequencer": True,
            "whatsapp": False,
        },
        "human_review_required": True,
        "direct_send_allowed": False,
        "auto_reply_allowed": False,
        "private_workspace_data_allowed": False,
        "max_contacts": 50,
        "expires_at": expiry,
    }
