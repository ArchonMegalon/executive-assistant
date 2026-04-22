from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path("/docker/EA/scripts/chummer6_browseract_prompting_systems.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_browseract_prompting_systems", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_env_value_allows_empty_env_to_clear_stale_local_value(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "LOCAL_ENV", {"CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID": "stale-workflow"})
    monkeypatch.setattr(module, "POLICY_ENV", {"CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID": "policy-workflow"})
    monkeypatch.setenv("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID", "")

    assert module.env_value("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID") == ""


def test_resolve_workflow_prefers_query_when_explicit_env_is_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "LOCAL_ENV", {"CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID": "stale-workflow"})
    monkeypatch.setattr(module, "POLICY_ENV", {})
    monkeypatch.setenv("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID", "")
    monkeypatch.setenv("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_QUERY", "prompt forge runtime")
    monkeypatch.setattr(
        module,
        "list_workflows",
        lambda: [
            {"workflow_id": "wf-runtime", "name": "Prompt Forge Runtime"},
            {"workflow_id": "wf-stale", "name": "Prompt Forge Legacy"},
        ],
    )

    workflow_id, workflow_name = module.resolve_workflow("REFINE")

    assert workflow_id == "wf-runtime"
    assert workflow_name == "Prompt Forge Runtime"


def test_resolve_workflow_falls_back_from_stale_query_to_default_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "LOCAL_ENV", {})
    monkeypatch.setattr(module, "POLICY_ENV", {})
    monkeypatch.delenv("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID", raising=False)
    monkeypatch.setenv("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_QUERY", "stale custom query")
    monkeypatch.setattr(
        module,
        "list_workflows",
        lambda: [
            {"workflow_id": "wf-live", "name": "prompting_systems_prompt_forge_live"},
        ],
    )

    workflow_id, workflow_name = module.resolve_workflow("REFINE")

    assert workflow_id == "wf-live"
    assert workflow_name == "prompting_systems_prompt_forge_live"
