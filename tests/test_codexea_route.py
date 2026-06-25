from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codexea_route.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codexea_route", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "probe_all": False,
        "probe_best_effort": False,
        "billing": False,
        "json": False,
        "account_labels": [],
        "timeout_seconds": 300,
        "max_workers": 4,
        "probe_limit": 8,
        "telemetry_answer": None,
        "onemin_aggregate": True,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_default_timeout_is_configurable_via_env(monkeypatch) -> None:
    monkeypatch.setenv("CODEXEA_ONEMIN_TIMEOUT_SECONDS", "420")
    module = _load_module()
    monkeypatch.setattr(module.sys, "argv", ["codexea_route.py"])

    args = module._parse_args()

    assert args.timeout_seconds == 420


def test_default_timeout_is_300_when_env_not_set(monkeypatch) -> None:
    monkeypatch.delenv("CODEXEA_ONEMIN_TIMEOUT_SECONDS", raising=False)
    module = _load_module()
    monkeypatch.setattr(module.sys, "argv", ["codexea_route.py"])

    args = module._parse_args()

    assert args.timeout_seconds == 300


def test_build_route_request_probe_all_is_unbounded() -> None:
    module = _load_module()

    payload = module._build_route_request(
        _args(probe_all=True),
        account_rows=[{"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com"}],
    )

    assert payload["probe"] is True
    assert payload["probe_mode"] == "all"
    assert payload["probe_limit"] == 0


def test_build_route_request_best_effort_is_bounded_without_labels() -> None:
    module = _load_module()

    payload = module._build_route_request(
        _args(probe_best_effort=True, probe_limit=3),
        account_rows=[{"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com"}],
    )

    assert payload["probe"] is True
    assert payload["probe_mode"] == "best_effort"
    assert payload["probe_limit"] == 3


def test_build_route_request_label_targeting_is_not_truncated() -> None:
    module = _load_module()

    payload = module._build_route_request(
        _args(
            probe_best_effort=True,
            probe_limit=1,
            account_labels=["ONEMIN_AI_API_KEY_FALLBACK_9"],
        ),
        account_rows=[{"account_name": "ONEMIN_AI_API_KEY_FALLBACK_9", "owner_email": "owner@example.com"}],
    )

    assert payload["probe"] is True
    assert payload["probe_mode"] == "best_effort"
    assert payload["probe_limit"] == 0
    assert payload["account_labels"] == ["ONEMIN_AI_API_KEY_FALLBACK_9"]


def test_build_route_request_does_not_load_account_rows_without_probe(monkeypatch) -> None:
    module = _load_module()

    def fail_load() -> list[dict[str, object]]:
        raise AssertionError("account ledger should not be loaded without a live probe")

    monkeypatch.setattr(module, "_load_onemin_account_rows", fail_load)

    payload = module._build_route_request(_args())

    assert payload["probe"] is False
    assert payload["account_rows"] == []


