from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_ltd_operations_to_teable.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_ltd_operations_to_teable", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_sources(tmp_path: Path, *, exposes_secret: bool = False) -> tuple[Path, Path]:
    provider = tmp_path / "provider.json"
    provider.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-13T00:00:00Z",
                "status": "ready_for_bounded_dispatch",
                "secret_material_exposed": exposes_secret,
                "truth_posture": "boolean presence only",
                "providers": [
                    {
                        "provider": "1min.AI",
                        "task_class": "background_summarization",
                        "slot_ref_sha256": "a" * 64,
                        "credit_basis": "minimum_live_credit_balance=1;live_balance_not_asserted",
                        "route_decision": "eligible_for_health_probe",
                        "configured_state": "active_background_candidate",
                        "credential_present": True,
                        "credential_slot": "ONEMIN_AI_API_KEY",
                        "maximum_blast_radius": "public_safe",
                        "review_required": True,
                        "route_state": "eligible_for_health_probe",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    proof = tmp_path / "proof.json"
    proof.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-13T00:00:00Z",
                "status": "projection_ready",
                "secret_material_exposed": False,
                "truth_posture": "operator review only",
                "rows": [
                    {
                        "service": "AI Magicx",
                        "current_workspace_tier": "Tier 2",
                        "candidate_lane": "background_capacity_scheduler",
                        "next_proof": "probe or retire",
                        "must_not_claim": "production",
                        "owner_review_required": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return provider, proof


def test_rows_are_stable_and_do_not_include_secret_values(tmp_path: Path) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path)
    rows = module.build_rows(provider_status_path=provider, proof_debt_path=proof)

    assert rows["ltd_provider_status"][0]["projection_id"] == "ltd-provider:1min-ai"
    assert rows["ltd_provider_status"][0]["slot_ref_sha256"] == "a" * 64
    assert rows["ltd_provider_status"][0]["route_decision"] == "eligible_for_health_probe"
    assert rows["ltd_proof_debt"][0]["projection_id"] == "ltd-proof-debt:ai-magicx"
    serialized = json.dumps(rows)
    assert "ONEMIN_AI_API_KEY" in serialized
    assert "api-secret-value" not in serialized
    assert all(not row["privacy_secret_material_exposed"] for values in rows.values() for row in values)


def test_secret_exposure_claim_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path, exposes_secret=True)

    with pytest.raises(SystemExit, match="exposes_secret_material"):
        module.build_rows(provider_status_path=provider, proof_debt_path=proof)


def test_forbidden_source_field_fails_closed_even_when_boolean_claim_is_false(tmp_path: Path) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path)
    payload = json.loads(provider.read_text(encoding="utf-8"))
    payload["providers"][0]["api_key"] = "must-not-project"
    provider.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit, match="ltd_projection_forbidden_field:api_key"):
        module.build_rows(provider_status_path=provider, proof_debt_path=proof)


def test_local_plan_can_be_written_explicitly_and_never_calls_teable(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT),
            "--provider-status-path",
            str(provider),
            "--proof-debt-path",
            str(proof),
            "--receipt-path",
            str(receipt),
            "--write-plan-receipt",
        ],
    )
    monkeypatch.setattr(module, "_request_json", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network called")))

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "plan_ready"
    assert payload["applied"] is False
    assert payload["secret_material_exposed"] is False
    assert json.loads(receipt.read_text(encoding="utf-8")) == payload


def test_default_plan_does_not_overwrite_a_live_receipt(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path)
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"status":"projection_ready"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT),
            "--provider-status-path",
            str(provider),
            "--proof-debt-path",
            str(proof),
            "--receipt-path",
            str(receipt),
        ],
    )

    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "plan_ready"
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "projection_ready"


def test_table_contracts_use_projection_ids_as_application_keys() -> None:
    module = _load_module()
    assert set(module.TABLES) == {"ltd_provider_status", "ltd_proof_debt"}
    for fields in module.TABLES.values():
        projection = fields[0]
        assert projection["name"] == "projection_id"
        assert projection["type"] == "singleLineText"


def test_teable_omitted_false_and_empty_cells_are_noop_equivalent() -> None:
    module = _load_module()
    assert module._teable_value_matches(None, False)
    assert module._teable_value_matches(None, "")
    assert module._teable_value_matches(False, False)
    assert not module._teable_value_matches(True, False)
