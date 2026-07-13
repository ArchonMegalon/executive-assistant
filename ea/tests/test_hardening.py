from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import importlib.util
import subprocess
import tempfile
import unittest
import time
import urllib.error
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
from app.api.routes import providers as providers_route
from app.api.routes import responses as responses_route
from app.api.routes import public_memorial_operator
from app.services import responses_upstream
from app.services import provider_registry
from app.services import proactive_ooda_delivery
from app.services import proactive_ooda_safe_work
from app.services import public_clickrank
from app.services import public_rybbit
from app.services import registration_email
from app.services import tool_execution_gemini_vortex_adapter as gemini_vortex_adapter
from app.services import tool_execution_browseract_adapter
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


def _load_script_module(module_name: str, *, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    module = importlib.util.module_from_spec(spec) if spec else None
    if module is None or spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module {module_name} from {path}")
    spec.loader.exec_module(module)
    return module

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

    def test_emailit_daily_limit_fails_fast_without_sleeping_retry_window(self) -> None:
        detail = json.dumps(
            {
                "error": "Daily limit exceeded",
                "message": "Daily sending limit of 5000 messages has been reached.",
                "retry_after": 48712,
            }
        ).encode("utf-8")
        http_error = urllib.error.HTTPError(
            registration_email.EMAILIT_API_BASE,
            429,
            "Too Many Requests",
            hdrs={},
            fp=io.BytesIO(detail),
        )
        with tempfile.TemporaryDirectory() as state_dir:
            env = {
                "EMAILIT_API_KEY": "emailit-fixture",
                "EA_EMAILIT_MAX_429_RETRY_ATTEMPTS": "1",
                "EA_EMAILIT_MAX_429_SLEEP_SECONDS": "30",
                "EA_OUTBOUND_EMAIL_GUARD_STATE_PATH": str(Path(state_dir) / "outbound_email_guard.json"),
            }
            with patch.dict(os.environ, env, clear=True), patch.object(
                registration_email.urllib.request,
                "urlopen",
                side_effect=http_error,
            ) as urlopen, patch.object(registration_email.time, "sleep") as sleep:
                with self.assertRaises(registration_email.EmailDeliveryRateLimitedError) as raised:
                    registration_email.send_plaintext_digest_email(
                        recipient_email="tibor@example.test",
                        digest_key="daily-limit",
                        headline="Daily limit fixture",
                        preview_text="",
                        plain_text="body",
                    )
            self.assertTrue(Path(env["EA_OUTBOUND_EMAIL_GUARD_STATE_PATH"]).is_file())

        self.assertEqual(raised.exception.retry_after_seconds, 48712)
        self.assertEqual(raised.exception.provider_error, "Daily limit exceeded")
        self.assertIn("registration_email_rate_limited", str(raised.exception))
        sleep.assert_not_called()
        self.assertEqual(urlopen.call_count, 1)

    def test_emailit_short_429_retry_still_sleeps_and_sends(self) -> None:
        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"id":"emailit-message-id"}'

        detail = json.dumps({"error": "Too Many Requests", "retry_after": 2}).encode("utf-8")
        http_error = urllib.error.HTTPError(
            registration_email.EMAILIT_API_BASE,
            429,
            "Too Many Requests",
            hdrs={},
            fp=io.BytesIO(detail),
        )
        with tempfile.TemporaryDirectory() as state_dir:
            env = {
                "EMAILIT_API_KEY": "emailit-fixture",
                "EA_EMAILIT_MAX_429_RETRY_ATTEMPTS": "1",
                "EA_EMAILIT_MAX_429_SLEEP_SECONDS": "30",
                "EA_OUTBOUND_EMAIL_GUARD_STATE_PATH": str(Path(state_dir) / "outbound_email_guard.json"),
            }
            with patch.dict(os.environ, env, clear=True), patch.object(
                registration_email.urllib.request,
                "urlopen",
                side_effect=[http_error, _Response()],
            ) as urlopen, patch.object(registration_email.time, "sleep") as sleep:
                receipt = registration_email.send_plaintext_digest_email(
                    recipient_email="tibor@example.test",
                    digest_key="short-retry",
                    headline="Short retry fixture",
                    preview_text="",
                    plain_text="body",
                )
            self.assertTrue(Path(env["EA_OUTBOUND_EMAIL_GUARD_STATE_PATH"]).is_file())

        self.assertEqual(receipt.provider, "emailit")
        self.assertEqual(receipt.message_id, "emailit-message-id")
        sleep.assert_called_once_with(2)
        self.assertEqual(urlopen.call_count, 2)

    def test_proactive_ooda_delivery_does_not_treat_internal_packet_as_telegram_action(self) -> None:
        request = {
            "packet_ref": "packet:proof",
            "staged_artifact_ref": "artifact:proof",
            "approval_prompt": "Approve whether EA should preserve this proof packet as the canonical live check.",
        }
        route = proactive_ooda_delivery.ProactiveOodaDeliveryStatus(
            ready=True,
            selected_channel="telegram",
            selected_transport="telegram",
            selected_by="unit_test",
            selected_reason="fixture",
            recipient_ref_hash="hash",
        )

        self.assertFalse(proactive_ooda_delivery._approval_request_requires_telegram_action(request))
        with patch.object(proactive_ooda_delivery, "prepare_proactive_ooda_telegram_approval") as prepare:
            prompt = proactive_ooda_delivery._proactive_ooda_approval_prompt(
                route=route,
                principal_id="principal",
                tool_runtime=None,
                approval_request=request,
            )

        prepare.assert_not_called()
        self.assertEqual(prompt["prompt_text"], "")
        self.assertEqual(prompt["inline_buttons"], [])
        self.assertEqual(prompt["approval_surface"], {})

    def test_proactive_ooda_delivery_suppresses_internal_telegram_status_packet(self) -> None:
        request = {
            "packet_ref": "packet:proof",
            "staged_artifact_ref": "artifact:proof",
            "approval_prompt": "Approve whether EA should preserve this proof packet as the canonical live check.",
        }
        route = proactive_ooda_delivery.ProactiveOodaDeliveryStatus(
            ready=True,
            selected_channel="telegram",
            selected_transport="telegram",
            selected_by="unit_test",
            selected_reason="fixture",
            recipient_ref_hash="hash",
        )

        with (
            patch.object(proactive_ooda_delivery, "resolve_proactive_ooda_delivery_status", return_value=route),
            patch.object(proactive_ooda_delivery, "_send_telegram_message_for_route") as send,
        ):
            receipt = proactive_ooda_delivery.send_proactive_ooda_notification(
                principal_id="principal",
                text="EA OODA runtime receipt: preserve this proof packet as canonical live check.",
                approval_request=request,
            )

        send.assert_not_called()
        self.assertEqual(receipt.message_ids, ())
        self.assertEqual(receipt.route_error, "telegram_notification_suppressed_non_actionable")
        self.assertEqual(dict(receipt.approval_surface or {}).get("status"), "suppressed_non_actionable")

    def test_proactive_ooda_delivery_suppresses_low_value_research_prompt(self) -> None:
        request = {
            "packet_ref": "packet:research",
            "staged_artifact_ref": "artifact:research",
            "approval_prompt": (
                "Approve whether EA should research further or change constraints. "
                "Research, compare, or draft only; require explicit approval before purchase, booking, "
                "cancellation, sending, posting, or commitment."
            ),
        }
        route = proactive_ooda_delivery.ProactiveOodaDeliveryStatus(
            ready=True,
            selected_channel="telegram",
            selected_transport="telegram",
            selected_by="unit_test",
            selected_reason="fixture",
            recipient_ref_hash="hash",
        )

        with (
            patch.object(proactive_ooda_delivery, "resolve_proactive_ooda_delivery_status", return_value=route),
            patch.object(proactive_ooda_delivery, "_send_telegram_message_for_route") as send,
        ):
            receipt = proactive_ooda_delivery.send_proactive_ooda_notification(
                principal_id="principal",
                text="EA OODA found a reversible research packet and saved it for dashboard review.",
                approval_request=request,
            )

        send.assert_not_called()
        self.assertEqual(receipt.message_ids, ())
        self.assertEqual(receipt.route_error, "telegram_notification_suppressed_non_actionable")

    def test_proactive_ooda_delivery_keeps_real_draft_packet_as_telegram_action(self) -> None:
        request = {
            "packet_ref": "packet:draft",
            "staged_artifact_ref": "artifact:draft",
            "approval_prompt": "Approve whether EA should save this Gmail draft as the chosen next step.",
            "approved_execution_mode": "record_outcome_only",
            "approved_action": "save_gmail_draft",
        }

        self.assertTrue(proactive_ooda_delivery._approval_request_requires_telegram_action(request))

    def test_provider_discovery_draft_blocks_without_safe_provider_candidate(self) -> None:
        packet = {
            "packet_ref": "packet:provider-bad",
            "approval": {"required": False},
            "safe_work_order": {
                "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
                "work_order_id": "work-provider-bad",
                "work_type": "draft",
                "requested_outcome": "Research candidates and prepare one inquiry draft.",
            },
            "stage": {
                "payload": {
                    "draft_mode": "research_backed_inquiry",
                    "locale": "de",
                    "draft_request_text": (
                        "suche mir rauchfangkehrer - ich brauche ein Gutachten, ob ich meinen Zimmerkamin "
                        "als Abluftrohr eines Klimageraetes verwenden kann"
                    ),
                    "research_query": "rauchfangkehrer gutachten klimageraet abluftrohr 1200 wien",
                    "selection_criteria": ["contact details visible", "reachability", "fit to request"],
                    "candidate_items": [
                        {
                            "label": "Difference between ein, eine, einen, and einem in the German language",
                            "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
                            "snippet": "German language grammar lesson and vocabulary examples.",
                            "reachable": True,
                            "page_title": "Difference between ein, eine, einen, and einem in the German language",
                        }
                    ],
                }
            },
        }

        result = proactive_ooda_safe_work.build_safe_work_result(packet, network_fetch_enabled=False)

        self.assertEqual(result["status"], "blocked_needs_research_input")
        self.assertEqual(result["recommended_option_or_draft"], {})
        issue_codes = {row["code"] for row in result["audit"]["issues"]}
        self.assertIn("top_candidate_not_provider_like", issue_codes)
        self.assertIn("draft_not_created", issue_codes)

    def test_provider_discovery_draft_blocks_provider_page_without_request_fit(self) -> None:
        packet = {
            "packet_ref": "packet:provider-generic-contact",
            "approval": {"required": False},
            "safe_work_order": {
                "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
                "work_order_id": "work-provider-generic-contact",
                "work_type": "draft",
                "requested_outcome": "Research candidates and prepare one inquiry draft.",
            },
            "stage": {
                "payload": {
                    "draft_mode": "research_backed_inquiry",
                    "locale": "de",
                    "draft_request_text": (
                        "suche mir rauchfangkehrer - ich brauche ein Gutachten, ob ich meinen Zimmerkamin "
                        "als Abluftrohr eines Klimageraetes verwenden kann"
                    ),
                    "research_query": "rauchfangkehrer gutachten klimageraet abluftrohr 1200 wien",
                    "selection_criteria": ["contact details visible", "reachability", "fit to request"],
                    "candidate_items": [
                        {
                            "label": "Dienstleister Wien - Kontakt und Leistungen",
                            "url": "https://example.test/kontakt",
                            "snippet": "Kontakt, Leistungen, Services und Office fuer allgemeine Anfragen in Wien.",
                            "contact_email": "office@example.test",
                            "reachable": True,
                            "page_title": "Kontakt und Leistungen",
                        }
                    ],
                }
            },
        }

        result = proactive_ooda_safe_work.build_safe_work_result(packet, network_fetch_enabled=False)

        self.assertEqual(result["status"], "blocked_needs_research_input")
        self.assertEqual(result["recommended_option_or_draft"], {})
        issue_codes = {row["code"] for row in result["audit"]["issues"]}
        self.assertIn("top_candidate_not_provider_like", issue_codes)
        self.assertIn("draft_not_created", issue_codes)
        self.assertIn("provider request terms missing", result["comparison_table"][0]["constraint_violations"])

    def test_provider_discovery_draft_uses_safe_provider_candidate(self) -> None:
        packet = {
            "packet_ref": "packet:provider-good",
            "approval": {"required": False},
            "safe_work_order": {
                "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
                "work_order_id": "work-provider-good",
                "work_type": "draft",
                "requested_outcome": "Research candidates and prepare one inquiry draft.",
            },
            "stage": {
                "payload": {
                    "draft_mode": "research_backed_inquiry",
                    "locale": "de",
                    "draft_request_text": (
                        "ich brauche ein Gutachten, ob ich meinen Zimmerkamin als Abluftrohr "
                        "eines Klimageraetes verwenden kann"
                    ),
                    "research_query": "rauchfangkehrer gutachten klimageraet abluftrohr 1200 wien",
                    "selection_criteria": ["contact details visible", "reachability", "fit to request"],
                    "candidate_items": [
                        {
                            "label": "Rauchfangkehrer Mayr - Befund und Gutachten Wien",
                            "url": "https://rauchfangkehrer-mayr.at/befunde/",
                            "snippet": "Rauchfangkehrermeister fuer Befund, Gutachten, Leistungen und Kontakt in Wien.",
                            "contact_email": "office@example.test",
                            "reachable": True,
                            "page_title": "Befund vom Rauchfangkehrer",
                        }
                    ],
                }
            },
        }

        result = proactive_ooda_safe_work.build_safe_work_result(packet, network_fetch_enabled=False)
        recommended = result["recommended_option_or_draft"]

        self.assertEqual(result["status"], "staged_for_user_decision")
        self.assertEqual(recommended["source"], "candidate_synthesis")
        self.assertEqual(recommended["recipient_email"], "office@example.test")
        self.assertIn("Rauchfangkehrer Mayr", recommended["value"])

    def test_provider_secret_file_candidates_finds_parent_config_path_for_relative_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            repo_root = base / "repo"
            repo_root.mkdir()
            cwd = base / "runtime"
            cwd.mkdir()
            (base / "config").mkdir()
            password_file = base / "config" / "amazon_archon_password"
            password_file.write_text("fixture-secret-value", encoding="utf-8")
            original_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                with patch.object(provider_registry, "_repo_root", return_value=repo_root):
                    loaded = provider_registry._secret_file_value("../config/amazon_archon_password")
                self.assertEqual(loaded, "fixture-secret-value")
            finally:
                os.chdir(original_cwd)

    def test_browseract_secret_file_candidates_finds_parent_config_path_for_relative_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            repo_root = base / "repo"
            repo_root.mkdir()
            cwd = base / "runtime"
            cwd.mkdir()
            (base / "config").mkdir()
            password_file = base / "config" / "amazon_archon_password"
            password_file.write_text("fixture-secret-value", encoding="utf-8")
            original_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                with patch.object(tool_execution_browseract_adapter, "_repo_root", return_value=repo_root):
                    loaded = tool_execution_browseract_adapter._secret_file_value("../config/amazon_archon_password")
                self.assertEqual(loaded, "fixture-secret-value")
            finally:
                os.chdir(original_cwd)

    def test_memorial_route_probe_collects_fast_and_failed_probes(self) -> None:
        def probe(url: str, timeout_seconds: float = 5.0) -> dict[str, object]:
            return {
                "url": url,
                "status_code": 200 if "fast" in url else 404,
                "status": "pass" if "fast" in url else "not_found",
                "detail": "",
            }

        with patch.object(public_memorial_operator, "_probe_url", side_effect=probe):
            result = public_memorial_operator._probe_urls(
                ["http://example.test/fast", "http://example.test/fail"],
                timeout_seconds=0.5,
            )

        self.assertEqual(
            result["http://example.test/fast"],
            {
                "url": "http://example.test/fast",
                "status_code": 200,
                "status": "pass",
                "detail": "",
            },
        )
        self.assertEqual(
            result["http://example.test/fail"],
            {
                "url": "http://example.test/fail",
                "status_code": 404,
                "status": "not_found",
                "detail": "",
            },
        )

    def test_memorial_route_probe_times_out_without_failing(self) -> None:
        start = time.perf_counter()

        def probe(url: str, timeout_seconds: float = 5.0) -> dict[str, object]:
            if "slow" in url:
                time.sleep(1.0)
            return {
                "url": url,
                "status_code": 200 if "fast" in url else 404,
                "status": "pass" if "fast" in url else "not_found",
                "detail": "",
            }

        with patch.object(public_memorial_operator, "_probe_url", side_effect=probe):
            result = public_memorial_operator._probe_urls(
                ["http://example.test/fast", "http://example.test/slow"],
                timeout_seconds=0.05,
            )

        self.assertLess(time.perf_counter() - start, 0.8)
        self.assertIn("http://example.test/fast", result)
        self.assertEqual(result["http://example.test/fast"]["status_code"], 200)
        self.assertIn("http://example.test/slow", result)
        self.assertEqual(result["http://example.test/slow"]["status"], "timeout")
        self.assertEqual(result["http://example.test/slow"]["detail"], "probe_timeout")

    def test_materialized_telegram_audiobook_readiness_tracks_cinematic_narration(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "materialize_telegram_audiobook_live_readiness.py"
        materialize_module = _load_script_module("ea_materialize_audiobook_live_readiness_for_test", path=script_path)
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt = materialize_module.materialize_telegram_audiobook_live_readiness(
                receipt_path=Path(tmpdir) / "telegram_audiobook_live_readiness_test.json"
            )
        voice_items = receipt.get("voice_samples", {}).get("items", [])
        cinematic_items = [item for item in voice_items if item.get("key") == "unmixr_cinematic_narration_enabled"]
        self.assertEqual(receipt.get("head_semantics"), "source_state")
        self.assertTrue(receipt.get("source_git_head"))
        self.assertTrue(receipt.get("source_state_fingerprint"))
        self.assertEqual(len(cinematic_items), 1)
        self.assertEqual(cinematic_items[0].get("status"), "ready")

    def test_verify_audiobook_cinematic_readiness_fails_if_disabled(self) -> None:
        script_root = Path(__file__).resolve().parents[1] / "scripts"
        materialize_module = _load_script_module("ea_materialize_audiobook_live_readiness_for_verify_test", path=script_root / "materialize_telegram_audiobook_live_readiness.py")
        verify_module = _load_script_module("ea_verify_audiobook_live_readiness_for_test", path=script_root / "verify_telegram_audiobook_live_readiness.py")
        with (
            patch.dict(
                os.environ,
                {
                    "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1",
                    "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1",
                    "UNMIXR_API_KEY": "test",
                    "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_ENABLED": "1",
                    "EA_AUDIOBOOK_CINEMATIC_NARRATION": "0",
                    "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES": "commemorative",
                    "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_TARGET_COUNT": "3",
                    "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED": "1",
                },
                clear=False,
            ),
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            temp_path = Path(tmpdir) / "receipt.json"
            materialize_module.materialize_telegram_audiobook_live_readiness(receipt_path=temp_path)
            verification = verify_module.verify_telegram_audiobook_live_readiness(
                temp_path,
                runtime_container=None,
                require_deployed_runtime=False,
            )
            self.assertEqual(verification.get("status"), "fail")
            issues = [str(item) for item in verification.get("issues", [])]
            self.assertTrue(any("live_readiness_critical_voice_item_blocked:unmixr_cinematic_narration_enabled" in item for item in issues))

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

    def test_workspace_access_session_rewrites_ea_property_targets_back_home(self) -> None:
        request = SimpleNamespace(
            headers={},
            query_params={"return_to": "/app/research/candidate-123"},
            cookies={},
            client=SimpleNamespace(host="198.51.100.10"),
            url=SimpleNamespace(path="/workspace-access/token-1"),
        )
        product = SimpleNamespace(
            open_workspace_access_session=lambda token, actor: {
                "access_token": "session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "default_target": "/app/research/candidate-123",
            }
        )
        with (
            patch.object(landing_access_support, "build_product_service", lambda container: product),
            patch.object(landing_access_support, "request_brand", lambda request: {"key": "ea", "app_home": "/app/today"}),
            patch.object(landing_access_support, "get_cloudflare_access_identity", side_effect=HTTPException(status_code=401, detail="cloudflare_access_invalid")),
            patch.object(landing_access_support, "get_request_context", side_effect=HTTPException(status_code=401, detail="auth_required")),
            patch.object(landing_access_support, "_workspace_session_payload", lambda request, container: None),
            patch.object(landing_access_support, "_workspace_session_cookie_kwargs", lambda request, expires_at: {"httponly": True}),
            patch.object(landing_access_support, "_normalize_browser_return_to", lambda value, default: str(value or default)),
        ):
            response = landing_access_support.workspace_access_session("token-1", request, SimpleNamespace())

        self.assertEqual(getattr(response, "status_code", None), 303)
        self.assertEqual(response.headers.get("location"), "/app/today")

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

    def test_onemin_selector_discovers_six_indexed_accounts_without_legacy_primary(self) -> None:
        env = {f"EA_RESPONSES_ONEMIN_API_KEY_{index}": f"key-{index}" for index in range(1, 7)}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                responses_upstream._onemin_secret_env_names(),
                tuple(f"EA_RESPONSES_ONEMIN_API_KEY_{index}" for index in range(1, 7)),
            )
            self.assertEqual(
                responses_upstream._onemin_key_names(),
                tuple(f"key-{index}" for index in range(1, 7)),
            )
            self.assertEqual(responses_upstream._onemin_active_keys(), tuple(f"key-{index}" for index in range(1, 7)))
            self.assertEqual(
                responses_upstream._onemin_key_slot("key-1", key_names=responses_upstream._onemin_key_names()),
                "primary",
            )
            self.assertEqual(
                responses_upstream._onemin_key_slot("key-6", key_names=responses_upstream._onemin_key_names()),
                "fallback_5",
            )

    def test_onemin_selector_applies_slots_to_indexed_accounts(self) -> None:
        env = {
            **{f"EA_RESPONSES_ONEMIN_API_KEY_{index}": f"key-{index}" for index in range(1, 7)},
            "EA_RESPONSES_ONEMIN_ACTIVE_SLOTS": "primary,fallback_5",
            "EA_RESPONSES_ONEMIN_RESERVE_SLOTS": "fallback_1,fallback_2,fallback_3,fallback_4",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(responses_upstream._onemin_active_keys(), ("key-1", "key-6"))
            self.assertEqual(responses_upstream._onemin_reserve_keys(), ("key-2", "key-3", "key-4", "key-5"))
            self.assertEqual(
                responses_upstream._ordered_onemin_keys_allow_reserve(False),
                ("key-1", "key-6"),
            )
            self.assertEqual(
                responses_upstream._ordered_onemin_keys_allow_reserve(True),
                tuple(f"key-{index}" for index in range(1, 7)),
            )

    def test_onemin_selector_supports_generic_all_and_ranges(self) -> None:
        env = {
            **{f"EA_RESPONSES_ONEMIN_API_KEY_{index}": f"key-{index}" for index in range(1, 12)},
            "EA_RESPONSES_ONEMIN_ACTIVE_SLOTS": "all",
            "EA_RESPONSES_ONEMIN_RESERVE_SLOTS": "none",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(responses_upstream._onemin_active_keys(), tuple(f"key-{index}" for index in range(1, 12)))
            self.assertEqual(responses_upstream._onemin_reserve_keys(), ())

        env = {
            **{f"EA_RESPONSES_ONEMIN_API_KEY_{index}": f"key-{index}" for index in range(1, 12)},
            "EA_RESPONSES_ONEMIN_ACTIVE_SLOTS": "primary,fallback_1..fallback_5",
            "EA_RESPONSES_ONEMIN_RESERVE_SLOTS": "fallback_6:fallback_10",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(responses_upstream._onemin_active_keys(), tuple(f"key-{index}" for index in range(1, 7)))
            self.assertEqual(responses_upstream._onemin_reserve_keys(), tuple(f"key-{index}" for index in range(7, 12)))

    def test_provider_registry_discovers_indexed_onemin_accounts(self) -> None:
        env = {f"EA_RESPONSES_ONEMIN_API_KEY_{index}": f"key-{index}" for index in range(1, 7)}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                provider_registry._onemin_secret_env_names(),
                tuple(f"EA_RESPONSES_ONEMIN_API_KEY_{index}" for index in range(1, 7)),
            )

    def test_provider_health_fallback_uses_generic_indexed_onemin_selector(self) -> None:
        env = {f"EA_RESPONSES_ONEMIN_API_KEY_{index}": f"key-{index}" for index in range(1, 7)}
        with patch.dict(os.environ, env, clear=True):
            snapshot = responses_route._minimal_provider_health_snapshot(
                lightweight=True,
                reason="unit_test",
            )

        slots = snapshot["providers"]["onemin"]["slots"]
        self.assertEqual(snapshot["providers"]["onemin"]["configured_slots"], 6)
        self.assertEqual(
            [slot["account_name"] for slot in slots],
            [f"EA_RESPONSES_ONEMIN_API_KEY_{index}" for index in range(1, 7)],
        )
        self.assertEqual([slot["slot"] for slot in slots], ["primary", "fallback_1", "fallback_2", "fallback_3", "fallback_4", "fallback_5"])

    def test_provider_onemin_slot_names_support_indexed_account_labels(self) -> None:
        self.assertEqual(providers_route._onemin_slot_name_for_account_label("EA_RESPONSES_ONEMIN_API_KEY"), "primary")
        self.assertEqual(providers_route._onemin_slot_name_for_account_label("EA_RESPONSES_ONEMIN_API_KEY_1"), "primary")
        self.assertEqual(providers_route._onemin_slot_name_for_account_label("EA_RESPONSES_ONEMIN_API_KEY_6"), "fallback_5")
        self.assertEqual(providers_route._onemin_slot_name_for_account_label("ONEMIN_API_KEY_6"), "fallback_5")

    def test_provider_onemin_binding_resolution_accepts_indexed_external_refs(self) -> None:
        binding = SimpleNamespace(
            auth_metadata_json={"trusted_onemin_mapping": True},
            external_account_ref="EA_RESPONSES_ONEMIN_API_KEY_6",
        )
        self.assertEqual(providers_route._resolve_onemin_account_labels(binding), ("EA_RESPONSES_ONEMIN_API_KEY_6",))

    def test_provider_health_env_signature_tracks_indexed_onemin_keys(self) -> None:
        base_env = {f"EA_RESPONSES_ONEMIN_API_KEY_{index}": f"key-{index}" for index in range(1, 7)}
        with patch.dict(os.environ, base_env, clear=True):
            first_signature = responses_route._provider_health_env_signature()
        updated_env = dict(base_env)
        updated_env["EA_RESPONSES_ONEMIN_API_KEY_6"] = "key-6-rotated"
        with patch.dict(os.environ, updated_env, clear=True):
            second_signature = responses_route._provider_health_env_signature()

        self.assertNotEqual(first_signature, second_signature)

    def test_provider_health_env_signature_tracks_cost_routing_knobs(self) -> None:
        base_env = {
            "EA_RESPONSES_PROVIDER_ORDER": "onemin,magixai,gemini_vortex",
            "EA_RESPONSES_GROUNDWORK_PROVIDER_ORDER": "onemin,magixai,gemini_vortex",
            "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H": "200000",
            "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS": "86400",
        }
        with patch.dict(os.environ, base_env, clear=True):
            first_signature = responses_route._provider_health_env_signature()
        updated_env = dict(base_env)
        updated_env["EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H"] = "100000"
        with patch.dict(os.environ, updated_env, clear=True):
            second_signature = responses_route._provider_health_env_signature()
        updated_env = dict(base_env)
        updated_env["EA_RESPONSES_GROUNDWORK_PROVIDER_ORDER"] = "magixai,onemin,gemini_vortex"
        with patch.dict(os.environ, updated_env, clear=True):
            third_signature = responses_route._provider_health_env_signature()

        self.assertNotEqual(first_signature, second_signature)
        self.assertNotEqual(first_signature, third_signature)

    def test_onemin_shell_resolver_discovers_six_indexed_accounts_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "# six account rotation should not require hardcoded fallbacks",
                        *(f"EA_RESPONSES_ONEMIN_API_KEY_{index}='key-{index}'" for index in range(1, 7)),
                        "ONEMIN_AI_API_KEY_FALLBACK_99=key-6",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            env = {
                "PATH": os.environ.get("PATH", ""),
                "EA_ENV_FILE": str(env_file),
            }
            all_keys = subprocess.run(
                ["bash", "../scripts/resolve_onemin_ai_key.sh", "--all"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                check=True,
                capture_output=True,
            )
            self.assertEqual(all_keys.stdout.splitlines(), [f"key-{index}" for index in range(1, 7)])

            next_key = subprocess.run(
                ["bash", "../scripts/resolve_onemin_ai_key.sh", "--next", "key-5"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                check=True,
                capture_output=True,
            )
            self.assertEqual(next_key.stdout.strip(), "key-6")

    def test_provider_registry_discovers_onemin_slot_ranges(self) -> None:
        env = {
            "ONEMIN_AI_API_KEY": "key-0",
            "EA_RESPONSES_ONEMIN_ACTIVE_SLOTS": "primary,fallback_2..fallback_4",
            "EA_RESPONSES_ONEMIN_RESERVE_SLOTS": "fallback_8:fallback_9",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                provider_registry._onemin_secret_env_names(),
                (
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_2",
                    "ONEMIN_AI_API_KEY_FALLBACK_3",
                    "ONEMIN_AI_API_KEY_FALLBACK_4",
                    "ONEMIN_AI_API_KEY_FALLBACK_8",
                    "ONEMIN_AI_API_KEY_FALLBACK_9",
                ),
            )

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

    def test_codex_status_report_keeps_redacted_provider_capacity_counts(self) -> None:
        provider_health = {
            "providers": {
                "onemin": {
                    "configured_slots": 6,
                    "live_dispatchable_slot_count": 2,
                    "slots": [
                        {"account_name": "secret-primary", "state": "ready", "slot_role": "active"},
                        {"account_name": "secret-fallback-1", "state": "ready", "slot_role": "active"},
                        {"account_name": "secret-fallback-2", "state": "degraded", "slot_role": "reserve"},
                        {"account_name": "secret-fallback-3", "state": "unknown", "slot_role": "reserve"},
                        {"account_name": "secret-fallback-4", "state": "unknown", "slot_role": "reserve"},
                        {"account_name": "secret-fallback-5", "state": "unknown", "slot_role": "reserve"},
                    ],
                }
            },
            "provider_config": {
                "onemin_accounts": ["secret-primary", "secret-fallback-1", "secret-fallback-2"],
                "onemin_active_accounts": ["secret-primary", "secret-fallback-1"],
                "onemin_reserve_accounts": ["secret-fallback-2"],
            },
            "jury_service": {},
        }

        report = responses_upstream.codex_status_report(
            window="1h",
            principal_id="principal-2",
            provider_health=provider_health,
        )

        self.assertEqual(report["provider_health"], {})
        self.assertEqual(report["providers_summary"], [])
        self.assertEqual(report["onemin_aggregate"], {})
        self.assertEqual(report["provider_capacity"]["redaction"], "counts_only")
        self.assertEqual(report["provider_capacity"]["onemin"]["configured_slots"], 6)
        self.assertEqual(report["provider_capacity"]["onemin"]["ready_slots"], 2)
        self.assertEqual(report["provider_capacity"]["onemin"]["degraded_slots"], 1)
        self.assertEqual(report["provider_capacity"]["onemin"]["unknown_slots"], 3)
        self.assertEqual(report["provider_capacity"]["onemin"]["configured_accounts"], 3)
        self.assertEqual(report["provider_capacity"]["onemin"]["active_accounts"], 2)
        self.assertEqual(report["provider_capacity"]["onemin"]["reserve_accounts"], 1)
        self.assertNotIn("secret-primary", str(report["provider_capacity"]))

    def test_compact_codex_status_report_keeps_redacted_provider_capacity_counts(self) -> None:
        provider_health = {
            "providers": {
                "onemin": {
                    "configured_slots": 3,
                    "live_ready_slot_count": 1,
                    "slots": [
                        {"account_name": "secret-primary", "state": "ready", "slot_role": "active"},
                        {"account_name": "secret-fallback-1", "state": "unknown", "slot_role": "active"},
                        {"account_name": "secret-fallback-2", "state": "unknown", "slot_role": "reserve"},
                    ],
                }
            },
            "provider_config": {
                "onemin_accounts": ["secret-primary", "secret-fallback-1", "secret-fallback-2"],
                "onemin_active_accounts": ["secret-primary", "secret-fallback-1"],
                "onemin_reserve_accounts": ["secret-fallback-2"],
            },
            "jury_service": {},
        }

        report = responses_upstream.codex_status_report(
            window="1h",
            principal_id="principal-2",
            provider_health=provider_health,
            compact=True,
        )

        self.assertEqual(report["provider_health"], {"providers": {"_compact": {"state": "ready"}}})
        self.assertEqual(report["providers_summary"], [])
        self.assertEqual(report["provider_capacity"]["onemin"]["configured_slots"], 3)
        self.assertEqual(report["provider_capacity"]["onemin"]["ready_slots"], 1)
        self.assertEqual(report["provider_capacity"]["onemin"]["unknown_slots"], 2)
        self.assertEqual(report["provider_capacity"]["onemin"]["active_accounts"], 2)
        self.assertNotIn("secret-primary", str(report["provider_capacity"]))


if __name__ == "__main__":
    unittest.main()
