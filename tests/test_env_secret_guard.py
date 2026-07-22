from __future__ import annotations

import importlib.util
import os
import sys
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


def test_active_secret_scan_excludes_generated_state_and_tests() -> None:
    module = _module()

    assert module.is_active_secret_scan_path("scripts/deploy.sh") is True
    assert module.is_active_secret_scan_path("README.md") is True
    assert module.is_active_secret_scan_path(".env.example") is True
    assert module.is_active_secret_scan_path("tests/test_example.py") is False
    assert module.is_active_secret_scan_path(".codex-studio/published/example.json") is False
    assert module.is_active_secret_scan_path(".vexp/manifest.json") is False
    assert module.is_active_secret_scan_path("state/example.json") is False


def test_raw_secret_context_hits_detects_key_like_literals(tmp_path: Path) -> None:
    module = _module()
    key_like_value = "a" * 40
    candidate = tmp_path / "README.md"
    candidate.write_text(f"unmixr api key: {key_like_value}\nsha256: {key_like_value}\n", encoding="utf-8")

    assert list(module.raw_secret_context_hits(candidate)) == [1]


def test_env_key_classifier_ignores_secret_file_hash_and_overlap_settings() -> None:
    module = _module()

    assert module.is_suspicious_env_key("UNMIXR_API_KEY") is True
    assert module.is_suspicious_env_key("EA_CALLBACK_SECRET") is True
    assert module.is_suspicious_env_key("EA_WORKSPACE_ACCESS_TOKEN_ISSUER") is False
    assert module.is_suspicious_env_key("EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE") is False
    assert module.is_suspicious_env_key("EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION") is False
    assert module.is_suspicious_env_key("EA_CALLBACK_SECRET_FILE") is False
    assert module.is_suspicious_env_key("EA_AUDIOBOOK_PUBLICATION_STT_MIN_BOOK_TOKEN_OVERLAP") is False
    assert module.is_suspicious_env_key("ONEMIN_SECRET_SHA256") is False


def test_ea_env_example_uses_ea_public_oauth_callback() -> None:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    assert values["EA_PUBLIC_APP_BASE_URL"] == "https://example.test"
    assert values["EA_GOOGLE_OAUTH_REDIRECT_URI"] == "https://example.test/google/callback"
    assert values["PROPERTYQUARRY_PUBLIC_BASE_URL"] == "https://property.example.test"


def test_public_publisher_defaults_are_generic_and_derive_from_public_app_base(monkeypatch) -> None:
    monkeypatch.delenv("EA_PUBLIC_RESULT_BASE_URL", raising=False)
    monkeypatch.delenv("EA_PUBLIC_TOUR_BASE_URL", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", raising=False)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://public.example.test/")

    browseract = _load_script(ROOT / "scripts" / "publish_browseract_ui_results.py")
    crezlo_property = _load_script(ROOT / "scripts" / "publish_crezlo_property_tours.py")
    crezlo_public = _load_script(ROOT / "scripts" / "publish_crezlo_public_tours.py")

    assert browseract.DEFAULT_PUBLIC_BASE_URL == "https://public.example.test/results"
    assert crezlo_property.DEFAULT_PUBLIC_BASE_URL == "https://propertyquarry.com/tours"
    assert crezlo_public.DEFAULT_PUBLIC_BASE_URL == "https://propertyquarry.com/tours"


def test_crezlo_public_publisher_defaults_are_propertyquarry_specific(monkeypatch) -> None:
    monkeypatch.delenv("EA_PUBLIC_TOUR_BASE_URL", raising=False)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://assistant.example.test/")
    monkeypatch.setenv("PROPERTYQUARRY_PUBLIC_BASE_URL", "https://property.example.test/")
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", raising=False)

    crezlo_property = _load_script(ROOT / "scripts" / "publish_crezlo_property_tours.py")
    crezlo_public = _load_script(ROOT / "scripts" / "publish_crezlo_public_tours.py")

    assert crezlo_property.DEFAULT_PUBLIC_BASE_URL == "https://property.example.test/tours"
    assert crezlo_public.DEFAULT_PUBLIC_BASE_URL == "https://property.example.test/tours"

    monkeypatch.setenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", "https://tours.example.test/")
    crezlo_property = _load_script(ROOT / "scripts" / "publish_crezlo_property_tours.py")
    crezlo_public = _load_script(ROOT / "scripts" / "publish_crezlo_public_tours.py")

    assert crezlo_property.DEFAULT_PUBLIC_BASE_URL == "https://tours.example.test"
    assert crezlo_public.DEFAULT_PUBLIC_BASE_URL == "https://tours.example.test"

    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://legacy-tour-override.example.test/")
    crezlo_property = _load_script(ROOT / "scripts" / "publish_crezlo_property_tours.py")
    crezlo_public = _load_script(ROOT / "scripts" / "publish_crezlo_public_tours.py")

    assert crezlo_property.DEFAULT_PUBLIC_BASE_URL == "https://legacy-tour-override.example.test"
    assert crezlo_public.DEFAULT_PUBLIC_BASE_URL == "https://legacy-tour-override.example.test"


def _load_script(path: Path):
    env_fingerprint = (
        os.environ.get("EA_PUBLIC_APP_BASE_URL", ""),
        os.environ.get("EA_PUBLIC_TOUR_BASE_URL", ""),
        os.environ.get("PROPERTYQUARRY_PUBLIC_BASE_URL", ""),
        os.environ.get("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", ""),
    )
    module_name = f"test_loaded_{path.stem}_{abs(hash((path, env_fingerprint)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    script_dir = str(path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec.loader.exec_module(module)
    return module
