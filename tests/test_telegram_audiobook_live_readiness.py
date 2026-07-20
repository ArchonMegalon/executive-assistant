from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


GENERATED_AT = "2026-06-19T22:45:00Z"


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configure_storage(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))


def _item_by_key(section: dict[str, object], key: str) -> dict[str, object]:
    for row in list(section.get("items") or []):
        if isinstance(row, dict) and row.get("key") == key:
            return row
    raise AssertionError(f"missing readiness item {key}")


def test_telegram_audiobook_live_readiness_next_action_names_exact_storage_blockers() -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")

    assert materializer._next_action(
        ["jobs_root_durable", "jobs_root_writable"],
        [
            "audiobookshelf_import_root_durable",
            "audiobookshelf_import_root_writable",
        ],
    ) == (
        "Configure durable, writable audiobook job and Audiobookshelf import "
        "storage, then rerun readiness."
    )
    assert materializer._next_action(
        ["jobs_root_writable"],
        [],
    ) == "Configure durable, writable audiobook job storage and rerun readiness."
    assert materializer._next_action(
        [],
        ["audiobookshelf_import_root_writable"],
    ) == "Configure durable, writable Audiobookshelf import storage and rerun readiness."
    assert materializer._next_action(
        [],
        ["player_access_signing_secret_present"],
    ) == "Configure player-scoped audiobook link prerequisites and rerun readiness."


