from __future__ import annotations

import importlib.util
import hashlib
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


def _write_sources(
    tmp_path: Path,
    *,
    provider_exposes_secret: bool = False,
    proof_exposes_secret: bool = False,
    stale_sources: bool = False,
) -> tuple[Path, Path]:
    capacity_config_sha = hashlib.sha256((ROOT / "config/ltd_capacity_scheduler.yaml").read_bytes()).hexdigest()
    inventory_sha = hashlib.sha256((ROOT / "LTDs.md").read_bytes()).hexdigest()
    if stale_sources:
        capacity_config_sha = "0" * 64
        inventory_sha = "0" * 64
    provider = tmp_path / "provider.json"
    provider.write_text(
        json.dumps(
            {
                "contract": "ea.ltd_capacity_status.v1",
                "generated_at": "2026-08-13T00:00:00Z",
                "status": "ready_for_bounded_probe",
                "config_sha256": capacity_config_sha,
                "secret_material_exposed": provider_exposes_secret,
                "truth_posture": "boolean presence only",
                "providers": [
                    {
                        "provider": "1min.AI",
                        "configured_state": "active_background_candidate",
                        "credential_present": True,
                        "credential_slot": "ONEMIN_AI_API_KEY",
                        "maximum_blast_radius": "public_safe",
                        "review_required": True,
                        "route_state": "eligible_for_health_probe",
                        "credit_balance_state": "unverified",
                        "slot_health_state": "unverified",
                        "dispatch_eligible": False,
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
                "contract": "ea.ltd_proof_debt.v1",
                "generated_at": "2026-08-13T00:00:00Z",
                "status": "projection_ready",
                "source_sha256": inventory_sha,
                "secret_material_exposed": proof_exposes_secret,
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
    assert rows["ltd_provider_status"][0]["dispatch_eligible"] is False
    assert rows["ltd_proof_debt"][0]["projection_id"] == "ltd-proof-debt:ai-magicx"
    assert all(row["current_or_stale"] == "current" for values in rows.values() for row in values)
    serialized = json.dumps(rows)
    assert "ONEMIN_AI_API_KEY" in serialized
    assert "api-secret-value" not in serialized
    assert all(not row["privacy_secret_material_exposed"] for values in rows.values() for row in values)


def test_secret_exposure_claim_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path, provider_exposes_secret=True)

    with pytest.raises(SystemExit, match="exposes_secret_material"):
        module.build_rows(provider_status_path=provider, proof_debt_path=proof)


def test_proof_debt_secret_exposure_claim_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path, proof_exposes_secret=True)

    with pytest.raises(SystemExit, match="proof_debt_projection_exposes_secret_material"):
        module.build_rows(provider_status_path=provider, proof_debt_path=proof)


def test_stale_sources_are_marked_and_cannot_be_applied(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    provider, proof = _write_sources(tmp_path, stale_sources=True)
    rows = module.build_rows(provider_status_path=provider, proof_debt_path=proof)
    assert all(row["current_or_stale"] == "stale" for values in rows.values() for row in values)

    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT),
            "--provider-status-path",
            str(provider),
            "--proof-debt-path",
            str(proof),
            "--apply",
        ],
    )
    monkeypatch.setattr(
        module,
        "_api_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("credentials accessed")),
    )

    with pytest.raises(SystemExit, match="ltd_projection_sources_stale"):
        module.main()


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
