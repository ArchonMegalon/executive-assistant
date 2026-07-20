from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from scripts.materialize_vexp_sentinel_v6_floor_fix import (
    CandidateError,
    EXPECTED_LIVE_SOURCE_SHA256,
    LIVE_SOURCE,
    PATCHES,
    materialize_candidate,
    patched_source,
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _synthetic_source() -> bytes:
    return "\n\n".join(old for _label, old, _new in PATCHES).encode("utf-8")


def _exact_live_source_available() -> bool:
    try:
        return _sha256(LIVE_SOURCE.read_bytes()) == EXPECTED_LIVE_SOURCE_SHA256
    except OSError:
        return False


@pytest.mark.skipif(
    not _exact_live_source_available(),
    reason="exact checksum-pinned schema-v6 sentinel source is not installed",
)
def test_exact_live_source_materializes_private_candidate_and_passes_policy_selftest(
    tmp_path: Path,
) -> None:
    source_raw = LIVE_SOURCE.read_bytes()
    assert _sha256(source_raw) == EXPECTED_LIVE_SOURCE_SHA256
    output = tmp_path / "vexp-codex-sentinel-v6.candidate.mjs"

    receipt = materialize_candidate(source=LIVE_SOURCE, output=output)

    assert receipt["status"] == "candidate_materialized_not_installed"
    assert receipt["source_sha256"] == EXPECTED_LIVE_SOURCE_SHA256
    assert receipt["candidate_sha256"] == _sha256(output.read_bytes())
    assert receipt["live_source_modified"] is False
    assert receipt["sentinel_state_modified"] is False
    assert receipt["service_restarted"] is False
    assert receipt["qualification_epoch_preserved"] is True
    assert receipt["installation_authority"] is False
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert LIVE_SOURCE.read_bytes() == source_raw

    syntax = subprocess.run(
        ["node", "--check", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
    policy = subprocess.run(
        ["node", str(output), "--policy-selftest"],
        text=True,
        capture_output=True,
        check=False,
        env={
            "HOME": os.environ.get("HOME", ""),
            "PATH": os.environ.get("PATH", ""),
            "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"),
        },
    )
    assert policy.returncode == 0, policy.stderr


def test_patch_rejects_source_drift() -> None:
    raw = _synthetic_source()
    drifted = raw + b"\n// unexpected source drift\n"

    with pytest.raises(CandidateError, match="sentinel_source_digest_mismatch"):
        patched_source(drifted, expected_sha256=_sha256(raw))


def test_all_bounded_source_transforms_apply_once() -> None:
    raw = _synthetic_source()

    candidate = patched_source(raw, expected_sha256=_sha256(raw)).decode("utf-8")

    for label, old, new in PATCHES:
        assert old not in candidate, label
        assert candidate.count(new) == 1, label


def test_candidate_never_overwrites_source_or_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source.mjs"
    source.write_bytes(_synthetic_source())
    source.chmod(0o600)
    expected_sha256 = _sha256(source.read_bytes())

    with pytest.raises(CandidateError, match="live_source_overwrite_forbidden"):
        materialize_candidate(
            source=source,
            output=source,
            expected_sha256=expected_sha256,
        )

    output = tmp_path / "candidate.mjs"
    output.write_text("keep\n", encoding="utf-8")
    with pytest.raises(CandidateError, match="candidate_output_write_failed"):
        materialize_candidate(
            source=source,
            output=output,
            expected_sha256=expected_sha256,
        )
    assert output.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.skipif(
    not _exact_live_source_available(),
    reason="exact checksum-pinned schema-v6 sentinel source is not installed",
)
def test_cli_receipt_is_non_authoritative(tmp_path: Path) -> None:
    output = tmp_path / "candidate.mjs"
    result = subprocess.run(
        [
            "python3",
            "scripts/materialize_vexp_sentinel_v6_floor_fix.py",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "candidate_materialized_not_installed"
    assert receipt["installation_authority"] is False
    assert receipt["sentinel_state_modified"] is False