def test_telegram_audiobook_live_readiness_blocks_missing_live_sample_prereqs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")
    verifier = _load_script("verify_telegram_audiobook_live_readiness")
    _configure_storage(monkeypatch, tmp_path)
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.delenv("UNMIXR_API_KEY", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    receipt_path = tmp_path / "live-readiness.generated.json"

    receipt = materializer.materialize_telegram_audiobook_live_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "blocked_live_prerequisites"
    assert receipt["voice_sample_prereqs_ready"] is False
    assert receipt["can_run_live_epub_delivery_test"] is False
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert "external_tts_enabled" in receipt["sample_blockers"]
    assert "unmixr_auto_render_enabled" in receipt["sample_blockers"]
    assert "voice_catalog_configured" in receipt["sample_blockers"]
    assert "unmixr_api_key_slot_present" in receipt["sample_blockers"]
    assert "audiobookshelf_public_share_enabled" in receipt["delivery_blockers"]
    assert "audiobookshelf_public_share_configured" in receipt["delivery_blockers"]
    assert receipt["voice_samples"]["api_key_slot_count"] == 0
    assert all(row["env_values_exposed"] is False for row in receipt["voice_samples"]["items"])
    catalog_env_vars = set(_item_by_key(receipt["voice_samples"], "voice_catalog_configured")["env_var_names"])
    audition_env_vars = set(_item_by_key(receipt["voice_samples"], "voice_catalog_audition_ready")["env_var_names"])
    assert "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED" in catalog_env_vars
    assert "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES" in catalog_env_vars
    assert "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED" in audition_env_vars
    assert "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_TARGET_COUNT" in audition_env_vars
    assert "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES" in audition_env_vars

    verification = verifier.verify_telegram_audiobook_live_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_telegram_audiobook_live_readiness_can_be_ready_without_overclaiming_delivery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")
    verifier = _load_script("verify_telegram_audiobook_live_readiness")
    _configure_storage(monkeypatch, tmp_path)
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("UNMIXR_API_KEY", "fake-unmixr-key")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_BASE_URL", "https://abs.internal")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL", "https://abs.example.com")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_TOKEN", "fake-abs-token")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_LIBRARY_ID", "library-1")
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "fake-signing-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", "https://ea.example.com")
    receipt_path = tmp_path / "ready-live-readiness.generated.json"

    receipt = materializer.materialize_telegram_audiobook_live_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "ready_for_live_epub_delivery_test"
    assert receipt["voice_sample_prereqs_ready"] is True
    assert receipt["public_share_delivery_prereqs_ready"] is True
    assert receipt["can_run_live_epub_delivery_test"] is True
    assert receipt["sample_blockers"] == []
    assert receipt["delivery_blockers"] == []
    assert receipt["voice_samples"]["voice_catalog_count"] == 3
    assert receipt["voice_samples"]["api_key_slot_count"] == 1
    assert receipt["delivery"]["audiobookshelf_public_share_configured"] is True
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert "separate human playback acceptance captured" in receipt["required_live_proof_after_readiness"]

    serialized = json.dumps(receipt)
    assert "fake-unmixr-key" not in serialized
    assert "fake-abs-token" not in serialized
    assert "fake-signing-secret" not in serialized
    assert str(tmp_path) not in serialized

    verification = verifier.verify_telegram_audiobook_live_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_telegram_audiobook_live_readiness_can_use_runtime_container_preflight(tmp_path: Path) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")
    verifier = _load_script("verify_telegram_audiobook_live_readiness")
    receipt_path = tmp_path / "container-live-readiness.generated.json"
    runtime_preflight = {
        "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
        "status": "warn",
        "checks": [
            {"key": "telegram_epub_enabled", "status": "pass"},
            {"key": "jobs_root_durable", "status": "pass"},
            {"key": "jobs_root_writable", "status": "pass"},
            {"key": "external_tts_enabled", "status": "pass"},
            {"key": "unmixr_auto_render_enabled", "status": "pass"},
            {"key": "voice_catalog_configured", "status": "pass"},
            {"key": "voice_catalog_audition_ready", "status": "pass"},
            {"key": "m4b_assembly_available", "status": "pass"},
            {"key": "audiobookshelf_import_root_durable", "status": "pass"},
            {"key": "audiobookshelf_import_root_writable", "status": "pass"},
            {"key": "audiobookshelf_public_share_configured", "status": "pass"},
            {"key": "player_access_signing_secret_present", "status": "pass"},
            {"key": "player_access_base_url_present", "status": "warn"},
            {"key": "scheduler_resume_enabled", "status": "pass"},
        ],
        "failed_checks": [],
        "warned_checks": ["player_access_base_url_present"],
        "provider": {
            "api_key_slot_count": 3,
            "voice_catalog_count": 30,
            "voice_discovery_enabled": True,
            "voice_discovery_target_count": 30,
            "voice_audition_min_candidates": 3,
            "provider_secrets_exposed": False,
            "raw_voice_ids_exposed": False,
        },
        "access": {
            "audiobookshelf_auto_import_enabled": True,
            "audiobookshelf_public_share_enabled": True,
            "audiobookshelf_public_share_configured": True,
            "player_access_signing_secret_present": True,
            "player_access_base_url_present": False,
            "tokens_exposed": False,
        },
        "assembly": {"m4b_assembly_available": True},
        "scheduler": {"resume_enabled": True},
    }

    def fake_runner(command, **kwargs):
        assert "docker" in command[0]
        return SimpleNamespace(returncode=0, stdout=json.dumps(runtime_preflight), stderr="")

    receipt = materializer.materialize_telegram_audiobook_live_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        runtime_container="ea-api",
        runner=fake_runner,
    )

    assert receipt["observation_source"] == "runtime_container"
    assert receipt["runtime_container"] == "ea-api"
    assert receipt["status"] == "ready_for_live_epub_delivery_test"
    assert receipt["preflight_status"] == "warn"
    assert receipt["preflight_warned_checks"] == ["player_access_base_url_present"]
    assert receipt["voice_sample_prereqs_ready"] is True
    assert receipt["public_share_delivery_prereqs_ready"] is True
    assert receipt["can_run_live_epub_delivery_test"] is True
    assert receipt["delivery_blockers"] == []
    assert _item_by_key(receipt["delivery"], "player_access_base_url_present")["status"] == "ready"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["voice_samples"]["api_key_slot_count"] == 3
    assert receipt["voice_samples"]["voice_catalog_count"] == 30
    assert receipt["privacy"]["env_values_exposed"] is False

    verification = verifier.verify_telegram_audiobook_live_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_telegram_audiobook_live_readiness_cli_defaults_to_runtime_container(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")
    receipt_path = tmp_path / "default-runtime.generated.json"
    captured: dict[str, object] = {}

    def fake_materialize(**kwargs):
        captured.update(kwargs)
        return {"status": "ready_for_live_epub_delivery_test"}

    monkeypatch.setattr(
        materializer,
        "materialize_telegram_audiobook_live_readiness",
        fake_materialize,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_telegram_audiobook_live_readiness.py",
            "--receipt",
            str(receipt_path),
        ],
    )

    assert materializer.main() == 0
    assert captured["runtime_container"] == "ea-api"
    assert json.loads(capsys.readouterr().out)["status"] == "ready_for_live_epub_delivery_test"


