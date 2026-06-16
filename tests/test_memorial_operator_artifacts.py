from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module(path_str: str, name: str):
    path = Path(path_str)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_memorial_phrase_bank_materializer_writes_expected_ids(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_phrase_bank.py", "materialize_memorial_phrase_bank")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "phrase_bank.json")
    assert module.main() == 0
    payload = __import__("json").loads((tmp_path / "phrase_bank.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in payload["phrases"]}
    assert {"contact_opening", "present_world_guardrail", "weather_guardrail"} <= ids


def test_memorial_operator_status_materializer_summarizes_blocked_public_gold(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "MEANINGFUL_BROWSER_RECEIPT", tmp_path / "meaningful-browser.json")
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "not_gold",
                "gold_claim_allowed": False,
                "blocking_planes": ["memorial_public_origin_gold"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "memorial_voice_gold_claim_allowed": False,
                "local_release_issues": [],
                "public_gold_issues": ["receipt_missing_or_invalid"],
                "public_browser_gold_issues": ["browser_receipt_missing_or_invalid"],
                "room_audio_issues": ["room_receipt_missing_or_invalid"],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "blocked"}
        ),
    )
    assert module.main() == 0
    payload = __import__("json").loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["current_label"] == "Memorial public-origin gold: blocked"
    assert payload["local_release_candidate"] == "pass"
    assert payload["public_voice_receipt"] == "missing_or_blocked"
    assert payload["public_browser_meaningful_receipt"] == "missing_or_blocked"
    assert payload["whole_project_gold"] == "blocked"
    assert payload["whole_project_map_summary"]["blocking_planes"] == ["memorial_public_origin_gold"]


def test_memorial_operator_status_run_json_reads_blocked_json_from_stderr(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_stderr")

    class _Proc:
        stdout = ""
        stderr = '{"status":"blocked","issues":["stale_receipt"]}'

    calls: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        calls["cwd"] = kwargs.get("cwd")
        return _Proc()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    payload = module._run_json("scripts/verify_whole_project_gold_map.py")
    assert payload["status"] == "blocked"
    assert calls["cwd"] == module.ROOT


def test_memorial_operator_status_marks_whole_project_gold_pass_only_when_map_allows_it(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_gold_pass")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    meaningful_receipt = tmp_path / "meaningful-browser.json"
    meaningful_receipt.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    monkeypatch.setattr(module, "MEANINGFUL_BROWSER_RECEIPT", meaningful_receipt)
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "gold",
                "gold_claim_allowed": True,
                "blocking_planes": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )
    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["whole_project_gold"] == "pass"
    assert payload["public_browser_meaningful_receipt"] == "pass"
    assert payload["status"] == "pass"
    assert payload["artifact_paths"]["public_gold_receipt"] == ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
    assert payload["workflow_backing"]["status"] == "no"
    assert payload["public_voice_receipt_semantics"]["label"] in {
        "Memorial public voice provenance proof",
        "Memorial public voice gold proof",
    }


def test_memorial_operator_status_reads_public_voice_transcriber_mode_from_metrics(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_metrics_semantics",
    )
    receipt = tmp_path / "public-voice.json"
    receipt.write_text(
        json.dumps(
            {
                "metrics": {
                    "direct_tts_transcriber": "memorial_tts_provenance_cache",
                    "conversation_turn_transcriber": "memorial_tts_provenance_cache",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PUBLIC_VOICE_RECEIPT", receipt)

    payload = module._public_voice_receipt_semantics()
    assert payload["label"] == "Memorial public voice provenance proof"
    assert payload["transcriber_mode"] == "provenance_cache"
    assert payload["direct_tts_transcriber"] == "memorial_tts_provenance_cache"
    assert payload["conversation_turn_transcriber"] == "memorial_tts_provenance_cache"


def test_memorial_operator_status_keeps_memorial_pass_when_unrelated_whole_project_gold_is_disallowed(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_whole_project_blocked")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "not_gold",
                "gold_claim_allowed": False,
                "blocking_planes": ["chummer_desktop_ui"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["current_label"] == "Memorial public-origin gold: pass"
    assert payload["whole_project_gold"] == "blocked"
    assert payload["status"] == "pass"


def test_memorial_operator_status_fails_closed_when_whole_project_verifier_blocks(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_verifier_blocked")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "gold",
                "gold_claim_allowed": True,
                "blocking_planes": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "status": "pass",
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "blocked", "issues": ["whole-project gold map is stale relative to current HEAD"]}
        ),
    )

    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["whole_project_gold"] == "blocked"
    assert payload["current_label"] == "Memorial public-origin gold: pass"
    assert payload["status"] == "pass"


def test_memorial_operator_status_uses_source_state_head(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_source_head")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "status": "pass",
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["source_git_head"] == "SOURCE_HEAD"


def test_memorial_room_audio_clean_materializer_builds_expected_receipt_command() -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_room_audio_receipt_clean.py", "materialize_memorial_room_audio_receipt_clean")

    class _Args:
        python_bin = "python3"
        base_url = "https://example.com"
        slug = "manfred"
        reviewer = "reviewer"
        device_label = "laptop"
        speaker_label = "speaker"
        room_label = "office"
        notes = "ok"

    cmd = module.build_room_receipt_command(_Args())
    assert cmd[:2] == ["python3", "scripts/materialize_memorial_room_audio_receipt.py"]
    assert "--base-url" in cmd
    assert "https://example.com" in cmd
    assert "--reviewer" in cmd
    assert "reviewer" in cmd
    assert "--require-public-origin" in cmd
    assert "--first-syllable-not-clipped" in cmd


def test_memorial_room_audio_clean_materializer_copies_expected_artifacts(tmp_path) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_room_audio_receipt_clean.py", "materialize_memorial_room_audio_receipt_clean_copy")
    clean_root = tmp_path / "clean"
    dest_root = tmp_path / "dest"
    for relpath in module.SYNC_ARTIFACTS:
        path = clean_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    copied = module._copy_artifacts_from_clean_clone(clean_root, dest_root)

    assert set(copied) == {path.as_posix() for path in module.SYNC_ARTIFACTS}
    for relpath in module.SYNC_ARTIFACTS:
        assert (dest_root / relpath).read_text(encoding="utf-8") == "{}"


def test_memorial_public_gold_clean_materializer_builds_expected_commands() -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_public_gold_clean.py", "materialize_memorial_public_gold_clean")

    class _Args:
        python_bin = "python3"
        base_url = "https://example.com"
        slug = "manfred"
        reviewer = "reviewer"
        device_label = "laptop"
        speaker_label = "speaker"
        room_label = "office"
        notes = "ok"
        direct_min_f1 = 0.92
        conversation_min_f1 = 0.90
        browser_first_answer_ms = 4500.0
        meaningful_browser_first_answer_ms = 8000.0
        meaningful_prompt = "Was war dir bei Gerechtigkeit wichtig?"

    local_voice = module.build_local_voice_receipt_command(_Args())
    voice = module.build_voice_receipt_command(_Args())
    browser = module.build_browser_receipt_command(_Args())
    meaningful = module.build_meaningful_browser_receipt_command(_Args())
    room = module.build_room_receipt_command(_Args())

    assert local_voice[:2] == ["python3", "scripts/materialize_memorial_voice_roundtrip_exit_gate.py"]
    assert ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json" in local_voice
    assert voice[:2] == ["python3", "scripts/materialize_memorial_voice_roundtrip_exit_gate.py"]
    assert "--gold-mode" in voice
    assert "--require-public-origin" in voice
    assert "https://example.com" in voice
    assert browser[:2] == ["python3", "scripts/measure_memorial_live_browser.py"]
    assert "--real-stt" in browser
    assert "--max-first-answer-ms" in browser
    assert meaningful[:2] == ["python3", "scripts/measure_memorial_live_browser.py"]
    assert "--text-prompt" in meaningful
    assert "Was war dir bei Gerechtigkeit wichtig?" in meaningful
    assert room[:2] == ["python3", "scripts/materialize_memorial_room_audio_receipt.py"]
    assert "--reviewer" in room
    assert "reviewer" in room


def test_memorial_public_gold_clean_materializer_copies_expected_artifacts(tmp_path) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_public_gold_clean.py", "materialize_memorial_public_gold_clean_copy")
    clean_root = tmp_path / "clean"
    dest_root = tmp_path / "dest"
    for relpath in module.SYNC_ARTIFACTS:
        path = clean_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    copied = module._copy_artifacts_from_clean_clone(clean_root, dest_root)

    assert set(copied) == {path.as_posix() for path in module.SYNC_ARTIFACTS}
    for relpath in module.SYNC_ARTIFACTS:
        assert (dest_root / relpath).read_text(encoding="utf-8") == "{}"


def test_memorial_receipt_materializers_use_source_state_head(monkeypatch) -> None:
    voice = _load_module(
        "/docker/EA/scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "materialize_memorial_voice_roundtrip_exit_gate_source_head",
    )
    browser = _load_module(
        "/docker/EA/scripts/measure_memorial_live_browser.py",
        "measure_memorial_live_browser_source_head",
    )
    room = _load_module(
        "/docker/EA/scripts/materialize_memorial_room_audio_receipt.py",
        "materialize_memorial_room_audio_receipt_source_head",
    )

    monkeypatch.setattr(voice, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(browser, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(room, "resolve_source_state_head", lambda root: "SOURCE_HEAD")

    assert voice._git_head() == "SOURCE_HEAD"
    assert browser._git_head() == "SOURCE_HEAD"
    assert room._git_head() == "SOURCE_HEAD"
