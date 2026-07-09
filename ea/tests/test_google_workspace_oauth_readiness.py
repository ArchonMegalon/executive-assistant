from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "materialize_google_workspace_oauth_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("materialize_google_workspace_oauth_readiness", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_receipt_uses_process_env_when_env_file_is_unreadable(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_path = tmp_path / ".env"
    env_path.write_text("EA_GOOGLE_OAUTH_CLIENT_ID=from-file-should-not-be-read\n", encoding="utf-8")
    original_read_text = Path.read_text

    monkeypatch.setenv(
        "EA_GOOGLE_OAUTH_CLIENT_ID",
        "95627800296-5p8etgg3vvc210mfs9hkphqohtd6bsdg.apps.googleusercontent.com",
    )
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://myexternalbrain.com/google/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_PROJECT_ID", "propertyquarry-498318")
    monkeypatch.setenv("EA_GOOGLE_WORKSPACE_EXPECTED_EMAIL", "work.tibor.girschele@gmail.com")

    def _patched_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == env_path:
            raise PermissionError("simulated container env-file permission error")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)

    receipt = module.build_receipt(
        include_env_file=env_path,
        reauth_required_reason="google_oauth_invalid_grant",
    )

    assert receipt["status"] == "ready_retry_required"
    assert receipt["reauth_required_reason"] == "google_oauth_invalid_grant"
    assert receipt["oauth_client"]["client_id_present"] is True
    assert receipt["expected_google_account"]["present"] is True
    assert receipt["operator_action"]["next_action"] == "retry_full_workspace_auth_with_approved_account"
