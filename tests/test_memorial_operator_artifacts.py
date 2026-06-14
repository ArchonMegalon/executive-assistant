from __future__ import annotations

import importlib.util
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
