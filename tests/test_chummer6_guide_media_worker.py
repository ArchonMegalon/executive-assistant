from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_guide_media_worker.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_guide_media_worker", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sandbox_root = Path(tempfile.mkdtemp(prefix="chummer6-media-worker-"))
    module.SCENE_LEDGER_OUT = sandbox_root / "scene-ledger.json"
    module.CHALLENGER_LEDGER_OUT = sandbox_root / "challenger-ledger.json"
    module.PROVIDER_SCHEDULER_OUT = sandbox_root / "provider-scheduler.json"
    return module


def test_provider_order_filters_fallback_render_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setenv(
        "CHUMMER6_IMAGE_PROVIDER_ORDER",
        "magixai,media_factory,ooda_compositor,local_raster,onemin,scene_contract_renderer",
    )

    assert media.provider_order() == ["magixai", "media_factory", "onemin"]


def test_provider_order_preserves_explicit_runtime_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setenv("CHUMMER6_IMAGE_PROVIDER_ORDER", "onemin,magixai,browseract_prompting_systems")

    assert media.provider_order() == ["onemin", "magixai", "browseract_prompting_systems"]


def test_provider_order_defaults_to_non_onemin_media_providers_before_onemin(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_IMAGE_PROVIDER_ORDER", raising=False)
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    assert media.provider_order() == ["media_factory", "browseract_prompting_systems", "browseract_magixai", "magixai", "onemin"]


def test_routed_provider_order_prefers_onemin_for_quality_focus_targets() -> None:
    media = _load_module()

    routed = media.routed_provider_order_for_target(
        "assets/pages/parts-index.png",
        providers=["media_factory", "magixai", "onemin"],
    )

    assert routed[0] == "onemin"


def test_routed_provider_order_keeps_media_factory_first_for_forge() -> None:
    media = _load_module()

    routed = media.routed_provider_order_for_target(
        "assets/horizons/karma-forge.png",
        providers=["onemin", "media_factory", "magixai"],
    )

    assert routed[0] == "media_factory"


def test_routed_provider_order_demotes_unhealthy_provider_for_target_family(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    monkeypatch.setattr(media, "PROVIDER_HEALTH_OUT", tmp_path / "provider-health.json")
    media.write_json_file(
        media.PROVIDER_HEALTH_OUT,
        {
            "providers": {
                "onemin": {
                    "families": {
                        "weak_page": {
                            "recent_attempts": [
                                {"outcome": "timeout"},
                                {"outcome": "no_output_watchdog"},
                            ]
                        }
                    }
                }
            }
        },
    )

    routed = media.routed_provider_order_for_target(
        "assets/pages/parts-index.png",
        providers=["onemin", "media_factory", "magixai"],
    )

    assert routed[0] != "onemin"
    assert routed[-1] == "onemin"


def test_run_magixai_api_provider_prefers_official_route_and_rejects_html(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("CHUMMER6_MAGIXAI_BASE_URL", "https://beta.aimagicx.com/api/v1")
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    calls: list[tuple[str, dict[str, object]]] = []

    class _HtmlResponse:
        def __init__(self, body: str) -> None:
            self.status = 200
            self.headers = {"Content-Type": "text/html; charset=utf-8"}
            self._body = body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body

    class _JsonResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.status = 200
            self.headers = {"Content-Type": "application/json"}
            self._body = json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body

    def fake_urlopen(request, timeout=0):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append((request.full_url, payload))
        if payload["size"] == "landscape_16_9":
            return _HtmlResponse("<!DOCTYPE html><html><body>wrong surface</body></html>")
        return _JsonResponse({"data": [{"url": "https://example.test/magix-image.png"}]})

    monkeypatch.setattr(media.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        media,
        "_download_remote_image",
        lambda url, output_path, name="magixai": ((output_path.write_bytes(b"png"), True)[1], "downloaded"),
    )

    ok, detail = media.run_magixai_api_provider(
        prompt="streetdoc clinic hero",
        output_path=tmp_path / "hero.png",
        width=1280,
        height=720,
    )

    assert ok is True
    assert detail == "downloaded"
    assert calls[0][0] == "https://www.aimagicx.com/api/v1/images/generations"
    assert calls[0][1]["size"] == "landscape_16_9"
    assert calls[1][1]["size"] == "1280x720"


def test_run_onemin_api_provider_uses_manager_reserved_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "resolve_onemin_image_slots",
        lambda: [
            {"env_name": "ONEMIN_AI_API_KEY_FALLBACK_22", "key": "key-22"},
            {"env_name": "ONEMIN_AI_API_KEY_FALLBACK_23", "key": "key-23"},
        ],
    )
    monkeypatch.setattr(
        media,
        "_reserve_onemin_image_slot",
        lambda **kwargs: {
            "lease_id": "lease-1",
            "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_23",
            "account_id": "ONEMIN_AI_API_KEY_FALLBACK_23",
        },
    )
    released: list[tuple[str, str, int | None, str]] = []
    monkeypatch.setattr(
        media,
        "_release_onemin_image_slot",
        lambda *, lease_id, status, actual_credits_delta=None, error="": released.append(
            (lease_id, status, actual_credits_delta, error)
        ),
    )
    monkeypatch.setattr(media, "onemin_model_candidates", lambda: ["gpt-image-1-mini"])
    monkeypatch.setattr(
        media,
        "onemin_payloads",
        lambda model, **kwargs: [{"type": "IMAGE_GENERATOR", "model": model, "promptObject": {"size": "1024x1024"}}],
    )
    monkeypatch.setattr(media, "_estimate_onemin_image_credits", lambda **kwargs: 900)
    monkeypatch.setattr(
        media,
        "_download_remote_image",
        lambda url, output_path, name="onemin": ((output_path.write_bytes(b"png"), True)[1], "downloaded"),
    )

    class _Response:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"url": "https://example.test/image.png"}).encode("utf-8")

    seen_api_keys: list[str] = []

    def fake_urlopen(request, timeout=0):
        headers = {str(key).lower(): value for key, value in request.header_items()}
        seen_api_keys.append(str(headers.get("api-key", "")))
        return _Response()

    monkeypatch.setattr(media.urllib.request, "urlopen", fake_urlopen)

    ok, detail = media.run_onemin_api_provider(
        prompt="render scene",
        output_path=tmp_path / "out.png",
        width=1024,
        height=1024,
    )

    assert ok is True
    assert detail == "downloaded"
    assert seen_api_keys == ["key-23"]
    assert released[0] == ("lease-1", "released", 900, "")


def test_run_onemin_api_provider_uses_local_manager_fallback_when_http_manager_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "resolve_onemin_image_slots",
        lambda: [
            {"env_name": "ONEMIN_AI_API_KEY_FALLBACK_23", "key": "key-23"},
        ],
    )
    monkeypatch.setattr(media, "_reserve_onemin_image_slot", lambda **kwargs: None)
    local_manager = object()
    monkeypatch.setattr(
        media,
        "_reserve_onemin_image_slot_locally",
        lambda **kwargs: (
            {
                "lease_id": "lease-local",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_23",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_23",
            },
            local_manager,
        ),
    )
    released_http: list[tuple[str, str, int | None, str]] = []
    released_local: list[tuple[object | None, str, str, int | None, str]] = []
    monkeypatch.setattr(
        media,
        "_release_onemin_image_slot",
        lambda *, lease_id, status, actual_credits_delta=None, error="": released_http.append(
            (lease_id, status, actual_credits_delta, error)
        ),
    )
    monkeypatch.setattr(
        media,
        "_release_onemin_image_slot_locally",
        lambda *, manager, lease_id, status, actual_credits_delta=None, error="": released_local.append(
            (manager, lease_id, status, actual_credits_delta, error)
        ),
    )
    monkeypatch.setattr(media, "onemin_model_candidates", lambda: ["gpt-image-1-mini"])
    monkeypatch.setattr(
        media,
        "onemin_payloads",
        lambda model, **kwargs: [{"type": "IMAGE_GENERATOR", "model": model, "promptObject": {"size": "1024x1024"}}],
    )
    monkeypatch.setattr(media, "_estimate_onemin_image_credits", lambda **kwargs: 900)
    monkeypatch.setattr(
        media,
        "_download_remote_image",
        lambda url, output_path, name="onemin": ((output_path.write_bytes(b"png"), True)[1], "downloaded"),
    )

    class _Response:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"url": "https://example.test/image.png"}).encode("utf-8")

    monkeypatch.setattr(media.urllib.request, "urlopen", lambda request, timeout=0: _Response())

    ok, detail = media.run_onemin_api_provider(
        prompt="render scene",
        output_path=tmp_path / "out.png",
        width=1024,
        height=1024,
    )

    assert ok is True
    assert detail == "downloaded"
    assert released_http[0] == ("lease-local", "released", 900, "")
    assert released_local[0] == (local_manager, "lease-local", "released", 900, "")


