from __future__ import annotations

from pathlib import Path


def test_runtime_image_copies_committed_completion_receipts() -> None:
    dockerfile = Path("/docker/EA/ea/Dockerfile").read_text(encoding="utf-8")

    assert 'cp -r "$APP_SRC/_completion" /app/_completion' in dockerfile
    assert "_completion" not in Path("/docker/EA/.dockerignore").read_text(encoding="utf-8").splitlines()


def test_runtime_image_copies_release_gate_makefile() -> None:
    dockerfile = Path("/docker/EA/ea/Dockerfile").read_text(encoding="utf-8")

    assert "cp /tmp/src/Makefile /app/Makefile" in dockerfile
