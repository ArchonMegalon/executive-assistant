from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _no_container_processor(_args):
    return {}, {"attempted": True, "stdout_json_present": False, "return_code": 127}


def _empty_sidecar_inbox(_args):
    return {
        "attempted": True,
        "status": "pass",
        "status_code": 200,
        "session_api_host_kind": "loopback",
        "session_ready": True,
        "session_status": "ready",
        "messages_accessible": True,
        "inbox_count": 0,
        "message_count": 0,
        "inbound_message_count": 0,
        "media_message_count": 0,
        "epub_media_candidate_count": 0,
        "selected_button_candidate_count": 0,
        "latest_message_timestamp_present": False,
        "raw_text_exposed": False,
        "raw_sender_exposed": False,
        "raw_message_ids_exposed": False,
        "raw_media_url_exposed": False,
    }


class ShadowReceipt:
    @staticmethod
    def build_receipt(**_kwargs):
        return {
            "status": "waiting",
            "reason": "waiting_whatsapp_voice_selection_job_not_found",
            "candidate": {},
            "shadow": {},
            "checks": {
                "waiting_voice_selection_job_found": False,
                "shadow_callback_applied": False,
                "shadow_text_fallback_ready": False,
                "shadow_reached_render_action": False,
                "live_job_unchanged": False,
            },
            "text_fallback": {"status": "waiting"},
            "live_mutation": {"unchanged": False},
        }


class PassingShadowReceipt:
    @staticmethod
    def build_receipt(**_kwargs):
        return {
            "status": "pass",
            "reason": "",
            "candidate": {
                "status": "waiting_voice_selection",
                "next_action": "choose_audiobook_voice",
                "pending_voice_count": 3,
                "voice_sample_delivery_status": "sent",
            },
            "shadow": {
                "status": "pass",
                "callback_status": "applied",
                "shadow_status": "voice_selected",
                "shadow_next_action": "render_chapter_audio",
                "pending_voice_count_after": 0,
                "selected_label_present": True,
            },
            "checks": {
                "waiting_voice_selection_job_found": True,
                "voice_sample_delivery_sent": True,
                "shadow_callback_applied": True,
                "shadow_text_fallback_ready": True,
                "shadow_reached_render_action": True,
                "shadow_pending_batch_cleared": True,
                "shadow_raw_voice_ids_not_exposed": True,
                "live_job_unchanged": True,
            },
            "text_fallback": {
                "status": "pass",
                "use_named_action": "use_named",
                "dismiss_named_action": "dismiss_named",
                "dismiss_all_action": "dismiss_all",
                "bare_voice_choice_resolved": True,
                "fallback_prompt_mentions_text_commands": True,
            },
            "live_mutation": {"unchanged": True},
        }


class FailingShadowReceipt:
    @staticmethod
    def build_receipt(**_kwargs):
        return {
            "status": "failed",
            "reason": "shadow_voice_selection_proof_failed",
            "candidate": {
                "status": "waiting_voice_selection",
                "next_action": "choose_audiobook_voice",
                "pending_voice_count": 3,
                "voice_sample_delivery_status": "sent",
            },
            "shadow": {
                "status": "failed",
                "callback_status": "failed",
                "shadow_status": "waiting_voice_selection",
                "shadow_next_action": "choose_audiobook_voice",
                "pending_voice_count_after": 3,
                "selected_label_present": False,
            },
            "checks": {
                "waiting_voice_selection_job_found": True,
                "voice_sample_delivery_sent": True,
                "shadow_callback_applied": False,
                "shadow_text_fallback_ready": False,
                "shadow_reached_render_action": False,
                "shadow_pending_batch_cleared": False,
                "shadow_raw_voice_ids_not_exposed": True,
                "live_job_unchanged": True,
            },
            "text_fallback": {"status": "failed"},
            "live_mutation": {"unchanged": True},
        }