def test_run_onemin_api_provider_trips_no_output_watchdog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "resolve_onemin_image_slots",
        lambda: [{"env_name": "ONEMIN_AI_API_KEY_FALLBACK_23", "key": "key-23"}],
    )
    monkeypatch.setattr(
        media,
        "_reserve_onemin_image_slot",
        lambda **kwargs: {
            "lease_id": "lease-1",
            "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_23",
            "account_id": "ONEMIN_AI_API_KEY_FALLBACK_23",
        },
    )
    released: list[tuple[str, str, int | None, str]] = []
    monkeypatch.setattr(
        media,
        "_release_onemin_image_slot",
        lambda *, lease_id, status, actual_credits_delta=None, error="": released.append(
            (lease_id, status, actual_credits_delta, error)
        ),
    )
    monkeypatch.setattr(media, "_release_onemin_image_slot_locally", lambda **kwargs: None)
    monkeypatch.setattr(media, "onemin_model_candidates", lambda **kwargs: ["gpt-image-1"])
    monkeypatch.setattr(
        media,
        "onemin_payloads",
        lambda *args, **kwargs: [{"type": "IMAGE_GENERATOR", "model": "gpt-image-1", "promptObject": {"size": "1536x1024"}}],
    )
    monkeypatch.setattr(media, "provider_busy_retries", lambda: 1)
    monkeypatch.setattr(media, "provider_busy_delay_seconds", lambda: 0)
    monkeypatch.setattr(media, "onemin_watchdog_seconds", lambda spec=None: 30)

    clock = iter([0.0, 31.0, 31.0, 31.0, 31.0])
    monkeypatch.setattr(media.time, "monotonic", lambda: next(clock))

    class _HttpError(media.urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__(
                url="https://api.1min.ai/api/features",
                code=400,
                msg="bad request",
                hdrs={},
                fp=None,
            )

        def read(self) -> bytes:
            return b'{"message":"OPEN_AI_UNEXPECTED_ERROR"}'

    monkeypatch.setattr(media.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(_HttpError()))

    ok, detail = media.run_onemin_api_provider(
        prompt="render scene",
        output_path=tmp_path / "out.png",
        width=1024,
        height=1024,
    )

    assert ok is False
    assert detail == "onemin:no_output_watchdog_timeout"
    assert released[0][1] == "failed"


def test_run_onemin_api_provider_walks_other_slots_after_synthetic_local_reservation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "resolve_onemin_image_slots",
        lambda: [
            {"env_name": "ONEMIN_RESOLVED_SLOT_1", "key": "empty-key"},
            {"env_name": "ONEMIN_RESOLVED_SLOT_2", "key": "good-key"},
        ],
    )
    monkeypatch.setattr(media, "_reserve_onemin_image_slot", lambda **kwargs: None)
    local_manager = object()
    monkeypatch.setattr(
        media,
        "_reserve_onemin_image_slot_locally",
        lambda **kwargs: (
            {
                "lease_id": "lease-local",
                "secret_env_name": "ONEMIN_RESOLVED_SLOT_1",
                "account_id": "ONEMIN_RESOLVED_SLOT_1",
            },
            local_manager,
        ),
    )
    released_http: list[tuple[str, str, int | None, str]] = []
    released_local: list[tuple[object | None, str, str, int | None, str]] = []
    monkeypatch.setattr(
        media,
        "_release_onemin_image_slot",
        lambda *, lease_id, status, actual_credits_delta=None, error="": released_http.append(
            (lease_id, status, actual_credits_delta, error)
        ),
    )
    monkeypatch.setattr(
        media,
        "_release_onemin_image_slot_locally",
        lambda *, manager, lease_id, status, actual_credits_delta=None, error="": released_local.append(
            (manager, lease_id, status, actual_credits_delta, error)
        ),
    )
    monkeypatch.setattr(media, "onemin_model_candidates", lambda: ["gpt-image-1-mini"])
    monkeypatch.setattr(
        media,
        "onemin_payloads",
        lambda model, **kwargs: [{"type": "IMAGE_GENERATOR", "model": model, "promptObject": {"size": "1024x1024"}}],
    )
    monkeypatch.setattr(media, "_estimate_onemin_image_credits", lambda **kwargs: 900)
    monkeypatch.setattr(
        media,
        "_download_remote_image",
        lambda url, output_path, name="onemin": ((output_path.write_bytes(b"png"), True)[1], "downloaded"),
    )

    class _SuccessResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"url": "https://example.test/image.png"}).encode("utf-8")

    seen_api_keys: list[str] = []

    def fake_urlopen(request, timeout=0):
        headers = {str(key).lower(): value for key, value in request.header_items()}
        api_key = str(headers.get("api-key", ""))
        seen_api_keys.append(api_key)
        if api_key == "empty-key":
            raise media.urllib.error.HTTPError(
                request.full_url,
                406,
                "Not Acceptable",
                hdrs={},
                fp=__import__("io").BytesIO(b'{"errorCode":"INSUFFICIENT_CREDITS","message":"empty"}'),
            )
        return _SuccessResponse()

    monkeypatch.setattr(media.urllib.request, "urlopen", fake_urlopen)

    ok, detail = media.run_onemin_api_provider(
        prompt="render scene",
        output_path=tmp_path / "out.png",
        width=1024,
        height=1024,
    )

    assert ok is True
    assert detail == "downloaded"
    assert seen_api_keys == ["empty-key", "good-key"]
    assert released_http[0] == ("lease-local", "released", 900, "")
    assert released_local[0] == (local_manager, "lease-local", "released", 900, "")


def test_run_command_provider_returns_timeout_when_subprocess_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    monkeypatch.setattr(media, "format_command", lambda parts, **kwargs: ["fake-render"])

    def fake_run(*args, **kwargs):
        raise media.subprocess.TimeoutExpired(cmd="fake-render", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(media.subprocess, "run", fake_run)

    ok, detail = media.run_command_provider(
        "media_factory",
        ["fake-render"],
        prompt="room-first streetdoc clinic",
        output_path=tmp_path / "hero.png",
        width=1280,
        height=720,
    )

    assert ok is False
    assert detail == "media_factory:timeout"


def test_run_command_provider_appends_reference_image_for_media_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    output_path = tmp_path / "hero.png"
    reference_path = tmp_path / "hero-reference.png"
    reference_path.write_bytes(b"png")
    seen: dict[str, object] = {}

    monkeypatch.setattr(media, "format_command", lambda parts, **kwargs: ["fake-render"])

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        output_path.write_bytes(b"png")
        return None

    monkeypatch.setattr(media.subprocess, "run", fake_run)

    ok, detail = media.run_command_provider(
        "media_factory",
        ["fake-render"],
        prompt="room-first streetdoc clinic",
        output_path=output_path,
        width=1280,
        height=720,
        reference_image=reference_path,
    )

    assert ok is True
    assert detail == "media_factory:rendered"
    assert seen["command"] == ["fake-render", "--reference-image", str(reference_path)]


def test_run_url_provider_returns_timeout_when_request_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()

    def fake_urlopen(request, timeout=0):
        raise TimeoutError("provider stalled")

    monkeypatch.setattr(media.urllib.request, "urlopen", fake_urlopen)

    ok, detail = media.run_url_provider(
        "magixai",
        "https://example.test/render?prompt={prompt}&width={width}&height={height}",
        prompt="industrial research forge",
        output_path=tmp_path / "forge.png",
        width=1280,
        height=720,
    )

    assert ok is False
    assert detail == "magixai:timeout"


def test_media_factory_timeout_defaults_support_slower_high_quality_renders() -> None:
    media = _load_module()

    assert media.command_provider_timeout_seconds("media_factory") == 240
    assert media.url_provider_timeout_seconds("media_factory") == 240


def test_reserve_onemin_image_slot_locally_synthesizes_candidates_when_provider_health_has_no_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _load_module()

    class _FakeManager:
        def __init__(self, repo=None) -> None:
            self.calls: list[dict[str, object]] = []

        def _candidates_from_provider_health(self, *, provider_health):
            return []

        def reserve_for_candidates(
            self,
            *,
            candidates,
            lane,
            capability,
            principal_id,
            request_id,
            estimated_credits,
            allow_reserve,
        ):
            self.calls.append(
                {
                    "candidates": [dict(candidate) for candidate in candidates],
                    "lane": lane,
                    "capability": capability,
                    "principal_id": principal_id,
                    "request_id": request_id,
                    "estimated_credits": estimated_credits,
                    "allow_reserve": allow_reserve,
                }
            )
            if estimated_credits:
                return None
            chosen = candidates[0]
            return {
                "lease_id": "lease-synth",
                "secret_env_name": str(chosen.get("secret_env_name") or ""),
                "account_id": str(chosen.get("account_id") or chosen.get("account_name") or ""),
            }

    fake_manager_holder: dict[str, object] = {}

    def _build_repo(settings):
        return object()

    def _build_settings():
        return object()

    def _with_backend(settings, backend):
        return settings

    services_pkg = types.ModuleType("app.services")
    responses_upstream_mod = types.ModuleType("app.services.responses_upstream")
    responses_upstream_mod._provider_health_report = lambda: {"providers": {"onemin": {"slots": []}}}
    responses_upstream_mod._env = lambda name: {
        "EA_RESPONSES_ONEMIN_ACTIVE_SLOTS": "ONEMIN_AI_API_KEY",
        "EA_RESPONSES_ONEMIN_RESERVE_SLOTS": "ONEMIN_AI_API_KEY_FALLBACK_1",
    }.get(name, "")
    responses_upstream_mod._csv_values = lambda value: [item.strip() for item in str(value or "").split(",") if item.strip()]
    services_pkg.responses_upstream = responses_upstream_mod

    onemin_manager_mod = types.ModuleType("app.services.onemin_manager")

    def _manager_factory(repo=None):
        manager = _FakeManager(repo=repo)
        fake_manager_holder["manager"] = manager
        return manager

    onemin_manager_mod.OneminManagerService = _manager_factory

    repositories_mod = types.ModuleType("app.repositories.onemin_manager")
    repositories_mod.build_onemin_manager_service_repo = _build_repo

    settings_mod = types.ModuleType("app.settings")
    settings_mod.get_settings = _build_settings
    settings_mod.settings_with_storage_backend = _with_backend

    monkeypatch.setattr(
        media,
        "resolve_onemin_image_slots",
        lambda: [
            {"env_name": "ONEMIN_AI_API_KEY", "key": "primary"},
            {"env_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "key": "fallback"},
        ],
    )
    monkeypatch.setattr(media, "_estimate_onemin_image_credits", lambda **kwargs: 900)
    monkeypatch.setitem(sys.modules, "app.services", services_pkg)
    monkeypatch.setitem(sys.modules, "app.services.responses_upstream", responses_upstream_mod)
    monkeypatch.setitem(sys.modules, "app.services.onemin_manager", onemin_manager_mod)
    monkeypatch.setitem(sys.modules, "app.repositories.onemin_manager", repositories_mod)
    monkeypatch.setitem(sys.modules, "app.settings", settings_mod)

    lease, manager = media._reserve_onemin_image_slot_locally(
        width=1024,
        height=1024,
        principal_id="ea-chummer6",
        allow_reserve=True,
        request_id="req-1",
    )

    assert lease == {
        "lease_id": "lease-synth",
        "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
        "account_id": "ONEMIN_AI_API_KEY_FALLBACK_1",
    }
    assert manager is fake_manager_holder["manager"]
    assert [call["estimated_credits"] for call in fake_manager_holder["manager"].calls[:2]] == [900, 0]
    assert [candidate["secret_env_name"] for candidate in fake_manager_holder["manager"].calls[-1]["candidates"]] == [
        "ONEMIN_AI_API_KEY_FALLBACK_1"
    ]


def test_onemin_model_candidates_prefers_flux_schnell_before_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_ONEMIN_MODEL", raising=False)
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    assert media.onemin_model_candidates()[:3] == [
        "black-forest-labs/flux-schnell",
        "gpt-image-1-mini",
        "gpt-image-1",
    ]


def test_onemin_model_candidates_honors_spec_override_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_ONEMIN_MODEL", raising=False)
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    assert media.onemin_model_candidates({"onemin_models": ["gpt-image-1", "gpt-image-1-mini"]})[:3] == [
        "gpt-image-1",
        "gpt-image-1-mini",
        "black-forest-labs/flux-schnell",
    ]


def test_resolve_onemin_image_slots_assigns_stable_names_to_script_only_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    fake_root = Path("/tmp/fake_ea_root")
    fake_script = fake_root / "scripts" / "resolve_onemin_ai_key.sh"
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})
    monkeypatch.setattr(media, "EA_ROOT", fake_root)
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "primary-key")

    def fake_check_output(command, text=True):
        assert command == ["bash", str(fake_script), "--all"]
        return "primary-key\nfallback-a\nfallback-b\n"

    monkeypatch.setattr(media.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(type(fake_script), "exists", lambda self: str(self) == str(fake_script))

    slots = media.resolve_onemin_image_slots()

    assert slots == [
        {"env_name": "ONEMIN_AI_API_KEY", "key": "primary-key"},
        {"env_name": "ONEMIN_RESOLVED_SLOT_1", "key": "fallback-a"},
        {"env_name": "ONEMIN_RESOLVED_SLOT_2", "key": "fallback-b"},
    ]


def test_onemin_payloads_build_flux_schnell_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setenv("CHUMMER6_ONEMIN_FLUX_SCHNELL_MEGAPIXELS", "1")
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    payloads = media.onemin_payloads(
        "black-forest-labs/flux-schnell",
        prompt="streetdoc clinic hero",
        width=1280,
        height=720,
    )

    assert payloads == [
        {
            "type": "IMAGE_GENERATOR",
            "model": "black-forest-labs/flux-schnell",
            "promptObject": {
                "prompt": "streetdoc clinic hero",
                "aspect_ratio": "16:9",
                "num_inference_steps": 4,
                "go_fast": True,
                "megapixels": "1",
                "output_quality": 80,
            },
        }
    ]


def test_onemin_payloads_honor_spec_quality_and_style_for_gpt_image(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_ONEMIN_IMAGE_QUALITY", raising=False)
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    payloads = media.onemin_payloads(
        "gpt-image-1",
        prompt="hero poster",
        width=960,
        height=540,
        spec={"onemin_image_quality": "high", "onemin_image_style": "vivid"},
    )

    assert payloads[0]["promptObject"]["quality"] == "high"
    assert payloads[0]["promptObject"]["style"] == "vivid"


def test_run_release_build_pipeline_refreshes_registry_then_runs_builder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    release_control = tmp_path / "materialize_chummer_release_registry_projection.py"
    release_control.write_text("", encoding="utf-8")
    release_builder = tmp_path / "chummer6_release_builder.py"
    release_builder.write_text("", encoding="utf-8")
    matrix_path = tmp_path / "chummer6_release_matrix.json"
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> object:
        calls.append(list(command))
        if command[1] == str(release_control):
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"output": str(matrix_path), "artifacts": 3}),
                "stderr": "",
            },
        )()

    monkeypatch.setattr(media, "RELEASE_CONTROL_SCRIPT", release_control)
    monkeypatch.setattr(media, "RELEASE_BUILDER_SCRIPT", release_builder)
    monkeypatch.setattr(media, "RELEASE_MATRIX_OUT", matrix_path)
    monkeypatch.setattr(media, "_run_release_build_command", fake_run)

    result = media.run_release_build_pipeline()

    assert result == {
        "status": "built",
        "registry_projection": "refreshed",
        "output": str(matrix_path),
        "commands": [
            ["python3", str(release_control)],
            ["python3", str(release_builder), "--output", str(matrix_path)],
        ],
        "artifacts": 3,
    }
    assert calls == result["commands"]


