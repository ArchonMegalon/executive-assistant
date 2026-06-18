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


def _sample_ltd_markdown() -> str:
    return """
# LTDs

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `blipai` | `No tier recorded` | `1 account` | `Owned` |  | `Tier 4` | Local credentials | Operator note capture only. |
| `Teable` | `Tier 2` | `1 account` | `Owned` |  | `Tier 2` | Projection adapter | Projection only, not source of truth. |
| `Syllabbles` | `No tier recorded` | `1 account` | `Owned` |  | `Tier 4` | Draft workbench | Dispatch draft only. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `FlipLink.me` | `Tier 10` | `1 account` | `Owned` |  | `Tier 3` | Candidate document portal | Must not host sourcebook PDFs, copied rulebook prose, private runner sheets, GM-only secrets, entitlement truth, or payment truth. |
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

## Discovery Tracking

| Service | Account | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `FlipLink.me` |  | `manual_seeded` | `user_reported` | 2026-06-05T00:00:00Z | Provider verification pending. |
| `Unmixr AI` | `the.girscheles@gmail.com` | `manual_seeded` | `user_report + local_runtime_docs` | 2026-06-03T09:58:09Z | API key and voice ID pending. |
| `Poppy AI` | `the.girscheles@gmail.com` | `user_reported` | `live_google_session_probe` | 2026-06-09T10:25:00Z | Session proof recorded; privacy, export and tenant isolation still pending. |
| `Rafter` | `the.girscheles@gmail.com` | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | Fleet proof passes. |
| `Pixefy` | `the.girscheles@gmail.com` | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | Fleet proof passes. |
| `Prompt Architects` |  | `manual_seeded` | `local_env + prompt_foundry_receipts` | 2026-06-01T20:54:48Z | Prompt Foundry receipts exist. |
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
        "fliplink_document_portal",
        "unmixr_voice_runtime",
        "magicfit_media_factory_candidate",
        "poppy_draft_workbench",
        "release_quality_gates",
        "public_signal_ingest",
        "docs_draft_factory",
        "prompt_foundry",
        "subscribr_chummer_script_factory",
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
    assert {"private_campaign_data", "user_submission", "private_memorial_memory", "product_truth"} <= set(
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
        cwd="/docker/EA",
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
    receipt_dir = Path("/docker/EA/ea/_completion/poppy")
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
            cwd="/docker/EA",
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
        cwd="/docker/EA",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    body = json.loads(result.stdout)
    assert body["lane_key"] == "poppy_draft_workbench"
    assert {"privacy_boundary", "export_semantics", "tenant_isolation"} <= set(body["missing_checks"])


def test_materialize_poppy_draft_workbench_receipts_promotes_draft_only_lane(tmp_path: Path) -> None:
    script = Path("/docker/EA/scripts/materialize_poppy_draft_workbench_receipts.py")
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
        cwd="/docker/EA",
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
    script = Path("/docker/EA/scripts/materialize_poppy_draft_packet.py")
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
        cwd="/docker/EA",
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
    script = Path("/docker/EA/scripts/materialize_poppy_draft_packet.py")
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
        cwd="/docker/EA",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "poppy_source_packet_rejected" in result.stderr
    assert "forbidden_flag_set:contains_private_campaign_data" in result.stderr
    assert "input_kind_not_allowed:private_campaign_data" in result.stderr
