from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "bootstrap_chummer6_guide_skill.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bootstrap_chummer6_guide_skill", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chummer6_public_writer_publish_repo_is_env_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    monkeypatch.delenv("CHUMMER6_GUIDE_PUBLISH_REPO", raising=False)
    monkeypatch.delenv("EA_CHUMMER6_GUIDE_PUBLISH_REPO", raising=False)
    assert module.build_public_writer_skill_payload()["budget_policy_json"]["publish_repo"] == "chummer6/docs"

    monkeypatch.setenv("EA_CHUMMER6_GUIDE_PUBLISH_REPO", "owner/from-ea-env")
    assert module.build_public_writer_skill_payload()["budget_policy_json"]["publish_repo"] == "owner/from-ea-env"

    monkeypatch.setenv("CHUMMER6_GUIDE_PUBLISH_REPO", "owner/from-direct-env")
    assert module.build_public_writer_skill_payload()["budget_policy_json"]["publish_repo"] == "owner/from-direct-env"


def test_chummer6_guide_bootstrap_has_no_personal_publish_repo_default() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "ArchonMegalon/" + "Chummer6" not in source
    assert "CHUMMER6_GUIDE_PUBLISH_REPO" in source
