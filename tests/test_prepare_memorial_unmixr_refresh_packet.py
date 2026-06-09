from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path("/docker/EA/ea/scripts/prepare_memorial_unmixr_refresh_packet.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("prepare_memorial_unmixr_refresh_packet", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_build_packet_lists_segments(tmp_path: Path) -> None:
    module = _load_module()
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    packet = module.build_packet(
        slug="manfred",
        voice_label="Manfred Hoza Memorial Refresh",
        segment_paths=[a, b],
        output_dir=tmp_path / "out",
    )

    assert packet["slug"] == "manfred"
    assert len(packet["segments"]) == 2
    assert packet["segments"][0]["filename"] == "a.wav"


def test_attempt_clone_reports_blocker(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    a = tmp_path / "a.wav"
    a.write_bytes(b"a")

    monkeypatch.setattr(module, "_load_unmixr_key_from_live_env", lambda: "token")

    class _Exc(Exception):
        pass

    from fastapi import HTTPException

    monkeypatch.setattr(
        module,
        "unmixr_clone_request",
        lambda **kwargs: (_ for _ in ()).throw(HTTPException(status_code=502, detail="You've reached the limit.:402")),
    )

    result = module.attempt_clone(
        slug="manfred",
        voice_label="Manfred Hoza Memorial Refresh",
        segment_paths=[a],
    )

    assert result["status"] == "blocked"
    assert result["code"] == "unmixr_clone_blocked"
    assert "limit" in result["detail"].lower()
