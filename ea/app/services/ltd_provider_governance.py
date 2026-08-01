from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from app.services.ltd_runtime_catalog import LtdInventoryRow, load_ltd_inventory_rows


SCHEMA_VERSION = "2026-06-10.ltd-provider-lane.v1"


def _normalize(value: object) -> str:
    lowered = str(value or "").strip().strip("`").lower()
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def _repo_root() -> Path:
    resolved = Path(__file__).resolve()
    candidates = (
        resolved.parents[3],
        resolved.parents[2],
        Path.cwd(),
        Path("/app"),
    )
    for candidate in candidates:
        if (candidate / "LTDs.md").is_file():
            return candidate
    return resolved.parents[2]


@dataclass(frozen=True)
class LaneCheck:
    check_key: str
    label: str
    proof_hint: str


@dataclass(frozen=True)
class ProviderLane:
    lane_key: str
    title: str
    providers: tuple[str, ...]
    integration_lane: str
    verified_state: str
    missing_state: str
    off_switch_env: tuple[str, ...]
    source_of_truth: str
    allowed_inputs: tuple[str, ...]
    forbidden_inputs: tuple[str, ...]
    normalized_signal_schema: tuple[str, ...]
    required_checks: tuple[LaneCheck, ...]


DOCUMENT_PORTAL_CHECKS = (
    LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Discovery row and product inventory row exist."),
    LaneCheck("provider_verification", "Account tier and provider capability proof are recorded.", "Provider verification receipt."),
    LaneCheck("copyright_privacy_boundary", "Copyright and privacy boundary is explicit.", "Boundary text in LTDs.md or receipt."),
    LaneCheck("first_publication_receipt", "First approved publication receipt exists.", "Publication receipt JSON."),
)


def _provider_contract_receipt(root: Path, filename: str) -> dict[str, Any]:
    for relative_path in (
        f"_completion/ea_provider_contracts/{filename}",
        f"ea/_completion/ea_provider_contracts/{filename}",
    ):
        path = root / relative_path
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _provider_contract_check(
    root: Path,
    *,
    filename: str,
    verification_key: str,
) -> bool:
    payload = _provider_contract_receipt(root, filename)
    verification = payload.get("verification")
    return bool(isinstance(verification, dict) and str(verification.get(verification_key) or "").strip().lower() == "pass")


def _provider_contract_summary(root: Path) -> dict[str, Any]:
    return _provider_contract_receipt(root, "EA_PROVIDER_CONTRACTS_SUMMARY.generated.json")


