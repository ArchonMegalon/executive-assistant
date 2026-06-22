from __future__ import annotations

import os

import scripts.run_proactive_ooda as runner
import scripts.verify_proactive_ooda as verifier


def test_dotenv_loader_fills_missing_values_without_overriding(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            (
                "EA_PROACTIVE_OODA_PRINCIPAL_ID=from-file",
                'EA_PROACTIVE_OODA_DISCOVERY_JSON="{\\"sources\\":[]}"',
                "EXISTING_VALUE=from-file",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING_VALUE", "from-env")
    monkeypatch.delenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", raising=False)

    runner._load_dotenv_if_present(env_path)

    assert os.environ["EA_PROACTIVE_OODA_PRINCIPAL_ID"] == "from-file"
    assert os.environ["EA_PROACTIVE_OODA_DISCOVERY_JSON"] == '{\\"sources\\":[]}'
    assert os.environ["EXISTING_VALUE"] == "from-env"


def test_verify_dotenv_loader_matches_runner(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EA_PROACTIVE_OODA_MAX_ITEMS=2\n", encoding="utf-8")
    monkeypatch.delenv("EA_PROACTIVE_OODA_MAX_ITEMS", raising=False)

    verifier._load_dotenv_if_present(env_path)

    assert os.environ["EA_PROACTIVE_OODA_MAX_ITEMS"] == "2"


def test_proactive_ooda_default_principal_is_generic_and_uses_runtime_default(monkeypatch) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("EA_DEFAULT_PRINCIPAL_ID", raising=False)

    assert runner._default_principal_id() == "principal-default"
    assert verifier._default_principal_id() == "principal-default"

    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "workspace-owner")
    assert runner._default_principal_id() == "workspace-owner"
    assert verifier._default_principal_id() == "workspace-owner"

    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "proactive-owner")
    assert runner._default_principal_id() == "proactive-owner"
    assert verifier._default_principal_id() == "proactive-owner"


def test_dotenv_loader_ignores_missing_or_unreadable_paths(tmp_path) -> None:
    runner._load_dotenv_if_present(tmp_path / "missing.env")
