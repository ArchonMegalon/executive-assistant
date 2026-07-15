from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script(script_name: str):
    module_name = f"test_{script_name.removesuffix('.py')}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "scripts" / script_name,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_refresh_packet_default_segments_follow_private_profile_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("prepare_memorial_unmixr_refresh_packet.py")
    monkeypatch.setattr(module, "private_profile_dir", lambda: tmp_path)

    segments = module.default_segment_paths("manfred")

    assert len(segments) == 3
    assert all(path.is_relative_to(tmp_path / "manfred") for path in segments)
    assert all(not path.is_absolute() for path in module.DEFAULT_SEGMENT_RELATIVE_PATHS)
    assert "/docker/" + "EA" not in "\n".join(module.DEFAULT_SEGMENTS)


def test_refresh_packet_rejects_unsafe_slug() -> None:
    module = _load_script("prepare_memorial_unmixr_refresh_packet.py")

    with pytest.raises(ValueError, match="^memorial_slug_invalid$"):
        module.default_segment_paths("../private")


def test_refresh_run_blocks_before_provider_call_when_segment_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("refresh_memorial_unmixr_clone.py")
    provider_called = False

    def unexpected_provider_call(**_kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(module._REFRESH_PACKET, "attempt_clone", unexpected_provider_call)
    missing = tmp_path / "not-present.wav"

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_label="Memorial Refresh",
        packet_output_dir=tmp_path / "packet",
        packet_output_path=tmp_path / "packet.json",
        compare_output_path=tmp_path / "compare.json",
        validation_output_dir=tmp_path / "validation",
        validation_output_path=tmp_path / "validation.json",
        apply_if_better=False,
        segment_paths=[missing],
    )

    assert result == {
        "slug": "manfred",
        "base_url": "http://127.0.0.1:8090",
        "status": "blocked",
        "code": "segment_missing",
        "missing_segment": "not-present.wav",
    }
    assert provider_called is False


def test_memorial_voice_operator_scripts_have_no_checkout_specific_defaults() -> None:
    rendered = "\n".join(
        (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for name in (
            "compare_memorial_ltd_voice_outputs.py",
            "prepare_memorial_unmixr_refresh_packet.py",
            "refresh_memorial_unmixr_clone.py",
        )
    )

    assert "/docker/" + "EA" not in rendered
    assert re.search(
        r"voice_id\s*=\s*['\"][0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}['\"]",
        rendered,
        flags=re.IGNORECASE,
    ) is None
