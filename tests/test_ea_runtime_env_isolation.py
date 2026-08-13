from __future__ import annotations

import errno
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "prepare_ea_runtime_env.py"
RUNTIME_DIR = ".ea-runtime-secrets"


def _module():
    spec = importlib.util.spec_from_file_location("prepare_ea_runtime_env", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "ea-repo"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    return root


def _secret_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    path.chmod(0o600)


def test_materialization_removes_every_propertyquarry_key_and_preserves_other_bytes(tmp_path: Path) -> None:
    module = _module()
    root = _repo(tmp_path)
    primary = (
        b"# PROPERTYQUARRY_COMMENT=is-not-an-assignment\r\n"
        b"EA_API_TOKEN=ea-token\r\n"
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_PASSWORD=mail-secret\r\n"
        b"  export PROPERTYQUARRY_GOOGLE_CLIENT_SECRET = google-secret\n"
        b"PROPERTYQUARRY_FUTURE_IDENTITY_KEY=future-secret\n"
        b"EA_LITERAL='spaces and = signs'\n"
        b"not valid PROPERTYQUARRY_TEXT=preserve-me\n"
        b"EA_FINAL=no-newline"
    )
    local = (
        b"EA_LOCAL_ONLY=keep\n"
        b"PROPERTYQUARRY_GOOGLE_CLIENT_ID=remove\n"
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SENDER # inherited value must also be removed\n"
    )
    _secret_file(root / ".env", primary)
    _secret_file(root / ".env.local", local)

    receipt = module.prepare_runtime_env(root)

    assert (root / RUNTIME_DIR / "ea_runtime.env").read_bytes() == (
        b"# PROPERTYQUARRY_COMMENT=is-not-an-assignment\r\n"
        b"EA_API_TOKEN=ea-token\r\n"
        b"EA_LITERAL='spaces and = signs'\n"
        b"not valid PROPERTYQUARRY_TEXT=preserve-me\n"
        b"EA_FINAL=no-newline"
    )
    assert (root / RUNTIME_DIR / "ea_runtime.local.env").read_bytes() == b"EA_LOCAL_ONLY=keep\n"
    assert receipt["status"] == "prepared"
    assert receipt["output_count"] == 2
    assert receipt["removed_key_count"] == 5
    assert receipt["optional_local_source"] == "present"
    assert stat.S_IMODE((root / RUNTIME_DIR).stat().st_mode) == 0o700
    assert stat.S_IMODE((root / RUNTIME_DIR / "ea_runtime.env").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / RUNTIME_DIR / "ea_runtime.local.env").stat().st_mode) == 0o600
    assert (root / ".env").read_bytes() == primary
    assert (root / ".env.local").read_bytes() == local


def test_all_named_mail_and_google_keys_are_denied_alongside_future_prefix_keys(tmp_path: Path) -> None:
    module = _module()
    root = _repo(tmp_path)
    blocked = sorted(module.BLOCKED_EXACT_KEYS | {b"PROPERTYQUARRY_FUTURE_SECRET"})
    content = b"EA_KEEP=yes\n" + b"".join(key + b"=do-not-copy\n" for key in blocked)
    _secret_file(root / ".env", content)

    receipt = module.prepare_runtime_env(root)

    assert (root / RUNTIME_DIR / "ea_runtime.env").read_bytes() == b"EA_KEEP=yes\n"
    assert receipt["removed_key_count"] == len(blocked)


def test_operator_only_spatial_tour_credentials_are_denied_from_both_runtime_env_files(
    tmp_path: Path,
) -> None:
    module = _module()
    root = _repo(tmp_path)
    _secret_file(
        root / ".env",
        b"EA_KEEP=yes\n"
        b"PANO2VR_EMAIL=operator@example.invalid\n"
        b"PANO2VR_LICENSE_KEY=license-secret\n",
    )
    _secret_file(
        root / ".env.local",
        b"EA_LOCAL_KEEP=yes\n"
        b"PANO2VR_PASSWORD=account-secret\n"
        b"PANO2VR_FUTURE_VENDOR_TOKEN=future-secret\n",
    )

    receipt = module.prepare_runtime_env(root)

    assert (root / RUNTIME_DIR / "ea_runtime.env").read_bytes() == b"EA_KEEP=yes\n"
    assert (root / RUNTIME_DIR / "ea_runtime.local.env").read_bytes() == b"EA_LOCAL_KEEP=yes\n"
    assert receipt["removed_key_count"] == 4


def test_absent_optional_source_removes_a_safe_stale_local_projection(tmp_path: Path) -> None:
    module = _module()
    root = _repo(tmp_path)
    _secret_file(root / ".env", b"EA_KEEP=yes\n")
    runtime = root / RUNTIME_DIR
    runtime.mkdir(mode=0o700)
    _secret_file(runtime / "ea_runtime.local.env", b"EA_STALE=must-not-survive\n")

    receipt = module.prepare_runtime_env(root)

    assert receipt["optional_local_source"] == "absent"
    assert receipt["stale_local_output_removed"] is True
    assert not (runtime / "ea_runtime.local.env").exists()


