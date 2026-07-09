from __future__ import annotations

import json
from pathlib import Path

from app.services.proactive_ooda_goal_actions import goal_action_queue_signals
from scripts.materialize_continuous_improvement_goal_posture import build_goal_posture
import scripts.materialize_continuous_improvement_goal_posture as posture_module
import scripts.verify_continuous_improvement_goal_posture as verifier_module
from scripts.verify_continuous_improvement_goal_posture import verify

GOOGLE_REAUTH_ACTION_HREF = (
    "/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
)


def _office_provider_cost_routing_posture() -> dict[str, object]:
    return {
        "status": "active_cost_control",
        "background_routing": {
            "primary_background_provider": "onemin",
            "primary_background_provider_label": "1min.ai",
            "default_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "fast_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "cost_sensitive_lanes": ["groundwork", "fast", "overflow", "review", "review_light", "audit"],
            "onemin_preferred_when_speed_is_not_critical": True,
            "onemin_preferred_whenever_usable": True,
        },
        "gemini_vertex": {
            "provider_key": "gemini_vortex",
            "token_tracking_required": True,
            "dispatch_ledger": "provider_dispatch_events.jsonl",
            "live_pressure_probe_command": "python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json",
            "live_pressure_probe_source": "runtime_container_exec:provider_ledger_cache",
            "soft_cap_env": "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H",
            "soft_cap_window_env": "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS",
            "soft_cap_action": "remove_gemini_vortex_from_cost_gated_background_candidate_lists",
            "explicit_gemini_requests_allowed": True,
            "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
        },
        "privacy": {
            "raw_provider_secret_exposed": False,
            "raw_prompt_or_response_text_exposed": False,
            "raw_google_cloud_billing_account_exposed": False,
        },
    }


def test_pushbullet_action_context_uses_default_client_ref_alias_token_env() -> None:
    context = posture_module._pushbullet_delivery_action_context(
        {
            "multi_client_expected": True,
            "client_count": 1,
            "required_client_keys": ["default", "elisabeth"],
            "default_client_ref": "elisabeth",
            "default_client_ref_present": True,
            "default_client_ref_resolves": True,
            "client_coverage": {
                "multi_client_expected": True,
                "configured_required_client_count": 2,
                "token_present_required_client_count": 0,
                "missing_client_keys": [],
                "missing_token_keys": ["elisabeth"],
                "multi_client_ready": False,
            },
            "missing_setup": ["pushbullet_token_missing:elisabeth"],
            "delivery_claim": {
                "pushbullet_note_delivery_ready": False,
                "multi_client_delivery_ready": False,
                "live_token_account_verified": False,
            },
            "clients": [
                {
                    "client_key": "elisabeth",
                    "token_env": "PB_TOKEN_ELISABETH",
                    "token_present": False,
                }
            ],
            "operator_action": {
                "user_action_required": True,
                "missing_setup": ["pushbullet_token_missing:elisabeth"],
                "required_client_keys": ["default", "elisabeth"],
                "default_client_ref": "elisabeth",
                "default_client_ref_present": True,
                "default_client_ref_resolves": True,
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "next_action_href": "https://www.pushbullet.com/#settings/account",
                "setup_checklist": [{"key": "create_pushbullet_access_token"}],
                "raw_email_exposed": False,
                "raw_token_exposed": False,
                "raw_private_context_exposed": False,
            },
            "privacy": {
                "raw_email_exposed": False,
                "raw_token_exposed": False,
            },
            "account_settings_url": "https://www.pushbullet.com/#settings/account",
        }
    )

    assert context["default_client_ref"] == "elisabeth"
    assert context["default_client_ref_present"] is True
    assert context["default_client_ref_resolves"] is True
    assert context["pushbullet_token_envs"] == ["PB_TOKEN_ELISABETH"]
    assert context["pushbullet_missing_token_envs"] == ["PB_TOKEN_ELISABETH"]
    assert context["missing_setup"] == ["pushbullet_token_missing:elisabeth"]
    assert "PB_TOKEN_ELISABETH" in context["telegram_message"]


def test_pushbullet_action_context_calls_out_distinct_relay_and_account_mismatch() -> None:
    context = posture_module._pushbullet_delivery_action_context(
        {
            "multi_client_expected": True,
            "client_count": 1,
            "required_client_keys": ["default", "elisabeth"],
            "default_client_ref": "elisabeth",
            "default_client_ref_present": True,
            "default_client_ref_resolves": True,
            "client_coverage": {
                "multi_client_expected": True,
                "configured_required_client_count": 2,
                "token_present_required_client_count": 2,
                "missing_client_keys": [],
                "missing_token_keys": [],
                "multi_client_ready": False,
            },
            "missing_setup": [
                "pushbullet_live_probe_failed:elisabeth",
                "pushbullet_relay_distinct_clients_required",
            ],
            "delivery_claim": {
                "pushbullet_note_delivery_ready": False,
                "multi_client_delivery_ready": False,
                "live_token_account_verified": False,
            },
            "live_probes": [
                {
                    "client_key": "elisabeth",
                    "status": "blocked",
                    "reason": "pushbullet_account_email_mismatch",
                    "expected_email_matches": False,
                    "raw_email_exposed": False,
                    "raw_token_exposed": False,
                }
            ],
            "relay": {
                "enabled": True,
                "primary_client_key": "default",
                "secondary_client_key": "elisabeth",
                "resolved_primary_client_key": "elisabeth",
                "resolved_secondary_client_key": "elisabeth",
                "distinct_client_keys_ready": False,
                "distinct_account_hashes_ready": False,
            },
            "clients": [
                {
                    "client_key": "elisabeth",
                    "token_env": "PB_TOKEN_ELISABETH",
                    "token_present": True,
                }
            ],
            "operator_action": {
                "user_action_required": True,
                "missing_setup": [
                    "pushbullet_live_probe_failed:elisabeth",
                    "pushbullet_relay_distinct_clients_required",
                ],
                "required_client_keys": ["default", "elisabeth"],
                "default_client_ref": "elisabeth",
                "default_client_ref_present": True,
                "default_client_ref_resolves": True,
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "next_action_href": "https://www.pushbullet.com/#settings/account",
                "raw_email_exposed": False,
                "raw_token_exposed": False,
                "raw_private_context_exposed": False,
            },
            "privacy": {
                "raw_email_exposed": False,
                "raw_token_exposed": False,
            },
            "account_settings_url": "https://www.pushbullet.com/#settings/account",
        }
    )

    assert context["relay_distinct_clients_required"] is True
    assert context["relay_resolved_primary_client_key"] == "elisabeth"
    assert context["relay_resolved_secondary_client_key"] == "elisabeth"
    assert context["live_probe_failed_client_keys"] == ["elisabeth"]
    assert context["account_mismatch_client_keys"] == ["elisabeth"]
    assert context["pushbullet_missing_token_envs"] == ["PB_TOKEN_ELISABETH"]
    assert context["action_required_reason"] == "pushbullet_relay_distinct_clients_required,pushbullet_account_email_mismatch"
    assert "same Pushbullet account" in context["telegram_message"]
    assert "Elisabeth token" in context["telegram_message"]
    checklist_keys = {item["key"] for item in context["setup_checklist"]}
    assert "configure_pushbullet_relay_clients" in checklist_keys
    assert "reissue_pushbullet_token:elisabeth" in checklist_keys
    assert "verify_pushbullet_account_match" in checklist_keys


