from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_ltds_rafter_pixefy_entries.py"


def test_rafter_pixefy_ltd_verifier_uses_repo_local_or_env_paths() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'Path("/docker/' + 'EA")' not in text
    assert "/docker/" + "chummercomplete" not in text
    assert "EA_LTD_INVENTORY_COMPLETION_ROOT" in text
    assert ".codex-studio" in text


def test_rafter_pixefy_ltd_verifier_does_not_serialize_account_identities() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "account_identity_policy" in text
    assert "account_user" not in text
    assert "the.girscheles" + "@gmail.com" not in text
