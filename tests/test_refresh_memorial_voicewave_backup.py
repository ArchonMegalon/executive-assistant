from __future__ import annotations

import ast
import importlib.util
import json
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "ea" / "scripts" / "refresh_memorial_voicewave_backup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("refresh_memorial_voicewave_backup", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(
    module: Any,
    tmp_path: Path,
    *,
    apply_metadata: bool = True,
    receipt_path: Path | None = None,
    comparator_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    output = receipt_path or tmp_path / "receipts" / "refresh.generated.json"
    result = module.run_refresh(
        slug="manfred",
        base_url="https://operator:secret@example.invalid/private?token=credential",
        prompts=["Private family transcript that must never be emitted"],
        compare_output_dir=tmp_path / "provider-private-output",
        compare_output_path=output,
        apply_metadata=apply_metadata,
        comparator_path=comparator_path,
        comparator_sha256="f" * 64,
    )
    return result, output


def test_run_refresh_is_honestly_blocked_and_receipt_only(tmp_path: Path) -> None:
    module = _load_module()

    result, receipt_path = _run(module, tmp_path, apply_metadata=False)

    assert result == json.loads(receipt_path.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["reason"] == "provider_evidence_lane_unavailable"
    assert result["applied_metadata"] is False
    assert result["receipt_persisted"] is True
    assert result["provider_evidence_lane"] == {
        "status": "unavailable",
        "independent_verification_required": True,
    }
    assert not (tmp_path / "provider-private-output").exists()


def test_forged_comparator_and_env_cannot_execute_or_mutate_private_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    profile_root = tmp_path / "private-profiles"
    profile_dir = profile_root / "manfred"
    profile_dir.mkdir(parents=True, mode=0o700)
    profile_root.chmod(0o700)
    profile_dir.chmod(0o700)
    voice_config = profile_dir / "tts_voice.json"
    original = b'{"tts_plugin":"unmixr_clone","private":"unchanged"}\n'
    voice_config.write_bytes(original)
    voice_config.chmod(0o600)
    marker = tmp_path / "comparator-executed"
    comparator = tmp_path / "forged-comparator.py"
    comparator.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(profile_root))
    monkeypatch.setenv("EA_MEMORIAL_VOICE_COMPARATOR_PATH", str(comparator))
    monkeypatch.setenv("EA_MEMORIAL_VOICE_COMPARATOR_SHA256", "0" * 64)

    result, receipt_path = _run(
        module,
        tmp_path,
        comparator_path=comparator,
    )

    assert result["reason"] == "provider_evidence_lane_unavailable"
    assert not marker.exists()
    assert voice_config.read_bytes() == original
    assert stat.S_IMODE(voice_config.stat().st_mode) == 0o600
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == result


def test_receipt_never_leaks_prompt_url_comparator_or_private_paths(tmp_path: Path) -> None:
    module = _load_module()
    comparator = tmp_path / "private-provider-id.py"
    comparator.write_text("raise RuntimeError('provider private')\n", encoding="utf-8")

    result, receipt_path = _run(module, tmp_path, comparator_path=comparator)
    serialized = json.dumps(result) + receipt_path.read_text(encoding="utf-8")

    for forbidden in (
        "operator:secret",
        "token=credential",
        "Private family transcript",
        "private-provider-id",
        str(tmp_path),
    ):
        assert forbidden not in serialized


def test_private_profile_root_precedence_is_portable(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    explicit = tmp_path / "explicit-profiles"
    data_root = tmp_path / "memorial-data"
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(explicit))
    monkeypatch.setenv("EA_MEMORIAL_DATA_ROOT", str(data_root))
    assert module._private_profiles_root() == explicit

    monkeypatch.delenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR")
    assert module._private_profiles_root() == data_root / "private_memorial_profiles"

    monkeypatch.delenv("EA_MEMORIAL_DATA_ROOT")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path / "repo")
    assert module._private_profiles_root() == tmp_path / "repo" / "memorial_data" / "private_memorial_profiles"
    assert "ea/memorial_data" not in module._private_profiles_root().as_posix()


def test_writer_creates_only_private_directories_and_files(tmp_path: Path) -> None:
    module = _load_module()
    tmp_path.chmod(0o700)
    target = tmp_path / "created-private" / "receipt.json"

    module._write_private_json(target, {"status": "blocked"})

    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE((target.parent / ".receipt.json.lock").stat().st_mode) == 0o600


@pytest.mark.parametrize("mode", [0o700, 0o750])
def test_writer_preserves_allowed_preexisting_directory_mode(tmp_path: Path, mode: int) -> None:
    module = _load_module()
    private_dir = tmp_path / "preexisting-private"
    private_dir.mkdir(mode=mode)
    private_dir.chmod(mode)
    target = private_dir / "receipt.json"

    module._write_private_json(target, {"status": "blocked"})

    assert stat.S_IMODE(private_dir.stat().st_mode) == mode
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_writer_rejects_insecure_preexisting_directory_without_chmod(
    tmp_path: Path,
    mode: int,
) -> None:
    module = _load_module()
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(mode)

    with pytest.raises(module._PrivateWriteError, match="private_directory_mode_invalid"):
        module._write_private_json(shared / "receipt.json", {"status": "blocked"})

    assert stat.S_IMODE(shared.stat().st_mode) == mode
    assert not (shared / "receipt.json").exists()


