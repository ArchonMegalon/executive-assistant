from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import _verify_signed_payload, authenticated_principal_override_allowed
from app.api.app import create_app
from app.api.routes import landing_access_support
from app.api.routes import landing_channel
from app.api.routes import landing_browser
from app.services import responses_upstream
from app.services import public_clickrank
from app.services import public_rybbit
from app.services import tool_execution_gemini_vortex_adapter as gemini_vortex_adapter
from app.settings import (
    AuthSettings,
    ChannelSettings,
    CoreSettings,
    FeatureSettings,
    PolicySettings,
    RuntimeSettings,
    Settings,
    StorageSettings,
    validate_startup_settings,
)


def _signed_token(payload: dict[str, object], *, secret: str) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _base_settings(*, mode: str = "prod") -> Settings:
    return Settings(
        core=CoreSettings(
            app_name="ea",
            app_version="0.1.0",
            role="api",
            host="127.0.0.1",
            port=8090,
            log_level="INFO",
            tenant_id="default",
        ),
        runtime=RuntimeSettings(mode=mode),
        storage=StorageSettings(
            backend="postgres" if mode == "prod" else "memory",
            database_url="postgresql://ea:ea@db/ea" if mode == "prod" else "",
            artifacts_dir=".runtime/ea_artifacts",
        ),
        auth=AuthSettings(
            api_token="token",
            default_principal_id="principal-default",
            signing_secret="prod-signing-secret-value",
        ),
        policy=PolicySettings(
            max_rewrite_chars=20000,
            approval_required_chars=5000,
            approval_ttl_minutes=120,
        ),
        channels=ChannelSettings(default_list_limit=50),
        features=FeatureSettings(),
    )


