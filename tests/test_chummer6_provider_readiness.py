from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_provider_readiness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_provider_readiness", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_text_provider_state_requires_registered_chummer6_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(
        readiness,
        "provider_state",
        lambda name: {
            "provider": name,
            "status": "ready",
            "available": True,
        }
        if name == "gemini_vortex"
        else readiness.provider_state(name),
    )
    monkeypatch.setattr(
        readiness,
        "chummer6_skill_catalog_state",
        lambda: {
            "status": "missing",
            "required_skill_keys": ["chummer6_public_writer"],
            "registered_skill_keys": [],
            "missing_skill_keys": ["chummer6_public_writer"],
            "upserted_skill_keys": [],
        },
    )

    state = readiness.text_provider_state("ea")

    assert state["available"] is False
    assert state["status"] == "not_ready"
    assert "missing required Chummer6 skill registrations" in state["detail"]
    assert state["skill_catalog"]["missing_skill_keys"] == ["chummer6_public_writer"]


def test_text_provider_state_reports_auto_registered_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(
        readiness,
        "provider_state",
        lambda name: {
            "provider": name,
            "status": "ready",
            "available": True,
        }
        if name == "gemini_vortex"
        else readiness.provider_state(name),
    )
    monkeypatch.setattr(
        readiness,
        "chummer6_skill_catalog_state",
        lambda: {
            "status": "ready",
            "required_skill_keys": ["chummer6_public_writer"],
            "registered_skill_keys": ["chummer6_public_writer"],
            "missing_skill_keys": [],
            "upserted_skill_keys": ["chummer6_public_writer"],
        },
    )

    state = readiness.text_provider_state("ea")

    assert state["available"] is True
    assert state["status"] == "ready"
    assert "auto-registered locally" in state["detail"]
    assert state["skill_catalog"]["upserted_skill_keys"] == ["chummer6_public_writer"]
