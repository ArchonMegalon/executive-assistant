from __future__ import annotations

import json

from scripts import materialize_pushbullet_delivery_readiness as materializer
from scripts import verify_pushbullet_delivery_readiness as verifier


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _patch_source_state(monkeypatch) -> None:
    monkeypatch.setattr(materializer, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(materializer, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")
    monkeypatch.setattr(verifier, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(verifier, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def test_pushbullet_readiness_blocks_missing_second_client_token(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "",
            "PUSHBULLET_ELISABETH_EMAIL": "Elisabeth.Girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["status"] == "blocked_setup_required"
    assert receipt["multi_client_expected"] is True
    assert receipt["required_client_keys"] == ["default", "elisabeth"]
    assert receipt["account_label"] == "default"
    assert receipt["account_label_basis"] == "literal_default_client"
    assert receipt["client_count"] == 2
    assert receipt["token_required_client_keys"] == ["default", "elisabeth"]
    assert receipt["client_coverage"]["missing_client_keys"] == []
    assert receipt["client_coverage"]["token_required_client_count"] == 2
    assert receipt["client_coverage"]["missing_token_keys"] == ["elisabeth"]
    assert receipt["client_coverage"]["multi_client_ready"] is False
    assert "pushbullet_token_missing:elisabeth" in receipt["missing_setup"]
    assert receipt["operator_action"]["user_action_required"] is True
    assert receipt["operator_action"]["telegram_push_allowed"] is True
    assert receipt["delivery_claim"]["pushbullet_note_delivery_ready"] is False
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is False
    assert "Elisabeth.Girschele@gmail.com" not in serialized
    assert "tibor@example.test" not in serialized
    assert "default-token" not in serialized
    assert "raw_token_exposed" in serialized
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_blocks_missing_primary_client(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["status"] == "blocked_setup_required"
    assert receipt["required_client_keys"] == ["default", "elisabeth"]
    assert receipt["account_label"] == "default(missing)"
    assert receipt["account_label_basis"] == "default_client_missing"
    assert receipt["client_coverage"]["missing_client_keys"] == ["default"]
    assert "pushbullet_client_missing:default" in receipt["missing_setup"]
    assert receipt["delivery_claim"]["pushbullet_note_delivery_ready"] is False
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is False
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_default_client_ref_can_cover_default_route(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "EA_PUSHBULLET_DEFAULT_CLIENT": "elisabeth",
            "PB_TOKEN_ELISABETH": "",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["status"] == "blocked_setup_required"
    assert receipt["required_client_keys"] == ["default", "elisabeth"]
    assert receipt["account_label"] == "default->elisabeth"
    assert receipt["account_label_basis"] == "default_client_ref"
    assert receipt["default_client_ref"] == "elisabeth"
    assert receipt["default_client_ref_present"] is True
    assert receipt["default_client_ref_resolves"] is True
    assert receipt["client_count"] == 1
    assert receipt["token_required_client_keys"] == ["default", "elisabeth"]
    assert receipt["client_coverage"]["configured_required_client_count"] == 2
    assert receipt["client_coverage"]["token_required_client_count"] == 2
    assert receipt["client_coverage"]["token_present_required_client_count"] == 0
    assert receipt["client_coverage"]["missing_client_keys"] == []
    assert receipt["client_coverage"]["missing_token_keys"] == ["elisabeth"]
    assert receipt["missing_setup"] == ["pushbullet_token_missing:elisabeth"]
    assert receipt["operator_action"]["default_client_ref"] == "elisabeth"
    assert receipt["operator_action"]["default_client_ref_resolves"] is True
    assert receipt["relay"]["enabled"] is False
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_ready_configured_when_token_present(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["status"] == "ready_configured"
    assert receipt["missing_setup"] == []
    assert receipt["account_label"] == "default"
    assert receipt["account_label_basis"] == "literal_default_client"
    assert receipt["operator_action"]["delivery_policy"] == "queue_only"
    assert receipt["delivery_claim"]["pushbullet_note_delivery_ready"] is True
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is True
    assert receipt["delivery_claim"]["pushbullet_relay_ready"] is True
    assert receipt["delivery_claim"]["live_token_account_verified"] is False
    assert "push-token" not in json.dumps(receipt, sort_keys=True)
    assert "default-token" not in json.dumps(receipt, sort_keys=True)
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_relay_requires_distinct_clients_when_enabled(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "EA_PUSHBULLET_RELAY_ENABLED": "1",
            "EA_PUSHBULLET_DEFAULT_CLIENT": "elisabeth",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["status"] == "blocked_setup_required"
    assert receipt["relay"]["enabled"] is True
    assert receipt["relay"]["resolved_primary_client_key"] == "elisabeth"
    assert receipt["relay"]["resolved_secondary_client_key"] == "elisabeth"
    assert receipt["relay"]["distinct_client_keys_ready"] is False
    assert receipt["relay"]["distinct_account_hashes_ready"] is False
    assert receipt["relay"]["missing_setup"] == ["pushbullet_relay_distinct_clients_required"]
    assert "pushbullet_relay_distinct_clients_required" in receipt["missing_setup"]
    assert receipt["client_coverage"]["multi_client_ready"] is False
    assert receipt["delivery_claim"]["pushbullet_relay_ready"] is False
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_reverse_relay_target_client_does_not_require_token(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "EA_PUSHBULLET_RELAY_ENABLED": "1",
            "EA_PUSHBULLET_DEFAULT_CLIENT": "elisabeth",
            "EA_PUSHBULLET_RELAY_PRIMARY_CLIENT": "tibor",
            "EA_PUSHBULLET_RELAY_SECONDARY_CLIENT": "elisabeth",
            "EA_PUSHBULLET_RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED": "0",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
            "PB_TOKEN_TIBOR": "",
            "PUSHBULLET_TIBOR_EMAIL": "tibor@example.test",
        },
    )

    assert receipt["status"] == "ready_configured"
    assert receipt["required_client_keys"] == ["default", "elisabeth", "tibor"]
    assert receipt["token_required_client_keys"] == ["default", "elisabeth"]
    assert receipt["client_coverage"]["missing_client_keys"] == []
    assert receipt["client_coverage"]["missing_token_keys"] == []
    assert receipt["relay"]["enabled"] is True
    assert receipt["relay"]["resolved_primary_client_key"] == "tibor"
    assert receipt["relay"]["resolved_secondary_client_key"] == "elisabeth"
    assert receipt["relay"]["missing_setup"] == []
    assert receipt["missing_setup"] == []
    assert receipt["delivery_claim"]["pushbullet_relay_ready"] is True
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_relay_ready_with_two_distinct_clients(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "EA_PUSHBULLET_RELAY_ENABLED": "1",
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["status"] == "ready_configured"
    assert receipt["relay"]["enabled"] is True
    assert receipt["relay"]["distinct_client_keys_ready"] is True
    assert receipt["relay"]["distinct_account_hashes_ready"] is True
    assert receipt["relay"]["missing_setup"] == []
    assert receipt["delivery_claim"]["pushbullet_relay_ready"] is True
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_live_probe_can_verify_token_account(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    def _fake_urlopen(_request, timeout=20):
        return _FakeResponse({"iden": "user-1", "email_normalized": "elisabeth.girschele@gmail.com"})

    def _fake_probe(client_key, *args, **kwargs):
        return {
            "status": "pass",
            "reason": "",
            "client_key": client_key,
            "user_id_hash": f"user-hash-{client_key}",
            "email_sha256": f"email-hash-{client_key}",
            "email_domain": "gmail.com",
            "expected_email_matches": True,
            "raw_email_exposed": False,
            "raw_token_exposed": False,
        }

    monkeypatch.setattr(materializer, "probe_pushbullet_client", _fake_probe)
    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
        probe_live=True,
    )

    assert receipt["status"] == "ready_live_verified"
    assert receipt["account_label"] == "default"
    assert receipt["account_label_basis"] == "literal_default_client"
    assert [probe["client_key"] for probe in receipt["live_probes"]] == ["default", "elisabeth"]
    assert receipt["live_probes"][0]["status"] == "pass"
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is True
    assert receipt["delivery_claim"]["live_token_account_verified"] is True
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_live_probe_mismatch_reports_token_replacement(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    def _fake_probe(client_key, *args, **kwargs):
        if client_key == "tibor":
            return {
                "status": "blocked",
                "reason": "pushbullet_account_email_mismatch",
                "client_key": client_key,
                "user_id_hash": "user-hash-elisabeth",
                "email_sha256": "email-hash-elisabeth",
                "email_domain": "gmail.com",
                "expected_email_matches": False,
                "raw_email_exposed": False,
                "raw_token_exposed": False,
            }
        return {
            "status": "pass",
            "reason": "",
            "client_key": client_key,
            "user_id_hash": f"user-hash-{client_key}",
            "email_sha256": f"email-hash-{client_key}",
            "email_domain": "gmail.com",
            "expected_email_matches": True,
            "raw_email_exposed": False,
            "raw_token_exposed": False,
        }

    monkeypatch.setattr(materializer, "probe_pushbullet_client", _fake_probe)
    receipt = materializer.build_receipt(
        env={
            "EA_PUSHBULLET_DEFAULT_CLIENT": "elisabeth",
            "EA_PUSHBULLET_RELAY_ENABLED": "1",
            "EA_PUSHBULLET_RELAY_PRIMARY_CLIENT": "tibor",
            "EA_PUSHBULLET_RELAY_SECONDARY_CLIENT": "elisabeth",
            "EA_PUSHBULLET_RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED": "1",
            "EA_PUSHBULLET_RELAY_SECONDARY_TO_PRIMARY_ALL_ENABLED": "1",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
            "PB_TOKEN_TIBOR": "tibor-token",
            "PUSHBULLET_TIBOR_EMAIL": "tibor.girschele@gmail.com",
        },
        probe_live=True,
    )

    assert receipt["status"] == "blocked_setup_required"
    assert receipt["missing_setup"] == ["pushbullet_live_probe_failed:tibor"]
    assert receipt["operator_action"]["next_action"] == "replace_mismatched_pushbullet_access_token"
    assert receipt["operator_action"]["next_action_label"] == "Replace the mismatched Pushbullet token"
    assert receipt["operator_action"]["setup_checklist"][0]["key"] == "replace_mismatched_pushbullet_access_token"
    assert "tibor" in receipt["operator_action"]["setup_checklist"][0]["how"]
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_verifier_rejects_secret_leak_flags(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )
    receipt["clients"][0]["raw_email_exposed"] = True
    receipt["privacy"]["raw_token_exposed"] = True
    receipt["operator_action"]["raw_private_context_exposed"] = True

    issues = verifier.verify_receipt_for_test(receipt)

    assert "clients[0].raw_email_exposed must be false" in issues
    assert "privacy.raw_token_exposed must be false" in issues
    assert "operator_action.raw_private_context_exposed must be false" in issues


def test_pushbullet_verifier_rejects_ready_single_client_overclaim(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )
    receipt["status"] = "ready_configured"
    receipt["missing_setup"] = []
    receipt["operator_action"]["missing_setup"] = []
    receipt["operator_action"]["user_action_required"] = False
    receipt["operator_action"]["telegram_push_allowed"] = False
    receipt["operator_action"]["interruption_budget"] = "none"
    receipt["operator_action"]["delivery_policy"] = "queue_only"
    receipt["delivery_claim"]["pushbullet_note_delivery_ready"] = True
    receipt["delivery_claim"]["multi_client_delivery_ready"] = True

    issues = verifier.verify_receipt_for_test(receipt)

    assert "missing_setup must include pushbullet_client_missing:default" in issues
    assert "ready Pushbullet receipt must cover every expected multi-client account" in issues
    assert "multi_client_delivery_ready must match status and expected-client coverage" in issues


def test_pushbullet_verifier_rejects_account_label_drift(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    receipt = materializer.build_receipt(
        env={
            "EA_PUSHBULLET_DEFAULT_CLIENT": "elisabeth",
            "PB_TOKEN_ELISABETH": "",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )
    receipt["account_label"] = "default"
    receipt["account_label_basis"] = "literal_default_client"

    issues = verifier.verify_receipt_for_test(receipt)

    assert "account_label mismatch" in issues
    assert "account_label_basis mismatch" in issues


def test_pushbullet_materializer_main_supports_pretty(monkeypatch, tmp_path, capsys) -> None:
    _patch_source_state(monkeypatch)
    monkeypatch.setattr(
        materializer,
        "build_receipt",
        lambda **_kwargs: {
            "contract_name": "ea.pushbullet_delivery_readiness.v1",
            "status": "ready_configured",
            "provider": "pushbullet",
        },
    )

    exit_code = materializer.main(
        [
            "--output",
            str(tmp_path / "ea_pushbullet_delivery_readiness.generated.json"),
            "--pretty",
        ]
    )

    printed = capsys.readouterr().out

    assert exit_code == 0
    assert '"contract_name": "ea.pushbullet_delivery_readiness.v1"' in printed
    assert '"status": "ready_configured"' in printed


def test_pushbullet_readiness_scripts_use_runtime_ledger_defaults(monkeypatch, tmp_path) -> None:
    ledger_dir = tmp_path / "provider-ledger"
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(ledger_dir))

    assert materializer._default_output_path() == ledger_dir / "pushbullet_readiness.generated.json"
    assert verifier._default_receipt_path() == ledger_dir / "pushbullet_readiness.generated.json"


def test_pushbullet_materializer_main_defaults_to_runtime_ledger(monkeypatch, tmp_path) -> None:
    _patch_source_state(monkeypatch)
    ledger_dir = tmp_path / "provider-ledger"
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(ledger_dir))
    monkeypatch.setattr(
        materializer,
        "build_receipt",
        lambda **_kwargs: {
            "contract_name": "ea.pushbullet_delivery_readiness.v1",
            "status": "ready_configured",
            "provider": "pushbullet",
        },
    )

    exit_code = materializer.main([])

    output = ledger_dir / "pushbullet_readiness.generated.json"
    assert exit_code == 0
    assert output.is_file()
    assert json.loads(output.read_text())["status"] == "ready_configured"


def test_pushbullet_verifier_allows_missing_source_git_head_without_runtime_git(monkeypatch) -> None:
    monkeypatch.setattr(materializer, "resolve_source_state_head", lambda _root: "")
    monkeypatch.setattr(materializer, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")
    monkeypatch.setattr(verifier, "resolve_source_state_head", lambda _root: "")
    monkeypatch.setattr(verifier, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")

    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["source_git_head"] == ""
    assert verifier.verify_receipt_for_test(receipt) == []