def test_render_pack_enables_release_build_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    seen: dict[str, object] = {}
    monkeypatch.setattr(media, "asset_specs", lambda: [{"target": "assets/hero/chummer6-hero.png"}])

    def fake_render_specs(*, specs, output_dir, build_release=False):
        seen["specs"] = specs
        seen["output_dir"] = output_dir
        seen["build_release"] = build_release
        return {"output_dir": str(output_dir), "assets": [], "release_build": {"status": "built"}}

    monkeypatch.setattr(media, "render_specs", fake_render_specs)

    media.render_pack(output_dir=tmp_path)

    assert seen["build_release"] is True


def test_render_targets_keep_release_build_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    seen: dict[str, object] = {}

    def fake_render_specs(*, specs, output_dir, build_release=False):
        seen["specs"] = specs
        seen["output_dir"] = output_dir
        seen["build_release"] = build_release
        return {"output_dir": str(output_dir), "assets": [], "release_build": {"status": "skipped"}}

    monkeypatch.setattr(
        media,
        "asset_specs",
        lambda: [
            {
                "target": "assets/hero/chummer6-hero.png",
                "prompt": "",
                "width": 1280,
                "height": 720,
                "media_row": {},
            }
        ],
    )
    monkeypatch.setattr(media, "render_specs", fake_render_specs)

    media.render_targets(targets=["assets/hero/chummer6-hero.png"], output_dir=tmp_path)

    assert seen["build_release"] is False
    assert seen["specs"] == [
        {
            "target": "assets/hero/chummer6-hero.png",
            "prompt": "",
            "width": 1280,
            "height": 720,
            "media_row": {},
            "allow_repeat": True,
        }
    ]


def test_reserve_onemin_image_slot_allows_reserve_pool_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    seen: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        media,
        "_ea_local_json_post",
        lambda path, payload: (seen.append((path, dict(payload))), {"lease_id": "lease-1"})[1],
    )

    payload = media._reserve_onemin_image_slot(width=1536, height=1024)

    assert payload == {"lease_id": "lease-1"}
    assert seen == [
        (
            "/v1/providers/onemin/reserve-image",
            {
                "request_id": seen[0][1]["request_id"],
                "estimated_credits": media._estimate_onemin_image_credits(width=1536, height=1024),
                "allow_reserve": True,
            },
        )
    ]


def test_reserve_onemin_image_slot_can_disable_reserve_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    seen: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setenv("CHUMMER6_ONEMIN_ALLOW_RESERVE", "0")
    monkeypatch.setattr(
        media,
        "_ea_local_json_post",
        lambda path, payload: (seen.append((path, dict(payload))), {"lease_id": "lease-2"})[1],
    )

    payload = media._reserve_onemin_image_slot(width=1024, height=1024)

    assert payload == {"lease_id": "lease-2"}
    assert seen == [
        (
            "/v1/providers/onemin/reserve-image",
            {
                "request_id": seen[0][1]["request_id"],
                "estimated_credits": media._estimate_onemin_image_credits(width=1024, height=1024),
                "allow_reserve": False,
            },
        )
    ]


def test_resolve_onemin_image_keys_keeps_fallback_rotation_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_ONEMIN_USE_FALLBACK_KEYS", raising=False)
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "fallback-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "fallback-2")
    monkeypatch.setattr(media.subprocess, "check_output", lambda *args, **kwargs: "")

    assert media.resolve_onemin_image_keys() == ["primary", "fallback-1", "fallback-2"]


def test_render_with_ooda_rejects_forbidden_fallback_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_IMAGE_PROVIDER_ORDER", raising=False)
    media.LOCAL_ENV.pop("CHUMMER6_IMAGE_PROVIDER_ORDER", None)
    media.POLICY_ENV.pop("CHUMMER6_IMAGE_PROVIDER_ORDER", None)

    with pytest.raises(RuntimeError, match="scene_contract_renderer:forbidden_fallback"):
        media.render_with_ooda(
            prompt="receipt-first skyline",
            output_path=tmp_path / "out.png",
            width=960,
            height=540,
            spec={"providers": ["scene_contract_renderer"]},
        )


def test_render_with_ooda_delegates_media_factory_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    seen: dict[str, object] = {}

    def fake_run_command_provider(name: str, template: list[str], **kwargs):
        assert name == "media_factory"
        assert template
        seen["prompt"] = kwargs["prompt"]
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"png")
        return True, "media_factory:rendered"

    monkeypatch.setattr(media, "run_command_provider", fake_run_command_provider)

    result = media.render_with_ooda(
        prompt="bounded runsite scene",
        output_path=tmp_path / "out.png",
        width=1600,
        height=900,
        spec={"providers": ["media_factory"]},
    )

    assert result["provider"] == "media_factory"
    assert result["status"] == "media_factory:rendered"
    assert seen["prompt"] == "bounded runsite scene"


def test_render_with_ooda_treats_explicit_provider_order_as_a_strict_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = _load_module()
    monkeypatch.setenv("CHUMMER6_IMAGE_PROVIDER_ORDER", "onemin")
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    attempted_commands: list[str] = []

    def fake_run_command_provider(name: str, template: list[str], **kwargs):
        attempted_commands.append(name)
        return False, f"{name}:should_not_run"

    monkeypatch.setattr(media, "run_command_provider", fake_run_command_provider)
    monkeypatch.setattr(media, "run_onemin_api_provider", lambda **kwargs: (False, "onemin:manager_unavailable"))

    with pytest.raises(RuntimeError, match="onemin:manager_unavailable"):
        media.render_with_ooda(
            prompt="bounded runsite scene",
            output_path=tmp_path / "out.png",
            width=1600,
            height=900,
            spec={
                "target": "assets/hero/chummer6-hero.png",
                "media_row": {"scene_contract": {}},
                "providers": ["media_factory", "onemin", "browseract_prompting_systems"],
            },
        )

    assert attempted_commands == []


def test_render_with_ooda_preserves_spec_provider_order_without_env_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_IMAGE_PROVIDER_ORDER", raising=False)
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    attempted_commands: list[str] = []

    def fake_run_command_provider(name: str, template: list[str], **kwargs):
        attempted_commands.append(name)
        if name == "browseract_prompting_systems":
            output_path = kwargs["output_path"]
            output_path.write_bytes(b"png")
            return True, "browseract_prompting_systems:rendered"
        return False, f"{name}:should_not_run"

    monkeypatch.setattr(media, "run_command_provider", fake_run_command_provider)
    monkeypatch.setattr(media, "run_url_provider", lambda *args, **kwargs: (False, "url:should_not_run"))

    result = media.render_with_ooda(
        prompt="bounded runsite scene",
        output_path=tmp_path / "out.png",
        width=1600,
        height=900,
        spec={
            "target": "assets/horizons/jackpoint.png",
            "media_row": {"scene_contract": {}},
            "providers": ["browseract_prompting_systems", "media_factory", "onemin"],
        },
    )

    assert attempted_commands[0] == "browseract_prompting_systems"
    assert result["provider"] == "browseract_prompting_systems"


def test_canonical_horizon_visual_contract_uses_canon_not_bespoke_fallback_map() -> None:
    media = _load_module()

    row = media.canonical_horizon_visual_contract("runsite", media.CANON_HORIZONS["runsite"])

    assert media.HORIZON_MEDIA_FALLBACKS == {}
    assert row["title"] == "RUNSITE"
    assert row["visual_prompt"]
    assert row["scene_contract"]["composition"] == "district_map"
    assert row["overlay_callouts"]


def test_forbid_legacy_svg_fallback_rejects_svg_targets(tmp_path: Path) -> None:
    media = _load_module()

    with pytest.raises(RuntimeError, match="legacy_svg_fallback_forbidden"):
        media.forbid_legacy_svg_fallback(tmp_path / "old-fallback.svg")


def test_is_credit_exhaustion_message_matches_common_provider_failures() -> None:
    media = _load_module()

    assert media.is_credit_exhaustion_message("INSUFFICIENT_CREDITS")
    assert media.is_credit_exhaustion_message("your balance is too low to continue")
    assert not media.is_credit_exhaustion_message("http_404: not found")


def test_sanitize_scene_humor_drops_readable_meta_jokes_but_keeps_adult_in_world_lines() -> None:
    media = _load_module()

    assert (
        media.sanitize_scene_humor("A worn sticker on the workbench reads: 'IF THE MATH SUCKS, THE CODE FUCKS'.")
        == ""
    )
    assert media.sanitize_scene_humor("A mean bastard of a night, but the rig still holds.") == (
        "A mean bastard of a night, but the rig still holds."
    )


