from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.api.routes import public_memorial_operator
from app.api.routes import public_memorials


class MemorialRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        public_memorials._MEMORIAL_RUNTIME_READINESS_CACHE_STATE.clear()

    def test_resolve_memorial_voice_chat_model_prefers_fast_before_gemini(self) -> None:
        payload = {"chat_models": [public_memorials.GEMINI_VORTEX_PUBLIC_MODEL, public_memorials.FAST_PUBLIC_MODEL]}

        model = public_memorials._resolve_memorial_voice_chat_model(
            payload,
            {},
            "Hallo Manfred, kann ich jetzt mit dir reden?",
        )

        self.assertEqual(model, public_memorials.FAST_PUBLIC_MODEL)

    def test_resolve_memorial_realtime_chat_model_prefers_fast_before_gemini(self) -> None:
        payload = {"chat_models": [public_memorials.GEMINI_VORTEX_PUBLIC_MODEL, public_memorials.FAST_PUBLIC_MODEL]}

        model = public_memorials._resolve_memorial_realtime_chat_model(payload, {})

        self.assertEqual(model, public_memorials.FAST_PUBLIC_MODEL)

    def test_public_memorial_page_opens_with_person_context_before_runtime_button(self) -> None:
        payload = {
            "slug": "manfred",
            "person_name": "Manfred",
            "title": "Erinnerungen an Manfred",
            "subtitle": "Eine ruhige Seite fuer Erinnerungen, Originalstimme und dokumentierte Gedanken.",
            "intro": "Diese Seite sammelt echte Aufnahmen und belegte Erinnerungen. Neue Texte sind keine direkte Rede.",
            "audio_clips": [{"asset_relpath": "voice.mp3"}],
            "memory_cards": [{"title": "Kindheit", "body": "Kurzfassung"}],
        }
        with (
            patch.object(public_memorials, "clickrank_head_snippet", return_value=""),
            patch.object(public_memorials, "_memorial_pwa_icon_url", return_value="/memorials/manfred/icon-180.png"),
            patch.object(public_memorials, "_memorial_video_call_avatar", return_value={}),
            patch.object(public_memorials, "_memorial_video_call_avatar_fallback_html", return_value=""),
        ):
            html = public_memorials._public_memorial_page_html(payload, hostname="myexternalbrain.com", private_profile={})

        self.assertIn("<h1>Erinnerungen an Manfred</h1>", html)
        self.assertIn("Eine ruhige Seite fuer Erinnerungen, Originalstimme und dokumentierte Gedanken.", html)
        self.assertNotIn("Diese Seite sammelt echte Aufnahmen und belegte Erinnerungen.", html)
        self.assertNotIn("1 Archivaufnahmen", html)
        self.assertNotIn("1 belegte Erinnerungen", html)
        self.assertIn("Das Mikrofon wird erst nach deinem Start verwendet.", html)
        self.assertIn("Gespräch wird vorbereitet …", html)

    def test_schedule_memorial_live_warmup_queues_voice_when_base_warmup_ready(self) -> None:
        with (
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "inflight": False,
                    "warm": True,
                    "voice_required": True,
                    "voice_ready": False,
                    "voice_inflight": False,
                },
            ),
            patch.object(public_memorials, "_schedule_missing_memorial_voice_prewarm", return_value=True) as schedule_voice,
        ):
            result = public_memorials._schedule_memorial_live_warmup("manfred")

        self.assertEqual(
            result,
            {
                "status": "queued_voice",
                "scheduled": True,
                "ttl_seconds": public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS,
            },
        )
        schedule_voice.assert_called_once_with("manfred")

    def test_schedule_memorial_live_warmup_reports_voice_cold_when_voice_prewarm_cannot_start(self) -> None:
        with (
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "inflight": False,
                    "warm": True,
                    "voice_required": True,
                    "voice_ready": False,
                    "voice_inflight": False,
                },
            ),
            patch.object(public_memorials, "_schedule_missing_memorial_voice_prewarm", return_value=False),
        ):
            result = public_memorials._schedule_memorial_live_warmup("manfred")

        self.assertEqual(
            result,
            {
                "status": "voice_cold",
                "scheduled": False,
                "ttl_seconds": public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS,
            },
        )

    def test_schedule_memorial_live_warmup_requeues_stale_voice_prewarm(self) -> None:
        with (
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "inflight": False,
                    "warm": True,
                    "voice_required": True,
                    "voice_ready": False,
                    "voice_inflight": True,
                    "voice_prewarm_stale": True,
                },
            ),
            patch.object(public_memorials, "_schedule_missing_memorial_voice_prewarm", return_value=True) as schedule_voice,
        ):
            result = public_memorials._schedule_memorial_live_warmup("manfred")

        self.assertEqual(
            result,
            {
                "status": "requeued_stale_voice",
                "scheduled": True,
                "ttl_seconds": public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS,
            },
        )
        schedule_voice.assert_called_once_with("manfred")

    def test_schedule_memorial_live_warmup_reports_stale_voice_when_requeue_fails(self) -> None:
        with (
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "inflight": False,
                    "warm": True,
                    "voice_required": True,
                    "voice_ready": False,
                    "voice_inflight": True,
                    "voice_prewarm_stale": True,
                },
            ),
            patch.object(public_memorials, "_schedule_missing_memorial_voice_prewarm", return_value=False),
        ):
            result = public_memorials._schedule_memorial_live_warmup("manfred")

        self.assertEqual(
            result,
            {
                "status": "voice_stale",
                "scheduled": False,
                "ttl_seconds": public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS,
            },
        )

    def test_memorial_runtime_readiness_is_degraded_when_realtime_backend_is_unavailable(self) -> None:
        with (
            patch.object(public_memorials, "_public_memorial_surface_probe", return_value={"slug": "manfred", "person_name": "Manfred"}),
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "status": "warm_recent",
                    "warm": True,
                    "inflight": False,
                    "started_at": 0.0,
                    "completed_at": 1.0,
                    "ttl_remaining_seconds": 120.0,
                    "errors": [],
                    "voice_ready": True,
                    "voice_inflight": False,
                    "voice_prewarm_stale": False,
                    "voice_prewarm_stale_in_seconds": 0.0,
                    "voice_completed_at": 1.0,
                    "voice_ttl_remaining_seconds": 90.0,
                    "voice_errors": [],
                    "voice_required": True,
                },
            ),
            patch.object(public_memorials, "_load_memorial", return_value={"slug": "manfred"}),
            patch.object(public_memorials, "_load_voice_config", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_public_voice_profile_summary", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_tts_plugin_options", return_value=[{"tts_plugin_enabled": True}]),
            patch.object(public_memorials, "_resolve_server_tts_plugin", return_value=("unmixr", {"tts_plugin_enabled": True})),
            patch.object(public_memorials, "_load_private_profile", return_value={}),
            patch.object(public_memorials, "_resolve_memorial_voice_chat_model", return_value="gemini-2.5-flash"),
            patch.object(public_memorials, "_gemini_live_available", return_value=False),
        ):
            readiness = public_memorials._memorial_runtime_readiness("manfred")

        self.assertEqual(readiness["status"], "degraded_realtime")
        self.assertEqual(readiness["interaction_mode"], "spoken_turn_fallback")
        self.assertTrue(readiness["spoken_voice_ready"])
        self.assertFalse(readiness["realtime_ready"])
        self.assertTrue(readiness["ready"])
        self.assertIn("realtime_backend_unavailable", readiness["degraded_reasons"])
        self.assertIn("check_memorial_realtime_backend", readiness["next_actions"])
        self.assertIn("continue_with_spoken_turn_fallback", readiness["next_actions"])
        self.assertTrue(readiness["operator_attention_recommended"])
        self.assertFalse(readiness["operator_action_required"])
        self.assertGreater(readiness["readiness_checked_at"], 0.0)
        self.assertEqual(readiness["readiness_ttl_remaining_seconds"], 90.0)
        self.assertEqual(readiness["readiness_ttl_state"], "refresh_soon")
        self.assertTrue(readiness["readiness_refresh_recommended"])
        self.assertEqual(readiness["operator_action_state"], "refresh_recommended")

    def test_memorial_runtime_readiness_exposes_operator_recovery_actions_when_not_ready(self) -> None:
        with (
            patch.object(public_memorials, "_public_memorial_surface_probe", return_value={"slug": "manfred", "person_name": "Manfred"}),
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "status": "cold",
                    "warm": False,
                    "inflight": False,
                    "started_at": 0.0,
                    "completed_at": 0.0,
                    "errors": [],
                    "voice_ready": False,
                    "voice_inflight": False,
                    "voice_prewarm_stale": False,
                    "voice_prewarm_stale_in_seconds": 0.0,
                    "voice_completed_at": 0.0,
                    "voice_errors": [],
                    "voice_required": True,
                },
            ),
            patch.object(public_memorials, "_load_memorial", return_value={"slug": "manfred"}),
            patch.object(public_memorials, "_load_voice_config", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_public_voice_profile_summary", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_tts_plugin_options", return_value=[{"tts_plugin_enabled": False}]),
            patch.object(public_memorials, "_resolve_server_tts_plugin", return_value=("unmixr", {"tts_plugin_enabled": False})),
            patch.object(public_memorials, "_load_private_profile", return_value={}),
            patch.object(public_memorials, "_resolve_memorial_voice_chat_model", return_value=""),
            patch.object(public_memorials, "_gemini_live_available", return_value=False),
        ):
            readiness = public_memorials._memorial_runtime_readiness("manfred")

        self.assertEqual(readiness["status"], "warming")
        self.assertFalse(readiness["ready"])
        self.assertTrue(readiness["operator_attention_recommended"])
        self.assertTrue(readiness["operator_action_required"])
        self.assertEqual(readiness["operator_action_state"], "action_required")
        self.assertEqual(
            readiness["next_actions"],
            [
                "run_memorial_warmup",
                "run_memorial_voice_prewarm",
                "configure_memorial_tts_provider",
                "configure_memorial_conversation_model",
                "check_memorial_realtime_backend",
            ],
        )

    def test_memorial_readiness_next_actions_avoid_redundant_base_warmup_when_voice_is_cold(self) -> None:
        actions = public_memorials._memorial_readiness_next_actions(
            ["voice_prewarm_cold", "realtime_backend_unavailable"],
            ready=False,
            realtime_ready=False,
        )

        self.assertEqual(actions, ["run_memorial_voice_prewarm", "check_memorial_realtime_backend"])
        self.assertNotIn("run_memorial_warmup", actions)

    def test_memorial_operator_action_state_is_normalized_for_operator_surfaces(self) -> None:
        self.assertEqual(
            public_memorials._memorial_operator_action_state(
                operator_attention_recommended=False,
                operator_action_required=False,
                readiness_refresh_recommended=False,
                degraded_reasons=[],
            ),
            "clear",
        )
        self.assertEqual(
            public_memorials._memorial_operator_action_state(
                operator_attention_recommended=True,
                operator_action_required=False,
                readiness_refresh_recommended=False,
                degraded_reasons=["voice_prewarm_warming"],
            ),
            "waiting_on_runtime",
        )
        self.assertEqual(
            public_memorials._memorial_operator_action_state(
                operator_attention_recommended=True,
                operator_action_required=True,
                readiness_refresh_recommended=True,
                degraded_reasons=["warmup_cold"],
            ),
            "action_required",
        )
        self.assertEqual(
            public_memorials._memorial_operator_action_state(
                operator_attention_recommended=True,
                operator_action_required=False,
                readiness_refresh_recommended=True,
                degraded_reasons=["realtime_backend_unavailable"],
            ),
            "refresh_recommended",
        )
        self.assertEqual(
            public_memorials._memorial_operator_action_state(
                operator_attention_recommended=True,
                operator_action_required=False,
                readiness_refresh_recommended=False,
                degraded_reasons=["realtime_backend_unavailable"],
            ),
            "attention",
        )

    def test_memorial_operator_recheck_cadence_is_normalized_for_operator_surfaces(self) -> None:
        self.assertEqual(public_memorials._memorial_operator_recheck_after_seconds("action_required"), 0)
        self.assertEqual(public_memorials._memorial_operator_recheck_after_seconds("waiting_on_runtime"), 5)
        self.assertEqual(public_memorials._memorial_operator_recheck_after_seconds("refresh_recommended"), 30)
        self.assertEqual(public_memorials._memorial_operator_recheck_after_seconds("attention"), 60)
        self.assertEqual(public_memorials._memorial_operator_recheck_after_seconds("clear"), 120)
        self.assertEqual(public_memorials._memorial_operator_recheck_after_seconds(""), 120)

    def test_memorial_voice_prewarm_state_is_normalized_for_operator_surfaces(self) -> None:
        self.assertEqual(
            public_memorials._memorial_voice_prewarm_state(
                voice_required=False,
                voice_ready=False,
                voice_inflight=False,
                voice_prewarm_stale=False,
                voice_errors=[],
            ),
            "not_required",
        )
        self.assertEqual(
            public_memorials._memorial_voice_prewarm_state(
                voice_required=True,
                voice_ready=False,
                voice_inflight=True,
                voice_prewarm_stale=False,
                voice_errors=[],
            ),
            "warming",
        )
        self.assertEqual(
            public_memorials._memorial_voice_prewarm_state(
                voice_required=True,
                voice_ready=False,
                voice_inflight=True,
                voice_prewarm_stale=True,
                voice_errors=[],
            ),
            "stale",
        )
        self.assertEqual(
            public_memorials._memorial_voice_prewarm_state(
                voice_required=True,
                voice_ready=True,
                voice_inflight=False,
                voice_prewarm_stale=False,
                voice_errors=[],
            ),
            "ready",
        )
        self.assertEqual(
            public_memorials._memorial_voice_prewarm_state(
                voice_required=True,
                voice_ready=True,
                voice_inflight=False,
                voice_prewarm_stale=False,
                voice_errors=["provider_timeout"],
            ),
            "error",
        )

    def test_memorial_warmup_snapshot_marks_stale_voice_prewarm(self) -> None:
        now = 1_000.0
        with (
            patch.object(public_memorials.time, "time", return_value=now),
            patch.dict(public_memorials.os.environ, {"EA_MEMORIAL_VOICE_PREWARM_STALE_SECONDS": "30"}, clear=False),
            patch.object(
                public_memorials,
                "_MEMORIAL_LIVE_WARMUP_STATE",
                {
                    "manfred": {
                        "inflight": False,
                        "started_at": now - 100.0,
                        "completed_at": now - 90.0,
                        "errors": [],
                        "voice_contact_required": True,
                        "voice_contact_inflight": True,
                        "voice_contact_started_at": now - 31.0,
                        "voice_contact_completed_at": 0.0,
                        "voice_contact_errors": [],
                    }
                },
            ),
        ):
            snapshot = public_memorials._memorial_live_warmup_snapshot("manfred")

        self.assertEqual(snapshot["status"], "voice_prewarm_stale")
        self.assertEqual(snapshot["voice_age_seconds"], 31.0)
        self.assertTrue(snapshot["voice_prewarm_stale"])
        self.assertEqual(snapshot["voice_prewarm_state"], "stale")
        self.assertEqual(snapshot["expires_at"], now - 90.0 + public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS)
        self.assertEqual(snapshot["ttl_remaining_seconds"], public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS - 90.0)
        self.assertEqual(snapshot["voice_expires_at"], 0.0)
        self.assertEqual(snapshot["voice_ttl_remaining_seconds"], 0.0)

    def test_memorial_warmup_snapshot_reports_voice_prewarm_duration(self) -> None:
        now = 1_000.0
        with (
            patch.object(public_memorials.time, "time", return_value=now),
            patch.object(
                public_memorials,
                "_MEMORIAL_LIVE_WARMUP_STATE",
                {
                    "manfred": {
                        "inflight": False,
                        "started_at": now - 100.0,
                        "completed_at": now - 90.0,
                        "errors": [],
                        "voice_contact_required": True,
                        "voice_contact_inflight": False,
                        "voice_contact_started_at": now - 84.0,
                        "voice_contact_completed_at": now - 4.0,
                        "voice_contact_errors": [],
                    }
                },
            ),
        ):
            snapshot = public_memorials._memorial_live_warmup_snapshot("manfred")

        self.assertEqual(snapshot["status"], "warm_recent")
        self.assertTrue(snapshot["voice_ready"])
        self.assertEqual(snapshot["voice_prewarm_state"], "ready")
        self.assertEqual(snapshot["voice_duration_seconds"], 80.0)
        self.assertEqual(snapshot["voice_completed_age_seconds"], 4.0)

    def test_memorial_runtime_readiness_reports_stale_voice_prewarm(self) -> None:
        with (
            patch.object(public_memorials, "_public_memorial_surface_probe", return_value={"slug": "manfred", "person_name": "Manfred"}),
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "status": "voice_prewarm_stale",
                    "warm": True,
                    "inflight": False,
                    "started_at": 0.0,
                    "completed_at": 1.0,
                    "errors": [],
                    "voice_ready": False,
                    "voice_inflight": True,
                    "voice_prewarm_stale": True,
                    "voice_prewarm_stale_in_seconds": 0.0,
                    "voice_started_at": 1.0,
                    "voice_age_seconds": 90.0,
                    "voice_completed_at": 0.0,
                    "voice_completed_age_seconds": 0.0,
                    "voice_errors": [],
                    "voice_required": True,
                },
            ),
            patch.object(public_memorials, "_load_memorial", return_value={"slug": "manfred"}),
            patch.object(public_memorials, "_load_voice_config", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_public_voice_profile_summary", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_tts_plugin_options", return_value=[{"tts_plugin_enabled": True}]),
            patch.object(public_memorials, "_resolve_server_tts_plugin", return_value=("unmixr", {"tts_plugin_enabled": True})),
            patch.object(public_memorials, "_load_private_profile", return_value={}),
            patch.object(public_memorials, "_resolve_memorial_voice_chat_model", return_value="gemini-2.5-flash"),
            patch.object(public_memorials, "_gemini_live_available", return_value=False),
        ):
            readiness = public_memorials._memorial_runtime_readiness("manfred")

        self.assertEqual(readiness["status"], "warming")
        self.assertEqual(readiness["interaction_mode"], "recovering_voice_prewarm")
        self.assertIn("voice_prewarm_stale", readiness["degraded_reasons"])
        self.assertNotIn("voice_prewarm_cold", readiness["degraded_reasons"])
        self.assertIn("restart_memorial_voice_prewarm", readiness["next_actions"])
        self.assertTrue(readiness["operator_attention_recommended"])
        self.assertTrue(readiness["operator_action_required"])

    def test_memorial_runtime_readiness_waits_when_voice_prewarm_is_already_inflight(self) -> None:
        with (
            patch.object(public_memorials, "_public_memorial_surface_probe", return_value={"slug": "manfred", "person_name": "Manfred"}),
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                return_value={
                    "status": "warming_voice",
                    "warm": True,
                    "inflight": False,
                    "started_at": 0.0,
                    "completed_at": 1.0,
                    "errors": [],
                    "voice_ready": False,
                    "voice_inflight": True,
                    "voice_prewarm_state": "warming",
                    "voice_prewarm_stale": False,
                    "voice_prewarm_stale_in_seconds": 120.0,
                    "voice_started_at": 1.0,
                    "voice_age_seconds": 30.0,
                    "voice_completed_at": 0.0,
                    "voice_completed_age_seconds": 0.0,
                    "voice_errors": [],
                    "voice_required": True,
                },
            ),
            patch.object(public_memorials, "_load_memorial", return_value={"slug": "manfred"}),
            patch.object(public_memorials, "_load_voice_config", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_public_voice_profile_summary", return_value={"voice_profile_ready": True}),
            patch.object(public_memorials, "_tts_plugin_options", return_value=[{"tts_plugin_enabled": True}]),
            patch.object(public_memorials, "_resolve_server_tts_plugin", return_value=("unmixr", {"tts_plugin_enabled": True})),
            patch.object(public_memorials, "_load_private_profile", return_value={}),
            patch.object(public_memorials, "_resolve_memorial_voice_chat_model", return_value="gemini-2.5-flash"),
            patch.object(public_memorials, "_gemini_live_available", return_value=False),
        ):
            readiness = public_memorials._memorial_runtime_readiness("manfred")

        self.assertEqual(readiness["status"], "warming")
        self.assertEqual(readiness["interaction_mode"], "warming")
        self.assertIn("voice_prewarm_warming", readiness["degraded_reasons"])
        self.assertNotIn("voice_prewarm_cold", readiness["degraded_reasons"])
        self.assertIn("wait_for_memorial_voice_prewarm", readiness["next_actions"])
        self.assertNotIn("run_memorial_voice_prewarm", readiness["next_actions"])
        self.assertTrue(readiness["operator_attention_recommended"])
        self.assertFalse(readiness["operator_action_required"])
        self.assertEqual(readiness["operator_action_state"], "waiting_on_runtime")
        self.assertEqual(readiness["operator_recheck_after_seconds"], 5)

    def test_public_memorial_warmup_status_exposes_readiness_fields(self) -> None:
        snapshot = {
            "status": "warm_recent",
            "warm": True,
            "inflight": False,
            "started_at": 0.0,
            "completed_at": 2.0,
            "warmup_age_seconds": 0.0,
            "warmup_completed_age_seconds": 0.0,
            "expires_at": 602.0,
            "ttl_remaining_seconds": 600.0,
            "errors": [],
            "voice_ready": True,
            "voice_inflight": False,
            "voice_prewarm_state": "ready",
            "voice_started_at": 0.0,
            "voice_age_seconds": 0.0,
            "voice_prewarm_stale": False,
            "voice_prewarm_stale_in_seconds": 0.0,
            "voice_completed_at": 2.0,
            "voice_duration_seconds": 0.0,
            "voice_completed_age_seconds": 0.0,
            "voice_expires_at": 602.0,
            "voice_ttl_remaining_seconds": 600.0,
            "voice_errors": [],
            "voice_required": True,
        }
        readiness = {
            "ready": True,
            "interaction_mode": "realtime_voice",
            "spoken_voice_ready": True,
            "realtime_ready": True,
            "readiness_checked_at": 2.0,
            "readiness_expires_at": 602.0,
            "readiness_ttl_remaining_seconds": 600.0,
            "readiness_ttl_state": "fresh",
            "readiness_refresh_recommended": False,
            "degraded_reasons": [],
            "next_actions": [],
            "operator_attention_recommended": False,
            "operator_action_required": False,
            "operator_action_state": "clear",
            "operator_recheck_after_seconds": 120,
        }
        with (
            patch.object(public_memorials, "_load_memorial", return_value={"slug": "manfred"}),
            patch.object(public_memorials, "_memorial_live_warmup_snapshot", return_value=snapshot),
            patch.object(public_memorials, "_memorial_runtime_readiness", return_value=readiness),
        ):
            response = public_memorials.public_memorial_warmup_status("manfred")

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["interaction_mode"], "realtime_voice")
        self.assertTrue(payload["spoken_voice_ready"])
        self.assertTrue(payload["realtime_ready"])
        self.assertEqual(payload["degraded_reasons"], [])
        self.assertEqual(payload["next_actions"], [])
        self.assertFalse(payload["operator_attention_recommended"])
        self.assertFalse(payload["operator_action_required"])
        self.assertEqual(payload["operator_action_state"], "clear")
        self.assertEqual(payload["operator_recheck_after_seconds"], 120)
        self.assertFalse(payload["voice_prewarm_stale"])
        self.assertEqual(payload["voice_prewarm_state"], "ready")
        self.assertEqual(payload["voice_prewarm_stale_in_seconds"], 0.0)
        self.assertEqual(payload["expires_at"], 602.0)
        self.assertEqual(payload["warmup_age_seconds"], 0.0)
        self.assertEqual(payload["warmup_completed_age_seconds"], 0.0)
        self.assertEqual(payload["ttl_remaining_seconds"], 600.0)
        self.assertEqual(payload["voice_expires_at"], 602.0)
        self.assertEqual(payload["voice_duration_seconds"], 0.0)
        self.assertEqual(payload["voice_ttl_remaining_seconds"], 600.0)
        self.assertEqual(
            payload["voice_recovery"],
            {"attempted": False, "scheduled": False, "reason": "", "at": 0.0, "age_seconds": 0.0},
        )
        self.assertEqual(payload["readiness_expires_at"], 602.0)
        self.assertEqual(payload["readiness_checked_at"], 2.0)
        self.assertEqual(payload["readiness_ttl_remaining_seconds"], 600.0)
        self.assertEqual(payload["readiness_ttl_state"], "fresh")
        self.assertFalse(payload["readiness_refresh_recommended"])

    def test_public_memorial_warmup_status_requeues_stale_voice_prewarm(self) -> None:
        stale_snapshot = {
            "status": "voice_prewarm_stale",
            "warm": True,
            "inflight": False,
            "started_at": 1.0,
            "completed_at": 2.0,
            "warmup_age_seconds": 0.0,
            "warmup_completed_age_seconds": 0.0,
            "expires_at": 602.0,
            "ttl_remaining_seconds": 500.0,
            "errors": [],
            "voice_ready": False,
            "voice_inflight": True,
            "voice_prewarm_state": "stale",
            "voice_started_at": 2.0,
            "voice_age_seconds": 90.0,
            "voice_prewarm_stale": True,
            "voice_prewarm_stale_in_seconds": 0.0,
            "voice_completed_at": 0.0,
            "voice_completed_age_seconds": 0.0,
            "voice_expires_at": 0.0,
            "voice_ttl_remaining_seconds": 0.0,
            "voice_errors": [],
            "voice_required": True,
        }
        refreshed_snapshot = dict(stale_snapshot)
        refreshed_snapshot.update(
            {
                "status": "warming_voice",
                "voice_inflight": True,
                "voice_prewarm_state": "warming",
                "voice_started_at": 20.0,
                "voice_age_seconds": 0.1,
                "voice_prewarm_stale": False,
                "voice_prewarm_stale_in_seconds": 59.9,
                "voice_duration_seconds": 0.0,
                "warmup_age_seconds": 0.0,
                "warmup_completed_age_seconds": 18.1,
            }
        )
        readiness = {
            "ready": False,
            "interaction_mode": "warming",
            "spoken_voice_ready": False,
            "realtime_ready": False,
            "readiness_expires_at": 0.0,
            "readiness_ttl_remaining_seconds": 0.0,
            "degraded_reasons": ["voice_prewarm_cold"],
            "next_actions": ["run_memorial_voice_prewarm"],
            "operator_action_required": True,
        }
        with (
            patch.object(public_memorials, "_load_memorial", return_value={"slug": "manfred"}),
            patch.object(
                public_memorials,
                "_memorial_live_warmup_snapshot",
                side_effect=[stale_snapshot, refreshed_snapshot],
            ),
            patch.object(public_memorials, "_schedule_missing_memorial_voice_prewarm", return_value=True) as schedule_voice,
            patch.object(public_memorials, "_memorial_runtime_readiness", return_value=readiness),
        ):
            response = public_memorials.public_memorial_warmup_status("manfred")

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        schedule_voice.assert_called_once_with("manfred")
        self.assertEqual(payload["status"], "warming_voice")
        self.assertEqual(payload["warmup_age_seconds"], 0.0)
        self.assertEqual(payload["warmup_completed_age_seconds"], 18.1)
        self.assertFalse(payload["voice_prewarm_stale"])
        self.assertEqual(payload["voice_prewarm_state"], "warming")
        self.assertEqual(payload["voice_prewarm_stale_in_seconds"], 59.9)
        self.assertEqual(payload["voice_started_at"], 20.0)
        self.assertTrue(payload["voice_recovery"]["attempted"])
        self.assertTrue(payload["voice_recovery"]["scheduled"])
        self.assertEqual(payload["voice_recovery"]["reason"], "voice_prewarm_stale")
        self.assertGreater(payload["voice_recovery"]["at"], 0.0)
        self.assertGreaterEqual(payload["voice_recovery"]["age_seconds"], 0.0)

    def test_recover_stale_memorial_voice_prewarm_for_status_invalidates_readiness_cache_on_requeue(self) -> None:
        stale_snapshot = {
            "warm": True,
            "voice_required": True,
            "voice_prewarm_stale": True,
        }
        refreshed_snapshot = {
            "status": "warming_voice",
            "warm": True,
            "inflight": False,
            "started_at": 1.0,
            "completed_at": 2.0,
            "voice_ready": True,
            "voice_inflight": True,
            "voice_prewarm_state": "warming",
            "voice_required": True,
            "voice_prewarm_stale": False,
        }
        with (
            patch.object(public_memorials, "_MEMORIAL_LIVE_WARMUP_STATE", {"manfred": {}}),
            patch.object(public_memorials, "_schedule_missing_memorial_voice_prewarm", return_value=True),
            patch.object(public_memorials, "_memorial_live_warmup_snapshot", return_value=refreshed_snapshot),
            patch.object(public_memorials, "_memorial_runtime_readiness_cache_invalidate") as invalidate,
        ):
            snapshot, recovery = public_memorials._recover_stale_memorial_voice_prewarm_for_status("manfred", stale_snapshot)

        self.assertEqual(snapshot["status"], "warming_voice")
        self.assertTrue(recovery["attempted"])
        self.assertTrue(recovery["scheduled"])
        self.assertEqual(recovery["reason"], "voice_prewarm_stale")
        invalidate.assert_called_once_with("manfred")

    def test_recover_stale_memorial_voice_prewarm_for_status_invalidates_readiness_cache_on_schedule_failure(self) -> None:
        stale_snapshot = {
            "warm": True,
            "voice_required": True,
            "voice_prewarm_stale": True,
        }
        with (
            patch.object(public_memorials, "_MEMORIAL_LIVE_WARMUP_STATE", {"manfred": {}}),
            patch.object(public_memorials, "_schedule_missing_memorial_voice_prewarm", return_value=False),
            patch.object(public_memorials, "_memorial_runtime_readiness_cache_invalidate") as invalidate,
        ):
            snapshot, recovery = public_memorials._recover_stale_memorial_voice_prewarm_for_status("manfred", stale_snapshot)

        self.assertEqual(snapshot, stale_snapshot)
        self.assertTrue(recovery["attempted"])
        self.assertFalse(recovery["scheduled"])
        self.assertEqual(recovery["reason"], "voice_prewarm_stale")
        invalidate.assert_called_once_with("manfred")

    def test_public_memorial_readiness_returns_503_when_not_ready(self) -> None:
        with patch.object(
            public_memorials,
            "_memorial_runtime_readiness",
            return_value={
                "slug": "manfred",
                "ready": False,
                "status": "warming",
                "degraded_reasons": ["warmup_cold"],
                "next_actions": ["run_memorial_warmup"],
                "operator_action_required": True,
            },
        ):
            response = public_memorials.public_memorial_readiness("manfred")

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.body)
        self.assertEqual(payload["status"], "warming")
        self.assertEqual(payload["next_actions"], ["run_memorial_warmup"])
        self.assertTrue(payload["operator_action_required"])

    def test_public_memorial_operator_status_includes_runtime_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "memorial_operator_status.json"
            status_path.write_text(json.dumps({"headline": "ok"}), encoding="utf-8")
            phrase_bank_path = Path(tmpdir) / "memorial_phrase_bank.json"
            phrase_bank_path.write_text("{}", encoding="utf-8")
            request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
            readiness = {"ready": False, "status": "warming", "degraded_reasons": ["voice_prewarm_cold"]}
            with (
                patch.object(public_memorial_operator, "_require_public_memorial_operator_surface_enabled", return_value=None),
                patch.object(public_memorial_operator, "_load_memorial", return_value={"slug": "manfred"}),
                patch.object(public_memorial_operator, "_require_public_memorial_write_access", return_value=None),
                patch.object(public_memorial_operator, "_memorial_operator_status_path", return_value=status_path),
                patch.object(public_memorial_operator, "_memorial_phrase_bank_path", return_value=phrase_bank_path),
                patch.object(public_memorial_operator.shared_memorials, "_memorial_runtime_readiness", return_value=readiness),
            ):
                response = public_memorial_operator.public_memorial_operator_status("manfred", request)

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["readiness"], readiness)
        self.assertEqual(payload["status_artifact"], status_path.name)
        self.assertIn("refresh_operator_status", payload["actions"])

    def test_public_memorial_operator_status_has_complete_readiness_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "memorial_operator_status.json"
            status_path.write_text(json.dumps({"headline": "ok"}), encoding="utf-8")
            phrase_bank_path = Path(tmpdir) / "memorial_phrase_bank.json"
            phrase_bank_path.write_text("{}", encoding="utf-8")
            request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
            with (
                patch.object(public_memorial_operator, "_require_public_memorial_operator_surface_enabled", return_value=None),
                patch.object(public_memorial_operator, "_load_memorial", return_value={"slug": "manfred"}),
                patch.object(public_memorial_operator, "_require_public_memorial_write_access", return_value=None),
                patch.object(public_memorial_operator, "_memorial_operator_status_path", return_value=status_path),
                patch.object(public_memorial_operator, "_memorial_phrase_bank_path", return_value=phrase_bank_path),
                patch.object(
                    public_memorial_operator.shared_memorials,
                    "_memorial_runtime_readiness",
                    side_effect=RuntimeError("readiness backend unavailable"),
                ),
            ):
                response = public_memorial_operator.public_memorial_operator_status("manfred", request)

        payload = json.loads(response.body)
        readiness = payload["readiness"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(readiness["status"], "degraded")
        self.assertEqual(readiness["interaction_mode"], "unavailable")
        self.assertFalse(readiness["ready"])
        self.assertTrue(readiness["operator_attention_recommended"])
        self.assertTrue(readiness["operator_action_required"])
        self.assertIn("readiness_checked_at", readiness)
        self.assertEqual(readiness["degraded_reasons"], ["runtime_readiness_probe_failed"])
        self.assertEqual(readiness["next_actions"], ["inspect_memorial_runtime_readiness"])
        self.assertIn("warmup", readiness)
        self.assertIn("voice_prewarm_stale", readiness["warmup"])
        self.assertIn("voice_duration_seconds", readiness["warmup"])
        self.assertIn("voice_recovery", readiness["warmup"])
        self.assertIn("readiness_ttl_remaining_seconds", readiness)
        self.assertIn("readiness_ttl_state", readiness)
        self.assertIn("readiness_refresh_recommended", readiness)
        self.assertIn("ttl_remaining_seconds", readiness["warmup"])
        self.assertIn("voice_ttl_remaining_seconds", readiness["warmup"])
        self.assertIn("voice", readiness)
        self.assertIn("models", readiness)

    def test_memorial_gold_template_surfaces_runtime_recovery_actions(self) -> None:
        template_path = Path(public_memorial_operator.__file__).resolve().parents[2] / "templates" / "admin_memorial_gold.html"
        template = template_path.read_text(encoding="utf-8")

        self.assertIn("operator_status.readiness.next_actions", template)
        self.assertIn("operator_status.readiness.operator_attention_recommended", template)
        self.assertIn("operator_status.readiness.interaction_mode", template)
        self.assertIn("operator_status.readiness.operator_action_required", template)
        self.assertIn("operator_status.readiness.operator_action_state", template)
        self.assertIn("operator_status.readiness.operator_recheck_after_seconds", template)
        self.assertIn("operator_status.readiness.degraded_reasons", template)
        self.assertIn("operator_status.readiness.spoken_voice_ready", template)
        self.assertIn("operator_status.readiness.realtime_ready", template)
        self.assertIn("operator_status.readiness.readiness_checked_at", template)
        self.assertIn("operator_status.readiness.readiness_ttl_remaining_seconds", template)
        self.assertIn("operator_status.readiness.readiness_ttl_state", template)
        self.assertIn("operator_status.readiness.readiness_refresh_recommended", template)
        self.assertIn("operator_status.readiness.warmup.warmup_age_seconds", template)
        self.assertIn("operator_status.readiness.warmup.warmup_completed_age_seconds", template)
        self.assertIn("operator_status.readiness.warmup.voice_inflight", template)
        self.assertIn("operator_status.readiness.warmup.voice_prewarm_state", template)
        self.assertIn("operator_status.readiness.warmup.voice_started_at", template)
        self.assertIn("operator_status.readiness.warmup.voice_age_seconds", template)
        self.assertIn("operator_status.readiness.warmup.voice_prewarm_stale", template)
        self.assertIn("operator_status.readiness.warmup.voice_prewarm_stale_in_seconds", template)
        self.assertIn("operator_status.readiness.warmup.voice_duration_seconds", template)
        self.assertIn("operator_status.readiness.warmup.voice_completed_age_seconds", template)
        self.assertIn("operator_status.readiness.warmup.voice_ttl_remaining_seconds", template)
        self.assertIn("operator_status.readiness.warmup.voice_recovery.attempted", template)
        self.assertIn("operator_status.readiness.warmup.voice_recovery.scheduled", template)
        self.assertIn("operator_status.readiness.warmup.voice_recovery.reason", template)
        self.assertIn("operator_status.readiness.warmup.voice_recovery.age_seconds", template)

    def test_public_memorial_browser_warmup_refreshes_before_readiness_expires(self) -> None:
        source = Path(public_memorials.__file__).read_text(encoding="utf-8")

        self.assertIn("readiness_ttl_remaining_seconds", source)
        self.assertIn('requestMemorialWarmup("ttl_refresh")', source)
        self.assertIn('requestMemorialWarmup("voice_stale_retry")', source)
        self.assertIn("scheduleMemorialReadyRefresh", source)
        self.assertIn("Math.max(5, ttl - 45)", source)
        self.assertIn("memorialWarmupPollDelayMs", source)
        self.assertIn("memorialLastWarmupStatus", source)
        self.assertIn("memorialLastWarmupStatus = payload;", source)
        self.assertIn("const retryMs = memorialWarmupPollDelayMs(memorialLastWarmupStatus);", source)
        self.assertIn("operator_recheck_after_seconds", source)
        self.assertIn("Math.max(700, Math.min(5000", source)
        self.assertNotIn("window.setTimeout(resolve, 900)", source)
        self.assertIn("memorialWarmupPromise = null;", source)
        self.assertIn("memorialReadyNeedsRefresh", source)
        self.assertIn("recheckMemorialReadinessOnReturn", source)
        self.assertIn('document.addEventListener("visibilitychange"', source)
        self.assertIn('window.addEventListener("focus"', source)
        self.assertIn('"window_focus"', source)

    def test_public_memorial_route_compiles_without_syntax_warnings(self) -> None:
        source_path = Path(public_memorials.__file__).resolve()
        source = source_path.read_text(encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SyntaxWarning)
            compile(source, str(source_path), "exec")
        syntax_warnings = [item for item in caught if issubclass(item.category, SyntaxWarning)]
        self.assertEqual(syntax_warnings, [])

    def test_safe_tts_plugin_id_normalizes_disabled_openvoice(self) -> None:
        self.assertEqual(public_memorials._safe_tts_plugin_id("openvoice_local"), public_memorials._TTS_PLUGIN_DEFAULT_ID)
        self.assertEqual(public_memorials._safe_tts_plugin_id("piper_local_fast"), public_memorials._TTS_PLUGIN_DEFAULT_ID)
        self.assertEqual(public_memorials._safe_tts_plugin_id("  "), "")

    def test_tts_plugin_options_do_not_reintroduce_openvoice(self) -> None:
        options = public_memorials._tts_plugin_options(payload={}, voice_profile_ready=False)
        plugin_ids = {str(option.get("tts_plugin") or "") for option in options}
        self.assertNotIn(public_memorials.OPENVOICE_TTS_PLUGIN_ID, plugin_ids)
        self.assertNotIn(public_memorials.PIPER_FAST_TTS_PLUGIN_ID, plugin_ids)

    def test_openvoice_tts_pipeline_files_are_removed(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        forbidden_paths = [
            repo_root / "Dockerfile.openvoice",
            repo_root / "requirements-openvoice.txt",
            repo_root / "app" / "openvoice_app.py",
            repo_root / "app" / "services" / "openvoice_runtime.py",
            repo_root / "scripts" / "optimize_memorial_openvoice_clone.py",
            repo_root / "scripts" / "compare_memorial_unmixr_clones.py",
        ]
        self.assertEqual([str(path) for path in forbidden_paths if path.exists()], [])

    def test_disabled_openvoice_backed_tts_never_becomes_fallback_selection(self) -> None:
        options = [
            {"tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID, "tts_plugin_enabled": False},
            {"tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID, "tts_plugin_enabled": False},
        ]

        selected_plugin, selected_option = public_memorials._resolve_tts_plugin(
            payload={"tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID},
            options=options,
        )

        self.assertEqual(selected_plugin, public_memorials.UNMIXR_TTS_PLUGIN_ID)
        self.assertEqual(selected_option["tts_plugin"], public_memorials.UNMIXR_TTS_PLUGIN_ID)
        self.assertFalse(selected_option["tts_plugin_enabled"])

    def test_server_tts_never_falls_back_to_disabled_openvoice_backed_option(self) -> None:
        options = [
            {"tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID, "tts_plugin_enabled": False},
            {"tts_plugin": public_memorials._BROWSER_SPEECH_TTS_PLUGIN_ID, "tts_plugin_enabled": True},
        ]

        selected_plugin, selected_option = public_memorials._resolve_server_tts_plugin(
            payload={"tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID},
            options=options,
        )

        self.assertEqual(selected_plugin, public_memorials.UNMIXR_TTS_PLUGIN_ID)
        self.assertEqual(selected_option["tts_plugin"], public_memorials.UNMIXR_TTS_PLUGIN_ID)
        self.assertFalse(selected_option["tts_plugin_enabled"])


if __name__ == "__main__":
    unittest.main()
