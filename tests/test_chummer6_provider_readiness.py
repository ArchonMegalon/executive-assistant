from __future__ import annotations

import importlib.util
import json
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


def test_browseract_prompting_systems_explicit_workflow_is_configured_but_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(
        readiness,
        "key_names_present",
        lambda names: [name for name in names if name.startswith("BROWSERACT")],
    )
    monkeypatch.setattr(
        readiness,
        "env_value",
        lambda name: "wf-123"
        if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID"
        else "",
    )

    state = readiness.provider_state("browseract_prompting_systems")

    assert state["available"] is True
    assert state["status"] == "workflow_configured"
    assert "not health-verified" in state["detail"]


def test_provider_summary_prefers_ready_provider_over_query_only_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(
        readiness,
        "provider_order",
        lambda: ["browseract_magixai", "media_factory"],
    )
    monkeypatch.setattr(
        readiness,
        "provider_state",
        lambda name: {
            "provider": "browseract_magixai",
            "status": "workflow_query_only",
            "available": True,
        }
        if name == "browseract_magixai"
        else {
            "provider": "media_factory",
            "status": "ready",
            "available": True,
        },
    )
    monkeypatch.setattr(
        readiness,
        "text_provider_order",
        lambda: ["ea"],
    )
    monkeypatch.setattr(
        readiness,
        "text_provider_state",
        lambda name: {
            "provider": name,
            "status": "ready",
            "available": True,
        },
    )

    rows = [readiness.provider_state(name) for name in readiness.provider_order()]
    summary = {
        "recommended_provider": next(
            (row["provider"] for row in rows if row["status"] in readiness.PREFERRED_PROVIDER_STATUSES),
            next((row["provider"] for row in rows if row["available"]), ""),
        )
    }

    assert summary["recommended_provider"] == "media_factory"


def test_media_factory_state_uses_resolved_onemin_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(readiness, "key_names_present", lambda names: [])
    monkeypatch.setattr(
        readiness,
        "resolved_onemin_slots",
        lambda: [{"env_name": "ONEMIN_RESOLVED_SLOT_1", "key": "resolved-key"}],
    )
    monkeypatch.setattr(readiness, "command_state", lambda command_name: ("python3", True))
    monkeypatch.setattr(readiness, "env_value", lambda name: "")

    state = readiness.provider_state("media_factory")

    assert state["available"] is True
    assert state["status"] == "ready"
    assert state["resolved_slot_count"] == 1


def test_provider_summary_writes_overlay_vision_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    readiness = _load_module()
    monkeypatch.setattr(readiness, "STATE_OUT", tmp_path / "provider-readiness.json")
    monkeypatch.setattr(readiness, "provider_order", lambda: ["media_factory"])
    monkeypatch.setattr(
        readiness,
        "provider_state",
        lambda name: {"provider": name, "status": "ready", "available": True},
    )
    monkeypatch.setattr(readiness, "text_provider_order", lambda: ["ea"])
    monkeypatch.setattr(
        readiness,
        "text_provider_state",
        lambda name: {"provider": name, "status": "ready", "available": True},
    )
    monkeypatch.setattr(
        readiness,
        "overlay_vision_state",
        lambda: {
            "provider": "overlay_vision",
            "status": "endpoint_unreachable",
            "available": False,
            "detail": "The overlay vision endpoint is not reachable from this host.",
            "enabled": False,
            "base_url": "",
            "model": "llama3.2-vision:11b",
            "candidate_base_urls": ["https://images.example/ollama"],
            "pull_attempted": False,
            "pull_succeeded": False,
        },
    )

    assert readiness.main() == 0
    payload = json.loads((tmp_path / "provider-readiness.json").read_text(encoding="utf-8"))

    assert payload["overlay_vision"]["provider"] == "overlay_vision"
    assert payload["overlay_vision"]["status"] == "endpoint_unreachable"
    assert payload["overlay_vision"]["model"] == "llama3.2-vision:11b"
