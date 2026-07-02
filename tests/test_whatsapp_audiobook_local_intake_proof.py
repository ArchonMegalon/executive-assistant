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


def test_whatsapp_audiobook_local_intake_proof_passes_and_is_sanitized(tmp_path: Path) -> None:
    module = _load_script("materialize_whatsapp_audiobook_local_intake_proof")

    output_path = tmp_path / "wa-local-proof.generated.json"
    proof = module.materialize_whatsapp_audiobook_local_intake_proof(output_path=output_path)

    assert proof["contract_name"] == "ea.whatsapp_audiobook_local_epub_intake_proof.v1"
    assert proof["status"] == "pass"
    assert output_path.is_file()
    assert all(proof["checks"].values())
    assert proof["processor_report"]["intake"]["epub_processed"] == 1
    assert proof["processor_report"]["intake"]["voice_sample_sent"] == 3
    assert proof["processor_report"]["voice_selection"]["processed"] == 1
    assert proof["processor_report"]["voice_selection"]["share_link_sent"] == 1
    assert proof["intake_summary"]["status"] == "waiting_voice_selection"
    assert proof["intake_summary"]["pending_voice_sample_count"] == 3
    assert proof["job_summary"]["status"] == "audiobookshelf_imported"
    assert proof["job_summary"]["voice_selection_status"] == "selected_by_user"
    assert proof["job_summary"]["render_status"] == "rendered"
    assert proof["job_summary"]["m4b_status"] == "m4b_ready"
    assert proof["job_summary"]["audiobookshelf_import_status"] == "imported"
    assert proof["job_summary"]["public_share_status"] == "public_share_ready"
    assert proof["job_summary"]["pending_voice_sample_count"] == 0
    assert proof["sanitized_receipt_summary"]["m4b_output_ready"] is True
    assert proof["sanitized_receipt_summary"]["chapter_metadata_embedded"] is True
    assert proof["sanitized_receipt_summary"]["player_scoped_reference_status"] == "signed_reference_ready"
    assert proof["player_probe_summary"]["status"] == "pass"
    assert proof["player_probe_summary"]["metadata_status"] == "ready"
    assert proof["player_probe_summary"]["content_type"] == "audio/mp4"
    assert proof["player_probe_summary"]["file_ready"] is True
    assert proof["player_probe_summary"]["file_sha256"]
    assert proof["player_probe_summary"]["audio_streams"] >= 1
    assert proof["player_probe_summary"]["duration_seconds"] > 0
    assert proof["player_probe_summary"]["raw_path_exposed"] is False
    assert proof["player_probe_summary"]["raw_token_exposed"] is False
    assert proof["player_http_probe_summary"]["status"] == "pass"
    assert proof["player_http_probe_summary"]["metadata_status_code"] == 200
    assert proof["player_http_probe_summary"]["metadata_status"] == "ready"
    assert proof["player_http_probe_summary"]["metadata_cache_control"] == "no-store"
    assert proof["player_http_probe_summary"]["metadata_download_url_present"] is True
    assert proof["player_http_probe_summary"]["metadata_vendor_token_exposed"] is False
    assert proof["player_http_probe_summary"]["metadata_raw_library_path_exposed"] is False
    assert proof["player_http_probe_summary"]["download_status_code"] == 200
    assert proof["player_http_probe_summary"]["download_content_type"].startswith("audio/mp4")
    assert proof["player_http_probe_summary"]["download_cache_control"] == "no-store"
    assert proof["player_http_probe_summary"]["download_bytes"] > 0
    assert proof["player_http_probe_summary"]["raw_path_exposed"] is False
    assert proof["player_http_probe_summary"]["raw_token_exposed"] is False
    assert proof["sanitized_receipt_summary"]["public_share_status"] == "public_share_ready"
    assert proof["sanitized_receipt_summary"]["public_share_whatsapp_delivery_status"] == "sent"
    assert proof["sanitized_receipt_summary"]["public_share_whatsapp_message_id_present"] is True
    assert proof["sanitized_receipt_summary"]["whatsapp_sender_bound"] is True
    assert proof["sanitized_receipt_summary"]["whatsapp_session_bound"] is True
    assert proof["sanitized_receipt_summary"]["whatsapp_message_hash_present"] is True
    assert proof["local_stage_receipt_summary"]["intake"]["next_action"] == "choose_whatsapp_audiobook_voice_sample"
    assert proof["local_stage_receipt_summary"]["intake"]["stage_counts"] == {"waiting_voice_choice": 1}
    assert (
        proof["local_stage_receipt_summary"]["delivery"]["next_action"]
        == "run_public_share_machine_playback_e2e_before_claiming_live_delivery"
    )
    assert proof["local_stage_receipt_summary"]["delivery"]["stage_counts"] == {
        "waiting_machine_playback_verification": 1
    }
    rendered = json.dumps(proof, sort_keys=True)
    assert "4368120864006" not in rendered
    assert "wamid.local-proof" not in rendered
    assert "local-proof-callback-secret" not in rendered
    assert "local-proof-access-secret" not in rendered
    assert "/internal/audiobooks/player/" not in rendered
    assert "ea-local-proof.invalid" not in rendered
    assert "ea.whatsapp_audiobook_local_epub_intake_proof" in rendered
    assert "ab|u|" not in rendered
    assert "ap|a|" not in rendered
    assert "voice-clear" not in rendered
    assert "voice-warm" not in rendered
    assert "voice-story" not in rendered


def test_whatsapp_audiobook_local_intake_proof_cli_require_pass(tmp_path: Path) -> None:
    output_path = tmp_path / "wa-local-proof-cli.generated.json"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "ea" / "scripts" / "materialize_whatsapp_audiobook_local_intake_proof.py"),
            "--output",
            str(output_path),
            "--require-pass",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    proof = json.loads(output_path.read_text(encoding="utf-8"))
    assert proof["status"] == "pass"
    assert json.loads(result.stdout)["receipt_path"] == output_path.as_posix()