def test_sanitize_media_row_strips_explicit_easter_eggs_for_non_sparse_targets() -> None:
    media = _load_module()

    row = media.sanitize_media_row(
        target="assets/parts/ui.png",
        row={
            "visual_prompt": "Prep desk scene, a troll monitor sticker is clearly visible on the bezel, grounded and tactile.",
            "visual_motifs": ["prep desk", "troll monitor sticker"],
            "overlay_callouts": ["receipt traces"],
            "scene_contract": {
                "subject": "a player building a runner",
                "environment": "a prep desk",
                "action": "checking gear",
                "metaphor": "receipt-first prep",
                "props": ["laptop", "troll monitor sticker"],
                "overlays": ["receipt traces"],
                "composition": "desk_still_life",
                "palette": "cyan",
                "mood": "focused",
                "humor": "A worn sticker on the monitor reads: 'NOT MY BUG'.",
                "easter_egg_kind": "troll monitor sticker",
                "easter_egg_placement": "upper-left bezel",
                "easter_egg_detail": "classic Chummer troll sticker",
                "easter_egg_visibility": "obvious",
            },
        },
    )

    assert "troll" not in row["visual_prompt"].lower()
    assert row["scene_contract"]["humor"] == ""
    assert "easter_egg_kind" not in row["scene_contract"]
    assert not any("troll" in entry.lower() for entry in row["visual_motifs"])


def test_sanitize_media_row_strips_sparse_showcase_easter_egg_targets_from_karma_forge() -> None:
    media = _load_module()

    row = media.sanitize_media_row(
        target="assets/horizons/karma-forge.png",
        row={
            "visual_prompt": "Rulesmith bench scene with a tiny troll forge patch on the apron.",
            "visual_motifs": ["rulesmith bench", "forge sparks"],
            "overlay_callouts": ["rollback markers"],
            "scene_contract": {
                "subject": "a rulesmith at a bench",
                "environment": "an industrial workshop",
                "action": "hammering volatile rules into shape",
                "metaphor": "forge sparks and molten rules",
                "props": ["forge tools", "receipt traces"],
                "overlays": ["rollback markers"],
                "composition": "workshop_bench",
                "palette": "rust amber",
                "mood": "intense",
                "humor": "The bastard thing finally behaves.",
                "easter_egg_kind": "troll forge patch",
                "easter_egg_placement": "on the apron strap",
                "easter_egg_detail": "classic Chummer troll embroidered as a forge patch",
                "easter_egg_visibility": "small but visible",
            },
        },
    )

    assert "easter_egg_kind" not in row["scene_contract"]
    assert row["scene_contract"]["humor"] == ""


def test_build_safe_onemin_prompt_does_not_force_troll_clause_without_explicit_request() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Grounded archive scene with dossier props.",
        spec={
            "media_row": {
                "visual_prompt": "Grounded archive scene with dossier props.",
                "scene_contract": {
                    "subject": "an archivist",
                    "environment": "a dim archive room",
                    "action": "sorting receipts",
                    "metaphor": "provenance before hype",
                    "composition": "archive_room",
                    "mood": "focused",
                    "props": ["binders", "chips"],
                    "overlays": ["receipt traces"],
                },
            }
        },
    )

    assert "troll motif" not in prompt.lower()


def test_first_contact_targets_do_not_get_sparse_karma_forge_easter_egg_allowance() -> None:
    media = _load_module()

    assert media.easter_egg_allowed_for_target("assets/horizons/karma-forge.png") is False


def test_build_safe_onemin_prompt_does_not_force_human_presence_for_environment_map_targets() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Wide work-zone map scene.",
        spec={
            "target": "assets/pages/parts-index.png",
            "media_row": {
                "scene_contract": {
                    "subject": "a walkable room map",
                    "environment": "an open warehouse floor with several work zones",
                    "action": "connecting the zones with route lines",
                    "metaphor": "a walkable map of work zones instead of a menu",
                    "composition": "district_map",
                    "mood": "grounded",
                },
            },
        },
    )

    assert "Human presence must be obvious" not in prompt


def test_build_safe_onemin_prompt_does_not_keep_troll_clause_for_karma_forge_even_when_requested() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Rulesmith forge scene.",
        spec={
            "target": "assets/horizons/karma-forge.png",
            "media_row": {
                "visual_prompt": "Rulesmith forge scene.",
                "scene_contract": {
                    "subject": "a rulesmith",
                    "environment": "a forge bench",
                    "action": "hammering volatile rules into shape",
                    "composition": "workshop_bench",
                    "mood": "intense",
                    "easter_egg_kind": "troll forge patch",
                    "easter_egg_placement": "on the apron strap",
                    "easter_egg_detail": "classic Chummer troll embroidered as a forge patch",
                    "easter_egg_visibility": "small but visible",
                },
            }
        },
    )

    assert "troll motif" not in prompt.lower()


def test_build_safe_onemin_prompt_does_not_force_troll_clause_for_non_sparse_targets_even_with_explicit_fields() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Prep desk scene with receipts.",
        spec={
            "target": "assets/parts/ui.png",
            "media_row": {
                "visual_prompt": "Prep desk scene with receipts.",
                "scene_contract": {
                    "subject": "a player building a runner",
                    "environment": "a prep desk",
                    "action": "checking gear",
                    "composition": "desk_still_life",
                    "mood": "focused",
                    "easter_egg_kind": "troll monitor sticker",
                    "easter_egg_placement": "upper-left bezel",
                    "easter_egg_detail": "classic Chummer troll sticker",
                    "easter_egg_visibility": "obvious",
                },
            },
        },
    )

    assert "troll motif" not in prompt.lower()


def test_build_safe_pollinations_prompt_does_not_force_troll_clause_without_explicit_request() -> None:
    media = _load_module()

    prompt = media.build_safe_pollinations_prompt(
        prompt="Grounded archive scene with dossier props.",
        spec={
            "media_row": {
                "visual_prompt": "Grounded archive scene with dossier props.",
                "scene_contract": {
                    "subject": "an archivist",
                    "environment": "a dim archive room",
                    "action": "sorting receipts",
                    "metaphor": "provenance before hype",
                    "composition": "archive_room",
                    "mood": "focused",
                },
            }
        },
    )

    assert "troll motif" not in prompt.lower()


def test_build_safe_pollinations_prompt_adds_hero_and_map_specific_hard_blocks() -> None:
    media = _load_module()

    hero_prompt = media.build_safe_pollinations_prompt(
        prompt="Hero prep scene.",
        spec={
            "target": "assets/hero/chummer6-hero.png",
            "media_row": {
                "scene_contract": {
                    "subject": "one runner",
                    "environment": "a prep wall threshold",
                    "action": "checking whether the build trail deserves trust",
                    "composition": "street_front",
                    "mood": "tense",
                },
            },
        },
    )
    horizons_prompt = media.build_safe_pollinations_prompt(
        prompt="Wide horizon map.",
        spec={
            "target": "assets/pages/horizons-index.png",
            "media_row": {
                "scene_contract": {
                    "subject": "future lanes",
                    "environment": "a rain-slick interchange",
                    "action": "splitting into possible routes",
                    "composition": "horizon_boulevard",
                    "mood": "grounded",
                },
            },
        },
    )

    assert "no crate desk" in hero_prompt.lower()
    assert "illustrated cover-grade shadowrun streetdoc poster scene" in hero_prompt.lower()
    assert "overlay mode medscan diagnostic" in hero_prompt.lower()
    assert "no central signboard" in horizons_prompt.lower()
    assert "ambient diegetic" in horizons_prompt.lower()


def test_build_safe_onemin_prompt_adds_target_specific_layout_blocks() -> None:
    media = _load_module()

    hero_prompt = media.build_safe_onemin_prompt(
        prompt="Hero prep scene.",
        spec={
            "target": "assets/hero/chummer6-hero.png",
            "media_row": {
                "scene_contract": {
                    "subject": "one runner",
                    "environment": "a prep wall threshold",
                    "action": "checking whether the build trail deserves trust",
                    "composition": "street_front",
                    "mood": "tense",
                },
            },
        },
    )
    what_prompt = media.build_safe_onemin_prompt(
        prompt="What-is scene.",
        spec={
            "target": "assets/pages/what-chummer6-is.png",
            "media_row": {
                "scene_contract": {
                    "subject": "one runner",
                    "environment": "a review bay",
                    "action": "cross-checking receipts on a standing trace surface",
                    "composition": "review_bay",
                    "mood": "focused",
                },
            },
        },
    )

    assert "hacked repair recliner" in hero_prompt.lower()
    assert "illustrated cover-grade cyberpunk-fantasy streetdoc cover art." in hero_prompt.lower()
    assert "environment first" in hero_prompt.lower()
    assert "figures occupy less than one quarter of frame" in hero_prompt.lower()
    assert "no face-only portrait" in what_prompt.lower()
    assert "poster energy is welcome when it stays tied to a lived scene" not in what_prompt.lower()


def test_build_safe_media_factory_prompt_uses_compact_flagship_scene_prompt() -> None:
    media = _load_module()

    hero_prompt = media.build_safe_media_factory_prompt(
        prompt="Hero prep scene.",
        spec={
            "target": "assets/hero/chummer6-hero.png",
            "media_row": {
                "scene_contract": {
                    "subject": "one runner",
                    "environment": "a prep wall threshold",
                    "action": "checking whether the build trail deserves trust",
                    "composition": "street_front",
                    "mood": "tense",
                },
            },
        },
    )

    lowered = hero_prompt.lower()
    assert "illustrated cover-grade cyberpunk-fantasy streetdoc cover art." in lowered
    assert "figures occupy less than one quarter of frame" in lowered
    assert "added in post" in lowered or "painted scene may only carry faint abstract scan glows" in lowered
    assert "hacked repair recliner" in lowered


def test_build_safe_onemin_prompt_keeps_critical_scene_brief_before_clip() -> None:
    media = _load_module()

    hero_prompt = media.build_safe_onemin_prompt(
        prompt="Hero prep scene.",
        spec={
            "target": "assets/hero/chummer6-hero.png",
            "media_row": {
                "visual_prompt": (
                    "Illustrated flagship promo poster for a cyberpunk-fantasy tabletop world, grimy barrens garage "
                    "converted into a streetdoc patch-up clinic, ork streetdoc actively operating on an ugly hairy troll "
                    "runner on a hacked surgical recliner built from mechanic-shop gear."
                ),
                "scene_contract": {
                    "subject": "an ork streetdoc stabilizing an ugly hairy troll runner",
                    "environment": "a grimy barrens garage clinic with wet concrete, rust, oil, and hacked med gear",
                    "action": "calibrating cyberware and stabilizing post-run strain while a teammate crowds the frame",
                    "composition": "clinic_intake",
                    "mood": "tense",
                    "props": ["tool chest", "med-gel", "cyberarm parts", "magical focus"],
                    "overlays": ["BOD rail", "ESS state", "cyberlimb calibration"],
                },
            },
        },
    )

    lowered = hero_prompt.lower()
    assert "hairy troll" in lowered
    assert "full treatment bay" in lowered or "wet floor" in lowered or "tool wall" in lowered
    assert "added in post" in lowered or "post-composited later" in lowered
    assert "medscan diagnostic" in lowered
    assert "cyberlimb calibration" not in lowered
    assert "bod rail" not in lowered
    assert "figures occupy less than one quarter of frame" in lowered


def test_onemin_size_candidates_honor_specified_wide_sizes() -> None:
    media = _load_module()

    assert media.onemin_size_candidates(
        "gpt-image-1",
        width=960,
        height=540,
        spec={"onemin_sizes": ["auto", "1536x1024"]},
    ) == ["auto", "1536x1024"]


