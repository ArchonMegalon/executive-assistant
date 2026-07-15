from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "scripts" / "codexea"


def _runtime_env_file(tmp_path: Path) -> Path:
    path = tmp_path / "codexea-harness-runtime.ea.env"
    path.write_text(
        "CODEXEA_ALLOW_ENV_MODEL_OVERRIDE=1\nCODEXEA_NICE=3\n",
        encoding="utf-8",
    )
    return path


def _fake_codex(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, sys",
                "nice_value = os.getpriority(os.PRIO_PROCESS, 0)",
                "state_dir = os.environ.get('CODEXEA_STATE_DIR', '')",
                "receipt_path = os.path.join(state_dir, 'launch-latest.json') if state_dir else ''",
                "launch_receipt = None",
                "if receipt_path and os.path.exists(receipt_path):",
                "    with open(receipt_path, encoding='utf-8') as handle:",
                "        launch_receipt = json.load(handle)",
                "keys = [",
                "  'EA_API_TOKEN',",
                "  'EA_MCP_API_TOKEN',",
                "  'EA_BASE_URL',",
                "  'EA_MCP_MODEL',",
                "  'EA_MCP_BASE_URL',",
                "  'EA_PRINCIPAL_ID',",
                "  'EA_MCP_PRINCIPAL_ID',",
                "  'CODEXEA_MODEL_STACK',",
                "  'CODEXEA_ORIGINAL_CWD',",
                "  'CODEXEA_REPO_ROOT',",
                "  'HOME',",
                "  'XDG_CACHE_HOME',",
                "  'XDG_CONFIG_HOME',",
                "]",
                "args = sys.argv[1:]",
                "for index, arg in enumerate(args):",
                "    if arg in {'-C', '--cd'} and index + 1 < len(args):",
                "        os.chdir(args[index + 1])",
                "        break",
                "    if arg.startswith('--cd='):",
                "        os.chdir(arg.split('=', 1)[1])",
                "        break",
                "print(json.dumps({'argv': args, 'cwd': os.getcwd(), 'env': {k: os.environ.get(k, '') for k in keys}, 'launch_receipt': launch_receipt, 'nice': nice_value}, sort_keys=True))",
            ]
        ),
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


def _run_shim(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "CODEXEA_RUNTIME_EA_ENV_PATH",
            "FLEET_RUNTIME_EA_ENV_PATH",
            "CODEXEA_ALLOW_CWD_RUNTIME_ENV",
            "EA_API_TOKEN",
            "EA_MCP_API_TOKEN",
            "EA_BASE_URL",
            "EA_MCP_MODEL",
            "EA_MCP_BASE_URL",
            "CODEXEA_STATUS_URL",
            "CODEXEA_PROFILES_URL",
            "EA_PRINCIPAL_ID",
            "EA_MCP_PRINCIPAL_ID",
            "CODEXEA_REAL_CODEX",
            "CODEX_REAL_BIN",
            "CODEXEA_USE_LIVE_PROFILE_MODELS",
            "CODEXEA_POST_AUDIT",
            "CODEXEA_TRACE_STARTUP",
            "CODEXEA_NO_ALT_SCREEN",
            "CODEXEA_STARTUP_STATUS",
            "CODEXEA_STATE_DIR",
            "CODEXEA_NICE",
            "CODEXEA_MODEL_CATALOG_JSON",
            "CODEXEA_MODELS_CACHE_PATH",
            "CODEXEA_BOOTSTRAP",
            "CODEXEA_BOOTSTRAP_PROMPT_FILE",
            "CODEXEA_MODE",
            "CODEXEA_MODEL",
            "CODEXEA_WORKER_MODEL",
            "CODEXEA_IMPLEMENT_MODEL",
            "CODEXEA_CONTROLLER_MODEL",
            "CODEXEA_CORE_MODEL",
            "CODEXEA_REPAIR_MODEL",
            "CODEXEA_EASY_MODEL",
            "CODEXEA_EASY_MCP_MODEL",
            "CODEXEA_EASY_SUBMODE",
            "CODEXEA_GROUNDWORK_MODEL",
            "CODEXEA_REVIEW_LIGHT_MODEL",
            "CODEXEA_JURY_MODEL",
            "CODEXEA_POST_AUDIT_MODEL",
            "CODEXEA_ONEMIN_DISPLAY_MODEL",
            "CODEXEA_ONEMIN_METADATA_SOURCE_MODEL",
            "CODEXEA_RESUME_INJECT_MODEL",
            "CODEXEA_ALLOW_ENV_MODEL_OVERRIDE",
            "ONEMIN_DEFAULT_PASSWORD",
            "BROWSERACT_PASSWORD",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
        }
        and not key.startswith("CODEXEA_CONTRACT_")
        and not key.startswith("ONEMIN_AI_API_KEY")
    }
    env.update(
        {
            "CODEXEA_REAL_CODEX": str(_fake_codex(tmp_path)),
            "CODEXEA_RUNTIME_EA_ENV_PATH": str(_runtime_env_file(tmp_path)),
            "CODEXEA_ONEMIN_DISPLAY_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_IMPLEMENT_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_WORKER_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_CONTROLLER_MODEL": "gpt-5.5",
            "CODEXEA_ALLOW_ENV_MODEL_OVERRIDE": "1",
            "CODEXEA_USE_LIVE_PROFILE_MODELS": "0",
            "CODEXEA_POST_AUDIT": "0",
            "CODEXEA_TRACE_STARTUP": "0",
            "CODEXEA_NO_ALT_SCREEN": "0",
            "CODEXEA_STARTUP_STATUS": "0",
            "CODEXEA_STATE_DIR": str(tmp_path / "state"),
            "CODEXEA_MODEL_CATALOG_JSON": "0",
        }
    )
    if extra_env:
        env.update(extra_env)

    completed = subprocess.run(
        [str(SHIM), *args],
        cwd=cwd or ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _run_shim_stdout(tmp_path: Path, *args: str, extra_env: dict[str, str] | None = None) -> str:
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "CODEXEA_RUNTIME_EA_ENV_PATH",
            "FLEET_RUNTIME_EA_ENV_PATH",
            "CODEXEA_ALLOW_CWD_RUNTIME_ENV",
            "EA_API_TOKEN",
            "EA_MCP_API_TOKEN",
            "EA_BASE_URL",
            "EA_MCP_BASE_URL",
            "CODEXEA_STATUS_URL",
            "CODEXEA_PROFILES_URL",
            "EA_PRINCIPAL_ID",
            "EA_MCP_PRINCIPAL_ID",
            "CODEXEA_REAL_CODEX",
            "CODEX_REAL_BIN",
            "CODEXEA_USE_LIVE_PROFILE_MODELS",
            "CODEXEA_POST_AUDIT",
            "CODEXEA_TRACE_STARTUP",
            "CODEXEA_NO_ALT_SCREEN",
            "CODEXEA_STARTUP_STATUS",
            "CODEXEA_STATE_DIR",
            "CODEXEA_NICE",
            "CODEXEA_MODEL_CATALOG_JSON",
            "CODEXEA_MODELS_CACHE_PATH",
            "CODEXEA_BOOTSTRAP",
            "CODEXEA_BOOTSTRAP_PROMPT_FILE",
            "CODEXEA_MODE",
            "CODEXEA_MODEL",
            "CODEXEA_WORKER_MODEL",
            "CODEXEA_IMPLEMENT_MODEL",
            "CODEXEA_CONTROLLER_MODEL",
            "CODEXEA_CORE_MODEL",
            "CODEXEA_REPAIR_MODEL",
            "CODEXEA_EASY_MODEL",
            "CODEXEA_EASY_MCP_MODEL",
            "CODEXEA_EASY_SUBMODE",
            "CODEXEA_GROUNDWORK_MODEL",
            "CODEXEA_REVIEW_LIGHT_MODEL",
            "CODEXEA_JURY_MODEL",
            "CODEXEA_POST_AUDIT_MODEL",
            "CODEXEA_ONEMIN_DISPLAY_MODEL",
            "CODEXEA_ONEMIN_METADATA_SOURCE_MODEL",
            "CODEXEA_RESUME_INJECT_MODEL",
            "CODEXEA_ALLOW_ENV_MODEL_OVERRIDE",
            "ONEMIN_DEFAULT_PASSWORD",
            "BROWSERACT_PASSWORD",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
        }
        and not key.startswith("CODEXEA_CONTRACT_")
        and not key.startswith("ONEMIN_AI_API_KEY")
    }
    env.update(
        {
            "CODEXEA_REAL_CODEX": str(_fake_codex(tmp_path)),
            "CODEXEA_RUNTIME_EA_ENV_PATH": str(_runtime_env_file(tmp_path)),
            "CODEXEA_ONEMIN_DISPLAY_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_IMPLEMENT_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_WORKER_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_CONTROLLER_MODEL": "gpt-5.5",
            "CODEXEA_ALLOW_ENV_MODEL_OVERRIDE": "1",
            "CODEXEA_USE_LIVE_PROFILE_MODELS": "0",
            "CODEXEA_POST_AUDIT": "0",
            "CODEXEA_TRACE_STARTUP": "0",
            "CODEXEA_NO_ALT_SCREEN": "0",
            "CODEXEA_STARTUP_STATUS": "0",
            "CODEXEA_STATE_DIR": str(tmp_path / "state"),
            "CODEXEA_MODEL_CATALOG_JSON": "0",
        }
    )
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        [str(SHIM), *args],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _run_shim_completed(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "CODEXEA_RUNTIME_EA_ENV_PATH",
            "FLEET_RUNTIME_EA_ENV_PATH",
            "CODEXEA_ALLOW_CWD_RUNTIME_ENV",
            "EA_API_TOKEN",
            "EA_MCP_API_TOKEN",
            "EA_BASE_URL",
            "EA_MCP_BASE_URL",
            "CODEXEA_STATUS_URL",
            "CODEXEA_PROFILES_URL",
            "EA_PRINCIPAL_ID",
            "EA_MCP_PRINCIPAL_ID",
            "CODEXEA_REAL_CODEX",
            "CODEX_REAL_BIN",
            "CODEXEA_USE_LIVE_PROFILE_MODELS",
            "CODEXEA_POST_AUDIT",
            "CODEXEA_TRACE_STARTUP",
            "CODEXEA_NO_ALT_SCREEN",
            "CODEXEA_STARTUP_STATUS",
            "CODEXEA_STATE_DIR",
            "CODEXEA_NICE",
            "CODEXEA_MODEL_CATALOG_JSON",
            "CODEXEA_MODELS_CACHE_PATH",
            "CODEXEA_BOOTSTRAP",
            "CODEXEA_BOOTSTRAP_PROMPT_FILE",
            "CODEXEA_MODEL",
            "CODEXEA_WORKER_MODEL",
            "CODEXEA_IMPLEMENT_MODEL",
            "CODEXEA_CONTROLLER_MODEL",
            "CODEXEA_CORE_MODEL",
            "CODEXEA_REPAIR_MODEL",
            "CODEXEA_EASY_MODEL",
            "CODEXEA_GROUNDWORK_MODEL",
            "CODEXEA_REVIEW_LIGHT_MODEL",
            "CODEXEA_JURY_MODEL",
            "CODEXEA_POST_AUDIT_MODEL",
            "CODEXEA_ONEMIN_DISPLAY_MODEL",
            "CODEXEA_ONEMIN_METADATA_SOURCE_MODEL",
            "CODEXEA_RESUME_INJECT_MODEL",
            "CODEXEA_ALLOW_ENV_MODEL_OVERRIDE",
            "ONEMIN_DEFAULT_PASSWORD",
            "BROWSERACT_PASSWORD",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
        }
        and not key.startswith("CODEXEA_CONTRACT_")
        and not key.startswith("ONEMIN_AI_API_KEY")
    }
    env.update(
        {
            "CODEXEA_REAL_CODEX": str(_fake_codex(tmp_path)),
            "CODEXEA_RUNTIME_EA_ENV_PATH": str(_runtime_env_file(tmp_path)),
            "CODEXEA_ONEMIN_DISPLAY_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_IMPLEMENT_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_WORKER_MODEL": "ChatGPT 5.5 (1min.ai)",
            "CODEXEA_CONTROLLER_MODEL": "gpt-5.5",
            "CODEXEA_ALLOW_ENV_MODEL_OVERRIDE": "1",
            "CODEXEA_USE_LIVE_PROFILE_MODELS": "0",
            "CODEXEA_POST_AUDIT": "0",
            "CODEXEA_TRACE_STARTUP": "0",
            "CODEXEA_NO_ALT_SCREEN": "0",
            "CODEXEA_STARTUP_STATUS": "0",
            "CODEXEA_STATE_DIR": str(tmp_path / "state"),
            "CODEXEA_MODEL_CATALOG_JSON": "0",
        }
    )
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [str(SHIM), *args],
        cwd=cwd or ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _bootstrap_prompt_file(tmp_path: Path) -> Path:
    bootstrap = tmp_path / "interactive-bootstrap.md"
    bootstrap.write_text(
        "WAIT_ONLY_BOOTSTRAP: ready and waiting for user instructions.",
        encoding="utf-8",
    )
    return bootstrap


