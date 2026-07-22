from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from scripts import materialize_governed_spatial_render_checkpoint as checkpoint_module
from scripts import verify_governed_spatial_render_checkpoint as checkpoint_verifier
from scripts.materialize_governed_spatial_render_checkpoint import build_checkpoint
from scripts.verify_governed_spatial_render_checkpoint import verify_checkpoint


OBSERVED_AT = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _canonical_input_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_drift(**_: object) -> dict[str, object]:
        raise ValueError("canonical_input_hash_drift:" + "a" * 64)

    monkeypatch.setattr(checkpoint_module, "build_design_review_receipt", _raise_drift)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _provider_receipt(path: Path) -> Path:
    check_names = [
        "3dvista_control_page_ok",
        "3dvista_no_browser_console_blockers",
        "3dvista_no_request_failures",
        "3dvista_no_bad_http_assets",
        "3dvista_rendered_viewer",
        "3dvista_accessible_shell",
        "3dvista_responsive_touch_shell",
        "3dvista_reduced_motion_shell",
        "3dvista_offline_recovery_visible",
        "3dvista_retry_restores_viewer",
        "3dvista_browser_render_proof_persisted",
    ]
    checks: list[dict[str, object]] = [
        {"name": name, "ok": True} for name in check_names
    ]
    next(row for row in checks if row["name"] == "3dvista_rendered_viewer")["state"] = {
        "same_origin_frame_inspected": True,
        "visible_canvas_count": 2,
    }
    path.write_text(
        json.dumps(
            {
                "contract_name": "propertyquarry.3d_browser_gate.v1",
                "generated_at": (OBSERVED_AT - timedelta(hours=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "status": "pass",
                "providers": ["3dvista"],
                "checks": checks,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_materialized_checkpoint_is_private_complete_and_fail_closed(
    tmp_path: Path,
) -> None:
    output = tmp_path / "checkpoint.json"
    private_root = tmp_path / "private"

    receipt = build_checkpoint(
        output_path=output,
        private_root=private_root,
        evidence_path=_provider_receipt(tmp_path / "browser.json"),
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
        focused_tests_passed=50,
    )
    verification = verify_checkpoint(output)

    assert receipt["status"] == "intermediate_blocked"
    assert (
        receipt["design_authority_status"]
        == "canonical_review_source_validation_blocked"
    )
    assert receipt["design_authority_blocker"]["reason"] == "canonical_input_hash_drift"
    assert receipt["design_authority_blocker"]["next_action"] == (
        "obtain_new_hash_bound_canonical_authority_receipt"
    )
    assert receipt["design_authority_blocker"]["raw_failure_detail_exposed"] is False
    assert "a" * 64 not in json.dumps(receipt["design_authority_blocker"])
    assert receipt["canonical_design_review"]["decision"]["disposition"] == "unverified"
    assert receipt["canonical_design_review"]["implementation_authorized"] is False
    assert receipt["launch_recommendation"] == "no"
    assert receipt["provider_execution"] == {
        "jobs_attempted": 0,
        "credits_consumed": 0,
        "quota_authorized": False,
    }
    assert receipt["example_build_receipt"]["status"] == "blocked"
    assert receipt["example_build_receipt"]["product_projection"]["state"] == "blocked"
    assert receipt["style_videos"] == []
    assert receipt["telegram_delivery_receipts"] == []
    assert receipt["canary"]["status"] == "not_started"
    assert receipt["propertyquarry_live_untouched"] is True
    assert verification["status"] == "pass", verification["issues"]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE((private_root / "fixture-signing.key").stat().st_mode) == 0o600


def test_checkpoint_materialization_replays_receipts_after_restart_without_duplicate_work(
    tmp_path: Path,
) -> None:
    output = tmp_path / "checkpoint.json"
    private_root = tmp_path / "private"
    evidence = _provider_receipt(tmp_path / "browser.json")
    first = build_checkpoint(
        output_path=output,
        private_root=private_root,
        evidence_path=evidence,
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
        focused_tests_passed=50,
    )
    replay = build_checkpoint(
        output_path=output,
        private_root=private_root,
        evidence_path=evidence,
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
        focused_tests_passed=50,
    )

    assert (
        replay["example_compose_receipt"]["composition_digest"]
        == first["example_compose_receipt"]["composition_digest"]
    )
    assert replay["example_compose_receipt"]["idempotent_replay"] is True
    assert (
        replay["example_build_receipt"]["build_id"]
        == first["example_build_receipt"]["build_id"]
    )
    assert replay["example_build_receipt"]["idempotent_replay"] is True
    assert replay["receipt_store_integrity"]["composition_count"] == 1
    assert replay["receipt_store_integrity"]["build_count"] == 1
    assert replay["provider_execution"]["jobs_attempted"] == 0
    assert replay["provider_execution"]["credits_consumed"] == 0
    assert verify_checkpoint(output)["status"] == "pass"


def test_checkpoint_verifier_rejects_semantic_overclaim_even_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "checkpoint.json"
    receipt = build_checkpoint(
        output_path=output,
        private_root=tmp_path / "private",
        evidence_path=_provider_receipt(tmp_path / "browser.json"),
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
        focused_tests_passed=50,
    )
    receipt["launch_recommendation"] = "ready for authorized promotion"
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = _digest(body)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output.chmod(0o600)

    result = verify_checkpoint(output)

    assert result["status"] == "fail"
    assert "launch_recommendation_must_be_no" in result["issues"]


def test_checkpoint_verifier_rejects_design_review_acceptance_overclaim(
    tmp_path: Path,
) -> None:
    output = tmp_path / "checkpoint.json"
    receipt = build_checkpoint(
        output_path=output,
        private_root=tmp_path / "private",
        evidence_path=_provider_receipt(tmp_path / "browser.json"),
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
        focused_tests_passed=50,
    )
    review = receipt["canonical_design_review"]
    review["decision"]["disposition"] = "accept"
    review_body = {
        key: value for key, value in review.items() if key != "receipt_digest"
    }
    review["receipt_digest"] = _digest(review_body)
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = _digest(body)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output.chmod(0o600)

    result = verify_checkpoint(output)

    assert result["status"] == "fail"
    assert "blocked_design_review_decision_invalid" in result["issues"]


def test_checkpoint_verifier_rejects_mutated_authority_blocker_with_recomputed_checkpoint_digest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "checkpoint.json"
    receipt = build_checkpoint(
        output_path=output,
        private_root=tmp_path / "private",
        evidence_path=_provider_receipt(tmp_path / "browser.json"),
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
        focused_tests_passed=50,
    )
    receipt["design_authority_blocker"]["next_action"] = "ignore_authority_and_launch"
    blocker = receipt["design_authority_blocker"]
    blocker_body = {
        key: value for key, value in blocker.items() if key != "receipt_digest"
    }
    blocker["receipt_digest"] = _digest(blocker_body)
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = _digest(body)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output.chmod(0o600)

    result = verify_checkpoint(output)

    assert result["status"] == "fail"
    assert "canonical_authority_blocker_next_action_invalid" in result["issues"]
    assert "blocked_design_review_binding_invalid" in result["issues"]


def test_checkpoint_verifier_rejects_non_private_permissions(tmp_path: Path) -> None:
    output = tmp_path / "checkpoint.json"
    build_checkpoint(
        output_path=output,
        private_root=tmp_path / "private",
        evidence_path=_provider_receipt(tmp_path / "browser.json"),
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
    )
    output.chmod(0o644)

    result = verify_checkpoint(output)

    assert result["status"] == "fail"
    assert "checkpoint_permissions_or_link_invalid" in result["issues"]


def test_checkpoint_does_not_swallow_unrelated_design_review_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_unrelated(**_: object) -> dict[str, object]:
        raise ValueError("unrelated_checkpoint_programming_error")

    monkeypatch.setattr(
        checkpoint_module, "build_design_review_receipt", _raise_unrelated
    )

    with pytest.raises(ValueError, match="unrelated_checkpoint_programming_error"):
        build_checkpoint(
            output_path=tmp_path / "checkpoint.json",
            private_root=tmp_path / "private",
            evidence_path=_provider_receipt(tmp_path / "browser.json"),
            design_review_output_path=tmp_path / "design-review.json",
            observed_at=OBSERVED_AT,
        )


def test_checkpoint_verifier_cli_passes_for_materialized_receipt(
    tmp_path: Path,
) -> None:
    output = tmp_path / "checkpoint.json"
    build_checkpoint(
        output_path=output,
        private_root=tmp_path / "private",
        evidence_path=_provider_receipt(tmp_path / "browser.json"),
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
        focused_tests_passed=50,
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_governed_spatial_render_checkpoint.py",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "pass"


def test_checkpoint_verifier_redacts_nested_design_review_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "checkpoint.json"
    receipt = build_checkpoint(
        output_path=output,
        private_root=tmp_path / "private",
        evidence_path=_provider_receipt(tmp_path / "browser.json"),
        design_review_output_path=tmp_path / "design-review.json",
        observed_at=OBSERVED_AT,
    )
    receipt["design_authority_blocker"] = None
    receipt["design_authority_status"] = checkpoint_verifier.CANONICAL_REVIEW_STATUS
    receipt["required_design_follow_up"] = checkpoint_verifier.EXPECTED_DESIGN_FOLLOW_UP
    receipt["capability_index"]["design_authority_status"] = (
        checkpoint_verifier.CANONICAL_REVIEW_STATUS
    )
    receipt["capability_index"]["design_review_disposition"] = "revise"
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = _digest(body)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output.chmod(0o600)

    leaked_hashes = ("b" * 64, "c" * 64)
    observed_fingerprints: list[str] = []
    for leaked_hash in leaked_hashes:
        expected_fingerprint = hashlib.sha256(
            f"canonical_input_hash_drift:{leaked_hash}".encode("utf-8")
        ).hexdigest()
        monkeypatch.setattr(
            checkpoint_verifier,
            "verify_design_review_receipt_payload",
            lambda _value, fingerprint=expected_fingerprint: {
                "status": "fail",
                "issues": ["canonical_input_hash_drift"],
                "validation_failure_fingerprints": [
                    {
                        "reason": "canonical_input_hash_drift",
                        "fingerprint": fingerprint,
                    }
                ],
            },
        )

        result = checkpoint_verifier.verify_checkpoint(output)

        assert (
            "canonical_design_review_invalid:canonical_input_hash_drift"
            in result["issues"]
        )
        assert all(raw_hash not in json.dumps(result) for raw_hash in leaked_hashes)
        assert result["issue_fingerprints"] == [
            {
                "scope": "canonical_design_review",
                "reason": "canonical_input_hash_drift",
                "fingerprint": expected_fingerprint,
            }
        ]
        observed_fingerprints.append(expected_fingerprint)

    assert len(set(observed_fingerprints)) == 2
