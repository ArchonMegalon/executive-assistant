from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import stat

import pytest

from scripts import materialize_governed_spatial_render_design_review as review_module
from scripts.materialize_governed_spatial_render_design_review import (
    build_design_review_receipt,
    verify_design_review_receipt,
    verify_design_review_receipt_payload,
)


OBSERVED_AT = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pin_expected_canonical_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = [
        {
            "path": str(review_module.CHUMMER_DESIGN_ROOT / relative_path),
            "sha256": expected_hash,
        }
        for relative_path, expected_hash in review_module.EXPECTED_CANONICAL_INPUTS.items()
    ]
    monkeypatch.setattr(
        review_module,
        "_validate_bound_sources",
        lambda: snapshot,
    )


def test_design_review_receipt_is_hash_bound_private_and_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_expected_canonical_snapshot(monkeypatch)
    output = tmp_path / "review.json"

    receipt = build_design_review_receipt(output_path=output, observed_at=OBSERVED_AT)
    verification = verify_design_review_receipt(output)

    assert receipt["status"] == "revise_blocked"
    assert receipt["decision"]["disposition"] == "revise"
    assert receipt["decision"]["implementation_state"] == "blocked"
    assert receipt["implementation_authorized"] is False
    assert receipt["provider_execution_authorized"] is False
    assert receipt["quota_authorized"] is False
    assert receipt["product_bridge_registration_authorized"] is False
    assert receipt["authority_contract"]["durable_chummer_contract_owner"] == (
        "chummer6-media-factory:Chummer.Media.Contracts"
    )
    assert len(receipt["required_amendments"]) == 10
    assert verification["status"] == "pass", verification["issues"]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_design_review_verifier_rejects_acceptance_overclaim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_expected_canonical_snapshot(monkeypatch)
    output = tmp_path / "review.json"
    receipt = build_design_review_receipt(output_path=output, observed_at=OBSERVED_AT)
    receipt["decision"]["disposition"] = "accept"
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = _digest(body)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output.chmod(0o600)

    result = verify_design_review_receipt(output)

    assert result["status"] == "fail"
    assert "design_review_decision_invalid:disposition" in result["issues"]


def test_design_review_materializer_rejects_decision_hash_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = tmp_path / "decision.md"
    drifted.write_text(
        review_module.DEFAULT_DECISION.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(review_module, "DEFAULT_DECISION", drifted)

    with pytest.raises(ValueError, match="decision_hash_drift"):
        build_design_review_receipt(
            output_path=tmp_path / "review.json",
            observed_at=OBSERVED_AT,
        )


def test_design_review_verification_redacts_canonical_hash_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaked_hash = "a" * 64

    def _raise_drift() -> list[dict[str, str]]:
        raise ValueError(f"canonical_input_hash_drift:{leaked_hash}")

    monkeypatch.setattr(review_module, "_validate_bound_sources", _raise_drift)
    result = verify_design_review_receipt_payload({}, verify_bound_files=True)

    assert "canonical_input_hash_drift" in result["issues"]
    assert leaked_hash not in json.dumps(result["issues"])
    assert result["validation_failure_fingerprints"] == [
        {
            "reason": "canonical_input_hash_drift",
            "fingerprint": hashlib.sha256(
                f"canonical_input_hash_drift:{leaked_hash}".encode("utf-8")
            ).hexdigest(),
        }
    ]