def test_responses_lane_launches_with_ea_provider_config_and_runtime_env(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.ea.env"
    runtime_env.write_text(
        "\n".join(
            [
                "EA_MCP_BASE_URL=http://ea-runtime.test:8090",
                "EA_MCP_API_TOKEN=file-token",
                "EA_MCP_PRINCIPAL_ID=runtime-principal",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_shim(
        tmp_path,
        "core",
        "inspect launch",
        extra_env={"CODEXEA_RUNTIME_EA_ENV_PATH": str(runtime_env)},
    )

    argv = result["argv"]
    assert isinstance(argv, list)
    assert "-c" in argv
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert 'model_provider="ea"' in rendered_args
    assert 'model_providers.ea.base_url="http://ea-runtime.test:8090/v1"' in rendered_args
    assert '"Authorization"="Bearer file-token"' in rendered_args
    assert argv[-2] == "exec"
    assert "inspect launch" in str(argv[-1])

    env = result["env"]
    assert isinstance(env, dict)
    assert env["EA_MCP_API_TOKEN"] == "file-token"
    assert env["EA_API_TOKEN"] == "file-token"
    assert env["EA_MCP_PRINCIPAL_ID"] == "runtime-principal"


def test_worker_launch_inherits_default_codexea_niceness(tmp_path: Path) -> None:
    ps_marker = tmp_path / "ps-invoked"
    renice_marker = tmp_path / "renice-args"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_ps = fake_bin / "ps"
    fake_ps.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        ': > "${CODEXEA_PS_MARKER:?}"\n'
        "printf '0\\n'\n",
        encoding="utf-8",
    )
    fake_ps.chmod(fake_ps.stat().st_mode | stat.S_IXUSR)
    fake_renice = fake_bin / "renice"
    fake_renice.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$@" > "${CODEXEA_RENICE_MARKER:?}"\n',
        encoding="utf-8",
    )
    fake_renice.chmod(fake_renice.stat().st_mode | stat.S_IXUSR)

    _run_shim(
        tmp_path,
        "worker",
        "nice check",
        extra_env={
            "CODEXEA_PS_MARKER": str(ps_marker),
            "CODEXEA_RENICE_MARKER": str(renice_marker),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert ps_marker.exists()
    renice_args = renice_marker.read_text(encoding="utf-8").splitlines()
    assert renice_args[:3] == ["--priority", "3", "--pid"]
    assert len(renice_args) == 4
    assert renice_args[3].isdigit()


def test_worker_launch_never_attempts_to_raise_inherited_priority(tmp_path: Path) -> None:
    ps_marker = tmp_path / "ps-invoked"
    renice_marker = tmp_path / "renice-invoked"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_ps = fake_bin / "ps"
    fake_ps.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        ': > "${CODEXEA_PS_MARKER:?}"\n'
        "printf '10\\n'\n",
        encoding="utf-8",
    )
    fake_ps.chmod(fake_ps.stat().st_mode | stat.S_IXUSR)
    fake_renice = fake_bin / "renice"
    fake_renice.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        ': > "${CODEXEA_RENICE_MARKER:?}"\n',
        encoding="utf-8",
    )
    fake_renice.chmod(fake_renice.stat().st_mode | stat.S_IXUSR)

    _run_shim(
        tmp_path,
        "worker",
        "monotonic nice check",
        extra_env={
            "CODEXEA_NICE": "3",
            "CODEXEA_PS_MARKER": str(ps_marker),
            "CODEXEA_RENICE_MARKER": str(renice_marker),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert ps_marker.exists()
    assert not renice_marker.exists()


def test_explicit_auth_env_is_not_overwritten_by_runtime_file(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.ea.env"
    runtime_env.write_text(
        "\n".join(
            [
                "EA_MCP_BASE_URL=http://ea-runtime.test:8090",
                "EA_MCP_API_TOKEN=file-token",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_shim(
        tmp_path,
        "core",
        "auth check",
        extra_env={
            "CODEXEA_RUNTIME_EA_ENV_PATH": str(runtime_env),
            "EA_MCP_API_TOKEN": "caller-token",
        },
    )

    env = result["env"]
    assert isinstance(env, dict)
    assert env["EA_MCP_API_TOKEN"] == "caller-token"
    assert env["EA_API_TOKEN"] == "caller-token"
    assert "Bearer caller-token" in "\n".join(str(arg) for arg in result["argv"])
    assert "Bearer file-token" not in "\n".join(str(arg) for arg in result["argv"])


def test_runtime_env_candidate_precedence_is_stable(tmp_path: Path) -> None:
    primary_runtime_env = tmp_path / "primary-runtime.ea.env"
    primary_runtime_env.write_text(
        "\n".join(
            [
                "EA_MCP_BASE_URL=http://primary-runtime.test:8090",
                "EA_MCP_API_TOKEN=primary-token",
            ]
        ),
        encoding="utf-8",
    )
    secondary_runtime_env = tmp_path / "secondary-runtime.ea.env"
    secondary_runtime_env.write_text(
        "\n".join(
            [
                "EA_MCP_BASE_URL=http://secondary-runtime.test:8090",
                "EA_MCP_API_TOKEN=secondary-token",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_shim(
        tmp_path,
        "core",
        "precedence check",
        extra_env={
            "CODEXEA_RUNTIME_EA_ENV_PATH": str(primary_runtime_env),
            "FLEET_RUNTIME_EA_ENV_PATH": str(secondary_runtime_env),
        },
    )

    env = result["env"]
    assert isinstance(env, dict)
    assert env["EA_MCP_API_TOKEN"] == "primary-token"
    assert env["EA_API_TOKEN"] == "primary-token"
    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert 'model_providers.ea.base_url="http://primary-runtime.test:8090/v1"' in rendered_args
    assert "secondary-runtime.test" not in rendered_args


def test_runtime_env_later_nonempty_token_overrides_earlier_empty_placeholder(tmp_path: Path) -> None:
    primary_runtime_env = tmp_path / "primary-runtime.ea.env"
    primary_runtime_env.write_text(
        "\n".join(
            [
                "EA_MCP_API_TOKEN=",
                "EA_API_TOKEN=",
            ]
        ),
        encoding="utf-8",
    )
    secondary_runtime_env = tmp_path / "secondary-runtime.ea.env"
    secondary_runtime_env.write_text(
        "\n".join(
            [
                "EA_MCP_API_TOKEN=secondary-token",
                "EA_API_TOKEN=secondary-token",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_shim(
        tmp_path,
        "core",
        "empty placeholder fallback check",
        extra_env={
            "CODEXEA_RUNTIME_EA_ENV_PATH": str(primary_runtime_env),
            "FLEET_RUNTIME_EA_ENV_PATH": str(secondary_runtime_env),
        },
    )

    env = result["env"]
    assert isinstance(env, dict)
    assert env["EA_MCP_API_TOKEN"] == "secondary-token"
    assert env["EA_API_TOKEN"] == "secondary-token"
    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert "Bearer secondary-token" in rendered_args


def test_eta_does_not_fall_through_into_worker_launch(tmp_path: Path) -> None:
    completed = _run_shim_completed(
        tmp_path,
        "eta",
        extra_env={
            "CODEXEA_STATUS_URL": "http://127.0.0.1:1/v1/codex/status",
            "CODEXEA_PROFILES_URL": "http://127.0.0.1:1/v1/codex/profiles",
        },
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "EA status unavailable" in completed.stderr
    assert "OpenAI Codex" not in completed.stderr
    assert "worker contract" not in completed.stderr


def test_startup_status_failure_prints_pending_route_instead_of_error(tmp_path: Path) -> None:
    completed = _run_shim_completed(
        tmp_path,
        "status",
        "--startup",
        extra_env={
            "CODEXEA_STATUS_URL": "http://127.0.0.1:1/v1/codex/status",
            "CODEXEA_PROFILES_URL": "http://127.0.0.1:1/v1/codex/profiles",
        },
    )

    assert completed.returncode == 0
    assert "CodexEA startup: lane unknown | provider unknown via 1min.AI manager | model unknown | mode unknown | status pending" in completed.stdout
    assert "EA status unavailable" not in completed.stderr
    assert "OpenAI Codex" not in completed.stderr


def test_startup_status_surfaces_onemin_pressure_when_available(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "providers_summary": [
                    {"provider_name": "1min", "account_name": "ONEMIN_AI_API_KEY", "state": "ready"},
                    {"provider_name": "1min", "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "state": "degraded"},
                ],
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 6100}}},
                "onemin_aggregate": {"attempt_throttle_pressure_15m": "high"},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--startup",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=1" in path for path in observed_paths)
    assert "1h 1min burn 6100 cr | 1min pressure high" in completed.stdout


def test_startup_status_can_tolerate_slow_but_healthy_status_endpoint(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            import time

            observed_paths.append(self.path)
            time.sleep(6.0)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "providers_summary": [
                    {"provider_name": "1min", "account_name": "ONEMIN_AI_API_KEY", "state": "ready"},
                ],
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 42}}},
                "onemin_aggregate": {"attempt_throttle_pressure_15m": "low"},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--startup",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=1" in path for path in observed_paths)
    assert "CodexEA startup:" in completed.stdout
    assert "1h 1min burn 42 cr | 1min pressure low" in completed.stdout
    assert "status pending" not in completed.stdout


def test_startup_status_uses_short_ttl_cache_without_refresh(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "providers_summary": [
                    {"provider_name": "1min", "account_name": "ONEMIN_AI_API_KEY", "state": "ready"},
                ],
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 123}}},
                "onemin_aggregate": {"attempt_throttle_pressure_15m": "low"},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first = _run_shim_completed(
            tmp_path,
            "status",
            "--startup",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_STARTUP_STATUS_CACHE_TTL_SECONDS": "60",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    second = _run_shim_completed(
        tmp_path,
        "status",
        "--startup",
        extra_env={
            "CODEXEA_STATUS_URL": "http://127.0.0.1:1/v1/codex/status",
            "CODEXEA_PROFILES_URL": "http://127.0.0.1:1/v1/codex/profiles",
            "CODEXEA_STARTUP_STATUS_CACHE_TTL_SECONDS": "60",
        },
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert any("compact=1" in path for path in observed_paths)
    assert len(observed_paths) == 1
    assert "1h 1min burn 123 cr | 1min pressure low" in first.stdout
    assert second.stdout == first.stdout
    assert second.stderr == ""


def test_startup_status_refresh_bypasses_short_ttl_cache(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "providers_summary": [
                    {"provider_name": "1min", "account_name": "ONEMIN_AI_API_KEY", "state": "ready"},
                ],
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 321}}},
                "onemin_aggregate": {"attempt_throttle_pressure_15m": "medium"},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first = _run_shim_completed(
            tmp_path,
            "status",
            "--startup",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_STARTUP_STATUS_CACHE_TTL_SECONDS": "60",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    second = _run_shim_completed(
        tmp_path,
        "status",
        "--startup",
        "--refresh",
        extra_env={
            "CODEXEA_STATUS_URL": "http://127.0.0.1:1/v1/codex/status",
            "CODEXEA_PROFILES_URL": "http://127.0.0.1:1/v1/codex/profiles",
            "CODEXEA_STARTUP_STATUS_CACHE_TTL_SECONDS": "60",
        },
    )

    assert first.returncode == 0
    assert "1h 1min burn 321 cr | 1min pressure medium" in first.stdout
    assert second.returncode == 0
    assert "status pending" in second.stdout
    assert second.stdout != first.stdout


def test_startup_status_compact_payload_without_default_route_uses_workspace_fallback(
    tmp_path: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            payload = {
                "providers_summary": [
                    {"provider_name": "1min", "account_name": "ONEMIN_AI_API_KEY", "state": "ready"},
                ],
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 9}}},
                "onemin_aggregate": {"attempt_throttle_pressure_15m": "low"},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--startup",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "EA_MCP_PRINCIPAL_ID": "principal-test",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert "CodexEA startup: workspace EA | principal principal-test | ready 1 | degraded 0 | cooldown 0 | 1h 1min burn 9 cr | 1min pressure low" in completed.stdout
    assert "lane n/a->n/a" not in completed.stdout


def test_installed_launcher_startup_status_prints_pending_route_instead_of_error(
    tmp_path: Path,
) -> None:
    install_home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(install_home)
    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()

    completed = subprocess.run(
        [
            str(launcher),
            "status",
            "--startup",
        ],
        cwd=ROOT,
        env=_codexea_launcher_env(
            runtime_home,
            CODEXEA_REAL_CODEX=str(_fake_codex(tmp_path)),
            CODEXEA_RUNTIME_EA_ENV_PATH=str(_runtime_env_file(tmp_path)),
            CODEXEA_STATUS_URL="http://127.0.0.1:1/v1/codex/status",
            CODEXEA_PROFILES_URL="http://127.0.0.1:1/v1/codex/profiles",
            CODEXEA_ONEMIN_DISPLAY_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_IMPLEMENT_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_WORKER_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_CONTROLLER_MODEL="gpt-5.5",
            CODEXEA_ALLOW_ENV_MODEL_OVERRIDE="1",
            CODEXEA_USE_LIVE_PROFILE_MODELS="0",
            CODEXEA_POST_AUDIT="0",
            CODEXEA_TRACE_STARTUP="0",
            CODEXEA_STARTUP_STATUS="0",
            CODEXEA_MODEL_CATALOG_JSON="0",
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "CodexEA startup: lane unknown | provider unknown via 1min.AI manager | model unknown | mode unknown | status pending" in completed.stdout
    assert completed.stderr == ""


def test_installed_launcher_startup_status_surfaces_onemin_pressure_when_available(
    tmp_path: Path,
) -> None:
    install_home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(install_home)
    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "providers_summary": [
                    {"provider_name": "1min", "account_name": "ONEMIN_AI_API_KEY", "state": "ready"},
                ],
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 77}}},
                "onemin_aggregate": {"attempt_throttle_pressure_15m": "medium"},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = subprocess.run(
            [
                str(launcher),
                "status",
                "--startup",
            ],
            cwd=ROOT,
            env=_codexea_launcher_env(
                runtime_home,
                CODEXEA_REAL_CODEX=str(_fake_codex(tmp_path)),
                CODEXEA_RUNTIME_EA_ENV_PATH=str(_runtime_env_file(tmp_path)),
                CODEXEA_STATUS_URL=f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                CODEXEA_ONEMIN_DISPLAY_MODEL="ChatGPT 5.5 (1min.ai)",
                CODEXEA_IMPLEMENT_MODEL="ChatGPT 5.5 (1min.ai)",
                CODEXEA_WORKER_MODEL="ChatGPT 5.5 (1min.ai)",
                CODEXEA_CONTROLLER_MODEL="gpt-5.5",
                CODEXEA_ALLOW_ENV_MODEL_OVERRIDE="1",
                CODEXEA_USE_LIVE_PROFILE_MODELS="0",
                CODEXEA_POST_AUDIT="0",
                CODEXEA_TRACE_STARTUP="0",
                CODEXEA_STARTUP_STATUS="0",
                CODEXEA_MODEL_CATALOG_JSON="0",
            ),
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=1" in path for path in observed_paths)
    assert "CodexEA startup:" in completed.stdout
    assert "1h 1min burn 77 cr | 1min pressure medium" in completed.stdout
    assert completed.stderr == ""


def test_status_help_describes_compact_and_pretty_flags(tmp_path: Path) -> None:
    completed = _run_shim_completed(
        tmp_path,
        "status",
        "--help",
    )

    assert completed.returncode == 0
    assert "codexea status --compact [--pretty]" in completed.stdout
    assert "codexea status --full [--pretty]" in completed.stdout
    assert "--pretty    Force the human-readable formatter" in completed.stdout
    assert completed.stderr == ""


def test_launcher_startup_status_path_uses_cached_startup_probe_by_default() -> None:
    shim_text = SHIM.read_text(encoding="utf-8")

    assert 'show_status --startup || true' in shim_text
    assert 'show_status --startup --refresh || true' not in shim_text


def test_status_pretty_output_surfaces_onemin_host_hotspots(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            if not self.path.startswith("/v1/codex/status"):
                self.send_response(404)
                self.end_headers()
                return
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "status_basis": "actual_billing_usage_page",
                "providers_summary": [
                    {
                        "provider_name": "1min",
                        "account_name": "ONEMIN_AI_API_KEY",
                        "free_credits": 42000,
                        "used_percent": 58.0,
                        "basis": "actual_billing_usage_page",
                        "burn_credits_per_hour": 6000,
                        "hours_remaining_at_current_pace": 7.0,
                        "state": "ready",
                    }
                ],
                "provider_health": {"providers": {"_compact": {"state": "ready"}, "onemin": {"backend": "1min"}}},
                "fleet_burn": {
                    "1h": {"provider_credits": {"onemin": 6000}, "lane_requests": {"fast": 4}},
                    "24h": {"provider_credits": {"onemin": 30000}, "lane_requests": {"fast": 20}},
                    "7d": {"provider_credits": {"onemin": 90000}, "lane_requests": {"fast": 80}},
                },
                "window": "1h",
                "avoided_credits": {
                    "selected_window": {"total_avoided_credits": 0},
                    "selected_window_text": {
                        "easy": "No measurable easy lane savings yet in this window.",
                        "jury": "No measurable jury lane savings yet in this window.",
                    },
                },
                "topup_summary": {},
                "onemin_aggregate": {
                    "attempt_throttle_pressure_15m": "high",
                    "attempt_peak_parallel_same_proxy_15m": 3,
                    "attempt_peak_parallel_same_account_15m": 2,
                    "attempt_busiest_hosts_15m": [
                        {"host_id": "host-a", "attempts": 5},
                        {"host_id": "host-b", "attempts": 2},
                    ],
                    "attempt_recent_by_host_15m": {
                        "host-a": {"attempts": 5, "http_429_count": 2, "error_count": 3, "timeout_count": 1},
                        "host-b": {"attempts": 2, "http_429_count": 0, "error_count": 0, "timeout_count": 0},
                    },
                },
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--compact",
            "--pretty",
            "--refresh",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=1" in path for path in observed_paths)
    assert "1min hotspots" in completed.stdout
    assert "Throttle pressure (15m): high" in completed.stdout
    assert "Peak parallel (15m): same-proxy 3 | same-account 2" in completed.stdout
    assert "Busiest hosts (15m): host-a (5), host-b (2)" in completed.stdout
    assert "Top host stats (15m): host-a attempts=5 429s=2 errors=3 timeouts=1" in completed.stdout
    assert "Savings" not in completed.stdout
    assert "Top-up / sustainability" not in completed.stdout


def test_installed_launcher_status_pretty_output_surfaces_onemin_host_hotspots_outside_repo(
    tmp_path: Path,
) -> None:
    install_home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(install_home)
    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()
    run_cwd = tmp_path / "outside-repo"
    run_cwd.mkdir()
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            if not self.path.startswith("/v1/codex/status"):
                self.send_response(404)
                self.end_headers()
                return
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "status_basis": "actual_billing_usage_page",
                "providers_summary": [
                    {
                        "provider_name": "1min",
                        "account_name": "ONEMIN_AI_API_KEY",
                        "free_credits": 42000,
                        "used_percent": 58.0,
                        "basis": "actual_billing_usage_page",
                        "burn_credits_per_hour": 6000,
                        "hours_remaining_at_current_pace": 7.0,
                        "state": "ready",
                    }
                ],
                "provider_health": {"providers": {"_compact": {"state": "ready"}, "onemin": {"backend": "1min"}}},
                "fleet_burn": {
                    "1h": {"provider_credits": {"onemin": 6000}, "lane_requests": {"fast": 4}},
                    "24h": {"provider_credits": {"onemin": 30000}, "lane_requests": {"fast": 20}},
                    "7d": {"provider_credits": {"onemin": 90000}, "lane_requests": {"fast": 80}},
                },
                "window": "1h",
                "avoided_credits": {
                    "selected_window": {"total_avoided_credits": 0},
                    "selected_window_text": {
                        "easy": "No measurable easy lane savings yet in this window.",
                        "jury": "No measurable jury lane savings yet in this window.",
                    },
                },
                "topup_summary": {},
                "onemin_aggregate": {
                    "attempt_throttle_pressure_15m": "high",
                    "attempt_peak_parallel_same_proxy_15m": 3,
                    "attempt_peak_parallel_same_account_15m": 2,
                    "attempt_busiest_hosts_15m": [
                        {"host_id": "host-a", "attempts": 5},
                        {"host_id": "host-b", "attempts": 2},
                    ],
                    "attempt_recent_by_host_15m": {
                        "host-a": {"attempts": 5, "http_429_count": 2, "error_count": 3, "timeout_count": 1},
                        "host-b": {"attempts": 2, "http_429_count": 0, "error_count": 0, "timeout_count": 0},
                    },
                },
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = subprocess.run(
            [
                str(launcher),
                "status",
                "--compact",
                "--pretty",
                "--refresh",
            ],
            cwd=run_cwd,
            env=_codexea_launcher_env(
                runtime_home,
                CODEXEA_REAL_CODEX=str(_fake_codex(tmp_path)),
                CODEXEA_RUNTIME_EA_ENV_PATH=str(_runtime_env_file(tmp_path)),
                CODEXEA_STATUS_URL=f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                CODEXEA_ONEMIN_DISPLAY_MODEL="ChatGPT 5.5 (1min.ai)",
                CODEXEA_IMPLEMENT_MODEL="ChatGPT 5.5 (1min.ai)",
                CODEXEA_WORKER_MODEL="ChatGPT 5.5 (1min.ai)",
                CODEXEA_CONTROLLER_MODEL="gpt-5.5",
                CODEXEA_ALLOW_ENV_MODEL_OVERRIDE="1",
                CODEXEA_USE_LIVE_PROFILE_MODELS="0",
                CODEXEA_POST_AUDIT="0",
                CODEXEA_TRACE_STARTUP="0",
                CODEXEA_STARTUP_STATUS="0",
                CODEXEA_MODEL_CATALOG_JSON="0",
            ),
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=1" in path for path in observed_paths)
    assert "CodexEA / Fleet Status" in completed.stdout
    assert "1min hotspots" in completed.stdout
    assert "Throttle pressure (15m): high" in completed.stdout
    assert "Peak parallel (15m): same-proxy 3 | same-account 2" in completed.stdout
    assert "Busiest hosts (15m): host-a (5), host-b (2)" in completed.stdout
    assert "Top host stats (15m): host-a attempts=5 429s=2 errors=3 timeouts=1" in completed.stdout
    assert "Savings" not in completed.stdout
    assert "Top-up / sustainability" not in completed.stdout
    assert completed.stderr == ""


def test_status_pretty_defaults_to_compact_fast_path(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "status_basis": "compact",
                "providers_summary": [],
                "provider_health": {"providers": {"_compact": {"state": "ready"}}},
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 0}}},
                "onemin_aggregate": {},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=1" in path for path in observed_paths)


def test_status_pretty_compact_payload_without_default_route_uses_workspace_fallback(
    tmp_path: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            payload = {
                "status_basis": "compact",
                "providers_summary": [],
                "provider_health": {"providers": {"_compact": {"state": "ready"}}},
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 0}}},
                "onemin_aggregate": {},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--compact",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "EA_MCP_PRINCIPAL_ID": "principal-test",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert "Workspace: EA" in completed.stdout
    assert "Principal: principal-test" in completed.stdout
    assert "Lane default: workspace/principal fallback" in completed.stdout
    assert "Lane default: n/a -> n/a" not in completed.stdout


def test_status_pretty_full_override_uses_full_status_payload(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "status_basis": "actual_billing_usage_page",
                "providers_summary": [],
                "provider_health": {"providers": {"onemin": {"backend": "1min"}}},
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 0}}},
                "onemin_aggregate": {},
                "avoided_credits": {
                    "selected_window": {"total_avoided_credits": 0},
                    "selected_window_text": {
                        "easy": "No measurable easy lane savings yet in this window.",
                        "jury": "No measurable jury lane savings yet in this window.",
                    },
                },
                "topup_summary": {},
                "window": "1h",
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--full",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=0" in path for path in observed_paths)
    assert "Savings" in completed.stdout


def test_status_pretty_last_flag_wins_when_full_then_compact(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "status_basis": "compact",
                "providers_summary": [],
                "provider_health": {"providers": {"_compact": {"state": "ready"}}},
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 0}}},
                "onemin_aggregate": {},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--full",
            "--compact",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=1" in path for path in observed_paths)