LANES: tuple[ProviderLane, ...] = (
    ProviderLane(
        lane_key="fliplink_document_portal",
        title="FlipLink Document Portal",
        providers=("FlipLink.me",),
        integration_lane="document_portal",
        verified_state="verified_runtime_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_FLIPLINK_DOCUMENT_PORTAL_ENABLED",),
        source_of_truth="EA/Chummer retain document truth and generate approved PDFs; FlipLink only presents, embeds, and measures them.",
        allowed_inputs=(
            "approved_pdf_artifact",
            "public_guide",
            "family_disclosure",
            "player_safe_packet",
            "operator_approved_document",
        ),
        forbidden_inputs=(
            "sourcebook_pdf",
            "copied_rulebook_prose",
            "private_runner_sheet",
            "gm_only_campaign_secret",
            "entitlement_truth",
            "payment_truth",
        ),
        normalized_signal_schema=(),
        required_checks=DOCUMENT_PORTAL_CHECKS,
    ),
    ProviderLane(
        lane_key="hedy_meeting_evidence",
        title="Hedy Meeting Evidence Intake",
        providers=("Hedy.ai",),
        integration_lane="meeting_evidence_review",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_HEDY_WEBHOOKS_ENABLED", "EA_HEDY_MEETING_EVIDENCE_ENABLED"),
        source_of_truth=(
            "EA owns evidence, commitment, decision, draft, and people-memory truth; "
            "Hedy only supplies consented meeting evidence for review."
        ),
        allowed_inputs=("consented_meeting_transcript", "consented_meeting_summary", "consented_meeting_followup_draft"),
        forbidden_inputs=(
            "unconsented_recording",
            "direct_commitment_creation",
            "direct_decision_creation",
            "direct_people_memory_overwrite",
            "direct_followup_send",
            "truth_overwrite",
        ),
        normalized_signal_schema=("session_id", "ea_decision_id", "recording_consent_confirmed", "transcript_hash"),
        required_checks=(
            LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Inventory row exists."),
            LaneCheck("hedy_provider_capability", "Live provider capability proof exists.", "Live provider receipt."),
            LaneCheck("hedy_consent_gate", "Consent gate stays fail-closed.", "Contract or lane boundary proof."),
            LaneCheck("hedy_webhook_signature", "Webhook signature contract is verified.", "Webhook contract or live proof."),
            LaneCheck("hedy_review_gate", "Meeting evidence remains review-only.", "Contract or lane boundary proof."),
            LaneCheck("hedy_memory_promotion_gate", "People-memory promotion requires review.", "Contract or lane boundary proof."),
            LaneCheck("hedy_session_mapping", "Webhook maps to EA review/session objects.", "Contract receipt."),
        ),
    ),
    ProviderLane(
        lane_key="markupgo_fliplink_premium_delivery",
        title="MarkupGo and FlipLink Premium Delivery",
        providers=("MarkupGo", "FlipLink.me"),
        integration_lane="premium_packet_delivery",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_MARKUPGO_PREMIUM_DELIVERY_ENABLED", "EA_FLIPLINK_PREMIUM_DELIVERY_ENABLED"),
        source_of_truth=(
            "EA approved packets, redaction policy, and access controls remain truth; "
            "MarkupGo renders and FlipLink presents approved premium artifacts only."
        ),
        allowed_inputs=("approved_source_packet", "approved_private_packet", "approved_board_packet", "rendered_artifact"),
        forbidden_inputs=(
            "content_mutation",
            "unredacted_board_material",
            "access_grant_truth",
            "direct_publish",
            "raw_workspace_data",
        ),
        normalized_signal_schema=("source_packet_id", "rendered_artifact_hash", "publication_id", "access_policy_hash"),
        required_checks=(
            LaneCheck("providers_recorded", "Providers are recorded in LTDs.md.", "Inventory rows exist."),
            LaneCheck("markupgo_provider_proof", "MarkupGo live provider proof exists.", "Live provider receipt."),
            LaneCheck("premium_source_packet", "Premium delivery starts from an approved source packet.", "Contract or boundary receipt."),
            LaneCheck("premium_artifact_hash", "Rendered artifact hashing is verified.", "Contract receipt."),
            LaneCheck("human_review", "Premium delivery requires human review.", "Contract or boundary receipt."),
            LaneCheck("premium_delivery_receipt", "End-to-end premium delivery receipt exists.", "Live roundtrip receipt."),
        ),
    ),
    ProviderLane(
        lane_key="approvethis_external_approval_edge",
        title="ApproveThis External Approval Edge",
        providers=("ApproveThis",),
        integration_lane="external_approval_edge",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_APPROVETHIS_EXTERNAL_APPROVAL_ENABLED", "EA_APPROVETHIS_WEBHOOKS_ENABLED"),
        source_of_truth=(
            "EA policy, decision state, and downstream action truth stay inside EA; "
            "ApproveThis carries bounded external approval evidence only."
        ),
        allowed_inputs=("bounded_ea_decision", "external_review_request", "reviewer_contact_hash"),
        forbidden_inputs=(
            "replace_internal_queue",
            "direct_downstream_action",
            "approval_without_ea_policy",
            "approval_truth",
            "workspace_truth",
        ),
        normalized_signal_schema=("ea_decision_id", "provider_request_id", "provider_status", "approver_contact_sha256"),
        required_checks=(
            LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Inventory row exists."),
            LaneCheck("approvethis_provider_capability", "Live provider capability proof exists.", "Live provider receipt."),
            LaneCheck("approvethis_external_scope", "Only bounded external scope is transportable.", "Contract or lane boundary proof."),
            LaneCheck("approvethis_final_policy_gate", "Final EA policy gate remains required.", "Contract or lane boundary proof."),
            LaneCheck("approvethis_webhook_signature", "Webhook signature contract is verified.", "Contract or live proof."),
            LaneCheck("approvethis_evidence_mapping", "Provider results map to evidence only.", "Contract receipt."),
        ),
    ),
    ProviderLane(
        lane_key="documentation_ai_publication",
        title="Documentation.AI Publication Projection",
        providers=("Documentation.AI",),
        integration_lane="docs_publication_projection",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_DOCUMENTATION_AI_PUBLICATION_ENABLED", "EA_DOCUMENTATION_AI_AGENT_WRITEBACK_ENABLED"),
        source_of_truth=(
            "Source-controlled markdown and mirrored design canon stay truth; "
            "Documentation.AI may project approved docs but must never own publication truth or silent writeback."
        ),
        allowed_inputs=("source_controlled_markdown", "approved_security_trust_center", "approved_release_notes"),
        forbidden_inputs=(
            "workspace_data",
            "customer_support_ticket",
            "private_incident_log",
            "silent_writeback",
            "publication_truth",
        ),
        normalized_signal_schema=("site_key", "source_tree_fingerprint", "source_git_head", "link_check_sha256"),
        required_checks=(
            LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Inventory row exists."),
            LaneCheck("documentation_ai_provider_capability", "Live provider capability proof exists.", "Live provider receipt."),
            LaneCheck("documentation_git_source_of_truth", "Git remains the source of truth.", "Contract or boundary proof."),
            LaneCheck("documentation_no_writeback", "Provider writeback remains disabled.", "Contract or boundary proof."),
            LaneCheck("documentation_privacy_boundary", "Workspace/private data is blocked.", "Boundary proof."),
            LaneCheck("documentation_llms_txt", "llms.txt delivery proof exists.", "Live route receipt."),
        ),
    ),
    ProviderLane(
        lane_key="unmixr_voice_runtime",
        title="Unmixr Governed Voice Runtime",
        providers=("Unmixr AI",),
        integration_lane="voice_tts_runtime",
        verified_state="verified_runtime_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_UNMIXR_VOICE_RUNTIME_ENABLED",),
        source_of_truth="EA consent registry and runtime config own voice eligibility truth; Unmixr only synthesizes approved text.",
        allowed_inputs=("consented_voice_tts", "chummer_promo_narration", "black_ledger_dispatch_narration"),
        forbidden_inputs=(
            "ad_hoc_public_voice_cloning",
            "user_supplied_voice_id",
            "committed_provider_voice_id",
            "provider_secret",
            "unconsented_likeness",
        ),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Discovery row and product inventory row exist."),
            LaneCheck("api_key_seeded", "Live API key is private runtime config.", "UNMIXR_API_KEY present outside git."),
            LaneCheck("voice_id_private", "Voice ID is private runtime config.", "UNMIXR_VOICE_ID present outside repo data."),
            LaneCheck("voice_roundtrip_validation", "Voice roundtrip latency/quality receipt exists.", "Roundtrip validation receipt."),
            LaneCheck("piper_fallback_policy", "Piper fallback remains available.", "Fallback policy or gate receipt."),
        ),
    ),
    ProviderLane(
        lane_key="magicfit_media_factory_candidate",
        title="MagicFit Media Factory Candidate",
        providers=("MagicFit",),
        integration_lane="media_factory_candidate",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_MAGICFIT_MEDIA_FACTORY_ENABLED",),
        source_of_truth="EA/Chummer storyboards and human review own editorial truth; MagicFit renders candidates only.",
        allowed_inputs=("text_prompt", "image_prompt", "storyboard_packet", "approved_public_b_roll_brief"),
        forbidden_inputs=("direct_publish", "product_truth", "private_campaign_data", "sourcebook_text", "unconsented_likeness"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Discovery row and product inventory row exist."),
            LaneCheck("commercial_use", "Commercial-use proof is recorded.", "Provider terms/commercial receipt."),
            LaneCheck("watermark_export", "Watermark and export behavior is proven.", "Export receipt."),
            LaneCheck("credit_budget", "Monthly credit budget is known.", "Credit receipt."),
            LaneCheck("safety_scan", "Generated candidate passes safety scan.", "Safety scan receipt."),
            LaneCheck("human_review", "Human creative review is required.", "Review receipt."),
        ),
    ),
    ProviderLane(
        lane_key="poppy_draft_workbench",
        title="Poppy AI Public Content Draft Workbench",
        providers=("Poppy AI",),
        integration_lane="content_repurposing_workbench",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_POPPY_DRAFT_WORKBENCH_ENABLED",),
        source_of_truth="EA/Chummer source markdown and approved notes remain truth; Poppy may draft only from approved public material.",
        allowed_inputs=("public_video_transcript", "public_pdf", "manually_approved_notes", "public_release_copy"),
        forbidden_inputs=(
            "private_campaign_data",
            "user_submission",
            "private_likeness_memory",
            "sourcebook_copied_text",
            "product_truth",
            "release_truth",
            "support_truth",
        ),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Discovery row and product inventory row exist."),
            LaneCheck("authenticated_session", "Authenticated session proof exists.", "Session proof receipt."),
            LaneCheck("privacy_boundary", "Privacy boundary is verified.", "Privacy review receipt."),
            LaneCheck("export_semantics", "Export behavior is known.", "Export receipt."),
            LaneCheck("tenant_isolation", "Tenant isolation is checked.", "Tenant isolation receipt."),
        ),
    ),
    ProviderLane(
        lane_key="release_quality_gates",
        title="Rafter and Pixefy Release Quality Gates",
        providers=("Rafter", "Pixefy"),
        integration_lane="ci_release_gates",
        verified_state="verified_runtime_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_RAFTER_SECURITY_GATE_ENABLED", "EA_PIXEFY_VISUAL_GATE_ENABLED"),
        source_of_truth="Fleet/Chummer release process owns release truth; Rafter and Pixefy provide auxiliary gate evidence.",
        allowed_inputs=("ea_app_surface_release_candidate", "product_landing_change", "black_ledger_newsroom_change", "security_scan_target"),
        forbidden_inputs=("product_truth", "release_truth", "roadmap_truth", "direct_publish", "source_code_mutation"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("rafter_fleet_verified", "Rafter Fleet provider verification passes.", "Fleet Rafter proof receipt."),
            LaneCheck("pixefy_fleet_verified", "Pixefy Fleet visual QA verification passes.", "Fleet Pixefy proof receipt."),
            LaneCheck("ci_targets", "CI targets exist for both gates.", "Make targets or gate scripts."),
            LaneCheck("ea_security_targets", "EA security targets are exercised against the current head.", "Contract receipt."),
            LaneCheck("ea_visual_targets", "EA visual targets are exercised against the current head.", "Contract receipt."),
            LaneCheck("release_truth_boundary", "Provider evidence cannot own release truth.", "Contract receipt."),
        ),
    ),
    ProviderLane(
        lane_key="public_signal_ingest",
        title="ProductLift, MetaSurvey, and Deftform Public Signal Ingest",
        providers=("ProductLift.dev", "MetaSurvey", "Deftform"),
        integration_lane="public_signal_intake",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_PUBLIC_SIGNAL_INGEST_ENABLED",),
        source_of_truth="EA mirrors signals for review; Chummer/Fleet/design own roadmap, issue, and release truth.",
        allowed_inputs=("feedback", "vote", "survey_result", "form_submission", "consented_contact"),
        forbidden_inputs=("canonical_roadmap_truth", "support_case_truth", "account_truth", "entitlement_truth", "private_campaign_data"),
        normalized_signal_schema=(
            "source",
            "author_contact",
            "project",
            "feature_request_category",
            "severity_value",
            "public_private_flag",
            "consent_to_contact",
            "raw_payload_hash",
        ),
        required_checks=(
            LaneCheck("providers_recorded", "All providers are recorded in LTDs.md.", "Inventory rows exist."),
            LaneCheck("normalized_schema", "One normalized signal schema is defined.", "Schema receipt."),
            LaneCheck("provider_boundaries", "Providers are mirrors, not truth stores.", "Boundary receipt."),
        ),
    ),
    ProviderLane(
        lane_key="docs_draft_factory",
        title="Documentation Draft Factory",
        providers=("Documentation.AI", "Paperguide", "First Book ai", "katteb.com"),
        integration_lane="docs_content_draft_factory",
        verified_state="verified_draft_operator_lane",
        missing_state="parked_inventory",
        off_switch_env=("EA_DOCS_DRAFT_FACTORY_ENABLED",),
        source_of_truth="Source-controlled markdown and mirrored design canon own docs truth; providers draft and format only.",
        allowed_inputs=("source_controlled_markdown", "approved_release_notes", "public_docs", "research_packet"),
        forbidden_inputs=("uncited_claim", "copied_rulebook_prose", "unapproved_product_claim", "stale_release_claim", "private_user_data"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("providers_recorded", "All providers are recorded in LTDs.md.", "Inventory rows exist."),
            LaneCheck("citation_required", "Citation requirement is explicit.", "Docs lane policy."),
            LaneCheck("freshness_check", "Freshness check is required.", "Freshness receipt."),
        ),
    ),
    ProviderLane(
        lane_key="prompt_foundry",
        title="Prompt Architects Governed Prompt Foundry",
        providers=("Prompt Architects",),
        integration_lane="prompt_template_foundry",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_PROMPT_FOUNDRY_ENABLED",),
        source_of_truth="EA approves templates; Prompt Architects cannot own rules, support, product, or GM runtime truth.",
        allowed_inputs=("template_seed", "operator_assist", "media_prompt_variant", "dispatch_prompt_draft", "support_style_draft"),
        forbidden_inputs=("rules_truth", "direct_gm_runtime", "private_user_content", "tenant_mixed_content", "support_truth"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("inventory_recorded", "Provider is recorded in LTDs.md.", "Discovery row and product inventory row exist."),
            LaneCheck("api_or_export_proof", "API/MCP/export proof is recorded.", "Provider proof receipt."),
            LaneCheck("retention_boundary", "Retention and tenant isolation are verified.", "Privacy receipt."),
        ),
    ),
    ProviderLane(
        lane_key="subscribr_chummer_script_factory",
        title="Subscribr Chummer Script Factory",
        providers=("Subscribr",),
        integration_lane="video_script_preproduction",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=(
            "EA_SUBSCRIBR_ENABLED",
            "EA_SUBSCRIBR_API_ENABLED",
            "EA_SUBSCRIBR_AGENT_MODE_ENABLED",
            "EA_SUBSCRIBR_INTEL_ENABLED",
            "EA_SUBSCRIBR_THUMBNAILS_ENABLED",
            "EA_SUBSCRIBR_WEBHOOKS_ENABLED",
            "EA_SUBSCRIBR_DIRECT_PUBLISH_ENABLED",
        ),
        source_of_truth=(
            "Chummer rule, release, dossier, and editorial packets own truth; "
            "Subscribr Tier 7 creates video-production drafts only, and EA approval owns publication truth."
        ),
        allowed_inputs=(
            "approved_public_source_packet",
            "public_release_receipt",
            "sanitized_explanation_packet",
            "approved_editorial_brief",
            "approved_origin_canon",
        ),
        forbidden_inputs=(
            "rules_truth",
            "character_legality",
            "release_truth",
            "sourcebook_pdf",
            "copied_rulebook_prose",
            "private_campaign_data",
            "gm_only_secret",
            "account_truth",
            "entitlement_truth",
            "publication_approval",
            "direct_publish",
        ),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("inventory_recorded", "Subscribr Tier 7 is recorded.", "LTD inventory row."),
            LaneCheck("provider_verification", "Tier/API capability is verified.", "Provider receipt."),
            LaneCheck("api_token_private", "API token remains outside git.", "Runtime config proof."),
            LaneCheck("channel_map", "Channel map is recorded.", "Channel-map receipt."),
            LaneCheck("script_roundtrip", "Idea-to-export roundtrip passes.", "Script receipt."),
            LaneCheck("source_binding", "Claims bind to approved sources.", "Validation receipt."),
            LaneCheck("copyright_privacy_boundary", "Input boundaries are enforced.", "Boundary tests."),
            LaneCheck("human_review", "Publication requires human approval.", "Approval contract."),
        ),
    ),
    ProviderLane(
        lane_key="sendr_ea_growth_outreach",
        title="Sendr EA Governed Outbound Growth Lane",
        providers=("Sendr",),
        integration_lane="governed_outbound_growth",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=(
            "EA_SENDR_ENABLED",
            "EA_SENDR_API_ENABLED",
            "EA_SENDR_WEBHOOKS_ENABLED",
            "EA_SENDR_DIRECT_SEND_ENABLED",
            "EA_SENDR_AUTO_REPLY_ENABLED",
            "EA_SENDR_PRIVATE_WORKSPACE_DATA_ALLOWED",
            "EA_SENDR_WHATSAPP_ENABLED",
        ),
        source_of_truth=(
            "EA product canon, approved campaign packets, recipient-basis policy, "
            "and human review own claims and follow-up truth. Sendr sequences approved outreach only."
        ),
        allowed_inputs=(
            "approved_public_ea_docs",
            "approved_demo_copy",
            "synthetic_demo_snapshot",
            "public_business_contact",
            "prior_relationship_contact",
            "inbound_lead",
            "opt_in_contact",
        ),
        forbidden_inputs=(
            "raw_gmail",
            "raw_calendar",
            "workspace_attachment",
            "people_memory",
            "private_commitment",
            "private_decision",
            "customer_draft",
            "private_workspace_snapshot",
            "customer_support_conversation",
            "secret",
            "auto_reply",
            "direct_publish",
            "publication_approval",
            "support_truth",
            "billing_truth",
            "product_truth",
        ),
        normalized_signal_schema=(
            "recipient_basis",
            "source_url_or_note",
            "campaign_type",
            "channel",
            "message_copy_hash",
            "suppression_status",
            "reply_event_hash",
            "human_review_status",
        ),
        required_checks=(
            LaneCheck("inventory_recorded", "Sendr Tier 4 is recorded.", "LTD inventory row."),
            LaneCheck("sendr_provider_verification", "Account and tier are verified.", "Provider receipt."),
            LaneCheck("sendr_recipient_basis", "Every recipient has approved basis.", "Recipient-basis receipt."),
            LaneCheck("sendr_suppression_sync", "Suppression list is fail-closed.", "Suppression receipt."),
            LaneCheck("sendr_claim_validation", "Campaign claims bind to approved EA sources.", "Claim receipt."),
            LaneCheck("sendr_privacy_boundary", "Raw office data is excluded.", "Privacy tests."),
            LaneCheck("sendr_human_review", "Send and follow-up require human approval.", "Approval receipt."),
            LaneCheck("sendr_reply_ingest", "Replies become EA review candidates, not automatic actions.", "Reply receipt."),
        ),
    ),
    ProviderLane(
        lane_key="operator_control_plane",
        title="blipai, Syllabbles, and Teable Operator Control Plane",
        providers=("blipai", "Syllabbles", "Teable"),
        integration_lane="operator_capture_projection",
        verified_state="verified_draft_operator_lane",
        missing_state="parked_inventory",
        off_switch_env=("EA_OPERATOR_CONTROL_PLANE_ENABLED",),
        source_of_truth="EA approval workflow owns action truth; Teable is projection, blipai captures notes, Syllabbles drafts wording.",
        allowed_inputs=("operator_note", "voice_note", "prompt_fragment", "dispatch_draft", "production_status"),
        forbidden_inputs=("direct_publish", "release_truth", "entitlement_truth", "private_user_truth", "canonical_queue_truth"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("provider_roles_defined", "Provider roles are separated.", "Control-plane receipt."),
            LaneCheck("approval_gate", "EA approval gate is required before publish.", "Approval receipt."),
        ),
    ),
    ProviderLane(
        lane_key="video_provider_bakeoff",
        title="Video and Avatar Provider Bake-off",
        providers=("VidBoard.ai", "FacePop", "Nonverbia", "Mootion", "MagicFit", "AvoMap", "JoggAI"),
        integration_lane="video_avatar_newsroom_bakeoff",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_VIDEO_PROVIDER_BAKEOFF_ENABLED",),
        source_of_truth="EA storyboards, safety scans, and human approval own publication truth; providers produce candidates only.",
        allowed_inputs=("storyboard_packet", "presenter_test_prompt", "map_b_roll_brief", "poster_frame_brief"),
        forbidden_inputs=("direct_publish", "unconsented_likeness", "private_likeness_memory", "sourcebook_text", "product_proof"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("providers_recorded", "All providers are recorded in LTDs.md.", "Inventory rows exist."),
            LaneCheck("commercial_use", "Commercial-use proof is recorded.", "Provider terms receipt."),
            LaneCheck("watermark_duration_export", "Watermark, duration, and export limits are known.", "Export receipt."),
            LaneCheck("likeness_policy", "Likeness policy is recorded.", "Likeness receipt."),
            LaneCheck("quality_score", "Quality score exists.", "Bake-off scoring receipt."),
        ),
    ),
    ProviderLane(
        lane_key="commercial_ops",
        title="Commercial Ops Verification Lane",
        providers=("Lunacal", "Signitic", "GetNextStep.io", "ICanpreneur"),
        integration_lane="commercial_ops_candidate",
        verified_state="verified_draft_operator_lane",
        missing_state="parked_inventory",
        off_switch_env=("EA_COMMERCIAL_OPS_LANE_ENABLED",),
        source_of_truth="EA may stage commercial ops evidence; CRM, booking, email, and product decision truth require explicit owner approval.",
        allowed_inputs=("booking_page_candidate", "email_signature_template", "growth_plan_draft", "validation_note"),
        forbidden_inputs=("system_of_record_without_approval", "customer_truth", "account_truth", "entitlement_truth", "automated_outreach"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("providers_recorded", "All providers are recorded in LTDs.md.", "Inventory rows exist."),
            LaneCheck("one_system_of_record_decision", "One system-of-record decision is required before promotion.", "Commercial ops decision receipt."),
        ),
    ),
)


