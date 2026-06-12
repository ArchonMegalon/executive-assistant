from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Mapping

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
        lane_key="unmixr_voice_runtime",
        title="Unmixr Governed Voice Runtime",
        providers=("Unmixr AI",),
        integration_lane="voice_tts_runtime",
        verified_state="verified_runtime_lane",
        missing_state="blocked_pending_proof",
        off_switch_env=("EA_UNMIXR_VOICE_RUNTIME_ENABLED", "EA_MEMORIAL_UNMIXR_ENABLED"),
        source_of_truth="EA consent registry and runtime config own voice eligibility truth; Unmixr only synthesizes approved text.",
        allowed_inputs=("consented_memorial_tts", "chummer_promo_narration", "black_ledger_dispatch_narration"),
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
            "private_memorial_memory",
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
        allowed_inputs=("public_ui_release_candidate", "memorial_landing_change", "black_ledger_newsroom_change", "security_scan_target"),
        forbidden_inputs=("product_truth", "release_truth", "roadmap_truth", "direct_publish", "source_code_mutation"),
        normalized_signal_schema=(),
        required_checks=(
            LaneCheck("rafter_fleet_verified", "Rafter Fleet provider verification passes.", "Fleet Rafter proof receipt."),
            LaneCheck("pixefy_fleet_verified", "Pixefy Fleet visual QA verification passes.", "Fleet Pixefy proof receipt."),
            LaneCheck("ci_targets", "CI targets exist for both gates.", "Make targets or gate scripts."),
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
        forbidden_inputs=("direct_publish", "unconsented_likeness", "private_memorial_memory", "sourcebook_text", "product_proof"),
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
    if key in {"inventory_recorded", "providers_recorded"}:
        ok = _all_providers_present(lane, inventory)
        return ok, "inventory_rows_present" if ok else "inventory_rows_missing"
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
            "ea/docs/memorial_realtime_voice_redesign.md",
            "docs/memorial_realtime_voice_redesign.md",
        )
        return ok, "fallback_policy_present" if ok else "fallback_policy_missing"
    if key in {"commercial_use", "watermark_export", "watermark_duration_export", "credit_budget", "safety_scan", "human_review", "likeness_policy", "quality_score"}:
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
    if key == "normalized_schema":
        ok = bool(lane.normalized_signal_schema)
        return ok, "schema_defined" if ok else "schema_missing"
    if key == "api_or_export_proof":
        row = discovery.get(_normalize("Prompt Architects"), {})
        ok = "prompt_foundry" in str(row.get("verification_source") or row.get("notes") or "").lower()
        return ok, "prompt_foundry_receipt_recorded" if ok else "prompt_foundry_receipt_missing"
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
        merged_env.update({key: value for key, value in os.environ.items() if value})
        dot_env = _load_dotenv(resolved_root / ".env")
        dot_env.update(merged_env)
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
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "contract_name": "ea.verify_ltd_provider_lanes",
        "status": "pass" if not failures else "fail",
        "lane_count": len(receipts),
        "verified_or_blocked_count": sum(1 for receipt in receipts if receipt["status"] == "pass"),
        "failures": failures,
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