def test_load_onemin_account_rows_uses_source_root_env(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "onemin_api_keys.local.json").write_text(
        json.dumps(
            {
                "slots": [
                    {
                        "slot": "primary",
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                        "owner_name": "Owner",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEXEA_SOURCE_ROOT", str(tmp_path))
    monkeypatch.delenv("CODEXEA_ONEMIN_LEDGER_PATHS", raising=False)

    assert module._load_onemin_account_rows() == [
        {
            "slot": "primary",
            "account_name": "ONEMIN_AI_API_KEY",
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
        }
    ]


def test_load_onemin_account_rows_sorts_generic_pool_ascending(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "onemin_api_keys.local.json").write_text(
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_6", "owner_email": "six@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "two@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "primary@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "one@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_5", "owner_email": "five@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_4", "owner_email": "four@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_3", "owner_email": "three@example.com"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEXEA_SOURCE_ROOT", str(tmp_path))
    monkeypatch.delenv("CODEXEA_ONEMIN_LEDGER_PATHS", raising=False)

    rows = module._load_onemin_account_rows()

    assert [row["account_name"] for row in rows] == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
        "ONEMIN_AI_API_KEY_FALLBACK_4",
        "ONEMIN_AI_API_KEY_FALLBACK_5",
        "ONEMIN_AI_API_KEY_FALLBACK_6",
    ]


def test_load_onemin_account_rows_derives_six_generic_accounts_manifest(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "onemin_api_keys.local.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {"key": f"secret-{index}", "owner_email": f"owner{index}@example.com"}
                    for index in range(1, 7)
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEXEA_SOURCE_ROOT", str(tmp_path))
    monkeypatch.delenv("CODEXEA_ONEMIN_LEDGER_PATHS", raising=False)

    rows = module._load_onemin_account_rows()

    assert [row["slot"] for row in rows] == [
        "fallback_1",
        "fallback_2",
        "fallback_3",
        "fallback_4",
        "fallback_5",
        "fallback_6",
    ]
    assert [row["account_name"] for row in rows] == [
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
        "ONEMIN_AI_API_KEY_FALLBACK_4",
        "ONEMIN_AI_API_KEY_FALLBACK_5",
        "ONEMIN_AI_API_KEY_FALLBACK_6",
    ]
    assert rows[5]["owner_email"] == "owner6@example.com"
    assert "key" not in rows[0]


def test_load_onemin_account_rows_accepts_string_key_pool_without_leaking_keys(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "onemin_api_keys.local.json").write_text(
        json.dumps({"keys": ["secret-1", "secret-2", "secret-3"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEXEA_SOURCE_ROOT", str(tmp_path))
    monkeypatch.delenv("CODEXEA_ONEMIN_LEDGER_PATHS", raising=False)

    rows = module._load_onemin_account_rows()

    assert [row["account_name"] for row in rows] == [
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
    ]
    assert all("secret" not in json.dumps(row) for row in rows)


def test_retry_after_parser_recognizes_429_payloads() -> None:
    module = _load_module()

    assert module._cooldown_seconds_for_probe_error('onemin_login_http_429: {"retryAfter": 42}') == 42
    assert module._cooldown_seconds_for_probe_error("Too Many Requests, retry after 7 seconds") == 7
    assert module._cooldown_seconds_for_probe_error("onemin_api_http_429 without explicit retry") == 300
    assert module._cooldown_seconds_for_probe_error("owner_email_missing") == 0


def test_apply_onemin_probe_cooldowns_skips_active_slots(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    cooldown_path = tmp_path / "cooldowns.json"
    monkeypatch.setenv("CODEXEA_ONEMIN_PROBE_COOLDOWN_PATH", str(cooldown_path))
    monkeypatch.setattr(module, "_cooldown_now_epoch", lambda: 1000.0)
    cooldown_path.write_text(
        json.dumps(
            {
                "cooldowns": {
                    "ONEMIN_AI_API_KEY": {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                        "retry_after_seconds": 120,
                        "cooldown_until_epoch": 1060.0,
                        "cooldown_until": "1970-01-01T00:17:40Z",
                        "reason": 'onemin_login_http_429: {"retryAfter": 120}',
                    },
                    "ONEMIN_AI_API_KEY_FALLBACK_1": {
                        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                        "cooldown_until_epoch": 900.0,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    request = module._build_route_request(
        _args(probe_best_effort=True, probe_limit=8),
        account_rows=[
            {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com"},
            {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner@example.com"},
            {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner@example.com"},
        ],
    )

    cooldown_state = module._apply_onemin_probe_cooldowns(request)

    assert [row["account_name"] for row in request["account_rows"]] == ["ONEMIN_AI_API_KEY_FALLBACK_1", "ONEMIN_AI_API_KEY_FALLBACK_2"]
    assert cooldown_state["active_count"] == 1
    assert cooldown_state["skipped_count"] == 1
    assert cooldown_state["skipped"][0]["account_name"] == "ONEMIN_AI_API_KEY"
    assert cooldown_state["skipped"][0]["cooldown_remaining_seconds"] == 60


def test_finalize_onemin_probe_payload_records_retry_after_cooldown(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    cooldown_path = tmp_path / "cooldowns.json"
    monkeypatch.setenv("CODEXEA_ONEMIN_PROBE_COOLDOWN_PATH", str(cooldown_path))
    monkeypatch.setattr(module, "_cooldown_now_epoch", lambda: 1000.0)

    payload = module._finalize_onemin_probe_payload(
        {
            "probe": {
                "requested": True,
                "errors": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                        "error": 'onemin_login_http_429: {"retryAfter": 45}',
                    }
                ],
            }
        },
        cooldown_state={"active_count": 0, "skipped": [], "skipped_count": 0},
    )

    assert payload["probe"]["cooldown"]["new_count"] == 1
    assert payload["probe"]["cooldown"]["new"][0]["account_name"] == "ONEMIN_AI_API_KEY"
    assert payload["probe"]["cooldown"]["new"][0]["retry_after_seconds"] == 45
    stored = json.loads(cooldown_path.read_text(encoding="utf-8"))
    assert stored["cooldowns"]["ONEMIN_AI_API_KEY"]["cooldown_until_epoch"] == 1045.0


def test_http_backend_urls_derive_runtime_telemetry_from_status_url(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setenv("CODEXEA_STATUS_URL", "http://ea-runtime.test:8090/v1/codex/status")
    monkeypatch.delenv("CODEXEA_RUNTIME_TELEMETRY_URL", raising=False)
    monkeypatch.delenv("EA_MCP_BASE_URL", raising=False)
    monkeypatch.delenv("EA_BASE_URL", raising=False)

    urls = module._http_backend_urls()

    assert urls == ["http://ea-runtime.test:8090/v1/runtime/lanes/telemetry?window=7d"]


def test_http_backend_urls_preserve_explicit_runtime_telemetry_url(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setenv("CODEXEA_RUNTIME_TELEMETRY_URL", "http://ea-runtime.test:8090/custom/telemetry")
    monkeypatch.setenv("CODEXEA_STATUS_URL", "http://ea-runtime.test:8090/v1/codex/status")
    monkeypatch.delenv("EA_MCP_BASE_URL", raising=False)
    monkeypatch.delenv("EA_BASE_URL", raising=False)

    urls = module._http_backend_urls()

    assert urls == [
        "http://ea-runtime.test:8090/custom/telemetry?window=7d",
        "http://ea-runtime.test:8090/v1/runtime/lanes/telemetry?window=7d",
    ]


def test_run_live_onemin_aggregate_falls_back_to_local_backend(monkeypatch) -> None:
    module = _load_module()
    args = _args(probe_best_effort=True)
    backend_calls: list[tuple[str, dict[str, object], int]] = []

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(module, "_http_backend_urls", lambda: [])

    def fake_run_backend(command, *, request, timeout_seconds, backend_name):
        backend_calls.append((backend_name, dict(request), timeout_seconds))
        if backend_name == "ea_api_container":
            raise RuntimeError("container_unreachable")
        return {"source": backend_name, "probe": {"requested": True, "mode": request["probe_mode"]}}

    monkeypatch.setattr(module, "_run_backend_command", fake_run_backend)

    payload = module._run_live_onemin_aggregate(args)

    assert payload["source"] == "local_python"
    assert [item[0] for item in backend_calls] == ["ea_api_container", "local_python"]
    assert backend_calls[1][1]["probe"] is True


def test_run_live_onemin_aggregate_skips_active_cooldown_rows(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    args = _args(probe_best_effort=True)
    cooldown_path = tmp_path / "cooldowns.json"
    captured_requests: list[dict[str, object]] = []

    monkeypatch.setenv("CODEXEA_ONEMIN_PROBE_COOLDOWN_PATH", str(cooldown_path))
    monkeypatch.setattr(module, "_cooldown_now_epoch", lambda: 1000.0)
    cooldown_path.write_text(
        json.dumps(
            {
                "cooldowns": {
                    "ONEMIN_AI_API_KEY": {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "retry_after_seconds": 90,
                        "cooldown_until_epoch": 1030.0,
                        "cooldown_until": "1970-01-01T00:17:10Z",
                        "reason": 'onemin_api_http_429: {"retryAfter": 90}',
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "_load_onemin_account_rows",
        lambda: [
            {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com"},
            {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner@example.com"},
        ],
    )
    monkeypatch.setattr(module, "_backend_attempts", lambda request: [("local_python", "subprocess", ["python"])])

    def fake_run_backend_attempt(backend_name, backend_kind, command, *, request, timeout_seconds):
        captured_requests.append(dict(request))
        return {
            "source": backend_name,
            "probe": {
                "requested": True,
                "mode": request["probe_mode"],
                "attempted_count": len(request["account_rows"]),
                "errors": [],
            },
        }

    monkeypatch.setattr(module, "_run_backend_attempt", fake_run_backend_attempt)

    payload = module._run_live_onemin_aggregate(args)

    assert [row["account_name"] for row in captured_requests[0]["account_rows"]] == ["ONEMIN_AI_API_KEY_FALLBACK_1"]
    assert payload["probe"]["attempted_count"] == 1
    assert payload["probe"]["cooldown"]["skipped_count"] == 1
    assert payload["probe"]["cooldown"]["skipped"][0]["account_name"] == "ONEMIN_AI_API_KEY"


def test_run_live_onemin_aggregate_degrades_probe_failures_to_cached(monkeypatch) -> None:
    module = _load_module()
    args = _args(probe_all=True)
    calls: list[tuple[str, bool, str]] = []

    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(module, "_http_backend_urls", lambda: [])

    def fake_run_backend(command, *, request, timeout_seconds, backend_name):
        calls.append((backend_name, bool(request["probe"]), str(request["probe_mode"])))
        if request["probe"]:
            raise RuntimeError("probe_failed")
        return {"source": backend_name, "probe": {"requested": False, "errors": []}}

    monkeypatch.setattr(module, "_run_backend_command", fake_run_backend)

    payload = module._run_live_onemin_aggregate(args)

    assert calls == [("local_python", True, "all"), ("local_python", False, "off")]
    assert payload["source"] == "local_python"
    assert payload["probe"]["requested"] is True
    assert payload["probe"]["mode"] == "all"
    assert payload["probe"]["degraded_to_cached"] is True
    assert payload["probe"]["backend_errors"] == ["probe_failed"]


def test_backend_attempts_skip_local_python_without_app_tree(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    request = module._build_route_request(_args(probe_best_effort=True), account_rows=[])

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(module, "APP_ROOT", tmp_path / "managed-share" / "ea")
    monkeypatch.setattr(module, "_http_backend_urls", lambda: ["http://ea-runtime.test/v1/runtime/lanes/telemetry?window=7d"])

    assert module._local_app_tree_available() is False
    assert [(name, kind) for name, kind, _command in module._backend_attempts(request)] == [
        ("ea_api_container", "subprocess"),
        ("http_runtime_telemetry", "http"),
    ]


def test_run_live_onemin_aggregate_uses_http_cached_when_installed_without_app_tree(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    args = _args(probe_best_effort=True)
    subprocess_calls: list[str] = []
    http_calls: list[tuple[bool, str]] = []

    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(module, "APP_ROOT", tmp_path / "managed-share" / "ea")
    monkeypatch.setattr(module, "_http_backend_urls", lambda: ["http://ea-runtime.test/v1/runtime/lanes/telemetry?window=7d"])

    def fake_run_backend(command, *, request, timeout_seconds, backend_name):
        subprocess_calls.append(backend_name)
        raise AssertionError("local-python should not run without an app tree")

    def fake_run_http_backend(*, request, timeout_seconds, backend_name):
        http_calls.append((bool(request["probe"]), str(request["probe_mode"])))
        if request["probe"]:
            raise RuntimeError("http should only be used for cached telemetry")
        return {
            "source": backend_name,
            "sum_free_credits": 44,
            "actual_free_credits_total": 40,
            "live_remaining_credits_total": 44,
            "probe": {"requested": False, "errors": []},
        }

    monkeypatch.setattr(module, "_run_backend_command", fake_run_backend)
    monkeypatch.setattr(module, "_run_http_backend", fake_run_http_backend)

    payload = module._run_live_onemin_aggregate(args)

    assert subprocess_calls == []
    assert http_calls == [(False, "off")]
    assert payload["source"] == "http_runtime_telemetry"
    assert payload["probe"]["requested"] is True
    assert payload["probe"]["mode"] == "best_effort"
    assert payload["probe"]["degraded_to_cached"] is True
    assert payload["probe"]["backend_errors"] == ["no_live_probe_backend_available"]


def test_http_payload_to_route_payload_maps_runtime_telemetry() -> None:
    module = _load_module()

    payload = module._http_payload_to_route_payload(
        {
            "onemin_aggregate": {
                "sum_free_credits": 100,
                "hours_remaining_at_current_pace": 5,
                "slots": [{"account_name": "ONEMIN_AI_API_KEY"}],
            },
            "onemin_billing_aggregate": {
                "sum_free_credits": 90,
                "remaining_percent_total": 75,
                "current_pace_burn_credits_per_hour": 10,
                "basis_summary": "billing x1",
                "slots": [{"account_name": "ONEMIN_AI_API_KEY", "basis": "billing"}],
            },
        },
        source="http_runtime_telemetry",
    )

    assert payload["source"] == "http_runtime_telemetry"
    assert payload["provider_key"] == "onemin"
    assert payload["sum_free_credits"] == 100
    assert payload["actual_free_credits_total"] == 90
    assert payload["live_remaining_credits_total"] == 100
    assert payload["current_burn_credits_per_hour"] == 10
    assert payload["basis_summary"] == "billing x1"
    assert payload["slots"] == [{"account_name": "ONEMIN_AI_API_KEY", "basis": "billing"}]


def test_run_backend_command_rejects_empty_local_aggregate(monkeypatch) -> None:
    module = _load_module()

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "sum_free_credits": 0,
                "live_remaining_credits_total": 0,
                "actual_free_credits_total": 0,
            }
        )
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Completed())

    try:
        module._run_backend_command(
            ["python3", "-c", "print(1)"],
            request={"account_rows": [{"account_name": "ONEMIN_AI_API_KEY"}]},
            timeout_seconds=5,
            backend_name="local_python",
        )
    except RuntimeError as exc:
        assert str(exc) == "local_python_empty_onemin_aggregate"
    else:
        raise AssertionError("expected local backend validation failure")


def test_command_timeout_gives_cached_status_room_to_finish() -> None:
    module = _load_module()

    assert module._command_timeout_seconds(_args(timeout_seconds=25), probe_mode="off") == 45


def test_run_backend_command_timeout_does_not_dump_request_payload(monkeypatch) -> None:
    module = _load_module()

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=[
                "docker",
                "exec",
                "-e",
                'CODEXEA_ROUTE_REQUEST_JSON={"owner_email":"owner@example.com"}',
            ],
            timeout=5,
        )

    monkeypatch.setattr(module.subprocess, "run", timeout_run)

    try:
        module._run_backend_command(
            ["docker", "exec", "-e", 'CODEXEA_ROUTE_REQUEST_JSON={"owner_email":"owner@example.com"}'],
            request={"account_rows": [{"account_name": "ONEMIN_AI_API_KEY"}]},
            timeout_seconds=5,
            backend_name="ea_api_container",
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected timeout failure")

    assert message == "ea_api_container_timeout_after_5.0s"
    assert "owner@example.com" not in message
    assert "CODEXEA_ROUTE_REQUEST_JSON" not in message


def test_container_script_preserves_multiple_credentials_in_slots() -> None:
    module = _load_module()

    assert "for credential in credentials" in module.CONTAINER_SCRIPT
    assert "credentials = [{}]" in module.CONTAINER_SCRIPT
    assert "\"slot_env_name\": slot_env_name" in module.CONTAINER_SCRIPT
    assert "\"slot_name\": str(credential.get(\"slot_name\") or \"\").strip()" in module.CONTAINER_SCRIPT


def test_summary_payload_is_bounded_and_preserves_probe_headline() -> None:
    module = _load_module()

    payload = module._summary_payload(
        {
            "provider_key": "onemin",
            "generated_at": "2026-06-23T10:00:00Z",
            "source": "local_python",
            "actual_free_credits_total": 111,
            "live_remaining_credits_total": 222,
            "sum_free_credits": 333,
            "current_burn_credits_per_hour": 4.5,
            "hours_remaining_at_current_pace": 49.3,
            "account_count": 70,
            "slots": [{"account_name": "A"}, {"account_name": "B"}],
            "accounts": [{"account_name": "A"}, {"account_name": "B"}],
            "probe": {
                "requested": True,
                "mode": "best_effort",
                "partial": True,
                "attempted_count": 8,
                "ok_count": 4,
                "error_count": 6,
                "last_probe_at": "2026-06-23T10:01:00Z",
                "degraded_to_cached": False,
                "errors": [
                    {"account_name": f"acct-{index}", "error": f"err-{index}", "extra": "ignored"}
                    for index in range(7)
                ],
                "cooldown": {
                    "active_count": 3,
                    "skipped_count": 2,
                    "new_count": 1,
                    "skipped": [
                        {
                            "account_name": "cooldown-a",
                            "cooldown_remaining_seconds": 60,
                            "cooldown_until": "2026-06-23T10:02:00Z",
                            "reason": "ignored",
                        },
                        {
                            "account_name": "cooldown-b",
                            "cooldown_remaining_seconds": 45,
                            "cooldown_until": "2026-06-23T10:01:45Z",
                            "reason": "ignored",
                        },
                    ],
                    "new": [
                        {
                            "account_name": "new-a",
                            "retry_after_seconds": 30,
                            "cooldown_until": "2026-06-23T10:01:30Z",
                            "reason": "ignored",
                        }
                    ],
                },
            },
        }
    )

    assert "accounts" not in payload
    assert "slots" not in payload
    assert payload["account_count"] == 70
    assert payload["slot_count"] == 2
    assert payload["probe"]["requested"] is True
    assert payload["probe"]["mode"] == "best_effort"
    assert payload["probe"]["sample_errors"] == [
        {"account_name": f"acct-{index}", "error": f"err-{index}"}
        for index in range(5)
    ]
    assert payload["probe"]["cooldown"] == {
        "active_count": 3,
        "skipped_count": 2,
        "new_count": 1,
        "sample_skipped": [
            {
                "account_name": "cooldown-a",
                "cooldown_remaining_seconds": 60,
                "cooldown_until": "2026-06-23T10:02:00Z",
            },
            {
                "account_name": "cooldown-b",
                "cooldown_remaining_seconds": 45,
                "cooldown_until": "2026-06-23T10:01:45Z",
            },
        ],
        "sample_new": [
            {
                "account_name": "new-a",
                "retry_after_seconds": 30,
                "cooldown_until": "2026-06-23T10:01:30Z",
            }
        ],
    }