def test_overlay_mode_for_target_maps_flagship_assets() -> None:
    media = _load_module()

    assert media.overlay_mode_for_target("assets/hero/chummer6-hero.png") == "medscan_diagnostic"
    assert media.overlay_mode_for_target("assets/pages/horizons-index.png") == "ambient_diegetic"
    assert media.overlay_mode_for_target("assets/horizons/karma-forge.png") == "forge_review_ar"
    assert media.overlay_mode_for_target("assets/pages/start-here.png") == ""


def test_page_media_row_does_not_literalize_page_id_as_metaphor() -> None:
    media = _load_module()

    loaded = media.load_media_overrides()
    pages = loaded["pages"]
    section_ooda = loaded["section_ooda"]["pages"]

    def page_media_row(page_id: str, *, role: str, composition_hint: str):
        page_row = pages.get(page_id)
        ooda_row = section_ooda.get(page_id)
        act = ooda_row.get("act") if isinstance(ooda_row.get("act"), dict) else {}
        observe = ooda_row.get("observe") if isinstance(ooda_row.get("observe"), dict) else {}
        orient = ooda_row.get("orient") if isinstance(ooda_row.get("orient"), dict) else {}
        decide = ooda_row.get("decide") if isinstance(ooda_row.get("decide"), dict) else {}
        interests = observe.get("likely_interest") if isinstance(observe.get("likely_interest"), list) else []
        concrete = observe.get("concrete_signals") if isinstance(observe.get("concrete_signals"), list) else []
        return {
            "title": role,
            "subtitle": str(page_row.get("intro", "")).strip(),
            "kicker": str(page_row.get("kicker", "")).strip(),
            "note": str(page_row.get("body", "")).strip(),
            "overlay_hint": str(decide.get("overlay_priority", "")).strip() or str(orient.get("visual_devices", "")).strip(),
            "visual_prompt": str(act.get("visual_prompt_seed", "")).strip(),
            "visual_motifs": [str(entry).strip() for entry in interests if str(entry).strip()],
            "overlay_callouts": [str(entry).strip() for entry in concrete if str(entry).strip()],
            "scene_contract": {
                "subject": str(orient.get("focal_subject") or "a cyberpunk protagonist").strip(),
                "environment": str(orient.get("scene_logic") or str(page_row.get("body", "")).strip()).strip(),
                "action": str(act.get("paragraph_seed", "")).strip() or str(act.get("one_liner", "")).strip(),
                "metaphor": "",
                "props": [],
                "overlays": [],
                "composition": composition_hint,
                "palette": str(orient.get("visual_devices", "")).strip(),
                "mood": str(orient.get("emotional_goal", "")).strip(),
                "humor": "",
            },
        }

    row = page_media_row("current_status", role="current-status banner", composition_hint="street_front")
    assert row["scene_contract"]["metaphor"] == ""


def test_contains_machine_overlay_language_flags_overliteralized_diagnostic_tokens() -> None:
    media = _load_module()

    assert media.contains_machine_overlay_language("Display Link Verified telemetry between screens.")
    assert media.contains_machine_overlay_language("Weapon diagnostics explain the damage modifiers.")
    assert media.contains_machine_overlay_language("Ares Predator smartlink electronics and barrel rifling.")


def test_scene_rows_for_style_epoch_can_refuse_stale_fallback_rows() -> None:
    media = _load_module()
    ledger = {
        "assets": [
            {
                "target": "assets/hero/chummer6-hero.png",
                "composition": "over_shoulder_receipt",
                "style_epoch": {"epoch": 1, "run_id": "style-001"},
            }
        ]
    }

    rows = media.scene_rows_for_style_epoch(
        ledger,
        style_epoch={"epoch": 2, "run_id": "style-002"},
        allow_fallback=False,
    )

    assert rows == []


def test_build_safe_onemin_prompt_can_carry_smartlink_and_lore_background_cues() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Rainy transit threshold scene.",
        spec={
            "media_row": {
                "visual_prompt": "Rainy transit threshold scene with one reconnecting operator.",
                "scene_contract": {
                    "subject": "one reconnecting operator",
                    "environment": "a rainy transit checkpoint",
                    "action": "checking whether the ambush lane is still live",
                    "metaphor": "trust rebuilt under pressure",
                    "composition": "transit_checkpoint",
                    "mood": "tense and focused",
                },
            }
        },
    )

    lowered = prompt.lower()
    assert "smartlink" in lowered or "threat posture" in lowered or "line-of-fire" in lowered
    assert "dragon-warning pictograms" in lowered or "crossed-out draconic pictograms" in lowered


def test_build_safe_onemin_prompt_can_carry_lore_scars_inside_dossier_or_workshop_scenes() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Safehouse publishing desk scene.",
        spec={
            "media_row": {
                "visual_prompt": "A campaign writer marks up a district guide on a rugged slate at a cluttered desk.",
                "scene_contract": {
                    "subject": "a campaign writer marking up a district guide on a rugged slate",
                    "environment": "a safehouse desk covered in physical maps and coffee rings",
                    "action": "turning loose notes into a dossier that still points back to source",
                    "metaphor": "leaked field manual",
                    "composition": "dossier_desk",
                    "mood": "focused and suspicious",
                },
            }
        },
    )

    lowered = prompt.lower()
    assert "anti-dragon sigil" in lowered or "runner superstition sticker" in lowered or "talismonger ward mark" in lowered


def test_sanitize_prompt_for_provider_onemin_keeps_shadowrun_lore_and_gear_terms() -> None:
    media = _load_module()

    prompt = media.sanitize_prompt_for_provider(
        "Shadowrun runner with a weapon checks smartlink threat posture in a rainy alley.",
        provider="onemin",
    )

    lowered = prompt.lower()
    assert "shadowrun" in lowered
    assert "runner" in lowered
    assert "weapon" in lowered
    assert "no weapons" not in lowered


def test_build_render_accounting_summarizes_provider_attempts() -> None:
    media = _load_module()

    report = media.build_render_accounting(
        [
            {
                "target": "assets/hero/chummer6-hero.png",
                "provider": "onemin",
                "status": "onemin:http_200",
                "attempts": ["magixai:not_configured", "onemin:http_200", "normalize_banner_size:applied:960x540"],
            },
            {
                "target": "assets/horizons/jackpoint.png",
                "provider": "media_factory",
                "status": "media_factory:rendered",
                "attempts": ["media_factory:rendered", "normalize_banner_size:applied:960x540"],
            },
        ]
    )

    assert report["asset_count"] == 2
    assert report["providers"]["onemin"]["successes"] == 1
    assert report["providers"]["magixai"]["estimated_billable_attempts"] == 0
    assert report["providers"]["media_factory"]["attempts"] == 1


def test_first_contact_target_variant_count_and_overlay_gate() -> None:
    media = _load_module()

    assert media.first_contact_target("assets/hero/chummer6-hero.png") is True
    assert media.first_contact_variant_count(target="assets/hero/chummer6-hero.png") == 8
    assert media.quality_focus_target("assets/pages/public-surfaces.png") is True
    assert media.quality_focus_target("assets/horizons/alice.png") is True
    assert media.first_contact_variant_count(target="assets/pages/public-surfaces.png") == 4
    assert media.first_contact_variant_count(target="assets/horizons/alice.png") == 4
    assert media.first_contact_variant_count(target="assets/parts/ui.png") == 1


def test_first_contact_target_variant_count_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setenv("CHUMMER6_FIRST_CONTACT_VARIANTS", "8")

    assert media.first_contact_variant_count(target="assets/pages/horizons-index.png") == 8


def test_target_visual_contract_loads_density_profile_and_blocks_flagship_humor() -> None:
    media = _load_module()

    hero_contract = media.target_visual_contract("assets/hero/chummer6-hero.png")
    contract = media.target_visual_contract("assets/horizons/karma-forge.png")

    assert hero_contract["person_count_target"] == "duo_or_team"
    assert any("improvised garage clinic" in marker for marker in hero_contract["required_setting_markers"])
    assert "BOD" in hero_contract["required_overlay_schema"]
    assert hero_contract["required_overlay_mode"] == "medscan_diagnostic"
    assert hero_contract["critical_style_overrides_shared_prompt_scaffold"] is True
    assert contract["density_target"] == "high"
    assert contract["overlay_density"] == "high"
    assert contract["person_count_target"] == "duo_preferred"
    assert "DIFF" in contract["required_overlay_schema"]
    assert contract["required_overlay_mode"] == "forge_review_ar"
    assert "approval or provenance logic" in contract["must_show_semantic_anchors"]
    assert media.humor_allowed_for_target(target="assets/horizons/karma-forge.png", contract={}) is False


def test_visual_contract_prompt_parts_add_cast_density_clauses() -> None:
    media = _load_module()

    hero_parts = media.visual_contract_prompt_parts(target="assets/hero/chummer6-hero.png")
    forge_parts = media.visual_contract_prompt_parts(target="assets/horizons/karma-forge.png")

    assert any("two to four people" in part.lower() for part in hero_parts)
    assert any("metahuman clinician" in part.lower() for part in hero_parts)
    assert any("flagship poster" in part.lower() or "cover-grade promo poster" in part.lower() for part in hero_parts)
    assert any("override the softer shared guide-still scaffold" in part.lower() for part in hero_parts)
    assert any("do not fall back to the softer secondary guide-still epoch" in part.lower() for part in hero_parts)
    assert any("overlay posture to medscan diagnostic" in part.lower() for part in hero_parts)
    assert any("clean scene plate" in part.lower() and "composited after the art render" in part.lower() for part in hero_parts)
    assert any("overlay render strategy: verified post composite only" in part.lower() for part in hero_parts)
    assert any("pipeline layers: base scene, verified overlay" in part.lower() for part in hero_parts)
    assert any("troll patient must read clearly" in part.lower() for part in hero_parts)
    assert any("shadowrun world markers visible" in part.lower() for part in hero_parts)
    assert any("room, district, or surrounding environment doing at least about 58% of the storytelling area" in part.lower() for part in hero_parts)
    assert any("single figure or tight subject cluster read larger than about 26% of the frame" in part.lower() for part in hero_parts)
    assert any("any overlay chip, rail, or callout must clearly anchor" in part.lower() or "all overlays must visibly anchor" in part.lower() for part in hero_parts)
    assert any("slim attribute rails" in part.lower() or "capsule chips" in part.lower() for part in hero_parts)
    assert any("visible reviewer" in part.lower() or "second pair of hands" in part.lower() for part in forge_parts)
    assert any("rules lab" in part.lower() or "approval rail" in part.lower() for part in forge_parts)
    assert any("cover-grade promo poster" in part.lower() or "flagship poster" in part.lower() for part in forge_parts)
    assert any("overlay posture to forge review ar" in part.lower() for part in forge_parts)
    assert any("apparatus, rails, machinery, or proving hardware occupy at least about 50% of the readable frame" in part.lower() for part in forge_parts)
    assert any("single figure or tight subject cluster read larger than about 24% of the frame" in part.lower() for part in forge_parts)
    assert any("approval state" in part.lower() and "rollback" in part.lower() for part in forge_parts)
    assert any("attach overlays to rails" in part.lower() or "avoid floating torso or face coverage" in part.lower() for part in forge_parts)


