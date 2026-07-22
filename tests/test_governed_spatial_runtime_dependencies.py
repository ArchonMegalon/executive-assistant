from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "ea" / "requirements.txt"
LOCK = ROOT / "ea" / "requirements.lock"


def _dependency_lines(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_governed_spatial_schema_validator_is_installed_and_constrained() -> None:
    requirements = _dependency_lines(REQUIREMENTS)
    lock = _dependency_lines(LOCK)

    assert "jsonschema==4.26.0" in requirements
    assert {
        "attrs==26.1.0",
        "jsonschema==4.26.0",
        "jsonschema-specifications==2025.9.1",
        "referencing==0.37.0",
        "rpds-py==2026.6.3",
    }.issubset(lock)


def test_crypto_requirement_and_lock_remain_exactly_pinned() -> None:
    requirements = _dependency_lines(REQUIREMENTS)
    lock = _dependency_lines(LOCK)

    assert "cryptography==48.0.1" in requirements
    assert "cryptography==48.0.1" in lock


def test_runtime_images_install_requirements_under_the_lock() -> None:
    for relative_path in ("Dockerfile", "ea/Dockerfile"):
        dockerfile = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "pip install --no-cache-dir -r requirements.txt -c requirements.lock" in dockerfile
