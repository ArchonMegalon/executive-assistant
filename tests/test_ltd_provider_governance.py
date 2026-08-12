from __future__ import annotations

from dataclasses import replace
import json
import subprocess
import sys
from pathlib import Path

from app.services.ltd_provider_governance import (
    LANES,
    build_ltd_provider_governance_receipt,
    build_ltd_provider_lane_receipt,
    lane_by_key,
    materialize_ltd_provider_governance_receipts,
)
from app.services.ltd_runtime_catalog import load_ltd_inventory_rows
from scripts.materialize_ea_provider_contract_receipts import build_receipts as build_provider_contract_receipts


ROOT = Path(__file__).resolve().parents[1]


def _sample_ltd_markdown() -> str:
    return """
# LTDs

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `blipai` | `No tier recorded` | `1 account` | `Owned` |  | `Tier 4` | Local credentials | Operator note capture only. |
| `hedy.ai` | `LTD account` | `1 account` | `Owned` |  | `Tier 4` | Governed meeting-evidence lane defined | Hedy captures consented transcripts only; EA owns evidence, commitment, decision, draft and people-memory truth. |
| `Teable` | `Tier 2` | `1 account` | `Owned` |  | `Tier 2` | Projection adapter | Projection only, not source of truth. |
| `Syllabbles` | `No tier recorded` | `1 account` | `Owned` |  | `Tier 4` | Draft workbench | Dispatch draft only. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `FlipLink.me` | `Tier 10` | `1 account` | `Owned` |  | `Tier 3` | Candidate document portal | Must not host sourcebook PDFs, copied rulebook prose, private runner sheets, GM-only secrets, entitlement truth, or payment truth. |
| `ApproveThis` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | Governed external approval edge defined | Transport only; EA owns approval truth and downstream policy. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | Governed premium renderer lane defined | Renders approved packets only, not source of truth. |
| `Unmixr AI` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 2` | Local UNMIXR_* env contract | Piper fallback policy remains active; live API key and voice ID pending. |
| `MagicFit` | `License Tier 5` | `3 accounts` | `Owned` |  | `Tier 4` | Candidate adapter | Commercial-use, watermark, export, credit, safety scan, human review, quality and likeness proof pending. |
| `Poppy AI` | `Tier 6` | `1 account` | `Owned` |  | `Tier 4` | BrowserAct session probe | Session proof exists; privacy review, export semantics, tenant isolation, source of truth boundary and runtime-boundary proof pending. |
| `Rafter` | `License Tier 3` | `1 account` | `Owned` |  | `Tier 2` | Fleet security/proof gate verified | Auxiliary security evidence only; not product truth, release truth, roadmap truth, or publish changes. |
| `Pixefy` | `License Tier 3` | `1 account` | `Owned` |  | `Tier 2` | Fleet responsive visual QA gate verified | Visual QA only, not product truth. |
| `ProductLift.dev` | `License Tier 5` | `1 license` | `Activated` |  | `Tier 2` | Signal mirror | Public signal mirror; Chummer remains source of truth. |
| `MetaSurvey` | `Plus exclusive` | `3 codes` | `Activated` |  | `Tier 2` | Survey extraction | Feedback mirror only. |
| `Deftform` | `No tier recorded` | `1 account` | `Owned` |  | `Tier 4` | Credentials only | Form intake candidate. |
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 4` | Credentials only | Cited docs and freshness check required. |
| `Paperguide` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Research packets only. |
| `First Book ai` | `License Tier 5` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct credentials | Long-form guide drafts only. |
| `katteb.com` | `10x code-based` | `10 codes` | `Owned` |  | `Tier 4` | Credentials only | Article drafts only. |
| `Prompt Architects` | `Tier 4` | `1 account` | `Activated` |  | `Tier 4` | PROMPTING_SYSTEMS_API_KEY | Prompt Foundry receipts verify template seed/operator assist, retention and tenant isolation boundary. |
| `AiWriteBook` | `Tier 4` | `1 account` | `Owned` |  | `Tier 2` | Governed operator handoff | Chummer owns approved source packets and publication truth; no unattended browser automation or direct publish. |
| `VidBoard.ai` | `Tier 5` | `1 account` | `Owned` |  | `Tier 4` | Credentials | Commercial-use, watermark, duration, export, likeness and quality proof pending. |
| `FacePop` | `Tier 5` | `1 account` | `Activated` |  | `Tier 4` | Credentials | Presenter candidate only. |
| `Nonverbia` | `Tier 4` | `1 account` | `Activated` |  | `Tier 2` | BrowserAct credentials | Presenter candidate only. |
| `Mootion` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | Scaffold packets | Motion candidate only. |
| `AvoMap` | `10x code-based` | `10 codes` | `Activated` |  | `Tier 2` | Scaffold packets | Map/B-roll candidate only. |
| `JoggAI` | `License Tier 4 / Team updates` | `1 account` | `Owned` |  | `Tier 4` | Local credentials/API status pending | Memorial video render candidate only. |
| `Lunacal` | `Tier 4` | `1 account` | `Activated` |  | `Tier 4` | Credentials | Booking candidate. |
| `Signitic` | `Tier 4` | `1 account` | `Activated` |  | `Tier 4` | Credentials | Signature template candidate. |
| `GetNextStep.io` | `Tier 5` | `1 account` | `Activated` |  | `Tier 4` | Credentials | Strategy workbench only. |
| `ICanpreneur` | `Tier 3` | `1 account` | `Activated` |  | `Tier 4` | Credentials | Validation workbench only. |
| `Sendr` | `License Tier 4` | `1 lifetime license` | `Owned / activated` |  | `Tier 4` | Governed EA outbound-growth lane scaffold | EA approved campaign packets only; no raw Gmail, raw Calendar, people memory, private commitments, customer drafts, direct send, auto-reply, WhatsApp, or product truth. |

## Discovery Tracking

| Service | Account | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `FlipLink.me` |  | `manual_seeded` | `user_reported` | 2026-06-05T00:00:00Z | Provider verification pending. |
| `ApproveThis` |  | `manual_seeded` | `manual_inventory` | 2026-06-18T00:00:00Z | Governed external approval edge defined; live provider proof pending. |
| `MarkupGo` |  | `manual_seeded` | `manual_inventory` | 2026-06-18T00:00:00Z | Governed premium renderer lane defined; provider proof pending. |
| `hedy.ai` | `ltd.account@example.test` | `manual_seeded` | `local_env` | 2026-06-18T00:00:00Z | Governed meeting-evidence lane defined; provider proof pending. |
| `Unmixr AI` | `ltd.account@example.test` | `manual_seeded` | `user_report + local_runtime_docs` | 2026-06-03T09:58:09Z | API key and voice ID pending. |
| `Poppy AI` | `ltd.account@example.test` | `user_reported` | `live_google_session_probe` | 2026-06-09T10:25:00Z | Session proof recorded; privacy, export and tenant isolation still pending. |
| `Rafter` | `ltd.account@example.test` | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | Fleet proof passes. |
| `Pixefy` | `ltd.account@example.test` | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | Fleet proof passes. |
| `Prompt Architects` |  | `manual_seeded` | `local_env + prompt_foundry_receipts` | 2026-06-01T20:54:48Z | Prompt Foundry receipts exist. |
| `AiWriteBook` | `gmail.com` | `complete` | `authenticated_sanitized_account_review` | 2026-08-11T07:33:00Z | AppSumo Tier 4 verified; operator-only lane, export canary pending. |
| `Sendr` |  | `manual_seeded` | `user_report_tier4 + governed_lane_scaffold` | 2026-06-30T20:45:00Z | License Tier 4 is recorded; EA campaign packet, provider proof, suppression sync, and human approval receipts remain pending. |
""".strip()