def test_writer_rejects_attacker_owned_configured_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    private_dir = tmp_path / "attacker-owned"
    private_dir.mkdir(mode=0o700)
    private_dir.chmod(0o700)
    actual_euid = os.geteuid()
    monkeypatch.setattr(module.os, "geteuid", lambda: actual_euid + 1)

    with pytest.raises(module._PrivateWriteError, match="private_directory_owner_invalid"):
        module._write_private_json(private_dir / "receipt.json", {"status": "blocked"})

    assert not (private_dir / "receipt.json").exists()


def test_writer_rejects_creation_below_shared_writable_parent(tmp_path: Path) -> None:
    module = _load_module()
    shared = tmp_path / "shared-writable"
    shared.mkdir()
    shared.chmod(0o777)

    with pytest.raises(module._PrivateWriteError, match="private_directory_parent_untrusted"):
        module._write_private_json(
            shared / "attacker-controlled" / "receipt.json",
            {"status": "blocked"},
        )

    assert not (shared / "attacker-controlled").exists()


def test_writer_rejects_symlink_hardlink_and_insecure_existing_targets(tmp_path: Path) -> None:
    module = _load_module()
    private_dir = tmp_path / "private"
    private_dir.mkdir(mode=0o700)
    private_dir.chmod(0o700)
    victim = private_dir / "victim.json"
    victim.write_text('{"untouched":true}\n', encoding="utf-8")
    victim.chmod(0o600)
    symlink = private_dir / "symlink.json"
    symlink.symlink_to(victim)

    with pytest.raises(module._PrivateWriteError, match="private_target_not_regular"):
        module._write_private_json(symlink, {"untouched": False})

    hardlink = private_dir / "hardlink.json"
    os.link(victim, hardlink)
    with pytest.raises(module._PrivateWriteError, match="private_target_link_count_invalid"):
        module._write_private_json(hardlink, {"untouched": False})

    insecure = private_dir / "insecure.json"
    insecure.write_text("{}\n", encoding="utf-8")
    insecure.chmod(0o644)
    with pytest.raises(module._PrivateWriteError, match="private_target_mode_invalid"):
        module._write_private_json(insecure, {"status": "blocked"})
    assert stat.S_IMODE(insecure.stat().st_mode) == 0o644


def test_concurrent_invocations_remain_consistently_blocked_and_receipt_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir(mode=0o700)
    receipt_dir.chmod(0o700)
    receipt_path = receipt_dir / "refresh.json"
    profile_root = tmp_path / "profiles"
    profile = profile_root / "manfred"
    profile.mkdir(parents=True, mode=0o700)
    profile_root.chmod(0o700)
    profile.chmod(0o700)
    config = profile / "tts_voice.json"
    original = b'{"private":"unchanged"}\n'
    config.write_bytes(original)
    config.chmod(0o600)
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(profile_root))
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            result, _ = _run(module, tmp_path, receipt_path=receipt_path)
            results.append(result)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 4
    assert {result["status"] for result in results} == {"blocked"}
    assert {result["reason"] for result in results} == {"provider_evidence_lane_unavailable"}
    final_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert final_receipt["status"] == "blocked"
    assert final_receipt["reason"] == "provider_evidence_lane_unavailable"
    assert config.read_bytes() == original


def test_cli_returns_nonzero_and_prints_only_sanitized_blocked_receipt(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir(mode=0o700)
    receipt_dir.chmod(0o700)
    receipt_path = receipt_dir / "refresh.json"
    marker = tmp_path / "executed"
    comparator = tmp_path / "forged.py"
    comparator.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["EA_MEMORIAL_VOICE_COMPARATOR_PATH"] = str(comparator)
    env["EA_MEMORIAL_VOICE_COMPARATOR_SHA256"] = "0" * 64

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--slug",
            "manfred",
            "--base-url",
            "https://operator:secret@example.invalid/private?token=credential",
            "--prompt",
            "Private family transcript",
            "--compare-output-path",
            str(receipt_path),
            "--apply-metadata",
            "--comparator-path",
            str(comparator),
            "--comparator-sha256",
            "f" * 64,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    output = completed.stdout + completed.stderr + receipt_path.read_text(encoding="utf-8")
    assert completed.returncode != 0
    assert json.loads(completed.stdout)["reason"] == "provider_evidence_lane_unavailable"
    assert not marker.exists()
    for forbidden in ("operator:secret", "token=credential", "Private family transcript", str(comparator)):
        assert forbidden not in output


def test_release_source_contains_no_execution_or_ready_lane() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "compare_outputs" not in source
    assert "importlib" not in source
    tree = ast.parse(source)
    forbidden_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"exec", "compile"}
    }
    assert not forbidden_calls
    assert '"status": "ready"' not in source
