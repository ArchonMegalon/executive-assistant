from __future__ import annotations

import importlib.util
from pathlib import Path

from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.task_contracts import TaskContractService


ROOT = Path(__file__).resolve().parents[1]
CHUMMER_GUIDE_BOOTSTRAP_PATH = ROOT / "scripts" / "bootstrap_chummer6_guide_skill.py"
BROWSERACT_REPAIR_BOOTSTRAP_PATH = ROOT / "scripts" / "bootstrap_browseract_workflow_repair_skill.py"
DESIGN_GOVERNANCE_BOOTSTRAP_PATH = ROOT / "scripts" / "bootstrap_design_governance_skills.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builtin_groundwork_contracts_advertise_onemin_first_provider_hints() -> None:
    service = TaskContractService(InMemoryTaskContractRepository())

    contract = service.get_contract_or_raise("meeting_prep")
    hints = contract.runtime_policy().skill_catalog.provider_hints_json

    assert hints["primary"][:3] == ["1min.AI", "AI Magicx", "Gemini Vortex"]


def test_chummer6_guide_bootstrap_routes_through_brain_router_with_onemin_first_hints() -> None:
    module = _load_module(CHUMMER_GUIDE_BOOTSTRAP_PATH, "bootstrap_chummer6_guide_skill")
    payloads = {payload["skill_key"]: payload for payload in module.build_skill_payloads()}

    for skill_key in ("chummer6_public_writer", "chummer6_visual_director"):
        payload = payloads[skill_key]
        assert payload["allowed_tools"] == ["provider.brain_router.structured_generate", "artifact_repository"]
        assert payload["tool_policy_json"]["allowed_tools"] == ["provider.brain_router.structured_generate", "artifact_repository"]
        assert payload["model_policy_json"]["brain_profile"] == "groundwork"
        assert payload["provider_hints_json"]["primary"] == ["1min.AI"]
        assert payload["provider_hints_json"]["output"][0] == "1min.AI"

    for skill_key in (
        "chummer6_public_auditor",
        "chummer6_user_auditor",
        "chummer6_scene_auditor",
        "chummer6_visual_auditor",
        "chummer6_pack_auditor",
    ):
        payload = payloads[skill_key]
        assert payload["allowed_tools"] == ["provider.brain_router.structured_generate", "artifact_repository"]
        assert payload["model_policy_json"]["brain_profile"] == "audit"
        assert payload["provider_hints_json"]["primary"] == ["1min.AI"]


def test_browseract_repair_bootstrap_uses_repair_profile_with_onemin_before_gemini() -> None:
    module = _load_module(BROWSERACT_REPAIR_BOOTSTRAP_PATH, "bootstrap_browseract_workflow_repair_skill")

    payload = module.build_skill_payload()

    assert payload["model_policy_json"]["brain_profile"] == "repair"
    assert payload["provider_hints_json"]["primary"] == ["1min.AI", "BrowserAct", "Gemini Vortex"]
    assert "Gemini Vortex" not in payload["tags"]


def test_design_governance_bootstrap_uses_onemin_before_browseract_or_gemini() -> None:
    module = _load_module(DESIGN_GOVERNANCE_BOOTSTRAP_PATH, "bootstrap_design_governance_skills")
    payloads = {payload["skill_key"]: payload for payload in module.SKILLS}

    assert payloads["design_petition"]["provider_hints_json"]["primary"] == [
        "1min.AI",
        "ChatPlayground AI",
        "Gemini Vortex",
    ]
    assert payloads["design_synthesis"]["provider_hints_json"]["primary"] == [
        "1min.AI",
        "Gemini Vortex",
        "ChatPlayground AI",
    ]
    assert payloads["mirror_status_brief"]["provider_hints_json"]["primary"] == [
        "1min.AI",
        "ChatPlayground AI",
        "Gemini Vortex",
    ]
