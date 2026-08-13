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
        lane_key="vocallab_catalog_authority",
        title="VocalLab Catalog and Authority Boundary",
        providers=("VocalLab.ai",),
        integration_lane="voice_catalog_only",
        verified_state="verified_catalog_only",
        missing_state="blocked_pending_proof",
        off_switch_env=(
            "EA_AUDIOBOOK_VOCALLAB_ENABLED",
            "EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER",
            "EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES",
            "EA_AUDIOBOOK_VOCALLAB_ALLOW_TOPUP_POINTS",
        ),
        source_of_truth=(
            "EA owns audiobook source, rights, cast, budget, quality, recipient, and publication truth; "
            "The separate Manfred product exclusively owns authority, samples, profiles, hearing, deletion, rollback, and release truth; "
            "VocalLab is catalog visibility only in this lane."
        ),
        allowed_inputs=(
            "redacted_voice_inventory_probe",
            "hashed_provider_voice_id",
            "approved_safe_voice_label",
        ),
        forbidden_inputs=(
            "raw_voice_sample",
            "real_person_voice_upload",
            "unconsented_likeness",
            "provider_voice_id_in_operator_name",
            "automatic_voice_render",
            "automatic_voice_clone",
            "automatic_point_topup",
            "cross_provider_fallback",
            "manfred_product_authority",
            "publication_truth",
            "release_truth",
        ),
        normalized_signal_schema=(
            "credential_present",
            "voice_count",
            "voice_id_sha256",
            "inventory_checked_at",
            "spend_authorized",
        ),
        required_checks=(
            LaneCheck("inventory_recorded", "VocalLab is recorded in LTDs.md.", "Inventory row exists."),
            LaneCheck(
                "vocallab_runtime_key_seeded",
                "The EA runtime has its own non-empty VocalLab key.",
                "VOCALLAB_API_KEY is populated in the evaluated runtime environment.",
            ),
            LaneCheck(
                "vocallab_registry_non_executable",
                "Generic provider routing cannot execute VocalLab inventory or rendering.",
                "ProviderRegistry binding and capabilities are non-executable.",
            ),
            LaneCheck(
                "vocallab_spend_controls_off",
                "Catalog verification cannot spend points, render, clone, or top up.",
                "All VocalLab spend/runtime switches remain off.",
            ),
            LaneCheck(
                "vocallab_manfred_product_authority_boundary",
                "The separate Manfred product retains exclusive authority and release truth.",
                "Lane boundary and forbidden inputs.",
            ),
        ),
    ),
    ProviderLane(
        lane_key="emailit_transactional_delivery",
        title="Emailit Governed Transactional Delivery",
        providers=("Emailit",),
        integration_lane="transactional_delivery_outbox",
        verified_state="verified_runtime_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=(
            "EA_EMAILIT_DELIVERY_ENABLED",
            "EA_EMAILIT_OFFICE_DELIVERY_ENABLED",
            "PROPERTYQUARRY_EMAILIT_DELIVERY_ENABLED",
            "CHUMMER_HUB_EMAILIT_DELIVERY_ENABLED",
        ),
        source_of_truth=(
            "EA owns recipient eligibility, template, suppression, approval, delivery, and closeout truth for EA-office notices only; "
            "PropertyQuarry owns property-mail truth and Chummer Hub owns lifecycle-notification truth; "
            "Emailit transports approved transactional notices and returns a provider receipt only."
        ),
        allowed_inputs=(
            "approved_transactional_notice",
            "approved_invite",
            "approved_followup",
            "approved_closeout_notice",
        ),
        forbidden_inputs=(
            "raw_gmail",
            "raw_calendar",
            "unsanitized_attachment",
            "unapproved_marketing_broadcast",
            "unsuppressed_recipient",
            "direct_send_without_approval",
            "support_truth",
            "billing_truth",
            "product_truth",
            "publication_truth",
        ),
        normalized_signal_schema=(
            "recipient_sha256",
            "template_ref",
            "template_version",
            "source_event_ref",
            "suppression_status",
            "approval_status",
            "provider_message_ref",
            "delivery_status",
        ),
        required_checks=(
            LaneCheck("inventory_recorded", "Emailit Tier 5 is recorded.", "LTD inventory row."),
            LaneCheck("emailit_provider_verification", "Recorded live provider capability proof exists.", "Discovery proof."),
            LaneCheck("emailit_api_key_private", "The API key is private runtime configuration.", "EMAILIT_API_KEY outside git."),
            LaneCheck("emailit_delivery_adapter", "The bounded transactional adapter is wired.", "Registration email adapter contract."),
            LaneCheck("emailit_receipt_contract", "Accepted sends return a provider receipt.", "RegistrationEmailReceipt contract."),
            LaneCheck("emailit_approval_suppression_boundary", "Approval and suppression boundaries are fail-closed.", "Lane and outbound guard contract."),
            LaneCheck("emailit_off_switch", "Global and product-scoped runtime kill switches exist.", "Named EA, PropertyQuarry, and Hub Emailit switch contract."),
        ),
    ),
    ProviderLane(
        lane_key="fastestvpn_governed_provider_transport",
        title="FastestVPN Governed Provider Transport",
        providers=("FastestVPN PRO",),
        integration_lane="provider_transport_proxy",
        verified_state="verified_runtime_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_ENABLE_FASTESTVPN",),
        source_of_truth=(
            "EA owns provider routing, account, quota, billing, product, and release truth; "
            "FastestVPN supplies bounded transport for approved provider probes only."
        ),
        allowed_inputs=("approved_provider_api_probe", "approved_browser_login", "sanitized_country_probe"),
        forbidden_inputs=(
            "customer_public_ingress",
            "provider_rate_limit_evasion",
            "access_policy_bypass",
            "raw_proxy_credential",
            "raw_exit_ip_receipt",
            "account_truth",
            "quota_truth",
            "billing_truth",
            "product_truth",
            "release_truth",
        ),
        normalized_signal_schema=(
            "proxy_mode",
            "proxy_pool_size",
            "proxy_reachable_count",
            "expected_country",
            "observed_country",
            "country_verified",
            "secret_material_exposed",
            "provider_cooldown_status",
        ),
        required_checks=(
            LaneCheck("inventory_recorded", "FastestVPN PRO is recorded.", "LTD inventory row."),
            LaneCheck("fastestvpn_runtime_contract", "The isolated proxy runtime is reproducible.", "Pinned Docker/Compose contract."),
            LaneCheck("fastestvpn_ch_profile_boundary", "The 1min lane is pinned to Switzerland profiles.", "Compose profile contract."),
            LaneCheck("fastestvpn_secret_boundary", "VPN profiles, credentials, and exit IPs stay private.", "Build and receipt privacy contract."),
            LaneCheck("fastestvpn_rate_limit_boundary", "Provider cooldown remains authoritative.", "Live-ops receipt and lane boundary."),
            LaneCheck("fastestvpn_off_switch", "The lane retains an explicit deployment off-switch.", "EA_ENABLE_FASTESTVPN contract."),
        ),
    ),
    ProviderLane(
        lane_key="onemin_bounded_capacity_scheduler",
        title="1min.AI Bounded Capacity Scheduler",
        providers=("1min.AI",),
        integration_lane="background_capacity_scheduler",
        verified_state="verified_runtime_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_RESPONSES_ONEMIN_BACKGROUND_REFRESH_ENABLED",),
        source_of_truth=(
            "EA owns task eligibility, model selection, account selection, quota, credit, evidence, approval, product, and release truth; "
            "1min.AI supplies bounded inference capacity only."
        ),
        allowed_inputs=(
            "public_safe_background_task",
            "sanitized_repository_task",
            "approved_operator_prompt",
            "synthetic_health_probe",
        ),
        forbidden_inputs=(
            "raw_gmail",
            "raw_calendar",
            "people_memory",
            "unredacted_attachment",
            "secret_value",
            "unbounded_parallel_dispatch",
            "quota_bypass",
            "provider_rate_limit_evasion",
            "automatic_publication",
            "approval_truth",
            "product_truth",
            "release_truth",
        ),
        normalized_signal_schema=(
            "task_class",
            "provider",
            "credential_present",
            "maximum_blast_radius",
            "quota_state",
            "dispatch_state",
            "receipt_sha256",
            "owner_review_required",
        ),
        required_checks=(
            LaneCheck("inventory_recorded", "1min.AI is recorded.", "LTD inventory row."),
            LaneCheck("onemin_credential_pool", "A private 1min credential pool is present.", "Secret-safe credential presence only."),
            LaneCheck("onemin_scheduler_contract", "The bounded scheduler and blast-radius contracts exist.", "Local operating-mesh contracts."),
            LaneCheck("onemin_quota_controls", "Request and credit ceilings are enforced.", "Responses runtime quota contract."),
            LaneCheck("onemin_secret_safe_receipt", "Capacity receipts expose no credential material.", "LTD capacity projection contract."),
            LaneCheck("onemin_background_off_switch", "Background capacity has a fail-closed off-switch.", "EA_RESPONSES_ONEMIN_BACKGROUND_REFRESH_ENABLED contract."),
            LaneCheck("onemin_review_boundary", "Dispatch cannot own approval or release truth.", "Lane boundary contract."),
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
        lane_key="aiwritebook_chronicle_studio",
        title="AIWriteBook Chronicle Studio Operator Lane",
        providers=("AiWriteBook",),
        integration_lane="operator_required_book_production",
        verified_state="verified_draft_operator_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_AIWRITEBOOK_CHRONICLE_STUDIO_ENABLED",),
        source_of_truth=(
            "Chummer groups own project, consent, spoiler/redaction review, source-packet, approval, artifact, and publication truth; "
            "AIWriteBook is used only through the operator-run production lane."
        ),
        allowed_inputs=(
            "approved_consent_spoiler_redaction_reviewed_chummer_source_packet",
            "consented_runner_handle_snapshot",
            "operator_approved_outline_revision",
        ),
        forbidden_inputs=(
            "unapproved_source_packet",
            "sourcebook_pdf",
            "copied_rulebook_prose",
            "private_campaign_data_without_consent",
            "unredacted_gm_secret",
            "provider_secret",
            "unattended_browser_automation",
            "credit_spend_without_approval",
            "source_upload_without_approval",
            "generation_without_approval",
            "external_send_without_approval",
            "direct_publish",
            "publication_truth",
            "rules_truth",
        ),
        normalized_signal_schema=(
            "source_packet_id",
            "source_packet_version",
            "source_packet_sha256",
            "provider_project_ref",
            "artifact_url",
            "artifact_sha256",
            "export_format",
            "upload_approval_status",
            "generation_approval_status",
            "outline_approval_status",
            "artifact_import_status",
            "publication_approval_status",
            "external_send_approval_status",
            "human_review_status",
        ),
        required_checks=(
            LaneCheck("inventory_recorded", "AIWriteBook Tier 4 is recorded.", "LTD inventory row."),
            LaneCheck("aiwritebook_account_review", "Sanitized authenticated account review exists.", "Account review receipt."),
            LaneCheck("aiwritebook_declared_limits", "Tier allowance and current credit costs are captured read-only.", "Authenticated pricing evidence."),
            LaneCheck("aiwritebook_declared_privacy", "Current privacy and retention declarations are captured.", "Privacy-policy evidence."),
            LaneCheck("aiwritebook_declared_exports", "PDF, EPUB, and DOCX support is declared on current provider surfaces.", "Pricing and terms evidence."),
            LaneCheck("aiwritebook_operator_boundary", "The lane cannot route unattended provider execution.", "Provider registry and lane boundary."),
            LaneCheck("aiwritebook_source_packet", "Only consented, spoiler-reviewed, redaction-reviewed source packets may leave Chummer.", "Chummer source-packet contract."),
            LaneCheck("aiwritebook_human_review", "Upload, generation, outline, artifact, publication, and external send remain separate human decisions.", "Chummer approval state machine."),
            LaneCheck("aiwritebook_export_roundtrip", "A redacted export round-trip is verified.", "Approved canary receipt."),
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


def _json_receipt(root: Path, *relative_paths: str) -> dict[str, Any]:
    for relative_path in relative_paths:
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


def _valid_aiwritebook_export_roundtrip_receipt(root: Path) -> bool:
    payload: dict[str, Any] = {}
    for relative_path in (
        "ea/_completion/aiwritebook/AIWRITEBOOK_EXPORT_ROUNDTRIP.generated.json",
        "_completion/aiwritebook/AIWRITEBOOK_EXPORT_ROUNDTRIP.generated.json",
        "config/provider_evidence/AIWRITEBOOK_EXPORT_ROUNDTRIP.source.json",
    ):
        path = root / relative_path
        if not path.is_file() or path.is_symlink():
            continue
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    fixture = payload.get("fixture") if isinstance(payload.get("fixture"), dict) else {}
    authorization = payload.get("authorization") if isinstance(payload.get("authorization"), dict) else {}
    provider_run = payload.get("provider_run") if isinstance(payload.get("provider_run"), dict) else {}
    exports = payload.get("exports") if isinstance(payload.get("exports"), dict) else {}
    maximum = authorization.get("maximum_credits")
    before = provider_run.get("credits_before")
    after = provider_run.get("credits_after")
    spent = provider_run.get("credits_spent")

    def strict_int(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def sha256(value: object) -> bool:
        return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))

    def safe_ref(value: object) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", str(value or "")))

    def timestamp(value: object) -> bool:
        try:
            parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None

    if (
        set(payload) != {
            "contract",
            "contract_version",
            "status",
            "generated_at",
            "fixture",
            "authorization",
            "provider_run",
            "exports",
            "expected_formats",
            "secret_material_in_receipt",
        }
        or payload.get("contract") != "ea.aiwritebook.export_roundtrip"
        or payload.get("contract_version") != 1
        or payload.get("status") != "pass"
        or not timestamp(payload.get("generated_at"))
        or payload.get("secret_material_in_receipt") is not False
        or set(payload.get("expected_formats") or ()) != {"pdf", "epub", "docx"}
        or set(fixture) != {"fixture_id", "manifest_sha256", "source_sha256", "data_classification", "rights"}
        or fixture.get("fixture_id") != "aiwritebook-chronicle-export-canary-v1"
        or fixture.get("data_classification") != "synthetic_no_personal_or_campaign_data"
        or fixture.get("rights") != "CC0-1.0"
        or not sha256(fixture.get("manifest_sha256"))
        or not sha256(fixture.get("source_sha256"))
        or set(authorization) != {
            "approval_contract",
            "approved_by_ref",
            "approved_at",
            "maximum_credits",
            "provider_project_creation_approved",
            "source_upload_approved",
            "generation_approved",
            "credit_spend_approved",
            "export_download_approved",
            "provider_project_deletion_approved",
            "publication_approved",
            "external_send_approved",
        }
        or authorization.get("approval_contract") != "ea.aiwritebook.canary_approval"
        or not safe_ref(authorization.get("approved_by_ref"))
        or not timestamp(authorization.get("approved_at"))
        or not strict_int(maximum)
        or maximum <= 0
        or authorization.get("provider_project_creation_approved") is not True
        or authorization.get("source_upload_approved") is not True
        or authorization.get("generation_approved") is not True
        or authorization.get("credit_spend_approved") is not True
        or authorization.get("export_download_approved") is not True
        or authorization.get("provider_project_deletion_approved") is not True
        or authorization.get("publication_approved") is not False
        or authorization.get("external_send_approved") is not False
        or set(provider_run) != {
            "provider_project_ref",
            "credits_before",
            "credits_after",
            "credits_spent",
            "operator_run",
            "unattended_browser_automation_used",
            "project_private_during_run",
            "shared_with_other_users",
            "delete_requested",
            "project_inaccessible_after_delete",
            "outline_reviewed",
            "exports_reviewed",
            "pdf_content_marker_reviewed",
            "publication_started",
            "external_send_performed",
            "run_started_at",
            "run_finished_at",
        }
        or not safe_ref(provider_run.get("provider_project_ref"))
        or not all(strict_int(value) for value in (before, after, spent))
        or before < after
        or spent != before - after
        or spent <= 0
        or spent > maximum
        or provider_run.get("operator_run") is not True
        or provider_run.get("unattended_browser_automation_used") is not False
        or provider_run.get("project_private_during_run") is not True
        or provider_run.get("shared_with_other_users") is not False
        or provider_run.get("delete_requested") is not True
        or provider_run.get("project_inaccessible_after_delete") is not True
        or provider_run.get("outline_reviewed") is not True
        or provider_run.get("exports_reviewed") is not True
        or provider_run.get("pdf_content_marker_reviewed") is not True
        or provider_run.get("publication_started") is not False
        or provider_run.get("external_send_performed") is not False
        or not timestamp(provider_run.get("run_started_at"))
        or not timestamp(provider_run.get("run_finished_at"))
        or set(exports) != {"pdf", "epub", "docx"}
    ):
        return False
    started_at = datetime.fromisoformat(str(provider_run["run_started_at"]).replace("Z", "+00:00"))
    finished_at = datetime.fromisoformat(str(provider_run["run_finished_at"]).replace("Z", "+00:00"))
    if finished_at < started_at:
        return False
    for export_format in ("pdf", "epub", "docx"):
        artifact = exports.get(export_format)
        if not isinstance(artifact, dict):
            return False
        filename = str(artifact.get("filename") or "")
        if (
            set(artifact) != {
                "filename",
                "sha256",
                "size_bytes",
                "structure_valid",
                "content_marker_verified",
                "content_marker_verification",
            }
            or not filename
            or Path(filename).name != filename
            or not sha256(artifact.get("sha256"))
            or not strict_int(artifact.get("size_bytes"))
            or artifact.get("size_bytes") <= 0
            or artifact.get("structure_valid") is not True
            or artifact.get("content_marker_verified") is not True
            or artifact.get("content_marker_verification") not in {"embedded", "human_review"}
        ):
            return False
    return True


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
    if key == "aiwritebook_account_review":
        payload = _json_receipt(
            root,
            "ea/_completion/aiwritebook/AIWRITEBOOK_ACCOUNT_REVIEW.generated.json",
            "_completion/aiwritebook/AIWRITEBOOK_ACCOUNT_REVIEW.generated.json",
            "config/provider_evidence/AIWRITEBOOK_ACCOUNT_REVIEW.source.json",
        )
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        posture = payload.get("automation_posture") if isinstance(payload.get("automation_posture"), dict) else {}
        actions = payload.get("review_actions") if isinstance(payload.get("review_actions"), dict) else {}
        ok = (
            payload.get("contract") == "ea.aiwritebook.account_review"
            and account.get("plan") == "AppSumo Tier 4"
            and isinstance(account.get("credit_balance"), int)
            and posture.get("operator_required") is True
            and posture.get("unattended_automation_allowed") is False
            and actions.get("credits_spent") == 0
            and payload.get("secret_material_in_receipt") is False
        )
        return ok, "sanitized_account_review_present" if ok else "aiwritebook_account_review_missing_or_invalid"
    if key in {
        "aiwritebook_declared_limits",
        "aiwritebook_declared_privacy",
        "aiwritebook_declared_exports",
    }:
        payload = _json_receipt(
            root,
            "ea/_completion/aiwritebook/AIWRITEBOOK_ACCOUNT_REVIEW.generated.json",
            "_completion/aiwritebook/AIWRITEBOOK_ACCOUNT_REVIEW.generated.json",
            "config/provider_evidence/AIWRITEBOOK_ACCOUNT_REVIEW.source.json",
        )
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        pricing = evidence.get("pricing_surface") if isinstance(evidence.get("pricing_surface"), dict) else {}
        privacy = evidence.get("privacy_policy") if isinstance(evidence.get("privacy_policy"), dict) else {}
        terms = evidence.get("terms") if isinstance(evidence.get("terms"), dict) else {}
        if key == "aiwritebook_declared_limits":
            costs = pricing.get("credit_costs_observed") if isinstance(pricing.get("credit_costs_observed"), dict) else {}
            ok = (
                evidence.get("classification") == "read_only_authenticated_and_public_declared_policy"
                and pricing.get("account_tier_marked_current") is True
                and pricing.get("account_tier_marked_highest_appsumo_tier") is True
                and pricing.get("monthly_credit_allowance") == 5000
                and costs == {
                    "chapter_outline": 3,
                    "chapter_gemini": 15,
                    "chapter_grok": 20,
                    "chapter_claude": 30,
                    "book_cover": 30,
                    "translation_per_chapter": 15,
                    "translation_base": 30,
                    "audiobook_characters_per_credit": 25,
                }
            )
            return ok, "read_only_tier_and_credit_limits_captured" if ok else "aiwritebook_declared_limits_missing_or_invalid"
        if key == "aiwritebook_declared_privacy":
            ok = (
                privacy.get("last_updated") == "2026-01-25"
                and privacy.get("content_used_to_train_models") is False
                and privacy.get("content_shared_with_other_users") is False
                and privacy.get("content_retained_until_deleted_or_account_closed") is True
                and privacy.get("account_deletion_or_anonymization_window_days") == 90
                and privacy.get("runtime_behavior_canary_verified") is False
            )
            return ok, "declared_privacy_and_retention_captured" if ok else "aiwritebook_declared_privacy_missing_or_invalid"
        declared_formats = {"pdf", "epub", "docx"}
        ok = (
            set(pricing.get("export_formats_declared") or ()) == declared_formats
            and set(terms.get("export_formats_declared") or ()) == declared_formats
            and terms.get("user_content_ownership_declared") is True
            and terms.get("human_review_required") is True
            and terms.get("unauthorized_automated_access_prohibited") is True
        )
        return ok, "declared_export_and_terms_evidence_captured" if ok else "aiwritebook_declared_exports_missing_or_invalid"
    if key == "aiwritebook_operator_boundary":
        ok = {
            "provider_secret",
            "unattended_browser_automation",
            "credit_spend_without_approval",
            "direct_publish",
        } <= set(lane.forbidden_inputs)
        return ok, "operator_only_boundary_defined" if ok else "aiwritebook_operator_boundary_incomplete"
    if key == "aiwritebook_source_packet":
        ok = (
            "approved_consent_spoiler_redaction_reviewed_chummer_source_packet" in lane.allowed_inputs
            and "unapproved_source_packet" in lane.forbidden_inputs
            and "unredacted_gm_secret" in lane.forbidden_inputs
            and "source_packet_sha256" in lane.normalized_signal_schema
            and "source_packet_version" in lane.normalized_signal_schema
        )
        return ok, "approved_source_packet_boundary_defined" if ok else "aiwritebook_source_packet_boundary_incomplete"
    if key == "aiwritebook_human_review":
        approval_signals = {
            "upload_approval_status",
            "generation_approval_status",
            "outline_approval_status",
            "artifact_import_status",
            "publication_approval_status",
            "external_send_approval_status",
            "human_review_status",
        }
        ok = (
            {
                "source_upload_without_approval",
                "generation_without_approval",
                "external_send_without_approval",
                "direct_publish",
            } <= set(lane.forbidden_inputs)
            and approval_signals <= set(lane.normalized_signal_schema)
            and all(term in lane.source_of_truth.lower() for term in ("approval", "artifact", "publication truth"))
        )
        return ok, "separate_human_approval_boundary_defined" if ok else "aiwritebook_human_review_boundary_incomplete"
    if key == "aiwritebook_export_roundtrip":
        ok = _valid_aiwritebook_export_roundtrip_receipt(root)
        return ok, "approved_canary_export_passed" if ok else "aiwritebook_export_roundtrip_pending"
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
    if key == "vocallab_runtime_key_seeded":
        ok = _env_present(env, "VOCALLAB_API_KEY")
        return ok, "VOCALLAB_API_KEY_present_in_runtime" if ok else "VOCALLAB_API_KEY_missing_in_runtime"
    if key == "vocallab_registry_non_executable":
        source_path = root / "ea" / "app" / "services" / "provider_registry.py"
        source_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
        binding_marker = 'provider_key="vocallab"'
        binding_start = source_text.find(binding_marker)
        binding_window = source_text[binding_start : binding_start + 1800] if binding_start >= 0 else ""
        ok = (
            binding_start >= 0
            and 'executable=False' in binding_window
            and 'capability_key="voice_inventory"' in binding_window
            and 'capability_key="voice_render"' in binding_window
            and binding_window.count('executable=False') >= 3
        )
        return ok, "vocallab_registry_catalog_only" if ok else "vocallab_registry_execution_boundary_missing"
    if key == "vocallab_spend_controls_off":
        spend_switches = (
            "EA_AUDIOBOOK_VOCALLAB_ENABLED",
            "EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER",
            "EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES",
            "EA_AUDIOBOOK_VOCALLAB_ALLOW_TOPUP_POINTS",
        )
        enabled_values = {"1", "true", "yes", "on", "enabled"}
        enabled = [
            name
            for name in spend_switches
            if str(env.get(name) or "").strip().lower() in enabled_values
        ]
        return (not enabled), "vocallab_spend_controls_off" if not enabled else "vocallab_spend_control_enabled"
    if key == "vocallab_manfred_product_authority_boundary":
        required_forbidden = {
            "raw_voice_sample",
            "real_person_voice_upload",
            "unconsented_likeness",
            "manfred_product_authority",
            "publication_truth",
            "release_truth",
        }
        boundary = lane.source_of_truth.lower()
        ok = (
            required_forbidden <= set(lane.forbidden_inputs)
            and "separate manfred product exclusively owns authority" in boundary
            and "release truth" in boundary
        )
        return ok, "vocallab_manfred_product_authority_retained" if ok else "vocallab_manfred_product_authority_boundary_missing"
    if key == "emailit_provider_verification":
        row = discovery.get(_normalize("Emailit"), {})
        ok = (
            str(row.get("discovery_status") or "").strip().lower() in {"complete", "manual_seeded"}
            and "emailit_api_live" in str(row.get("verification_source") or "").strip().lower()
        )
        return ok, "recorded_emailit_api_live_proof" if ok else "emailit_provider_verification_missing"
    if key == "emailit_api_key_private":
        ok = _env_present(env, "EMAILIT_API_KEY")
        return ok, "EMAILIT_API_KEY_present_outside_git" if ok else "EMAILIT_API_KEY_missing"
    if key in {"emailit_delivery_adapter", "emailit_receipt_contract", "emailit_off_switch"}:
        source_path = root / "ea" / "app" / "services" / "registration_email.py"
        source_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
        if key == "emailit_delivery_adapter":
            required = ("EMAILIT_API_BASE", "def _send_emailit_email", "bounded_outbound_email")
            ok = all(token in source_text for token in required)
            return ok, "bounded_emailit_adapter_present" if ok else "emailit_delivery_adapter_missing"
        if key == "emailit_receipt_contract":
            required = ("class RegistrationEmailReceipt", "provider: str", "message_id: str", "accepted_at: str")
            ok = all(token in source_text for token in required)
            return ok, "emailit_provider_receipt_contract_present" if ok else "emailit_receipt_contract_missing"
        required_switches = {
            "EA_EMAILIT_DELIVERY_ENABLED",
            "EA_EMAILIT_OFFICE_DELIVERY_ENABLED",
            "PROPERTYQUARRY_EMAILIT_DELIVERY_ENABLED",
            "CHUMMER_HUB_EMAILIT_DELIVERY_ENABLED",
        }
        switch_declared = (
            required_switches <= set(lane.off_switch_env)
            and all(name in source_text for name in required_switches)
            and "registration_email_delivery_disabled" in source_text
        )
        switch_value = str(env.get("EA_EMAILIT_DELIVERY_ENABLED") or "").strip().lower()
        switch_engaged = switch_value in {"0", "false", "no", "off", "disabled"}
        ok = switch_declared and not switch_engaged
        if not switch_declared:
            return False, "emailit_off_switch_contract_missing"
        return ok, "emailit_off_switch_available" if ok else "emailit_off_switch_engaged"
    if key == "emailit_approval_suppression_boundary":
        forbidden = {
            "unapproved_marketing_broadcast",
            "unsuppressed_recipient",
            "direct_send_without_approval",
            "raw_gmail",
            "raw_calendar",
        }
        required_schema = {"recipient_sha256", "suppression_status", "approval_status", "provider_message_ref"}
        ok = (
            forbidden <= set(lane.forbidden_inputs)
            and required_schema <= set(lane.normalized_signal_schema)
            and "approval" in lane.source_of_truth.lower()
            and "suppression" in lane.source_of_truth.lower()
        )
        return ok, "emailit_approval_suppression_boundary_defined" if ok else "emailit_approval_suppression_boundary_missing"
    if key in {
        "fastestvpn_runtime_contract",
        "fastestvpn_ch_profile_boundary",
        "fastestvpn_secret_boundary",
        "fastestvpn_rate_limit_boundary",
        "fastestvpn_off_switch",
    }:
        compose_path = root / "docker-compose.fastestvpn.yml"
        dockerfile_path = root / "docker" / "fastestvpn-proxy" / "Dockerfile"
        ignore_path = root / ".dockerignore"
        live_ops_path = root / "scripts" / "ea_live_ops.py"
        compose_text = compose_path.read_text(encoding="utf-8") if compose_path.is_file() else ""
        dockerfile_text = dockerfile_path.read_text(encoding="utf-8") if dockerfile_path.is_file() else ""
        ignore_text = ignore_path.read_text(encoding="utf-8") if ignore_path.is_file() else ""
        live_ops_text = live_ops_path.read_text(encoding="utf-8") if live_ops_path.is_file() else ""
        if key == "fastestvpn_runtime_contract":
            ok = (
                "ea-fastestvpn-proxy-ch:" in compose_text
                and "FROM alpine:3.20@sha256:" in dockerfile_text
                and "no-new-privileges:true" in compose_text
            )
            return ok, "fastestvpn_pinned_runtime_contract" if ok else "fastestvpn_runtime_contract_missing"
        if key == "fastestvpn_ch_profile_boundary":
            ok = (
                "FASTESTVPN_CH_CONFIG_GLOB:-switzerland*.ovpn" in compose_text
                and "ONEMIN_DIRECT_API_PROXY_SERVER=http://ea-fastestvpn-proxy-ch" in compose_text
                and "--expected-proxy-country" in live_ops_text
            )
            return ok, "fastestvpn_ch_profile_and_country_contract" if ok else "fastestvpn_ch_profile_boundary_missing"
        if key == "fastestvpn_secret_boundary":
            ok = (
                "*.ovpn" in ignore_text
                and "proxy_secret_material_exposed" in live_ops_text
                and "raw_proxy_credential" in lane.forbidden_inputs
                and "raw_exit_ip_receipt" in lane.forbidden_inputs
            )
            return ok, "fastestvpn_secret_safe_receipt_contract" if ok else "fastestvpn_secret_boundary_missing"
        if key == "fastestvpn_rate_limit_boundary":
            ok = (
                "provider_rate_limit_evasion" in lane.forbidden_inputs
                and "resume_not_before" in live_ops_text
                and "retry_after_seconds" in live_ops_text
            )
            return ok, "fastestvpn_provider_cooldown_boundary" if ok else "fastestvpn_rate_limit_boundary_missing"
        deploy_path = root / "scripts" / "deploy.sh"
        deploy_text = deploy_path.read_text(encoding="utf-8") if deploy_path.is_file() else ""
        ok = "EA_ENABLE_FASTESTVPN" in lane.off_switch_env and "EA_ENABLE_FASTESTVPN" in deploy_text
        return ok, "fastestvpn_deployment_off_switch" if ok else "fastestvpn_off_switch_missing"
    if key in {
        "onemin_credential_pool",
        "onemin_scheduler_contract",
        "onemin_quota_controls",
        "onemin_secret_safe_receipt",
        "onemin_background_off_switch",
        "onemin_review_boundary",
    }:
        scheduler_path = root / "config" / "ltd_capacity_scheduler.yaml"
        blast_radius_path = root / "config" / "ltd_blast_radius.yaml"
        responses_path = root / "ea" / "app" / "services" / "responses_upstream.py"
        capacity_path = root / "scripts" / "materialize_ltd_capacity_status.py"
        scheduler_text = scheduler_path.read_text(encoding="utf-8") if scheduler_path.is_file() else ""
        blast_radius_text = blast_radius_path.read_text(encoding="utf-8") if blast_radius_path.is_file() else ""
        responses_text = responses_path.read_text(encoding="utf-8") if responses_path.is_file() else ""
        capacity_text = capacity_path.read_text(encoding="utf-8") if capacity_path.is_file() else ""
        if key == "onemin_credential_pool":
            manifest = root / "config" / "onemin_api_keys.local.json"
            ok = _env_present(env, "ONEMIN_AI_API_KEY") or manifest.is_file()
            return ok, "onemin_private_credential_pool_present" if ok else "onemin_credential_pool_missing"
        if key == "onemin_scheduler_contract":
            ok = (
                "1min.AI:" in scheduler_text
                and "default_policy: fail_closed" in scheduler_text
                and "public_safe" in blast_radius_text
                and "private_sensitive" in blast_radius_text
            )
            return ok, "onemin_bounded_scheduler_contract" if ok else "onemin_scheduler_contract_missing"
        if key == "onemin_quota_controls":
            required = (
                "EA_RESPONSES_ONEMIN_MAX_REQUESTS_PER_HOUR",
                "EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_HOUR",
                "EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_DAY",
                "EA_RESPONSES_ONEMIN_RATE_LIMIT_COOLDOWN_SECONDS",
            )
            ok = all(marker in responses_text for marker in required)
            return ok, "onemin_request_credit_ceiling_contract" if ok else "onemin_quota_controls_missing"
        if key == "onemin_secret_safe_receipt":
            ok = (
                '"secret_material_exposed": False' in capacity_text
                and '"credential_present"' in capacity_text
                and "credential_value" not in capacity_text
            )
            return ok, "onemin_secret_safe_capacity_receipt" if ok else "onemin_secret_safe_receipt_missing"
        if key == "onemin_background_off_switch":
            enabled_values = {"1", "true", "yes", "on", "enabled"}
            value = str(env.get("EA_RESPONSES_ONEMIN_BACKGROUND_REFRESH_ENABLED") or "1").strip().lower()
            declared = (
                "EA_RESPONSES_ONEMIN_BACKGROUND_REFRESH_ENABLED" in lane.off_switch_env
                and "EA_RESPONSES_ONEMIN_BACKGROUND_REFRESH_ENABLED" in responses_text
            )
            ok = declared and value in enabled_values
            return ok, "onemin_background_off_switch_available" if ok else "onemin_background_off_switch_engaged_or_missing"
        required_forbidden = {
            "raw_gmail",
            "raw_calendar",
            "people_memory",
            "secret_value",
            "unbounded_parallel_dispatch",
            "quota_bypass",
            "approval_truth",
            "product_truth",
            "release_truth",
        }
        ok = (
            required_forbidden <= set(lane.forbidden_inputs)
            and "ea owns task eligibility" in lane.source_of_truth.lower()
            and "release truth" in lane.source_of_truth.lower()
        )
        return ok, "onemin_ea_review_truth_boundary" if ok else "onemin_review_boundary_missing"
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
    if lane.lane_key == "aiwritebook_chronicle_studio":
        required_forbidden = {
            "provider_secret",
            "unattended_browser_automation",
            "credit_spend_without_approval",
            "source_upload_without_approval",
            "generation_without_approval",
            "external_send_without_approval",
            "direct_publish",
            "publication_truth",
            "rules_truth",
        }
        if not required_forbidden <= set(lane.forbidden_inputs):
            failures.append("aiwritebook_operator_boundary_incomplete")
        if "approved_consent_spoiler_redaction_reviewed_chummer_source_packet" not in lane.allowed_inputs:
            failures.append("aiwritebook_source_packet_missing")
        required_schema = {
            "source_packet_version",
            "source_packet_sha256",
            "upload_approval_status",
            "generation_approval_status",
            "outline_approval_status",
            "artifact_import_status",
            "publication_approval_status",
            "external_send_approval_status",
        }
        if not required_schema <= set(lane.normalized_signal_schema):
            failures.append("aiwritebook_approval_schema_incomplete")
        if "EA_AIWRITEBOOK_CHRONICLE_STUDIO_ENABLED" not in lane.off_switch_env:
            failures.append("aiwritebook_off_switch_missing")
    if lane.lane_key == "emailit_transactional_delivery":
        required_forbidden = {
            "raw_gmail",
            "raw_calendar",
            "unapproved_marketing_broadcast",
            "unsuppressed_recipient",
            "direct_send_without_approval",
            "support_truth",
            "billing_truth",
            "product_truth",
            "publication_truth",
        }
        if not required_forbidden <= set(lane.forbidden_inputs):
            failures.append("emailit_privacy_or_send_boundary_incomplete")
        required_schema = {"recipient_sha256", "suppression_status", "approval_status", "provider_message_ref", "delivery_status"}
        if not required_schema <= set(lane.normalized_signal_schema):
            failures.append("emailit_signal_schema_incomplete")
        required_switches = {
            "EA_EMAILIT_DELIVERY_ENABLED",
            "EA_EMAILIT_OFFICE_DELIVERY_ENABLED",
            "PROPERTYQUARRY_EMAILIT_DELIVERY_ENABLED",
            "CHUMMER_HUB_EMAILIT_DELIVERY_ENABLED",
        }
        if not required_switches <= set(lane.off_switch_env):
            failures.append("emailit_off_switch_missing")
        boundary = lane.source_of_truth.lower()
        if not all(owner in boundary for owner in ("ea-office", "propertyquarry", "chummer hub")):
            failures.append("emailit_product_ownership_boundary_missing")
    if lane.lane_key == "vocallab_catalog_authority":
        if lane.verified_state == "verified_runtime_lane":
            failures.append("vocallab_catalog_lane_must_not_be_runtime")
        required_forbidden = {
            "raw_voice_sample",
            "real_person_voice_upload",
            "unconsented_likeness",
            "automatic_voice_render",
            "automatic_voice_clone",
            "automatic_point_topup",
            "manfred_product_authority",
            "publication_truth",
            "release_truth",
        }
        if not required_forbidden <= set(lane.forbidden_inputs):
            failures.append("vocallab_authority_or_spend_boundary_incomplete")
        required_switches = {
            "EA_AUDIOBOOK_VOCALLAB_ENABLED",
            "EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER",
            "EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES",
            "EA_AUDIOBOOK_VOCALLAB_ALLOW_TOPUP_POINTS",
        }
        if not required_switches <= set(lane.off_switch_env):
            failures.append("vocallab_spend_switch_missing")
    if lane.lane_key == "fastestvpn_governed_provider_transport":
        required_forbidden = {
            "customer_public_ingress",
            "provider_rate_limit_evasion",
            "access_policy_bypass",
            "raw_proxy_credential",
            "raw_exit_ip_receipt",
            "account_truth",
            "quota_truth",
            "billing_truth",
            "product_truth",
            "release_truth",
        }
        if not required_forbidden <= set(lane.forbidden_inputs):
            failures.append("fastestvpn_transport_boundary_incomplete")
        if "EA_ENABLE_FASTESTVPN" not in lane.off_switch_env:
            failures.append("fastestvpn_off_switch_missing")
    if lane.lane_key == "onemin_bounded_capacity_scheduler":
        required_forbidden = {
            "raw_gmail",
            "raw_calendar",
            "people_memory",
            "unredacted_attachment",
            "secret_value",
            "unbounded_parallel_dispatch",
            "quota_bypass",
            "provider_rate_limit_evasion",
            "automatic_publication",
            "approval_truth",
            "product_truth",
            "release_truth",
        }
        if not required_forbidden <= set(lane.forbidden_inputs):
            failures.append("onemin_capacity_boundary_incomplete")
        if "EA_RESPONSES_ONEMIN_BACKGROUND_REFRESH_ENABLED" not in lane.off_switch_env:
            failures.append("onemin_background_off_switch_missing")
        required_schema = {
            "task_class",
            "credential_present",
            "maximum_blast_radius",
            "quota_state",
            "dispatch_state",
            "receipt_sha256",
            "owner_review_required",
        }
        if not required_schema <= set(lane.normalized_signal_schema):
            failures.append("onemin_capacity_signal_schema_incomplete")
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
