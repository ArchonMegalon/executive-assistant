#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re
import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = (ROOT / "ea") if (ROOT / "ea").exists() else ROOT
PIN_RE = re.compile(r"^[A-Za-z0-9_.+\-\[\]]+==[^=\s]+$")
DOCKER_RE = re.compile(r"^FROM\s+python:(?P<tag>3\.(?:11|12)-slim)@sha256:(?P<digest>[a-f0-9]{64})\s*$", re.MULTILINE)
COMPOSE_IMAGE_PIN_RE = re.compile(r"^[a-z0-9./_-]+:[^@\s]+@sha256:[a-f0-9]{64}$", re.IGNORECASE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _pinned_requirements(path: Path) -> list[str]:
    rows: list[str] = []
    for raw in _read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        rows.append(line)
    return rows


def _load_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(_read(path))
    return loaded if isinstance(loaded, dict) else {}


def _verify_compose_image_pins(
    *,
    compose_path: Path,
    service_names: tuple[str, ...],
    compose_label: str,
    issues: list[str],
    compose_images: dict[str, str],
) -> None:
    if not compose_path.is_file():
        issues.append(f"compose_file_missing:{compose_label}")
        return
    compose = _load_yaml(compose_path)
    raw_services = compose.get("services")
    services = raw_services if isinstance(raw_services, dict) else {}
    for service_name in service_names:
        raw_service = services.get(service_name)
        service = raw_service if isinstance(raw_service, dict) else {}
        image = str(service.get("image") or "").strip()
        checked_key = f"{compose_label}:{service_name}"
        if not image:
            issues.append(f"compose_image_missing:{checked_key}")
            continue
        compose_images[checked_key] = image
        if not COMPOSE_IMAGE_PIN_RE.match(image):
            issues.append(f"compose_image_not_pinned:{checked_key}")


def verify() -> dict[str, object]:
    issues: list[str] = []
    compose_images: dict[str, str] = {}

    requirements_path = _first_existing(APP_ROOT / "requirements.txt", ROOT / "requirements.txt")
    lock_path = _first_existing(APP_ROOT / "requirements.lock", ROOT / "requirements.lock")
    if requirements_path is None:
        issues.append("requirements_txt_missing")
        requirements = []
    else:
        requirements = _pinned_requirements(requirements_path)
    if not requirements:
        issues.append("requirements_txt_empty")
    if any(not PIN_RE.match(line) for line in requirements):
        issues.append("requirements_txt_unpinned_entries")
    forbidden_openvoice_tts_files = [
        APP_ROOT / "requirements-openvoice.txt",
        ROOT / "requirements-openvoice.txt",
        APP_ROOT / "Dockerfile.openvoice",
        ROOT / "Dockerfile.openvoice",
        APP_ROOT / "app" / "openvoice_app.py",
        APP_ROOT / "app" / "services" / "openvoice_runtime.py",
    ]
    for path in forbidden_openvoice_tts_files:
        if path.exists():
            issues.append(f"forbidden_openvoice_tts_file_present:{path.relative_to(ROOT).as_posix()}")

    lock_text = _read(lock_path) if lock_path is not None else ""
    if lock_path is None:
        issues.append("requirements_lock_missing")
    if not lock_text.strip():
        issues.append("requirements_lock_empty")

    dockerfile_candidates = (
        ("ea/Dockerfile", _first_existing(ROOT / "ea/Dockerfile", ROOT / "Dockerfile")),
        ("ea/Dockerfile.operator", _first_existing(ROOT / "ea/Dockerfile.operator", ROOT / "Dockerfile.operator")),
        ("Dockerfile", _first_existing(ROOT / "Dockerfile", APP_ROOT / "Dockerfile")),
    )
    resolved_operator_dockerfile = _first_existing(ROOT / "ea/Dockerfile.operator", ROOT / "Dockerfile.operator")
    resolved_root_dockerfile = _first_existing(ROOT / "Dockerfile", APP_ROOT / "Dockerfile")
    for rel, dockerfile_path in dockerfile_candidates:
        if dockerfile_path is None:
            issues.append(f"dockerfile_missing:{rel}")
            continue
        text = _read(dockerfile_path)
        if not DOCKER_RE.search(text):
            issues.append(f"docker_base_not_pinned:{rel}")
    if resolved_operator_dockerfile is None:
        issues.append("operator_dockerfile_missing")
    elif "pip install --no-cache-dir -r requirements.txt -c requirements.lock" not in _read(resolved_operator_dockerfile):
        issues.append("operator_image_missing_locked_install")
    if resolved_operator_dockerfile is not None and "pip install --no-cache-dir -r requirements.txt;" in _read(resolved_operator_dockerfile):
        issues.append("operator_image_has_unlocked_install_fallback")
    if resolved_root_dockerfile is None:
        issues.append("root_dockerfile_missing")
    elif "pip install --no-cache-dir -r requirements.txt -c requirements.lock" not in _read(resolved_root_dockerfile):
        issues.append("root_image_missing_locked_install")

    _verify_compose_image_pins(
        compose_path=ROOT / "docker-compose.yml",
        service_names=("ea-db", "ea-redis"),
        compose_label="docker-compose.yml",
        issues=issues,
        compose_images=compose_images,
    )
    _verify_compose_image_pins(
        compose_path=ROOT / "docker-compose.host-tools.yml",
        service_names=("ea-docker-socket-proxy",),
        compose_label="docker-compose.host-tools.yml",
        issues=issues,
        compose_images=compose_images,
    )
    _verify_compose_image_pins(
        compose_path=ROOT / "docker-compose.fastestvpn.yml",
        service_names=("ea-docker-socket-proxy",),
        compose_label="docker-compose.fastestvpn.yml",
        issues=issues,
        compose_images=compose_images,
    )
    _verify_compose_image_pins(
        compose_path=ROOT / "docker-compose.cloudflared.yml",
        service_names=("ea-cloudflared",),
        compose_label="docker-compose.cloudflared.yml",
        issues=issues,
        compose_images=compose_images,
    )

    return {
        "contract_name": "ea.runtime_supply_chain.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "checked": {
            "requirements_txt": "ea/requirements.txt",
            "requirements_lock": "ea/requirements.lock",
            "dockerfiles": [
                "ea/Dockerfile",
                "ea/Dockerfile.operator",
                "Dockerfile",
            ],
            "forbidden_openvoice_tts_files": [path.relative_to(ROOT).as_posix() for path in forbidden_openvoice_tts_files],
            "compose_services": [
                "docker-compose.yml:ea-db",
                "docker-compose.yml:ea-redis",
                "docker-compose.host-tools.yml:ea-docker-socket-proxy",
                "docker-compose.fastestvpn.yml:ea-docker-socket-proxy",
                "docker-compose.cloudflared.yml:ea-cloudflared",
            ],
            "compose_images": compose_images,
        },
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
