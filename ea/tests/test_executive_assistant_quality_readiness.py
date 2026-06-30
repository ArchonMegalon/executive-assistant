from __future__ import annotations

import json
from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_FORM_FIELDS  # noqa: E402
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_PATH  # noqa: E402
from materialize_executive_assistant_acceptance_evidence import REQUIRED_ACCEPTANCE_KEYS  # noqa: E402
from materialize_executive_assistant_quality_readiness import (  # noqa: E402
    materialize_executive_assistant_quality_readiness,
)
from verify_executive_assistant_quality_readiness import verify_executive_assistant_quality_readiness  # noqa: E402


def _office_loop_receipt() -> dict[str, object]:
    return {
        "components": {
            "command_brief": {"status": "pass"},
            "decision_queue": {"status": "pass"},
            "commitment_ledger": {"status": "pass"},
            "approved_action_workflow": {"status": "pass"},
            "evidence_audit_trail": {"status": "pass"},
            "support_recovery": {"status": "pass"},
            "operator_control": {"status": "pass"},
            "goal_evidence": {"status": "pass"},
        },
        "diagnostics_summary": {"channel_loop_digest_keys": ["memo", "approvals", "operator"]},
    }


def test_quality_readiness_exposes_redacted_acceptance_capture_surface(tmp_path: Path) -> None:
    receipt_path = tmp_path / "quality.json"
    acceptance = {
        "accepted_keys": [],
        "next_action_proof_key": "real_daily_morning_brief_accepted",
        "acceptance_keys": {
            key: {
                "accepted": False,
                "status": "missing_or_invalid",
                "raw_evidence_exposed": False,
                "raw_actor_exposed": False,
                "raw_object_ref_exposed": False,
            }
            for key in REQUIRED_ACCEPTANCE_KEYS
        },
    }

    receipt = materialize_executive_assistant_quality_readiness(
        receipt_path=receipt_path,
        office_loop=_office_loop_receipt(),
        acceptance_evidence=acceptance,
    )

    surface = dict(receipt.get("acceptance_capture_surface") or {})
    assert surface["path"] == ACCEPTANCE_CAPTURE_PATH
    assert surface["stored_evidence_shape"] == "sha256_only"
    assert surface["raw_input_not_persisted"] is True
    assert set(ACCEPTANCE_CAPTURE_FORM_FIELDS) <= set(surface["required_form_fields"])
    requirements = {
        str(dict(item).get("key") or ""): dict(item)
        for item in list(receipt.get("acceptance_capture_requirements") or [])
    }
    assert set(requirements) == set(REQUIRED_ACCEPTANCE_KEYS)
    assert requirements["real_daily_morning_brief_accepted"]["status"] == "pending_real_world_evidence"
    context = dict(receipt.get("next_action_context") or {})
    assert context["kind"] == "redacted_acceptance_capture"
    assert context["proof_key"] == "real_daily_morning_brief_accepted"
    assert context["proof_label"] == "real daily morning brief acceptance"
    assert context["capture_path"] == ACCEPTANCE_CAPTURE_PATH
    assert context["stored_evidence_shape"] == "sha256_only"
    assert context["raw_acceptance_text_persisted"] is False
    assert context["raw_actor_identity_persisted"] is False
    assert context["raw_object_reference_persisted"] is False
    assert verify_executive_assistant_quality_readiness(receipt_path)["status"] == "pass"


def test_quality_verifier_fails_when_acceptance_capture_surface_is_missing(tmp_path: Path) -> None:
    receipt_path = tmp_path / "quality.json"
    receipt = materialize_executive_assistant_quality_readiness(
        receipt_path=receipt_path,
        office_loop=_office_loop_receipt(),
        acceptance_evidence={"accepted_keys": [], "acceptance_keys": {}},
    )
    receipt.pop("acceptance_capture_surface", None)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verify_executive_assistant_quality_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "ea_quality_acceptance_capture_surface_path_missing" in verification["issues"]
