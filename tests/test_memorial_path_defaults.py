from __future__ import annotations

from pathlib import Path


def test_memorial_voice_profile_defaults_to_memorial_data_root(monkeypatch, tmp_path: Path) -> None:
    from app.services.memorial_voice_profile import memorial_private_profile_root

    monkeypatch.delenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", raising=False)
    monkeypatch.setenv("EA_MEMORIAL_DATA_ROOT", str(tmp_path))

    root = memorial_private_profile_root()

    assert root == tmp_path / "memorial_data" / "private_memorial_profiles"
    assert "/mnt/pcloud" not in root.as_posix()


def test_memorial_voice_profile_honors_explicit_profile_dir(monkeypatch, tmp_path: Path) -> None:
    from app.services.memorial_voice_profile import memorial_private_profile_root

    explicit = tmp_path / "profiles"
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(explicit))
    monkeypatch.setenv("EA_MEMORIAL_DATA_ROOT", str(tmp_path / "data-root"))

    assert memorial_private_profile_root() == explicit


def test_memorial_stt_error_log_defaults_to_private_memorial_data_root(monkeypatch, tmp_path: Path) -> None:
    from app.services.memorial_stt_error_log import memorial_stt_error_log_root, _storage_policy

    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", raising=False)
    monkeypatch.setenv("EA_MEMORIAL_DATA_ROOT", str(tmp_path))

    root = memorial_stt_error_log_root()
    policy = _storage_policy()

    assert root == tmp_path / "memorial_data" / "private_memorial_stt_errors"
    assert "/mnt/pcloud" not in root.as_posix()
    assert policy["allowed"] is True
    assert policy["storage_mode"] == "managed_private_root"


def test_memorial_stt_error_log_rejects_unmanaged_root_without_override(monkeypatch, tmp_path: Path) -> None:
    from app.services.memorial_stt_error_log import _storage_policy

    monkeypatch.setenv("EA_MEMORIAL_DATA_ROOT", str(tmp_path / "memorial-root"))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(tmp_path / "other"))
    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", raising=False)

    policy = _storage_policy()

    assert policy["allowed"] is False
    assert policy["reason"] == "root_not_under_memorial_stt_error_root"