@pytest.mark.parametrize("unsafe_source", ["symlink", "hardlink", "world_writable", "world_readable"])
def test_unsafe_source_metadata_is_rejected(tmp_path: Path, unsafe_source: str) -> None:
    module = _module()
    root = _repo(tmp_path)
    backing = root / "backing.env"
    _secret_file(backing, b"EA_KEEP=yes\n")
    source = root / ".env"
    if unsafe_source == "symlink":
        source.symlink_to(backing.name)
    elif unsafe_source == "hardlink":
        os.link(backing, source)
    elif unsafe_source == "world_writable":
        source.write_bytes(b"EA_KEEP=yes\n")
        source.chmod(0o622)
    else:
        source.write_bytes(b"EA_KEEP=yes\n")
        source.chmod(0o644)

    with pytest.raises(module.SanitizerError):
        module.prepare_runtime_env(root)

    assert not (root / RUNTIME_DIR / "ea_runtime.env").exists()


@pytest.mark.parametrize("unsafe_destination", ["symlink", "hardlink", "permissive_mode"])
def test_unsafe_destination_metadata_is_rejected_without_touching_target(
    tmp_path: Path,
    unsafe_destination: str,
) -> None:
    module = _module()
    root = _repo(tmp_path)
    _secret_file(root / ".env", b"EA_KEEP=new\n")
    runtime = root / RUNTIME_DIR
    runtime.mkdir(mode=0o700)
    target = root / "outside-target"
    _secret_file(target, b"must-stay-unchanged")
    destination = runtime / "ea_runtime.env"
    if unsafe_destination == "symlink":
        destination.symlink_to(target)
    elif unsafe_destination == "hardlink":
        os.link(target, destination)
    else:
        destination.write_bytes(b"unsafe-old-value")
        destination.chmod(0o644)

    with pytest.raises(module.SanitizerError):
        module.prepare_runtime_env(root)

    assert target.read_bytes() == b"must-stay-unchanged"


def test_runtime_directory_symlink_is_rejected(tmp_path: Path) -> None:
    module = _module()
    root = _repo(tmp_path)
    _secret_file(root / ".env", b"EA_KEEP=yes\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / RUNTIME_DIR).symlink_to(outside, target_is_directory=True)

    with pytest.raises(module.SanitizerError):
        module.prepare_runtime_env(root)

    assert list(outside.iterdir()) == []


def test_trusted_group_writable_repository_root_is_supported(tmp_path: Path) -> None:
    module = _module()
    root = _repo(tmp_path)
    root.chmod(0o775)
    _secret_file(
        root / ".env",
        b"EA_KEEP=yes\nEMAILIT_API_KEY=property-mail-secret\n",
    )

    receipt = module.prepare_runtime_env(root)

    assert receipt["removed_key_count"] == 1
    assert (root / RUNTIME_DIR / "ea_runtime.env").read_bytes() == b"EA_KEEP=yes\n"


def test_atomic_replace_failure_preserves_previous_projection_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    root = _repo(tmp_path)
    _secret_file(root / ".env", b"EA_KEEP=new\n")
    runtime = root / RUNTIME_DIR
    runtime.mkdir(mode=0o700)
    destination = runtime / "ea_runtime.env"
    _secret_file(destination, b"EA_KEEP=old\n")

    def fail_replace(*_args, **_kwargs):
        raise OSError(errno.EIO, "simulated replace failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(module.SanitizerError):
        module.prepare_runtime_env(root)

    assert destination.read_bytes() == b"EA_KEEP=old\n"
    assert [path.name for path in runtime.iterdir()] == ["ea_runtime.env"]


def test_cli_receipt_contains_only_counts_and_digests_not_values(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    mail_secret = "smtp-secret-never-print"
    ea_secret = "ea-secret-never-print"
    _secret_file(
        root / ".env",
        f"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_PASSWORD={mail_secret}\nEA_API_TOKEN={ea_secret}\n".encode(),
    )

    result = subprocess.run(
        [str(SCRIPT_PATH), "--root", str(root)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    receipt = json.loads(result.stdout)

    assert receipt["status"] == "prepared"
    assert receipt["removed_key_count"] == 1
    assert mail_secret not in result.stdout + result.stderr
    assert ea_secret not in result.stdout + result.stderr
    assert receipt["outputs"][0]["sha256"]


def test_deploy_runs_runtime_isolation_preflight_after_source_exists() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    source_gate = 'if [[ ! -f "${APP_ROOT}/.env" ]]; then'
    preflight = '"${PYTHON_BIN}" "${APP_ROOT}/scripts/prepare_ea_runtime_env.py" --root "${APP_ROOT}"'

    assert "python3 scripts/prepare_ea_runtime_env.py" in deploy
    assert deploy.index(source_gate) < deploy.index(preflight) < deploy.index("source_worktree_status=\"\"")


def test_generated_runtime_env_files_are_ignored_and_script_is_executable() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".ea-runtime-secrets/" in gitignore
    assert SCRIPT_PATH.is_file()
    assert os.access(SCRIPT_PATH, os.X_OK)
