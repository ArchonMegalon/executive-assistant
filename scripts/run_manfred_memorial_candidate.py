#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_manfred_memorial_candidate import _parse_env  # noqa: E402
from scripts.verify_manfred_memorial_candidate import (  # noqa: E402
    audit_browser_surface,
    verify_candidate,
)


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_runtime.v2"
ALLOWED_ENV_KEYS = {
    "DATABASE_URL",
    "EA_API_TOKEN",
    "EA_MANFRED_COMPOSE_PROJECT",
    "EA_MANFRED_ENV_FILE",
    "EA_MANFRED_HOST_PORT",
    "EA_MANFRED_IMAGE",
    "EA_MANFRED_POSTGRES_PASSWORD",
    "EA_MANFRED_RELEASE_ROOT",
    "EA_MANFRED_RUNTIME_ROOT",
    "EA_PUBLIC_APP_BASE_URL",
    "EA_SIGNING_SECRET",
}
FORBIDDEN_LOG_MARKERS = (
    "ImportError:",
    "ModuleNotFoundError:",
    "cannot import name",
)


def _run(argv: list[str], *, timeout: int = 300) -> bytes:
    completed = subprocess.run(
        argv,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return completed.stdout


def _compose_argv(env_file: Path, compose_file: Path, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--file",
        str(compose_file),
        *args,
    ]


def _live_snapshot() -> dict[str, object]:
    raw = _run(["docker", "inspect", "ea-api"], timeout=30)
    payload = json.loads(raw)
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError("manfred_candidate_live_snapshot_invalid")
    row = payload[0]
    state = dict(row.get("State") or {})
    health = dict(state.get("Health") or {})
    networks = sorted((row.get("NetworkSettings") or {}).get("Networks") or {})
    return {
        "container_id": str(row.get("Id") or ""),
        "image_id": str(row.get("Image") or ""),
        "started_at": str(state.get("StartedAt") or ""),
        "running": bool(state.get("Running")),
        "health": str(health.get("Status") or ""),
        "networks": networks,
    }


def _assert_live_unchanged(before: dict[str, object], after: dict[str, object]) -> None:
    for key in ("container_id", "image_id", "started_at", "networks"):
        if before.get(key) != after.get(key):
            raise RuntimeError(f"manfred_candidate_live_runtime_changed:{key}")
    if not after.get("running") or after.get("health") != "healthy":
        raise RuntimeError("manfred_candidate_live_runtime_unhealthy")


def _assert_live_http() -> None:
    request = urllib.request.Request("http://127.0.0.1:8090/healthz", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(response.status) != 200:
                raise RuntimeError("manfred_candidate_live_health_unexpected")
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_live_health_unreachable") from exc


def _candidate_runtime_source_revision(base_url: str) -> str:
    request = urllib.request.Request(
        f"{str(base_url or '').rstrip('/')}/memorials/manfred.json",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(response.status or 0) != 200:
                raise RuntimeError("manfred_candidate_runtime_revision_probe_status")
            revision = str(
                response.headers.get("X-EA-Source-Revision") or ""
            ).strip()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_runtime_revision_unreachable") from exc
    if len(revision) != 40 or revision != revision.lower() or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise RuntimeError("manfred_candidate_runtime_revision_invalid")
    return revision


def _rendered_compose(env_file: Path, compose_file: Path) -> dict[str, object]:
    raw = _run(
        _compose_argv(env_file, compose_file, "config", "--format", "json"),
        timeout=60,
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_candidate_compose_invalid")
    return payload


def _assert_compose_isolation(
    payload: dict[str, object], *, env: dict[str, str]
) -> None:
    services = dict(payload.get("services") or {})
    api = dict(services.get("api") or {})
    gateway = dict(services.get("gateway") or {})
    if api.get("build") or api.get("container_name"):
        raise RuntimeError("manfred_candidate_compose_not_image_pure")
    if str(api.get("image") or "") != env["EA_MANFRED_IMAGE"]:
        raise RuntimeError("manfred_candidate_compose_image_mismatch")
    if str(api.get("pull_policy") or "") != "never":
        raise RuntimeError("manfred_candidate_compose_pull_policy_invalid")
    if api.get("read_only") is not True or str(api.get("user") or "") != "10001:10001":
        raise RuntimeError("manfred_candidate_compose_runtime_hardening_invalid")
    networks = dict(payload.get("networks") or {})
    if set(networks) != {"backend", "ingress"}:
        raise RuntimeError("manfred_candidate_compose_network_invalid")
    backend = dict(networks.get("backend") or {})
    ingress = dict(networks.get("ingress") or {})
    if backend.get("internal") is not True or backend.get("external") is True:
        raise RuntimeError("manfred_candidate_compose_network_not_isolated")
    if ingress.get("internal") is True or ingress.get("external") is True:
        raise RuntimeError("manfred_candidate_compose_ingress_invalid")

    def network_names(service: dict[str, object]) -> set[str]:
        configured = service.get("networks") or {}
        if isinstance(configured, dict):
            return {str(name) for name in configured}
        if isinstance(configured, list):
            return {str(name) for name in configured}
        return set()

    if network_names(api) != {"backend"}:
        raise RuntimeError("manfred_candidate_api_egress_not_isolated")
    if network_names(dict(services.get("postgres") or {})) != {"backend"}:
        raise RuntimeError("manfred_candidate_postgres_network_invalid")
    if network_names(dict(services.get("redis") or {})) != {"backend"}:
        raise RuntimeError("manfred_candidate_redis_network_invalid")
    if network_names(gateway) != {"backend", "ingress"}:
        raise RuntimeError("manfred_candidate_gateway_network_invalid")
    if str(gateway.get("image") or "") != env["EA_MANFRED_IMAGE"]:
        raise RuntimeError("manfred_candidate_gateway_image_mismatch")
    if gateway.get("env_file") or gateway.get("environment"):
        raise RuntimeError("manfred_candidate_gateway_secret_scope_invalid")
    gateway_ports = list(gateway.get("ports") or [])
    if len(gateway_ports) != 1 or not isinstance(gateway_ports[0], dict):
        raise RuntimeError("manfred_candidate_gateway_port_invalid")
    gateway_port = gateway_ports[0]
    if (
        str(gateway_port.get("host_ip") or "") != "127.0.0.1"
        or int(gateway_port.get("target") or 0) != 18090
        or int(gateway_port.get("published") or 0)
        != int(env["EA_MANFRED_HOST_PORT"])
    ):
        raise RuntimeError("manfred_candidate_gateway_port_invalid")
    for service in services.values():
        service_payload = dict(service or {})
        if service_payload.get("build") or service_payload.get("container_name"):
            raise RuntimeError("manfred_candidate_compose_service_not_isolated")
        for mount in list(service_payload.get("volumes") or []):
            if not isinstance(mount, dict):
                continue
            source = str(mount.get("source") or "")
            if source.startswith("/docker/EA") or source == "/var/run/docker.sock":
                raise RuntimeError("manfred_candidate_compose_live_bind_forbidden")


def _assert_env_allowlist(env_file: Path) -> dict[str, str]:
    env = _parse_env(env_file)
    if set(env) != ALLOWED_ENV_KEYS:
        raise RuntimeError("manfred_candidate_env_allowlist_invalid")
    for name in ("EA_API_TOKEN", "EA_SIGNING_SECRET", "EA_MANFRED_POSTGRES_PASSWORD"):
        if len(env.get(name, "")) < 40:
            raise RuntimeError("manfred_candidate_env_secret_invalid")
    if env["EA_MANFRED_IMAGE"].lower().endswith(":latest"):
        raise RuntimeError("manfred_candidate_image_mutable")
    return env


def _assert_redis(compose: list[str]) -> None:
    response = _run([*compose, "exec", "-T", "redis", "redis-cli", "ping"], timeout=30)
    if response.decode("utf-8", errors="replace").strip() != "PONG":
        raise RuntimeError("manfred_candidate_redis_unavailable")


def _assert_contribution_modes(compose: list[str]) -> dict[str, str]:
    command = (
        "private=/data/memorial/private-contributions/manfred/family_contributions.json; "
        "public=/data/memorial/public-contributions/manfred/family_contributions.public.json; "
        "test -f \"$private\"; test -f \"$public\"; "
        "printf '%s %s' \"$(stat -c %a \"$private\")\" \"$(stat -c %a \"$public\")\""
    )
    raw = _run([*compose, "exec", "-T", "api", "/bin/sh", "-ec", command], timeout=30)
    private_mode, public_mode = raw.decode("ascii").strip().split()
    if private_mode != "600" or public_mode != "644":
        raise RuntimeError("manfred_candidate_contribution_permissions_invalid")
    return {"private_ledger": private_mode, "public_projection": public_mode}


def _assert_logs_clean(compose: list[str]) -> None:
    logs = _run(
        [*compose, "logs", "--no-color", "--tail", "1000", "api", "gateway"],
        timeout=60,
    )
    text = logs.decode("utf-8", errors="replace")
    if any(marker in text for marker in FORBIDDEN_LOG_MARKERS):
        raise RuntimeError("manfred_candidate_import_failure_in_logs")


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def prove_candidate(
    *,
    env_file: Path,
    compose_file: Path,
    receipt_path: Path,
    wait_seconds: int,
) -> dict[str, object]:
    env_file = env_file.expanduser().resolve()
    compose_file = compose_file.expanduser().resolve()
    env = _assert_env_allowlist(env_file)
    rendered = _rendered_compose(env_file, compose_file)
    _assert_compose_isolation(rendered, env=env)
    live_before = _live_snapshot()
    _assert_live_http()
    compose = _compose_argv(env_file, compose_file)
    _run(
        [*compose, "up", "-d", "--wait", "--wait-timeout", str(wait_seconds)],
        timeout=wait_seconds + 60,
    )
    _assert_redis(compose)

    base_url = f"http://127.0.0.1:{env['EA_MANFRED_HOST_PORT']}"
    contribution_receipt = receipt_path.parent / "candidate-contribution.private.json"
    first_smoke = verify_candidate(
        base_url=base_url,
        public_origin=env["EA_PUBLIC_APP_BASE_URL"],
        wait_seconds=wait_seconds,
        submit_receipt=contribution_receipt,
        withdraw_receipt=None,
    )
    api_before_restart = _run([*compose, "ps", "-q", "api"], timeout=30).decode().strip()
    if not api_before_restart:
        raise RuntimeError("manfred_candidate_api_missing")
    _run([*compose, "restart", "api"], timeout=90)
    second_smoke = verify_candidate(
        base_url=base_url,
        public_origin=env["EA_PUBLIC_APP_BASE_URL"],
        wait_seconds=wait_seconds,
        submit_receipt=None,
        withdraw_receipt=contribution_receipt,
    )
    api_after_restart = _run([*compose, "ps", "-q", "api"], timeout=30).decode().strip()
    if api_after_restart != api_before_restart:
        raise RuntimeError("manfred_candidate_restart_recreated_container")
    _assert_redis(compose)
    contribution_modes = _assert_contribution_modes(compose)
    browser_surface = audit_browser_surface(base_url)
    _assert_logs_clean(compose)
    live_after = _live_snapshot()
    _assert_live_unchanged(live_before, live_after)
    _assert_live_http()

    raw_image_inspection = _run(
        ["docker", "image", "inspect", env["EA_MANFRED_IMAGE"]], timeout=30
    )
    image_rows = json.loads(raw_image_inspection)
    if (
        not isinstance(image_rows, list)
        or len(image_rows) != 1
        or not isinstance(image_rows[0], dict)
    ):
        raise RuntimeError("manfred_candidate_image_inspection_invalid")
    image_inspection = dict(image_rows[0])
    image_id = str(image_inspection.get("Id") or "").strip()
    image_labels = dict((image_inspection.get("Config") or {}).get("Labels") or {})
    image_source_revision = str(
        image_labels.get("org.opencontainers.image.revision") or ""
    ).strip()
    runtime_source_revision = _candidate_runtime_source_revision(base_url)
    if runtime_source_revision != image_source_revision:
        raise RuntimeError("manfred_candidate_runtime_revision_image_mismatch")
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "image": env["EA_MANFRED_IMAGE"],
        "image_id": image_id,
        "image_source_revision": image_source_revision,
        "runtime_source_revision": runtime_source_revision,
        "runtime_revision_matches_image": True,
        "candidate_api_container_id": api_after_restart,
        "candidate_port": int(env["EA_MANFRED_HOST_PORT"]),
        "api_network_internal": True,
        "gateway_has_runtime_secrets": False,
        "provider_credentials_present": False,
        "provider_calls_performed": False,
        "redis_ping": "PONG",
        "contribution_modes": contribution_modes,
        "contribution_survived_restart": bool(
            second_smoke.get("contribution", {}).get("survived_candidate_restart")
        ),
        "first_smoke_checks": first_smoke.get("checks", []),
        "second_smoke_checks": second_smoke.get("checks", []),
        "browser_surface": browser_surface,
        "live_ea_api_unchanged": True,
        "live_ea_api": live_after,
        "candidate_left_running_for_soak": True,
        "promotion_authority": False,
    }
    _atomic_receipt(receipt_path, receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Launch and prove the isolated provider-free Manfred candidate."
    )
    parser.add_argument("--env-file", required=True)
    parser.add_argument(
        "--compose-file",
        default=str(root / "deploy/manfred-memorial/docker-compose.candidate.yml"),
    )
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--wait-seconds", type=int, default=240)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = prove_candidate(
            env_file=Path(args.env_file),
            compose_file=Path(args.compose_file),
            receipt_path=Path(args.receipt).expanduser().resolve(),
            wait_seconds=max(60, min(600, int(args.wait_seconds))),
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "live_ea_api_mutation_requested": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