def test_infer_cast_signature_recognizes_duo_operator_relationships() -> None:
    media = _load_module()

    assert media.infer_cast_signature({"subject": "a streetdoc and a runner locked in an upgrade trust check"}) == "duo"
    assert media.infer_cast_signature({"subject": "a crew waiting behind the rail"}) == "group"


def test_row_has_stale_override_drift_rejects_quiet_solo_hero_prompt() -> None:
    media = _load_module()

    stale = media.row_has_stale_override_drift(
        target="assets/hero/chummer6-hero.png",
        row={
            "visual_prompt": "One man in profile beside a vague board in a quiet gear bay.",
            "scene_contract": {
                "subject": "one standing runner alone at a prep wall",
                "composition": "clinic_intake",
            },
        },
    )

    assert stale is True


def test_visual_audit_score_flags_dead_negative_space(tmp_path: Path) -> None:
    media = _load_module()
    pytest.importorskip("PIL")
    from PIL import Image

    image_path = tmp_path / "empty.png"
    Image.new("RGB", (960, 540), (5, 5, 5)).save(image_path)

    score, notes = media.visual_audit_score(
        image_path=image_path,
        target="assets/pages/horizons-index.png",
    )

    assert score < 0
    assert "visual_audit:dead_negative_space" in notes


def test_visual_audit_score_uses_ffmpeg_fallback_when_pil_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    image_path = tmp_path / "empty.png"
    image_path.write_bytes(b"png")

    class _Completed:
        stdout = bytes([0] * (48 * 36))

    monkeypatch.setattr(media, "Image", None)
    monkeypatch.setattr(media, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", lambda *args, **kwargs: _Completed())

    score, notes = media.visual_audit_score(
        image_path=image_path,
        target="assets/pages/horizons-index.png",
    )

    assert score < 0
    assert "visual_audit:dead_negative_space" in notes


def test_visual_audit_enabled_uses_ffmpeg_fallback_when_pil_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setattr(media, "Image", None)
    monkeypatch.setattr(media, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")

    assert media.visual_audit_enabled(target="assets/hero/chummer6-hero.png") is True
    assert media.visual_audit_enabled(target="assets/pages/public-surfaces.png") is True
    assert media.visual_audit_enabled(target="assets/parts/ui.png") is False


def _synthetic_grid(*, active_tiles: set[tuple[int, int]], bright_tiles: set[tuple[int, int]] | None = None) -> tuple[int, int, list[int]]:
    width = 48
    height = 36
    tile_w = width // 4
    tile_h = height // 3
    bright_tiles = bright_tiles or set()
    raw = [18] * (width * height)
    for tile_y in range(3):
        for tile_x in range(4):
            if (tile_x, tile_y) not in active_tiles:
                continue
            for y in range(tile_y * tile_h, (tile_y + 1) * tile_h):
                for x in range(tile_x * tile_w, (tile_x + 1) * tile_w):
                    idx = y * width + x
                    if (x + y) % 2 == 0:
                        raw[idx] = 245 if (tile_x, tile_y) in bright_tiles else 210
                    else:
                        raw[idx] = 20
    return width, height, raw


def test_visual_audit_score_flags_overlay_anchor_spread_weak_for_hero(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "_visual_audit_grayscale_grid",
        lambda **_: _synthetic_grid(
            active_tiles={(1, 0), (2, 0), (1, 1), (2, 1), (1, 2), (2, 2)},
            bright_tiles={(1, 0), (2, 0), (1, 1), (2, 1), (1, 2), (2, 2)},
        ),
    )

    score, notes = media.visual_audit_score(
        image_path=Path("/tmp/ignored.png"),
        target="assets/hero/chummer6-hero.png",
    )

    assert score > 0
    assert "visual_audit:overlay_anchor_spread_weak" in notes


def test_visual_audit_score_flags_workzone_story_weak_for_public_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "_visual_audit_grayscale_grid",
        lambda **_: _synthetic_grid(
            active_tiles={(1, 0), (2, 0), (1, 1), (2, 1)},
            bright_tiles={(1, 0), (2, 0), (1, 1), (2, 1)},
        ),
    )

    score, notes = media.visual_audit_score(
        image_path=Path("/tmp/ignored.png"),
        target="assets/pages/public-surfaces.png",
    )

    assert score < 200
    assert "visual_audit:workzone_story_weak" in notes


def test_visual_audit_score_accepts_gritty_flash_for_karma_forge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    image_path = tmp_path / "karma.png"
    image_path.write_bytes(b"png")
    width, height = 48, 36
    tile_w, tile_h = 12, 12
    raw: list[int] = []
    tile_specs = {
        (2, 0): (0, 170),
        (3, 0): (10, 210),
    }
    for y in range(height):
        tile_y = min(2, y // tile_h)
        for x in range(width):
            tile_x = min(3, x // tile_w)
            low, high = tile_specs.get((tile_x, tile_y), (20, 80))
            raw.append(high if (x + y) % 2 else low)

    monkeypatch.setattr(media, "_visual_audit_grayscale_grid", lambda **kwargs: (width, height, raw))

    score, notes = media.visual_audit_score(
        image_path=image_path,
        target="assets/horizons/karma-forge.png",
    )

    assert score > 0
    assert "visual_audit:insufficient_flash" not in notes


def test_visual_audit_score_accepts_gritty_flash_for_hero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    image_path = tmp_path / "hero.png"
    image_path.write_bytes(b"png")
    width, height = 48, 36
    tile_w, tile_h = 12, 12
    raw: list[int] = []
    tile_specs = {
        (2, 0): (5, 135),
        (0, 1): (15, 140),
    }
    for y in range(height):
        tile_y = min(2, y // tile_h)
        for x in range(width):
            tile_x = min(3, x // tile_w)
            low, high = tile_specs.get((tile_x, tile_y), (10, 110))
            raw.append(high if (x + y) % 2 else low)

    monkeypatch.setattr(media, "_visual_audit_grayscale_grid", lambda **kwargs: (width, height, raw))

    score, notes = media.visual_audit_score(
        image_path=image_path,
        target="assets/hero/chummer6-hero.png",
    )

    assert score > 0
    assert "visual_audit:insufficient_flash" not in notes
    assert "visual_audit:soft_finish" not in notes


def test_visual_audit_score_flags_soft_finish_for_hero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    image_path = tmp_path / "hero-soft.png"
    image_path.write_bytes(b"png")
    width, height = 48, 36
    raw: list[int] = []
    for y in range(height):
        for x in range(width):
            raw.append(78 + ((x + y) % 3))

    monkeypatch.setattr(media, "_visual_audit_grayscale_grid", lambda **kwargs: (width, height, raw))

    score, notes = media.visual_audit_score(
        image_path=image_path,
        target="assets/hero/chummer6-hero.png",
    )

    assert score < 0
    assert "visual_audit:soft_finish" in notes


def test_apply_first_contact_overlay_postpass_uses_ffmpeg_when_pil_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    image_path = tmp_path / "hero.png"
    image_path.write_bytes(b"png")
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        Path(command[-1]).write_bytes(b"png-overlay")
        return type("Completed", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(media, "Image", None)
    monkeypatch.setattr(media, "ImageDraw", None)
    monkeypatch.setattr(media, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(media, "_ffmpeg_overlay_fontfile", lambda: "/tmp/font.ttf")
    monkeypatch.setattr(media.subprocess, "run", fake_run)

    result = media.apply_first_contact_overlay_postpass(
        image_path=image_path,
        spec={"target": "assets/hero/chummer6-hero.png"},
        width=960,
        height=540,
    )

    assert result == "first_contact_overlay:applied_ffmpeg"
    assert "drawtext=" in seen["command"][7]
    assert "UPGRADING" in seen["command"][7]
    assert "TRUST CHECK" not in seen["command"][7]
    assert "NEURAL LINK RESYNC" in seen["command"][7]
    assert "boxborderw=4" in seen["command"][7]


def test_karma_forge_overlay_layout_prefers_rails_and_arcs() -> None:
    media = _load_module()

    layout = media._first_contact_overlay_layout(
        target="assets/horizons/karma-forge.png",
        width=960,
        height=540,
    )

    assert len(layout["fills"]) >= 5
    assert len(layout["chips"]) >= 7
    assert len(layout["lines"]) >= 6
    assert len(layout["arcs"]) >= 3
    assert any(chip["text"] == "COMPATIBILITY ARC" for chip in layout["chips"])
    provenance = next(chip for chip in layout["chips"] if chip["text"] == "PROVENANCE")
    rollback = next(chip for chip in layout["chips"] if chip["text"] == "ROLLBACK")
    compatibility = next(chip for chip in layout["chips"] if chip["text"] == "COMPATIBILITY ARC")
    assert int(provenance["x"]) > int(0.72 * 960)
    assert int(rollback["x"]) > int(0.78 * 960)
    assert int(compatibility["x"]) > int(0.7 * 960)


def test_hero_overlay_layout_uses_edge_biased_rails_over_large_boxes() -> None:
    media = _load_module()

    layout = media._first_contact_overlay_layout(
        target="assets/hero/chummer6-hero.png",
        width=960,
        height=540,
    )

    total_box_area = sum(int(box["w"]) * int(box["h"]) for box in layout["boxes"])
    calibration = next(chip for chip in layout["chips"] if chip["text"] == "CYBERLIMB CALIBRATION")
    wound = next(chip for chip in layout["chips"] if chip["text"] == "WOUND STABILIZED")

    assert total_box_area < int(0.07 * 960 * 540)
    assert any(chip["text"] == "AGI 4 ↑ UPGRADING" for chip in layout["chips"])
    assert any(chip["text"] == "ESS 2.8 ↑ UPGRADING" for chip in layout["chips"])
    assert int(calibration["x"]) > int(0.78 * 960)
    assert int(calibration["y"]) > int(0.64 * 540)
    assert int(wound["x"]) < int(0.12 * 960)
    assert int(wound["y"]) > int(0.68 * 540)


def test_apply_flagship_finish_postpass_uses_pillow_when_available(tmp_path: Path) -> None:
    media = _load_module()
    if media.Image is None:
        pytest.skip("Pillow not available")
    image_path = tmp_path / "hero.png"
    base = media.Image.new("RGB", (240, 160), (22, 26, 33))
    draw = media.ImageDraw.Draw(base)
    draw.rectangle((18, 22, 118, 142), fill=(72, 88, 118))
    draw.rectangle((112, 28, 208, 148), fill=(128, 84, 68))
    base.save(image_path, format="PNG")
    original_bytes = image_path.read_bytes()

    result = media.apply_flagship_finish_postpass(
        image_path=image_path,
        spec={"target": "assets/hero/chummer6-hero.png"},
    )

    assert result == "flagship_finish_postpass:applied_pillow"
    assert image_path.read_bytes() != original_bytes


def test_apply_flagship_finish_postpass_supports_horizons_index(tmp_path: Path) -> None:
    media = _load_module()
    if media.Image is None:
        pytest.skip("Pillow not available")
    image_path = tmp_path / "horizons.png"
    base = media.Image.new("RGB", (240, 160), (24, 28, 34))
    draw = media.ImageDraw.Draw(base)
    draw.rectangle((12, 20, 224, 144), fill=(42, 76, 112))
    draw.ellipse((124, 18, 220, 112), fill=(148, 84, 72))
    base.save(image_path, format="PNG")

    result = media.apply_flagship_finish_postpass(
        image_path=image_path,
        spec={"target": "assets/pages/horizons-index.png"},
    )

    assert result == "flagship_finish_postpass:applied_pillow"


def test_apply_public_asset_finish_postpass_uses_pillow_for_non_flagship_asset(tmp_path: Path) -> None:
    media = _load_module()
    if media.Image is None:
        pytest.skip("Pillow not available")
    image_path = tmp_path / "status.png"
    base = media.Image.new("RGB", (240, 160), (28, 30, 36))
    draw = media.ImageDraw.Draw(base)
    draw.rectangle((18, 18, 118, 144), fill=(58, 72, 84))
    draw.rectangle((106, 24, 220, 132), fill=(82, 92, 110))
    base.save(image_path, format="PNG")
    original_bytes = image_path.read_bytes()

    result = media.apply_public_asset_finish_postpass(
        image_path=image_path,
        spec={"target": "assets/pages/current-status.png"},
    )

    assert result == "public_asset_finish_postpass:applied_pillow"
    assert image_path.read_bytes() != original_bytes


def test_apply_public_asset_finish_postpass_skips_first_contact_assets(tmp_path: Path) -> None:
    media = _load_module()
    image_path = tmp_path / "hero.png"
    image_path.write_bytes(b"png")

    result = media.apply_public_asset_finish_postpass(
        image_path=image_path,
        spec={"target": "assets/hero/chummer6-hero.png"},
    )

    assert result == "public_asset_finish_postpass:skipped"


def test_apply_flagship_finish_postpass_uses_ffmpeg_when_pillow_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    image_path = tmp_path / "hero.png"
    image_path.write_bytes(b"png")
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        Path(command[-1]).write_bytes(b"png-sharp")
        return type("Completed", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(media, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    monkeypatch.setattr(media, "Image", None)
    monkeypatch.setattr(media, "ImageEnhance", None)
    monkeypatch.setattr(media, "ImageFilter", None)

    result = media.apply_flagship_finish_postpass(
        image_path=image_path,
        spec={"target": "assets/hero/chummer6-hero.png"},
    )

    assert result == "flagship_finish_postpass:applied_ffmpeg"
    assert "unsharp=9:9:1.45:5:5:0.0" in seen["command"][7]
    assert "eq=contrast=1.12:saturation=1.12:brightness=0.025" in seen["command"][7]


def test_asset_specs_use_vivid_auto_first_flagship_onemin_lane() -> None:
    media = _load_module()
    specs = media.asset_specs()
    hero = next(spec for spec in specs if spec["target"] == "assets/hero/chummer6-hero.png")
    horizons = next(spec for spec in specs if spec["target"] == "assets/pages/horizons-index.png")
    forge = next(spec for spec in specs if spec["target"] == "assets/horizons/karma-forge.png")

    assert hero["onemin_sizes"] == ["auto", "1536x1024"]
    assert hero["onemin_image_style"] == "vivid"
    assert hero["onemin_models"] == ["gpt-image-1"]
    assert hero["providers"][0] == "onemin"
    assert horizons["onemin_sizes"] == ["auto", "1536x1024"]
    assert horizons["onemin_image_style"] == "vivid"
    assert horizons["onemin_models"] == ["gpt-image-1"]
    assert horizons["providers"][0] == "media_factory"
    assert forge["onemin_sizes"] == ["auto", "1536x1024"]
    assert forge["onemin_image_style"] == "vivid"
    assert forge["onemin_models"] == ["gpt-image-1"]
    assert forge["providers"][0] == "media_factory"


def test_render_prompt_from_row_uses_clean_scene_plate_for_flagship_assets() -> None:
    media = _load_module()
    specs = media.asset_specs()
    hero_spec = next(spec for spec in specs if spec["target"] == "assets/hero/chummer6-hero.png")
    karma_spec = next(spec for spec in specs if spec["target"] == "assets/horizons/karma-forge.png")

    hero_prompt = str(hero_spec["prompt"])
    karma_prompt = str(karma_spec["prompt"])

    assert "clean base-scene plate" in hero_prompt
    assert "deterministic post-composite overlay layer" in hero_prompt
    assert "Reserve the scene-specific overlay semantics for the verified composite layer only" in hero_prompt
    assert "Do not paint readable stat names, subsystem labels, approval words, or status text into the base artwork." in hero_prompt
    assert "troll patient must read clearly" in hero_prompt
    assert "Trust Check" not in hero_prompt
    assert "clean base-scene plate" in karma_prompt
    assert "Keep the shared guide continuity in palette, texture, and world feel without softening the flagship poster finish." in karma_prompt


def test_critical_visual_gate_failures_reject_sparse_first_contact_candidates() -> None:
    media = _load_module()

    failures = media.critical_visual_gate_failures(
        target="assets/hero/chummer6-hero.png",
        base_score=42.0,
        base_notes=["visual_audit:low_semantic_density", "visual_audit:narrow_subject_cluster"],
        final_score=61.0,
        final_notes=["visual_audit:insufficient_flash"],
    )

    assert "critical_visual_gate:base_score<85" in failures
    assert "critical_visual_gate:low_semantic_density" in failures
    assert "critical_visual_gate:narrow_subject_cluster" in failures
    assert "critical_visual_gate:insufficient_flash" in failures


def test_provider_rate_limit_cooldown_parses_retry_after() -> None:
    media = _load_module()

    delay = media._provider_rate_limit_cooldown_seconds(
        provider="onemin",
        detail='onemin:http_429:{"message":"Too many requests. Please try again after 26 seconds","retryAfter":26}',
    )

    assert delay == 26


def test_render_with_ooda_skips_provider_on_rate_limit_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    media._PROVIDER_RATE_LIMIT_COOLDOWNS.clear()
    monkeypatch.setattr(media, "PROVIDER_SCHEDULER_OUT", tmp_path / "scheduler.json")
    output_path = tmp_path / "render.png"

    monkeypatch.setattr(media, "build_safe_onemin_prompt", lambda **kwargs: str(kwargs["prompt"]))
    monkeypatch.setattr(media, "build_safe_media_factory_prompt", lambda **kwargs: str(kwargs["prompt"]))
    monkeypatch.setattr(
        media,
        "run_onemin_api_provider",
        lambda **_kwargs: (False, 'onemin:http_429:{"retryAfter":26}'),
    )

    def _run_command_provider(name: str, command: list[str], **kwargs: object) -> tuple[bool, str]:
        Path(str(kwargs["output_path"])).write_bytes(b"png")
        return True, f"{name}:rendered"

    monkeypatch.setattr(media, "run_command_provider", _run_command_provider)

    first = media.render_with_ooda(
        prompt="render the room",
        output_path=output_path,
        width=960,
        height=540,
        spec={"providers": ["onemin", "media_factory"]},
    )
    second = media.render_with_ooda(
        prompt="render the room",
        output_path=output_path,
        width=960,
        height=540,
        spec={"providers": ["onemin", "media_factory"]},
    )

    assert any("cooldown_applied:26s" in item for item in first["attempts"])
    assert any(item.startswith("onemin:cooldown:") for item in second["attempts"])
    assert second["provider"] == "media_factory"


def test_render_with_ooda_skips_provider_when_scheduler_slot_is_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    monkeypatch.setattr(media, "PROVIDER_SCHEDULER_OUT", tmp_path / "scheduler.json")
    media.write_json_file(
        media.PROVIDER_SCHEDULER_OUT,
        {
            "providers": {
                "onemin": {
                    "active_until_epoch": media._scheduler_now_epoch() + 120.0,
                    "active_target": "assets/other.png",
                    "active_owner_pid": 999999,
                }
            }
        },
    )
    output_path = tmp_path / "render.png"

    monkeypatch.setattr(media, "build_safe_media_factory_prompt", lambda **kwargs: str(kwargs["prompt"]))
    monkeypatch.setattr(media, "_pid_is_alive", lambda pid: True)

    def _run_command_provider(name: str, command: list[str], **kwargs: object) -> tuple[bool, str]:
        Path(str(kwargs["output_path"])).write_bytes(b"png")
        return True, f"{name}:rendered"

    monkeypatch.setattr(media, "run_command_provider", _run_command_provider)

    result = media.render_with_ooda(
        prompt="render the room",
        output_path=output_path,
        width=960,
        height=540,
        spec={"providers": ["onemin", "media_factory"], "target": "assets/pages/current-status.png"},
    )

    assert any(item.startswith("onemin:cooldown:") or item.startswith("onemin:scheduled_wait:") for item in result["attempts"])
    assert result["provider"] == "media_factory"


def test_render_with_ooda_skips_provider_when_family_health_is_stalled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    monkeypatch.setattr(media, "PROVIDER_HEALTH_OUT", tmp_path / "provider-health.json")
    media.write_json_file(
        media.PROVIDER_HEALTH_OUT,
        {
            "providers": {
                "onemin": {
                    "families": {
                        "weak_page": {
                            "recent_attempts": [
                                {"outcome": "timeout"},
                                {"outcome": "no_output_watchdog"},
                            ]
                        }
                    }
                }
            }
        },
    )
    output_path = tmp_path / "render.png"
    monkeypatch.setattr(media, "build_safe_media_factory_prompt", lambda **kwargs: str(kwargs["prompt"]))
    monkeypatch.setattr(media, "run_onemin_api_provider", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("should_not_run")))

    def _run_command_provider(name: str, command: list[str], **kwargs: object) -> tuple[bool, str]:
        Path(str(kwargs["output_path"])).write_bytes(b"png")
        return True, f"{name}:rendered"

    monkeypatch.setattr(media, "run_command_provider", _run_command_provider)

    with pytest.raises(RuntimeError) as exc:
        media.render_with_ooda(
            prompt="render the room",
            output_path=output_path,
            width=960,
            height=540,
            spec={"providers": ["onemin"], "target": "assets/pages/parts-index.png"},
        )

    assert "onemin:health_skip:stalled" in str(exc.value)


def test_champion_entry_for_target_seeds_from_repo_asset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    repo_root = tmp_path / "Chummer6"
    target = "assets/pages/current-status.png"
    target_path = repo_root / target
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(b"png")

    monkeypatch.setattr(media, "CHUMMER6_REPO_ROOT", repo_root)
    monkeypatch.setattr(media, "visual_audit_enabled", lambda **kwargs: True)
    monkeypatch.setattr(
        media,
        "visual_audit_score",
        lambda **kwargs: (287.5, ["visual_audit:world_marker_spread_weak"]),
    )

    ledger = {"assets": {}}
    entry = media.champion_entry_for_target(target=target, ledger=ledger)

    assert entry["score"] == 287.5
    assert entry["source"] == "repo_seed"
    assert ledger["assets"][target]["path"] == str(target_path)


def test_provider_scheduler_entry_clears_stale_legacy_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    scheduler_path = tmp_path / "scheduler.json"
    monkeypatch.setattr(media, "PROVIDER_SCHEDULER_OUT", scheduler_path)
    media.write_json_file(
        scheduler_path,
        {
            "providers": {
                "media_factory": {
                    "active_until_epoch": media._scheduler_now_epoch() + 120.0,
                    "active_target": "assets/horizons/alice.png",
                    "updated_at": media._scheduler_now_epoch(),
                }
            }
        },
    )
    monkeypatch.setattr(media, "_render_target_process_alive", lambda target: False)

    entry = media._provider_scheduler_entry(provider="media_factory")
    persisted = json.loads(scheduler_path.read_text(encoding="utf-8"))

    assert entry["active_until_epoch"] == 0.0
    assert entry["active_target"] == ""
    assert persisted["providers"]["media_factory"]["active_until_epoch"] == 0.0


def test_render_specs_keeps_existing_champion_when_challenger_does_not_beat_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media = _load_module()
    repo_root = tmp_path / "Chummer6"
    target = "assets/pages/current-status.png"
    canonical_path = repo_root / target
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_bytes(b"champion")

    monkeypatch.setattr(media, "CHUMMER6_REPO_ROOT", repo_root)
    monkeypatch.setattr(media, "SCENE_LEDGER_OUT", tmp_path / "scene-ledger.json")
    monkeypatch.setattr(media, "CHALLENGER_LEDGER_OUT", tmp_path / "challenger-ledger.json")
    monkeypatch.setattr(media, "MANIFEST_OUT", tmp_path / "manifest.json")
    monkeypatch.setattr(media, "STATE_OUT", tmp_path / "state.json")
    monkeypatch.setattr(media, "scene_rows_for_style_epoch", lambda *args, **kwargs: [])
    monkeypatch.setattr(media, "repetition_block_reason", lambda **kwargs: "")
    monkeypatch.setattr(media, "refine_prompt_with_ooda", lambda **kwargs: str(kwargs["prompt"]))
    monkeypatch.setattr(media, "ensure_troll_clause", lambda **kwargs: str(kwargs["prompt"]))
    monkeypatch.setattr(media, "first_contact_variant_count", lambda **kwargs: 2)
    monkeypatch.setattr(media, "normalize_banner_size", lambda **kwargs: "normalize_banner_size:ok")
    monkeypatch.setattr(media, "first_contact_target", lambda target: False)
    monkeypatch.setattr(media, "troll_postpass_enabled", lambda: False)
    monkeypatch.setattr(media, "apply_public_asset_finish_postpass", lambda **kwargs: "public_asset_finish_postpass:pillow")
    monkeypatch.setattr(media, "build_render_accounting", lambda assets: {"assets": len(assets)})
    monkeypatch.setattr(media, "easter_egg_payload", lambda contract: {})
    monkeypatch.setattr(media, "infer_cast_signature", lambda contract: "duo")

    def _variant_prompt(**kwargs: object) -> tuple[str, list[str]]:
        return str(kwargs["prompt"]), []

    monkeypatch.setattr(media, "ooda_variant_prompt", _variant_prompt)
    monkeypatch.setattr(media, "ooda_variant_spec", lambda **kwargs: (dict(kwargs["spec"]), []))

    def _render_with_ooda(**kwargs: object) -> dict[str, object]:
        output_path = Path(str(kwargs["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"candidate")
        return {"provider": "media_factory", "status": "media_factory:rendered", "attempts": ["media_factory:rendered"]}

    monkeypatch.setattr(media, "render_with_ooda", _render_with_ooda)
    monkeypatch.setattr(media, "visual_audit_enabled", lambda target: True)

    def _visual_audit_score(*, image_path: Path, target: str) -> tuple[float, list[str]]:
        if image_path == canonical_path:
            return 310.0, []
        return 300.0, ["visual_audit:cast_readability_weak"]

    monkeypatch.setattr(media, "visual_audit_score", _visual_audit_score)
    monkeypatch.setattr(media, "critical_visual_gate_failures", lambda **kwargs: [])

    manifest = media.render_specs(
        specs=[
            {
                "target": target,
                "prompt": "Render the room",
                "width": 960,
                "height": 540,
                "media_row": {"scene_contract": {"composition": "workspace", "subject": "status wall"}},
                "providers": ["media_factory"],
            }
        ],
        output_dir=repo_root,
    )

    champion_after = canonical_path.read_bytes()
    ledger = json.loads((tmp_path / "challenger-ledger.json").read_text(encoding="utf-8"))
    entry = ledger["assets"][target]

    assert champion_after == b"champion"
    assert "challenger:kept_existing_champion" in manifest["assets"][0]["attempts"]
    assert entry["score"] == 310.0
    assert entry["last_challenger"]["beat_champion"] is False


def test_critical_visual_gate_failures_reject_soft_finish_on_flagship_assets() -> None:
    media = _load_module()

    failures = media.critical_visual_gate_failures(
        target="assets/hero/chummer6-hero.png",
        base_score=96.0,
        base_notes=["visual_audit:soft_finish"],
        final_score=92.0,
        final_notes=["visual_audit:soft_finish"],
    )

    assert "critical_visual_gate:soft_finish" in failures


def test_scene_policy_for_target_uses_approval_rail_for_karma_forge() -> None:
    media = _load_module()
    specs = media.asset_specs()
    forge = next(spec for spec in specs if spec["target"] == "assets/horizons/karma-forge.png")
    contract = forge["media_row"]["scene_contract"]

    assert contract["composition"] == "approval_rail"


def test_scene_policy_for_target_rebriefs_hero_as_active_triage() -> None:
    media = _load_module()
    specs = media.asset_specs()
    hero = next(spec for spec in specs if spec["target"] == "assets/hero/chummer6-hero.png")
    contract = hero["media_row"]["scene_contract"]

    assert "garage clinic" in str(contract["environment"]).lower()
    assert "stabilizing" in str(contract["subject"]).lower()
    assert "side bench" in str(contract["environment"]).lower() or "open bay door" in str(contract["environment"]).lower()
    assert "triage" in str(hero["prompt"]).lower() or "garage clinic" in str(hero["prompt"]).lower()


def test_scene_policy_for_target_makes_karma_forge_an_industrial_materials_lab() -> None:
    media = _load_module()
    specs = media.asset_specs()
    forge = next(spec for spec in specs if spec["target"] == "assets/horizons/karma-forge.png")
    contract = forge["media_row"]["scene_contract"]
    prompt = str(forge["prompt"]).lower()

    assert "assay" in str(contract["environment"]).lower() or "sample" in str(contract["environment"]).lower()
    assert "materials" in prompt or "awakened" in prompt


def test_ooda_variant_prompt_adds_room_finish_and_energy_corrections() -> None:
    media = _load_module()

    variant_prompt, tags = media.ooda_variant_prompt(
        prompt="Base hero prompt.",
        target="assets/hero/chummer6-hero.png",
        variant=1,
        previous_notes=[
            "visual_audit:environment_share_too_low",
            "visual_audit:soft_finish",
            "visual_audit:insufficient_flash",
        ],
        previous_gate_failures=[],
    )

    lowered = variant_prompt.lower()
    assert "camera farther back" in lowered
    assert "harder edges" in lowered
    assert "stronger contrast" in lowered
    assert "clinic geography" in lowered
    assert tags == ["wider_room_first", "harder_finish", "higher_energy"]


def test_ooda_variant_spec_switches_toward_room_or_finish_provider() -> None:
    media = _load_module()

    adjusted_room, room_tags = media.ooda_variant_spec(
        spec={"providers": ["onemin", "media_factory", "magixai"]},
        target="assets/pages/parts-index.png",
        variant=1,
        previous_provider="onemin",
        previous_notes=["visual_audit:environment_share_too_low"],
        previous_gate_failures=[],
    )
    assert adjusted_room["providers"][0] == "media_factory"
    assert "prefer_media_factory_room" in room_tags

    adjusted_finish, finish_tags = media.ooda_variant_spec(
        spec={"providers": ["media_factory", "onemin", "magixai"]},
        target="assets/horizons/karma-forge.png",
        variant=1,
        previous_provider="media_factory",
        previous_notes=["visual_audit:soft_finish"],
        previous_gate_failures=[],
    )
    assert adjusted_finish["providers"][0] == "onemin"
    assert "prefer_onemin_finish" in finish_tags


def test_refine_prompt_with_ooda_uses_external_refiner_when_available_without_requiring_it(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_PROMPT_REFINEMENT_REQUIRED", raising=False)
    monkeypatch.setattr(media, "env_value", lambda name: "wf-123" if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID" else "")
    monkeypatch.setattr(media, "shlex_command", lambda name: ["python3", "-c", "print('refined prompt from external lane')"])

    refined = media.refine_prompt_with_ooda(prompt="base prompt", target="assets/pages/start-here.png")

    assert refined == "refined prompt from external lane"


def test_refine_prompt_with_ooda_can_disable_external_refinement(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "env_value",
        lambda name: "1"
        if name == "CHUMMER6_DISABLE_PROMPT_REFINEMENT"
        else "wf-123"
        if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID"
        else "",
    )
    monkeypatch.setattr(media, "shlex_command", lambda name: ["python3", "-c", "print('should not run')"])

    refined = media.refine_prompt_with_ooda(prompt="base prompt", target="assets/pages/start-here.png")

    assert refined == "base prompt"


def test_refine_prompt_with_ooda_falls_back_to_local_prompt_on_timeout_when_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_PROMPT_REFINEMENT_REQUIRED", raising=False)
    monkeypatch.setattr(media, "env_value", lambda name: "wf-123" if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID" else "")
    monkeypatch.setattr(media, "shlex_command", lambda name: ["python3", "-c", "print('never reached')"])

    def _timeout(*args, **kwargs):
        raise media.subprocess.TimeoutExpired(cmd="refiner", timeout=media.prompt_refinement_timeout_seconds())

    monkeypatch.setattr(media.subprocess, "run", _timeout)

    refined = media.refine_prompt_with_ooda(prompt="base prompt", target="assets/pages/start-here.png")

    assert refined == "base prompt"


def test_sanitize_media_row_strips_machine_overlay_labels_from_render_prompts() -> None:
    media = _load_module()

    row = media.sanitize_media_row(
        target="assets/horizons/jackpoint.png",
        row={
            "visual_prompt": (
                "Dossier desk scene with receipt threads and hard evidence. "
                "Hovering digital 'VERIFIED' stamps glow in the air with metadata strings."
            ),
            "overlay_hint": "HUD style: Data-dossier classification stamps and rotating provenance hashes in the corners.",
            "visual_motifs": ["dossier desk", "receipt threads", "SIG_MATCH: 99.8%"],
            "overlay_callouts": ["receipt markers", "PROVENANCE VERIFIED", "HW_ID: 0x882_DECK"],
            "scene_contract": {
                "subject": "a fixer sorting a dossier",
                "environment": "a dim archive desk",
                "action": "sorting evidence",
                "metaphor": "dossier evidence wall",
                "props": ["dossiers", "chips"],
                "overlays": ["receipt markers", "AUDIT_PASS: 100%"],
                "composition": "desk_still_life",
                "palette": "cyan",
                "mood": "focused",
                "humor": "",
            },
        },
    )

    assert row["visual_motifs"] == ["dossier desk", "receipt threads"]
    assert row["overlay_callouts"] == ["receipt markers"]
    assert row["scene_contract"]["overlays"] == ["receipt markers"]
    assert "verified" not in row["visual_prompt"].lower()
    assert "metadata" not in row["visual_prompt"].lower()
    assert row["overlay_hint"] == ""
