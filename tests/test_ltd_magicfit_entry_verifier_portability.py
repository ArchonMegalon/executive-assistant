from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_ltds_magicfit_entry.py"


def test_magicfit_ltd_verifier_uses_repo_local_or_env_paths() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'Path("/docker/' + 'EA")' not in text
    assert "/docker/" + "chummercomplete" not in text
    assert "EA_LTD_INVENTORY_COMPLETION_ROOT" in text
    assert ".codex-studio" in text


def test_magicfit_ltd_verifier_does_not_serialize_account_identities() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "account_identity_policy" in text
    assert '"accounts"' not in text
    assert "tibor.girschele" + "@gmail.com" not in text
    assert "the.girscheles" + "@gmail.com" not in text
    assert "archon.megalon" + "@gmail.com" not in text