def _write_ltd(tmp_path: Path) -> Path:
    path = tmp_path / "LTDs.md"
    path.write_text(_sample_ltd_markdown(), encoding="utf-8")
    return path


def _minimal_ltds(markdown_row: str, discovery_row: str) -> str:
    return f"""# LTDs

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
{markdown_row}

## Discovery Tracking

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
{discovery_row}
"""


def test_all_requested_ltd_provider_lanes_are_defined() -> None:
    keys = {lane.lane_key for lane in LANES}
    assert keys >= {
        "hedy_meeting_evidence",
        "markupgo_fliplink_premium_delivery",
        "fliplink_document_portal",
        "approvethis_external_approval_edge",
        "documentation_ai_publication",
        "unmixr_voice_runtime",
        "magicfit_media_factory_candidate",
        "poppy_draft_workbench",
        "release_quality_gates",
        "public_signal_ingest",
        "docs_draft_factory",
        "prompt_foundry",
        "aiwritebook_chronicle_studio",
        "subscribr_chummer_script_factory",
        "sendr_ea_growth_outreach",
        "operator_control_plane",
        "video_provider_bakeoff",
        "commercial_ops",
    }


def test_every_lane_has_off_switch_and_not_source_of_truth_boundary() -> None:
    for lane in LANES:
        assert lane.off_switch_env, lane.lane_key
        assert "truth" in lane.source_of_truth.lower(), lane.lane_key
        assert lane.forbidden_inputs, lane.lane_key


def test_lane_boundaries_match_provider_risks() -> None:
    fliplink = lane_by_key("fliplink_document_portal")
    assert fliplink is not None
    assert {"sourcebook_pdf", "copied_rulebook_prose", "private_runner_sheet", "gm_only_campaign_secret"} <= set(
        fliplink.forbidden_inputs
    )

    unmixr = lane_by_key("unmixr_voice_runtime")
    assert unmixr is not None
    assert {"ad_hoc_public_voice_cloning", "user_supplied_voice_id", "committed_provider_voice_id"} <= set(
        unmixr.forbidden_inputs
    )

    poppy = lane_by_key("poppy_draft_workbench")
    assert poppy is not None
    assert {"private_campaign_data", "user_submission", "product_truth"} <= set(
        poppy.forbidden_inputs
    )

    video = lane_by_key("video_provider_bakeoff")
    assert video is not None
    assert {"direct_publish", "unconsented_likeness", "product_proof"} <= set(video.forbidden_inputs)
    assert "JoggAI" in set(video.providers)

    subscribr = lane_by_key("subscribr_chummer_script_factory")
    assert subscribr is not None
    assert subscribr.providers == ("Subscribr",)
    assert subscribr.integration_lane == "video_script_preproduction"
    assert subscribr.verified_state == "verified_draft_operator_lane"
    assert "EA_SUBSCRIBR_DIRECT_PUBLISH_ENABLED" in subscribr.off_switch_env
    assert "approved_public_source_packet" in subscribr.allowed_inputs
    assert {"direct_publish", "publication_approval", "rules_truth", "release_truth"} <= set(subscribr.forbidden_inputs)

    sendr = lane_by_key("sendr_ea_growth_outreach")
    assert sendr is not None
    assert sendr.providers == ("Sendr",)
    assert sendr.integration_lane == "governed_outbound_growth"
    assert "EA_SENDR_DIRECT_SEND_ENABLED" in sendr.off_switch_env
    assert "EA_SENDR_AUTO_REPLY_ENABLED" in sendr.off_switch_env
    assert "EA_SENDR_PRIVATE_WORKSPACE_DATA_ALLOWED" in sendr.off_switch_env
    assert {"raw_gmail", "raw_calendar", "people_memory", "private_commitment", "private_decision"} <= set(
        sendr.forbidden_inputs
    )
    assert {"recipient_basis", "suppression_status", "reply_event_hash", "human_review_status"} <= set(
        sendr.normalized_signal_schema
    )

    aiwritebook = lane_by_key("aiwritebook_chronicle_studio")
    assert aiwritebook is not None
    assert "approved_consent_spoiler_redaction_reviewed_chummer_source_packet" in aiwritebook.allowed_inputs
    assert {
        "source_upload_without_approval",
        "generation_without_approval",
        "external_send_without_approval",
    } <= set(aiwritebook.forbidden_inputs)
    assert {
        "source_packet_version",
        "source_packet_sha256",
        "upload_approval_status",
        "generation_approval_status",
        "outline_approval_status",
        "artifact_import_status",
        "publication_approval_status",
        "external_send_approval_status",
    } <= set(aiwritebook.normalized_signal_schema)

    hedy = lane_by_key("hedy_meeting_evidence")
    assert hedy is not None
    assert hedy.providers == ("Hedy.ai",)
    assert "consented_meeting_transcript" in hedy.allowed_inputs
    assert {"unconsented_recording", "direct_commitment_creation", "direct_people_memory_overwrite"} <= set(
        hedy.forbidden_inputs
    )
    assert "EA_HEDY_WEBHOOKS_ENABLED" in hedy.off_switch_env

    premium = lane_by_key("markupgo_fliplink_premium_delivery")
    assert premium is not None
    assert premium.providers == ("MarkupGo", "FlipLink.me")
    assert {"content_mutation", "unredacted_board_material", "access_grant_truth", "direct_publish"} <= set(
        premium.forbidden_inputs
    )
    assert "rendered_artifact_hash" in premium.normalized_signal_schema

    approvethis = lane_by_key("approvethis_external_approval_edge")
    assert approvethis is not None
    assert {"replace_internal_queue", "direct_downstream_action", "approval_without_ea_policy", "approval_truth"} <= set(
        approvethis.forbidden_inputs
    )
    assert "ea_decision_id" in approvethis.normalized_signal_schema

    docs = lane_by_key("documentation_ai_publication")
    assert docs is not None
    assert {"workspace_data", "customer_support_ticket", "private_incident_log", "silent_writeback"} <= set(
        docs.forbidden_inputs
    )
    assert "EA_DOCUMENTATION_AI_AGENT_WRITEBACK_ENABLED" in docs.off_switch_env

    release = lane_by_key("release_quality_gates")
    assert release is not None
    assert "release_truth" in release.forbidden_inputs
    assert "ea_app_surface_release_candidate" in release.allowed_inputs

    aiwritebook = lane_by_key("aiwritebook_chronicle_studio")
    assert aiwritebook is not None
    assert aiwritebook.providers == ("AiWriteBook",)
    assert aiwritebook.integration_lane == "operator_required_book_production"
    assert "approved_consent_spoiler_redaction_reviewed_chummer_source_packet" in aiwritebook.allowed_inputs
    assert {
        "provider_secret",
        "unattended_browser_automation",
        "credit_spend_without_approval",
        "source_upload_without_approval",
        "generation_without_approval",
        "external_send_without_approval",
        "direct_publish",
        "publication_truth",
        "rules_truth",
    } <= set(aiwritebook.forbidden_inputs)
    assert {
        "source_packet_version",
        "upload_approval_status",
        "generation_approval_status",
        "external_send_approval_status",
    } <= set(aiwritebook.normalized_signal_schema)


