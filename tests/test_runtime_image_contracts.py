from __future__ import annotations

from pathlib import Path


def test_runtime_image_copies_committed_completion_receipts() -> None:
    dockerfile = Path("/docker/EA/ea/Dockerfile").read_text(encoding="utf-8")

    assert 'cp -r "$APP_SRC/_completion" /app/_completion' in dockerfile
    assert "_completion" not in Path("/docker/EA/.dockerignore").read_text(encoding="utf-8").splitlines()


def test_runtime_image_copies_release_gate_makefile() -> None:
    dockerfile = Path("/docker/EA/ea/Dockerfile").read_text(encoding="utf-8")

    assert "cp /tmp/src/Makefile /app/Makefile" in dockerfile


def test_runtime_images_install_with_requirements_lock_constraints() -> None:
    dockerfile = Path("/docker/EA/ea/Dockerfile").read_text(encoding="utf-8")
    openvoice_dockerfile = Path("/docker/EA/ea/Dockerfile.openvoice").read_text(encoding="utf-8")

    assert "requirements.lock" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt -c requirements.lock" in dockerfile
    assert "COPY requirements.lock /app/requirements.lock" in openvoice_dockerfile
    assert "pip install --no-cache-dir -r /app/requirements.txt -c /app/requirements.lock" in openvoice_dockerfile
    assert "pip install --no-cache-dir -r /app/requirements-openvoice.txt -c /app/requirements.lock" in openvoice_dockerfile
