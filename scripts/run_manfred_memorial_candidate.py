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
from scripts.verify_manfred_memorial_candidate import verify_candidate  # noqa: E402


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_runtime.v1"
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
    if api.get("build") or api.get("container_name"):
        raise RuntimeError("manfred_candidate_compose_not_image_pure")
    if str(api.get("image") or "") != env["EA_MANFRED_IMAGE"]:
        raise RuntimeError("manfred_candidate_compose_image_mismatch")
    if str(api.get("pull_policy") or "") != "never":
        raise RuntimeError("manfred_candidate_compose_pull_policy_invalid")
    if api.get("read_only") is not True or str(api.get("user") or "") != "10001:10001":
        raise RuntimeError("manfred_candidate_compose_runtime_hardening_invalid")
    networks = dict(payload.get("networks") or {})
    if len(networks) != 1:
        raise RuntimeError("manfred_candidate_compose_network_invalid")
    network = dict(next(iter(networks.values())) or {})
    if network.get("internal") is not True or network.get("external") is True:
        raise RuntimeError("manfred_candidate_compose_network_not_isolated")
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
    logs = _run([*compose, "logs", "--no-color", "--tail", "1000", "api"], timeout=60)
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
    _assert_logs_clean(compose)
    live_after = _live_snapshot()
    _assert_live_unchanged(live_before, live_after)
    _assert_live_http()

    image_id = _run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", env["EA_MANFRED_IMAGE"]],
        timeout=30,
    ).decode().strip()
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "image": env["EA_MANFRED_IMAGE"],
        "image_id": image_id,
        "candidate_api_container_id": api_after_restart,
        "candidate_port": int(env["EA_MANFRED_HOST_PORT"]),
        "network_internal": True,
        "provider_credentials_present": False,
        "provider_calls_performed": False,
        "redis_ping": "PONG",
        "contribution_modes": contribution_modes,
        "contribution_survived_restart": bool(
            second_smoke.get("contribution", {}).get("survived_candidate_restart")
        ),
        "first_smoke_checks": first_smoke.get("checks", []),
        "second_smoke_checks": second_smoke.get("checks", []),
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
