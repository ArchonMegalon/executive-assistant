from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_origin_m4b_provider_import.py"


def load_module():
    spec = importlib.util.spec_from_file_location("origin_m4b_provider_import_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_fixture(tmp_path: Path) -> dict[str, Path | str]:
    root = tmp_path / "origin.chummer.run" / "Varga" / "Mira" / "Kestrel" / "audiobook"
    root.mkdir(parents=True)
    m4b = root / "kestrel-origin.m4b"
    cover = root / "cover.jpg"
    m4b.write_bytes(b"real provider m4b bytes")
    cover.write_bytes(b"real selected cover bytes")
    source_sha = hashlib.sha256(b"approved story").hexdigest()
    provider_receipt = write_json(
        root / "provider-m4b.receipt.json",
        {
            "status": "verified",
            "provider": "Inkfluence",
            "m4bSha256": sha256_file(m4b),
            "sourceSha256": source_sha,
        },
    )
    cover_receipt = write_json(
        root / "m4b-cover.receipt.json",
        {
            "status": "verified",
            "coverSha256": sha256_file(cover),
            "m4bSha256": sha256_file(m4b),
        },
    )
    return {
        "m4b": m4b,
        "cover": cover,
        "provider_receipt": provider_receipt,
        "cover_receipt": cover_receipt,
        "source_sha": source_sha,
    }


def verify(module, fixture: dict[str, Path | str]) -> dict:
    return module.verify(
        namespace="origin.chummer.run/Varga/Mira/Kestrel",
        m4b=fixture["m4b"],
        cover=fixture["cover"],
        provider_receipt=fixture["provider_receipt"],
        cover_receipt=fixture["cover_receipt"],
        source_sha256=str(fixture["source_sha"]),
    )


def test_origin_m4b_gate_passes_for_provider_backed_cover_bound_m4b(tmp_path: Path) -> None:
    module = load_module()
    fixture = build_fixture(tmp_path)

    result = verify(module, fixture)

    assert result["status"] == "pass"
    assert result["goldEligible"] is True
    assert result["issues"] == []
    assert result["rawRuntimePathsExposed"] is False
    assert result["rawCredentialExposed"] is False
    assert result["rawProviderTokenExposed"] is False
    assert result["m4bPath"] == "origin.chummer.run/Varga/Mira/Kestrel/audiobook/kestrel-origin.m4b"
    assert "provider_m4b_verified" in result["tokens"]
    assert "m4b_cover_embedded" in result["tokens"]


def test_origin_m4b_gate_blocks_missing_m4b(tmp_path: Path) -> None:
    module = load_module()
    fixture = build_fixture(tmp_path)
    Path(fixture["m4b"]).unlink()

    result = verify(module, fixture)

    assert result["status"] == "blocked"
    assert "m4b_missing" in result["issues"]
    assert result["goldEligible"] is False


def test_origin_m4b_gate_blocks_probe_or_fallback_markers(tmp_path: Path) -> None:
    module = load_module()
    fixture = build_fixture(tmp_path)
    probe_m4b = Path(fixture["m4b"]).with_name("unmixr-probe-fallback.m4b")
    Path(fixture["m4b"]).rename(probe_m4b)
    fixture["m4b"] = probe_m4b

    result = verify(module, fixture)

    assert result["status"] == "blocked"
    assert "m4b_filename_contains_rejected_marker" in result["issues"]


def test_origin_m4b_gate_blocks_source_hash_mismatch(tmp_path: Path) -> None:
    module = load_module()
    fixture = build_fixture(tmp_path)
    provider_receipt = Path(fixture["provider_receipt"])
    payload = json.loads(provider_receipt.read_text(encoding="utf-8"))
    payload["sourceSha256"] = "0" * 64
    write_json(provider_receipt, payload)

    result = verify(module, fixture)

    assert result["status"] == "blocked"
    assert "provider_receipt_source_hash_mismatch" in result["issues"]


def test_origin_m4b_gate_blocks_cover_hash_mismatch(tmp_path: Path) -> None:
    module = load_module()
    fixture = build_fixture(tmp_path)
    cover_receipt = Path(fixture["cover_receipt"])
    payload = json.loads(cover_receipt.read_text(encoding="utf-8"))
    payload["coverSha256"] = "0" * 64
    write_json(cover_receipt, payload)

    result = verify(module, fixture)

    assert result["status"] == "blocked"
    assert "m4b_cover_hash_mismatch" in result["issues"]
