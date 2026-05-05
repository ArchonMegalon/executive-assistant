from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_env_no_secrets.py"


def _module():
    spec = importlib.util.spec_from_file_location("verify_env_no_secrets", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_is_tracked_env_template_accepts_only_tracked_env_templates() -> None:
    module = _module()

    assert module.is_tracked_env_template(".env.example") is True
    assert module.is_tracked_env_template("config/.env.prod.example") is True
    assert module.is_tracked_env_template(".env") is False
    assert module.is_tracked_env_template("ENVIRONMENT_MATRIX.md") is False


def test_tracked_env_template_paths_ignore_local_dotenv(monkeypatch) -> None:
    module = _module()

    class FakeCompletedProcess:
        stdout = b".env.example\0.env.local.example\0.env\0README.md\0"

    def _fake_run(*args, **kwargs):
        return FakeCompletedProcess()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    paths = module.tracked_env_template_paths()

    assert [path.name for path in paths] == [".env.example", ".env.local.example"]