def test_telegram_audiobook_live_readiness_verifier_rejects_overclaims(tmp_path: Path) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")
    verifier = _load_script("verify_telegram_audiobook_live_readiness")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_telegram_audiobook_live_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        preflight={
            "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
            "status": "fail",
            "checks": [{"key": "external_tts_enabled", "status": "fail"}],
            "failed_checks": ["external_tts_enabled"],
            "warned_checks": [],
            "provider": {"api_key_slot_count": 0, "voice_catalog_count": 0, "voice_audition_min_candidates": 3},
            "access": {},
            "assembly": {},
            "scheduler": {},
        },
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["live_delivery_claim_allowed"] = True
    receipt["privacy"]["env_values_exposed"] = True
    receipt["required_live_proof_after_readiness"] = []
    catalog_item = _item_by_key(receipt["voice_samples"], "voice_catalog_configured")
    catalog_item["env_var_names"] = ["EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON"]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_telegram_audiobook_live_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "live_readiness_delivery_claim_overclaim" in verification["issues"]
    assert "live_readiness_privacy_flag_not_false:env_values_exposed" in verification["issues"]
    assert "live_readiness_required_live_proof_incomplete" in verification["issues"]
    assert "live_readiness_discovery_env_vars_missing:voice_catalog_configured" in verification["issues"]


def test_telegram_audiobook_live_readiness_verifier_checks_deployed_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")
    verifier = _load_script("verify_telegram_audiobook_live_readiness")
    _configure_storage(monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.generated.json"
    materializer.materialize_telegram_audiobook_live_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
    )

    def fake_runner(command, **kwargs):
        command_text = " ".join(str(part) for part in command)
        if "channels.py" in command_text:
            return SimpleNamespace(
                returncode=0,
                stdout="_telegram_audiobook_voice_sample_subset replacement audiobook voice",
                stderr="",
            )
        if "audiobook_epub_pipeline.py" in command_text:
            return SimpleNamespace(
                returncode=0,
                stdout="refill_pending replacement_candidate_keys author_gender_signal",
                stderr="",
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    verification = verifier.verify_telegram_audiobook_live_readiness(
        receipt_path,
        runtime_container="ea-api",
        require_deployed_runtime=True,
        runner=fake_runner,
    )

    assert verification["status"] == "pass"
    assert verification["issues"] == []
    assert verification["deployed_runtime"]["status"] == "pass"


def test_telegram_audiobook_live_readiness_verifier_rejects_old_deployed_dismiss_workflow(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_readiness")
    verifier = _load_script("verify_telegram_audiobook_live_readiness")
    _configure_storage(monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-old.generated.json"
    materializer.materialize_telegram_audiobook_live_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
    )

    def fake_runner(command, **kwargs):
        command_text = " ".join(str(part) for part in command)
        if "channels.py" in command_text:
            return SimpleNamespace(
                returncode=0,
                stdout="dismiss the rest get the next batch",
                stderr="",
            )
        if "audiobook_epub_pipeline.py" in command_text:
            return SimpleNamespace(
                returncode=0,
                stdout="replacement_candidate_keys",
                stderr="",
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    verification = verifier.verify_telegram_audiobook_live_readiness(
        receipt_path,
        runtime_container="ea-api",
        require_deployed_runtime=True,
        runner=fake_runner,
    )

    assert verification["status"] == "fail"
    assert "deployed_runtime_old_audiobook_dismiss_workflow_present:telegram_channels" in verification["issues"]
    assert "deployed_runtime_immediate_replacement_missing:telegram_channels" in verification["issues"]
    assert "deployed_runtime_immediate_replacement_missing:audiobook_pipeline" in verification["issues"]


def test_telegram_audiobook_live_readiness_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-live-readiness.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_telegram_audiobook_live_readiness.py"),
            "--receipt",
            str(receipt_path),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    assert receipt_path.is_file()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_telegram_audiobook_live_readiness.py"),
            "--receipt",
            str(receipt_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )

    assert verified.returncode == 0, verified.stderr + verified.stdout
    assert json.loads(verified.stdout)["status"] == "pass"