def test_status_pretty_last_flag_wins_when_compact_then_full(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            payload = {
                "default_profile": "core",
                "default_lane": "hard",
                "status_basis": "actual_billing_usage_page",
                "providers_summary": [],
                "provider_health": {"providers": {"onemin": {"backend": "1min"}}},
                "fleet_burn": {"1h": {"provider_credits": {"onemin": 0}}},
                "onemin_aggregate": {},
                "avoided_credits": {
                    "selected_window": {"total_avoided_credits": 0},
                    "selected_window_text": {
                        "easy": "No measurable easy lane savings yet in this window.",
                        "jury": "No measurable jury lane savings yet in this window.",
                    },
                },
                "topup_summary": {},
                "window": "1h",
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--compact",
            "--full",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any("compact=0" in path for path in observed_paths)
    assert "Savings" in completed.stdout


def test_status_pretty_invalid_json_reports_parse_failure_without_traceback(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            encoded = b"not-json"
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_PROFILES_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/profiles",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 1
    assert "CodexEA status parse failure: invalid JSON from EA profiles fallback." in completed.stdout
    assert "not-json" in completed.stdout
    assert "Traceback" not in completed.stdout


def test_status_pretty_recovers_via_profiles_fallback_when_primary_json_is_invalid(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            if self.path.startswith("/v1/codex/status"):
                encoded = b"not-json"
                self.send_response(200)
                self.send_header("content-type", "text/plain")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            payload = {
                "provider_health": {
                    "providers": {
                        "onemin": {
                            "backend": "1min",
                            "configured_slots": 2,
                            "state": "ready",
                            "remaining_percent_of_max": 55,
                            "estimated_burn_credits_per_hour": 6000,
                            "estimated_hours_remaining_at_current_pace": 7,
                        }
                    }
                },
                "profiles": [
                    {
                        "profile": "core",
                        "lane": "hard",
                        "model": "gpt-5.4",
                        "provider_hint_order": ["onemin"],
                        "review_required": False,
                        "merge_policy": "manual",
                    }
                ],
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_PROFILES_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/profiles",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any(path.startswith("/v1/codex/status") for path in observed_paths)
    assert any(path.startswith("/v1/codex/profiles") for path in observed_paths)
    assert "CodexEA / Fleet Status" in completed.stdout
    assert "EA status basis: profiles_fallback" in completed.stdout
    assert "Traceback" not in completed.stdout


def test_status_pretty_reports_profiles_fallback_parse_failure_source(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            encoded = b"not-json"
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--pretty",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_PROFILES_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/profiles",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 1
    assert any(path.startswith("/v1/codex/status") for path in observed_paths)
    assert any(path.startswith("/v1/codex/profiles") for path in observed_paths)
    assert "CodexEA status parse failure: invalid JSON from EA profiles fallback." in completed.stdout
    assert "not-json" in completed.stdout
    assert "Traceback" not in completed.stdout


def test_status_json_recovers_via_profiles_fallback_when_primary_json_is_invalid(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            if self.path.startswith("/v1/codex/status"):
                encoded = b"not-json"
                self.send_response(200)
                self.send_header("content-type", "text/plain")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            payload = {
                "profiles": [
                    {
                        "profile": "core",
                        "lane": "hard",
                        "model": "gpt-5.4",
                        "provider_hint_order": ["onemin"],
                        "review_required": False,
                        "merge_policy": "manual",
                    }
                ]
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--json",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_PROFILES_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/profiles",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any(path.startswith("/v1/codex/status") for path in observed_paths)
    assert any(path.startswith("/v1/codex/profiles") for path in observed_paths)
    payload = json.loads(completed.stdout)
    assert payload["profiles"][0]["profile"] == "core"


def test_status_json_returns_invalid_primary_body_and_exit_one_when_no_valid_fallback(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            encoded = b"not-json"
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--json",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_PROFILES_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/profiles",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 1
    assert completed.stdout.strip() == "not-json"


def test_startup_status_recovers_via_profiles_fallback_when_primary_json_is_invalid(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            observed_paths.append(self.path)
            if self.path.startswith("/v1/codex/status"):
                encoded = b"not-json"
                self.send_response(200)
                self.send_header("content-type", "text/plain")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            payload = {
                "provider_health": {
                    "providers": {
                        "onemin": {"state": "ready"},
                        "gemini_vortex": {"state": "degraded"},
                    }
                },
                "profiles": [
                    {
                        "profile": "core",
                        "lane": "hard",
                        "model": "gpt-5.4",
                        "provider_hint_order": ["onemin", "gemini_vortex"],
                    }
                ],
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = _run_shim_completed(
            tmp_path,
            "status",
            "--startup",
            extra_env={
                "CODEXEA_STATUS_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/status",
                "CODEXEA_PROFILES_URL": f"http://127.0.0.1:{server.server_port}/v1/codex/profiles",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert any(path.startswith("/v1/codex/status") for path in observed_paths)
    assert any(path.startswith("/v1/codex/profiles") for path in observed_paths)
    assert "lane hard | model gpt-5.4 | providers onemin, gemini_vortex | ready 1 | degraded 1" in completed.stdout


def test_missing_explicit_runtime_env_path_falls_back_to_home_runtime_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runtime_dir = home / ".config" / "ea"
    runtime_dir.mkdir(parents=True)
    fallback_env = runtime_dir / "runtime.ea.env"
    fallback_env.write_text(
        "\n".join(
            [
                "EA_MCP_BASE_URL=http://fallback-runtime.test:8090",
                "EA_MCP_API_TOKEN=fallback-token",
            ]
        ),
        encoding="utf-8",
    )
    result = _run_shim(
        tmp_path,
        "core",
        "fallback check",
        extra_env={
            "HOME": str(home),
            "CODEXEA_RUNTIME_EA_ENV_PATH": str(tmp_path / "missing-runtime.ea.env"),
        },
    )

    env = result["env"]
    assert isinstance(env, dict)
    assert env["EA_MCP_API_TOKEN"] == "fallback-token"
    assert env["EA_API_TOKEN"] == "fallback-token"
    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert 'model_providers.ea.base_url="http://fallback-runtime.test:8090/v1"' in rendered_args


def test_outside_repo_cwd_env_is_ignored_unless_explicitly_allowed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runtime_dir = home / ".config" / "ea"
    runtime_dir.mkdir(parents=True)
    fallback_env = runtime_dir / "runtime.ea.env"
    fallback_env.write_text(
        "\n".join(
            [
                "EA_MCP_BASE_URL=http://fallback-runtime.test:8090",
                "EA_MCP_API_TOKEN=fallback-token",
                "EA_MCP_PRINCIPAL_ID=fallback-principal",
            ]
        ),
        encoding="utf-8",
    )
    outside_cwd = tmp_path / "not-a-worktree"
    outside_cwd.mkdir()
    (outside_cwd / ".env").write_text(
        "\n".join(
            [
                "EA_MCP_BASE_URL=http://poison.test:9999",
                "EA_MCP_API_TOKEN=poison-token",
                "EA_MCP_PRINCIPAL_ID=poison-principal",
            ]
        ),
        encoding="utf-8",
    )

    ignored = _run_shim(
        tmp_path,
        "core",
        "outside cwd poison ignored",
        cwd=outside_cwd,
        extra_env={"HOME": str(home)},
    )
    ignored_env = ignored["env"]
    assert isinstance(ignored_env, dict)
    assert ignored_env["EA_MCP_BASE_URL"] == "http://fallback-runtime.test:8090"
    assert ignored_env["EA_MCP_API_TOKEN"] == "fallback-token"
    assert ignored_env["EA_MCP_PRINCIPAL_ID"] == "fallback-principal"

    allowed = _run_shim(
        tmp_path,
        "core",
        "outside cwd poison allowed",
        cwd=outside_cwd,
        extra_env={
            "HOME": str(home),
            "CODEXEA_ALLOW_CWD_RUNTIME_ENV": "1",
        },
    )
    allowed_env = allowed["env"]
    assert isinstance(allowed_env, dict)
    assert allowed_env["EA_MCP_BASE_URL"] == "http://poison.test:9999"
    assert allowed_env["EA_MCP_API_TOKEN"] == "poison-token"
    assert allowed_env["EA_MCP_PRINCIPAL_ID"] == "poison-principal"


def test_onemin_route_forwards_summary_json(tmp_path: Path) -> None:
    route_helper = tmp_path / "fake-route-helper.py"
    route_helper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "print(json.dumps(sys.argv[1:]))",
            ]
        ),
        encoding="utf-8",
    )
    route_helper.chmod(route_helper.stat().st_mode | stat.S_IXUSR)

    stdout = _run_shim_stdout(
        tmp_path,
        "credits",
        "--summary-json",
        extra_env={
            "CODEXEA_ROUTE_HELPER": str(route_helper),
            "CODEXEA_CREDITS_INCLUDE_BILLING": "1",
        },
    )

    argv = json.loads(stdout)
    assert argv[:3] == ["--onemin-aggregate", "--probe-best-effort", "--billing"]
    assert "--summary-json" in argv


def test_credits_refresh_forwards_telegram_arguments_to_route_helper(tmp_path: Path) -> None:
    route_helper = tmp_path / "fake-route-helper.py"
    route_helper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "print(json.dumps(sys.argv[1:]))",
            ]
        ),
        encoding="utf-8",
    )
    route_helper.chmod(route_helper.stat().st_mode | stat.S_IXUSR)

    argv = json.loads(
        _run_shim_stdout(
            tmp_path,
            "credits",
            "refresh",
            "--send-telegram",
            "--telegram-chat-id",
            "123456789",
            "--telegram-bot-token",
            "bot-token",
            "--telegram-timeout-seconds",
            "19",
            extra_env={
                "CODEXEA_ROUTE_HELPER": str(route_helper),
                "CODEXEA_CREDITS_INCLUDE_BILLING": "1",
            },
        )
    )

    assert argv[:2] == ["--onemin-aggregate", "--onemin-refresh"]
    assert "--send-telegram" in argv
    assert "--telegram-chat-id" in argv
    assert "123456789" in argv
    assert "--telegram-bot-token" in argv
    assert "bot-token" in argv
    assert "--telegram-timeout-seconds" in argv
    assert "19" in argv


def test_credits_refresh_exports_telegram_principal_defaults_to_route_helper(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.ea.env"
    runtime_env.write_text(
        "\n".join(
            [
                "EA_PROACTIVE_OODA_PRINCIPAL_ID=cf-email:user@example.test",
                "EA_TELEGRAM_DEFAULT_PRINCIPAL_ID=cf-email:user@example.test",
                "EA_DEFAULT_PRINCIPAL_ID=local-user",
                "EA_TELEGRAM_DEFAULT_CHAT_ID=1354554303",
                "EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID=1354554303",
            ]
        ),
        encoding="utf-8",
    )
    route_helper = tmp_path / "fake-route-helper.py"
    route_helper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os",
                "keys = [",
                "  'EA_PROACTIVE_OODA_PRINCIPAL_ID',",
                "  'EA_TELEGRAM_DEFAULT_PRINCIPAL_ID',",
                "  'EA_DEFAULT_PRINCIPAL_ID',",
                "  'EA_TELEGRAM_DEFAULT_CHAT_ID',",
                "  'EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID',",
                "]",
                "print(json.dumps({key: os.environ.get(key, '') for key in keys}, sort_keys=True))",
            ]
        ),
        encoding="utf-8",
    )
    route_helper.chmod(route_helper.stat().st_mode | stat.S_IXUSR)

    env = json.loads(
        _run_shim_stdout(
            tmp_path,
            "credits",
            "refresh",
            "--send-telegram",
            extra_env={
                "CODEXEA_ROUTE_HELPER": str(route_helper),
                "CODEXEA_RUNTIME_EA_ENV_PATH": str(runtime_env),
                "EA_PROACTIVE_OODA_PRINCIPAL_ID": "",
                "EA_TELEGRAM_DEFAULT_PRINCIPAL_ID": "",
                "EA_DEFAULT_PRINCIPAL_ID": "",
                "EA_TELEGRAM_DEFAULT_CHAT_ID": "",
                "EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID": "",
            },
        )
    )

    assert env == {
        "EA_PROACTIVE_OODA_PRINCIPAL_ID": "cf-email:user@example.test",
        "EA_TELEGRAM_DEFAULT_PRINCIPAL_ID": "cf-email:user@example.test",
        "EA_DEFAULT_PRINCIPAL_ID": "local-user",
        "EA_TELEGRAM_DEFAULT_CHAT_ID": "1354554303",
        "EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID": "1354554303",
    }


def test_onemin_help_is_shim_local_and_does_not_require_route_helper(tmp_path: Path) -> None:
    stdout = _run_shim_stdout(
        tmp_path,
        "credits",
        "--help",
        extra_env={"CODEXEA_ROUTE_HELPER": str(tmp_path / "missing-route-helper.py")},
    )

    assert "CodexEA credits / 1min.AI commands:" in stdout
    assert "codexea credits --summary-json" in stdout
    assert "codexea credits --json" in stdout
    assert "Use --json only when you explicitly need the full payload." in stdout


def test_unusable_home_falls_back_before_state_paths_are_created(tmp_path: Path) -> None:
    fallback_home = tmp_path / "codexea-home"

    result = _run_shim(
        tmp_path,
        "core",
        "home check",
        extra_env={
            "HOME": "/",
            "CODEXEA_FALLBACK_HOME": str(fallback_home),
            "EA_MCP_BASE_URL": "http://ea-runtime.test:8090",
        },
    )

    env = result["env"]
    assert isinstance(env, dict)
    assert env["HOME"] == str(fallback_home)
    assert env["XDG_CACHE_HOME"] == str(fallback_home / ".cache")
    assert env["XDG_CONFIG_HOME"] == str(fallback_home / ".config")
    assert (fallback_home / ".cache").is_dir()
    assert (fallback_home / ".config").is_dir()


def test_contract_subcommand_emits_structured_worker_payload(tmp_path: Path) -> None:
    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "contract",
            extra_env={
                "CODEXEA_CONTRACT_OBJECTIVE": "Harden the WhatsApp automation stack.",
                "CODEXEA_CONTRACT_OWNED_FILES": "ea/app/services/audiobook_epub_pipeline.py\ntests/test_telegram_epub_audiobook_pipeline.py",
                "CODEXEA_CONTRACT_ACCEPTANCE_TESTS": "pytest -q tests/test_telegram_epub_audiobook_pipeline.py -k cleanup",
            },
        )
    )

    assert payload["lane"] == "worker"
    assert payload["role"] == "worker"
    assert payload["implementation_model"] == "ChatGPT 5.5 (1min.ai)"
    assert payload["review_model"] == "claude-opus-4.8"
    assert payload["objective"] == "Harden the WhatsApp automation stack."
    assert payload["owned_files"] == [
        "ea/app/services/audiobook_epub_pipeline.py",
        "tests/test_telegram_epub_audiobook_pipeline.py",
    ]
    assert payload["acceptance_tests"] == [
        "pytest -q tests/test_telegram_epub_audiobook_pipeline.py -k cleanup"
    ]
    assert payload["required_receipts"] == [
        "status",
        "files_changed",
        "tests_run",
        "tests_passed",
        "runtime_actions_taken",
        "assumptions_made",
        "genericity_findings",
        "observability_notes",
        "remaining_risks",
        "needs_review",
    ]


def test_worker_lane_injects_contract_and_visible_onemin_model_by_default(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "worker",
        "Fix the failing cleanup race",
        extra_env={
            "CODEXEA_CONTRACT_OBJECTIVE": "Fix the failing cleanup race.",
            "CODEXEA_CONTRACT_OWNED_FILES": "ea/app/services/audiobook_epub_pipeline.py",
            "CODEXEA_CONTRACT_ACCEPTANCE_TESTS": "pytest -q tests/test_telegram_epub_audiobook_pipeline.py -k cleanup",
        },
    )

    argv = result["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert 'model="ChatGPT 5.5 (1min.ai)"' in rendered_args
    assert 'model_provider="ea"' in rendered_args
    assert '"X-EA-Codex-Profile"="core"' in rendered_args
    assert "exec" in argv
    prompt = str(argv[-1])
    assert "You are running under the CodexEA worker contract." in prompt
    assert '"lane": "worker"' in prompt
    assert '"implementation_model": "ChatGPT 5.5 (1min.ai)"' in prompt
    assert "Fix the failing cleanup race" in prompt
    assert "After the first passing verification, do one brief hardening pass" in prompt
    assert "over-specialized, hardcoded, weakly observed, or only partially generalized" in prompt


def test_worker_lane_persists_redacted_launch_receipt_before_handoff(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    result = _run_shim(
        tmp_path,
        "worker",
        "Persist launch receipt",
        extra_env={
            "CODEXEA_STATE_DIR": str(state_dir),
            "CODEXEA_CONTRACT_OBJECTIVE": "Persist launch receipt before worker handoff with top-secret-worker-token.",
            "CODEXEA_CONTRACT_OWNED_FILES": "scripts/codexea\ntests/test_codexea_shim.py",
            "CODEXEA_CONTRACT_ACCEPTANCE_TESTS": "python3 -m pytest -q tests/test_codexea_shim.py",
            "EA_MCP_API_TOKEN": "top-secret-worker-token",
            "EA_API_TOKEN": "legacy-secret-worker-token",
            "ONEMIN_AI_API_KEY": "slot-secret-worker-token",
        },
    )

    receipt_path = state_dir / "launch-latest.json"
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert result["launch_receipt"] == receipt
    assert receipt["receipt_type"] == "codexea_launch"
    assert receipt["launch_kind"] == "exec"
    assert receipt["lane"] == "worker"
    assert receipt["mode"] == "responses"
    assert receipt["submode"] == "responses_core"
    assert receipt["provider"] == "ea"
    assert receipt["model"] == "ChatGPT 5.5 (1min.ai)"
    assert receipt["contract"]["runtime_mode"] == "code_only"
    assert receipt["contract"]["owned_files"] == [
        "scripts/codexea",
        "tests/test_codexea_shim.py",
    ]
    assert receipt["contract"]["acceptance_tests"] == [
        "python3 -m pytest -q tests/test_codexea_shim.py"
    ]
    assert receipt["handoff"]["exec"] is True
    assert receipt["handoff"]["argv_count"] > 0
    assert receipt["privacy"] == {
        "secrets_excluded": True,
        "argv_redacted": True,
        "env_redacted": True,
        "auth_headers_redacted": True,
        "sensitive_env_values_redacted": True,
    }
    rendered_receipt = json.dumps(receipt, sort_keys=True)
    assert "top-secret-worker-token" not in rendered_receipt
    assert "legacy-secret-worker-token" not in rendered_receipt
    assert "slot-secret-worker-token" not in rendered_receipt
    assert "Persist launch receipt before worker handoff with [REDACTED]." in rendered_receipt


def test_spawned_codexea_exit_gate_runs_smoke_task_through_worker_lane(tmp_path: Path) -> None:
    completed = _run_shim_completed(
        tmp_path,
        "worker",
        "E2E_EXIT_GATE_TASK: reply with E2E_EXIT_GATE_OK and stop.",
        extra_env={
            "CODEXEA_CONTRACT_OBJECTIVE": "Run the CodexEA exit-gate smoke task and stop after the first receipt.",
            "CODEXEA_STATE_DIR": str(tmp_path / "state"),
        },
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    argv = payload["argv"]
    prompt = str(argv[-1])
    assert "exec" in argv
    assert "E2E_EXIT_GATE_TASK" in prompt
    assert "E2E_EXIT_GATE_OK" in prompt
    assert '"lane": "worker"' in prompt
    assert payload["launch_receipt"]["launch_kind"] == "exec"
    assert payload["launch_receipt"]["lane"] == "worker"
    assert payload["launch_receipt"]["provider"] == "ea"
    assert payload["launch_receipt"]["mode"] == "responses"


def test_installed_launcher_spawned_codexea_exit_gate_runs_smoke_task_through_worker_lane(
    tmp_path: Path,
) -> None:
    install_home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(install_home)
    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()

    completed = subprocess.run(
        [
            str(launcher),
            "worker",
            "INSTALLED_E2E_EXIT_GATE_TASK: reply with INSTALLED_E2E_EXIT_GATE_OK and stop.",
        ],
        cwd=ROOT,
        env=_codexea_launcher_env(
            runtime_home,
            CODEXEA_REAL_CODEX=str(_fake_codex(tmp_path)),
            CODEXEA_RUNTIME_EA_ENV_PATH=str(_runtime_env_file(tmp_path)),
            CODEXEA_ONEMIN_DISPLAY_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_IMPLEMENT_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_WORKER_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_CONTROLLER_MODEL="gpt-5.5",
            CODEXEA_ALLOW_ENV_MODEL_OVERRIDE="1",
            CODEXEA_USE_LIVE_PROFILE_MODELS="0",
            CODEXEA_POST_AUDIT="0",
            CODEXEA_TRACE_STARTUP="0",
            CODEXEA_NO_ALT_SCREEN="0",
            CODEXEA_STARTUP_STATUS="0",
            CODEXEA_STATE_DIR=str(tmp_path / "state"),
            CODEXEA_MODEL_CATALOG_JSON="0",
            CODEXEA_CONTRACT_OBJECTIVE="Run the installed-launcher CodexEA exit-gate smoke task and stop after the first receipt.",
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    argv = payload["argv"]
    prompt = str(argv[-1])
    assert "exec" in argv
    assert "INSTALLED_E2E_EXIT_GATE_TASK" in prompt
    assert "INSTALLED_E2E_EXIT_GATE_OK" in prompt
    assert '"lane": "worker"' in prompt
    assert payload["launch_receipt"]["launch_kind"] == "exec"
    assert payload["launch_receipt"]["lane"] == "worker"
    assert payload["launch_receipt"]["provider"] == "ea"
    assert payload["launch_receipt"]["mode"] == "responses"


def test_worker_lane_preserves_explicit_local_ea_base_url_even_when_probe_candidates_exist(
    tmp_path: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/health", "/health/live"}:
                self.send_response(404)
                self.end_headers()
                return
            encoded = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
            payload = _run_shim(
                tmp_path,
                "worker",
                "explicit local ea url smoke",
                extra_env={
                    "EA_BASE_URL": "http://127.0.0.1:1",
                    "CODEXEA_LOCAL_EA_PORT_CANDIDATES": str(server.server_port),
                },
            )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    argv = [str(arg) for arg in payload["argv"]]
    assert 'model_providers.ea.base_url="http://127.0.0.1:1/v1"' in argv
    assert payload["launch_receipt"]["provider"] == "ea"


def test_worker_lane_preserves_explicit_local_ea_mcp_base_url_when_probe_candidates_exist(
    tmp_path: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/health", "/health/live"}:
                self.send_response(404)
                self.end_headers()
                return
            encoded = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = _run_shim(
            tmp_path,
            "worker",
            "explicit local ea mcp url smoke",
            extra_env={
                "EA_MCP_BASE_URL": "http://127.0.0.1:1",
                "CODEXEA_LOCAL_EA_PORT_CANDIDATES": str(server.server_port),
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    argv = [str(arg) for arg in payload["argv"]]
    assert 'model_providers.ea.base_url="http://127.0.0.1:1/v1"' in argv
    assert payload["launch_receipt"]["provider"] == "ea"


def test_worker_lane_syncs_visible_model_metadata_cache_when_forced(tmp_path: Path) -> None:
    home = tmp_path / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    cache_path = codex_home / "models_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": "2026-06-23T10:00:00Z",
                "models": [
                    {
                        "slug": "gpt-5.5",
                        "display_name": "GPT-5.5",
                        "context_window": 272000,
                        "supports_reasoning_summaries": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _run_shim(
        tmp_path,
        "worker",
        "metadata cache smoke",
        extra_env={
            "HOME": str(home),
            "CODEXEA_SYNC_MODEL_METADATA": "force",
        },
    )

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    alias = payload["models"][0]
    assert alias["slug"] == "ChatGPT 5.5 (1min.ai)"
    assert alias["display_name"] == "ChatGPT 5.5 (1min.ai)"
    assert alias["context_window"] == 272000
    assert payload["models"][1]["slug"] == "gpt-5.5"


def test_worker_lane_passes_synced_model_catalog_json_when_cache_exists(tmp_path: Path) -> None:
    home = tmp_path / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    cache_path = codex_home / "models_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.5",
                        "display_name": "GPT-5.5",
                        "context_window": 272000,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run_shim(
        tmp_path,
        "worker",
        "catalog cache smoke",
        extra_env={
            "HOME": str(home),
            "CODEXEA_MODEL_CATALOG_JSON": str(cache_path),
            "CODEXEA_SYNC_MODEL_METADATA": "force",
        },
    )

    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert f'model_catalog_json="{cache_path}"' in rendered_args
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["models"][0]["slug"] == "ChatGPT 5.5 (1min.ai)"
    assert payload["models"][1]["slug"] == "gpt-5.5"


def test_launch_receipt_is_private_and_bounded(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    long_objective = "Bound receipt size. " + ("x" * 600)
    many_owned_files = "\n".join(f"owned/file_{index}.py" for index in range(40))
    long_acceptance = "python3 -m pytest -q " + ("tests/test_codexea_shim.py::test_" + ("y" * 320))

    _run_shim(
        tmp_path,
        "worker",
        "Bound receipt size",
        extra_env={
            "CODEXEA_STATE_DIR": str(state_dir),
            "CODEXEA_CONTRACT_OBJECTIVE": long_objective,
            "CODEXEA_CONTRACT_OWNED_FILES": many_owned_files,
            "CODEXEA_CONTRACT_ACCEPTANCE_TESTS": long_acceptance,
        },
    )

    receipt_path = state_dir / "launch-latest.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_mode = stat.S_IMODE(receipt_path.stat().st_mode)

    assert receipt_mode == 0o600
    assert receipt["contract"]["truncation"] == {
        "max_text_len": 400,
        "max_list_items": 24,
        "max_list_item_len": 240,
    }
    assert len(receipt["contract"]["objective"]) == 400
    assert receipt["contract"]["objective"].endswith("...")
    assert len(receipt["contract"]["owned_files"]) == 24
    assert all(len(item) <= 240 for item in receipt["contract"]["owned_files"])
    assert len(receipt["contract"]["acceptance_tests"]) == 1
    assert len(receipt["contract"]["acceptance_tests"][0]) == 240
    assert receipt["contract"]["acceptance_tests"][0].endswith("...")


def test_launch_receipt_history_is_private_newest_first_and_retained(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    for index in range(5):
        _run_shim(
            tmp_path,
            "worker",
            f"History receipt run {index}",
            extra_env={
                "CODEXEA_STATE_DIR": str(state_dir),
                "CODEXEA_LAUNCH_HISTORY_LIMIT": "3",
                "CODEXEA_CONTRACT_OBJECTIVE": f"History receipt run {index} with history-secret-token.",
                "CODEXEA_CONTRACT_OWNED_FILES": "scripts/codexea\ntests/test_codexea_shim.py",
                "EA_MCP_API_TOKEN": "history-secret-token",
            },
        )

    latest = json.loads((state_dir / "launch-latest.json").read_text(encoding="utf-8"))
    history_path = state_dir / "launch-history.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history_mode = stat.S_IMODE(history_path.stat().st_mode)

    assert history_mode == 0o600
    assert history["receipt_type"] == "codexea_launch_history"
    assert history["retention"] == {
        "max_entries": 3,
        "order": "newest_first",
    }
    entries = history["entries"]
    assert len(entries) == 3
    assert entries[0] == latest
    assert [entry["contract"]["objective"] for entry in entries] == [
        "History receipt run 4 with [REDACTED].",
        "History receipt run 3 with [REDACTED].",
        "History receipt run 2 with [REDACTED].",
    ]
    rendered_history = json.dumps(history, sort_keys=True)
    assert "History receipt run 1" not in rendered_history
    assert "history-secret-token" not in rendered_history


def test_receipt_latest_subcommand_reads_latest_launch_receipt(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    _run_shim(
        tmp_path,
        "worker",
        "Latest receipt read surface",
        extra_env={
            "CODEXEA_STATE_DIR": str(state_dir),
            "CODEXEA_CONTRACT_OBJECTIVE": "Latest receipt read surface.",
            "CODEXEA_CONTRACT_OWNED_FILES": "scripts/codexea\ntests/test_codexea_shim.py",
        },
    )

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "receipt",
            "latest",
            "--json",
            extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
        )
    )

    assert payload["receipt_type"] == "codexea_launch_receipt_read"
    assert payload["source"] == "latest"
    assert payload["exists"] is True
    assert payload["path"] == str(state_dir / "launch-latest.json")
    assert payload["receipt"]["receipt_type"] == "codexea_launch"
    assert payload["receipt"]["contract"]["objective"] == "Latest receipt read surface."
    assert payload["receipt"]["contract"]["owned_files"] == [
        "scripts/codexea",
        "tests/test_codexea_shim.py",
    ]


def test_receipt_list_subcommand_returns_bounded_newest_first_summaries(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    for index in range(4):
        _run_shim(
            tmp_path,
            "worker",
            f"Receipt list run {index}",
            extra_env={
                "CODEXEA_STATE_DIR": str(state_dir),
                "CODEXEA_CONTRACT_OBJECTIVE": f"Receipt list run {index}.",
                "CODEXEA_CONTRACT_ACCEPTANCE_TESTS": "python3 -m pytest -q tests/test_codexea_shim.py",
            },
        )

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "receipts",
            "list",
            "--limit",
            "2",
            extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
        )
    )

    assert payload["receipt_type"] == "codexea_launch_history_list"
    assert payload["exists"] is True
    assert payload["limit"] == 2
    assert payload["count"] == 2
    assert [entry["objective"] for entry in payload["entries"]] == [
        "Receipt list run 3.",
        "Receipt list run 2.",
    ]
    assert payload["entries"][0]["acceptance_tests"] == [
        "python3 -m pytest -q tests/test_codexea_shim.py"
    ]
    assert "contract" not in payload["entries"][0]


def test_local_receipts_namespace_reads_bounded_history_summaries(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    _run_shim(
        tmp_path,
        "worker",
        "Local receipt namespace read",
        extra_env={
            "CODEXEA_STATE_DIR": str(state_dir),
            "CODEXEA_CONTRACT_OBJECTIVE": "Local receipt namespace read.",
        },
    )

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "local",
            "receipts",
            "list",
            "--limit=1",
            extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
        )
    )

    assert payload["receipt_type"] == "codexea_launch_history_list"
    assert payload["source"] == "history"
    assert payload["limit"] == 1
    assert payload["count"] == 1
    assert payload["entries"][0]["objective"] == "Local receipt namespace read."


def test_local_help_documents_read_only_control_plane_namespace(tmp_path: Path) -> None:
    state_dir = tmp_path / "missing-local-help-state"
    stdout = _run_shim_stdout(
        tmp_path,
        "local",
        "--help",
        extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
    )

    assert "CodexEA local control-plane commands:" in stdout
    assert "codexea local inspect [--limit N] [--json]" in stdout
    assert "codexea local receipts latest [--json]" in stdout
    assert "codexea local receipts history [--limit N] [--json]" in stdout
    assert "codexea local receipts list [--limit N] [--json]" in stdout
    assert "codexea inspect is reserved for the upstream Codex inspect command" in stdout
    assert "Use codexea local inspect for shim-local read-only state." in stdout
    assert not state_dir.exists()


def test_local_receipts_namespace_reads_latest_and_history_aliases(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    for index in range(2):
        _run_shim(
            tmp_path,
            "worker",
            f"Local receipt alias run {index}",
            extra_env={
                "CODEXEA_STATE_DIR": str(state_dir),
                "CODEXEA_CONTRACT_OBJECTIVE": f"Local receipt alias run {index}.",
            },
        )

    latest = json.loads(
        _run_shim_stdout(
            tmp_path,
            "local",
            "receipt",
            "latest",
            extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
        )
    )
    history = json.loads(
        _run_shim_stdout(
            tmp_path,
            "control-plane",
            "launch-receipts",
            "history",
            "--limit=1",
            extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
        )
    )

    assert latest["receipt_type"] == "codexea_launch_receipt_read"
    assert latest["receipt"]["contract"]["objective"] == "Local receipt alias run 1."
    assert history["receipt_type"] == "codexea_launch_history_read"
    assert history["source"] == "history"
    assert history["limit"] == 1
    assert history["count"] == 1
    assert history["entries"][0]["contract"]["objective"] == "Local receipt alias run 1."


def test_receipt_history_subcommand_clamps_requested_limit(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    _run_shim(
        tmp_path,
        "worker",
        "Receipt history clamp",
        extra_env={
            "CODEXEA_STATE_DIR": str(state_dir),
            "CODEXEA_CONTRACT_OBJECTIVE": "Receipt history clamp.",
        },
    )

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "launch-receipts",
            "history",
            "--limit=9999",
            extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
        )
    )

    assert payload["receipt_type"] == "codexea_launch_history_read"
    assert payload["limit"] == 200
    assert payload["count"] == 1
    assert payload["entries"][0]["contract"]["objective"] == "Receipt history clamp."


def test_receipt_subcommand_reports_missing_state_without_handoff(tmp_path: Path) -> None:
    state_dir = tmp_path / "missing-state"

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "receipt",
            "latest",
            extra_env={
                "CODEXEA_STATE_DIR": str(state_dir),
                "CODEXEA_REAL_CODEX": str(tmp_path / "missing-codex"),
            },
        )
    )

    assert payload["receipt_type"] == "codexea_launch_receipt_read"
    assert payload["exists"] is False
    assert payload["receipt"] is None
    assert not (state_dir / "launch-latest.json").exists()


def test_inspect_subcommand_combines_latest_history_and_post_audit_state(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"

    for index in range(3):
        _run_shim(
            tmp_path,
            "worker",
            f"Inspect surface run {index}",
            extra_env={
                "CODEXEA_STATE_DIR": str(state_dir),
                "CODEXEA_CONTRACT_OBJECTIVE": f"Inspect surface run {index}.",
                "CODEXEA_CONTRACT_OWNED_FILES": "scripts/codexea\ntests/test_codexea_shim.py",
                "CODEXEA_CONTRACT_ACCEPTANCE_TESTS": "python3 -m pytest -q tests/test_codexea_shim.py",
            },
        )

    post_audit_request = {
        "model": "ea-review-light",
        "input": "review prompt body " + ("x" * 700),
        "metadata": {
            "codexea_post_audit": True,
            "codexea_lane": "worker",
            "codexea_submode": "mcp_worker",
            "codexea_git_root": str(ROOT),
            "codexea_review_packet": {
                "objective": "Review inspect surface.",
                "changed_files": [f"changed/file_{index}.py" for index in range(40)],
                "diff_summary": "diff stat " + ("y" * 900),
                "verification": {
                    "commands": ["python3 -m pytest -q tests/test_codexea_shim.py"],
                    "passed": None,
                    "session_exit_code": 0,
                    "notes": ["No verification commands were captured by the codexea shim."],
                },
                "warnings": ["no_verification_captured_by_shim"],
                "final_claim": "CodexEA lane=worker submode=mcp_worker exited with code 0.",
            },
        },
    }
    (state_dir / "post-audit-latest.json").write_text(
        json.dumps(post_audit_request),
        encoding="utf-8",
    )

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "local",
            "inspect",
            "--limit=2",
            extra_env={"CODEXEA_STATE_DIR": str(state_dir)},
        )
    )

    assert payload["receipt_type"] == "codexea_inspect"
    assert payload["state_dir"] == str(state_dir)
    assert payload["truncation"] == {
        "max_text_len": 400,
        "max_list_items": 24,
        "max_list_item_len": 240,
        "indicator": "ellipsis_suffix",
        "applies_to": [
            "launch_history_summary.entries[].objective",
            "launch_history_summary.entries[].owned_files[]",
            "launch_history_summary.entries[].acceptance_tests[]",
            "post_audit_request.request.model",
            "post_audit_request.request.metadata.codexea_lane",
            "post_audit_request.request.metadata.codexea_submode",
            "post_audit_request.request.metadata.codexea_git_root",
            "post_audit_request.request.review_packet.objective",
            "post_audit_request.request.review_packet.changed_files[]",
            "post_audit_request.request.review_packet.verification.commands[]",
            "post_audit_request.request.review_packet.verification.notes[]",
            "post_audit_request.request.review_packet.warnings[]",
            "post_audit_request.request.review_packet.final_claim",
        ],
    }
    assert payload["summary_shape"] == {
        "launch_latest": {
            "shape": "full_receipt",
            "truncated": False,
        },
        "launch_history_summary": {
            "shape": "bounded_receipt_summaries",
            "entry_fields": [
                "launch_id",
                "generated_at",
                "launch_kind",
                "lane",
                "mode",
                "submode",
                "provider",
                "model",
                "reasoning_effort",
                "objective",
                "owned_files",
                "acceptance_tests",
            ],
            "full_contract_included": False,
            "truncated": True,
        },
        "post_audit_request": {
            "shape": "bounded_request_summary",
            "input_included": False,
            "review_packet_diff_summary_included": False,
            "truncated": True,
        },
    }
    assert payload["launch_latest"]["exists"] is True
    assert payload["launch_latest"]["receipt"]["contract"]["objective"] == "Inspect surface run 2."
    history = payload["launch_history_summary"]
    assert history["exists"] is True
    assert history["limit"] == 2
    assert history["count"] == 2
    assert [entry["objective"] for entry in history["entries"]] == [
        "Inspect surface run 2.",
        "Inspect surface run 1.",
    ]
    assert "contract" not in history["entries"][0]
    post_audit = payload["post_audit_request"]
    assert post_audit["exists"] is True
    assert post_audit["request"]["model"] == "ea-review-light"
    assert post_audit["request"]["has_input"] is True
    assert post_audit["request"]["input_chars"] == len(post_audit_request["input"])
    assert "input" not in post_audit["request"]
    assert post_audit["request"]["metadata"]["codexea_lane"] == "worker"
    packet = post_audit["request"]["review_packet"]
    assert packet["objective"] == "Review inspect surface."
    assert len(packet["changed_files"]) == 24
    assert "diff_summary" not in packet
    assert packet["diff_summary_chars"] == len(
        post_audit_request["metadata"]["codexea_review_packet"]["diff_summary"]
    )


def test_inspect_subcommand_reports_missing_state_without_handoff(tmp_path: Path) -> None:
    state_dir = tmp_path / "missing-inspect-state"

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "local",
            "inspect",
            extra_env={
                "CODEXEA_STATE_DIR": str(state_dir),
                "CODEXEA_REAL_CODEX": str(tmp_path / "missing-codex"),
            },
        )
    )

    assert payload["receipt_type"] == "codexea_inspect"
    assert payload["launch_latest"]["exists"] is False
    assert payload["launch_latest"]["receipt"] is None
    assert payload["launch_history_summary"]["exists"] is False
    assert payload["launch_history_summary"]["entries"] == []
    assert payload["post_audit_request"]["exists"] is False
    assert payload["post_audit_request"]["request"] is None
    assert not state_dir.exists()


def test_top_level_inspect_passes_through_to_codex_command(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "inspect",
        "--limit=2",
        extra_env={"CODEXEA_MODEL": "codex-default"},
    )

    argv = result["argv"]
    assert isinstance(argv, list)
    assert "inspect" in argv
    assert "--limit=2" in argv
    assert "exec" not in argv
    assert result["launch_receipt"]["launch_kind"] == "direct"


def test_worker_lane_does_not_inherit_interactive_wait_bootstrap(tmp_path: Path) -> None:
    bootstrap = _bootstrap_prompt_file(tmp_path)

    result = _run_shim(
        tmp_path,
        "worker",
        "Fix the failing cleanup race",
        extra_env={
            "CODEXEA_BOOTSTRAP": "1",
            "CODEXEA_BOOTSTRAP_PROMPT_FILE": str(bootstrap),
            "CODEXEA_CONTRACT_OBJECTIVE": "Fix the failing cleanup race.",
        },
    )

    prompt = str(result["argv"][-1])
    assert "You are running under the CodexEA worker contract." in prompt
    assert "Fix the failing cleanup race" in prompt
    assert "WAIT_ONLY_BOOTSTRAP" not in prompt


def test_noninteractive_prompt_session_does_not_inherit_interactive_wait_bootstrap(
    tmp_path: Path,
) -> None:
    bootstrap = _bootstrap_prompt_file(tmp_path)

    result = _run_shim(
        tmp_path,
        "core",
        "Inspect the launch path",
        extra_env={
            "CODEXEA_BOOTSTRAP": "1",
            "CODEXEA_BOOTSTRAP_PROMPT_FILE": str(bootstrap),
        },
    )

    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert "exec" in result["argv"]
    assert "Inspect the launch path" in rendered_args
    assert "WAIT_ONLY_BOOTSTRAP" not in rendered_args


def test_interactive_session_inherits_wait_bootstrap(tmp_path: Path) -> None:
    bootstrap = _bootstrap_prompt_file(tmp_path)

    result = _run_shim(
        tmp_path,
        extra_env={
            "CODEXEA_BOOTSTRAP": "1",
            "CODEXEA_BOOTSTRAP_PROMPT_FILE": str(bootstrap),
        },
    )

    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert "WAIT_ONLY_BOOTSTRAP" in rendered_args
    assert "You are running under the CodexEA worker contract." not in rendered_args


def test_interactive_flag_prompt_inherits_wait_bootstrap_without_contract(tmp_path: Path) -> None:
    bootstrap = _bootstrap_prompt_file(tmp_path)

    result = _run_shim(
        tmp_path,
        "--interactive",
        "Inspect the launch path",
        extra_env={
            "CODEXEA_BOOTSTRAP": "1",
            "CODEXEA_BOOTSTRAP_PROMPT_FILE": str(bootstrap),
        },
    )

    argv = result["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert "exec" not in argv
    assert "WAIT_ONLY_BOOTSTRAP" in rendered_args
    assert "Inspect the launch path" in rendered_args
    assert "You are running under the CodexEA worker contract." not in rendered_args


def test_easy_lane_defaults_to_ea_fast_route_instead_of_explicit_gemini(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "easy",
        "Summarize the latest queue",
    )

    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert result["launch_receipt"]["mode"] == "responses"
    assert result["launch_receipt"]["provider"] == "ea"
    assert result["launch_receipt"]["submode"] == "responses_fast"
    assert result["launch_receipt"]["model"] == "ea-coder-fast"
    assert 'model="ea-coder-fast"' in rendered_args
    assert 'model_provider="ea"' in rendered_args
    assert '"X-EA-Codex-Profile"="easy"' in rendered_args


def test_easy_lane_mcp_escape_hatch_inherits_onemin_default_model(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "easy",
        "Summarize the latest queue without the EA responses lane",
        extra_env={"CODEXEA_MODE": "mcp", "CODEXEA_ALLOW_EASY_MODE_OVERRIDE": "1"},
    )

    argv = result["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    env = result["env"]
    assert result["launch_receipt"]["mode"] == "mcp"
    assert result["launch_receipt"]["provider"] == "mcp"
    assert result["launch_receipt"]["submode"] == "mcp"
    assert result["launch_receipt"]["model"] == "ChatGPT 5.5 (1min.ai)"
    assert env["EA_MCP_MODEL"] == "ChatGPT 5.5 (1min.ai)"
    assert 'model="ChatGPT 5.5 (1min.ai)"' in rendered_args
    assert 'model_provider="ea"' not in rendered_args
    assert "exec" in argv


def test_groundwork_lane_defaults_to_provider_neutral_groundwork_alias(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "groundwork",
        "Draft a compact groundwork brief",
    )

    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert 'model="ea-groundwork"' in rendered_args
    assert '"X-EA-Codex-Profile"="groundwork"' in rendered_args


def test_review_light_lane_launch_stack_keeps_chatplayground_ahead_of_gemini(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "review_light",
        "Audit the proposed patch",
    )

    model_stack = str(result["env"]["CODEXEA_MODEL_STACK"])
    assert "codex:ea-review-light" in model_stack
    assert "route:1min.ai:" in model_stack
    assert "chatplayground" in model_stack
    assert "gemini_vortex:" in model_stack
    assert model_stack.index("chatplayground") < model_stack.index("gemini_vortex:")


def test_survival_lane_launch_stack_keeps_chatplayground_ahead_of_gemini(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "survival",
        "Recover the session with maximum survivability",
    )

    model_stack = str(result["env"]["CODEXEA_MODEL_STACK"])
    assert "codex:ea-coder-survival" in model_stack
    assert "route:1min.ai:" in model_stack
    assert "chatplayground" in model_stack
    assert "gemini_vortex:" in model_stack
    assert model_stack.index("chatplayground") < model_stack.index("gemini_vortex:")


def test_resume_session_uses_interactive_terminal_defaults(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "resume",
        "--last",
        extra_env={"CODEXEA_NO_ALT_SCREEN": "1"},
    )

    argv = result["argv"]
    assert isinstance(argv, list)
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert "--no-alt-screen" in argv
    assert argv.index("--no-alt-screen") < argv.index("resume")
    assert "exec" not in argv
    assert "resume" in argv
    assert "--last" in argv
    assert "You are running under the CodexEA worker contract." not in rendered_args


def test_installed_launcher_resume_session_uses_interactive_terminal_defaults_without_contract(
    tmp_path: Path,
) -> None:
    install_home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(install_home)
    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()

    completed = subprocess.run(
        [
            str(launcher),
            "resume",
            "--last",
        ],
        cwd=ROOT,
        env=_codexea_launcher_env(
            runtime_home,
            CODEXEA_REAL_CODEX=str(_fake_codex(tmp_path)),
            CODEXEA_RUNTIME_EA_ENV_PATH=str(_runtime_env_file(tmp_path)),
            CODEXEA_ONEMIN_DISPLAY_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_IMPLEMENT_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_WORKER_MODEL="ChatGPT 5.5 (1min.ai)",
            CODEXEA_CONTROLLER_MODEL="gpt-5.5",
            CODEXEA_ALLOW_ENV_MODEL_OVERRIDE="1",
            CODEXEA_USE_LIVE_PROFILE_MODELS="0",
            CODEXEA_POST_AUDIT="0",
            CODEXEA_TRACE_STARTUP="0",
            CODEXEA_NO_ALT_SCREEN="1",
            CODEXEA_STARTUP_STATUS="0",
            CODEXEA_STATE_DIR=str(tmp_path / "state"),
            CODEXEA_MODEL_CATALOG_JSON="0",
            CODEXEA_BOOTSTRAP="1",
            CODEXEA_BOOTSTRAP_PROMPT_FILE=str(_bootstrap_prompt_file(tmp_path)),
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    argv = payload["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert "--no-alt-screen" in argv
    assert argv.index("--no-alt-screen") < argv.index("resume")
    assert "exec" not in argv
    assert "resume" in argv
    assert "--last" in argv
    assert "You are running under the CodexEA worker contract." not in rendered_args
    assert "WAIT_ONLY_BOOTSTRAP" not in rendered_args


def test_worker_lane_codex_default_model_uses_safe_ea_responses_default(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "worker",
        "Probe the route",
        extra_env={
            "CODEXEA_MODEL": "codex-default",
            "CODEXEA_CONTRACT_OBJECTIVE": "Probe the route without forcing a model override.",
        },
    )

    argv = result["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert 'model="codex-default"' not in rendered_args
    assert 'model="ChatGPT 5.5 (1min.ai)"' in rendered_args
    assert 'model_provider="ea"' in rendered_args
    assert '"X-EA-Codex-Profile"="core"' in rendered_args
    assert "exec" in argv
    assert '"lane": "worker"' in str(argv[-1])
    assert "Probe the route without forcing a model override." in str(argv[-1])


def test_controller_lane_defaults_to_onemin_display_model(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "controller",
        "Coordinate the next coding slice",
        extra_env={
            "CODEXEA_CONTROLLER_MODEL": "",
            "CODEXEA_CONTRACT_OBJECTIVE": "Coordinate the next coding slice.",
        },
    )

    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert result["launch_receipt"]["mode"] == "responses"
    assert result["launch_receipt"]["provider"] == "ea"
    assert result["launch_receipt"]["model"] == "ChatGPT 5.5 (1min.ai)"
    assert 'model="ChatGPT 5.5 (1min.ai)"' in rendered_args
    assert '"X-EA-Codex-Profile"="audit"' in rendered_args


def test_worker_lane_can_still_opt_into_mcp_mode_explicitly(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "worker",
        "Probe the MCP escape hatch",
        extra_env={
            "CODEXEA_MODE": "mcp",
            "CODEXEA_CONTRACT_OBJECTIVE": "Probe the MCP escape hatch.",
        },
    )

    argv = result["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert 'model="ChatGPT 5.5 (1min.ai)"' in rendered_args
    assert 'model_provider="ea"' not in rendered_args
    assert result["launch_receipt"]["mode"] == "mcp"
    assert result["launch_receipt"]["submode"] == "mcp_worker"
    assert result["launch_receipt"]["provider"] == "mcp"
    assert "exec" in argv


def test_worker_explicit_exec_with_stdin_prompt_preserves_exec_argv(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "worker",
        "exec",
        "--output-last-message",
        "/tmp/out.txt",
        "-",
    )

    argv = result["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert 'model_provider="ea"' in rendered_args
    assert argv[-4:] == ["exec", "--output-last-message", "/tmp/out.txt", "-"]


def test_worker_stdin_prompt_shorthand_places_exec_options_before_prompt(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "worker",
        "-",
        "--output-last-message",
        "/tmp/out.txt",
    )

    argv = result["argv"]
    rendered_args = "\n".join(str(arg) for arg in argv)
    assert 'model_provider="ea"' in rendered_args
    assert argv[-4:] == ["exec", "--output-last-message", "/tmp/out.txt", "-"]


def test_default_lane_is_worker_and_uses_controller_designed_contract(tmp_path: Path) -> None:
    result = _run_shim(
        tmp_path,
        "Continue working on the current coding slice",
        extra_env={
            "CODEXEA_CONTRACT_OBJECTIVE": "Continue the active goal under controller supervision.",
        },
    )

    rendered_args = "\n".join(str(arg) for arg in result["argv"])
    assert 'model="ChatGPT 5.5 (1min.ai)"' in rendered_args
    assert 'model_provider="ea"' in rendered_args
    assert '"X-EA-Codex-Profile"="core"' in rendered_args
    assert '"lane": "worker"' in str(result["argv"][-1])


def test_nested_repo_launch_anchors_to_repo_root_and_preserves_original_cwd(tmp_path: Path) -> None:
    nested_cwd = ROOT / "ea"

    result = _run_shim(
        tmp_path,
        "worker",
        "Nested launch context check",
        cwd=nested_cwd,
        extra_env={
            "CODEXEA_CONTRACT_OBJECTIVE": "Verify nested launch anchoring.",
        },
    )

    argv = result["argv"]
    assert isinstance(argv, list)
    assert "-C" in argv
    assert argv[argv.index("-C") + 1] == str(ROOT)
    assert result["cwd"] == str(ROOT)

    env = result["env"]
    assert isinstance(env, dict)
    assert env["CODEXEA_ORIGINAL_CWD"] == str(nested_cwd)
    assert env["CODEXEA_REPO_ROOT"] == str(ROOT)

    prompt = str(argv[-1])
    assert '"repo_root": "' + str(ROOT) + '"' in prompt
    assert '"original_caller_cwd": "' + str(nested_cwd) + '"' in prompt


def test_launch_outside_git_worktree_keeps_caller_cwd_without_cd_override(tmp_path: Path) -> None:
    outside_cwd = tmp_path / "not-a-worktree"
    outside_cwd.mkdir()

    result = _run_shim(
        tmp_path,
        "worker",
        "Outside worktree context check",
        cwd=outside_cwd,
        extra_env={
            "CODEXEA_CONTRACT_OBJECTIVE": "Verify non-worktree cwd behavior.",
        },
    )

    argv = result["argv"]
    assert isinstance(argv, list)
    assert "-C" not in argv
    assert "--cd" not in argv
    assert result["cwd"] == str(outside_cwd)

    env = result["env"]
    assert isinstance(env, dict)
    assert env["CODEXEA_ORIGINAL_CWD"] == str(outside_cwd)
    assert env["CODEXEA_REPO_ROOT"] == ""


def test_nested_repo_launch_honors_explicit_cd_override(tmp_path: Path) -> None:
    explicit_cwd = tmp_path / "explicit-cwd"
    explicit_cwd.mkdir()

    result = _run_shim(
        tmp_path,
        "worker",
        "--cd",
        str(explicit_cwd),
        "Explicit cd context check",
        cwd=ROOT / "ea",
        extra_env={
            "CODEXEA_CONTRACT_OBJECTIVE": "Verify explicit cd override.",
        },
    )

    argv = result["argv"]
    assert isinstance(argv, list)
    assert "-C" not in argv
    assert "--cd" in argv
    assert argv[argv.index("--cd") + 1] == str(explicit_cwd)
    assert result["cwd"] == str(explicit_cwd)


def test_onemin_route_defaults_to_best_effort_probe(tmp_path: Path) -> None:
    route_helper = tmp_path / "route_helper.py"
    route_helper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "print(json.dumps(sys.argv[1:]))",
            ]
        ),
        encoding="utf-8",
    )

    stdout = _run_shim_stdout(
        tmp_path,
        "onemin",
        extra_env={
            "CODEXEA_ROUTE_HELPER": str(route_helper),
            "CODEXEA_CREDITS_INCLUDE_BILLING": "1",
        },
    )

    argv = json.loads(stdout)
    assert argv[:3] == ["--onemin-aggregate", "--probe-best-effort", "--billing"]


def test_onemin_route_honors_explicit_probe_all(tmp_path: Path) -> None:
    route_helper = tmp_path / "route_helper.py"
    route_helper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "print(json.dumps(sys.argv[1:]))",
            ]
        ),
        encoding="utf-8",
    )

    stdout = _run_shim_stdout(
        tmp_path,
        "onemin",
        "--probe-all",
        extra_env={
            "CODEXEA_ROUTE_HELPER": str(route_helper),
            "CODEXEA_CREDITS_INCLUDE_BILLING": "0",
        },
    )

    argv = json.loads(stdout)
    assert argv == ["--onemin-aggregate", "--probe-all"]


def test_onemin_route_loads_runtime_password_for_local_fallback(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.ea.env"
    runtime_env.write_text(
        "\n".join(
            [
                "ONEMIN_DEFAULT_PASSWORD=runtime-secret",
                "ONEMIN_AI_API_KEY_FALLBACK_7=slot-secret",
                "CODEXEA_ONEMIN_TIMEOUT_SECONDS=420",
            ]
        ),
        encoding="utf-8",
    )
    route_helper = tmp_path / "route_helper.py"
    route_helper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, sys",
                "print(json.dumps({",
                "    'argv': sys.argv[1:],",
                "    'password': os.environ.get('ONEMIN_DEFAULT_PASSWORD', ''),",
                "    'slot': os.environ.get('ONEMIN_AI_API_KEY_FALLBACK_7', ''),",
                "    'timeout_seconds': os.environ.get('CODEXEA_ONEMIN_TIMEOUT_SECONDS', ''),",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        _run_shim_stdout(
            tmp_path,
            "onemin",
            extra_env={
                "CODEXEA_ROUTE_HELPER": str(route_helper),
                "CODEXEA_RUNTIME_EA_ENV_PATH": str(runtime_env),
            },
        )
    )

    assert payload["password"] == "runtime-secret"
    assert payload["slot"] == "slot-secret"
    assert payload["timeout_seconds"] == "420"


def _codexea_launcher_env(home: Path, **overrides: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"CODEXEA_MANAGED_SHIM", "CODEXEA_FLEET_ROOT", "CODEXEA_ROUTE_HELPER"}
    }
    env["HOME"] = str(home)
    env.update(overrides)
    return env


def _install_codexea(tmp_path: Path) -> tuple[Path, subprocess.CompletedProcess[str]]:
    home = tmp_path / "home"
    home.mkdir()
    completed = subprocess.run(
        [str(ROOT / "scripts" / "install_codexea.sh")],
        cwd=ROOT,
        env=_codexea_launcher_env(home),
        check=True,
        capture_output=True,
        text=True,
    )
    return home, completed


def _launcher_path(home: Path) -> Path:
    return home / ".local" / "bin" / "codexea"


def _managed_shim_path(home: Path) -> Path:
    return home / ".local" / "share" / "codexea" / "fleet" / "scripts" / "codexea"


def _route_helper_path(home: Path) -> Path:
    return home / ".local" / "share" / "codexea" / "fleet" / "scripts" / "codexea_route.py"


def _write_echo_shim(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"printf '{label}:%s\\n' \"$*\"",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_echo_route_helper(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, sys",
                f"label = {label!r}",
                "print(json.dumps({'label': label, 'helper': __file__, 'argv': sys.argv[1:], 'cwd': os.getcwd(), 'home': os.environ.get('HOME', '')}, sort_keys=True))",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_install_script_installs_route_helper_to_share_root(tmp_path: Path) -> None:
    home, completed = _install_codexea(tmp_path)

    launcher = _launcher_path(home)
    managed_shim = _managed_shim_path(home)
    route_helper = _route_helper_path(home)
    assert launcher.is_file()
    assert launcher.stat().st_mode & stat.S_IXUSR
    assert managed_shim.is_file()
    assert managed_shim.stat().st_mode & stat.S_IXUSR
    assert route_helper.is_file()
    assert str(managed_shim) in completed.stdout
    assert str(route_helper) in completed.stdout

    _write_echo_shim(managed_shim, "managed-shim")

    launched = subprocess.run(
        [str(launcher), "current", "shim"],
        cwd=ROOT,
        env=_codexea_launcher_env(home),
        check=True,
        capture_output=True,
        text=True,
    )
    assert launched.stdout == "managed-shim:current shim\n"


def test_managed_shim_launcher_fails_closed_when_default_shim_is_missing(tmp_path: Path) -> None:
    home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(home)
    managed_shim = _managed_shim_path(home)
    missing_shim = managed_shim.with_name("codexea.off")
    managed_shim.rename(missing_shim)

    launched = subprocess.run(
        [str(launcher), "smoke"],
        cwd=ROOT,
        env=_codexea_launcher_env(home),
        check=False,
        capture_output=True,
        text=True,
    )

    assert launched.returncode == 1
    assert launched.stdout == ""
    assert f"Missing managed CodexEA shim: {managed_shim}" in launched.stderr


def test_managed_shim_launcher_honors_fleet_root_override(tmp_path: Path) -> None:
    home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(home)
    _write_echo_shim(_managed_shim_path(home), "default-shim")

    fleet_root = tmp_path / "fleet-root"
    fleet_shim = fleet_root / "scripts" / "codexea"
    _write_echo_shim(fleet_shim, "fleet-shim")

    launched = subprocess.run(
        [str(launcher), "override", "check"],
        cwd=ROOT,
        env=_codexea_launcher_env(home, CODEXEA_FLEET_ROOT=f"{fleet_root}/"),
        check=True,
        capture_output=True,
        text=True,
    )

    assert launched.stdout == "fleet-shim:override check\n"


def test_managed_shim_launcher_honors_explicit_shim_over_fleet_root(tmp_path: Path) -> None:
    home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(home)
    _write_echo_shim(_managed_shim_path(home), "default-shim")

    fleet_root = tmp_path / "fleet-root"
    _write_echo_shim(fleet_root / "scripts" / "codexea", "fleet-shim")
    explicit_shim = tmp_path / "explicit" / "codexea"
    _write_echo_shim(explicit_shim, "explicit-shim")

    launched = subprocess.run(
        [str(launcher), "override", "check"],
        cwd=ROOT,
        env=_codexea_launcher_env(
            home,
            CODEXEA_FLEET_ROOT=str(fleet_root),
            CODEXEA_MANAGED_SHIM=str(explicit_shim),
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    assert launched.stdout == "explicit-shim:override check\n"


def test_managed_shim_launcher_fails_closed_for_missing_explicit_override(tmp_path: Path) -> None:
    home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(home)
    _write_echo_shim(_managed_shim_path(home), "default-shim")

    missing_shim = tmp_path / "missing" / "codexea"
    launched = subprocess.run(
        [str(launcher), "smoke"],
        cwd=ROOT,
        env=_codexea_launcher_env(home, CODEXEA_MANAGED_SHIM=str(missing_shim)),
        check=False,
        capture_output=True,
        text=True,
    )

    assert launched.returncode == 1
    assert launched.stdout == ""
    assert f"Missing managed CodexEA shim: {missing_shim}" in launched.stderr


def test_installed_launcher_onemin_uses_managed_route_helper_outside_repo_when_home_changes(tmp_path: Path) -> None:
    install_home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(install_home)
    route_helper = _route_helper_path(install_home)
    _write_echo_route_helper(route_helper, "managed-route")

    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()
    run_cwd = tmp_path / "not-the-repo"
    run_cwd.mkdir()

    launched = subprocess.run(
        [str(launcher), "onemin", "--probe-all"],
        cwd=run_cwd,
        env=_codexea_launcher_env(runtime_home),
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(launched.stdout)
    assert payload["label"] == "managed-route"
    assert payload["helper"] == str(route_helper)
    assert payload["cwd"] == str(run_cwd)
    assert payload["home"] == str(runtime_home)
    assert payload["argv"][0] == "--onemin-aggregate"
    assert "--probe-all" in payload["argv"]
    assert "--billing" in payload["argv"]


def test_managed_shim_route_helper_prefers_sibling_over_stale_home_helper(tmp_path: Path) -> None:
    install_home, _completed = _install_codexea(tmp_path)
    launcher = _launcher_path(install_home)
    managed_route_helper = _route_helper_path(install_home)
    _write_echo_route_helper(managed_route_helper, "managed-route")

    runtime_home = tmp_path / "runtime-home"
    stale_home_helper = _route_helper_path(runtime_home)
    _write_echo_route_helper(stale_home_helper, "stale-home-route")

    launched = subprocess.run(
        [str(launcher), "onemin", "--probe-all"],
        cwd=tmp_path,
        env=_codexea_launcher_env(runtime_home),
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(launched.stdout)
    assert payload["label"] == "managed-route"
    assert payload["helper"] == str(managed_route_helper)