def test_whatsapp_audiobook_operator_proof_bundle_separates_local_and_live_states(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "receipt_path": "local-proof.json",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {
                        "next_action": "finish_user_selected_voice_audiobook_before_sending_whatsapp_public_share_link",
                        "stage_counts": {"waiting_machine_playback_verification": 1},
                    },
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "blocked",
                "candidate_count": 0,
                "observed_job_count": 4,
                "non_whatsapp_job_count": 4,
                "failed_codes": ["valid_live_audiobook_delivery_missing", "whatsapp_audiobook_job_missing"],
                "next_action": "send_epub_over_whatsapp_to_start_audiobook_flow",
                "stage_summary": {"counts": {}},
                "live_delivery_claim_allowed": False,
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {
                "ready": True,
                "reason": "ready",
                "reasons": [],
                "action_processor_enabled": True,
                "sidecar_ready": True,
                "state_fresh": True,
            }

    class Processor:
        DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
        DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
        DEFAULT_SESSION_REF = "test-wa-web"
        DEFAULT_STATE_FILE = "/tmp/test-wa-actions.json"

        @staticmethod
        def _env(_name, default=""):
            return os.environ.get(_name, default)

        @staticmethod
        def build_report(_args):
            return {
                "status": "pass",
                "message_count": 0,
                "candidate_count": 0,
                "epub_candidate_count": 0,
                "epub_processed": 0,
                "status_candidate_count": 0,
                "status_processed": 0,
                "processed": 0,
                "skipped_processed": 0,
                "reply_sent": 0,
                "voice_sample_sent": 0,
                "share_link_sent": 0,
                "errors": 0,
                "followup_summary": {"attempted": 0, "sent": 0, "errors": 0},
                "resume_summary": {"ran": False, "errors": 0},
            }

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return ShadowReceipt
        if "process_whatsapp" in name:
            return Processor
        return Readiness

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", _no_container_processor)
    monkeypatch.setattr(module, "_sidecar_inbox_observation", _empty_sidecar_inbox)
    monkeypatch.setattr(module, "_read_json", lambda _path: {})
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="test-wa-web",
            state_file="/tmp/test-wa-actions.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert bundle["contract_name"] == "ea.whatsapp_audiobook_operator_proof_bundle.v1"
    assert bundle["status"] == "blocked"
    assert bundle["recommended_action"] == "send_epub_over_whatsapp_to_start_audiobook_flow"
    assert bundle["checks"]["local_epub_intake_proof_passed"] is True
    assert bundle["checks"]["live_action_processor_ready"] is True
    assert bundle["checks"]["local_proof_selects_voice_and_sends_share"] is True
    assert bundle["checks"]["local_proof_player_probe_passed"] is True
    assert bundle["checks"]["local_proof_player_http_route_passed"] is True
    assert bundle["checks"]["historical_public_share_playback_proven"] is False
    assert bundle["checks"]["live_action_processor_ran"] is True
    assert bundle["checks"]["live_action_processor_no_runtime_errors"] is True
    assert bundle["checks"]["live_processor_runtime_alignment_evaluated"] is True
    assert bundle["checks"]["live_sidecar_inbox_accessible"] is True
    assert bundle["checks"]["live_public_share_playback_verified_or_not_required"] is True
    assert bundle["checks"]["live_voice_selection_text_fallback_ready_or_not_required"] is True
    assert bundle["checks"]["live_voice_selection_shadow_passed_or_not_required"] is True
    assert bundle["live_sidecar_inbox"]["messages_accessible"] is True
    assert bundle["live_sidecar_inbox"]["epub_media_candidate_count"] == 0
    assert bundle["live_sidecar_inbox"]["raw_text_exposed"] is False
    assert bundle["live_sidecar_inbox"]["raw_sender_exposed"] is False
    assert bundle["live_sidecar_inbox"]["raw_message_ids_exposed"] is False
    assert bundle["runtime_alignment"]["evaluated"] is True
    assert bundle["runtime_alignment"]["state_file_match"] is True
    assert bundle["runtime_alignment"]["session_ref_match"] is True
    assert bundle["runtime_alignment"]["session_api_host_kind_match"] is True
    assert bundle["runtime_alignment"]["session_api_host_kind_exact_match"] is True
    assert bundle["runtime_alignment"]["secret_values_exposed"] is False
    assert bundle["warnings"] == []
    assert bundle["local_intake"]["voice_sample_sent"] == 3
    assert bundle["local_intake"]["voice_selection_processed"] == 1
    assert bundle["local_intake"]["share_link_sent"] == 1
    assert bundle["local_intake"]["delivery_stage_counts"] == {"waiting_machine_playback_verification": 1}
    assert bundle["local_intake"]["player_probe"]["status"] == "pass"
    assert bundle["local_intake"]["player_probe"]["content_type"] == "audio/mp4"
    assert bundle["local_intake"]["player_probe"]["audio_streams"] == 1
    assert bundle["local_intake"]["player_http_probe"]["status"] == "pass"
    assert bundle["local_intake"]["player_http_probe"]["metadata_status_code"] == 200
    assert bundle["local_intake"]["player_http_probe"]["download_status_code"] == 200
    assert bundle["local_intake"]["player_http_probe"]["download_content_type"] == "audio/mp4"
    assert bundle["local_intake"]["player_http_probe"]["download_bytes"] == 1024
    assert bundle["live_processor"]["ran"] is True
    assert bundle["live_processor"]["execution_runtime"] == "host_fallback"
    assert bundle["live_processor"]["status"] == "pass"
    assert bundle["live_processor"]["errors"] == 0
    assert bundle["live_delivery"]["candidate_count"] == 0
    assert bundle["public_share_playback"]["status"] in {"", "waiting"}
    assert bundle["public_share_playback"]["historical_playback_path_proven"] is False
    assert bundle["live_voice_selection_shadow"]["status"] == "waiting"
    assert bundle["live_voice_selection_shadow"]["text_fallback"]["status"] == "waiting"
    rendered = json.dumps(bundle, sort_keys=True)
    assert "4368120864006" not in rendered
    assert "wamid" not in rendered


def test_whatsapp_audiobook_operator_proof_bundle_uses_effective_session_ref_for_sidecar_inbox(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")
    observed: dict[str, str] = {}

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "receipt_path": "local-proof.json",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {"stage_counts": {"waiting_machine_playback_verification": 1}},
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "blocked",
                "candidate_count": 0,
                "observed_job_count": 0,
                "non_whatsapp_job_count": 0,
                "failed_codes": ["valid_live_audiobook_delivery_missing", "whatsapp_audiobook_job_missing"],
                "next_action": "send_epub_over_whatsapp_to_start_audiobook_flow",
                "stage_summary": {"counts": {}},
                "live_delivery_claim_allowed": False,
                "historical_evidence": {"present": False, "historical_live_path_proven": False},
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {
                "ready": True,
                "reason": "ready",
                "reasons": [],
                "action_processor_enabled": True,
                "sidecar_ready": True,
                "state_fresh": True,
                "effective_session_ref": "tibor-wa-web",
            }

    class Processor:
        DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
        DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
        DEFAULT_SESSION_REF = "default-wa-web"
        DEFAULT_STATE_FILE = "/tmp/test-wa-actions.json"

        @staticmethod
        def _env(_name, default=""):
            return os.environ.get(_name, default)

        @staticmethod
        def build_report(_args):
            return {
                "status": "pass",
                "message_count": 0,
                "candidate_count": 0,
                "epub_candidate_count": 0,
                "epub_processed": 0,
                "status_candidate_count": 0,
                "status_processed": 0,
                "processed": 0,
                "skipped_processed": 0,
                "reply_sent": 0,
                "voice_sample_sent": 0,
                "share_link_sent": 0,
                "errors": 0,
                "followup_summary": {"attempted": 0, "sent": 0, "errors": 0},
                "resume_summary": {"ran": False, "errors": 0},
            }

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return ShadowReceipt
        if "process_whatsapp" in name:
            return Processor
        return Readiness

    def fake_sidecar_inbox(args):
        observed["session_ref"] = str(getattr(args, "session_ref", "") or "")
        return _empty_sidecar_inbox(args)

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", _no_container_processor)
    monkeypatch.setattr(module, "_sidecar_inbox_observation", fake_sidecar_inbox)
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="default-wa-web",
            state_file="/tmp/test-wa-actions.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert observed["session_ref"] == "tibor-wa-web"
    assert bundle["live_sidecar_inbox"]["messages_accessible"] is True


def test_whatsapp_audiobook_operator_proof_bundle_blocks_voice_choice_when_shadow_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {"stage_counts": {"waiting_machine_playback_verification": 1}},
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "waiting_voice_choice",
                "candidate_count": 1,
                "observed_job_count": 1,
                "non_whatsapp_job_count": 0,
                "failed_codes": ["user_selected_voice_delivery_not_ready"],
                "next_action": "choose_whatsapp_audiobook_voice_sample",
                "stage_summary": {"counts": {"waiting_voice_choice": 1}},
                "live_delivery_claim_allowed": False,
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {
                "ready": True,
                "reason": "ready",
                "reasons": [],
                "action_processor_enabled": True,
                "sidecar_ready": True,
                "state_fresh": True,
            }

    class Processor:
        DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
        DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
        DEFAULT_SESSION_REF = "test-wa-web"
        DEFAULT_STATE_FILE = "/tmp/test-wa-actions.json"

        @staticmethod
        def _env(_name, default=""):
            return os.environ.get(_name, default)

        @staticmethod
        def build_report(_args):
            return {"status": "pass", "errors": 0, "followup_summary": {}, "resume_summary": {}}

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return FailingShadowReceipt
        if "process_whatsapp" in name:
            return Processor
        return Readiness

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", _no_container_processor)
    monkeypatch.setattr(module, "_sidecar_inbox_observation", _empty_sidecar_inbox)
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="test-wa-web",
            state_file="/tmp/test-wa-actions.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert bundle["status"] == "blocked"
    assert bundle["recommended_action"] == "fix_whatsapp_voice_selection_shadow_proof"
    assert bundle["checks"]["live_voice_selection_shadow_passed_or_not_required"] is False
    assert bundle["live_voice_selection_shadow"]["status"] == "failed"
    assert bundle["live_delivery"]["status"] == "waiting_voice_choice"


def test_whatsapp_audiobook_operator_proof_bundle_requests_refresh_when_only_historical_live_proof_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "receipt_path": "local-proof.json",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {"stage_counts": {"waiting_machine_playback_verification": 1}},
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "waiting_for_live_epub",
                "candidate_count": 0,
                "observed_job_count": 0,
                "non_whatsapp_job_count": 0,
                "failed_codes": [
                    "whatsapp_audiobook_job_missing",
                    "fresh_live_whatsapp_job_receipt_missing",
                ],
                "next_action": "send_epub_over_whatsapp_to_refresh_live_audiobook_flow",
                "stage_summary": {"counts": {}},
                "live_delivery_claim_allowed": False,
                "historical_evidence": {
                    "present": True,
                    "historical_live_path_proven": True,
                },
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {
                "ready": True,
                "reason": "ready",
                "reasons": [],
                "action_processor_enabled": True,
                "sidecar_ready": True,
                "state_fresh": True,
            }

    class Processor:
        DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
        DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
        DEFAULT_SESSION_REF = "test-wa-web"
        DEFAULT_STATE_FILE = "/tmp/test-wa-actions.json"

        @staticmethod
        def _env(_name, default=""):
            return os.environ.get(_name, default)

        @staticmethod
        def build_report(_args):
            return {
                "status": "pass",
                "message_count": 0,
                "candidate_count": 0,
                "epub_candidate_count": 0,
                "epub_processed": 0,
                "status_candidate_count": 0,
                "status_processed": 0,
                "processed": 0,
                "skipped_processed": 0,
                "reply_sent": 0,
                "voice_sample_sent": 0,
                "share_link_sent": 0,
                "errors": 0,
                "followup_summary": {"attempted": 0, "sent": 0, "errors": 0},
                "resume_summary": {"ran": False, "errors": 0},
            }

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return ShadowReceipt
        if "process_whatsapp" in name:
            return Processor
        return Readiness

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", _no_container_processor)
    monkeypatch.setattr(module, "_sidecar_inbox_observation", _empty_sidecar_inbox)
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="test-wa-web",
            state_file="/tmp/test-wa-actions.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert bundle["status"] == "waiting_for_live_epub"
    assert bundle["recommended_action"] == "send_epub_over_whatsapp_to_refresh_live_audiobook_flow"
    assert bundle["live_delivery"]["historical_evidence_present"] is True
    assert bundle["live_delivery"]["historical_live_path_proven"] is True


def test_whatsapp_audiobook_operator_proof_bundle_blocks_processor_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {"stage_counts": {"waiting_machine_playback_verification": 1}},
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "waiting_for_live_epub",
                "candidate_count": 0,
                "failed_codes": ["whatsapp_audiobook_job_missing", "fresh_live_whatsapp_job_receipt_missing"],
                "next_action": "send_epub_over_whatsapp_to_start_live_audiobook_flow",
                "stage_summary": {"counts": {}},
                "live_delivery_claim_allowed": False,
                "historical_evidence": {
                    "present": True,
                    "historical_live_path_proven": True,
                },
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {"ready": True, "reason": "ready", "reasons": []}

    class Processor:
        DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
        DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
        DEFAULT_SESSION_REF = "test-wa-web"
        DEFAULT_STATE_FILE = "/tmp/test-wa-actions.json"

        @staticmethod
        def _env(_name, default=""):
            return os.environ.get(_name, default)

        @staticmethod
        def build_report(_args):
            raise RuntimeError("sidecar_down")

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return ShadowReceipt
        if "process_whatsapp" in name:
            return Processor
        return Readiness

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", _no_container_processor)
    monkeypatch.setattr(module, "_sidecar_inbox_observation", _empty_sidecar_inbox)
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="test-wa-web",
            state_file="/tmp/test-wa-actions.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert bundle["status"] == "blocked"
    assert bundle["recommended_action"] == "fix_whatsapp_action_processor_run"
    assert bundle["checks"]["live_action_processor_ran"] is True
    assert bundle["checks"]["live_action_processor_no_runtime_errors"] is False
    assert bundle["checks"]["live_processor_runtime_alignment_evaluated"] is True
    assert bundle["live_processor"]["errors"] == 1


def test_whatsapp_audiobook_operator_proof_bundle_blocks_when_sidecar_inbox_is_inaccessible(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {"stage_counts": {"waiting_machine_playback_verification": 1}},
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "waiting_for_live_epub",
                "candidate_count": 0,
                "failed_codes": ["whatsapp_audiobook_job_missing", "fresh_live_whatsapp_job_receipt_missing"],
                "next_action": "send_epub_over_whatsapp_to_start_live_audiobook_flow",
                "stage_summary": {"counts": {}},
                "live_delivery_claim_allowed": False,
                "historical_evidence": {
                    "present": True,
                    "historical_live_path_proven": True,
                },
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {"ready": True, "reason": "ready", "reasons": []}

    class Processor:
        DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
        DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
        DEFAULT_SESSION_REF = "test-wa-web"
        DEFAULT_STATE_FILE = "/tmp/test-wa-actions.json"

        @staticmethod
        def _env(_name, default=""):
            return os.environ.get(_name, default)

        @staticmethod
        def build_report(_args):
            return {"status": "pass", "errors": 0, "followup_summary": {}, "resume_summary": {}}

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return ShadowReceipt
        if "process_whatsapp" in name:
            return Processor
        return Readiness

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", _no_container_processor)
    monkeypatch.setattr(
        module,
        "_sidecar_inbox_observation",
        lambda _args: {
            "attempted": True,
            "status": "failed",
            "messages_accessible": False,
            "raw_text_exposed": False,
            "raw_sender_exposed": False,
            "raw_message_ids_exposed": False,
            "raw_media_url_exposed": False,
        },
    )
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="test-wa-web",
            state_file="/tmp/test-wa-actions.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert bundle["status"] == "blocked"
    assert bundle["recommended_action"] == "fix_whatsapp_sidecar_inbox_access"
    assert bundle["checks"]["live_sidecar_inbox_accessible"] is False
    assert bundle["live_sidecar_inbox"]["messages_accessible"] is False


def test_whatsapp_audiobook_operator_proof_bundle_warns_on_state_file_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {"stage_counts": {"waiting_machine_playback_verification": 1}},
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "waiting_for_live_epub",
                "candidate_count": 0,
                "failed_codes": ["whatsapp_audiobook_job_missing", "fresh_live_whatsapp_job_receipt_missing"],
                "next_action": "send_epub_over_whatsapp_to_start_live_audiobook_flow",
                "stage_summary": {"counts": {}},
                "live_delivery_claim_allowed": False,
                "historical_evidence": {
                    "present": True,
                    "historical_live_path_proven": True,
                },
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {"ready": True, "reason": "ready", "reasons": []}

    class Processor:
        DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
        DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
        DEFAULT_SESSION_REF = "test-wa-web"
        DEFAULT_STATE_FILE = "/tmp/test-wa-actions.json"

        @staticmethod
        def _env(_name, default=""):
            return os.environ.get(_name, default)

        @staticmethod
        def build_report(_args):
            return {
                "status": "pass",
                "errors": 0,
                "followup_summary": {},
                "resume_summary": {},
            }

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return ShadowReceipt
        if "process_whatsapp" in name:
            return Processor
        return Readiness

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", _no_container_processor)
    monkeypatch.setattr(module, "_sidecar_inbox_observation", _empty_sidecar_inbox)
    monkeypatch.setenv("EA_WHATSAPP_WEB_ACTION_STATE_FILE", "/tmp/test-wa-actions.json")
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="test-wa-web",
            state_file="/data/whatsapp-actions/processed.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert bundle["status"] == "waiting_for_live_epub"
    assert bundle["runtime_alignment"]["state_file_match"] is False
    assert bundle["runtime_alignment"]["processor_state_file_kind"] == "host_tmp"
    assert bundle["runtime_alignment"]["readiness_state_file_kind"] == "whatsapp_actions_volume"
    assert bundle["runtime_alignment"]["secret_values_exposed"] is False
    assert bundle["warnings"] == ["live_processor_state_file_mismatch"]


def test_whatsapp_audiobook_operator_proof_bundle_prefers_container_processor_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")

    class LocalProof:
        @staticmethod
        def materialize_whatsapp_audiobook_local_intake_proof():
            return {
                "status": "pass",
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"processed": 1, "share_link_sent": 1},
                },
                "local_stage_receipt_summary": {
                    "intake": {"next_action": "choose_whatsapp_audiobook_voice_sample"},
                    "delivery": {"stage_counts": {"waiting_machine_playback_verification": 1}},
                },
                "player_probe_summary": {
                    "status": "pass",
                    "metadata_status": "ready",
                    "content_type": "audio/mp4",
                    "audio_streams": 1,
                    "duration_seconds": 0.24,
                },
                "player_http_probe_summary": {
                    "status": "pass",
                    "metadata_status_code": 200,
                    "download_status_code": 200,
                    "download_content_type": "audio/mp4",
                    "download_bytes": 1024,
                },
            }

    class LiveReceipt:
        @staticmethod
        def _scan_job_receipts(_limit):
            return [], []

        @staticmethod
        def build_receipt(**_kwargs):
            return {
                "status": "waiting_for_live_epub",
                "candidate_count": 0,
                "failed_codes": ["whatsapp_audiobook_job_missing", "fresh_live_whatsapp_job_receipt_missing"],
                "next_action": "send_epub_over_whatsapp_to_start_live_audiobook_flow",
                "stage_summary": {"counts": {}},
                "live_delivery_claim_allowed": False,
                "historical_evidence": {
                    "present": True,
                    "historical_live_path_proven": True,
                },
            }

    class Readiness:
        @staticmethod
        def build_report(_args):
            return {"ready": True, "reason": "ready", "reasons": []}

    def fake_load_module(*, name: str, path: Path):
        if "local_intake" in name:
            return LocalProof
        if "live_delivery" in name:
            return LiveReceipt
        if "voice_selection_shadow" in name:
            return ShadowReceipt
        if "process_whatsapp" in name:
            raise AssertionError("host processor should not load when container runtime reports JSON")
        return Readiness

    def fake_container_processor(_args):
        return (
            {
                "status": "pass",
                "message_count": 0,
                "candidate_count": 0,
                "epub_candidate_count": 0,
                "epub_processed": 0,
                "status_candidate_count": 0,
                "status_processed": 0,
                "processed": 0,
                "skipped_processed": 0,
                "reply_sent": 0,
                "voice_sample_sent": 0,
                "share_link_sent": 0,
                "errors": 0,
                "followup_summary": {"attempted": 0, "sent": 0, "errors": 0},
                "resume_summary": {"ran": False, "errors": 0},
            },
            {"attempted": True, "stdout_json_present": True, "return_code": 0},
        )

    monkeypatch.setattr(module, "_load_module", fake_load_module)
    monkeypatch.setattr(module, "_run_processor_in_container", fake_container_processor)
    monkeypatch.setattr(module, "_sidecar_inbox_observation", _empty_sidecar_inbox)
    monkeypatch.setattr(
        module,
        "_readiness_args",
        lambda _module: SimpleNamespace(
            processor_container="ea-whatsapp-web-action-processor",
            session_api_base_url="http://127.0.0.1:8098",
            session_ref="test-wa-web",
            state_file="/data/whatsapp-actions/processed.json",
        ),
    )

    bundle = module.materialize_whatsapp_audiobook_operator_proof_bundle(output_path=tmp_path / "bundle.json")

    assert bundle["status"] == "waiting_for_live_epub"
    assert bundle["live_processor"]["execution_runtime"] == "container"
    assert bundle["live_processor"]["container_stdout_json_present"] is True
    assert bundle["runtime_alignment"]["state_file_match"] is True
    assert bundle["runtime_alignment"]["processor_state_file_kind"] == "whatsapp_actions_volume"
    assert bundle["runtime_alignment"]["readiness_state_file_kind"] == "whatsapp_actions_volume"
    assert bundle["runtime_alignment"]["session_ref_match"] is True
    assert bundle["runtime_alignment"]["session_api_host_kind_match"] is True
    assert bundle["runtime_alignment"]["session_api_host_kind_exact_match"] is False
    assert bundle["runtime_alignment"]["secret_values_exposed"] is False
    assert bundle["warnings"] == []


def test_whatsapp_audiobook_operator_proof_bundle_cli_no_live_readiness(tmp_path: Path) -> None:
    output_path = tmp_path / "wa-operator-bundle.generated.json"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "ea" / "scripts" / "materialize_whatsapp_audiobook_operator_proof_bundle.py"),
            "--output",
            str(output_path),
            "--no-live-readiness",
            "--no-live-processor",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode in {0, 1}
    payload = json.loads(result.stdout)
    assert payload["contract_name"] == "ea.whatsapp_audiobook_operator_proof_bundle.v1"
    assert output_path.is_file()


def test_run_processor_in_container_times_out_fail_closed(monkeypatch) -> None:
    module = _load_script("materialize_whatsapp_audiobook_operator_proof_bundle")
    observed: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        observed["cmd"] = list(args[0])
        observed["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(cmd=["docker", "exec"], timeout=3)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("EA_WHATSAPP_WEB_ACTION_PROCESSOR_CONTAINER_TIMEOUT_SECONDS", "3")

    report, meta = module._run_processor_in_container(SimpleNamespace(processor_container="ea-whatsapp-web-action-processor"))

    assert report["status"] == "failed"
    assert report["errors"] == 1
    assert report["reason"] == "processor_container_timeout"
    assert meta["attempted"] is True
    assert meta["timed_out"] is True
    assert meta["timeout_seconds"] == 3.0
    assert observed["timeout"] == 3.0
    assert observed["cmd"] == [
        "docker",
        "exec",
        "ea-whatsapp-web-action-processor",
        "python",
        "/app/scripts/process_whatsapp_web_session_actions.py",
        "--no-conversation-fallback-enabled",
        "--no-telegram-summary-enabled",
        "--no-audiobook-resume-due",
        "--no-audiobook-followup-enabled",
    ]
