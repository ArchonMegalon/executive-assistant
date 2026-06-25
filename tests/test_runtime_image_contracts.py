from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "ea"


def test_runtime_image_build_inputs_exist() -> None:
    required = (
        APP_ROOT / "Dockerfile",
        APP_ROOT / "Dockerfile.operator",
        APP_ROOT / "requirements.txt",
        APP_ROOT / "requirements.lock",
        APP_ROOT / "docker-entrypoint.sh",
        APP_ROOT / "app" / "runner.py",
        APP_ROOT / "app" / "logging_utils.py",
    )

    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert missing == [], f"missing runtime image build inputs: {missing}"


def test_runtime_image_copies_committed_completion_receipts() -> None:
    dockerfile = (APP_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'cp -r "$APP_SRC/_completion" /app/_completion' in dockerfile
    assert "_completion" not in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()


def test_runtime_image_copies_release_gate_makefile() -> None:
    dockerfile = (APP_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "cp /tmp/src/Makefile /app/Makefile" in dockerfile


def test_runtime_images_install_with_requirements_lock_constraints() -> None:
    dockerfile = (APP_ROOT / "Dockerfile").read_text(encoding="utf-8")
    operator_dockerfile = (APP_ROOT / "Dockerfile.operator").read_text(encoding="utf-8")

    assert "requirements.lock" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt -c requirements.lock" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt;" not in dockerfile
    assert "requirements.lock" in operator_dockerfile
    assert "pip install --no-cache-dir -r requirements.txt -c requirements.lock" in operator_dockerfile
    assert "pip install --no-cache-dir -r requirements.txt;" not in operator_dockerfile


def test_runtime_images_pin_python_base_image_digests() -> None:
    dockerfile = (APP_ROOT / "Dockerfile").read_text(encoding="utf-8")
    operator_dockerfile = (APP_ROOT / "Dockerfile.operator").read_text(encoding="utf-8")
    root_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim@sha256:" in dockerfile
    assert "FROM python:3.12-slim@sha256:" in operator_dockerfile
    assert "FROM python:3.12-slim@sha256:" in root_dockerfile


def test_runtime_requirements_are_exactly_pinned() -> None:
    lines = [
        line.strip()
        for line in (APP_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert lines, "requirements.txt must not be empty"
    assert all("==" in line for line in lines), f"unlocked requirements found: {lines}"
    assert not any(">=" in line or "<=" in line or "~=" in line for line in lines)


def test_openvoice_tts_runtime_image_inputs_are_absent() -> None:
    forbidden = (
        APP_ROOT / "Dockerfile.openvoice",
        APP_ROOT / "requirements-openvoice.txt",
        APP_ROOT / "app" / "openvoice_app.py",
        APP_ROOT / "app" / "services" / "openvoice_runtime.py",
    )

    assert [str(path.relative_to(ROOT)) for path in forbidden if path.exists()] == []


def test_runtime_image_runs_as_non_root_user_by_default() -> None:
    dockerfile = (APP_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER ea" in dockerfile
    assert "USER root" not in dockerfile


def test_core_runtime_image_omits_host_docker_tooling() -> None:
    dockerfile = (APP_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "docker.io" not in dockerfile
    assert "docker-compose" not in dockerfile
    assert "docker-29.3.0.tgz" not in dockerfile
    assert 'mv /tmp/docker/docker /usr/local/bin/docker' not in dockerfile


def test_operator_runtime_image_carries_host_docker_tooling() -> None:
    dockerfile = (APP_ROOT / "Dockerfile.operator").read_text(encoding="utf-8")

    assert "docker.io" in dockerfile
    assert "docker-compose" in dockerfile
    assert "docker-29.3.0.tgz" in dockerfile
    assert "/usr/local/bin/docker" in dockerfile
