from __future__ import annotations

import json
from pathlib import Path


def _voice_receipt(*, base_url: str = "https://memorial.example.test", slow: bool = False) -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
        "git_head": "HEAD",
        "source_git_head": "HEAD",
        "source_tree_fingerprint": "unit-source-tree",
        "dirty_worktree": False,
        "status": "pass",
        "base_url": base_url,
        "gold_mode": True,
        "require_public_origin": True,
        "gold_claim_allowed": True,
        "failed_codes": [],
        "warned_codes": [],
        "metrics": {
            "direct_tts_f1": 1.0,
            "conversation_turn_audio_f1": 1.0,
            "conversation_turn_total_ms": 7000 if slow else 1200,
            "speech_transcribe_ms": 4000 if slow else 700,
        },
        "checks": [{"status": "pass", "code": "present_world_route_ok"}],
    }


def _browser_receipt(*, base_url: str = "https://memorial.example.test", mode: str = "live") -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_realtime_browser_exit_gate",
        "git_head": "HEAD",
        "source_git_head": "HEAD",
        "source_tree_fingerprint": "unit-source-tree",
        "dirty_worktree": False,
        "status": "pass",
        "base_url": base_url,
        "gold_mode": True,
        "require_public_origin": True,
        "gold_claim_allowed": True,
        "speech_transcribe_mode": mode,
        "failed_codes": [],
        "first_answer_ms": 1200,
        "audio_ready_for_ui": True,
        "answer_text_visible": True,
        "ui_audio_play_calls": 1,
        "ui_audio_play_ended": 1,
        "answer_semantic_passed": True,
    }


def _room_receipt(*, base_url: str = "https://memorial.example.test") -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_room_audio_public_origin",
        "git_head": "HEAD",
        "source_git_head": "HEAD",
        "source_tree_fingerprint": "unit-source-tree",
        "dirty_worktree": False,
        "status": "pass",
        "base_url": base_url,
        "require_public_origin": True,
        "reviewer": "unit reviewer",
        "checks": {
            "actual_device_checked": True,
            "actual_speaker_checked": True,
            "first_syllable_not_clipped": True,
            "intelligibility_confirmed": True,
            "answer_text_fallback_visible": True,
            "no_internet_search_confirmed": True,
        },
    }


def test_memorial_gold_readiness_requires_public_browser_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


def test_memorial_gold_readiness_passes_with_public_voice_and_browser_receipts(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 0


def test_memorial_gold_readiness_blocks_slow_public_voice_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt(slow=True)), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


def test_memorial_gold_readiness_blocks_browser_stub_stt_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt(mode="transcript_injected")), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


def test_memorial_gold_readiness_requires_room_audio_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


def test_memorial_gold_readiness_uses_source_git_head_before_receipt_commit_head(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local = _voice_receipt(base_url="http://127.0.0.1:8090")
    public = _voice_receipt()
    browser = _browser_receipt()
    room = _room_receipt()
    for payload in (local, public, browser, room):
        payload["git_head"] = "RECEIPT_COMMIT"
        payload["source_git_head"] = "SOURCE_HEAD"
    local_path.write_text(json.dumps(local), encoding="utf-8")
    public_path.write_text(json.dumps(public), encoding="utf-8")
    browser_path.write_text(json.dumps(browser), encoding="utf-8")
    room_path.write_text(json.dumps(room), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "SOURCE_HEAD")

    assert readiness.main() == 0
