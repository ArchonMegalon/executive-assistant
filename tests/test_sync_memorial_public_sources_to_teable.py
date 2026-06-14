from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path("/docker/EA/scripts/sync_memorial_public_sources_to_teable.py")
    spec = importlib.util.spec_from_file_location("sync_memorial_public_sources_to_teable", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_configured_base_url_prefers_env(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("TEABLE_BASE_URL", "https://teable.example")
    assert module._configured_base_url() == "https://teable.example"
