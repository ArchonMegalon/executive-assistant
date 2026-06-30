from __future__ import annotations

import json
import sys
from pathlib import Path

from app.api.routes import landing_actions


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from verify_executive_assistant_acceptance_evidence import (  # noqa: E402
    verify_executive_assistant_acceptance_evidence,
)
from verify_executive_assistant_quality_readiness import (  # noqa: E402
    verify_executive_assistant_quality_readiness,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_landing_acceptance_receipt_refresh_matches_verifier_contract(tmp_path: Path) -> None:
    receipt = landing_actions._default_acceptance_receipt()  # noqa: SLF001
    rows = dict(receipt.get("acceptance_keys") or {})
    row = dict(rows["real_daily_morning_brief_accepted"])
    row.update(
        {
            "accepted": True,
            "status": "accepted_redacted",
            "source_kind": "operator_admin",
            "recorded_at": "2026-06-30T00:00:00Z",
            "evidence_sha256": "evidence-hash",
            "actor_sha256": "actor-hash",
            "object_ref_sha256": "object-hash",
            "raw_evidence_exposed": False,
            "raw_actor_exposed": False,
            "raw_object_ref_exposed": False,
        }
    )
    rows["real_daily_morning_brief_accepted"] = row

    landing_actions._refresh_acceptance_receipt_summary(receipt, rows)  # noqa: SLF001
    receipt_path = tmp_path / "acceptance.json"
    _write_json(receipt_path, receipt)

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert receipt["next_action_proof_key"] == "real_decision_cleared"
    assert receipt["real_principal_acceptance_verified"] is True


def test_landing_quality_receipt_refresh_preserves_acceptance_capture_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    quality_path = tmp_path / "quality.json"
    monkeypatch.setattr(landing_actions, "EA_QUALITY_READINESS_RECEIPT", quality_path)

    receipt = landing_actions._default_acceptance_receipt()  # noqa: SLF001
    landing_actions._update_quality_receipt_from_acceptance(receipt)  # noqa: SLF001

    verification = verify_executive_assistant_quality_readiness(quality_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    assert verification["status"] == "pass"
    assert quality["status"] == "blocked_real_world_acceptance"
    assert quality["next_action_href"] == "/admin/actions/acceptance-evidence"
    assert quality["next_action_label"] == "Record a real-use outcome"
    assert quality["next_action_proof_key"] == "real_daily_morning_brief_accepted"
    context = dict(quality.get("next_action_context") or {})
    assert context["kind"] == "redacted_acceptance_capture"
    assert context["proof_key"] == "real_daily_morning_brief_accepted"
    assert context["proof_label"] == "real daily morning brief acceptance"
    assert context["capture_path"] == "/admin/actions/acceptance-evidence"
    assert context["stored_evidence_shape"] == "sha256_only"
    assert context["raw_acceptance_text_persisted"] is False
    assert "acceptance_capture_requirements" in quality


def test_landing_acceptance_capture_path_writes_complete_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    acceptance_path = tmp_path / "acceptance.json"
    quality_path = tmp_path / "quality.json"
    scope_gap_path = tmp_path / "scope-gap.json"
    signal_path = tmp_path / "signal.json"
    monkeypatch.setattr(landing_actions, "EA_ACCEPTANCE_EVIDENCE_RECEIPT", acceptance_path)
    monkeypatch.setattr(landing_actions, "EA_QUALITY_READINESS_RECEIPT", quality_path)
    monkeypatch.setattr(landing_actions, "EA_SCOPE_GAP_AUDIT_RECEIPT", scope_gap_path)
    monkeypatch.setattr(landing_actions, "EA_SIGNAL_TO_DECISION_RECEIPT", signal_path)

    receipt = landing_actions._record_acceptance_evidence_receipt(  # noqa: SLF001
        proof_key="real_daily_morning_brief_accepted",
        source_kind="operator_admin",
        evidence="The morning brief was useful and worth reading.",
        object_ref="morning-brief:2026-06-30",
        actor="operator:test",
    )

    acceptance_verification = verify_executive_assistant_acceptance_evidence(acceptance_path)
    quality_verification = verify_executive_assistant_quality_readiness(quality_path)
    assert acceptance_verification["status"] == "pass"
    assert quality_verification["status"] == "pass"
    assert receipt["status"] == "partial_real_world_acceptance_evidence"
    assert receipt["next_action"] == "collect_redacted_real_world_acceptance_evidence"
    assert receipt["next_action_proof_key"] == "real_decision_cleared"
    assert receipt["real_principal_acceptance_verified"] is True
    assert receipt["real_daily_use_verified"] is False
    row = dict(dict(receipt.get("acceptance_keys") or {})["real_daily_morning_brief_accepted"])
    assert row["evidence_sha256"]
    assert row["actor_sha256"]
    assert row["object_ref_sha256"]
    assert row["raw_evidence_exposed"] is False
    assert "The morning brief was useful" not in acceptance_path.read_text(encoding="utf-8")