class HardeningTests(unittest.TestCase):
    def test_clickrank_hostname_fallback_ignores_untrusted_forwarded_proxy_headers(self) -> None:
        request = SimpleNamespace(
            headers={
                "host": "internal.local",
                "x-forwarded-for": "198.51.100.10",
                "cf-connecting-ip": "198.51.100.10",
                "cf-ray": "unit-test",
            },
            url=SimpleNamespace(hostname="internal.local"),
        )
        env = {
            "EA_PUBLIC_APP_BASE_URL": "https://myexternalbrain.com",
            "PROPERTYQUARRY_TRUST_X_FORWARDED_FOR": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(public_clickrank.request_hostname(request), "internal.local")

    def test_rybbit_hostname_fallback_ignores_untrusted_forwarded_proxy_headers(self) -> None:
        request = SimpleNamespace(
            headers={
                "host": "internal.local",
                "x-forwarded-for": "198.51.100.10",
                "cf-connecting-ip": "198.51.100.10",
                "cf-ray": "unit-test",
            },
            url=SimpleNamespace(hostname="internal.local"),
        )
        env = {
            "EA_PUBLIC_APP_BASE_URL": "https://myexternalbrain.com",
            "PROPERTYQUARRY_TRUST_X_FORWARDED_FOR": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(public_rybbit.request_hostname(request), "internal.local")

    def test_clickrank_hostname_fallback_accepts_trusted_forwarded_proxy_headers(self) -> None:
        request = SimpleNamespace(
            headers={
                "host": "internal.local",
                "x-forwarded-for": "198.51.100.10",
                "cf-connecting-ip": "198.51.100.10",
                "cf-ray": "unit-test",
            },
            url=SimpleNamespace(hostname="internal.local"),
        )
        env = {
            "EA_PUBLIC_APP_BASE_URL": "https://myexternalbrain.com",
            "PROPERTYQUARRY_TRUST_X_FORWARDED_FOR": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(public_clickrank.request_hostname(request), "myexternalbrain.com")

    def test_rybbit_hostname_does_not_use_clickrank_proxy_signal_fallback(self) -> None:
        request = SimpleNamespace(
            headers={
                "host": "internal.local",
                "x-forwarded-for": "198.51.100.10",
                "cf-connecting-ip": "198.51.100.10",
                "cf-ray": "unit-test",
            },
            url=SimpleNamespace(hostname="internal.local"),
        )
        env = {
            "EA_PUBLIC_APP_BASE_URL": "https://myexternalbrain.com",
            "PROPERTYQUARRY_TRUST_X_FORWARDED_FOR": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(public_rybbit.request_hostname(request), "internal.local")

    def test_browser_workspace_cookie_ignores_raw_forwarded_proto_without_trust(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-proto": "https"},
            url=SimpleNamespace(scheme="http"),
        )
        with patch.dict(os.environ, {"PROPERTYQUARRY_TRUST_X_FORWARDED_HOST": "0"}, clear=False):
            self.assertFalse(landing_browser._workspace_session_cookie_kwargs(request)["secure"])

    def test_browser_workspace_cookie_accepts_forwarded_proto_when_trust_enabled(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-proto": "https"},
            url=SimpleNamespace(scheme="http"),
        )
        with patch.dict(os.environ, {"PROPERTYQUARRY_TRUST_X_FORWARDED_HOST": "1"}, clear=False):
            self.assertTrue(landing_browser._workspace_session_cookie_kwargs(request)["secure"])

    def test_validate_startup_settings_rejects_prod_principal_override_flags(self) -> None:
        settings = _base_settings(mode="prod")
        env = {
            "EA_PUBLIC_APP_BASE_URL": "https://ea.example.com",
            "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"):
                validate_startup_settings(settings)

    def test_verify_signed_payload_requires_issued_at(self) -> None:
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        token = _signed_token(
            {
                "token_kind": "workspace_access_session",
                "expires_at": expires_at,
            },
            secret="secret",
        )
        self.assertIsNone(_verify_signed_payload(secret="secret", token=token))

    def test_verify_signed_payload_rejects_excessive_ttl(self) -> None:
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(days=8)
        token = _signed_token(
            {
                "token_kind": "workspace_access_session",
                "issued_at": issued_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
            secret="secret",
        )
        self.assertIsNone(_verify_signed_payload(secret="secret", token=token))

    def test_verify_signed_payload_accepts_bounded_ttl(self) -> None:
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(hours=2)
        payload = {
            "token_kind": "workspace_access_session",
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "jti": "wsa_123",
        }
        token = _signed_token(payload, secret="secret")
        self.assertEqual(_verify_signed_payload(secret="secret", token=token), payload)

    def test_authenticated_principal_override_uses_container_runtime_mode(self) -> None:
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            app=SimpleNamespace(
                state=SimpleNamespace(
                    container=SimpleNamespace(
                        settings=replace(_base_settings(mode="prod"), runtime=RuntimeSettings(mode="prod"))
                    )
                )
            ),
        )
        env = {
            "EA_RUNTIME_MODE": "dev",
            "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(authenticated_principal_override_allowed(request))

    def test_channel_action_does_not_trust_raw_principal_header(self) -> None:
        request = SimpleNamespace(
            method="POST",
            headers={"X-EA-Principal-ID": "spoofed-user"},
            query_params={},
            client=SimpleNamespace(host="198.51.100.10"),
        )
        seen: dict[str, object] = {}
        product = SimpleNamespace(
            preview_channel_action_token=lambda token: {"object_kind": "draft"},
            redeem_channel_action_token=lambda token, actor, preferred_operator_id: seen.update(
                {"actor": actor, "preferred_operator_id": preferred_operator_id}
            )
            or {"return_to": "/app/channel-loop", "object_kind": "draft"},
        )
        with (
            patch.object(landing_channel, "_enforce_public_channel_rate_limit", lambda **kwargs: None),
            patch.object(landing_channel, "build_product_service", lambda container: product),
            patch.object(landing_channel, "_workspace_session_payload", lambda request, container: None),
            patch.object(landing_channel, "get_request_context", side_effect=HTTPException(status_code=401, detail="auth_required")),
            patch.object(landing_channel, "_render_secure_link_page", lambda *args, **kwargs: ("secure", kwargs)),
        ):
            result = landing_channel.app_channel_action("token-1", request, SimpleNamespace(), None)

        self.assertEqual(seen["actor"], "channel_link")
        self.assertEqual(seen["preferred_operator_id"], "")
        self.assertEqual(result[0], "secure")

    def test_channel_action_accepts_verified_authenticated_context(self) -> None:
        request = SimpleNamespace(
            method="POST",
            headers={"Authorization": "Bearer token", "X-EA-Principal-ID": "verified-user"},
            query_params={},
            client=SimpleNamespace(host="198.51.100.10"),
        )
        seen: dict[str, object] = {}
        product = SimpleNamespace(
            preview_channel_action_token=lambda token: {"object_kind": "draft"},
            redeem_channel_action_token=lambda token, actor, preferred_operator_id: seen.update(
                {"actor": actor, "preferred_operator_id": preferred_operator_id}
            )
            or {"return_to": "/app/channel-loop", "object_kind": "draft"},
        )
        context = landing_channel.RequestContext(principal_id="verified-user", authenticated=True, auth_source="api_token")
        with (
            patch.object(landing_channel, "_enforce_public_channel_rate_limit", lambda **kwargs: None),
            patch.object(landing_channel, "build_product_service", lambda container: product),
            patch.object(landing_channel, "_workspace_session_payload", lambda request, container: None),
            patch.object(landing_channel, "get_request_context", lambda request, container, access_identity: context),
        ):
            response = landing_channel.app_channel_action("token-2", request, SimpleNamespace(), None)

        self.assertEqual(seen["actor"], "verified-user")
        self.assertEqual(seen["preferred_operator_id"], "")
        self.assertEqual(getattr(response, "status_code", None), 303)

    def test_workspace_access_session_does_not_trust_raw_x_ea_headers(self) -> None:
        request = SimpleNamespace(
            headers={"X-EA-Operator-ID": "spoofed-operator", "X-EA-Principal-ID": "spoofed-user"},
            query_params={},
            cookies={},
            client=SimpleNamespace(host="198.51.100.10"),
            url=SimpleNamespace(path="/workspace-access/token-1"),
        )
        seen: dict[str, object] = {}
        product = SimpleNamespace(
            open_workspace_access_session=lambda token, actor: seen.update({"token": token, "actor": actor})
            or {
                "access_token": "session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "default_target": "/app/today",
            }
        )
        with (
            patch.object(landing_access_support, "build_product_service", lambda container: product),
            patch.object(landing_access_support, "request_brand", lambda request: {"app_home": "/app/today"}),
            patch.object(landing_access_support, "get_cloudflare_access_identity", side_effect=HTTPException(status_code=401, detail="cloudflare_access_invalid")),
            patch.object(landing_access_support, "get_request_context", side_effect=HTTPException(status_code=401, detail="auth_required")),
            patch.object(landing_access_support, "_workspace_session_payload", lambda request, container: None),
            patch.object(landing_access_support, "_workspace_session_cookie_kwargs", lambda request, expires_at: {"httponly": True}),
            patch.object(landing_access_support, "_normalize_browser_return_to", lambda value, default: default),
        ):
            response = landing_access_support.workspace_access_session("token-1", request, SimpleNamespace())

        self.assertEqual(seen["actor"], "workspace_access")
        self.assertEqual(getattr(response, "status_code", None), 303)

    def test_workspace_invite_accept_prefers_verified_identity_sources(self) -> None:
        request = SimpleNamespace(
            headers={"X-EA-Operator-ID": "spoofed-operator", "X-EA-Principal-ID": "spoofed-user"},
            query_params={},
            cookies={},
            client=SimpleNamespace(host="198.51.100.10"),
            url=SimpleNamespace(path="/workspace-invites/token-2/accept"),
        )
        seen: dict[str, object] = {}
        product = SimpleNamespace(
            accept_workspace_invitation=lambda token, accepted_by: seen.update({"token": token, "accepted_by": accepted_by})
            or {
                "status": "accepted",
                "email": "invitee@example.com",
                "role": "operator",
            }
        )
        context = landing_access_support.RequestContext(
            principal_id="verified-user",
            authenticated=True,
            auth_source="workspace_access_session",
            access_email="verified@example.com",
            operator_id="verified-operator",
            operator_authorized=True,
        )
        with (
            patch.object(landing_access_support, "build_product_service", lambda container: product),
            patch.object(landing_access_support, "request_brand", lambda request: {"app_home": "/app/today"}),
            patch.object(landing_access_support, "get_request_context", lambda request, container, access_identity: context),
            patch.object(landing_access_support, "_workspace_session_payload", lambda request, container: {"email": "session@example.com", "operator_id": "session-operator", "principal_id": "session-user"}),
            patch.object(landing_access_support, "_render_secure_link_page", lambda *args, **kwargs: ("secure", kwargs)),
        ):
            result = landing_access_support.workspace_invite_accept("token-2", request, SimpleNamespace(), None)

        self.assertEqual(seen["accepted_by"], "verified@example.com")
        self.assertEqual(result[0], "secure")

    def test_memorial_voice_config_requires_write_access(self) -> None:
        env = {
            "EA_ENABLE_PUBLIC_MEMORIALS": "1",
            "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                public_root = root / "public"
                private_root = root / "private"
                slug = "manfred"
                bundle_dir = public_root / slug
                bundle_dir.mkdir(parents=True)
                (bundle_dir / "memorial.json").write_text(
                    json.dumps(
                        {
                            "slug": slug,
                            "person_name": "Manfred Hoza",
                            "audio_clips": [],
                            "write_token": "unit-write-token",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                profile_dir = private_root / slug
                profile_dir.mkdir(parents=True)
                (profile_dir / "tts_voice.json").write_text(
                    json.dumps({"tts_mode": "browser_speech_synthesis"}, ensure_ascii=False),
                    encoding="utf-8",
                )
                with patch.dict(
                    os.environ,
                    {
                        "EA_PUBLIC_MEMORIAL_DIR": str(public_root),
                        "EA_PRIVATE_MEMORIAL_PROFILE_DIR": str(private_root),
                    },
                    clear=False,
                ):
                    client = TestClient(create_app())
                    unauthorized = client.get(f"/memorials/{slug}/voice-config")
                    authorized = client.get(
                        f"/memorials/{slug}/voice-config",
                        headers={"x-memorial-write-token": "unit-write-token"},
                    )

        self.assertEqual(unauthorized.status_code, 403)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["slug"], "manfred")

    def test_gemini_vortex_auth_state_requires_noninteractive_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "settings.json").write_text("{}", encoding="utf-8")
            env = {
                "EA_GEMINI_VORTEX_CONFIG_DIR": str(root),
                "GOOGLE_API_KEY_FALLBACK_1": "",
            }
            with patch.dict(os.environ, env, clear=False):
                state, detail = gemini_vortex_adapter.gemini_vortex_auth_state()

        self.assertEqual(state, "missing")
        self.assertEqual(detail, "auth_credentials_missing")

    def test_fast_provider_candidates_skip_gemini_when_live_health_degraded(self) -> None:
        with patch.object(
            responses_upstream,
            "_gemini_vortex_health_state",
            return_value=("degraded", "auth_credentials_missing"),
        ):
            candidates = responses_upstream._provider_candidates(
                responses_upstream.FAST_PUBLIC_MODEL,
                lane=responses_upstream._LANE_FAST,
            )

        self.assertNotIn("gemini_vortex", {config.provider_key for config, _ in candidates})

    def test_gemini_vortex_health_state_reports_spawn_pressure_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "EA_RESPONSES_PROVIDER_LEDGER_DIR": tmpdir,
                "EA_GEMINI_VORTEX_COMMAND": "sh",
                "EA_GEMINI_VORTEX_API_KEY": "direct-gemini-key",
            },
            clear=False,
        ):
            gemini_vortex_adapter._record_spawn_pressure("spawn /usr/bin/node EAGAIN")
            state, detail = responses_upstream._gemini_vortex_health_state()

        self.assertEqual(state, "degraded")
        self.assertIn("spawn_pressure_cooldown", detail)

    def test_onemin_attempt_summary_tracks_parallel_proxy_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"EA_RESPONSES_PROVIDER_LEDGER_DIR": tmpdir},
            clear=False,
        ):
            responses_upstream._test_reset_onemin_states()
            proxy_id, proxy_service = responses_upstream._onemin_proxy_identity(
                "http://user:pass@ea-fastestvpn-proxy-2:8080"
            )
            inflight_one = responses_upstream._onemin_attempt_enter(proxy_id=proxy_id, account_name="acct-1")
            inflight_two = responses_upstream._onemin_attempt_enter(proxy_id=proxy_id, account_name="acct-2")
            responses_upstream._record_onemin_attempt_event(
                attempt_id="req-1:1",
                request_id="req-1",
                lane="fast",
                model_requested="gpt-5.4",
                model_resolved="gpt-5.4",
                account_name="acct-1",
                key_slot="fallback_1",
                endpoint_mode="chat",
                endpoint_url="https://api.1min.ai/api/features",
                proxy_id=proxy_id,
                proxy_service=proxy_service,
                timeout_seconds=30,
                latency_ms=2400,
                status="success",
                http_status=200,
                principal_id="principal-1",
                inflight_total=inflight_one[0],
                inflight_same_proxy=inflight_one[1],
                inflight_same_account=inflight_one[2],
            )
            responses_upstream._record_onemin_attempt_event(
                attempt_id="req-2:1",
                request_id="req-2",
                lane="fast",
                model_requested="gpt-5.4",
                account_name="acct-2",
                key_slot="fallback_2",
                endpoint_mode="chat",
                endpoint_url="https://api.1min.ai/api/features",
                proxy_id=proxy_id,
                proxy_service=proxy_service,
                timeout_seconds=30,
                latency_ms=4100,
                status="http_error",
                error="http_429:too_many_requests",
                http_status=429,
                principal_id="principal-1",
                inflight_total=inflight_two[0],
                inflight_same_proxy=inflight_two[1],
                inflight_same_account=inflight_two[2],
            )
            responses_upstream._onemin_attempt_exit(proxy_id=proxy_id, account_name="acct-2")
            responses_upstream._onemin_attempt_exit(proxy_id=proxy_id, account_name="acct-1")

            summary = responses_upstream._onemin_attempt_summary(
                now=responses_upstream._now_epoch(),
                window_seconds=3600.0,
                principal_id="principal-1",
            )

        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["success_count"], 1)
        self.assertEqual(summary["http_429_count"], 1)
        self.assertEqual(summary["peak_parallel_total"], 2)
        self.assertEqual(summary["peak_parallel_same_proxy"], 2)
        self.assertEqual(summary["active_inflight_total"], 0)
        self.assertEqual(summary["throttle_pressure"], "high")
        self.assertEqual(summary["busiest_proxy_services"][0]["proxy_service"], "ea-fastestvpn-proxy-2")

    def test_onemin_selector_defaults_all_configured_accounts_active(self) -> None:
        env = {
            "ONEMIN_AI_API_KEY": "key-0",
            "ONEMIN_AI_API_KEY_FALLBACK_1": "key-1",
            "ONEMIN_AI_API_KEY_FALLBACK_2": "key-2",
            "ONEMIN_AI_API_KEY_FALLBACK_3": "key-3",
            "ONEMIN_AI_API_KEY_FALLBACK_4": "key-4",
            "ONEMIN_AI_API_KEY_FALLBACK_5": "key-5",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(responses_upstream._onemin_key_names(), tuple(env.values()))
            self.assertEqual(responses_upstream._onemin_active_keys(), tuple(env.values()))
            self.assertEqual(responses_upstream._onemin_reserve_keys(), ())
            self.assertEqual(
                responses_upstream._ordered_onemin_keys_allow_reserve(False),
                tuple(env.values()),
            )

    def test_onemin_selector_honors_explicit_active_and_reserve_slots(self) -> None:
        env = {
            "ONEMIN_AI_API_KEY": "key-0",
            "ONEMIN_AI_API_KEY_FALLBACK_1": "key-1",
            "ONEMIN_AI_API_KEY_FALLBACK_2": "key-2",
            "ONEMIN_AI_API_KEY_FALLBACK_3": "key-3",
            "EA_RESPONSES_ONEMIN_ACTIVE_SLOTS": "primary,fallback_2",
            "EA_RESPONSES_ONEMIN_RESERVE_SLOTS": "fallback_1,fallback_3",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(responses_upstream._onemin_active_keys(), ("key-0", "key-2"))
            self.assertEqual(responses_upstream._onemin_reserve_keys(), ("key-1", "key-3"))
            self.assertEqual(
                responses_upstream._ordered_onemin_keys_allow_reserve(False),
                ("key-0", "key-2"),
            )
            self.assertEqual(
                responses_upstream._ordered_onemin_keys_allow_reserve(True),
                ("key-0", "key-1", "key-2", "key-3"),
            )

    def test_onemin_selector_discovers_numbered_env_aliases(self) -> None:
        env = {
            "EA_RESPONSES_ONEMIN_API_KEY": "key-0",
            "EA_RESPONSES_ONEMIN_API_KEY_2": "key-1",
            "EA_RESPONSES_ONEMIN_API_KEY_3": "key-2",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(responses_upstream._onemin_key_names(), ("key-0", "key-1", "key-2"))
            self.assertEqual(responses_upstream._onemin_active_keys(), ("key-0", "key-1", "key-2"))

    def test_onemin_json_attempt_wrapper_records_live_success_and_drains_inflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "EA_RESPONSES_PROVIDER_LEDGER_DIR": tmpdir,
                "EA_ONEMIN_DIRECT_API_PROXY_POOL": "http://ea-fastestvpn-proxy-1:8080",
            },
            clear=False,
        ):
            responses_upstream._test_reset_onemin_states()
            with patch.object(responses_upstream, "_post_json", return_value=(200, {"text": "ok"})):
                status, payload = responses_upstream._post_onemin_json_with_attempt(
                    url="https://api.1min.ai/api/features",
                    api_key="unit-key",
                    payload={"type": "UNIFY_CHAT_WITH_AI", "model": "gpt-5.4"},
                    timeout_seconds=30,
                    attempt_id="attempt-success",
                    request_id="request-success",
                    lane="fast",
                    model="gpt-5.4",
                    account_name="acct-success",
                    key_slot="fallback_4",
                    principal_id="principal-live",
                    principal_scope_id="scope-live",
                    endpoint_mode="chat",
                )
            summary = responses_upstream._onemin_attempt_summary(
                now=responses_upstream._now_epoch(),
                window_seconds=3600.0,
                principal_id="principal-live",
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"text": "ok"})
        self.assertEqual(summary["attempt_count"], 1)
        self.assertEqual(summary["success_count"], 1)
        self.assertEqual(summary["active_inflight_total"], 0)
        self.assertEqual(summary["busiest_proxy_services"][0]["proxy_service"], "ea-fastestvpn-proxy-1")

    def test_onemin_json_attempt_wrapper_records_transport_error_and_drains_inflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"EA_RESPONSES_PROVIDER_LEDGER_DIR": tmpdir},
            clear=False,
        ):
            responses_upstream._test_reset_onemin_states()
            with patch.object(
                responses_upstream,
                "_post_json",
                side_effect=responses_upstream.ResponsesUpstreamError("request_timeout:30s"),
            ):
                with self.assertRaises(responses_upstream.ResponsesUpstreamError):
                    responses_upstream._post_onemin_json_with_attempt(
                        url="https://api.1min.ai/api/features",
                        api_key="unit-key",
                        payload={"type": "UNIFY_CHAT_WITH_AI", "model": "gpt-5.4"},
                        timeout_seconds=30,
                        attempt_id="attempt-error",
                        request_id="request-error",
                        lane="fast",
                        model="gpt-5.4",
                        account_name="acct-error",
                        key_slot="fallback_5",
                        principal_id="principal-live",
                        principal_scope_id="scope-live",
                        endpoint_mode="chat",
                    )
            summary = responses_upstream._onemin_attempt_summary(
                now=responses_upstream._now_epoch(),
                window_seconds=3600.0,
                principal_id="principal-live",
            )

        self.assertEqual(summary["attempt_count"], 1)
        self.assertEqual(summary["success_count"], 0)
        self.assertEqual(summary["active_inflight_total"], 0)
        self.assertEqual(summary["status_breakdown"]["error"], 1)

    def test_codex_status_report_exposes_onemin_attempt_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"EA_RESPONSES_PROVIDER_LEDGER_DIR": tmpdir},
            clear=False,
        ):
            responses_upstream._test_reset_onemin_states()
            responses_upstream._record_onemin_attempt_event(
                attempt_id="req-3:1",
                request_id="req-3",
                lane="review",
                model_requested="gpt-5.4",
                account_name="acct-3",
                key_slot="fallback_3",
                endpoint_mode="code",
                endpoint_url="https://api.1min.ai/api/features",
                proxy_id="direct",
                proxy_service="direct",
                timeout_seconds=45,
                latency_ms=1800,
                status="success",
                http_status=200,
                principal_id="principal-2",
                inflight_total=1,
                inflight_same_proxy=1,
                inflight_same_account=1,
            )
            report = responses_upstream.codex_status_report(
                window="1h",
                principal_id="principal-2",
                provider_health={"providers": {"onemin": {"slots": []}}, "provider_config": {}, "jury_service": {}},
            )

        self.assertIn("onemin_attempt_telemetry", report)
        self.assertEqual(report["onemin_attempt_telemetry"]["selected_window"]["attempt_count"], 1)
        self.assertEqual(report["onemin_attempt_telemetry"]["selected_window"]["success_count"], 1)


if __name__ == "__main__":
    unittest.main()
