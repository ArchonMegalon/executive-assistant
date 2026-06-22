from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_audiobook_epub_quality_contract_passes() -> None:
    module = _load_script("verify_audiobook_epub_quality_contract")

    payload = module.verify_audiobook_epub_quality_contract()

    assert payload["contract_name"] == "ea.telegram_epub_audiobook_quality_contract.v1"
    assert payload["status"] == "pass"
    assert payload["issues"] == []
    checks = payload["checks"]
    assert checks["voice_audition_runtime_present"] is True
    assert checks["telegram_dismiss_immediate_replacement_present"] is True
    assert checks["author_gender_voice_signal_present"] is True
    assert checks["telegram_voice_sample_status_diagnostic_present"] is True
    assert checks["alice_blocklist_default_present"] is True
    assert checks["quiet_tail_quality_gates_present"] is True
    assert checks["publication_stt_required_by_default_present"] is True
    assert checks["paragraph_pause_rendering_present"] is True
    assert checks["audiobook_quality_env_surface_present"] is True
    assert checks["kindle_source_formats_present"] is True
    assert checks["voice_feedback_learning_present"] is True
    assert checks["m4b_chapters_and_cover_present"] is True
    assert checks["m4b_structure_probe_present"] is True
    assert checks["delayed_audiobookshelf_share_followup_present"] is True
    assert checks["live_telegram_audiobook_delivery_receipt_present"] is True
    assert checks["live_whatsapp_audiobook_delivery_receipt_present"] is True
    assert checks["local_whatsapp_audiobook_intake_proof_present"] is True
    assert checks["whatsapp_audiobook_operator_proof_bundle_present"] is True
    assert checks["whatsapp_live_voice_selection_shadow_present"] is True
    assert checks["whatsapp_public_share_playback_proof_present"] is True
    assert checks["whatsapp_web_action_processor_readiness_present"] is True
    assert checks["focused_tests_cover_m4b_structure_probe"] is True


def test_audiobook_epub_quality_contract_fails_when_sources_are_missing(tmp_path: Path) -> None:
    module = _load_script("verify_audiobook_epub_quality_contract")
    empty = tmp_path / "empty.txt"
    empty.write_text("placeholder\n", encoding="utf-8")
    module.AUDIOBOOK_PIPELINE_PATH = empty
    module.TELEGRAM_CHANNELS_PATH = empty
    module.AUDIOBOOK_TEST_PATH = empty
    module.AUDIOBOOK_LIVE_DELIVERY_TEST_PATH = empty
    module.WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_TEST_PATH = empty
    module.WHATSAPP_AUDIOBOOK_LOCAL_INTAKE_PROOF_TEST_PATH = empty
    module.WHATSAPP_AUDIOBOOK_OPERATOR_PROOF_BUNDLE_TEST_PATH = empty
    module.WHATSAPP_AUDIOBOOK_LIVE_VOICE_SELECTION_SHADOW_TEST_PATH = empty
    module.WHATSAPP_AUDIOBOOK_PUBLIC_SHARE_PLAYBACK_TEST_PATH = empty
    module.WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_TEST_PATH = empty
    module.AUDIOBOOK_SKILL_PATH = empty
    module.LTD_MAP_PATH = empty
    module.AUDIOBOOK_LIVE_DELIVERY_SCRIPT_PATH = empty
    module.WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_SCRIPT_PATH = empty
    module.WHATSAPP_AUDIOBOOK_LOCAL_INTAKE_PROOF_SCRIPT_PATH = empty
    module.WHATSAPP_AUDIOBOOK_OPERATOR_PROOF_BUNDLE_SCRIPT_PATH = empty
    module.WHATSAPP_AUDIOBOOK_LIVE_VOICE_SELECTION_SHADOW_SCRIPT_PATH = empty
    module.WHATSAPP_AUDIOBOOK_PUBLIC_SHARE_PLAYBACK_SCRIPT_PATH = empty
    module.WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_SCRIPT_PATH = empty
    module.ENV_EXAMPLE_PATH = empty
    module.ENV_LOCAL_EXAMPLE_PATH = empty
    module.DOCKER_COMPOSE_PATH = empty
    module.DOCKER_COMPOSE_WHATSAPP_PATH = empty

    payload = module.verify_audiobook_epub_quality_contract()

    assert payload["status"] == "fail"
    assert "voice_audition_runtime_present_missing" in payload["issues"]
    assert "telegram_inline_voice_controls_present_missing" in payload["issues"]
    assert "telegram_voice_sample_status_diagnostic_present_missing" in payload["issues"]
    assert "publication_stt_required_by_default_present_missing" in payload["issues"]
    assert "paragraph_pause_rendering_present_missing" in payload["issues"]
    assert "audiobook_quality_env_surface_present_missing" in payload["issues"]
    assert "kindle_source_formats_present_missing" in payload["issues"]
    assert "voice_feedback_learning_present_missing" in payload["issues"]
    assert "delayed_audiobookshelf_share_followup_present_missing" in payload["issues"]
    assert "live_telegram_audiobook_delivery_receipt_present_missing" in payload["issues"]
    assert "live_whatsapp_audiobook_delivery_receipt_present_missing" in payload["issues"]
    assert "local_whatsapp_audiobook_intake_proof_present_missing" in payload["issues"]
    assert "whatsapp_audiobook_operator_proof_bundle_present_missing" in payload["issues"]
    assert "whatsapp_live_voice_selection_shadow_present_missing" in payload["issues"]
    assert "whatsapp_public_share_playback_proof_present_missing" in payload["issues"]
    assert "whatsapp_web_action_processor_readiness_present_missing" in payload["issues"]
    assert "focused_tests_cover_audio_and_m4b_missing" in payload["issues"]


def test_audiobook_epub_quality_contract_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_audiobook_epub_quality_contract.py"),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verification = json.loads(verified.stdout)
    assert verification["status"] == "pass"

    output_path = tmp_path / "audiobook-quality.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_audiobook_epub_quality_contract.py"),
            "--out",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    result = json.loads(materialized.stdout)
    assert result["status"] == "pass"
    assert result["receipt_path"] == output_path.as_posix()
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
