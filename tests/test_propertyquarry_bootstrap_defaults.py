from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_emailit_bootstrap_domain_defaults_are_configured_not_live_domain(monkeypatch) -> None:
    module = _load_script("bootstrap_emailit_propertyquarry.py")
    monkeypatch.delenv("PROPERTYQUARRY_EMAILIT_DOMAIN", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)

    assert module._configured_domain({}) == "propertyquarry.example.test"
    assert module._configured_sender_email({}, "propertyquarry.example.test") == "property@propertyquarry.example.test"

    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://assistant.example.test")
    assert module._configured_domain({}) == "assistant.example.test"

    monkeypatch.setenv("PROPERTYQUARRY_EMAILIT_DOMAIN", "mail.example.test")
    assert module._configured_domain({}) == "mail.example.test"


def test_payfunnels_bootstrap_public_base_defaults_to_example(monkeypatch) -> None:
    module = _load_script("bootstrap_payfunnels_propertyquarry.py")

    assert module._public_base({}) == "https://example.test"
    assert module._public_base({"EA_PUBLIC_APP_BASE_URL": "https://assistant.example.test/"}) == "https://assistant.example.test"
    assert module._public_base({"PROPERTYQUARRY_PUBLIC_BASE_URL": "https://property.example.test/"}) == "https://property.example.test"


def test_deploy_and_hard_exit_help_do_not_default_to_live_personal_public_state() -> None:
    root = Path(__file__).resolve().parents[1]
    deploy = (root / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    hard_exit = (root / "scripts" / "hard_exit_gates.sh").read_text(encoding="utf-8")

    live_sign_in = "https://propertyquarry" + ".com/sign-in"
    legacy_label = "Tibor " + "smoke"

    assert live_sign_in not in deploy
    assert "EA_PUBLIC_APP_BASE_URL:-https://example.test" in deploy
    assert legacy_label not in hard_exit
    assert "principal API smoke" in hard_exit