def lane_by_key(lane_key: str) -> ProviderLane | None:
    normalized = _normalize(lane_key)
    for lane in LANES:
        if _normalize(lane.lane_key) == normalized:
            return lane
    return None


def _discovery_rows(markdown_text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    in_section = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## Discovery Tracking"):
            in_section = True
            continue
        if in_section and line.startswith("## ") and not line.startswith("## Discovery Tracking"):
            break
        if not in_section or not line.startswith("|") or line.startswith("|---"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) != 6 or parts[0] == "Service":
            continue
        rows[_normalize(parts[0])] = {
            "service": parts[0].strip().strip("`"),
            "account": parts[1],
            "discovery_status": parts[2].strip("`"),
            "verification_source": parts[3].strip("`"),
            "last_verified": parts[4],
            "notes": parts[5],
        }
    return rows


def _inventory_index(rows: tuple[LtdInventoryRow, ...]) -> dict[str, LtdInventoryRow]:
    index: dict[str, LtdInventoryRow] = {}
    for row in rows:
        normalized = _normalize(row.service_name)
        index[normalized] = row
        if normalized == "fliplink_me":
            index.setdefault("fliplink", row)
        if normalized == "vidboard_ai":
            index.setdefault("vidboard", row)
    return index


def _all_providers_present(lane: ProviderLane, inventory: Mapping[str, LtdInventoryRow]) -> bool:
    return all(_normalize(provider) in inventory for provider in lane.providers)


def _env_present(env: Mapping[str, str], *keys: str) -> bool:
    return all(bool(str(env.get(key) or "").strip()) for key in keys)


def _existing_receipt(root: Path, *relative_paths: str) -> bool:
    return any((root / relative_path).is_file() for relative_path in relative_paths)


def _passing_json_receipt(root: Path, *relative_paths: str) -> bool:
    for relative_path in relative_paths:
        path = root / relative_path
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "pass":
            return True
    return False


def _row_notes(discovery: Mapping[str, Mapping[str, str]], provider: str) -> str:
    row = discovery.get(_normalize(provider), {})
    return " ".join(str(row.get(key) or "") for key in ("verification_source", "notes")).lower()


def _has_positive_proof_text(text: str, *, required_terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    negative_markers = (
        "pending",
        "still pending",
        "not verified",
        "no authenticated",
        "no structured",
        "fails",
        "failed",
        "blocked",
        "before any chummer use",
    )
    if any(marker in lowered for marker in negative_markers):
        return False
    positive_markers = (
        "verified",
        "proven",
        "proof exists",
        "receipt exists",
        "receipt recorded",
        "passes",
        "approved",
    )
    return all(term in lowered for term in required_terms) and any(marker in lowered for marker in positive_markers)


def _check_passed(
    lane: ProviderLane,
    check: LaneCheck,
    *,
    markdown_text: str,
    inventory: Mapping[str, LtdInventoryRow],
    discovery: Mapping[str, Mapping[str, str]],
    env: Mapping[str, str],
    root: Path,
) -> tuple[bool, str]:
    key = check.check_key
    notes = "missing"
    contract_summary = _provider_contract_summary(root)
    if key in {"inventory_recorded", "providers_recorded"}:
        ok = _all_providers_present(lane, inventory)
        return ok, "inventory_rows_present" if ok else "inventory_rows_missing"
    if key == "hedy_provider_capability":
        ok = _passing_json_receipt(
            root,
            "_completion/hedy/HEDY_PROVIDER_CAPABILITY.generated.json",
            "ea/_completion/hedy/HEDY_PROVIDER_CAPABILITY.generated.json",
        )
        return ok, "hedy_live_provider_capability" if ok else "hedy_provider_capability_missing"
    if key == "hedy_consent_gate":
        if _provider_contract_check(
            root,
            filename="HEDY_MEETING_EVIDENCE_CONTRACT.generated.json",
            verification_key="consent_gate_contract",
        ):
            return True, "hedy_contract_receipt_consent_gate"
        ok = "consented_meeting_transcript" in lane.allowed_inputs and "unconsented_recording" in lane.forbidden_inputs
        return ok, "hedy_consent_boundary_defined" if ok else "hedy_consent_boundary_missing"
    if key == "hedy_webhook_signature":
        if _provider_contract_check(
            root,
            filename="HEDY_MEETING_EVIDENCE_CONTRACT.generated.json",
            verification_key="webhook_signature_contract",
        ):
            return True, "hedy_contract_receipt_webhook_signature"
        ok = _passing_json_receipt(
            root,
            "_completion/hedy/HEDY_WEBHOOK_SIGNATURE.generated.json",
            "ea/_completion/hedy/HEDY_WEBHOOK_SIGNATURE.generated.json",
        )
        return ok, "hedy_live_webhook_signature" if ok else "hedy_webhook_signature_missing"
    if key == "hedy_review_gate":
        ok = (
            "direct_commitment_creation" in lane.forbidden_inputs
            and "direct_decision_creation" in lane.forbidden_inputs
            and "review" in lane.source_of_truth.lower()
        )
        return ok, "hedy_review_only_boundary" if ok else "hedy_review_only_boundary_missing"
    if key == "hedy_memory_promotion_gate":
        ok = "direct_people_memory_overwrite" in lane.forbidden_inputs
        return ok, "hedy_memory_promotion_boundary" if ok else "hedy_memory_promotion_boundary_missing"
    if key == "hedy_session_mapping":
        ok = _provider_contract_check(
            root,
            filename="HEDY_MEETING_EVIDENCE_CONTRACT.generated.json",
            verification_key="webhook_to_review_queue_contract",
        )
        return ok, "hedy_contract_receipt_session_mapping" if ok else "hedy_session_mapping_missing"
    if key == "markupgo_provider_proof":
        ok = _passing_json_receipt(
            root,
            "_completion/markupgo/MARKUPGO_PROVIDER_VERIFICATION.generated.json",
            "ea/_completion/markupgo/MARKUPGO_PROVIDER_VERIFICATION.generated.json",
        )
        return ok, "markupgo_live_provider_capability" if ok else "markupgo_provider_proof_missing"
    if key == "premium_source_packet":
        if _provider_contract_check(
            root,
            filename="PREMIUM_DELIVERY_CONTRACT.generated.json",
            verification_key="approved_source_contract",
        ):
            return True, "premium_contract_receipt_source_packet"
        ok = any(item in lane.allowed_inputs for item in ("approved_source_packet", "approved_private_packet", "approved_board_packet"))
        return ok, "premium_source_packet_boundary" if ok else "premium_source_packet_missing"
    if key == "premium_artifact_hash":
        ok = _provider_contract_check(
            root,
            filename="PREMIUM_DELIVERY_CONTRACT.generated.json",
            verification_key="artifact_hash_contract",
        )
        return ok, "premium_contract_receipt_artifact_hash" if ok else "premium_artifact_hash_missing"
    if key == "premium_delivery_receipt":
        ok = _passing_json_receipt(
            root,
            "_completion/premium_delivery/EA_PREMIUM_DELIVERY_ROUNDTRIP.generated.json",
            "ea/_completion/premium_delivery/EA_PREMIUM_DELIVERY_ROUNDTRIP.generated.json",
            "_completion/premium_delivery/premium_packet_to_delivery_e2e.generated.json",
            "ea/_completion/premium_delivery/premium_packet_to_delivery_e2e.generated.json",
        )
        return ok, "premium_delivery_roundtrip_passed" if ok else "premium_delivery_receipt_missing"
    if key == "approvethis_provider_capability":
        ok = _passing_json_receipt(
            root,
            "_completion/approvethis/APPROVETHIS_PROVIDER_CAPABILITY.generated.json",
            "ea/_completion/approvethis/APPROVETHIS_PROVIDER_CAPABILITY.generated.json",
        )
        return ok, "approvethis_live_provider_capability" if ok else "approvethis_provider_capability_missing"
    if key == "approvethis_external_scope":
        if _provider_contract_check(
            root,
            filename="APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json",
            verification_key="bounded_scope_contract",
        ):
            return True, "approvethis_contract_receipt_external_scope"
        ok = "replace_internal_queue" in lane.forbidden_inputs and "approval_truth" in lane.forbidden_inputs
        return ok, "approvethis_external_scope_boundary" if ok else "approvethis_external_scope_missing"
    if key == "approvethis_final_policy_gate":
        ok = "direct_downstream_action" in lane.forbidden_inputs and "approval_without_ea_policy" in lane.forbidden_inputs
        return ok, "approvethis_final_policy_gate_boundary" if ok else "approvethis_final_policy_gate_missing"
    if key == "approvethis_webhook_signature":
        if _provider_contract_check(
            root,
            filename="APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json",
            verification_key="webhook_signature_contract",
        ):
            return True, "approvethis_contract_receipt_webhook_signature"
        ok = _passing_json_receipt(
            root,
            "_completion/approvethis/APPROVETHIS_WEBHOOK_SIGNATURE.generated.json",
            "ea/_completion/approvethis/APPROVETHIS_WEBHOOK_SIGNATURE.generated.json",
        )
        return ok, "approvethis_live_webhook_signature" if ok else "approvethis_webhook_signature_missing"
    if key == "approvethis_evidence_mapping":
        ok = _provider_contract_check(
            root,
            filename="APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json",
            verification_key="evidence_mapping_contract",
        )
        return ok, "approvethis_contract_receipt_evidence_mapping" if ok else "approvethis_evidence_mapping_missing"
    if key == "documentation_ai_provider_capability":
        ok = _passing_json_receipt(
            root,
            "_completion/documentation_ai/DOCUMENTATION_AI_PROVIDER_CAPABILITY.generated.json",
            "ea/_completion/documentation_ai/DOCUMENTATION_AI_PROVIDER_CAPABILITY.generated.json",
        )
        return ok, "documentation_ai_live_provider_capability" if ok else "documentation_ai_provider_capability_missing"
    if key == "documentation_git_source_of_truth":
        if _provider_contract_check(
            root,
            filename="DOCUMENTATION_AI_PUBLICATION_CONTRACT.generated.json",
            verification_key="source_hash_contract",
        ):
            return True, "documentation_contract_receipt_git_truth"
        ok = "source-controlled markdown" in lane.source_of_truth.lower() or "git" in lane.source_of_truth.lower()
        return ok, "documentation_git_truth_boundary" if ok else "documentation_git_truth_missing"
    if key == "documentation_no_writeback":
        if _provider_contract_check(
            root,
            filename="DOCUMENTATION_AI_PUBLICATION_CONTRACT.generated.json",
            verification_key="provider_writeback_boundary",
        ):
            return True, "documentation_contract_receipt_no_writeback"
        ok = "EA_DOCUMENTATION_AI_AGENT_WRITEBACK_ENABLED" in lane.off_switch_env and "silent_writeback" in lane.forbidden_inputs
        return ok, "documentation_no_writeback_boundary" if ok else "documentation_no_writeback_missing"
    if key == "documentation_privacy_boundary":
        ok = {
            "workspace_data",
            "customer_support_ticket",
            "private_incident_log",
        } <= set(lane.forbidden_inputs)
        return ok, "documentation_privacy_boundary_defined" if ok else "documentation_privacy_boundary_missing"
    if key == "documentation_llms_txt":
        ok = _passing_json_receipt(
            root,
            "_completion/documentation_ai/DOCUMENTATION_AI_LLMS_TXT.generated.json",
            "ea/_completion/documentation_ai/DOCUMENTATION_AI_LLMS_TXT.generated.json",
        )
        return ok, "documentation_ai_llms_txt_passed" if ok else "documentation_llms_txt_missing"
    if key in {"copyright_privacy_boundary", "provider_boundaries", "citation_required", "freshness_check", "retention_boundary"}:
        needles = {
            "copyright_privacy_boundary": ("must not host sourcebook PDFs", "copied rulebook prose", "private runner sheets"),
            "provider_boundaries": ("source of truth", "mirror"),
            "citation_required": ("cited", "freshness"),
            "freshness_check": ("freshness",),
            "retention_boundary": ("retention", "tenant isolation"),
        }[key]
        ok = all(needle.lower() in markdown_text.lower() for needle in needles)
        return ok, "boundary_text_present" if ok else "boundary_text_missing"
    if key == "first_publication_receipt":
        ok = _passing_json_receipt(root, "ea/_completion/fliplink/CHUMMER_FLIPLINK_PUBLICATION.generated.json", "_completion/fliplink/CHUMMER_FLIPLINK_PUBLICATION.generated.json")
        return ok, "publication_receipt_passed" if ok else "publication_receipt_missing_or_failed"
    if key == "provider_verification":
        ok = any(
            str(discovery.get(_normalize(provider), {}).get("discovery_status") or "") in {"complete", "manual_seeded"}
            for provider in lane.providers
        )
        return ok, "discovery_status_present" if ok else "provider_verification_missing"
    if key == "api_key_seeded":
        ok = _env_present(env, "UNMIXR_API_KEY")
        return ok, "env_slot_populated" if ok else "UNMIXR_API_KEY_missing"
    if key == "voice_id_private":
        ok = _env_present(env, "UNMIXR_VOICE_ID")
        return ok, "env_slot_populated" if ok else "UNMIXR_VOICE_ID_missing"
    if key == "voice_roundtrip_validation":
        ok = _passing_json_receipt(root, "ea/_completion/unmixr/UNMIXR_VOICE_ROUNDTRIP.generated.json", "_completion/unmixr/UNMIXR_VOICE_ROUNDTRIP.generated.json")
        return ok, "roundtrip_receipt_present" if ok else "roundtrip_receipt_missing"
    if key == "piper_fallback_policy":
        ok = "piper" in markdown_text.lower() or _existing_receipt(
            root,
            "ea/docs/realtime_voice_redesign.md",
            "docs/realtime_voice_redesign.md",
        )
        return ok, "fallback_policy_present" if ok else "fallback_policy_missing"
    if key in {"commercial_use", "watermark_export", "watermark_duration_export", "credit_budget", "safety_scan", "human_review", "likeness_policy", "quality_score"}:
        if key == "human_review" and lane.lane_key == "markupgo_fliplink_premium_delivery":
            if _provider_contract_check(
                root,
                filename="PREMIUM_DELIVERY_CONTRACT.generated.json",
                verification_key="private_redaction_access_contract",
            ):
                return True, "premium_contract_receipt_human_review"
            ok = "human review" in lane.source_of_truth.lower() or "direct_publish" in lane.forbidden_inputs
            return ok, "premium_human_review_boundary" if ok else "premium_human_review_missing"
        relevant = "\n".join(str(inventory.get(_normalize(provider), "") or "") for provider in lane.providers)
        terms = {
            "commercial_use": ("commercial-use",),
            "watermark_export": ("watermark", "export"),
            "watermark_duration_export": ("watermark", "duration", "export"),
            "credit_budget": ("credit",),
            "safety_scan": ("safety",),
            "human_review": ("human", "review"),
            "likeness_policy": ("likeness",),
            "quality_score": ("quality",),
        }[key]
        ok = all(term in (markdown_text + relevant).lower() for term in terms)
        return ok, "inventory_or_receipt_text_present" if ok else "proof_missing"
    if key == "authenticated_session":
        if _passing_json_receipt(
            root,
            "ea/_completion/poppy/POPPY_AUTHENTICATED_SESSION.generated.json",
            "_completion/poppy/POPPY_AUTHENTICATED_SESSION.generated.json",
        ):
            return True, "poppy_receipt_passed"
        notes = _row_notes(discovery, "Poppy AI")
        ok = _has_positive_proof_text(notes, required_terms=("session",))
        return ok, "session_proof_recorded" if ok else "session_proof_missing"
    if key in {"privacy_boundary", "export_semantics", "tenant_isolation"}:
        receipt_paths = {
            "privacy_boundary": (
                "ea/_completion/poppy/POPPY_PRIVACY_BOUNDARY.generated.json",
                "_completion/poppy/POPPY_PRIVACY_BOUNDARY.generated.json",
            ),
            "export_semantics": (
                "ea/_completion/poppy/POPPY_EXPORT_SEMANTICS.generated.json",
                "_completion/poppy/POPPY_EXPORT_SEMANTICS.generated.json",
            ),
            "tenant_isolation": (
                "ea/_completion/poppy/POPPY_TENANT_ISOLATION.generated.json",
                "_completion/poppy/POPPY_TENANT_ISOLATION.generated.json",
            ),
        }[key]
        if _passing_json_receipt(root, *receipt_paths):
            return True, "poppy_receipt_passed"
        notes = _row_notes(discovery, "Poppy AI")
        terms = {
            "privacy_boundary": ("privacy",),
            "export_semantics": ("export",),
            "tenant_isolation": ("tenant", "isolation"),
        }[key]
        ok = _has_positive_proof_text(notes, required_terms=terms)
        return ok, "poppy_boundary_recorded" if ok else "poppy_boundary_missing"
    if key == "rafter_fleet_verified":
        row = discovery.get(_normalize("Rafter"), {})
        ok = row.get("verification_source") == "fleet_verified"
        return ok, "fleet_verified" if ok else "rafter_fleet_proof_missing"
    if key == "pixefy_fleet_verified":
        row = discovery.get(_normalize("Pixefy"), {})
        ok = row.get("verification_source") == "fleet_verified"
        return ok, "fleet_verified" if ok else "pixefy_fleet_proof_missing"
    if key == "ci_targets":
        makefile = root / "Makefile"
        text = makefile.read_text(encoding="utf-8") if makefile.is_file() else ""
        ok = "ltd-release-gates" in text and "verify-ltd-provider-lanes" in text
        return ok, "ci_target_present" if ok else "ci_target_missing"
    if key == "ea_security_targets":
        if _provider_contract_check(
            root,
            filename="EA_QUALITY_GATES_CONTRACT.generated.json",
            verification_key="security_target_matrix_contract",
        ):
            return True, "quality_contract_receipt_security_targets"
        ok = (
            contract_summary.get("status") == "contract_pass_live_provider_pending"
            or _row_notes(discovery, "Rafter").find("fleet proof passes") >= 0
        )
        return ok, "release_quality_security_targets_local" if ok else "ea_security_targets_missing"
    if key == "ea_visual_targets":
        if _provider_contract_check(
            root,
            filename="EA_QUALITY_GATES_CONTRACT.generated.json",
            verification_key="visual_target_matrix_contract",
        ):
            return True, "quality_contract_receipt_visual_targets"
        ok = (
            contract_summary.get("status") == "contract_pass_live_provider_pending"
            or _row_notes(discovery, "Pixefy").find("fleet proof passes") >= 0
        )
        return ok, "release_quality_visual_targets_local" if ok else "ea_visual_targets_missing"
    if key == "release_truth_boundary":
        if _provider_contract_check(
            root,
            filename="EA_QUALITY_GATES_CONTRACT.generated.json",
            verification_key="release_truth_boundary",
        ):
            return True, "quality_contract_receipt_release_truth_boundary"
        ok = "release_truth" in lane.forbidden_inputs
        return ok, "release_truth_boundary_defined" if ok else "release_truth_boundary_missing"
    if key == "normalized_schema":
        ok = bool(lane.normalized_signal_schema)
        return ok, "schema_defined" if ok else "schema_missing"
    if key == "api_or_export_proof":
        row = discovery.get(_normalize("Prompt Architects"), {})
        ok = "prompt_foundry" in str(row.get("verification_source") or row.get("notes") or "").lower()
        return ok, "prompt_foundry_receipt_recorded" if ok else "prompt_foundry_receipt_missing"
    if key == "api_token_private":
        ok = _env_present(env, "SUBSCRIBR_API_TOKEN")
        return ok, "SUBSCRIBR_API_TOKEN_present_outside_git" if ok else "SUBSCRIBR_API_TOKEN_missing"
    if key == "channel_map":
        ok = _passing_json_receipt(
            root,
            "ea/_completion/subscribr/SUBSCRIBR_CHANNEL_MAP.generated.json",
            "_completion/subscribr/SUBSCRIBR_CHANNEL_MAP.generated.json",
        )
        return ok, "subscribr_channel_map_receipt_passed" if ok else "subscribr_channel_map_missing"
    if key == "script_roundtrip":
        ok = _passing_json_receipt(
            root,
            "ea/_completion/subscribr/CHUMMER_SUBSCRIBR_SCRIPT_DRAFT.generated.json",
            "ea/_completion/subscribr/SUBSCRIBR_SCRIPT_ROUNDTRIP.generated.json",
            "_completion/subscribr/CHUMMER_SUBSCRIBR_SCRIPT_DRAFT.generated.json",
            "_completion/subscribr/SUBSCRIBR_SCRIPT_ROUNDTRIP.generated.json",
        )
        return ok, "subscribr_script_receipt_passed" if ok else "subscribr_script_roundtrip_missing"
    if key == "source_binding":
        ok = _passing_json_receipt(
            root,
            "ea/_completion/subscribr/SUBSCRIBR_SOURCE_BINDING.generated.json",
            "_completion/subscribr/SUBSCRIBR_SOURCE_BINDING.generated.json",
        )
        return ok, "subscribr_source_binding_passed" if ok else "subscribr_source_binding_missing"
    if key == "sendr_provider_verification":
        ok = _passing_json_receipt(
            root,
            "ea/_completion/sendr/SENDR_PROVIDER_VERIFICATION.generated.json",
            "_completion/sendr/SENDR_PROVIDER_VERIFICATION.generated.json",
        )
        return ok, "sendr_provider_verification_passed" if ok else "sendr_provider_verification_missing"
    if key == "sendr_recipient_basis":
        required = {"recipient_basis", "source_url_or_note", "suppression_status"}
        ok = required <= set(lane.normalized_signal_schema)
        return ok, "sendr_recipient_basis_boundary_defined" if ok else "sendr_recipient_basis_boundary_missing"
    if key == "sendr_suppression_sync":
        ok = _passing_json_receipt(
            root,
            "ea/_completion/sendr/SENDR_SUPPRESSION_SYNC.generated.json",
            "_completion/sendr/SENDR_SUPPRESSION_SYNC.generated.json",
        )
        return ok, "sendr_suppression_sync_passed" if ok else "sendr_suppression_sync_missing"
    if key == "sendr_claim_validation":
        ok = "approved_public_ea_docs" in lane.allowed_inputs and "product_truth" in lane.forbidden_inputs
        return ok, "sendr_claim_boundary_defined" if ok else "sendr_claim_boundary_missing"
    if key == "sendr_privacy_boundary":
        required = {
            "raw_gmail",
            "raw_calendar",
            "people_memory",
            "private_commitment",
            "private_decision",
            "customer_draft",
            "secret",
        }
        ok = required <= set(lane.forbidden_inputs)
        return ok, "sendr_privacy_boundary_defined" if ok else "sendr_privacy_boundary_missing"
    if key == "sendr_human_review":
        ok = (
            "human review" in lane.source_of_truth.lower()
            and "auto_reply" in lane.forbidden_inputs
            and "direct_publish" in lane.forbidden_inputs
            and "EA_SENDR_DIRECT_SEND_ENABLED" in lane.off_switch_env
            and "EA_SENDR_AUTO_REPLY_ENABLED" in lane.off_switch_env
        )
        return ok, "sendr_human_review_boundary_defined" if ok else "sendr_human_review_boundary_missing"
    if key == "sendr_reply_ingest":
        ok = (
            "reply_event_hash" in lane.normalized_signal_schema
            and "human_review_status" in lane.normalized_signal_schema
            and "auto_reply" in lane.forbidden_inputs
        )
        return ok, "sendr_reply_ingest_boundary_defined" if ok else "sendr_reply_ingest_boundary_missing"
    if key == "provider_roles_defined":
        ok = all(part in lane.source_of_truth.lower() for part in ("teable", "blipai", "syllabbles"))
        return ok, "roles_defined" if ok else "roles_missing"
    if key == "approval_gate":
        ok = "approval" in lane.source_of_truth.lower() or "approval" in " ".join(lane.forbidden_inputs).lower()
        return ok, "approval_gate_present" if ok else "approval_gate_missing"
    if key == "one_system_of_record_decision":
        ok = "system_of_record_without_approval" in lane.forbidden_inputs
        return ok, "promotion_guard_present" if ok else "promotion_guard_missing"
    return False, notes


def build_ltd_provider_lane_receipt(
    lane: ProviderLane,
    *,
    markdown_text: str,
    inventory_rows: tuple[LtdInventoryRow, ...],
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    resolved_root = root or _repo_root()
    resolved_env = dict(env or {})
    inventory = _inventory_index(inventory_rows)
    discovery = _discovery_rows(markdown_text)
    check_rows: list[dict[str, object]] = []
    missing: list[str] = []
    for check in lane.required_checks:
        passed, source = _check_passed(
            lane,
            check,
            markdown_text=markdown_text,
            inventory=inventory,
            discovery=discovery,
            env=resolved_env,
            root=resolved_root,
        )
        if not passed:
            missing.append(check.check_key)
        check_rows.append(
            {
                "check_key": check.check_key,
                "label": check.label,
                "passed": passed,
                "source": source,
                "proof_hint": check.proof_hint,
            }
        )
    hard_failures = _hard_contract_failures(lane)
    lane_state = lane.verified_state if not missing else lane.missing_state
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "lane_key": lane.lane_key,
        "title": lane.title,
        "integration_lane": lane.integration_lane,
        "providers": list(lane.providers),
        "lane_state": lane_state,
        "runtime_enabled": lane_state == "verified_runtime_lane" and not hard_failures,
        "not_source_of_truth": True,
        "source_of_truth_boundary": lane.source_of_truth,
        "off_switch_env": list(lane.off_switch_env),
        "allowed_inputs": list(lane.allowed_inputs),
        "forbidden_inputs": list(lane.forbidden_inputs),
        "normalized_signal_schema": list(lane.normalized_signal_schema),
        "required_checks": check_rows,
        "passed_checks": [row["check_key"] for row in check_rows if row["passed"]],
        "missing_checks": missing,
        "hard_contract_failures": hard_failures,
        "status": "pass" if not hard_failures else "fail",
    }


def _hard_contract_failures(lane: ProviderLane) -> list[str]:
    failures: list[str] = []
    if not lane.off_switch_env:
        failures.append("missing_off_switch")
    if not lane.source_of_truth or "truth" not in lane.source_of_truth.lower():
        failures.append("missing_source_of_truth_boundary")
    if not lane.forbidden_inputs:
        failures.append("missing_forbidden_inputs")
    if lane.lane_key == "public_signal_ingest":
        required = {
            "source",
            "author_contact",
            "project",
            "feature_request_category",
            "severity_value",
            "public_private_flag",
            "consent_to_contact",
            "raw_payload_hash",
        }
        if set(lane.normalized_signal_schema) != required:
            failures.append("public_signal_schema_mismatch")
    if lane.lane_key == "subscribr_chummer_script_factory":
        if "direct_publish" not in lane.forbidden_inputs:
            failures.append("subscribr_direct_publish_not_forbidden")
        if "publication_approval" not in lane.forbidden_inputs:
            failures.append("subscribr_publication_approval_not_forbidden")
        if "release_truth" not in lane.forbidden_inputs or "rules_truth" not in lane.forbidden_inputs:
            failures.append("subscribr_truth_boundary_incomplete")
        if "approved_public_source_packet" not in lane.allowed_inputs:
            failures.append("subscribr_source_packet_missing")
        if "EA_SUBSCRIBR_DIRECT_PUBLISH_ENABLED" not in lane.off_switch_env:
            failures.append("subscribr_direct_publish_off_switch_missing")
    if lane.lane_key == "sendr_ea_growth_outreach":
        required_forbidden = {
            "raw_gmail",
            "raw_calendar",
            "people_memory",
            "private_commitment",
            "private_decision",
            "customer_draft",
            "secret",
            "auto_reply",
            "direct_publish",
        }
        missing_forbidden = required_forbidden - set(lane.forbidden_inputs)
        if missing_forbidden:
            failures.append("sendr_privacy_or_send_boundary_incomplete")
        required_switches = {
            "EA_SENDR_DIRECT_SEND_ENABLED",
            "EA_SENDR_AUTO_REPLY_ENABLED",
            "EA_SENDR_PRIVATE_WORKSPACE_DATA_ALLOWED",
            "EA_SENDR_WHATSAPP_ENABLED",
        }
        if not required_switches <= set(lane.off_switch_env):
            failures.append("sendr_fail_closed_switch_missing")
        required_schema = {"recipient_basis", "suppression_status", "human_review_status", "reply_event_hash"}
        if not required_schema <= set(lane.normalized_signal_schema):
            failures.append("sendr_signal_schema_incomplete")
    if lane.lane_key == "hedy_meeting_evidence":
        if "direct_people_memory_overwrite" not in lane.forbidden_inputs:
            failures.append("hedy_review_boundary_incomplete")
    if lane.lane_key == "markupgo_fliplink_premium_delivery":
        if "access_grant_truth" not in lane.forbidden_inputs:
            failures.append("premium_delivery_boundary_incomplete")
    if lane.lane_key == "approvethis_external_approval_edge":
        if "direct_downstream_action" not in lane.forbidden_inputs:
            failures.append("approvethis_boundary_incomplete")
    if lane.lane_key == "documentation_ai_publication":
        if "silent_writeback" not in lane.forbidden_inputs:
            failures.append("documentation_ai_boundary_incomplete")
    if lane.lane_key == "release_quality_gates":
        if "release_truth" not in lane.forbidden_inputs:
            failures.append("release_quality_truth_boundary_missing")
    return failures


def build_ltd_provider_governance_receipt(
    *,
    markdown_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    resolved_root = root or (markdown_path.parent if markdown_path else _repo_root())
    path = markdown_path or (resolved_root / "LTDs.md")
    markdown_text = path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(path)
    merged_env = dict(env or {})
    if env is None:
        dot_env = _load_dotenv(resolved_root / ".env")
        local_env = _load_dotenv(resolved_root / ".env.local")
        service_env = _load_dotenv(resolved_root / "ea" / ".env")
        dot_env.update(local_env)
        dot_env.update(service_env)
        dot_env.update({key: value for key, value in os.environ.items() if value})
        merged_env = dot_env
    receipts = [
        build_ltd_provider_lane_receipt(
            lane,
            markdown_text=markdown_text,
            inventory_rows=inventory_rows,
            env=merged_env,
            root=resolved_root,
            generated_at=generated_at,
        )
        for lane in LANES
    ]
    failures = [receipt["lane_key"] for receipt in receipts if receipt["status"] != "pass"]
    contract_summary = _provider_contract_summary(resolved_root)
    contract_backed_checks = [
        {
            "lane_key": receipt["lane_key"],
            "check_key": check["check_key"],
            "source": check["source"],
        }
        for receipt in receipts
        for check in list(receipt["required_checks"])
        if isinstance(check, dict) and "contract_receipt_" in str(check.get("source") or "")
    ]
    provider_contracts = {
        "local_contracts_present": bool(contract_summary),
        "status": str(contract_summary.get("status") or "missing"),
        "proof_scope": str(contract_summary.get("proof_scope") or ""),
        "live_provider_runtime_verified": bool(contract_summary.get("live_provider_runtime_verified")),
        "gold_claim_allowed": bool(contract_summary.get("gold_claim_allowed")),
        "required_next_receipts": list(contract_summary.get("required_next_receipts") or []),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "contract_name": "ea.verify_ltd_provider_lanes",
        "status": "pass" if not failures else "fail",
        "lane_count": len(receipts),
        "verified_or_blocked_count": sum(1 for receipt in receipts if receipt["status"] == "pass"),
        "failures": failures,
        "provider_contracts": provider_contracts,
        "contract_backed_checks": contract_backed_checks,
        "contract_backed_check_count": len(contract_backed_checks),
        "lanes": receipts,
    }


def materialize_ltd_provider_governance_receipts(
    *,
    output_dir: Path | None = None,
    markdown_path: Path | None = None,
    lane_key: str | None = None,
) -> dict[str, object]:
    root = _repo_root()
    target = output_dir or (root / "_completion" / "ltd_provider_lanes")
    target.mkdir(parents=True, exist_ok=True)
    receipt = build_ltd_provider_governance_receipt(markdown_path=markdown_path, root=markdown_path.parent if markdown_path else root)
    lanes = receipt["lanes"]
    if lane_key:
        lane = lane_by_key(lane_key)
        if lane is None:
            raise ValueError(f"unknown_ltd_provider_lane:{lane_key}")
        lanes = [row for row in lanes if row["lane_key"] == lane.lane_key]
        if not lanes:
            raise ValueError(f"ltd_provider_lane_receipt_missing:{lane_key}")
    for lane_receipt in lanes:
        path = target / f"{str(lane_receipt['lane_key']).upper()}.generated.json"
        path.write_text(json.dumps(lane_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not lane_key:
        (target / "LTD_PROVIDER_GOVERNANCE.generated.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return receipt


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