def test_public_signal_lane_schema_is_single_normalized_object() -> None:
    lane = lane_by_key("public_signal_ingest")
    assert lane is not None
    assert set(lane.normalized_signal_schema) == {
        "source",
        "author_contact",
        "project",
        "feature_request_category",
        "severity_value",
        "public_private_flag",
        "consent_to_contact",
        "raw_payload_hash",
    }


def test_receipts_pass_hard_contracts_even_when_proofs_are_missing(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    receipt = build_ltd_provider_governance_receipt(
        markdown_path=ltd_path,
        env={},
        generated_at="2026-06-10T00:00:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["lane_count"] == len(LANES)
    lanes = {str(row["lane_key"]): row for row in receipt["lanes"]}
    assert lanes["fliplink_document_portal"]["not_source_of_truth"] is True
    assert lanes["fliplink_document_portal"]["lane_state"] == "blocked_pending_proof"
    assert "first_publication_receipt" in lanes["fliplink_document_portal"]["missing_checks"]
    assert lanes["release_quality_gates"]["lane_state"] in {"verified_runtime_lane", "blocked_pending_proof"}
    assert lanes["public_signal_ingest"]["normalized_signal_schema"]


def test_aiwritebook_lane_accepts_sanitized_account_review_but_waits_for_export_canary(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "ea" / "_completion" / "aiwritebook"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "AIWRITEBOOK_ACCOUNT_REVIEW.generated.json").write_text(
        json.dumps(
            {
                "contract": "ea.aiwritebook.account_review",
                "status": "operator_review",
                "account": {"plan": "AppSumo Tier 4", "credit_balance": 5100},
                "evidence": {
                    "classification": "read_only_authenticated_and_public_declared_policy",
                    "pricing_surface": {
                        "account_tier_marked_current": True,
                        "account_tier_marked_highest_appsumo_tier": True,
                        "monthly_credit_allowance": 5000,
                        "export_formats_declared": ["pdf", "epub", "docx"],
                        "credit_costs_observed": {
                            "chapter_outline": 3,
                            "chapter_gemini": 15,
                            "chapter_grok": 20,
                            "chapter_claude": 30,
                            "book_cover": 30,
                            "translation_per_chapter": 15,
                            "translation_base": 30,
                            "audiobook_characters_per_credit": 25,
                        },
                    },
                    "privacy_policy": {
                        "last_updated": "2026-01-25",
                        "content_used_to_train_models": False,
                        "content_shared_with_other_users": False,
                        "content_retained_until_deleted_or_account_closed": True,
                        "account_deletion_or_anonymization_window_days": 90,
                        "runtime_behavior_canary_verified": False,
                    },
                    "terms": {
                        "user_content_ownership_declared": True,
                        "human_review_required": True,
                        "unauthorized_automated_access_prohibited": True,
                        "export_formats_declared": ["pdf", "epub", "docx"],
                    },
                },
                "automation_posture": {"operator_required": True, "unattended_automation_allowed": False},
                "review_actions": {"credits_spent": 0},
                "secret_material_in_receipt": False,
            }
        ),
        encoding="utf-8",
    )
    inventory_path = tmp_path / "LTDs.md"
    inventory_path.write_text(
        _minimal_ltds(
            "| `AiWriteBook` | `Tier 4` | `1 account` | `Owned` |  | `Tier 2` | Governed operator handoff | Chummer owns publication truth. |",
            "| `AiWriteBook` | `gmail.com` | `complete` | `authenticated_sanitized_account_review` | 2026-08-11T07:33:00Z | Operator-only lane. |",
        ),
        encoding="utf-8",
    )
    lane = lane_by_key("aiwritebook_chronicle_studio")
    assert lane is not None

    result = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=inventory_path.read_text(encoding="utf-8"),
        inventory_rows=load_ltd_inventory_rows(inventory_path),
        root=tmp_path,
        env={},
        generated_at="2026-08-11T08:00:00Z",
    )

    assert result["status"] == "pass"
    assert result["lane_state"] == "blocked_pending_proof"
    assert "aiwritebook_account_review" in result["passed_checks"]
    assert "aiwritebook_declared_limits" in result["passed_checks"]
    assert "aiwritebook_declared_privacy" in result["passed_checks"]
    assert "aiwritebook_declared_exports" in result["passed_checks"]
    assert "aiwritebook_operator_boundary" in result["passed_checks"]
    assert "aiwritebook_source_packet" in result["passed_checks"]
    assert result["missing_checks"] == ["aiwritebook_export_roundtrip"]
    assert result["runtime_enabled"] is False


def test_aiwritebook_account_review_materializes_from_tracked_sanitized_source(tmp_path: Path) -> None:
    source = ROOT / "config" / "provider_evidence" / "AIWRITEBOOK_ACCOUNT_REVIEW.source.json"
    output = tmp_path / "AIWRITEBOOK_ACCOUNT_REVIEW.generated.json"
    script = ROOT / "scripts" / "materialize_aiwritebook_account_review.py"
    first = subprocess.run(
        [sys.executable, str(script), "--source", str(source), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    first_rendered = output.read_text(encoding="utf-8")
    second = subprocess.run(
        [sys.executable, str(script), "--source", str(source), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert output.read_text(encoding="utf-8") == first_rendered
    payload = json.loads(first_rendered)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["contract"] == "ea.aiwritebook.account_review"
    assert payload["account"]["plan"] == "AppSumo Tier 4"
    assert payload["evidence"]["pricing_surface"]["monthly_credit_allowance"] == 5000
    assert set(payload["evidence"]["pricing_surface"]["export_formats_declared"]) == {"pdf", "epub", "docx"}
    assert payload["evidence"]["privacy_policy"]["content_used_to_train_models"] is False
    assert payload["evidence"]["privacy_policy"]["runtime_behavior_canary_verified"] is False
    assert payload["evidence"]["terms"]["unauthorized_automated_access_prohibited"] is True
    assert payload["automation_posture"]["operator_required"] is True
    assert payload["automation_posture"]["unattended_automation_allowed"] is False
    assert payload["review_actions"] == {
        "credits_spent": 0,
        "source_uploaded": False,
        "generation_started": False,
        "publication_started": False,
        "external_send_performed": False,
    }
    assert payload["secret_material_in_receipt"] is False
    assert "@" not in serialized
    assert "password" not in serialized.lower()


def test_aiwritebook_governance_accepts_tracked_source_when_generated_receipt_is_absent(tmp_path: Path) -> None:
    source_dir = tmp_path / "config" / "provider_evidence"
    source_dir.mkdir(parents=True)
    source_dir.joinpath("AIWRITEBOOK_ACCOUNT_REVIEW.source.json").write_text(
        (ROOT / "config" / "provider_evidence" / "AIWRITEBOOK_ACCOUNT_REVIEW.source.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    inventory_path = tmp_path / "LTDs.md"
    inventory_path.write_text(
        _minimal_ltds(
            "| `AiWriteBook` | `Tier 4` | `1 account` | `Owned` |  | `Tier 2` | Governed operator handoff | Chummer owns publication truth. |",
            "| `AiWriteBook` | `gmail.com` | `complete` | `authenticated_sanitized_account_review` | 2026-08-11T08:14:11Z | Operator-only lane. |",
        ),
        encoding="utf-8",
    )
    lane = lane_by_key("aiwritebook_chronicle_studio")
    assert lane is not None

    result = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=inventory_path.read_text(encoding="utf-8"),
        inventory_rows=load_ltd_inventory_rows(inventory_path),
        root=tmp_path,
        env={},
        generated_at="2026-08-11T08:20:00Z",
    )

    assert {
        "aiwritebook_account_review",
        "aiwritebook_declared_limits",
        "aiwritebook_declared_privacy",
        "aiwritebook_declared_exports",
    } <= set(result["passed_checks"])
    assert result["missing_checks"] == ["aiwritebook_export_roundtrip"]


def test_aiwritebook_governance_accepts_tracked_sanitized_roundtrip_on_fresh_checkout(tmp_path: Path) -> None:
    source_dir = tmp_path / "config" / "provider_evidence"
    source_dir.mkdir(parents=True)
    for filename in (
        "AIWRITEBOOK_ACCOUNT_REVIEW.source.json",
        "AIWRITEBOOK_EXPORT_ROUNDTRIP.source.json",
    ):
        source_dir.joinpath(filename).write_text(
            (ROOT / "config" / "provider_evidence" / filename).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    inventory_path = tmp_path / "LTDs.md"
    inventory_path.write_text(
        _minimal_ltds(
            "| `AiWriteBook` | `Tier 4` | `1 account` | `Owned` |  | `Tier 2` | Governed operator handoff | Chummer owns publication truth. |",
            "| `AiWriteBook` | `gmail.com` | `complete` | `authenticated_sanitized_account_review_and_canary` | 2026-08-11T13:30:18Z | Operator-only lane. |",
        ),
        encoding="utf-8",
    )
    lane = lane_by_key("aiwritebook_chronicle_studio")
    assert lane is not None

    result = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=inventory_path.read_text(encoding="utf-8"),
        inventory_rows=load_ltd_inventory_rows(inventory_path),
        root=tmp_path,
        env={},
        generated_at="2026-08-11T13:31:00Z",
    )

    assert result["status"] == "pass"
    assert result["lane_state"] == "verified_draft_operator_lane"
    assert result["missing_checks"] == []
    assert "aiwritebook_export_roundtrip" in result["passed_checks"]
    assert result["runtime_enabled"] is False


def test_priority_ltd_lanes_are_bounded_until_live_proof_exists(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    markdown_text = ltd_path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(ltd_path)

    expectations = {
        "hedy_meeting_evidence": {
            "passed": {"inventory_recorded", "hedy_consent_gate", "hedy_review_gate", "hedy_memory_promotion_gate"},
            "missing": {"hedy_provider_capability", "hedy_webhook_signature"},
        },
        "markupgo_fliplink_premium_delivery": {
            "passed": {"providers_recorded", "premium_source_packet", "human_review"},
            "missing": {"markupgo_provider_proof", "premium_delivery_receipt"},
        },
        "approvethis_external_approval_edge": {
            "passed": {"inventory_recorded", "approvethis_external_scope", "approvethis_final_policy_gate"},
            "missing": {"approvethis_provider_capability", "approvethis_webhook_signature"},
        },
        "documentation_ai_publication": {
            "passed": {"inventory_recorded", "documentation_git_source_of_truth", "documentation_no_writeback", "documentation_privacy_boundary"},
            "missing": {"documentation_ai_provider_capability", "documentation_llms_txt"},
        },
        "sendr_ea_growth_outreach": {
            "passed": {
                "inventory_recorded",
                "sendr_recipient_basis",
                "sendr_claim_validation",
                "sendr_privacy_boundary",
                "sendr_human_review",
                "sendr_reply_ingest",
            },
            "missing": {"sendr_provider_verification", "sendr_suppression_sync"},
        },
    }

    for lane_key, expected in expectations.items():
        lane = lane_by_key(lane_key)
        assert lane is not None
        receipt = build_ltd_provider_lane_receipt(
            lane,
            markdown_text=markdown_text,
            inventory_rows=inventory_rows,
            env={},
            root=tmp_path,
            generated_at="2026-06-18T00:00:00Z",
        )
        assert receipt["status"] == "pass"
        assert receipt["lane_state"] == "blocked_pending_proof"
        assert receipt["runtime_enabled"] is False
        assert expected["passed"] <= set(receipt["passed_checks"])
        assert expected["missing"] <= set(receipt["missing_checks"])


def test_priority_ltd_lanes_use_contract_receipts_without_promoting_live_runtime(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    build_provider_contract_receipts(
        output_dir=tmp_path / "_completion" / "ea_provider_contracts",
        generated_at="2026-06-18T00:00:00Z",
        source_git_head="contract-head",
    )
    markdown_text = ltd_path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(ltd_path)

    expectations = {
        "hedy_meeting_evidence": {
            "contract_sources": {
                "hedy_consent_gate": "hedy_contract_receipt_consent_gate",
                "hedy_webhook_signature": "hedy_contract_receipt_webhook_signature",
                "hedy_session_mapping": "hedy_contract_receipt_session_mapping",
            },
            "live_missing": {"hedy_provider_capability"},
        },
        "markupgo_fliplink_premium_delivery": {
            "contract_sources": {
                "premium_source_packet": "premium_contract_receipt_source_packet",
                "premium_artifact_hash": "premium_contract_receipt_artifact_hash",
            },
            "live_missing": {"markupgo_provider_proof", "premium_delivery_receipt"},
        },
        "approvethis_external_approval_edge": {
            "contract_sources": {
                "approvethis_external_scope": "approvethis_contract_receipt_external_scope",
                "approvethis_webhook_signature": "approvethis_contract_receipt_webhook_signature",
                "approvethis_evidence_mapping": "approvethis_contract_receipt_evidence_mapping",
            },
            "live_missing": {"approvethis_provider_capability"},
        },
        "documentation_ai_publication": {
            "contract_sources": {
                "documentation_git_source_of_truth": "documentation_contract_receipt_git_truth",
                "documentation_no_writeback": "documentation_contract_receipt_no_writeback",
            },
            "live_missing": {"documentation_ai_provider_capability", "documentation_llms_txt"},
        },
        "release_quality_gates": {
            "contract_sources": {
                "ea_security_targets": "quality_contract_receipt_security_targets",
                "ea_visual_targets": "quality_contract_receipt_visual_targets",
                "release_truth_boundary": "quality_contract_receipt_release_truth_boundary",
            },
            "live_missing": set(),
        },
    }

    for lane_key, expected in expectations.items():
        lane = lane_by_key(lane_key)
        assert lane is not None
        receipt = build_ltd_provider_lane_receipt(
            lane,
            markdown_text=markdown_text,
            inventory_rows=inventory_rows,
            env={},
            root=tmp_path,
            generated_at="2026-06-18T00:00:00Z",
        )
        checks = {str(row["check_key"]): row for row in receipt["required_checks"]}
        for check_key, source in expected["contract_sources"].items():
            assert checks[check_key]["passed"] is True
            assert checks[check_key]["source"] == source
        assert expected["live_missing"] <= set(receipt["missing_checks"])
        if expected["live_missing"]:
            assert receipt["lane_state"] == "blocked_pending_proof"
            assert receipt["runtime_enabled"] is False


def test_aggregate_ltd_governance_summarizes_contract_proof_without_live_overclaim(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    build_provider_contract_receipts(
        output_dir=tmp_path / "_completion" / "ea_provider_contracts",
        generated_at="2026-06-18T00:00:00Z",
        source_git_head="contract-head",
    )

    receipt = build_ltd_provider_governance_receipt(
        markdown_path=ltd_path,
        root=tmp_path,
        env={},
        generated_at="2026-06-18T00:00:00Z",
    )

    provider_contracts = dict(receipt["provider_contracts"])
    assert provider_contracts["local_contracts_present"] is True
    assert provider_contracts["status"] == "contract_pass_live_provider_pending"
    assert provider_contracts["proof_scope"] == "local_contract_exercise"
    assert provider_contracts["live_provider_runtime_verified"] is False
    assert provider_contracts["gold_claim_allowed"] is False
    assert "_completion/hedy/HEDY_PROVIDER_CAPABILITY.generated.json" in provider_contracts["required_next_receipts"]
    assert receipt["contract_backed_check_count"] >= 10
    backed = {
        (str(row["lane_key"]), str(row["check_key"]), str(row["source"]))
        for row in list(receipt["contract_backed_checks"])
    }
    assert (
        "hedy_meeting_evidence",
        "hedy_webhook_signature",
        "hedy_contract_receipt_webhook_signature",
    ) in backed
    assert (
        "documentation_ai_publication",
        "documentation_no_writeback",
        "documentation_contract_receipt_no_writeback",
    ) in backed


def test_priority_ltd_lane_hard_contracts_prevent_scope_creep() -> None:
    from app.services.ltd_provider_governance import _hard_contract_failures

    hedy = lane_by_key("hedy_meeting_evidence")
    assert hedy is not None
    hedy_regressed = replace(
        hedy,
        forbidden_inputs=tuple(value for value in hedy.forbidden_inputs if value != "direct_people_memory_overwrite"),
    )
    assert "hedy_review_boundary_incomplete" in _hard_contract_failures(hedy_regressed)

    premium = lane_by_key("markupgo_fliplink_premium_delivery")
    assert premium is not None
    premium_regressed = replace(
        premium,
        forbidden_inputs=tuple(value for value in premium.forbidden_inputs if value != "access_grant_truth"),
    )
    assert "premium_delivery_boundary_incomplete" in _hard_contract_failures(premium_regressed)

    approvethis = lane_by_key("approvethis_external_approval_edge")
    assert approvethis is not None
    approvethis_regressed = replace(
        approvethis,
        forbidden_inputs=tuple(value for value in approvethis.forbidden_inputs if value != "direct_downstream_action"),
    )
    assert "approvethis_boundary_incomplete" in _hard_contract_failures(approvethis_regressed)

    docs = lane_by_key("documentation_ai_publication")
    assert docs is not None
    docs_regressed = replace(
        docs,
        forbidden_inputs=tuple(value for value in docs.forbidden_inputs if value != "silent_writeback"),
    )
    assert "documentation_ai_boundary_incomplete" in _hard_contract_failures(docs_regressed)

    release = lane_by_key("release_quality_gates")
    assert release is not None
    release_regressed = replace(
        release,
        forbidden_inputs=tuple(value for value in release.forbidden_inputs if value != "release_truth"),
    )
    assert "release_quality_truth_boundary_missing" in _hard_contract_failures(release_regressed)

    sendr = lane_by_key("sendr_ea_growth_outreach")
    assert sendr is not None
    sendr_privacy_regressed = replace(
        sendr,
        forbidden_inputs=tuple(value for value in sendr.forbidden_inputs if value != "raw_gmail"),
    )
    assert "sendr_privacy_or_send_boundary_incomplete" in _hard_contract_failures(sendr_privacy_regressed)

    sendr_switch_regressed = replace(
        sendr,
        off_switch_env=tuple(value for value in sendr.off_switch_env if value != "EA_SENDR_DIRECT_SEND_ENABLED"),
    )
    assert "sendr_fail_closed_switch_missing" in _hard_contract_failures(sendr_switch_regressed)


def test_lane_receipt_never_leaks_env_secret_values(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    markdown_text = ltd_path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(ltd_path)
    lane = lane_by_key("unmixr_voice_runtime")
    assert lane is not None

    receipt = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_text,
        inventory_rows=inventory_rows,
        env={"UNMIXR_API_KEY": "secret-api-key", "UNMIXR_VOICE_ID": "secret-voice"},
        root=tmp_path,
        generated_at="2026-06-10T00:00:00Z",
    )

    rendered = json.dumps(receipt, sort_keys=True)
    assert "secret-api-key" not in rendered
    assert "secret-voice" not in rendered
    assert "api_key_seeded" in receipt["passed_checks"]
    assert "voice_id_private" in receipt["passed_checks"]


def test_unmixr_voice_roundtrip_requires_passing_receipt(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    markdown_text = ltd_path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(ltd_path)
    lane = lane_by_key("unmixr_voice_runtime")
    assert lane is not None
    receipt_dir = tmp_path / "_completion" / "unmixr"
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "UNMIXR_VOICE_ROUNDTRIP.generated.json"
    env = {"UNMIXR_API_KEY": "secret-api-key", "UNMIXR_VOICE_ID": "secret-voice"}

    receipt_path.write_text(json.dumps({"status": "fail"}), encoding="utf-8")
    failed = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_text,
        inventory_rows=inventory_rows,
        env=env,
        root=tmp_path,
        generated_at="2026-06-10T00:00:00Z",
    )
    assert "voice_roundtrip_validation" in failed["missing_checks"]

    receipt_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    passed = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_text,
        inventory_rows=inventory_rows,
        env=env,
        root=tmp_path,
        generated_at="2026-06-10T00:00:00Z",
    )
    assert "voice_roundtrip_validation" in passed["passed_checks"]
    assert "voice_roundtrip_validation" not in passed["missing_checks"]


def test_subscribr_tier7_receipt_blocks_until_provider_proof(tmp_path: Path) -> None:
    markdown_row = (
        "| `Subscribr` | `License Tier 7 / Scale 3` | `1 lifetime license` | `Owned / activated` |  | "
        "`Tier 4` | Usual credentials local; API/channel/export proof pending | "
        "Governed script-intelligence lane. Must not host sourcebook PDFs, copied rulebook prose, "
        "private runner sheets, GM-only campaign secrets, or account records. Human review is required. |"
    )
    discovery_row = (
        "| `Subscribr` |  | `manual_seeded` | `user_report_tier7` | 2026-06-18T00:00:00Z | "
        "License Tier 7 / Scale 3 is recorded; API token, channel map, Markdown export, source binding, "
        "webhook proof, and human review enforcement are still pending. |"
    )
    markdown_path = tmp_path / "LTDs.md"
    markdown_path.write_text(_minimal_ltds(markdown_row, discovery_row), encoding="utf-8")

    lane = lane_by_key("subscribr_chummer_script_factory")
    assert lane is not None

    receipt = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_path.read_text(encoding="utf-8"),
        inventory_rows=load_ltd_inventory_rows(markdown_path),
        env={"SUBSCRIBR_API_TOKEN": "runtime-only-test-token"},
        root=tmp_path,
        generated_at="2026-06-18T00:00:00Z",
    )

    checks = {str(row["check_key"]): row for row in receipt["required_checks"]}
    assert receipt["status"] == "pass"
    assert receipt["lane_state"] == "blocked_pending_proof"
    assert receipt["runtime_enabled"] is False
    assert checks["inventory_recorded"]["passed"] is True
    assert checks["provider_verification"]["passed"] is True
    assert checks["api_token_private"]["passed"] is True
    assert checks["copyright_privacy_boundary"]["passed"] is True
    assert checks["human_review"]["passed"] is True
    assert checks["channel_map"]["passed"] is False
    assert checks["script_roundtrip"]["passed"] is False
    assert checks["source_binding"]["passed"] is False


def test_ltd_provider_governance_loads_env_local_for_private_runtime_slots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    markdown_row = (
        "| `Subscribr` | `License Tier 7 / Scale 3` | `1 lifetime license` | `Owned / activated` |  | "
        "`Tier 4` | API/channel/export proof pending | Human review is required. |"
    )
    discovery_row = (
        "| `Subscribr` |  | `manual_seeded` | `user_report_tier7` | 2026-06-18T00:00:00Z | "
        "License Tier 7 / Scale 3 is recorded; channel map, Markdown export, source binding, and human review enforcement are still pending. |"
    )
    markdown_path = tmp_path / "LTDs.md"
    markdown_path.write_text(_minimal_ltds(markdown_row, discovery_row), encoding="utf-8")
    (tmp_path / ".env.local").write_text("SUBSCRIBR_API_TOKEN=runtime-only-test-token\n", encoding="utf-8")
    monkeypatch.delenv("SUBSCRIBR_API_TOKEN", raising=False)

    receipt = build_ltd_provider_governance_receipt(
        markdown_path=markdown_path,
        root=tmp_path,
        generated_at="2026-06-18T00:00:00Z",
    )

    subscribr = next(row for row in receipt["lanes"] if row["lane_key"] == "subscribr_chummer_script_factory")
    checks = {str(row["check_key"]): row for row in subscribr["required_checks"]}
    assert checks["api_token_private"]["passed"] is True
    assert checks["api_token_private"]["source"] == "SUBSCRIBR_API_TOKEN_present_outside_git"
    assert "runtime-only-test-token" not in json.dumps(receipt, sort_keys=True)


def test_subscribr_direct_publish_regression_is_hard_failure() -> None:
    from app.services.ltd_provider_governance import _hard_contract_failures

    lane = lane_by_key("subscribr_chummer_script_factory")
    assert lane is not None

    regressed = replace(
        lane,
        forbidden_inputs=tuple(value for value in lane.forbidden_inputs if value != "direct_publish"),
    )

    assert "subscribr_direct_publish_not_forbidden" in _hard_contract_failures(regressed)


def test_fliplink_first_publication_requires_passing_receipt(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    markdown_text = ltd_path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(ltd_path)
    lane = lane_by_key("fliplink_document_portal")
    assert lane is not None
    receipt_dir = tmp_path / "_completion" / "fliplink"
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "CHUMMER_FLIPLINK_PUBLICATION.generated.json"

    receipt_path.write_text(json.dumps({"status": "fail"}), encoding="utf-8")
    failed = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_text,
        inventory_rows=inventory_rows,
        env={},
        root=tmp_path,
        generated_at="2026-06-10T00:00:00Z",
    )
    assert "first_publication_receipt" in failed["missing_checks"]
    assert failed["lane_state"] == "blocked_pending_proof"

    receipt_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    passed = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_text,
        inventory_rows=inventory_rows,
        env={},
        root=tmp_path,
        generated_at="2026-06-10T00:00:00Z",
    )
    assert "first_publication_receipt" in passed["passed_checks"]
    assert "first_publication_receipt" not in passed["missing_checks"]
    assert passed["lane_state"] == "verified_runtime_lane"
    assert passed["runtime_enabled"] is True


def test_poppy_pending_boundary_text_does_not_count_as_proof(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    markdown_text = ltd_path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(ltd_path)
    lane = lane_by_key("poppy_draft_workbench")
    assert lane is not None

    receipt = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_text,
        inventory_rows=inventory_rows,
        env={},
        root=tmp_path,
        generated_at="2026-06-10T00:00:00Z",
    )

    assert receipt["lane_state"] == "blocked_pending_proof"
    assert {"authenticated_session", "privacy_boundary", "export_semantics", "tenant_isolation"} <= set(
        receipt["missing_checks"]
    )
    assert "privacy_boundary" not in receipt["passed_checks"]


def test_poppy_boundary_checks_require_passing_receipts(tmp_path: Path) -> None:
    ltd_path = _write_ltd(tmp_path)
    markdown_text = ltd_path.read_text(encoding="utf-8")
    inventory_rows = load_ltd_inventory_rows(ltd_path)
    lane = lane_by_key("poppy_draft_workbench")
    assert lane is not None
    receipt_dir = tmp_path / "_completion" / "poppy"
    receipt_dir.mkdir(parents=True)
    for name in (
        "POPPY_AUTHENTICATED_SESSION.generated.json",
        "POPPY_PRIVACY_BOUNDARY.generated.json",
        "POPPY_EXPORT_SEMANTICS.generated.json",
        "POPPY_TENANT_ISOLATION.generated.json",
    ):
        (receipt_dir / name).write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    receipt = build_ltd_provider_lane_receipt(
        lane,
        markdown_text=markdown_text,
        inventory_rows=inventory_rows,
        env={},
        root=tmp_path,
        generated_at="2026-06-10T00:00:00Z",
    )

    assert receipt["lane_state"] == "verified_draft_operator_lane"
    assert "authenticated_session" in receipt["passed_checks"]
    assert {"privacy_boundary", "export_semantics", "tenant_isolation"} <= set(receipt["passed_checks"])


def test_materializer_writes_aggregate_and_lane_receipts(tmp_path: Path, monkeypatch) -> None:
    ltd_path = _write_ltd(tmp_path)
    output_dir = tmp_path / "receipts"

    receipt = materialize_ltd_provider_governance_receipts(output_dir=output_dir, markdown_path=ltd_path)

    assert receipt["status"] == "pass"
    assert (output_dir / "LTD_PROVIDER_GOVERNANCE.generated.json").is_file()
    assert (output_dir / "FLIPLINK_DOCUMENT_PORTAL.generated.json").is_file()


def test_verify_ltd_provider_lanes_cli_prints_requested_lane() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_ltd_provider_lanes.py",
            "--lane",
            "fliplink_document_portal",
            "--no-write",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    body = json.loads(result.stdout)
    assert body["lane_key"] == "fliplink_document_portal"
    assert body["not_source_of_truth"] is True
    assert "lanes" not in body


def test_verify_ltd_provider_lanes_cli_works_outside_repo_cwd() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "/docker/EA/scripts/verify_ltd_provider_lanes.py",
            "--lane",
            "release-quality-gates",
            "--no-write",
        ],
        cwd="/tmp",
        check=True,
        text=True,
        capture_output=True,
    )

    body = json.loads(result.stdout)
    assert body["lane_key"] == "release_quality_gates"
    assert body["runtime_enabled"] is True


def test_verify_poppy_session_cli_fails_until_boundary_receipts_exist() -> None:
    receipt_dir = ROOT / "ea" / "_completion" / "poppy"
    if receipt_dir.is_dir() and all(
        (receipt_dir / name).is_file()
        for name in (
            "POPPY_AUTHENTICATED_SESSION.generated.json",
            "POPPY_PRIVACY_BOUNDARY.generated.json",
            "POPPY_EXPORT_SEMANTICS.generated.json",
            "POPPY_TENANT_ISOLATION.generated.json",
        )
    ):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/verify_poppy_session.py",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        body = json.loads(result.stdout)
        assert body["lane_key"] == "poppy_draft_workbench"
        assert body["lane_state"] == "verified_draft_operator_lane"
        assert body["runtime_enabled"] is False
        return

    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_poppy_session.py",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    body = json.loads(result.stdout)
    assert body["lane_key"] == "poppy_draft_workbench"
    assert {"privacy_boundary", "export_semantics", "tenant_isolation"} <= set(body["missing_checks"])


def test_materialize_poppy_draft_workbench_receipts_promotes_draft_only_lane(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "materialize_poppy_draft_workbench_receipts.py"
    session_probe = tmp_path / "POPPY_AI_PROVIDER_SESSION_PROBE.generated.json"
    session_probe.write_text(
        json.dumps(
            {
                "status": "authenticated_session_proven_host_headful",
                "verification_result": {"authenticated_session_proven": True},
                "browser_lane": {"google_email_submitted": "secret@example.com"},
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "_completion" / "poppy"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--output-dir",
            str(output_dir),
            "--session-probe",
            str(session_probe),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    receipt_files = sorted(output_dir.glob("POPPY_*.generated.json"))
    assert len(receipt_files) == 4
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in receipt_files)
    assert "private_memorial_memory" in rendered
    assert "secret@example.com" not in rendered

    ltd_path = _write_ltd(tmp_path)
    receipt = build_ltd_provider_lane_receipt(
        lane_by_key("poppy_draft_workbench"),
        markdown_text=ltd_path.read_text(encoding="utf-8"),
        inventory_rows=load_ltd_inventory_rows(ltd_path),
        env={},
        root=tmp_path,
        generated_at="2026-06-12T00:00:00Z",
    )
    assert receipt["lane_state"] == "verified_draft_operator_lane"
    assert receipt["runtime_enabled"] is False
    assert receipt["missing_checks"] == []


def test_materialize_poppy_draft_packet_accepts_only_approved_public_inputs(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "materialize_poppy_draft_packet.py"
    source_packet = tmp_path / "source.packet.json"
    draft_output = tmp_path / "draft.txt"
    output_dir = tmp_path / "poppy-drafts"
    source_packet.write_text(
        json.dumps(
            {
                "source_packet_id": "public-release-copy-v1",
                "input_kind": "public_release_copy",
                "visibility": "public",
                "review_status": "approved",
                "source_refs": ["README.md"],
                "source_text": "Public source packet only.",
            }
        ),
        encoding="utf-8",
    )
    draft_output.write_text("Draft summary copied manually from Poppy.", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source-packet",
            str(source_packet),
            "--draft-output",
            str(draft_output),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    receipt = json.loads(Path(body["output"]).read_text(encoding="utf-8"))
    rendered = json.dumps(receipt, sort_keys=True)
    assert receipt["contract_name"] == "executive_assistant.poppy_draft_packet.v1"
    assert receipt["lane_state"] == "verified_draft_operator_lane"
    assert receipt["runtime_enabled"] is False
    assert receipt["human_review_required"] is True
    assert receipt["status"] == "pending_human_review"
    assert "Draft summary copied manually from Poppy." not in rendered


def test_materialize_poppy_draft_packet_rejects_private_or_truth_inputs(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "materialize_poppy_draft_packet.py"
    source_packet = tmp_path / "source.packet.json"
    draft_output = tmp_path / "draft.txt"
    source_packet.write_text(
        json.dumps(
            {
                "source_packet_id": "bad-private-packet",
                "input_kind": "private_campaign_data",
                "visibility": "private",
                "review_status": "draft",
                "source_text": "Do not send this.",
                "contains_private_campaign_data": True,
                "contains_release_truth": True,
            }
        ),
        encoding="utf-8",
    )
    draft_output.write_text("Draft should not be accepted.", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source-packet",
            str(source_packet),
            "--draft-output",
            str(draft_output),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "poppy_source_packet_rejected" in result.stderr
    assert "forbidden_flag_set:contains_private_campaign_data" in result.stderr
    assert "input_kind_not_allowed:private_campaign_data" in result.stderr