def test_load_receipt_prefers_runtime_pushbullet_readiness_when_newer(tmp_path, monkeypatch) -> None:
    published_path = tmp_path / ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json"
    published_path.parent.mkdir(parents=True, exist_ok=True)
    published_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.pushbullet_delivery_readiness.v1",
                "generated_at": "2026-07-07T03:00:00Z",
                "status": "blocked_setup_required",
                "missing_setup": ["pushbullet_token_missing:elisabeth"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "provider-ledger"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / "pushbullet_readiness.generated.json"
    runtime_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.pushbullet_delivery_readiness.v1",
                "generated_at": "2026-07-07T04:45:48Z",
                "status": "blocked_setup_required",
                "missing_setup": [
                    "pushbullet_live_probe_failed:elisabeth",
                    "pushbullet_relay_distinct_clients_required",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(runtime_dir))

    payload, resolved_path = posture_module._load_receipt(tmp_path, published_path)

    assert payload["missing_setup"] == [
        "pushbullet_live_probe_failed:elisabeth",
        "pushbullet_relay_distinct_clients_required",
    ]
    assert resolved_path.endswith("provider-ledger/pushbullet_readiness.generated.json")


def test_load_receipt_can_discover_runtime_ledger_via_docker_inspect(tmp_path, monkeypatch) -> None:
    published_path = tmp_path / ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json"
    published_path.parent.mkdir(parents=True, exist_ok=True)
    published_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.pushbullet_delivery_readiness.v1",
                "generated_at": "2026-07-07T03:00:00Z",
                "status": "blocked_setup_required",
                "missing_setup": ["pushbullet_token_missing:elisabeth"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "docker-volume-ledger"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / "pushbullet_readiness.generated.json"
    runtime_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.pushbullet_delivery_readiness.v1",
                "generated_at": "2026-07-07T05:04:52Z",
                "status": "blocked_setup_required",
                "missing_setup": ["pushbullet_live_probe_failed:elisabeth"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class _DockerInspectResult:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    monkeypatch.delenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", raising=False)
    monkeypatch.delenv("EA_RESPONSES_PROVIDER_LEDGER_HOST_DIR", raising=False)
    monkeypatch.setattr(posture_module, "ROOT", tmp_path)
    monkeypatch.setattr(
        posture_module.subprocess,
        "run",
        lambda *args, **kwargs: _DockerInspectResult(f"{runtime_dir}\n"),
    )

    payload, resolved_path = posture_module._load_receipt(tmp_path, published_path)

    assert payload["missing_setup"] == ["pushbullet_live_probe_failed:elisabeth"]
    assert resolved_path.endswith("docker-volume-ledger/pushbullet_readiness.generated.json")


def test_load_receipt_prefers_runtime_receipt_over_newer_published_copy(tmp_path, monkeypatch) -> None:
    published_path = tmp_path / ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json"
    published_path.parent.mkdir(parents=True, exist_ok=True)
    published_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.pushbullet_delivery_readiness.v1",
                "generated_at": "2026-07-07T06:00:00Z",
                "status": "blocked_setup_required",
                "missing_setup": ["pushbullet_relay_distinct_clients_required"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "provider-ledger"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / "pushbullet_readiness.generated.json"
    runtime_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.pushbullet_delivery_readiness.v1",
                "generated_at": "2026-07-07T05:04:52Z",
                "status": "blocked_setup_required",
                "missing_setup": ["pushbullet_live_probe_failed:elisabeth"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(runtime_dir))

    payload, resolved_path = posture_module._load_receipt(tmp_path, published_path)

    assert payload["missing_setup"] == ["pushbullet_live_probe_failed:elisabeth"]
    assert resolved_path.endswith("provider-ledger/pushbullet_readiness.generated.json")


def test_load_receipt_can_fall_back_to_docker_exec_runtime_payload(tmp_path, monkeypatch) -> None:
    published_path = tmp_path / ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json"
    published_path.parent.mkdir(parents=True, exist_ok=True)
    published_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.pushbullet_delivery_readiness.v1",
                "generated_at": "2026-07-07T06:00:00Z",
                "status": "blocked_setup_required",
                "missing_setup": ["pushbullet_relay_distinct_clients_required"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class _RunResult:
        def __init__(self, *, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    def _fake_run(args, **kwargs):
        if args[:3] == ["docker", "exec", "ea-scheduler"]:
            return _RunResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "contract_name": "ea.pushbullet_delivery_readiness.v1",
                        "generated_at": "2026-07-07T05:04:52Z",
                        "status": "blocked_setup_required",
                        "missing_setup": ["pushbullet_live_probe_failed:elisabeth"],
                    }
                ),
            )
        return _RunResult(returncode=1, stdout="")

    monkeypatch.delenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", raising=False)
    monkeypatch.delenv("EA_RESPONSES_PROVIDER_LEDGER_HOST_DIR", raising=False)
    monkeypatch.setattr(posture_module, "ROOT", tmp_path)
    monkeypatch.setattr(posture_module.subprocess, "run", _fake_run)

    payload, resolved_path = posture_module._load_receipt(tmp_path, published_path)

    assert payload["missing_setup"] == ["pushbullet_live_probe_failed:elisabeth"]
    assert resolved_path == "docker-exec:ea-scheduler:/data/provider-ledger/pushbullet_readiness.generated.json"


def _operator_provider_cost_pressure() -> dict[str, object]:
    return {
        "checked": True,
        "probe_ok": True,
        "status": "active_cost_control",
        "source": "runtime_container_exec:ea-api:provider_ledger_cache",
        "observed_at": "2026-07-02T09:25:00Z",
        "window": "24h",
        "primary_background_provider": "onemin",
        "provider_order": ["onemin", "magixai", "gemini_vortex"],
        "fast_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "cost_sensitive_lanes": ["groundwork", "fast", "overflow", "review", "review_light", "audit"],
        "onemin_preferred_when_speed_is_not_critical": True,
        "onemin_preferred_whenever_usable": True,
        "onemin_usable": True,
        "onemin_ready_slots": 18,
        "onemin_configured_slots": 70,
        "gemini_provider_key": "gemini_vortex",
        "gemini_token_tracking": {
            "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
            "24h": {
                "request_count": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0,
                "soft_cap_tokens": 200000,
                "state": "within_soft_cap",
            },
            "background_cost_gate": "open",
            "explicit_gemini_requests_allowed": True,
            "soft_cap_percent_24h": 0.0,
        },
        "routing_decision": "prefer_onemin_background_when_usable",
        "requires_recovery": False,
        "privacy": {
            "raw_provider_secret_exposed": False,
            "raw_prompt_or_response_text_exposed": False,
            "raw_google_cloud_billing_account_exposed": False,
            "raw_provider_slots_exposed": False,
        },
    }


def _live_provider_cost_pressure_probe_payload() -> dict[str, object]:
    return {
        "probe_ok": True,
        "status": "active_cost_control",
        "source": "runtime_container_exec:ea-api:provider_ledger_cache",
        "observed_at": "2026-07-06T11:53:55Z",
        "window": "24h",
        "primary_background_provider": "onemin",
        "provider_order": ["onemin", "magixai", "gemini_vortex"],
        "fast_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "cost_sensitive_lanes": ["audit", "fast", "groundwork", "overflow", "review", "review_light"],
        "onemin_preferred_when_speed_is_not_critical": True,
        "onemin_preferred_whenever_usable": True,
        "onemin_usable": True,
        "onemin_ready_slots": 17,
        "onemin_configured_slots": 70,
        "gemini_provider_key": "gemini_vortex",
        "gemini_token_tracking": {
            "24h": {
                "request_count": 0,
                "soft_cap_tokens": 200000,
                "state": "within_soft_cap",
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0,
                "window_seconds": 86400.0,
            },
            "background_cost_gate": "open",
            "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
            "explicit_gemini_requests_allowed": True,
            "selected_window": {
                "request_count": 0,
                "soft_cap_tokens": 200000,
                "state": "within_soft_cap",
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0,
                "window_seconds": 86400.0,
            },
            "soft_cap_percent_24h": 0.0,
        },
        "routing_decision": "prefer_onemin_background_when_usable",
        "requires_recovery": False,
        "privacy": {
            "raw_google_cloud_billing_account_exposed": False,
            "raw_prompt_or_response_text_exposed": False,
            "raw_provider_secret_exposed": False,
            "raw_provider_slots_exposed": False,
        },
    }


def _write_receipt(
    root: Path,
    relative_path: str,
    *,
    status: str,
    source_git_head: str = "source-head",
    source_state_fingerprint: str = "source-fingerprint",
    **extra: object,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "contract_name": f"test.{path.stem}"}
    if source_git_head:
        payload["source_git_head"] = source_git_head
    if source_state_fingerprint:
        payload["source_state_fingerprint"] = source_state_fingerprint
    if relative_path.endswith("ea_office_loop_goal.generated.json"):
        payload["provider_cost_routing_posture"] = _office_provider_cost_routing_posture()
    payload.update(extra)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _set_source_state(monkeypatch, *, head: str = "source-head", fingerprint: str = "source-fingerprint") -> None:
    monkeypatch.setattr(posture_module, "_git_head", lambda _root: head)
    monkeypatch.setattr(posture_module, "_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(verifier_module, "_git_head", lambda _root: head)
    monkeypatch.setattr(verifier_module, "_source_fingerprint", lambda _root: fingerprint)


def _write_proactive_ooda_receipts(
    root: Path,
    *,
    source_git_head: str = "source-head",
    source_state_fingerprint: str = "source-fingerprint",
    gold_status: str = "blocked_low_quality_packet_evidence",
    gold_claim_allowed: bool = False,
    gold_remaining_external_proofs: list[str] | None = None,
    gold_approval_accepted: bool = False,
    gold_summary: str = "The proactive OODA mechanics have evidence, but the selected packet is not assistant-grade enough to prove production readiness.",
    gold_next_action: str = "stage_fresh_assistant_grade_proactive_packet",
    gold_next_action_href: str = "/app/queue",
    gold_next_action_label: str = "Open queue",
    gold_next_action_method: str = "get",
    operator_approval_capture_surface: dict[str, object] | None = None,
    operator_status_override: str | None = None,
    operator_reason_override: str | None = None,
    operator_summary_override: str | None = None,
    operator_next_action_override: str | None = None,
    operator_next_action_href_override: str | None = None,
    operator_next_action_label_override: str | None = None,
    operator_next_action_method_override: str | None = None,
    operator_extra: dict[str, object] | None = None,
) -> None:
    extra = {"source_git_head": source_git_head} if source_git_head else {}
    if source_state_fingerprint:
        extra["source_state_fingerprint"] = source_state_fingerprint
    if gold_remaining_external_proofs is None:
        gold_remaining_external_proofs = [
            "assistant-grade source intent and candidate alignment for the proactive OODA packet",
            "redacted explicit approval outcome for the proactive OODA packet",
        ]
    operator_status = "ready_with_recovery_action"
    operator_reason = "internal_action_not_assistant_grade"
    operator_summary = gold_summary
    operator_next_action = gold_next_action
    operator_next_action_href = gold_next_action_href
    operator_next_action_label = gold_next_action_label
    operator_next_action_method = gold_next_action_method
    if gold_status == "pass":
        operator_status = "ready_with_live_receipt"
        operator_reason = "ready"
        operator_summary = (
            "Proactive OODA route, packet runtime, latest host-visible live receipt, "
            "Telegram approval, and manual approval outcome capture are ready for operator follow-through."
        )
        operator_next_action = "maintain_proactive_ooda_gold_acceptance_evidence"
        operator_next_action_href = "/app/today"
        operator_next_action_label = "Open Today"
        operator_next_action_method = "get"
        if gold_next_action == "stage_fresh_assistant_grade_proactive_packet":
            gold_next_action = operator_next_action
            gold_next_action_href = operator_next_action_href
            gold_next_action_label = operator_next_action_label
            gold_next_action_method = operator_next_action_method
    elif gold_status == "ready_for_approval_outcome_capture":
        operator_status = "ready_with_live_receipt"
        operator_reason = "ready"
        operator_summary = (
            "A proactive OODA packet has local gold-proof runtime evidence and a live Telegram approval "
            "capture surface; capture the redacted approval outcome next."
        )
        operator_next_action = "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
        operator_next_action_href = "https://myexternalbrain.com/admin/proactive-ooda/approval"
        operator_next_action_label = "Record packet verdict"
        operator_next_action_method = "get"
        if gold_next_action == "stage_fresh_assistant_grade_proactive_packet":
            gold_next_action = operator_next_action
            gold_next_action_href = operator_next_action_href
            gold_next_action_label = operator_next_action_label
            gold_next_action_method = operator_next_action_method
    if operator_status_override is not None:
        operator_status = operator_status_override
    if operator_reason_override is not None:
        operator_reason = operator_reason_override
    if operator_summary_override is not None:
        operator_summary = operator_summary_override
    if operator_next_action_override is not None:
        operator_next_action = operator_next_action_override
    if operator_next_action_href_override is not None:
        operator_next_action_href = operator_next_action_href_override
    if operator_next_action_label_override is not None:
        operator_next_action_label = operator_next_action_label_override
    if operator_next_action_method_override is not None:
        operator_next_action_method = operator_next_action_method_override
    operator_extra_payload = dict(operator_extra or {})
    provider_cost_pressure = operator_extra_payload.pop("provider_cost_pressure", _operator_provider_cost_pressure())
    _write_receipt(
        root,
        ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
        status=gold_status,
        gold_claim_allowed=gold_claim_allowed,
        remaining_external_proofs=gold_remaining_external_proofs,
        proofs={"approval_outcome": {"accepted": gold_approval_accepted}},
        summary=gold_summary,
        next_action=gold_next_action,
        next_action_href=gold_next_action_href,
        next_action_label=gold_next_action_label,
        next_action_method=gold_next_action_method,
        **extra,
    )
    _write_receipt(
        root,
        ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
        status=operator_status,
        reason=operator_reason,
        summary=operator_summary,
        next_action=operator_next_action,
        next_action_href=operator_next_action_href,
        next_action_label=operator_next_action_label,
        next_action_method=operator_next_action_method,
        provider_cost_pressure=provider_cost_pressure,
        approval_capture_surface=operator_approval_capture_surface or {},
        **operator_extra_payload,
        **extra,
    )


def _write_teable_recovery_proof_receipt(
    root: Path,
    *,
    status: str = "pass",
    source_git_head: str = "",
    source_state_fingerprint: str = "",
) -> None:
    _write_receipt(
        root,
        ".codex-studio/published/teable_env_recovery_proof.generated.json",
        status=status,
        source_git_head=source_git_head,
        source_state_fingerprint=source_state_fingerprint,
        generated_by="scripts/materialize_teable_env_recovery_proof.py",
        recovery_status="recovered" if status == "pass" else "failed",
        fresh_host_api_key_source="process_env",
        secret_values_redacted=True,
        drill_output_removed=True,
        privacy={
            "raw_paths_exposed": False,
            "raw_table_id_exposed": False,
            "raw_api_key_exposed": False,
            "secret_values_exposed": False,
        },
        env_files=[
            {
                "scope": "ea_root",
                "path_sha256": "1",
                "path_recorded": True,
                "restored": 1,
                "hash_verified": 1,
                "hash_mismatch_count": 0,
                "backup_created": False,
                "mode": "0o600",
            },
            {
                "scope": "ea_root_local",
                "path_sha256": "2",
                "path_recorded": True,
                "restored": 1,
                "hash_verified": 1,
                "hash_mismatch_count": 0,
                "backup_created": False,
                "mode": "0o600",
            },
            {
                "scope": "ea_service",
                "path_sha256": "3",
                "path_recorded": True,
                "restored": 1,
                "hash_verified": 1,
                "hash_mismatch_count": 0,
                "backup_created": False,
                "mode": "0o600",
            },
        ],
        referenced_files={
            "restored": 0,
            "hash_verified": 0,
            "hash_mismatch_count": 0,
            "backup_count": 0,
            "path_count": 0,
            "path_sha256": [],
            "modes": [],
        },
        verification={
            "status": "pass" if status == "pass" else "fail",
            "expected_rows": 3,
            "same_hash": 3 if status == "pass" else 0,
            "missing_count": 0,
            "different_hash_count": 0,
            "missing_secret_value_count": 0,
            "extra_restorable_count": 0,
        },
    )


def _write_operator_readiness_receipt(
    root: Path,
    *,
    status: str = "ready_with_actions",
    ready: bool = False,
    pairing_probe_mode: str = "passive",
    component_keys: list[str] | None = None,
    steering_component_keys: list[str] | None = None,
    attention_component_keys: list[str] | None = None,
    blocked_count: int = 3,
    probe_failed_count: int = 0,
    supplemental_attention_component_keys: list[str] | None = None,
    supplemental_next_actions: list[dict[str, object]] | None = None,
    next_action: str = "set_google_workspace_expected_email_and_refresh_receipt",
    summary: str = (
        "operator_readiness status=ready_with_actions; ready=false; components=8; "
        "attention=4; blocked=3; probe_failed=0"
    ),
) -> None:
    if component_keys is None:
        component_keys = [
            "telegram",
            "google_workspace_oauth",
            "pushbullet",
            "whatsapp",
            "teable_recovery",
            "mymedia_alexa",
            "proactive_route",
            "proactive_artifacts",
        ]
    if attention_component_keys is None:
        attention_component_keys = [
            "google_workspace_oauth",
            "pushbullet",
            "whatsapp",
            "mymedia_alexa",
        ]
    if steering_component_keys is None:
        steering_component_keys = list(component_keys)
    if supplemental_attention_component_keys is None:
        supplemental_attention_component_keys = []
    if supplemental_next_actions is None:
        supplemental_next_actions = []
    _write_receipt(
        root,
        ".codex-studio/published/ea_operator_readiness.generated.json",
        status=status,
        ready=ready,
        pairing_probe_mode=pairing_probe_mode,
        component_count=len(component_keys),
        blocked_count=blocked_count,
        probe_failed_count=probe_failed_count,
        supplemental_attention_count=len(supplemental_attention_component_keys),
        supplemental_blocked_count=0,
        supplemental_probe_failed_count=0,
        component_keys=component_keys,
        steering_component_keys=steering_component_keys,
        attention_component_keys=attention_component_keys,
        supplemental_attention_component_keys=supplemental_attention_component_keys,
        supplemental_next_actions=supplemental_next_actions,
        next_action=next_action,
        summary=summary,
        privacy={
            "raw_component_payload_exposed": False,
            "raw_delivery_token_exposed": False,
            "raw_qr_artifact_exposed": False,
            "raw_chat_ref_exposed": False,
        },
    )


def _write_acceptance_receipt_with_morning_brief_accepted(root: Path) -> None:
    accepted_row = {
        "accepted": True,
        "status": "accepted_redacted",
        "source_kind": "operator_admin",
        "recorded_at": "2026-06-30T10:41:57Z",
        "evidence_sha256": "evidence-hash",
        "actor_sha256": "actor-hash",
        "object_ref_sha256": "object-hash",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }
    _write_receipt(
        root,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="partial_real_world_acceptance_evidence",
        acceptance_keys={"real_daily_morning_brief_accepted": accepted_row},
        acceptance_capture_requirements=[
            {
                "key": "real_daily_morning_brief_accepted",
                "proof_key": "real_daily_morning_brief_accepted",
                "accepted": True,
                "status": "accepted_redacted",
            }
        ],
    )


def _write_acceptance_receipt_with_pending_quality_keys(root: Path) -> None:
    accepted_row = {
        "accepted": True,
        "status": "accepted_redacted",
        "source_kind": "operator_admin",
        "recorded_at": "2026-06-30T10:41:57Z",
        "evidence_sha256": "evidence-hash",
        "actor_sha256": "actor-hash",
        "object_ref_sha256": "object-hash",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }
    pending_keys = [
        "real_commitment_recovered_or_closed",
        "real_approved_action_audited",
        "real_provider_failure_recovered",
    ]
    acceptance_keys = {
        "real_daily_morning_brief_accepted": accepted_row,
        **{
            key: {
                "accepted": False,
                "status": "missing_or_invalid",
                "source_kind": "unknown",
                "recorded_at": "",
                "evidence_sha256": "",
                "actor_sha256": "",
                "object_ref_sha256": "",
                "raw_evidence_exposed": False,
                "raw_actor_exposed": False,
                "raw_object_ref_exposed": False,
            }
            for key in pending_keys
        },
    }
    _write_receipt(
        root,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="partial_real_world_acceptance_evidence",
        acceptance_keys=acceptance_keys,
        acceptance_capture_requirements=[
            {
                "key": "real_daily_morning_brief_accepted",
                "proof_key": "real_daily_morning_brief_accepted",
                "accepted": True,
                "status": "accepted_redacted",
            },
            *[
                {
                    "key": key,
                    "proof_key": key,
                    "accepted": False,
                    "status": "pending_real_world_evidence",
                }
                for key in pending_keys
            ],
        ],
    )


def test_stale_source_action_context_is_queue_only_and_redacted() -> None:
    context = posture_module._stale_source_action_context(
        receipts=[
            {
                "path": ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
                "present": True,
                "source_fresh_to_current_source": False,
            },
            {
                "path": ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
                "present": True,
                "source_fresh_to_current_source": True,
            },
        ],
        refresh_commands=[
            "PYTHONPATH=ea python3 ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
            "python3 scripts/verify_continuous_improvement_goal_posture.py --pretty",
        ],
    )

    assert context["kind"] == "stale_source_evidence_refresh"
    assert context["user_action_required"] is False
    assert context["delivery_policy"] == "queue_only"
    assert context["telegram_push_allowed"] is False
    assert context["non_action_progress_push_allowed"] is False
    assert context["stale_source_receipts"] == ["whatsapp_audiobook_live_delivery.generated.json"]
    assert "materialize_whatsapp_audiobook_live_delivery_receipt.py" in context["refresh_commands"][0]
    assert context["raw_private_context_exposed"] is False
    assert context["raw_chat_ids_exposed"] is False
    assert context["raw_token_exposed"] is False
    assert context["raw_secret_exposed"] is False


def test_whatsapp_sidecar_pairing_context_is_action_required_and_redacted() -> None:
    context = posture_module._whatsapp_sidecar_pairing_action_context(
        readiness_receipt={
            "status": "blocked",
            "reason": "sidecar_not_ready",
            "reasons": ["sidecar_not_ready"],
            "sidecar_ready": False,
            "sidecar_status": "qr_required",
            "sidecar_qr_required": True,
            "sidecar_qr_present": True,
            "sidecar_qr_fresh": True,
            "sidecar_qr_age_seconds": 12,
        },
        bundle_receipt={
            "live_readiness": {"status": "blocked", "reason": "sidecar_not_ready", "sidecar_ready": False},
            "live_sidecar_inbox": {"session_status": "qr_required", "session_api_host_kind": "loopback"},
        },
    )

    assert context["kind"] == "whatsapp_web_sidecar_pairing_required"
    assert context["user_action_required"] is True
    assert context["delivery_policy"] == "action_required_only"
    assert context["telegram_push_allowed"] is True
    assert context["sidecar_status"] == "qr_required"
    assert context["sidecar_qr_required"] is True
    assert context["sidecar_qr_present"] is True
    assert context["pair_url_scope"] == "host_local"
    assert context["pair_url_actionable_from_telegram"] is False
    assert context["raw_pair_url_exposed"] is False
    assert context["raw_qr_payload_exposed"] is False
    assert context["raw_whatsapp_session_ref_exposed"] is False
    assert "pair URLs or QR payloads" in context["telegram_message"]


def test_operator_form_surface_prefers_explicit_action_context_for_non_catalogued_actions() -> None:
    form_surface = posture_module._operator_form_surface(  # noqa: SLF001
        "enter_mymedia_amazon_pairing_code",
        {
            "next_action_form_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_form_label": "Open My Media setup",
            "next_action_form_method": "get",
        },
    )

    assert form_surface == {
        "next_action_form_href": "http://127.0.0.1:52051/index.html#!/setup",
        "next_action_form_label": "Open My Media setup",
        "next_action_form_method": "get",
    }


def test_accepted_morning_brief_evidence_is_satisfied_not_operator_action(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_acceptance_receipt_with_morning_brief_accepted(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-22T15:00:00Z",
    )

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    morning_requirement = proof_requirements["morning_brief_operator_acceptance"]
    assert morning_requirement["status"] == "satisfied"
    assert morning_requirement["action_context"]["user_action_required"] is False
    assert morning_requirement["action_context"]["delivery_policy"] == "queue_only"
    assert morning_requirement["action_context"]["telegram_push_allowed"] is False
    assert morning_requirement["action_context"]["interruption_budget"] == "none"
    assert "real operator acceptance that the morning brief was worth reading" not in receipt["required_next_receipts"]
    assert "morning_brief_operator_acceptance" not in {
        item["key"] for item in receipt["operator_action_queue"]
    }


def test_weekly_signal_review_acceptance_sorts_after_concrete_setup_actions() -> None:
    requirements = [
        {
            "key": "weekly_signal_to_decision_review_acceptance",
            "title": "Weekly signal-to-decision review acceptance",
            "lens": "detect",
            "status": "pending_real_world_evidence",
            "action_context": {
                "user_action_required": True,
                "kind": "real_world_acceptance_capture",
                "telegram_push_allowed": False,
            },
        },
        {
            "key": "google_workspace_oauth_setup",
            "title": "Google Workspace OAuth test-user setup",
            "lens": "detect",
            "status": "pending_setup",
            "action_context": {
                "user_action_required": True,
                "kind": "google_workspace_oauth_setup",
            },
        },
        {
            "key": "pushbullet_delivery_setup",
            "title": "Pushbullet delivery setup",
            "lens": "detect",
            "status": "pending_setup",
            "action_context": {
                "user_action_required": True,
                "kind": "pushbullet_delivery_setup",
            },
        },
    ]

    queue = posture_module._operator_action_queue(requirements)  # noqa: SLF001

    assert [item["key"] for item in queue] == [
        "google_workspace_oauth_setup",
        "pushbullet_delivery_setup",
        "weekly_signal_to_decision_review_acceptance",
    ]
    weekly = queue[-1]
    assert weekly["user_action_required"] is True
    assert weekly["telegram_push_allowed"] is False
    assert weekly["action_digest_eligible"] is False
    assert weekly["default_action_digest_suppressed_reason"] == "telegram_push_not_allowed"


def test_google_manual_console_check_becomes_blocking_operator_action(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_proactive_ooda_receipts(tmp_path)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
        status="ready_manual_console_check",
        scope_bundle="full_workspace",
        console_deep_link="https://console.cloud.google.com/auth/audience?project=openclaw-concierge",
        auth_link_template=(
            "https://myexternalbrain.com/app/actions/google/connect?"
            "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&"
            "expected_google_email=%3Credacted-email%3E"
        ),
        missing_setup=["oauth_test_user_confirmation_pending"],
        privacy={
            "raw_expected_google_email_exposed": False,
            "raw_observed_google_email_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_access_token_exposed": False,
            "raw_refresh_token_exposed": False,
            "raw_error_description_exposed": False,
        },
        operator_action={
            "user_action_required": True,
            "instruction": (
                "Open the Google Auth Platform Audience page, confirm the requested work Google account is allowed there, "
                "add it if missing, save, then retry the Full Workspace auth link."
            ),
            "next_action": "add_google_oauth_test_user_and_retry_full_workspace_auth",
            "next_action_href": GOOGLE_REAUTH_ACTION_HREF,
            "next_action_label": "Open Google setup",
            "next_action_method": "get",
            "missing_setup": ["oauth_test_user_confirmation_pending"],
            "setup_checklist": [
                {
                    "key": "oauth_test_user_confirmation_pending",
                    "label": "Confirm the work Google account is allowed in OAuth Audience",
                    "how": "Open the Audience page, confirm the requested account is listed there or add it if missing, save, then retry the auth link.",
                }
            ],
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=openclaw-concierge",
            "auth_link_template": (
                "https://myexternalbrain.com/app/actions/google/connect?"
                "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&"
                "expected_google_email=%3Credacted-email%3E"
            ),
            "scope_bundle": "full_workspace",
            "expected_google_email_present": True,
            "expected_google_email_sha256": "expected-google-email-hash",
            "expected_google_domain": "gmail.com",
            "observed_google_email_present": False,
            "observed_google_email_sha256": "",
            "observed_google_domain": "",
            "observed_google_account_matches_expected": False,
            "telegram_message": (
                "Action needed: Google Full Workspace auth still needs a manual Audience-page check. "
                "Open Google Auth Platform, confirm the requested work account is allowed there, add it if missing, save, then retry the auth link."
            ),
            "delivery_policy": "action_required_only",
            "telegram_push_allowed": True,
            "interruption_budget": "action_required",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "raw_private_context_exposed": False,
            "raw_expected_google_email_exposed": False,
            "raw_observed_google_email_exposed": False,
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_error_description_exposed": False,
        },
    )

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-07-05T15:00:00Z",
    )

    assert "detect:google_workspace_oauth=ready_manual_console_check" in receipt["blocking_reasons"]
    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    google_requirement = proof_requirements["google_workspace_oauth_setup"]
    assert google_requirement["action_context"]["user_action_required"] is True
    assert google_requirement["action_context"]["missing_setup"] == ["oauth_test_user_confirmation_pending"]
    google_queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "google_workspace_oauth_setup")
    assert google_queue_row["user_action_required"] is True
    assert google_queue_row["delivery_policy"] == "action_required_only"
    assert google_queue_row["telegram_push_allowed"] is True
    assert google_queue_row["operator_stream"] == "office_setup"


def test_pending_quality_acceptance_keys_become_action_required_queue_items(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_acceptance_receipt_with_pending_quality_keys(tmp_path)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-06-22T15:00:00Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    expected = {
        "ea_real_commitment_recovered_or_closed": "real_commitment_recovered_or_closed",
        "ea_real_approved_action_audited": "real_approved_action_audited",
        "ea_real_provider_failure_recovered": "real_provider_failure_recovered",
    }
    for proof_key, acceptance_key in expected.items():
        requirement = proof_requirements[proof_key]
        assert requirement["status"] == "pending_real_world_evidence"
        assert requirement["next_action_href"] == "/admin/actions/acceptance-evidence"
        assert requirement["next_action_method"] == "post"
        assert (
            requirement["next_action_form_href"]
            == f"/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key={acceptance_key}"
        )
        assert requirement["next_action_form_method"] == "get"
        context = requirement["action_context"]
        assert context["kind"] == "real_world_acceptance_capture"
        assert context["proof_key"] == acceptance_key
        assert (
            context["next_action_form_href"]
            == f"/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key={acceptance_key}"
        )
        assert context["user_action_required"] is True
        assert context["delivery_policy"] == "action_required_only"
        assert context["telegram_push_allowed"] is True
        assert context["interruption_budget"] == "action_required"
        assert context["raw_acceptance_text_exposed"] is False
        assert context["raw_actor_identity_exposed"] is False
        assert context["raw_object_reference_exposed"] is False

    queue = {item["key"]: item for item in receipt["operator_action_queue"]}
    assert receipt["next_action_key"] == "ea_real_commitment_recovered_or_closed"
    assert receipt["next_action"] == "record_redacted_real_commitment_recovery_evidence"
    assert receipt["operator_action_queue"][0]["key"] == "ea_real_commitment_recovered_or_closed"
    for proof_key, acceptance_key in expected.items():
        assert proof_key in queue
        assert queue[proof_key]["proof_key"] == acceptance_key
        assert (
            queue[proof_key]["next_action_form_href"]
            == f"/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key={acceptance_key}"
        )
        assert queue[proof_key]["user_action_required"] is True
        assert queue[proof_key]["delivery_policy"] == "action_required_only"
        assert queue[proof_key]["telegram_push_allowed"] is True
    assert verify(output, root=tmp_path) == []


def test_mymedia_action_context_adds_public_console_repair_checklist_when_surface_is_broken() -> None:
    context = posture_module._mymedia_alexa_action_context(
        {
            "ready": False,
            "reason": "mymedia_library_scan_pending",
            "next_action": "wait_for_mymedia_library_scan",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/tables",
            "next_action_label": "Open Watch Folders",
            "next_action_method": "get",
            "echo_playback_claim_allowed": False,
            "operator_action": {
                "user_action_required": True,
                "delivery_policy": "action_required_only",
                "interruption_budget": "action_required",
                "telegram_delivery_ready": False,
            },
            "pairing_telegram_delivery": {
                "delivery_reason": "no_operator_action_required",
                "delivery_transport": "telegram_bot",
                "telegram_delivery": {
                    "reason": "no_operator_action_required",
                    "delivery_transport": "telegram_bot",
                },
            },
            "probe": {
                "public_surface_configured": True,
                "public_surface_ready": False,
                "public_surface_status": "blocked_by_cloudflare",
                "public_surface_reason": "mymedia_public_console_blocked_by_cloudflare",
            },
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        }
    )

    assert context["missing_setup"] == [
        "mymedia_library_scan_pending",
        "mymedia_public_console_blocked_by_cloudflare",
    ]
    assert {
        "key": "repair_mymedia_public_console_route",
        "label": "Repair My Media public console route",
        "how": "make repair-mymedia-public-surface",
    } in context["setup_checklist"]
    assert context["public_console_surface_ready"] is False
    assert context["public_console_surface_status"] == "blocked_by_cloudflare"


def test_build_goal_posture_emits_required_lenses_and_conservative_claims(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
        operator_action_packet={
            "status": "action_required",
            "user_action_required": True,
            "action_required_reason": "real_world_acceptance_missing",
            "next_action": "record_redacted_signal_review_acceptance",
            "next_action_href": "/admin/actions/signal-to-decision-evidence",
            "next_action_label": "Record a signal-loop outcome",
            "next_action_method": "post",
            "next_action_form_href": (
                "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review"
            ),
            "next_action_form_label": "Record a signal-loop outcome",
            "next_action_form_method": "get",
            "next_action_evidence_part": "review",
            "instruction": "Record redacted evidence that the weekly signal-to-decision review was actually reviewed.",
            "required_next_receipt": "real weekly signal-to-decision review accepted by the operator",
            "required_form_fields": ["evidence_part", "source_kind", "evidence", "packet_ref"],
            "accepted_parts": {"review": False, "followthrough": False},
            "delivery_policy": "action_required_only",
            "telegram_push_allowed": True,
            "interruption_budget": "action_required",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "claim_boundary": (
                "does_not_prove_closed_signal_to_decision_loop_until_review_and_followthrough_are_accepted"
            ),
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "raw_private_context_exposed": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
        next_action="capture a consented real STT fixture",
        current_label="Memorial public-origin gold: blocked",
        room_audio_attestation={
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "required_check_ids": [
                "actual_device_checked",
                "actual_speaker_checked",
                "normal_spoken_turn_confirmed",
            ],
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
        summary="Teable recovery command surface is mirrored and documented locally; a seeded fresh-host drill receipt is still required before any pass claim.",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/pocket_audio_archive_receipt.generated.json",
        status="pass",
        transcript_ingest_ready=True,
        evidence_mode="filesystem_archive_scan",
        next_action="maintain_pocket_ai_audio_transcript_archive",
        archive_files={
            "audio_file_total": 2,
            "metadata_json_total": 2,
            "raw_archive_root_exposed": False,
        },
        database_index={"latest_non_dismissed_missing_transcript_total": 0},
        privacy={
            "raw_transcript_text_exposed": False,
            "raw_archive_root_exposed": False,
            "raw_credential_exposed": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_business_signal_readiness.generated.json",
        status="blocked_setup_required",
        business_mode=True,
        webhook_path="/v1/channels/telegram/business/ingest",
        allowed_updates=[
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
        ],
        missing_setup=["chat_allowlist_configured"],
        bot_registry={
            "token_present": True,
            "ingest_secret_present": True,
            "default_principal_present": True,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_principal_id_exposed": False,
        },
        chat_allowlist={
            "configured": False,
            "raw_chat_ids_exposed": False,
            "raw_chat_hashes_exposed": False,
        },
        privacy={
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_webhook_url_exposed": False,
            "raw_payload_exposed": False,
        },
        operator_action={
            "user_action_required": True,
            "instruction": "Connect the EA bot as Telegram Business/Secretary bot, allow only selected chats, configure the Business webhook, and set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES.",
            "missing_setup": ["chat_allowlist_configured"],
            "setup_checklist": [
                {
                    "key": "chat_allowlist_configured",
                    "label": "Choose Telegram Business chats EA may read",
                    "how": "Set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS.",
                }
            ],
            "telegram_message": "Action needed: Telegram Business/Secretary ingest is not live yet. Missing: Choose Telegram Business chats EA may read.",
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
        status="ready_retry_required",
        scope_bundle="full_workspace",
        console_deep_link="https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
        auth_link_template=(
            "https://myexternalbrain.com/app/actions/google/connect?"
            "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&"
            "expected_google_email=%3Credacted-email%3E"
        ),
        missing_setup=["oauth_access_retry_or_account_selection_required"],
        privacy={
            "raw_expected_google_email_exposed": False,
            "raw_observed_google_email_exposed": False,
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_state_secret_exposed": False,
            "raw_provider_secret_exposed": False,
            "raw_google_code_exposed": False,
            "raw_access_token_exposed": False,
            "raw_refresh_token_exposed": False,
            "raw_gcloud_token_exposed": False,
            "raw_gcloud_account_exposed": False,
            "raw_error_description_exposed": False,
        },
        operator_action={
            "user_action_required": True,
            "instruction": (
                "Retry the Full Workspace auth link and explicitly choose the approved work Google account."
            ),
            "next_action": "retry_full_workspace_auth_with_approved_account",
            "next_action_href": GOOGLE_REAUTH_ACTION_HREF,
            "next_action_label": "Retry Google auth",
            "next_action_method": "get",
            "missing_setup": ["oauth_access_retry_or_account_selection_required"],
            "setup_checklist": [
                {
                    "key": "oauth_access_retry_or_account_selection_required",
                    "label": "Retry Full Workspace auth with the approved Google account",
                    "how": "Open the redacted auth link, choose the approved work account, and finish consent.",
                }
            ],
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "auth_link_template": (
                "https://myexternalbrain.com/app/actions/google/connect?"
                "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&"
                "expected_google_email=%3Credacted-email%3E"
            ),
            "scope_bundle": "full_workspace",
            "expected_google_email_present": True,
            "expected_google_email_sha256": "expected-google-email-hash",
            "expected_google_domain": "gmail.com",
            "observed_google_email_present": True,
            "observed_google_email_sha256": "observed-google-email-hash",
            "observed_google_domain": "gmail.com",
            "observed_google_account_matches_expected": True,
            "telegram_message": "Action needed: Google Full Workspace auth is still denied even though the work account is already approved.",
            "delivery_policy": "action_required_only",
            "telegram_push_allowed": True,
            "interruption_budget": "action_required",
            "raw_private_context_exposed": False,
            "raw_expected_google_email_exposed": False,
            "raw_observed_google_email_exposed": False,
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_error_description_exposed": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json",
        status="blocked_setup_required",
        provider="pushbullet",
        client_count=1,
        multi_client_expected=True,
        required_client_keys=["default", "elisabeth"],
        client_coverage={
            "multi_client_expected": True,
            "expected_client_count": 2,
            "configured_client_count": 1,
            "configured_required_client_count": 1,
            "token_present_required_client_count": 0,
            "missing_client_keys": ["default"],
            "missing_token_keys": ["elisabeth"],
            "multi_client_ready": False,
        },
        missing_setup=["pushbullet_client_missing:default", "pushbullet_token_missing:elisabeth"],
        account_settings_url="https://www.pushbullet.com/#settings/account",
        delivery_claim={
            "pushbullet_note_delivery_ready": False,
            "multi_client_delivery_ready": False,
            "live_token_account_verified": False,
            "irreversible_actions_consent_gated": True,
            "non_action_progress_push_allowed": False,
        },
        clients=[
            {
                "client_key": "elisabeth",
                "email_domain": "gmail.com",
                "email_present": True,
                "email_sha256": "email-hash",
                "token_env": "PB_TOKEN_ELISABETH",
                "token_present": False,
                "raw_email_exposed": False,
                "raw_token_exposed": False,
            }
        ],
        privacy={
            "raw_email_exposed": False,
            "raw_token_exposed": False,
            "raw_push_body_exposed": False,
            "raw_push_ids_exposed": False,
        },
        operator_action={
            "user_action_required": True,
            "missing_setup": ["pushbullet_client_missing:default", "pushbullet_token_missing:elisabeth"],
            "required_client_keys": ["default", "elisabeth"],
            "client_coverage": {
                "multi_client_expected": True,
                "expected_client_count": 2,
                "configured_client_count": 1,
                "configured_required_client_count": 1,
                "token_present_required_client_count": 0,
                "missing_client_keys": ["default"],
                "missing_token_keys": ["elisabeth"],
                "multi_client_ready": False,
            },
            "delivery_policy": "action_required_only",
            "telegram_push_allowed": True,
            "interruption_budget": "action_required",
            "next_action": "create_missing_pushbullet_access_tokens",
            "next_action_label": "Open Pushbullet account settings",
            "next_action_href": "https://www.pushbullet.com/#settings/account",
            "next_action_method": "get",
            "setup_checklist": [
                {
                    "key": "configure_pushbullet_clients",
                    "label": "Configure every expected Pushbullet client",
                    "how": "Keep the original/default Pushbullet client configured and add the Elisabeth client.",
                },
                {
                    "key": "create_pushbullet_access_token",
                    "label": "Create a Pushbullet access token for each missing token",
                    "how": "Open Pushbullet Account Settings, create an access token, store it in the listed token env var, then rerun this readiness receipt.",
                }
            ],
            "raw_email_exposed": False,
            "raw_token_exposed": False,
            "raw_private_context_exposed": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="blocked_pairing_required",
        ready=False,
        probe_ok=True,
        reason="amazon_account_not_paired",
        next_action="enter_mymedia_amazon_pairing_code",
        next_action_href="http://127.0.0.1:52051/index.html#!/setup",
        next_action_label="Open My Media setup",
        next_action_method="get",
        pairing_resume_ready=True,
        pairing_resume_command="make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
        echo_playback_claim_allowed=False,
        operator_action={
            "user_action_required": True,
            "delivery_policy": "action_required_only",
            "interruption_budget": "action_required",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "pairing_resume_ready": True,
            "pairing_resume_command": "make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
            "telegram_delivery_ready": True,
            "raw_private_context_exposed": False,
        },
        pairing_telegram_delivery={
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "delivery_transport": "telegram_bot",
            "delivery_reason": "dry_run",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "telegram_delivery": {
                "ready": True,
                "readiness_status": "ready",
                "readiness_reason": "",
                "reason": "dry_run",
                "delivery_transport": "telegram_bot",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
            },
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
        probe={
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "pairing_resume_ready": True,
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="choose_sent_replacement_voice_sample",
        operator_action_packet={
            "user_action_required": True,
            "instruction": "Choose one sent replacement voice sample in Telegram.",
            "sent_samples_cover_expected": True,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        duplicate_suppression={
            "action_required_only": True,
            "only_current_jobs_can_require_user_action": True,
            "superseded_duplicate_candidate_count": 3,
            "suppressed_pending_voice_duplicate_count": 1,
            "active_pending_voice_job_count": 1,
            "duplicate_active_pending_source_key_count": 0,
            "duplicate_active_pending_source_keys_sha256": [],
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        pending_user_selected_voice_jobs=[
            {
                "replacement_candidate_count": 1,
                "replacement_candidate_labels": ["Dieter"],
                "author_gender_signal": "male",
                "author_gender_match_count": 1,
                "author_gender_mismatch_count": 0,
                "author_gender_matched_candidates_only": True,
                "voice_sample_delivery_status": "sent",
                "voice_sample_delivery_sent_count": 1,
                "voice_sample_delivery_expected_count": 1,
                "raw_voice_ids_exposed": False,
                "callback_tokens_exposed": False,
            }
        ],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="waiting",
    )
    _write_proactive_ooda_receipts(tmp_path)
    _write_operator_readiness_receipt(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-22T15:00:00Z",
    )

    assert receipt["contract_name"] == "ea.continuous_improvement_goal_posture.v1"
    assert receipt["execution_lenses"] == ["detect", "decide", "deliver", "recover", "prove"]
    assert receipt["overall_status"] == "blocked_real_world_acceptance"
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["real_use_claim_allowed"] is False
    assert "paid-human-assistant-grade proactive OODA" in receipt["goal_shorthand"]
    assert "transcript-aware ingest" in receipt["goal_shorthand"]
    assert "auditor-passed decision-ready packets" in receipt["goal_shorthand"]
    assert "Teable-mirrored current/stale state" in receipt["goal_shorthand"]
    assert "cost-aware 1min.ai-first background routing" in receipt["goal_shorthand"]
    assert "Gemini/Vertex token telemetry" in receipt["goal_shorthand"]
    assert "real proactive OODA packet accepted with action-required-only routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome" in receipt["required_next_receipts"]
    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    assert set(proof_requirements) == {
        "morning_brief_operator_acceptance",
        "weekly_signal_to_decision_review_acceptance",
        "proactive_ooda_packet_acceptance",
        "fresh_host_teable_recovery_drill",
        "telegram_business_signal_setup",
        "google_workspace_oauth_setup",
        "pushbullet_delivery_setup",
        "mymedia_alexa_setup",
        "manfred_stt_tts_realtime_conversation",
        "telegram_audiobook_live_delivery",
        "whatsapp_audiobook_live_delivery",
    }
    assert {item["required_next_receipt"] for item in proof_requirements.values()} == set(receipt["required_next_receipts"])
    assert proof_requirements["proactive_ooda_packet_acceptance"]["evidence_kind"] == "approval_outcome"
    assert (
        proof_requirements["proactive_ooda_packet_acceptance"]["next_action"]
        == "stage_fresh_assistant_grade_proactive_packet"
    )
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_href"] == "/app/queue"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_label"] == "Open queue"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_method"] == "get"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_form_href"] == "/app/queue"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_form_method"] == "get"
    assert proof_requirements["morning_brief_operator_acceptance"]["next_action_href"] == "/admin/actions/acceptance-evidence"
    assert proof_requirements["morning_brief_operator_acceptance"]["next_action_method"] == "post"
    assert (
        proof_requirements["morning_brief_operator_acceptance"]["next_action_form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert proof_requirements["morning_brief_operator_acceptance"]["next_action_form_method"] == "get"
    morning_context = proof_requirements["morning_brief_operator_acceptance"]["action_context"]
    assert morning_context["kind"] == "real_world_acceptance_capture"
    assert morning_context["proof_key"] == "real_daily_morning_brief_accepted"
    assert morning_context["user_action_required"] is True
    assert morning_context["delivery_policy"] == "action_required_only"
    assert morning_context["telegram_push_allowed"] is True
    assert morning_context["non_action_progress_push_allowed"] is False
    assert morning_context["raw_acceptance_text_exposed"] is False
    assert morning_context["raw_actor_identity_exposed"] is False
    assert morning_context["raw_object_reference_exposed"] is False
    assert proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_href"] == "/admin/actions/signal-to-decision-evidence"
    assert proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_label"] == "Record a signal-loop outcome"
    assert proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_method"] == "post"
    assert (
        proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_form_href"]
        == "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review"
    )
    assert proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_form_method"] == "get"
    weekly_context = proof_requirements["weekly_signal_to_decision_review_acceptance"]["action_context"]
    assert weekly_context["kind"] == "real_world_acceptance_capture"
    assert weekly_context["evidence_part"] == "review"
    assert weekly_context["source_action_packet_present"] is True
    assert weekly_context["source_action_packet_status"] == "action_required"
    assert weekly_context["action_required_reason"] == "real_world_acceptance_missing"
    assert weekly_context["required_form_fields"] == ["evidence_part", "source_kind", "evidence", "packet_ref"]
    assert weekly_context["accepted_parts"] == {"review": False, "followthrough": False}
    assert weekly_context["user_action_required"] is True
    assert weekly_context["delivery_policy"] == "action_required_only"
    assert weekly_context["telegram_push_allowed"] is False
    assert weekly_context["notification_policy"] == "queue_only_proof"
    assert weekly_context["non_action_progress_push_allowed"] is False
    assert any(
        "ea_proactive_ooda_gold_acceptance.generated.json" in surface
        for surface in proof_requirements["proactive_ooda_packet_acceptance"]["capture_surfaces"]
    )
    assert proof_requirements["fresh_host_teable_recovery_drill"]["lens"] == "recover"
    assert proof_requirements["fresh_host_teable_recovery_drill"]["evidence_kind"] == "fresh_host_recovery_drill"
    assert proof_requirements["telegram_business_signal_setup"]["evidence_kind"] == "secretary_bot_signal_ingest_setup"
    telegram_business_context = proof_requirements["telegram_business_signal_setup"]["action_context"]
    assert telegram_business_context["user_action_required"] is True
    assert telegram_business_context["missing_setup"] == ["chat_allowlist_configured"]
    assert telegram_business_context["setup_checklist"] == [
        {
            "key": "chat_allowlist_configured",
            "label": "Choose Telegram Business chats EA may read",
            "how": "Set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS.",
        }
    ]
    assert "Action needed:" in telegram_business_context["telegram_message"]
    assert telegram_business_context["raw_chat_ids_exposed"] is False
    assert telegram_business_context["raw_token_exposed"] is False
    assert telegram_business_context["raw_secret_exposed"] is False
    assert proof_requirements["google_workspace_oauth_setup"]["evidence_kind"] == "google_workspace_oauth_test_user_setup"
    assert proof_requirements["google_workspace_oauth_setup"]["next_action"] == "retry_full_workspace_auth_with_approved_account"
    assert proof_requirements["google_workspace_oauth_setup"]["next_action_href"] == GOOGLE_REAUTH_ACTION_HREF
    assert proof_requirements["google_workspace_oauth_setup"]["next_action_label"] == "Retry Google auth"
    assert proof_requirements["google_workspace_oauth_setup"]["next_action_form_href"] == GOOGLE_REAUTH_ACTION_HREF
    assert proof_requirements["google_workspace_oauth_setup"]["next_action_form_method"] == "get"
    google_context = proof_requirements["google_workspace_oauth_setup"]["action_context"]
    assert google_context["user_action_required"] is True
    assert google_context["missing_setup"] == ["oauth_access_retry_or_account_selection_required"]
    assert google_context["setup_checklist"][0]["key"] == "oauth_access_retry_or_account_selection_required"
    assert google_context["observed_google_email_present"] is True
    assert google_context["observed_google_account_matches_expected"] is True
    assert google_context["raw_expected_google_email_exposed"] is False
    assert google_context["raw_observed_google_email_exposed"] is False
    assert google_context["raw_client_id_exposed"] is False
    assert google_context["raw_client_secret_exposed"] is False
    assert proof_requirements["pushbullet_delivery_setup"]["evidence_kind"] == "delivery_channel_setup"
    pushbullet_context = proof_requirements["pushbullet_delivery_setup"]["action_context"]
    assert pushbullet_context["kind"] == "pushbullet_delivery_setup"
    assert pushbullet_context["user_action_required"] is True
    assert pushbullet_context["missing_setup"] == [
        "pushbullet_client_missing:default",
        "pushbullet_token_missing:elisabeth",
    ]
    assert pushbullet_context["required_client_keys"] == ["default", "elisabeth"]
    assert pushbullet_context["missing_client_keys"] == ["default"]
    assert pushbullet_context["token_missing_client_keys"] == ["elisabeth"]
    assert pushbullet_context["multi_client_expected"] is True
    assert pushbullet_context["pushbullet_token_envs"] == ["PB_TOKEN_ELISABETH", "PB_TOKEN"]
    assert pushbullet_context["pushbullet_missing_token_envs"] == ["PB_TOKEN_ELISABETH"]
    assert "PB_TOKEN_ELISABETH" in pushbullet_context["telegram_message"]
    assert pushbullet_context["multi_client_delivery_ready"] is False
    assert pushbullet_context["external_setup_url"] == "https://www.pushbullet.com/#settings/account"
    assert pushbullet_context["raw_email_exposed"] is False
    assert pushbullet_context["raw_token_exposed"] is False
    assert proof_requirements["mymedia_alexa_setup"]["evidence_kind"] == "delivery_channel_setup"
    assert proof_requirements["mymedia_alexa_setup"]["next_action"] == "enter_mymedia_amazon_pairing_code"
    assert proof_requirements["mymedia_alexa_setup"]["next_action_href"] == "http://127.0.0.1:52051/index.html#!/setup"
    assert proof_requirements["mymedia_alexa_setup"]["next_action_label"] == "Open My Media setup"
    mymedia_context = proof_requirements["mymedia_alexa_setup"]["action_context"]
    assert mymedia_context["kind"] == "mymedia_alexa_setup"
    assert mymedia_context["user_action_required"] is True
    assert mymedia_context["missing_setup"] == ["amazon_account_not_paired"]
    assert mymedia_context["pairing_resume_ready"] is True
    assert mymedia_context["pairing_resume_command"] == "make submit-mymedia-amazon-pairing-code OTP_CODE=123456"
    assert mymedia_context["echo_playback_claim_allowed"] is False
    assert mymedia_context["telegram_delivery_ready"] is True
    assert mymedia_context["telegram_delivery_transport"] == "telegram_bot"
    assert mymedia_context.get("telegram_delivery_reason", "") == ""
    assert mymedia_context["external_setup_url"] == "http://127.0.0.1:52051/index.html#!/setup"
    assert mymedia_context["raw_refresh_token_exposed"] is False
    assert mymedia_context["raw_paired_user_exposed"] is False
    assert mymedia_context["raw_watch_folder_paths_exposed"] is False
    assert mymedia_context["raw_public_ip_exposed"] is False
    assert mymedia_context["raw_pairing_resume_url_exposed"] is False
    assert proof_requirements["telegram_audiobook_live_delivery"]["evidence_kind"] == "live_delivery_receipt"
    assert (
        proof_requirements["telegram_audiobook_live_delivery"]["next_action"]
        == "choose_sent_replacement_voice_sample"
    )
    assert proof_requirements["telegram_audiobook_live_delivery"]["next_action_href"] == "/integrations/telegram"
    assert proof_requirements["telegram_audiobook_live_delivery"]["next_action_method"] == "get"
    manfred_context = proof_requirements["manfred_stt_tts_realtime_conversation"]["action_context"]
    assert manfred_context["kind"] == "manual_room_audio_attestation"
    assert manfred_context["user_action_required"] is True
    assert manfred_context["delivery_policy"] == "action_required_only"
    assert manfred_context["telegram_push_allowed"] is True
    assert manfred_context["manual_only"] is True
    assert manfred_context["ci_must_not_auto_assert"] is True
    assert manfred_context["required_check_count"] == 3
    assert manfred_context["required_check_ids"] == [
        "actual_device_checked",
        "actual_speaker_checked",
        "normal_spoken_turn_confirmed",
    ]
    assert manfred_context["raw_transcript_fields_exposed"] is False
    assert manfred_context["candidate_raw_text_fields_exposed"] is False
    telegram_action_context = proof_requirements["telegram_audiobook_live_delivery"]["action_context"]
    assert telegram_action_context["kind"] == "telegram_audiobook_voice_choice"
    assert telegram_action_context["operator_action"] == "choose_sent_replacement_voice_sample"
    assert telegram_action_context["user_action_required"] is True
    assert telegram_action_context["instruction"] == "Choose one sent replacement voice sample in Telegram."
    assert telegram_action_context["sent_samples_cover_expected"] is True
    assert telegram_action_context["candidate_labels"] == ["Dieter"]
    assert telegram_action_context["candidate_label_count"] == 1
    assert telegram_action_context["distinct_candidate_label_count"] == 1
    assert telegram_action_context["candidate_labels_distinct"] is True
    assert telegram_action_context["author_gender_signal"] == "male"
    assert telegram_action_context["author_gender_match_count"] == 1
    assert telegram_action_context["author_gender_mismatch_count"] == 0
    assert telegram_action_context["author_gender_matched_candidates_only"] is True
    assert telegram_action_context["voice_sample_delivery_status"] == "sent"
    assert telegram_action_context["raw_voice_ids_exposed"] is False
    assert telegram_action_context["callback_tokens_exposed"] is False
    queue_streams = {item["key"]: item["operator_stream"] for item in receipt["operator_action_queue"]}
    assert queue_streams["proactive_ooda_packet_acceptance"] == "office_loop"
    assert queue_streams["google_workspace_oauth_setup"] == "office_setup"
    assert queue_streams["pushbullet_delivery_setup"] == "office_setup"
    assert queue_streams["mymedia_alexa_setup"] == "media_memorial"
    assert queue_streams["telegram_audiobook_live_delivery"] == "media_memorial"
    duplicate_suppression = telegram_action_context["duplicate_suppression"]
    assert duplicate_suppression["action_required_only"] is True
    assert duplicate_suppression["only_current_jobs_can_require_user_action"] is True
    assert duplicate_suppression["active_pending_voice_job_count"] == 1
    assert duplicate_suppression["duplicate_active_pending_source_key_count"] == 0
    assert duplicate_suppression["raw_voice_ids_exposed"] is False
    assert duplicate_suppression["callback_tokens_exposed"] is False
    assert receipt["next_action_key"] == "morning_brief_operator_acceptance"
    assert receipt["next_action"] == "record_redacted_operator_acceptance_for_real_morning_brief"
    assert receipt["next_action_href"] == "/admin/actions/acceptance-evidence"
    assert receipt["next_action_label"] == "Record a real-use outcome"
    assert receipt["next_action_method"] == "post"
    assert (
        receipt["next_action_form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert receipt["next_action_form_method"] == "get"
    assert receipt["next_action_instruction"] == "Record redacted real-world acceptance evidence for the morning brief."
    assert receipt["operator_action_queue"][0]["key"] == "morning_brief_operator_acceptance"
    assert receipt["operator_action_queue"][0]["user_action_required"] is True
    assert receipt["operator_action_queue"][0]["delivery_policy"] == "action_required_only"
    assert receipt["operator_action_queue"][0]["telegram_push_allowed"] is True
    assert receipt["operator_action_queue"][0]["interruption_budget"] == "action_required"
    assert receipt["operator_action_queue"][0]["quiet_hours_respected"] is True
    assert receipt["operator_action_queue"][0]["non_action_progress_push_allowed"] is False
    assert receipt["operator_action_queue"][0]["irreversible_actions_consent_gated"] is True
    assert receipt["operator_action_queue"][0]["raw_private_context_exposed"] is False
    telegram_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "telegram_audiobook_live_delivery"
    )
    assert telegram_action["candidate_labels"] == ["Dieter"]
    assert telegram_action["candidate_labels_distinct"] is True
    assert telegram_action["author_gender_signal"] == "male"
    assert telegram_action["author_gender_matched_candidates_only"] is True
    assert telegram_action["sent_samples_cover_expected"] is True
    assert telegram_action["duplicate_suppression"]["active_pending_voice_job_count"] == 1
    manfred_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "manfred_stt_tts_realtime_conversation"
    )
    assert manfred_action["user_action_required"] is True
    assert manfred_action["delivery_policy"] == "action_required_only"
    assert manfred_action["telegram_push_allowed"] is True
    assert manfred_action["manual_only"] is True
    assert manfred_action["ci_must_not_auto_assert"] is True
    assert manfred_action["required_check_count"] == 3
    assert manfred_action["raw_transcript_fields_exposed"] is False
    assert manfred_action["candidate_raw_text_fields_exposed"] is False
    morning_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "morning_brief_operator_acceptance"
    )
    assert morning_action["user_action_required"] is True
    assert morning_action["delivery_policy"] == "action_required_only"
    assert morning_action["telegram_push_allowed"] is True
    assert morning_action["interruption_budget"] == "action_required"
    assert morning_action["proof_key"] == "real_daily_morning_brief_accepted"
    assert (
        morning_action["next_action_form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert morning_action["raw_acceptance_text_exposed"] is False
    assert morning_action["raw_actor_identity_exposed"] is False
    assert morning_action["raw_object_reference_exposed"] is False
    weekly_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "weekly_signal_to_decision_review_acceptance"
    )
    assert weekly_action["user_action_required"] is True
    assert weekly_action["delivery_policy"] == "action_required_only"
    assert weekly_action["telegram_push_allowed"] is False
    assert weekly_action["action_digest_eligible"] is False
    assert weekly_action["default_action_digest_suppressed_reason"] == "telegram_push_not_allowed"
    assert weekly_action["notification_policy"] == "queue_only_proof"
    assert weekly_action["evidence_part"] == "review"
    assert weekly_action["next_action_label"] == "Record a signal-loop outcome"
    assert weekly_action["next_action_form_label"] == "Record a signal-loop outcome"
    assert weekly_action["source_action_packet_present"] is True
    assert weekly_action["source_action_packet_status"] == "action_required"
    assert weekly_action["action_required_reason"] == "real_world_acceptance_missing"
    assert "Action needed:" in weekly_action["telegram_message"]
    assert "weekly signal-to-decision packet" in weekly_action["telegram_message"]
    assert weekly_action["required_form_fields"] == ["evidence_part", "source_kind", "evidence", "packet_ref"]
    assert weekly_action["accepted_parts"] == {"review": False, "followthrough": False}
    assert (
        weekly_action["next_action_form_href"]
        == "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review"
    )
    assert weekly_action["non_action_progress_push_allowed"] is False
    telegram_business_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "telegram_business_signal_setup"
    )
    assert telegram_business_action["user_action_required"] is True
    assert telegram_business_action["delivery_policy"] == "action_required_only"
    assert telegram_business_action["telegram_push_allowed"] is True
    assert telegram_business_action["interruption_budget"] == "action_required"
    assert telegram_business_action["missing_setup"] == ["chat_allowlist_configured"]
    assert telegram_business_action["setup_checklist"] == [
        {
            "key": "chat_allowlist_configured",
            "label": "Choose Telegram Business chats EA may read",
            "how": "Set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS.",
        }
    ]
    assert "Action needed:" in telegram_business_action["telegram_message"]
    assert telegram_business_action["raw_private_context_exposed"] is False
    assert telegram_business_action["raw_chat_ids_exposed"] is False
    assert telegram_business_action["raw_token_exposed"] is False
    assert telegram_business_action["raw_secret_exposed"] is False
    google_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "google_workspace_oauth_setup"
    )
    assert google_action["user_action_required"] is True
    assert google_action["next_action"] == "retry_full_workspace_auth_with_approved_account"
    assert google_action["next_action_href"] == GOOGLE_REAUTH_ACTION_HREF
    assert google_action["next_action_label"] == "Retry Google auth"
    assert google_action["next_action_form_href"] == GOOGLE_REAUTH_ACTION_HREF
    assert google_action["next_action_form_method"] == "get"
    assert google_action["missing_setup"] == ["oauth_access_retry_or_account_selection_required"]
    assert google_action["observed_google_email_present"] is True
    assert google_action["observed_google_account_matches_expected"] is True
    assert google_action["raw_expected_google_email_exposed"] is False
    assert google_action["raw_observed_google_email_exposed"] is False
    assert google_action["raw_client_id_exposed"] is False
    assert google_action["raw_client_secret_exposed"] is False
    assert google_action["proactive_signal_allowed"] is True
    pushbullet_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "pushbullet_delivery_setup"
    )
    assert pushbullet_action["user_action_required"] is True
    assert pushbullet_action["delivery_policy"] == "action_required_only"
    assert pushbullet_action["telegram_push_allowed"] is True
    assert pushbullet_action["missing_setup"] == [
        "pushbullet_client_missing:default",
        "pushbullet_token_missing:elisabeth",
    ]
    assert pushbullet_action["required_client_keys"] == ["default", "elisabeth"]
    assert pushbullet_action["missing_client_keys"] == ["default"]
    assert pushbullet_action["token_missing_client_keys"] == ["elisabeth"]
    assert pushbullet_action["multi_client_expected"] is True
    assert pushbullet_action["pushbullet_token_envs"] == ["PB_TOKEN_ELISABETH", "PB_TOKEN"]
    assert pushbullet_action["pushbullet_missing_token_envs"] == ["PB_TOKEN_ELISABETH"]
    assert "PB_TOKEN_ELISABETH" in pushbullet_action["telegram_message"]
    assert pushbullet_action["multi_client_delivery_ready"] is False
    assert pushbullet_action["external_setup_url"] == "https://www.pushbullet.com/#settings/account"
    assert pushbullet_action["notification_policy"] == "default"
    assert pushbullet_action["raw_email_exposed"] is False
    assert pushbullet_action["raw_token_exposed"] is False
    assert pushbullet_action["proactive_signal_allowed"] is True
    mymedia_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "mymedia_alexa_setup"
    )
    assert mymedia_action["user_action_required"] is True
    assert mymedia_action["delivery_policy"] == "action_required_only"
    assert mymedia_action["telegram_push_allowed"] is True
    assert mymedia_action["next_action"] == "enter_mymedia_amazon_pairing_code"
    assert mymedia_action["next_action_href"] == "http://127.0.0.1:52051/index.html#!/setup"
    assert mymedia_action["next_action_form_href"] == "http://127.0.0.1:52051/index.html#!/setup"
    assert mymedia_action["missing_setup"] == ["amazon_account_not_paired"]
    assert mymedia_action["pairing_resume_ready"] is True
    assert mymedia_action["pairing_resume_command"] == "make submit-mymedia-amazon-pairing-code OTP_CODE=123456"
    assert mymedia_action["echo_playback_claim_allowed"] is False
    assert mymedia_action["telegram_delivery_ready"] is True
    assert mymedia_action["telegram_delivery_transport"] == "telegram_bot"
    assert mymedia_action.get("telegram_delivery_reason", "") == ""
    assert mymedia_action["raw_refresh_token_exposed"] is False
    assert mymedia_action["raw_paired_user_exposed"] is False
    assert mymedia_action["raw_watch_folder_paths_exposed"] is False
    assert mymedia_action["raw_public_ip_exposed"] is False
    assert mymedia_action["raw_pairing_resume_url_exposed"] is False
    operator_delivery_policy = receipt["operator_delivery_policy"]
    assert operator_delivery_policy["action_required_only"] is True
    assert operator_delivery_policy["non_action_progress_push_allowed"] is False
    assert operator_delivery_policy["quiet_hours_respected"] is True
    assert operator_delivery_policy["irreversible_actions_consent_gated"] is True
    assert operator_delivery_policy["default_action_digest_streams"] == ["office_loop", "office_setup", "recovery"]
    assert operator_delivery_policy["telegram_push_allowed_for_next_action"] is True
    assert operator_delivery_policy["next_action_digest_eligible"] is True
    assert operator_delivery_policy["next_action_requires_user"] is True
    assert operator_delivery_policy["next_action_delivery_policy"] == "action_required_only"
    assert operator_delivery_policy["default_action_digest_eligible_count"] == sum(
        1 for item in receipt["operator_action_queue"] if item["action_digest_eligible"] is True
    )
    assert operator_delivery_policy["default_action_digest_suppressed_count"] == sum(
        1
        for item in receipt["operator_action_queue"]
        if item["user_action_required"] is True and item["action_digest_eligible"] is not True
    )
    for row in receipt["operator_action_queue"][1:]:
        assert row["operator_stream"] in {"office_loop", "office_setup", "recovery", "media_memorial"}
        if row["user_action_required"]:
            assert row["delivery_policy"] == "action_required_only"
            assert row["interruption_budget"] == "action_required"
            if row["key"] == "weekly_signal_to_decision_review_acceptance":
                assert row["telegram_push_allowed"] is False
                assert row["action_digest_eligible"] is False
                assert row["proactive_signal_allowed"] is False
                assert row["default_action_digest_suppressed_reason"] == "telegram_push_not_allowed"
                continue
            assert row["telegram_push_allowed"] is True
            if row["operator_stream"] == "media_memorial":
                assert row["action_digest_eligible"] is False
                assert row["proactive_signal_allowed"] is False
                assert row["default_action_digest_suppressed_reason"] == "operator_stream_not_in_default_action_digest"
            else:
                assert row["action_digest_eligible"] is True
                assert row["proactive_signal_allowed"] is True
            continue
        assert row["delivery_policy"] == "queue_only"
        assert row["telegram_push_allowed"] is False
        assert row["proactive_signal_allowed"] is False
        assert row["interruption_budget"] == "none"
        assert row["quiet_hours_respected"] is True
        assert row["non_action_progress_push_allowed"] is False
        assert row["irreversible_actions_consent_gated"] is True
    goal_action_signals = goal_action_queue_signals(receipt, limit=1, public_base_url="https://ea.test")
    assert len(goal_action_signals) == 1
    assert goal_action_signals[0].payload["schema"] == "ea.proactive_ooda.goal_action_queue_signal.v1"
    assert goal_action_signals[0].source_ref.startswith("goal_action_queue:morning_brief_operator_acceptance:")
    assert {item["key"] for item in receipt["operator_action_queue"]} == {
        key for key, item in proof_requirements.items() if item["status"] != "satisfied"
    }
    assert "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something." in receipt["rules"]
    assert "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient." in receipt["rules"]
    assert "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved." in receipt["rules"]
    assert "Provider-cost governance is part of the goal: whenever a lane can route through the active 1min.ai manager it should prefer 1min.ai first, Gemini/Vertex usage must be token-tracked, and Gemini soft caps may remove it from background candidate lists without blocking explicit Gemini requests." in receipt["rules"]
    assert "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth." in receipt["rules"]

    lenses = {lens["key"]: lens for lens in receipt["lenses"]}
    assert lenses["detect"]["status"] == "ready_local_packet_pending_operator_acceptance"
    assert "Pocket/audio transcript ingest is pass" in lenses["detect"]["summary"]
    transcript_evidence = lenses["detect"]["transcript_ingest_evidence"]
    assert transcript_evidence["key"] == "pocket_ai_audio_transcripts"
    assert transcript_evidence["status"] == "pass"
    assert transcript_evidence["transcript_ingest_ready"] is True
    assert transcript_evidence["archive_audio_file_total"] == 2
    assert transcript_evidence["archive_metadata_json_total"] == 2
    assert transcript_evidence["missing_transcript_total"] == 0
    assert transcript_evidence["raw_transcript_text_exposed"] is False
    assert transcript_evidence["raw_archive_root_exposed"] is False
    assert transcript_evidence["raw_credential_exposed"] is False
    assert len(lenses["detect"]["source_receipts"]) == 5
    operator_readiness = lenses["detect"]["operator_readiness_aggregate"]
    assert operator_readiness["key"] == "ea_operator_readiness_aggregate"
    assert operator_readiness["status"] == "ready_with_actions"
    assert operator_readiness["ready"] is False
    assert operator_readiness["pairing_probe_mode"] == "passive"
    assert operator_readiness["component_count"] == 8
    assert operator_readiness["blocked_count"] == 3
    assert operator_readiness["probe_failed_count"] == 0
    assert operator_readiness["component_keys"] == [
        "telegram",
        "google_workspace_oauth",
        "pushbullet",
        "whatsapp",
        "teable_recovery",
        "mymedia_alexa",
        "proactive_route",
        "proactive_artifacts",
    ]
    assert operator_readiness["steering_component_keys"] == operator_readiness["component_keys"]
    assert operator_readiness["attention_component_keys"] == [
        "google_workspace_oauth",
        "pushbullet",
        "whatsapp",
        "mymedia_alexa",
    ]
    assert operator_readiness["supplemental_attention_count"] == 0
    assert operator_readiness["supplemental_blocked_count"] == 0
    assert operator_readiness["supplemental_probe_failed_count"] == 0
    assert operator_readiness["supplemental_attention_component_keys"] == []
    assert operator_readiness["supplemental_next_actions"] == []
    assert operator_readiness["next_action"] == "set_google_workspace_expected_email_and_refresh_receipt"
    assert operator_readiness["summary"].startswith("operator_readiness status=ready_with_actions")
    assert operator_readiness["raw_component_payload_exposed"] is False
    assert operator_readiness["raw_delivery_token_exposed"] is False
    assert operator_readiness["raw_qr_artifact_exposed"] is False
    assert operator_readiness["raw_chat_ref_exposed"] is False
    assert lenses["decide"]["status"] == "ready_local_evidence"
    provider_cost = lenses["decide"]["provider_cost_control"]
    assert provider_cost["status"] == "active_cost_control"
    assert provider_cost["primary_background_provider"] == "onemin"
    assert provider_cost["primary_background_provider_label"] == "1min.ai"
    assert provider_cost["default_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_cost["fast_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_cost["cheap_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_cost["groundwork_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_cost["hard_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert "groundwork" in provider_cost["cost_sensitive_lanes"]
    assert provider_cost["onemin_preferred_when_speed_is_not_critical"] is True
    assert provider_cost["onemin_preferred_whenever_usable"] is True
    assert provider_cost["gemini_provider_key"] == "gemini_vortex"
    assert provider_cost["gemini_token_tracking_required"] is True
    assert provider_cost["gemini_dispatch_ledger"] == "provider_dispatch_events.jsonl"
    assert (
        provider_cost["gemini_live_pressure_probe_command"]
        == "python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json"
    )
    assert provider_cost["gemini_live_pressure_probe_source"] == "runtime_container_exec:provider_ledger_cache"
    assert provider_cost["gemini_soft_cap_env"] == "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H"
    assert provider_cost["gemini_soft_cap_window_env"] == "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS"
    assert provider_cost["gemini_soft_cap_action"] == "remove_gemini_vortex_from_cost_gated_background_candidate_lists"
    assert provider_cost["explicit_gemini_requests_allowed"] is True
    assert provider_cost["billing_truth_boundary"] == "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
    assert provider_cost["raw_provider_secret_exposed"] is False
    assert provider_cost["raw_prompt_or_response_text_exposed"] is False
    assert provider_cost["raw_google_cloud_billing_account_exposed"] is False
    provider_pressure = lenses["decide"]["provider_cost_pressure"]
    assert provider_pressure["present"] is True
    assert provider_pressure["checked"] is True
    assert provider_pressure["status"] == "active_cost_control"
    assert provider_pressure["primary_background_provider"] == "onemin"
    assert provider_pressure["provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_pressure["fast_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_pressure["cheap_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_pressure["groundwork_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_pressure["hard_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_pressure["onemin_preferred_when_speed_is_not_critical"] is True
    assert provider_pressure["onemin_preferred_whenever_usable"] is True
    assert provider_pressure["onemin_usable"] is True
    assert provider_pressure["gemini_provider_key"] == "gemini_vortex"
    assert provider_pressure["gemini_billing_truth_boundary"] == (
        "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
    )
    assert provider_pressure["gemini_24h_total_tokens"] == 0
    assert provider_pressure["gemini_24h_soft_cap_tokens"] == 200000
    assert provider_pressure["gemini_background_cost_gate"] == "open"
    assert provider_pressure["explicit_gemini_requests_allowed"] is True
    assert provider_pressure["requires_recovery"] is False
    assert provider_pressure["raw_provider_secret_exposed"] is False
    assert provider_pressure["raw_prompt_or_response_text_exposed"] is False
    assert provider_pressure["raw_google_cloud_billing_account_exposed"] is False
    assert provider_pressure["raw_provider_slots_exposed"] is False
    assert lenses["deliver"]["status"] == "mixed_local_progress"
    assert lenses["recover"]["status"] == "ready_local_audit"
    assert "make probe-teable-recovery" in lenses["recover"]["verifier_commands"]
    assert lenses["prove"]["status"] == "blocked_real_world_acceptance"
    assert "proactive OODA shortlist" in lenses["detect"]["summary"]
    assert "proactive OODA packet loop" in lenses["decide"]["summary"]

    deliver_components = {component["key"]: component for component in lenses["deliver"]["components"]}
    assert deliver_components["promo_media"]["status"] == "ready_local_evidence"
    assert deliver_components["manfred_speech"]["status"] == "blocked_realtime_prerequisites"
    assert deliver_components["telegram_audiobook"]["status"] == "blocked"
    assert deliver_components["whatsapp_audiobook"]["status"] == "blocked"
    assert deliver_components["pushbullet_delivery"]["status"] == "blocked_setup_required"
    assert deliver_components["mymedia_alexa"]["status"] == "blocked_pairing_required"
    assert deliver_components["pushbullet_delivery"]["missing_setup"] == [
        "pushbullet_client_missing:default",
        "pushbullet_token_missing:elisabeth",
    ]
    assert deliver_components["pushbullet_delivery"]["raw_email_exposed"] is False
    assert deliver_components["pushbullet_delivery"]["raw_token_exposed"] is False
    assert deliver_components["mymedia_alexa"]["pairing_resume_ready"] is True
    assert deliver_components["mymedia_alexa"]["pairing_resume_command"] == "make submit-mymedia-amazon-pairing-code OTP_CODE=123456"
    assert deliver_components["mymedia_alexa"]["echo_playback_claim_allowed"] is False
    assert deliver_components["mymedia_alexa"]["telegram_delivery_ready"] is True
    assert deliver_components["mymedia_alexa"]["telegram_delivery_transport"] == "telegram_bot"
    assert deliver_components["mymedia_alexa"].get("telegram_delivery_reason", "") == ""
    assert deliver_components["mymedia_alexa"]["raw_refresh_token_exposed"] is False
    assert deliver_components["mymedia_alexa"]["raw_paired_user_exposed"] is False
    assert deliver_components["mymedia_alexa"]["raw_watch_folder_paths_exposed"] is False
    assert deliver_components["mymedia_alexa"]["raw_public_ip_exposed"] is False
    assert deliver_components["mymedia_alexa"]["raw_pairing_resume_url_exposed"] is False
    assert "deliver:manfred_speech=blocked_realtime_prerequisites" in receipt["blocking_reasons"]
    assert "deliver:telegram_audiobook=blocked" in receipt["blocking_reasons"]
    assert "deliver:whatsapp_audiobook=blocked" in receipt["blocking_reasons"]
    assert "deliver:pushbullet_delivery=blocked_setup_required" in receipt["blocking_reasons"]
    assert "deliver:mymedia_alexa=blocked_pairing_required" in receipt["blocking_reasons"]

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    assert verify(output, root=tmp_path) == []

    stale_google_action_receipt = json.loads(json.dumps(receipt))
    for requirement in stale_google_action_receipt["acceptance_proof_requirements"]:
        if requirement["key"] == "google_workspace_oauth_setup":
            requirement["next_action"] = "add_google_oauth_test_user_and_retry_full_workspace_auth"
    for queue_row in stale_google_action_receipt["operator_action_queue"]:
        if queue_row["key"] == "google_workspace_oauth_setup":
            queue_row["next_action"] = "add_google_oauth_test_user_and_retry_full_workspace_auth"
    output.write_text(json.dumps(stale_google_action_receipt, indent=2) + "\n", encoding="utf-8")
    issues = verify(output, root=tmp_path)
    assert "google_workspace_oauth_setup next_action must mirror OAuth readiness next_action" in issues
    assert "google_workspace_oauth_setup queue row next_action must mirror OAuth readiness next_action" in issues

    stale_operator_readiness_receipt = json.loads(json.dumps(receipt))
    detect_lens = next(lens for lens in stale_operator_readiness_receipt["lenses"] if lens["key"] == "detect")
    detect_lens["operator_readiness_aggregate"]["component_count"] = 99
    output.write_text(json.dumps(stale_operator_readiness_receipt, indent=2) + "\n", encoding="utf-8")
    issues = verify(output, root=tmp_path)
    assert "operator_readiness_aggregate component_count must mirror operator readiness receipt" in issues

    operator_readiness_path = tmp_path / ".codex-studio/published/ea_operator_readiness.generated.json"
    operator_readiness_payload = json.loads(operator_readiness_path.read_text(encoding="utf-8"))
    operator_readiness_payload["summary"] = (
        "operator_readiness status=ready_with_actions; ready=false; components=8; "
        "attention=4; blocked=3; probe_failed=0; observed_at=2026-07-05T16:00:00Z"
    )
    operator_readiness_path.write_text(json.dumps(operator_readiness_payload, indent=2) + "\n", encoding="utf-8")
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    assert verify(output, root=tmp_path) == []

    stale_mymedia_delivery_receipt = json.loads(json.dumps(receipt))
    for requirement in stale_mymedia_delivery_receipt["acceptance_proof_requirements"]:
        if requirement["key"] == "mymedia_alexa_setup":
            requirement["action_context"]["telegram_delivery_ready"] = False
            requirement["action_context"]["telegram_delivery_reason"] = ""
    for queue_row in stale_mymedia_delivery_receipt["operator_action_queue"]:
        if queue_row["key"] == "mymedia_alexa_setup":
            queue_row["telegram_delivery_ready"] = False
            queue_row["telegram_delivery_reason"] = ""
    output.write_text(json.dumps(stale_mymedia_delivery_receipt, indent=2) + "\n", encoding="utf-8")
    issues = verify(output, root=tmp_path)
    assert "mymedia_alexa_setup action_context telegram_delivery_ready must match deliver component" in issues
    assert "blocked mymedia_alexa_setup action_context must explain Telegram delivery repair" in issues
    assert "mymedia_alexa_setup queue row telegram_delivery_ready must match action_context" not in issues
    assert "mymedia_alexa_setup queue row must explain Telegram delivery repair" in issues

    receipt["acceptance_proof_requirements"] = [
        item
        for item in list(receipt["acceptance_proof_requirements"])
        if item["key"] != "telegram_audiobook_live_delivery"
    ]
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    assert (
        "active blocker deliver:telegram_audiobook must have acceptance proof requirement telegram_audiobook_live_delivery"
        in verify(output)
    )


def test_goal_posture_prefers_live_provider_cost_probe_when_operator_status_is_unchecked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_proactive_ooda_receipts(
        tmp_path,
        operator_extra={
            "provider_cost_pressure": {
                "checked": False,
                "probe_ok": False,
                "status": "not_checked",
                "source": "",
                "observed_at": "",
                "window": "",
                "primary_background_provider": "",
                "provider_order": [],
                "fast_provider_order": [],
                "cheap_provider_order": [],
                "groundwork_provider_order": [],
                "hard_provider_order": [],
                "cost_sensitive_lanes": [],
                "onemin_preferred_when_speed_is_not_critical": False,
                "onemin_preferred_whenever_usable": False,
                "onemin_usable": False,
                "onemin_ready_slots": 0,
                "onemin_configured_slots": 0,
                "gemini_provider_key": "gemini_vortex",
                "gemini_token_tracking": {
                    "24h": {},
                    "background_cost_gate": "",
                    "billing_truth_boundary": "",
                    "explicit_gemini_requests_allowed": False,
                    "selected_window": {},
                    "soft_cap_percent_24h": None,
                },
                "requires_recovery": False,
                "privacy": {
                    "raw_provider_secret_exposed": False,
                    "raw_prompt_or_response_text_exposed": False,
                    "raw_google_cloud_billing_account_exposed": False,
                    "raw_provider_slots_exposed": False,
                },
            }
        },
    )
    _write_acceptance_receipt_with_morning_brief_accepted(tmp_path)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        source_git_head="source-head",
        source_state_fingerprint="source-fingerprint",
        provider_cost_routing_posture=_office_provider_cost_routing_posture(),
    )

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-07-06T12:00:00Z",
        provider_cost_pressure_probe=_live_provider_cost_pressure_probe_payload,
    )

    provider_pressure = {lens["key"]: lens for lens in receipt["lenses"]}["decide"]["provider_cost_pressure"]
    assert provider_pressure["present"] is True
    assert provider_pressure["checked"] is True
    assert provider_pressure["status"] == "active_cost_control"
    assert provider_pressure["source"] == "runtime_container_exec:ea-api:provider_ledger_cache"
    assert provider_pressure["primary_background_provider"] == "onemin"
    assert provider_pressure["provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert provider_pressure["gemini_background_cost_gate"] == "open"
    assert provider_pressure["explicit_gemini_requests_allowed"] is True
    assert provider_pressure["gemini_billing_truth_boundary"] == (
        "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
    )


def test_build_goal_posture_uses_proactive_gold_surface_when_packet_quality_is_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="blocked_real_world_acceptance",
        accepted_keys=[],
        acceptance_capture_requirements=[],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        real_weekly_operator_review_accepted=True,
        closed_loop_followthrough_receipt_verified=True,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_scope_gap_audit.generated.json",
        status="pass",
        reviewed_against_current_product_spine=True,
        operator_review_accepted=True,
    )
    _write_receipt(tmp_path, ".codex-studio/published/teable_env_recovery_proof.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_business_signal_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="blocked_pairing_required",
        ready=False,
        probe_ok=True,
        reason="amazon_account_not_paired",
        next_action="enter_mymedia_amazon_pairing_code",
        next_action_href="http://127.0.0.1:52051/index.html#!/setup",
        next_action_label="Open My Media setup",
        next_action_method="get",
        pairing_resume_ready=True,
        pairing_resume_command="make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
        echo_playback_claim_allowed=False,
        operator_action={
            "user_action_required": True,
            "delivery_policy": "action_required_only",
            "interruption_budget": "action_required",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "pairing_resume_ready": True,
            "pairing_resume_command": "make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
            "telegram_delivery_ready": True,
            "raw_private_context_exposed": False,
        },
        pairing_telegram_delivery={
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "delivery_transport": "telegram_bot",
            "delivery_reason": "dry_run",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "telegram_delivery": {
                "ready": True,
                "readiness_status": "ready",
                "readiness_reason": "",
                "reason": "dry_run",
                "delivery_transport": "telegram_bot",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
            },
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
        probe={
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "pairing_resume_ready": True,
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/active_media_ltd_goal_bundle.generated.json", status="ready_local_evidence")
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="blocked_low_quality_packet_evidence",
        gold_remaining_external_proofs=[
            "assistant-grade source intent and candidate alignment for the proactive OODA packet",
            "redacted explicit approval outcome for the proactive OODA packet",
        ],
        gold_summary="The proactive OODA mechanics have evidence, but the selected packet is not assistant-grade enough to prove production readiness.",
        gold_next_action="stage_fresh_assistant_grade_proactive_packet",
        gold_next_action_href="/app/queue",
        gold_next_action_label="Open queue",
        gold_next_action_method="get",
    )
    _write_operator_readiness_receipt(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
        generated_at="2026-07-04T20:20:00Z",
    )

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["next_action"] == "stage_fresh_assistant_grade_proactive_packet"
    assert proactive["next_action_href"] == "/app/queue"
    assert proactive["next_action_label"] == "Open queue"
    assert proactive["next_action_method"] == "get"
    assert proactive["action_context"]["delivery_policy"] == "queue_only"
    assert proactive["action_context"]["telegram_push_allowed"] is False
    assert proactive["action_context"]["gold_status"] == "blocked_low_quality_packet_evidence"


def test_build_goal_posture_marks_live_proactive_approval_as_action_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="blocked_real_world_acceptance",
        accepted_keys=[],
        acceptance_capture_requirements=[],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        real_weekly_operator_review_accepted=True,
        closed_loop_followthrough_receipt_verified=True,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_scope_gap_audit.generated.json",
        status="pass",
        reviewed_against_current_product_spine=True,
        operator_review_accepted=True,
    )
    _write_receipt(tmp_path, ".codex-studio/published/teable_env_recovery_proof.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_business_signal_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="blocked_pairing_required",
        ready=False,
        probe_ok=True,
        reason="amazon_account_not_paired",
        next_action="enter_mymedia_amazon_pairing_code",
        next_action_href="http://127.0.0.1:52051/index.html#!/setup",
        next_action_label="Open My Media setup",
        next_action_method="get",
        pairing_resume_ready=True,
        pairing_resume_command="make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
        echo_playback_claim_allowed=False,
        operator_action={
            "user_action_required": True,
            "delivery_policy": "action_required_only",
            "interruption_budget": "action_required",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "pairing_resume_ready": True,
            "pairing_resume_command": "make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
            "telegram_delivery_ready": True,
            "raw_private_context_exposed": False,
        },
        pairing_telegram_delivery={
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "delivery_transport": "telegram_bot",
            "delivery_reason": "dry_run",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "telegram_delivery": {
                "ready": True,
                "readiness_status": "ready",
                "readiness_reason": "",
                "reason": "dry_run",
                "delivery_transport": "telegram_bot",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
            },
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
        probe={
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "pairing_resume_ready": True,
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/active_media_ltd_goal_bundle.generated.json", status="ready_local_evidence")
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="ready_for_approval_outcome_capture",
        gold_remaining_external_proofs=["redacted explicit approval outcome for the proactive OODA packet"],
        gold_summary=(
            "A proactive OODA packet has local gold-proof runtime evidence and a live Telegram approval "
            "capture surface; capture the redacted approval outcome next."
        ),
        gold_next_action="tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        gold_next_action_href="https://myexternalbrain.com/admin/proactive-ooda/approval",
        gold_next_action_label="Record packet verdict",
        gold_next_action_method="get",
        operator_approval_capture_surface={
            "ready": True,
            "telegram_approval_surface_ready": True,
            "manual_outcome_capture_ready": True,
            "current_packet_present": True,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expires_at": "2026-07-11T21:19:05Z",
            "selected_channel": "telegram",
        },
    )
    _write_operator_readiness_receipt(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-07-04T20:20:00Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert proactive["action_context"]["user_action_required"] is True
    assert proactive["action_context"]["delivery_policy"] == "action_required_only"
    assert proactive["action_context"]["telegram_push_allowed"] is False
    assert proactive["action_context"]["interruption_budget"] == "action_required"
    assert proactive["action_context"]["notification_policy"] == "exclusive_head"
    assert proactive["action_context"]["approval_capture_latest_expires_at"] == "2026-07-11T21:19:05Z"
    assert proactive["action_context"]["console_deep_link"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert "Action needed:" in proactive["action_context"]["telegram_message"]
    assert "2026-07-11T21:19:05Z" in proactive["action_context"]["telegram_message"]

    proactive_queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "proactive_ooda_packet_acceptance")
    assert receipt["next_action_key"] == "proactive_ooda_packet_acceptance"
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["operator_action_queue"][0]["key"] == "proactive_ooda_packet_acceptance"
    assert proactive_queue_row["operator_stream"] == "office_loop"
    assert proactive_queue_row["user_action_required"] is True
    assert proactive_queue_row["delivery_policy"] == "action_required_only"
    assert proactive_queue_row["telegram_push_allowed"] is False
    assert proactive_queue_row["interruption_budget"] == "action_required"
    assert proactive_queue_row["notification_policy"] == "exclusive_head"
    assert proactive_queue_row["console_deep_link"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert "Action needed:" in proactive_queue_row["telegram_message"]
    assert verify(output, root=tmp_path) == []


def test_build_goal_posture_marks_manual_proactive_approval_as_action_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="blocked_real_world_acceptance",
        accepted_keys=[],
        acceptance_capture_requirements=[],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        real_weekly_operator_review_accepted=True,
        closed_loop_followthrough_receipt_verified=True,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_scope_gap_audit.generated.json",
        status="pass",
        reviewed_against_current_product_spine=True,
        operator_review_accepted=True,
    )
    _write_receipt(tmp_path, ".codex-studio/published/teable_env_recovery_proof.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_business_signal_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="blocked_pairing_required",
        ready=False,
        probe_ok=True,
        reason="amazon_account_not_paired",
        next_action="enter_mymedia_amazon_pairing_code",
        next_action_href="http://127.0.0.1:52051/index.html#!/setup",
        next_action_label="Open My Media setup",
        next_action_method="get",
        pairing_resume_ready=True,
        pairing_resume_command="make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
        echo_playback_claim_allowed=False,
        operator_action={
            "user_action_required": True,
            "delivery_policy": "action_required_only",
            "interruption_budget": "action_required",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "pairing_resume_ready": True,
            "pairing_resume_command": "make submit-mymedia-amazon-pairing-code OTP_CODE=123456",
            "telegram_delivery_ready": True,
            "raw_private_context_exposed": False,
        },
        pairing_telegram_delivery={
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "delivery_transport": "telegram_bot",
            "delivery_reason": "dry_run",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "telegram_delivery": {
                "ready": True,
                "readiness_status": "ready",
                "readiness_reason": "",
                "reason": "dry_run",
                "delivery_transport": "telegram_bot",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
            },
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
        probe={
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "pairing_resume_ready": True,
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/active_media_ltd_goal_bundle.generated.json", status="ready_local_evidence")
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="ready_for_approval_outcome_capture",
        gold_remaining_external_proofs=["redacted explicit approval outcome for the proactive OODA packet"],
        gold_summary=(
            "A proactive OODA packet has local gold-proof runtime evidence and manual approval outcome capture is ready; "
            "capture the current redacted approval outcome next."
        ),
        gold_next_action="record_proactive_ooda_approval_outcome",
        gold_next_action_href="https://myexternalbrain.com/admin/proactive-ooda/approval",
        gold_next_action_label="Record packet verdict",
        gold_next_action_method="get",
        operator_approval_capture_surface={
            "ready": True,
            "telegram_approval_surface_ready": False,
            "manual_outcome_capture_ready": True,
            "current_packet_present": True,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expires_at": "2026-07-12T11:52:01Z",
            "selected_channel": "telegram",
        },
    )
    _write_operator_readiness_receipt(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-07-06T04:40:45Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["next_action"] == "record_proactive_ooda_approval_outcome"
    assert proactive["action_context"]["user_action_required"] is True
    assert proactive["action_context"]["delivery_policy"] == "action_required_only"
    assert proactive["action_context"]["telegram_push_allowed"] is False
    assert proactive["action_context"]["notification_policy"] == "exclusive_head"
    assert proactive["action_context"]["approval_capture_ready"] is True
    assert proactive["action_context"]["approval_capture_telegram_surface_ready"] is False
    assert proactive["action_context"]["approval_capture_manual_outcome_capture_ready"] is True
    assert proactive["action_context"]["console_deep_link"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert "Action needed:" in proactive["action_context"]["telegram_message"]

    proactive_queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "proactive_ooda_packet_acceptance")
    assert receipt["next_action_key"] == "proactive_ooda_packet_acceptance"
    assert receipt["next_action"] == "record_proactive_ooda_approval_outcome"
    assert receipt["operator_action_queue"][0]["key"] == "proactive_ooda_packet_acceptance"
    assert proactive_queue_row["user_action_required"] is True
    assert proactive_queue_row["delivery_policy"] == "action_required_only"
    assert proactive_queue_row["telegram_push_allowed"] is False
    assert proactive_queue_row["notification_policy"] == "exclusive_head"
    assert verify(output, root=tmp_path) == []


def test_build_goal_posture_keeps_proactive_approval_queue_only_when_runtime_marks_no_user_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="blocked_real_world_acceptance",
        accepted_keys=[],
        acceptance_capture_requirements=[],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        real_weekly_operator_review_accepted=True,
        closed_loop_followthrough_receipt_verified=True,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_scope_gap_audit.generated.json",
        status="pass",
        reviewed_against_current_product_spine=True,
        operator_review_accepted=True,
    )
    _write_receipt(tmp_path, ".codex-studio/published/teable_env_recovery_proof.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_business_signal_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="pass",
        ready=True,
        echo_playback_claim_allowed=False,
        operator_action={
            "telegram_delivery_ready": True,
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/active_media_ltd_goal_bundle.generated.json", status="ready_local_evidence")
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="ready_for_approval_outcome_capture",
        gold_remaining_external_proofs=["redacted explicit approval outcome for the proactive OODA packet"],
        gold_summary=(
            "A proactive OODA packet has local gold-proof runtime evidence, but the current packet no longer "
            "requires explicit user approval."
        ),
        gold_next_action="record_proactive_ooda_approval_outcome",
        gold_next_action_href="https://myexternalbrain.com/admin/proactive-ooda/approval",
        gold_next_action_label="Record packet verdict",
        gold_next_action_method="get",
        operator_approval_capture_surface={
            "ready": True,
            "telegram_approval_surface_ready": False,
            "manual_outcome_capture_ready": True,
            "current_packet_present": True,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expires_at": "2026-07-12T11:52:01Z",
            "current_packet_user_action_required": False,
            "selected_channel": "telegram",
        },
    )
    _write_operator_readiness_receipt(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-07-06T09:30:00Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["action_context"]["user_action_required"] is False
    assert proactive["action_context"]["approval_capture_current_packet_user_action_required"] is False
    assert proactive["action_context"]["delivery_policy"] == "queue_only"
    assert proactive["action_context"]["operator_queue_visible"] is False
    assert proactive["action_context"]["telegram_push_allowed"] is False
    assert proactive["action_context"]["notification_policy"] == "default"
    assert all(item["key"] != "proactive_ooda_packet_acceptance" for item in receipt["operator_action_queue"])
    assert receipt["next_action_key"] != "proactive_ooda_packet_acceptance"
    assert verify(output, root=tmp_path) == []


def test_build_goal_posture_hides_meta_only_proactive_approval_repair_without_live_surface(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="blocked_real_world_acceptance",
        accepted_keys=[],
        acceptance_capture_requirements=[],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        real_weekly_operator_review_accepted=True,
        closed_loop_followthrough_receipt_verified=True,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_scope_gap_audit.generated.json",
        status="pass",
        reviewed_against_current_product_spine=True,
        operator_review_accepted=True,
    )
    _write_receipt(tmp_path, ".codex-studio/published/teable_env_recovery_proof.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_business_signal_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="pass",
        ready=True,
        echo_playback_claim_allowed=False,
        operator_action={
            "telegram_delivery_ready": True,
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/active_media_ltd_goal_bundle.generated.json", status="ready_local_evidence")
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="blocked_missing_proactive_packet_evidence",
        gold_remaining_external_proofs=[
            "redacted approval-capture readiness for the proactive OODA packet",
            "redacted explicit approval outcome for the proactive OODA packet",
        ],
        gold_summary="Proactive OODA gold proof is still blocked because one or more packet-evidence links are missing.",
        gold_next_action="repair_proactive_approval_capture",
        gold_next_action_href="https://myexternalbrain.com/admin/goals",
        gold_next_action_label="Open goals",
        gold_next_action_method="get",
        operator_approval_capture_surface={
            "ready": False,
            "telegram_approval_surface_ready": False,
            "manual_outcome_capture_ready": False,
            "current_packet_present": True,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_user_action_required": False,
            "selected_channel": "telegram",
        },
    )
    _write_operator_readiness_receipt(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-07-06T09:40:00Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["next_action"] == "repair_proactive_approval_capture"
    assert proactive["next_action_href"] == "https://myexternalbrain.com/admin/goals"
    assert proactive["next_action_label"] == "Open goals"
    assert proactive["action_context"]["user_action_required"] is False
    assert proactive["action_context"]["delivery_policy"] == "queue_only"
    assert proactive["action_context"]["operator_queue_visible"] is False
    assert proactive["action_context"]["telegram_push_allowed"] is False
    assert proactive["action_context"]["console_deep_link"] == ""
    assert all(item["key"] != "proactive_ooda_packet_acceptance" for item in receipt["operator_action_queue"])
    assert receipt["next_action_key"] != "proactive_ooda_packet_acceptance"
    assert verify(output, root=tmp_path) == []


def test_goal_posture_verifier_accepts_queue_only_proactive_recovery_without_approval_form(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="blocked_real_world_acceptance",
        accepted_keys=[],
        acceptance_capture_requirements=[],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        real_weekly_operator_review_accepted=True,
        closed_loop_followthrough_receipt_verified=True,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_scope_gap_audit.generated.json",
        status="pass",
        reviewed_against_current_product_spine=True,
        operator_review_accepted=True,
    )
    _write_receipt(tmp_path, ".codex-studio/published/teable_env_recovery_proof.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_business_signal_readiness.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
        status="pass",
    )
    _write_receipt(tmp_path, ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="pass",
        ready=True,
        echo_playback_claim_allowed=False,
        operator_action={
            "telegram_delivery_ready": True,
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/active_media_ltd_goal_bundle.generated.json", status="ready_local_evidence")
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="blocked_operator_runtime_posture",
        gold_summary=(
            "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold cannot "
            "be claimed until approved source health is restored."
        ),
        gold_next_action="repair_proactive_operator_runtime_posture",
        gold_next_action_href="https://myexternalbrain.com/admin/goals",
        gold_next_action_label="Open goals",
        gold_next_action_method="get",
        operator_status_override="ready_with_recovery_action",
        operator_reason_override="source_health_google_workspace:google_oauth_invalid_grant",
        operator_summary_override=(
            "Proactive OODA route and packet runtime are available, but Google Workspace source health still "
            "needs operator recovery."
        ),
        operator_next_action_override="reauthorize_google_workspace_binding",
        operator_next_action_href_override=GOOGLE_REAUTH_ACTION_HREF,
        operator_next_action_label_override="Open Google setup",
        operator_next_action_method_override="get",
        operator_approval_capture_surface={
            "ready": False,
            "telegram_approval_surface_ready": False,
            "manual_outcome_capture_ready": False,
            "current_packet_present": True,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_user_action_required": False,
            "selected_channel": "telegram",
        },
        operator_extra={
            "source_health": {
                "present": True,
                "status": "recovery_required",
                "issue_count": 1,
                "operator_action_required": True,
                "user_action_required": False,
                "issues": [
                    {
                        "source_key": "google_workspace",
                        "status": "unhealthy",
                        "error_code": "google_oauth_invalid_grant",
                        "operator_action_required": True,
                        "user_action_required": False,
                    }
                ],
                "privacy": {
                    "raw_source_ref_exposed": False,
                    "raw_payload_exposed": False,
                    "raw_credential_exposed": False,
                    "source_refs_hashed": True,
                },
            },
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "delivery_route_error": "",
            "delivery_route_ready": True,
        },
    )
    _write_operator_readiness_receipt(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-07-06T09:45:00Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["next_action"] == "reauthorize_google_workspace_binding"
    assert proactive["next_action_href"] == GOOGLE_REAUTH_ACTION_HREF
    assert proactive["next_action_label"] == "Open Google setup"
    assert proactive["action_context"]["user_action_required"] is False
    assert proactive["next_action_form_href"] == GOOGLE_REAUTH_ACTION_HREF
    assert proactive["next_action_form_label"] == "Reconnect Google workspace"
    assert proactive["next_action_form_method"] == "get"

    proactive_queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "proactive_ooda_packet_acceptance")
    assert proactive_queue_row["user_action_required"] is False
    assert proactive_queue_row["next_action"] == "reauthorize_google_workspace_binding"
    assert proactive_queue_row["next_action_href"] == GOOGLE_REAUTH_ACTION_HREF
    assert proactive_queue_row["next_action_label"] == "Open Google setup"
    assert proactive_queue_row.get("next_action_form_href", "") == GOOGLE_REAUTH_ACTION_HREF
    assert proactive_queue_row.get("next_action_form_label", "") == "Reconnect Google workspace"
    assert proactive_queue_row.get("next_action_form_method", "") == "get"
    assert receipt["next_action_key"] != "proactive_ooda_packet_acceptance"
    assert verify(output, root=tmp_path) == []


def test_build_goal_posture_keeps_proactive_approval_as_action_required_during_background_google_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="blocked_real_world_acceptance",
        accepted_keys=[],
        acceptance_capture_requirements=[],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        real_weekly_operator_review_accepted=True,
        closed_loop_followthrough_receipt_verified=True,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_scope_gap_audit.generated.json",
        status="pass",
        reviewed_against_current_product_spine=True,
        operator_review_accepted=True,
    )
    _write_receipt(tmp_path, ".codex-studio/published/teable_env_recovery_proof.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_business_signal_readiness.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
        status="ready_retry_required",
        scope_bundle="full_workspace",
        console_deep_link="https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
        auth_link_template=(
            "https://myexternalbrain.com/app/actions/google/connect?"
            "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&"
            "expected_google_email=%3Credacted-email%3E"
        ),
        missing_setup=["oauth_access_retry_or_account_selection_required"],
        privacy={
            "raw_expected_google_email_exposed": False,
            "raw_observed_google_email_exposed": False,
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_state_secret_exposed": False,
            "raw_provider_secret_exposed": False,
            "raw_google_code_exposed": False,
            "raw_access_token_exposed": False,
            "raw_refresh_token_exposed": False,
            "raw_gcloud_token_exposed": False,
            "raw_gcloud_account_exposed": False,
            "raw_error_description_exposed": False,
        },
        ready=False,
        operator_action={
            "user_action_required": True,
            "instruction": "Retry the Full Workspace auth link and explicitly choose the approved work Google account.",
            "next_action": "retry_full_workspace_auth_with_approved_account",
            "next_action_href": GOOGLE_REAUTH_ACTION_HREF,
            "next_action_label": "Retry Google auth",
            "next_action_method": "get",
            "missing_setup": ["oauth_access_retry_or_account_selection_required"],
            "setup_checklist": [
                {
                    "key": "oauth_access_retry_or_account_selection_required",
                    "label": "Retry Full Workspace auth with the approved Google account",
                    "how": "Open the redacted auth link, choose the approved work account, and finish consent.",
                }
            ],
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "auth_link_template": (
                "https://myexternalbrain.com/app/actions/google/connect?"
                "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&"
                "expected_google_email=%3Credacted-email%3E"
            ),
            "scope_bundle": "full_workspace",
            "expected_google_email_present": True,
            "expected_google_email_sha256": "expected-google-email-hash",
            "expected_google_domain": "gmail.com",
            "observed_google_email_present": True,
            "observed_google_email_sha256": "observed-google-email-hash",
            "observed_google_domain": "gmail.com",
            "observed_google_account_matches_expected": True,
            "telegram_message": "Action needed: Google Full Workspace auth is still denied even though the work account is already approved.",
            "delivery_policy": "action_required_only",
            "telegram_push_allowed": True,
            "interruption_budget": "action_required",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "raw_private_context_exposed": False,
            "raw_expected_google_email_exposed": False,
            "raw_observed_google_email_exposed": False,
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_error_description_exposed": False,
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/telegram_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(tmp_path, ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json", status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/mymedia_alexa_readiness.generated.json",
        status="pass",
        ready=True,
        echo_playback_claim_allowed=False,
        operator_action={
            "telegram_delivery_ready": True,
        },
        privacy={
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
    )
    _write_receipt(tmp_path, ".codex-studio/published/active_media_ltd_goal_bundle.generated.json", status="ready_local_evidence")
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="ready_for_approval_outcome_capture",
        gold_remaining_external_proofs=["redacted explicit approval outcome for the proactive OODA packet"],
        gold_summary=(
            "A proactive OODA packet has local gold-proof runtime evidence and a live Telegram approval capture "
            "surface; capture the redacted approval outcome next."
        ),
        gold_next_action="tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        gold_next_action_href="https://myexternalbrain.com/admin/proactive-ooda/approval",
        gold_next_action_label="Record packet verdict",
        gold_next_action_method="get",
        operator_approval_capture_surface={
            "ready": True,
            "telegram_approval_surface_ready": True,
            "manual_outcome_capture_ready": True,
            "current_packet_present": True,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expires_at": "2026-07-13T04:54:06Z",
            "selected_channel": "telegram",
        },
        operator_status_override="ready_with_recovery_action",
        operator_reason_override="source_health_google_workspace:google_oauth_invalid_grant",
        operator_summary_override=(
            "Proactive OODA route and packet runtime are available, but 1 signal source health issue needs "
            "operator recovery: google_workspace."
        ),
        operator_next_action_override="reauthorize_google_workspace_binding",
        operator_next_action_href_override=(
            "https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
        ),
        operator_next_action_label_override="Reconnect Google workspace",
        operator_next_action_method_override="get",
        operator_extra={
            "source_health": {
                "present": True,
                "status": "recovery_required",
                "issue_count": 1,
                "operator_action_required": True,
                "user_action_required": False,
                "issues": [
                    {
                        "source_key": "google_workspace",
                        "source_type": "google_workspace",
                        "status": "unhealthy",
                        "error_code": "google_oauth_invalid_grant",
                        "operator_action_required": True,
                        "user_action_required": False,
                        "next_action": "reauthorize_google_workspace_binding",
                        "raw_source_ref_exposed": False,
                        "raw_payload_exposed": False,
                        "raw_credential_exposed": False,
                    }
                ],
                "privacy": {
                    "raw_source_ref_exposed": False,
                    "raw_payload_exposed": False,
                    "raw_credential_exposed": False,
                    "source_refs_hashed": True,
                },
            },
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "delivery_route_error": "",
            "delivery_route_ready": True,
        },
    )
    _write_operator_readiness_receipt(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-07-06T05:10:00Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    google = proof_requirements["google_workspace_oauth_setup"]
    assert proactive["action_context"]["user_action_required"] is True
    assert proactive["action_context"]["delivery_policy"] == "action_required_only"
    assert proactive["action_context"]["telegram_push_allowed"] is False
    assert proactive["action_context"]["notification_policy"] == "exclusive_head"
    assert google["action_context"]["user_action_required"] is True

    assert receipt["next_action_key"] == "proactive_ooda_packet_acceptance"
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["operator_action_queue"][0]["key"] == "proactive_ooda_packet_acceptance"
    assert any(item["key"] == "google_workspace_oauth_setup" for item in receipt["operator_action_queue"])
    assert verify(output, root=tmp_path) == []


def test_build_goal_posture_marks_recover_pass_when_mirrored_fresh_host_proof_exists(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass", source_git_head="source-head")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-29T20:00:00Z",
    )

    lenses = {lens["key"]: lens for lens in receipt["lenses"]}
    proof_keys = {item["key"] for item in receipt["acceptance_proof_requirements"]}
    assert lenses["recover"]["status"] == "pass"
    assert "fresh_host_teable_recovery_drill" not in proof_keys
    assert "fresh-host Teable recovery drill receipt mirrored into the repo" not in receipt["required_next_receipts"]


def test_build_goal_posture_keeps_recover_audit_when_recovery_proof_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass", source_git_head="old-head")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-29T20:05:00Z",
    )

    lenses = {lens["key"]: lens for lens in receipt["lenses"]}
    proof_keys = {item["key"] for item in receipt["acceptance_proof_requirements"]}
    assert lenses["recover"]["status"] == "ready_local_audit"
    assert "source-state evidence is stale" in lenses["recover"]["summary"]
    assert "fresh_host_teable_recovery_drill" in proof_keys
    recovery_sources = {
        Path(source["path"]).name: source
        for source in lenses["recover"]["source_receipts"]
    }
    assert recovery_sources["teable_env_recovery_proof.generated.json"]["source_fresh_to_current_source"] is False


def test_goal_posture_verifier_rejects_recover_pass_with_stale_recovery_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass", source_git_head="old-head")
    receipt = {
        "contract_name": "ea.continuous_improvement_goal_posture.v1",
        "goal_doc": ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md",
        "goal_completion_claim_allowed": False,
        "goal_shorthand": "paid-human-assistant-grade proactive OODA governed by owning truth planes",
        "source_git_head": "source-head",
        "source_state_fingerprint": "source-fingerprint",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "execution_lenses": ["detect", "decide", "deliver", "recover", "prove"],
        "overall_status": "blocked_real_world_acceptance",
        "blocking_reasons": [],
        "required_next_receipts": [],
        "acceptance_proof_requirements": [],
        "rules": [
            "The recover lens may use a mirrored local readiness receipt, but it must not claim pass until a source-fresh fresh-host Teable recovery drill receipt is mirrored.",
            "Irreversible purchases, bookings, cancellations, outbound commitments, and sent messages must stay consent-gated even when proactive OODA staging is automated.",
            "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something.",
            "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient.",
            "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved.",
            "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth.",
        ],
        "lenses": [
            {"key": "detect", "status": "ready_local_packet_pending_operator_acceptance", "verifier_commands": ["cmd"], "source_receipts": []},
            {"key": "decide", "status": "ready_local_evidence", "verifier_commands": ["cmd"], "source_receipts": []},
            {"key": "deliver", "status": "mixed_local_progress", "verifier_commands": ["cmd"], "components": [
                {"key": "promo_media", "status": "ready_local_evidence"},
                {"key": "manfred_speech", "status": "pass"},
                {"key": "telegram_audiobook", "status": "pass"},
                {"key": "whatsapp_audiobook", "status": "pass"},
            ]},
            {
                "key": "recover",
                "status": "pass",
                "verifier_commands": ["cmd"],
                "source_receipts": [
                    {
                        "path": ".codex-studio/published/teable_env_recovery_readiness.generated.json",
                        "present": True,
                        "status": "ready_local_audit",
                    },
                    {
                        "path": ".codex-studio/published/teable_env_recovery_proof.generated.json",
                        "present": True,
                        "status": "pass",
                        "source_fresh_to_current_source": False,
                    },
                ],
            },
            {"key": "prove", "status": "blocked_real_world_acceptance", "verifier_commands": ["cmd"], "source_receipts": []},
        ],
    }
    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    assert "recover lens pass requires a source-fresh Teable recovery proof receipt" in verify(output, root=tmp_path)


def test_goal_posture_verifier_accepts_materialized_receipt(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
        next_action="capture a consented real STT fixture",
        current_label="Memorial public-origin gold: blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
        summary="Teable recovery command surface is mirrored and documented locally; a seeded fresh-host drill receipt is still required before any pass claim.",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="waiting",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output)
    assert issues == []


def test_goal_posture_verifier_rejects_uncovered_acceptance_proof_requirement(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
        next_action="maintain consented real STT fixture",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:15:00Z")
    receipt["acceptance_proof_requirements"] = [
        item
        for item in list(receipt["acceptance_proof_requirements"])
        if item["key"] != "proactive_ooda_packet_acceptance"
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output)
    assert "acceptance_proof_requirements must cover every required_next_receipts item exactly" in issues
    assert "acceptance_proof_requirements must include proactive_ooda_packet_acceptance" in issues


def test_goal_posture_verifier_requires_acceptance_requirement_action_surface(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="choose_sent_replacement_voice_sample",
    )
    for relative_path in (
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
    ):
        _write_receipt(tmp_path, relative_path, status="pass")
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T05:15:00Z")
    receipt["acceptance_proof_requirements"][0]["next_action_href"] = ""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output, root=tmp_path)

    assert "acceptance proof requirement morning_brief_operator_acceptance missing next_action_href" in issues
    assert (
        "acceptance proof requirement morning_brief_operator_acceptance next_action_href must target "
        "/admin/actions/acceptance-evidence"
    ) in issues


def test_goal_posture_verifier_rejects_stale_proactive_ooda_source_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch, head="fresh-source-head", fingerprint="fresh-source-fingerprint")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        source_git_head="stale-source-head",
        source_state_fingerprint="stale-source-fingerprint",
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:25:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output, root=tmp_path)
    assert (
        "proactive_ooda_packet_acceptance source receipt stale: .codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
        in issues
    )
    assert (
        "proactive_ooda_packet_acceptance source receipt stale: .codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
        in issues
    )


def test_goal_posture_marks_passed_proactive_ooda_gold_as_satisfied(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="pass",
        gold_claim_allowed=True,
        gold_remaining_external_proofs=[],
        gold_approval_accepted=True,
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T05:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["status"] == "satisfied"
    assert proactive["next_action"] == "maintain_proactive_ooda_gold_acceptance_evidence"
    assert proactive["next_action_href"] == "/app/today"
    assert proactive["next_action_method"] == "get"
    assert posture_module.PROACTIVE_OODA_ACCEPTANCE_RECEIPT not in receipt["required_next_receipts"]
    assert verify(output, root=tmp_path) == []


def test_goal_posture_verifier_accepts_waiting_for_live_epub_component_status(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
        next_action="capture a consented real STT fixture",
        current_label="Memorial public-origin gold: blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
        summary="Teable recovery command surface is mirrored and documented locally; a seeded fresh-host drill receipt is still required before any pass claim.",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="waiting_for_live_epub",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="waiting_for_live_epub",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="waiting",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:30:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output)
    assert issues == []


def test_goal_posture_accepts_internal_telegram_voice_sample_repair(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
        next_action="capture a consented real STT fixture",
        current_label="Memorial public-origin gold: blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="send_missing_telegram_audiobook_voice_samples_before_user_choice",
        operator_action_packet={
            "user_action_required": False,
            "instruction": "Send the missing Telegram audiobook voice samples before asking the user to choose.",
            "sent_samples_cover_expected": False,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        duplicate_suppression={
            "action_required_only": True,
            "only_current_jobs_can_require_user_action": True,
            "superseded_duplicate_candidate_count": 1,
            "suppressed_pending_voice_duplicate_count": 1,
            "active_pending_voice_job_count": 1,
            "duplicate_active_pending_source_key_count": 0,
            "duplicate_active_pending_source_keys_sha256": [],
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        pending_user_selected_voice_jobs=[
            {
                "replacement_candidate_count": 2,
                "replacement_candidate_labels": ["Hans", "Jurgen"],
                "author_gender_signal": "male",
                "author_gender_match_count": 2,
                "author_gender_mismatch_count": 0,
                "author_gender_matched_candidates_only": True,
                "voice_sample_delivery_status": "sent",
                "voice_sample_delivery_sent_count": 1,
                "voice_sample_delivery_expected_count": 1,
                "raw_voice_ids_exposed": False,
                "callback_tokens_exposed": False,
            }
        ],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:45:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    telegram = proof_requirements["telegram_audiobook_live_delivery"]
    assert telegram["next_action"] == "send_missing_telegram_audiobook_voice_samples_before_user_choice"
    assert telegram["next_action_href"] == "/app/channel-loop"
    assert telegram["next_action_form_href"] == "/app/channel-loop"
    assert telegram["action_context"]["user_action_required"] is False
    assert telegram["action_context"]["sent_samples_cover_expected"] is False
    queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "telegram_audiobook_live_delivery")
    assert queue_row["user_action_required"] is False
    assert queue_row["telegram_push_allowed"] is False
    assert verify(output) == []


def test_goal_posture_models_failed_whatsapp_playback_as_queue_only_repair(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="failed",
        failed=1,
        attempted=1,
        results=[
            {
                "status": "failed",
                "passed": False,
                "reason": "play_failed",
                "track_response_status": 500,
                "track_content_type": "text/html",
                "media_error": True,
                "media_error_code": 4,
                "public_share_host": "audiobookshelf.example.test",
                "raw_url_exposed": False,
            }
        ],
        privacy={"raw_public_share_url_exposed": False, "raw_track_url_exposed": False},
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="pass",
        gold_claim_allowed=True,
        gold_remaining_external_proofs=[],
        gold_approval_accepted=True,
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T09:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    whatsapp = proof_requirements["whatsapp_audiobook_live_delivery"]
    assert whatsapp["action_context"]["kind"] == "public_share_playback_failure"
    assert whatsapp["action_context"]["user_action_required"] is False
    assert whatsapp["action_context"]["telegram_push_allowed"] is False
    assert whatsapp["action_context"]["track_response_status"] == 500
    assert whatsapp["action_context"]["track_content_type"] == "text/html"
    queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "whatsapp_audiobook_live_delivery")
    assert queue_row["user_action_required"] is False
    assert queue_row["telegram_push_allowed"] is False
    assert queue_row["track_response_status"] == 500
    assert queue_row["raw_public_share_url_exposed"] is False
    assert queue_row["raw_track_url_exposed"] is False
    assert "deliver:whatsapp_audiobook=failed" in receipt["blocking_reasons"]
    assert verify(output, root=tmp_path) == []


def test_goal_posture_models_blocked_whatsapp_playback_as_queue_only_repair(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_delivery_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_business_signal_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/pocket_audio_archive_receipt.generated.json",
        status="pass",
        transcript_ingest_ready=True,
        archive_audio_file_total=1,
        archive_metadata_json_total=1,
        missing_transcript_total=0,
    )
    _write_teable_recovery_proof_receipt(tmp_path)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="blocked",
        recommended_action="fix_whatsapp_action_processor_run",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="run_public_share_machine_playback_e2e_before_claiming_live_delivery",
        failed_codes=["valid_live_audiobook_delivery_missing", "machine_playback_e2e_not_verified"],
        selected_delivery={
            "failed_codes": ["machine_playback_e2e_not_verified"],
            "machine_playback_e2e_reason": "play_failed",
            "machine_playback_e2e_track_response_status": 500,
            "machine_playback_e2e_track_content_type": "text/html",
            "machine_playback_e2e_media_error_present": True,
            "machine_playback_e2e_media_error_code": 4,
            "public_share_host": "audiobookshelf.example.test",
            "public_share_status": "public_share_ready",
            "public_share_url_present": True,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="blocked",
        failed=0,
        attempted=0,
        results=[],
        privacy={"raw_public_share_url_exposed": False, "raw_track_url_exposed": False},
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="pass",
        gold_claim_allowed=True,
        gold_remaining_external_proofs=[],
        gold_approval_accepted=True,
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T09:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    whatsapp = proof_requirements["whatsapp_audiobook_live_delivery"]
    assert whatsapp["action_context"]["kind"] == "public_share_playback_failure"
    assert whatsapp["action_context"]["user_action_required"] is False
    assert whatsapp["action_context"]["telegram_push_allowed"] is False
    assert whatsapp["action_context"]["failed_playback_count"] == 1
    assert whatsapp["action_context"]["attempted_playback_count"] == 1
    assert whatsapp["action_context"]["track_response_status"] == 500
    assert whatsapp["action_context"]["track_content_type"] == "text/html"
    assert whatsapp["action_context"]["raw_public_share_url_exposed"] is False
    assert whatsapp["action_context"]["raw_track_url_exposed"] is False
    queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "whatsapp_audiobook_live_delivery")
    assert queue_row["user_action_required"] is False
    assert queue_row["delivery_policy"] == "queue_only"
    assert queue_row["telegram_push_allowed"] is False
    assert queue_row["track_response_status"] == 500
    assert queue_row["track_content_type"] == "text/html"
    assert queue_row["raw_public_share_url_exposed"] is False
    assert queue_row["raw_track_url_exposed"] is False
    assert "deliver:whatsapp_audiobook=blocked" in receipt["blocking_reasons"]
    assert verify(output, root=tmp_path) == []


def test_whatsapp_live_playback_blocked_ignores_waiting_public_share_scan() -> None:
    receipt = {
        "failed_codes": ["valid_live_audiobook_delivery_missing", "machine_playback_e2e_not_verified"],
        "next_action": "finish_user_selected_voice_audiobook_before_sending_whatsapp_public_share_link",
        "selected_delivery": {
            "failed_codes": [
                "audiobookshelf_public_share_not_ready",
                "audiobookshelf_public_share_url_missing",
                "machine_playback_e2e_not_verified",
            ],
            "public_share_status": "waiting_for_audiobookshelf_scan",
            "public_share_url_present": False,
            "machine_playback_e2e_track_response_status": 0,
            "machine_playback_e2e_track_content_type": "",
        },
    }

    assert posture_module._whatsapp_live_playback_blocked(  # noqa: SLF001
        receipt,
        ["deliver:whatsapp_audiobook=blocked"],
    ) is False


def test_goal_posture_models_whatsapp_qr_required_as_action_required_pairing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_acceptance_receipt_with_morning_brief_accepted(tmp_path)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_business_signal_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
        status="pass",
        scope_bundle="full_workspace",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/pocket_audio_archive_receipt.generated.json",
        status="pass",
        transcript_ingest_ready=True,
        archive_audio_file_total=1,
        archive_metadata_json_total=1,
        missing_transcript_total=0,
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json",
        status="blocked",
        reason="sidecar_not_ready",
        reasons=["sidecar_not_ready"],
        sidecar_ready=False,
        sidecar_status="qr_required",
        sidecar_qr_required=True,
        sidecar_qr_present=True,
        sidecar_qr_fresh=True,
        sidecar_qr_age_seconds=12,
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="blocked",
        live_readiness={"status": "blocked", "reason": "sidecar_not_ready", "sidecar_ready": False},
        live_sidecar_inbox={"status": "pass", "session_status": "qr_required", "session_api_host_kind": "loopback"},
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="finish_user_selected_voice_audiobook_before_sending_whatsapp_public_share_link",
        failed_codes=["valid_live_audiobook_delivery_missing", "audiobookshelf_public_share_url_missing"],
        selected_delivery={
            "public_share_status": "waiting_for_audiobookshelf_scan",
            "public_share_url_present": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="waiting",
        attempted=0,
        failed=0,
        privacy={"raw_public_share_url_exposed": False, "raw_track_url_exposed": False},
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="pass",
        gold_claim_allowed=True,
        gold_remaining_external_proofs=[],
        gold_approval_accepted=True,
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-07-01T13:30:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    whatsapp = proof_requirements["whatsapp_audiobook_live_delivery"]
    context = whatsapp["action_context"]
    assert context["kind"] == "whatsapp_web_sidecar_pairing_required"
    assert context["user_action_required"] is True
    assert context["telegram_push_allowed"] is True
    assert context["sidecar_status"] == "qr_required"
    assert context["pair_url_scope"] == "host_local"
    assert context["pair_url_actionable_from_telegram"] is False
    assert context["raw_pair_url_exposed"] is False
    assert context["raw_qr_payload_exposed"] is False
    assert context["raw_whatsapp_session_ref_exposed"] is False

    queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "whatsapp_audiobook_live_delivery")
    assert queue_row["kind"] == "whatsapp_web_sidecar_pairing_required"
    assert queue_row["user_action_required"] is True
    assert queue_row["delivery_policy"] == "action_required_only"
    assert queue_row["telegram_push_allowed"] is True
    assert queue_row["sidecar_status"] == "qr_required"
    assert queue_row["sidecar_qr_required"] is True
    assert queue_row["pair_url_scope"] == "host_local"
    assert queue_row["pair_url_actionable_from_telegram"] is False
    assert queue_row["raw_pair_url_exposed"] is False
    assert queue_row["raw_qr_payload_exposed"] is False
    assert queue_row["raw_whatsapp_session_ref_exposed"] is False
    assert "deliver:whatsapp_audiobook=blocked" in receipt["blocking_reasons"]
    assert verify(output, root=tmp_path) == []


def test_goal_posture_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch, head="new-head", fingerprint="source-fingerprint")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(
        tmp_path,
        status="pass",
        source_git_head="old-head",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        source_git_head="old-head",
        source_state_fingerprint="source-fingerprint",
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:40:00Z")
    receipt["source_git_head"] = "old-head"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    assert verify(output, root=tmp_path) == []
