from __future__ import annotations

import json
from pathlib import Path
import sys


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from materialize_whole_project_signal_to_decision_receipt import (  # noqa: E402
    materialize_whole_project_signal_to_decision_receipt,
)
from verify_whole_project_signal_to_decision_receipt import (  # noqa: E402
    verify_whole_project_signal_to_decision_receipt,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_signal_to_decision_materializer_exposes_source_state(tmp_path: Path) -> None:
    office_path = tmp_path / "office.json"
    acceptance_path = tmp_path / "acceptance.json"
    quality_path = tmp_path / "quality.json"
    active_media_path = tmp_path / "active-media.json"
    receipt_path = tmp_path / "signal.json"
    _write_json(office_path, {"contract_name": "office", "status": "pass", "remaining_external_proofs": []})
    _write_json(
        acceptance_path,
        {"contract_name": "acceptance", "status": "blocked_missing_real_world_acceptance_evidence"},
    )
    _write_json(quality_path, {"contract_name": "quality", "status": "blocked_real_world_acceptance"})
    _write_json(active_media_path, {"contract_name": "active-media", "status": "pass"})

    receipt = materialize_whole_project_signal_to_decision_receipt(
        receipt_path=receipt_path,
        office_loop_receipt_path=office_path,
        acceptance_evidence_receipt_path=acceptance_path,
        ea_quality_receipt_path=quality_path,
        active_media_receipt_path=active_media_path,
        preserve_existing=False,
    )

    verification = verify_whole_project_signal_to_decision_receipt(receipt_path)
    assert verification["status"] == "pass"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
