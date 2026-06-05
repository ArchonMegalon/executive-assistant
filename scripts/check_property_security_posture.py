#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _normalized_requirement_name(line: str) -> str:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return ""
    name = re.split(r"[<>=!~\[]", raw, maxsplit=1)[0].strip().lower()
    return name


def _lock_package_names(lock_text: str) -> set[str]:
    names: set[str] = set()
    for line in lock_text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "==" not in raw:
            continue
        names.add(raw.split("==", 1)[0].strip().lower().replace("_", "-"))
    return names


def main() -> int:
    failures: list[str] = []
    env_example = _read(".env.example")
    if "property@propertyquery.com" in env_example:
        failures.append(".env.example still references property@propertyquery.com")
    if re.search(r"^EA_REGISTRATION_EMAIL_FROM_FALLBACK=.+", env_example, flags=re.MULTILINE):
        failures.append(".env.example should not advertise a non-PropertyQuarry fallback sender")
    for env_name in ("EA_API_TOKEN", "EA_SIGNING_SECRET", "EA_CF_ACCESS_TEAM_DOMAIN", "EA_CF_ACCESS_AUD"):
        if not re.search(rf"^{re.escape(env_name)}=", env_example, flags=re.MULTILINE):
            failures.append(f".env.example must list prod auth/signing placeholder {env_name}")
    expected_service_aliases = {
        "PROPERTYQUARRY_API_SERVICE": "propertyquarry-api",
        "PROPERTYQUARRY_SCHEDULER_SERVICE": "propertyquarry-scheduler",
        "PROPERTYQUARRY_DB_SERVICE": "propertyquarry-db",
    }
    for env_name, expected_value in expected_service_aliases.items():
        if not re.search(rf"^{re.escape(env_name)}={re.escape(expected_value)}$", env_example, flags=re.MULTILINE):
            failures.append(f".env.example must default {env_name}={expected_value}")

    compose = _read("docker-compose.property.yml")
    forbidden_compose_tokens = (
        "ea-openvoice",
        "openvoice",
        "ea-responses-proxy",
        "ea-teable-relay",
        "memorial",
        "/var/run/docker.sock",
        "/mnt/onedrive",
        "/mnt/pcloud",
    )
    for token in forbidden_compose_tokens:
        if token in compose.lower():
            failures.append(f"docker-compose.property.yml contains inherited surface: {token}")
    for service_name in ("propertyquarry-api", "propertyquarry-scheduler", "propertyquarry-db"):
        if service_name not in compose:
            failures.append(f"docker-compose.property.yml missing {service_name}")
    if "propertyquarry-worker" in compose or "PROPERTYQUARRY_WORKER_PROFILE" in compose:
        failures.append("docker-compose.property.yml must not start the inherited idle worker by default")
    if "POSTGRES_HOST_AUTH_METHOD" in compose or ":-trust" in compose:
        failures.append("docker-compose.property.yml must not default Postgres to trust auth")
    if 'POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?' not in compose:
        failures.append("docker-compose.property.yml must require POSTGRES_PASSWORD")
    if 'EA_RUNTIME_MODE: "${EA_RUNTIME_MODE:-prod}"' not in compose:
        failures.append("docker-compose.property.yml must default EA_RUNTIME_MODE to prod")
    if 'PROPERTYQUARRY_SCHEDULER_PROFILE: "${PROPERTYQUARRY_SCHEDULER_PROFILE:-property_only}"' not in compose:
        failures.append("docker-compose.property.yml must default the scheduler to property_only")

    dockerfile = _read("ea/Dockerfile.property")
    if not re.search(r"^FROM\s+\S+@sha256:[0-9a-f]{64}\s*$", dockerfile, flags=re.MULTILINE):
        failures.append("ea/Dockerfile.property must pin its base image by digest")
    if " docker.io" in dockerfile or "docker-compose" in dockerfile or "docker-29." in dockerfile:
        failures.append("ea/Dockerfile.property must not install Docker tooling")
    if not re.search(r"^USER\s+ea\s*$", dockerfile, flags=re.MULTILINE):
        failures.append("ea/Dockerfile.property must run as USER ea")
    if "requirements.lock" not in dockerfile or "-c requirements.lock" not in dockerfile:
        failures.append("ea/Dockerfile.property must install with requirements.lock constraints")
    if not re.search(r"image:\s+\S+@sha256:[0-9a-f]{64}", compose):
        failures.append("docker-compose.property.yml must pin sidecar images by digest")

    public_tours = _read("ea/app/api/routes/public_tours.py")
    if "tour-action-tokens" in public_tours or "tourActionTokens" in public_tours:
        failures.append("public tours must not emit bearer-style action tokens into HTML")
    if "record_property_feedback(" in public_tours:
        failures.append("public tour feedback must not directly mutate owner learning profiles")
    if "request_property_tour_detail_refresh(" in public_tours:
        failures.append("public tour request-details must not queue owner work from public links")
    if 'request.headers.get("x-forwarded-for")' in public_tours and "PROPERTYQUARRY_TRUST_X_FORWARDED_FOR" not in public_tours:
        failures.append("public tour feedback must not trust x-forwarded-for without explicit opt-in")
    if 'except Exception:\n        pass' in public_tours:
        failures.append("public tour feedback must not silently swallow persistence failures")
    if '"status": "not_captured"' not in public_tours:
        failures.append("public tour feedback must report persistence failures honestly")
    if "_redacted_public_tour_payload(payload, expose_asset_relpaths=False)" not in public_tours:
        failures.append("public tour JSON must use the redacted public payload builder")
    if "_PUBLIC_TOUR_DENIED_ASSET_EXTENSIONS" not in public_tours or "_public_tour_manifest(payload)" not in public_tours or "safe_relpath not in manifest" not in public_tours:
        failures.append("public tour file serving must use a manifest-backed asset allowlist with denied sidecar extensions")
    if "_public_tour_listing_research_url_allowed(normalized)" not in public_tours:
        failures.append("public render-time listing research must pass through the provider-host URL guard")
    if "_PUBLIC_TOUR_EXACT_LOCATION_FACT_KEYS" not in public_tours or "_redacted_public_tour_facts" not in public_tours:
        failures.append("public tour facts must use mode-aware exact-location redaction")
    if "_public_tour_external_media_url_allowed" not in public_tours:
        failures.append("public tour scene media must pass through the external-media URL guard")
    if "_PUBLIC_TOUR_PUBLIC_PDF_PRIVACY_CLASSES" not in public_tours or "floorplan_pdf_public" not in public_tours:
        failures.append("public tour PDFs must require an explicit public floorplan privacy class")
    if "PROPERTYQUARRY_PUBLIC_RATE_LIMIT_FAIL_CLOSED" not in public_tours or "_public_tour_prod_mode_enabled()" not in public_tours:
        failures.append("public tour durable rate-limit failures must fail closed in prod")
    if "_public_tour_security_headers" not in public_tours or "Content-Security-Policy" not in public_tours:
        failures.append("public tours must set public page/file security headers")

    requirements = _read("ea/requirements.txt")
    lock_text = _read("ea/requirements.lock")
    lock_names = _lock_package_names(lock_text)
    for line in requirements.splitlines():
        name = _normalized_requirement_name(line)
        if not name:
            continue
        if name.replace("_", "-") not in lock_names:
            failures.append(f"ea/requirements.lock missing direct requirement {name}")
    for line in lock_text.splitlines():
        raw = line.strip()
        if raw and not raw.startswith("#") and "==" not in raw:
            failures.append(f"ea/requirements.lock contains an unpinned row: {raw}")

    if failures:
        print("property security posture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property security posture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
