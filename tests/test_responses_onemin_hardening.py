from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.services import responses_upstream
from app.services import tool_execution_gemini_vortex_adapter as gemini_vortex_adapter


class ResponsesOneminHardeningTests(unittest.TestCase):
    def test_fast_provider_candidates_skip_gemini_when_live_health_degraded(self) -> None:
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
            candidates = responses_upstream._provider_candidates("ea-coder-fast", lane="fast")

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


if __name__ == "__main__":
    unittest.main()
