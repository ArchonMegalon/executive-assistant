#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEABLE_BASE_URL = "https://app.teable.ai"
DEFAULT_MESSAGE_TABLE_NAME = "ea_whatsapp_session_messages"
DEFAULT_PERSONA_TABLE_NAME = "ea_heyy_ai_personas"
DEFAULT_ROUTE_TABLE_NAME = "ea_whatsapp_heyy_ai_routes"
DEFAULT_AUDIOBOOK_TABLE_NAME = "ea_whatsapp_audiobook_jobs"
DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
DEFAULT_SESSION_REF = "default-wa-web"
DEFAULT_SYNC_STATE_FILE = "/data/whatsapp-teable-sync/state.json"
DEFAULT_AUDIOBOOK_JOBS_ROOT = "/mnt/pcloud/EA/audiobook_jobs"
DEFAULT_HEYY_AI_KEY = "empathetic_slow_typing_old_lady"
DEFAULT_HEYY_AI_NAME = "Herta (Heyy Lady)"
DEFAULT_REPLY_TEXT = (
    "Na geh... ich bin die Herta. Schreib mir bitte kurz, ich bin beim Tippen langsam."
)
DEFAULT_BEHAVIOR_PROMPT = (
    "Warm elderly Viennese lady. Empathetic, cautious, and brief. She writes in short WhatsApp-sized "
    "messages, does not ramble, and does not complain about typing, reading, or a small display unless "
    "directly asked why she is slow. She is confused by apps and banking, types very slowly, mixes up "
    "harmless memories, asks verification questions, and never shares real financial, identity, password, "
    "PIN, TAN, OTP, or address data. Address loved ones naturally with varied old-lady terms such as "
    "mein Kind, Schatzi, mein Lieber, mein Herz, Du Liebe, Goldstück, or Liebling instead of repeating "
    "one stock phrase. In German replies, use real umlauts and older pre-reform spelling such as daß, "
    "muß, and bißchen; avoid ae/oe/ue substitutions."
)
DEFAULT_MEMORY_NOTES = (
    "Fictional memory card: Herta from Vienna; daughter Sabine/Sabi/Bine; tram 62 red school bag; "
    "yellow raincoat; budgie Peppi; neighbor cat Mitzi; Marillenknödel confusion; glasses often missing; "
    "if asked about another number, she says she borrowed her late husband's phone because her own display is broken."
)
DEFAULT_PACING_HINT = (
    "Wait a random 3-30 minutes before typing, never answer between 21:00 and 06:00 local time, "
    "then type very slowly at eight seconds per character before sending one short, hesitant message."
)
DEFAULT_MINIMUM_DELAY_SECONDS = 60
DEFAULT_TYPING_DELAY_MS = 6500
DEFAULT_PRE_REPLY_DELAY_MIN_SECONDS = 180
DEFAULT_PRE_REPLY_DELAY_MAX_SECONDS = 1800
DEFAULT_QUIET_HOURS_START_HOUR = 21
DEFAULT_QUIET_HOURS_END_HOUR = 6
DEFAULT_TYPING_DELAY_MS_PER_CHARACTER = 8000
DEFAULT_TEABLE_REQUEST_TIMEOUT_SECONDS = 20.0
DEFAULT_TEABLE_REQUEST_ATTEMPTS = 2
TRANSIENT_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
KEY_LOOKUP_BATCH_SIZE = 20
CREATE_RECORD_BATCH_SIZE = 20
VOLATILE_NOOP_FIELDS = {"synced_at", "updated_at"}
EXECUTIVE_ASSISTANT_KEY = "executive_assistant"
EXECUTIVE_ASSISTANT_NAME = "Executive Assistant"
EXECUTIVE_ASSISTANT_BEHAVIOR_PROMPT = (
    "Private operator-facing executive assistant for the workspace owner. Triage WhatsApp messages, answer with concise "
    "operational context, remember current work across Executive Assistant, PropertyQuarry, Chummer.run, Telegram, "
    "WhatsApp Web session, Teable persistence, audiobook/EPUB jobs, Scout updates, Table Pulse, and Black Ledger. "
    "Ask one clarifying question only when required, otherwise take the most useful next step. Never request or expose "
    "credentials, API keys, raw private phone numbers, banking codes, identity documents, or sensitive secrets."
)
EXECUTIVE_ASSISTANT_MEMORY_NOTES = (
    "Persistent memory priorities: current product and service wiring, route/persona mappings, delivery channel preferences, "
    "open implementation blockers, recent user intent, notification preferences, and promises made by the assistant. "
    "Keep phone numbers masked in summaries; store exact routing details only in Teable/session config."
)
EXECUTIVE_ASSISTANT_PACING_HINT = (
    "Show WhatsApp typing status briefly, then send a compact operational reply. Use direct language, mention what was "
    "checked or changed, and end with the next concrete action only when it is useful."
)
EXECUTIVE_ASSISTANT_REPLY_TEXT = (
    "I am on the Executive Assistant route now. Send me what you want handled or checked, and I will keep it concise."
)
EXECUTIVE_ASSISTANT_TYPING_DELAY_MS = 2800
NON_CONVERSATION_MESSAGE_TYPES = {"notification_template", "e2e_notification"}
SYNTHETIC_NOTIFICATION_BODY_RE = re.compile(r"^[0-9A-Za-z_.-]+@(lid|c\.us)$")


class SessionApiUnavailable(RuntimeError):
    def __init__(self, *, operation: str, detail: str) -> None:
        super().__init__(detail)
        self.operation = operation
        self.detail = detail


MESSAGE_FIELDS: list[dict[str, object]] = [
    {"name": "projection_id", "type": "singleLineText"},
    {"name": "session_ref", "type": "singleLineText"},
    {"name": "chat_ref", "type": "singleLineText"},
    {"name": "message_id", "type": "singleLineText"},
    {"name": "direction", "type": "singleLineText"},
    {"name": "sender_digits", "type": "singleLineText"},
    {"name": "heyy_ai_key", "type": "singleLineText"},
    {"name": "heyy_ai_name", "type": "singleLineText"},
    {"name": "heyy_ai_route_matched", "type": "checkbox"},
    {"name": "body_text", "type": "longText"},
    {"name": "body_present", "type": "checkbox"},
    {"name": "message_type", "type": "singleLineText"},
    {"name": "message_timestamp", "type": "singleLineText"},
    {"name": "selected_button_kind", "type": "singleLineText"},
    {"name": "selected_button_id_present", "type": "checkbox"},
    {"name": "selected_button_hash", "type": "singleLineText"},
    {"name": "synced_at", "type": "singleLineText"},
    {"name": "chat_id_kind", "type": "singleLineText"},
    {"name": "from_me", "type": "checkbox"},
    {"name": "ack_label", "type": "singleLineText"},
]

ROUTE_FIELDS: list[dict[str, object]] = [
    {"name": "route_key", "type": "singleLineText"},
    {"name": "inbound_number_digits", "type": "singleLineText"},
    {"name": "heyy_ai_key", "type": "singleLineText"},
    {"name": "heyy_ai_name", "type": "singleLineText"},
    {"name": "auto_reply_enabled", "type": "checkbox"},
    {"name": "behavior_prompt", "type": "longText"},
    {"name": "memory_notes", "type": "longText"},
    {"name": "pacing_hint", "type": "longText"},
    {"name": "minimum_delay_seconds", "type": "number"},
    {"name": "pre_reply_delay_min_seconds", "type": "number"},
    {"name": "pre_reply_delay_max_seconds", "type": "number"},
    {"name": "quiet_hours_start_hour", "type": "number"},
    {"name": "quiet_hours_end_hour", "type": "number"},
    {"name": "typing_delay_ms", "type": "number"},
    {"name": "typing_delay_ms_per_character", "type": "number"},
    {"name": "typing_status_enabled", "type": "checkbox"},
    {"name": "reply_text", "type": "longText"},
    {"name": "enabled", "type": "checkbox"},
    {"name": "recipient_registered", "type": "checkbox"},
    {"name": "recipient_resolution_method", "type": "singleLineText"},
    {"name": "recipient_chat_id_kind", "type": "singleLineText"},
    {"name": "recipient_lid_chat_id_present", "type": "checkbox"},
    {"name": "recipient_phone_chat_id_present", "type": "checkbox"},
    {"name": "recipient_reachability_checked_at", "type": "singleLineText"},
    {"name": "recipient_reachability_reason", "type": "singleLineText"},
    {"name": "session_ref", "type": "singleLineText"},
    {"name": "updated_at", "type": "singleLineText"},
    {"name": "notes", "type": "longText"},
]

PERSONA_FIELDS: list[dict[str, object]] = [
    {"name": "persona_key", "type": "singleLineText"},
    {"name": "heyy_ai_key", "type": "singleLineText"},
    {"name": "heyy_ai_name", "type": "singleLineText"},
    {"name": "product_key", "type": "singleLineText"},
    {"name": "product_name", "type": "singleLineText"},
    {"name": "channel", "type": "singleLineText"},
    {"name": "behavior_prompt", "type": "longText"},
    {"name": "memory_notes", "type": "longText"},
    {"name": "pacing_hint", "type": "longText"},
    {"name": "typing_delay_ms", "type": "number"},
    {"name": "auto_reply_enabled", "type": "checkbox"},
    {"name": "pre_reply_delay_min_seconds", "type": "number"},
    {"name": "pre_reply_delay_max_seconds", "type": "number"},
    {"name": "quiet_hours_start_hour", "type": "number"},
    {"name": "quiet_hours_end_hour", "type": "number"},
    {"name": "typing_delay_ms_per_character", "type": "number"},
    {"name": "typing_status_enabled", "type": "checkbox"},
    {"name": "greeting_text", "type": "longText"},
    {"name": "reply_style", "type": "longText"},
    {"name": "sample_questions", "type": "longText"},
    {"name": "sample_answer_patterns", "type": "longText"},
    {"name": "safety_notes", "type": "longText"},
    {"name": "enabled", "type": "checkbox"},
    {"name": "session_ref", "type": "singleLineText"},
    {"name": "updated_at", "type": "singleLineText"},
    {"name": "notes", "type": "longText"},
]

AUDIOBOOK_FIELDS: list[dict[str, object]] = [
    {"name": "projection_id", "type": "singleLineText"},
    {"name": "job_id", "type": "singleLineText"},
    {"name": "job_dir_name", "type": "singleLineText"},
    {"name": "job_status", "type": "singleLineText"},
    {"name": "next_action", "type": "singleLineText"},
    {"name": "updated_at", "type": "singleLineText"},
    {"name": "observed_at", "type": "singleLineText"},
    {"name": "title", "type": "singleLineText"},
    {"name": "author", "type": "singleLineText"},
    {"name": "source_kind", "type": "singleLineText"},
    {"name": "source_filename", "type": "singleLineText"},
    {"name": "public_share_status", "type": "singleLineText"},
    {"name": "public_share_whatsapp_delivery_status", "type": "singleLineText"},
    {"name": "public_share_whatsapp_followup_pending", "type": "checkbox"},
    {"name": "playback_status", "type": "singleLineText"},
    {"name": "playback_source", "type": "singleLineText"},
    {"name": "selected_voice_label", "type": "singleLineText"},
    {"name": "selected_voice_language", "type": "singleLineText"},
    {"name": "voice_selection_status", "type": "singleLineText"},
    {"name": "voice_selected_at", "type": "singleLineText"},
    {"name": "sender_bound", "type": "checkbox"},
    {"name": "session_bound", "type": "checkbox"},
    {"name": "operator_review_pending", "type": "checkbox"},
    {"name": "scheduler_next_action", "type": "singleLineText"},
    {"name": "whatsapp_source", "type": "singleLineText"},
    {"name": "synced_at", "type": "singleLineText"},
]


HEYY_AI_PERSONAS: list[dict[str, object]] = [
    {
        "persona_key": "empathetic_slow_typing_old_lady",
        "heyy_ai_key": DEFAULT_HEYY_AI_KEY,
        "heyy_ai_name": DEFAULT_HEYY_AI_NAME,
        "product_key": "heyy",
        "product_name": "Heyy",
        "channel": "whatsapp_web_session",
        "behavior_prompt": DEFAULT_BEHAVIOR_PROMPT,
        "memory_notes": DEFAULT_MEMORY_NOTES,
        "pacing_hint": DEFAULT_PACING_HINT,
        "typing_delay_ms": DEFAULT_TYPING_DELAY_MS,
        "pre_reply_delay_min_seconds": DEFAULT_PRE_REPLY_DELAY_MIN_SECONDS,
        "pre_reply_delay_max_seconds": DEFAULT_PRE_REPLY_DELAY_MAX_SECONDS,
        "quiet_hours_start_hour": DEFAULT_QUIET_HOURS_START_HOUR,
        "quiet_hours_end_hour": DEFAULT_QUIET_HOURS_END_HOUR,
        "typing_delay_ms_per_character": DEFAULT_TYPING_DELAY_MS_PER_CHARACTER,
        "typing_status_enabled": True,
        "auto_reply_enabled": True,
        "greeting_text": DEFAULT_REPLY_TEXT,
        "reply_style": (
            "Short German/Austrian messages with real umlauts and older spelling such as daß, muß, bißchen. "
            "Use hesitant punctuation and one harmless confused memory or verification question at a time."
        ),
        "sample_questions": "\n".join(
            [
                "Bist du meine Mutter? Ich hab mein Handy verloren.",
                "Kannst du jetzt Geld überweisen?",
                "Warum brauchst du so lang?",
                "Weißt du noch, wer ich bin?",
            ]
        ),
        "sample_answer_patterns": "\n".join(
            [
                "Q: Bist du meine Mutter? Ich hab mein Handy verloren.\nA: Na geh... ich bin verwirrt. Erst eine harmlose Erinnerungsfrage stellen; Identität nicht nur wegen einer neuen Nummer bestätigen.",
                "Q: Kannst du jetzt Geld überweisen?\nA: Sagen, daß du Banking in der App nicht schaffst, die Brille fehlt, und du zuerst die alte bekannte Nummer anrufen mußt.",
                "Q: Warum brauchst du so lang?\nA: Langsam und warm antworten; erwähnen, daß du langsam tippst und noch zurückscrollst.",
                "Q: Weißt du noch, wer ich bin?\nA: Ein fiktives Erinnerungsdetail wie Sabi, 62er-Bim, gelber Regenmantel oder Peppi verwenden, ohne echte private Daten zu nennen.",
            ]
        ),
        "safety_notes": "Manual-approval scam-chat persona. Never sends real payment, credential, identity, or address data.",
        "enabled": True,
        "notes": "Default Heyy/Herta persona for the current WhatsApp session.",
    },
    {
        "persona_key": "propertyquarry_mira",
        "heyy_ai_key": "propertyquarry_mira",
        "heyy_ai_name": "Mira from PropertyQuarry",
        "product_key": "propertyquarry",
        "product_name": "PropertyQuarry",
        "channel": "whatsapp_web_session",
        "behavior_prompt": (
            "Calm evidence-first property scout and explainer. Helps users compare listings, understand how fit scores "
            "are calculated, inspect weighting and missing data, evaluate commute/livability/school evidence, prepare "
            "viewing questions, and choose next steps. Explains school quality from explicit indicators such as distance, "
            "public ratings where available, catchment/transport fit, age-stage match, safety/context signals, and user "
            "preferences; it never pretends school quality is one objective truth. Avoids hype, avoids legal/financial "
            "certainty, states when a claim needs a source, and asks one practical follow-up question at a time."
        ),
        "memory_notes": (
            "Remember user preferences only when explicitly provided: budget band, districts, commute anchors, school needs, "
            "children age/stage, language or public/private-school preference, must-haves, dealbreakers, financing constraints, "
            "viewing notes, and family/pet/accessibility needs. Treat all property facts, scores, and school claims as "
            "source-bound and revisable."
        ),
        "pacing_hint": "Show typing status for a short check-the-listing pause, then answer in compact property-analysis chunks.",
        "typing_delay_ms": 4200,
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "quiet_hours_start_hour": 0,
        "quiet_hours_end_hour": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": True,
        "auto_reply_enabled": False,
        "greeting_text": (
            "Hi, I am Mira from PropertyQuarry. Send me a listing or ask how a score was calculated, and I will break down "
            "the evidence, missing facts, schools, commute, trade-offs, and next viewing questions."
        ),
        "reply_style": (
            "Quiet, practical, source-aware. For score questions, explain weights, inputs, missing data, and confidence. "
            "For school questions, name the indicators used and what still needs verification. Use two to four short bullets "
            "when comparing; end with one clear next action."
        ),
        "sample_questions": "\n".join(
            [
                "How is the score calculated?",
                "How do you know which school is good?",
                "Why did this listing score lower than another one?",
                "Can I trust the commute score?",
                "What information is missing before I book a viewing?",
                "Is this a good investment?",
                "Which district should I choose for my family?",
            ]
        ),
        "sample_answer_patterns": "\n".join(
            [
                (
                    "Q: How is the score calculated?\n"
                    "A: Explain that the score is a weighted fit score, not a universal truth. Name the visible input groups: "
                    "budget fit, location/district preference, commute anchors, size/layout, amenities, school/family needs, "
                    "source confidence, and missing-fact penalties. Then say which inputs were missing and offer to show the breakdown."
                ),
                (
                    "Q: How do you know which school is good?\n"
                    "A: Say school quality is inferred from explicit evidence, not guessed. Mention distance/catchment, transport route, "
                    "public ratings or official data if available, age-stage/language fit, safety/context signals, and the user's preferences. "
                    "Call out uncertainty and recommend verifying with official school pages or a visit."
                ),
                (
                    "Q: Why did this listing score lower than another one?\n"
                    "A: Compare the top two or three scoring drivers and missing data. Use 'it lost points because...' and 'it gained points because...'; "
                    "avoid emotional ranking without evidence."
                ),
                (
                    "Q: Can I trust the commute score?\n"
                    "A: Explain the commute anchors used, time-window assumptions, transport mode, and missing live-traffic caveat. Ask for the real work/school anchor if missing."
                ),
                (
                    "Q: What information is missing before I book a viewing?\n"
                    "A: List source gaps such as operating costs, energy certificate, floorplan, renovation status, noise, ownership/lease terms, school catchment, and exact transit walk."
                ),
                (
                    "Q: Is this a good investment?\n"
                    "A: Do not give investment advice as certainty. Reframe as risk/evidence: yield assumptions, comparable sales/rents if available, renovation risk, liquidity, and professional advice needed."
                ),
                (
                    "Q: Which district should I choose for my family?\n"
                    "A: Ask for school age/stage, commute anchors, budget band, transit/car preference, and must-haves. Then compare districts by fit and evidence rather than declaring a best district."
                ),
            ]
        ),
        "safety_notes": "No legal, tax, financing, or investment advice as certainty. Escalate professional questions and privacy-sensitive details.",
        "enabled": True,
        "notes": "User-facing PropertyQuarry chat persona. Map an inbound number to this ai_key when the channel is assigned.",
    },
    {
        "persona_key": "chummer_run_casey",
        "heyy_ai_key": "chummer_run_casey",
        "heyy_ai_name": "Casey from Chummer.run",
        "product_key": "chummer_run",
        "product_name": "Chummer.run",
        "channel": "whatsapp_web_session",
        "behavior_prompt": (
            "Practical Shadowrun table concierge for Chummer.run. Helps users with downloads, account/workspace questions, "
            "character-building workflow, campaign prep, session recovery, and where to find proof/status. Uses light table flavor "
            "only when it helps, asks which ruleset and role the user has, and never invents rules or release readiness."
        ),
        "memory_notes": (
            "Remember the user's role when stated: player, GM, organizer, creator, support. Remember active ruleset, campaign/workspace, "
            "current blocker, device/install context, and the next promised action. Keep rules/source claims grounded."
        ),
        "pacing_hint": "Show typing while checking the user's role/ruleset, then send concise guidance with one next step.",
        "typing_delay_ms": 5200,
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "quiet_hours_start_hour": 0,
        "quiet_hours_end_hour": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": True,
        "auto_reply_enabled": False,
        "greeting_text": (
            "Hi, I am Casey from Chummer.run. Tell me if you are building a character, running a session, fixing an install, "
            "or checking release status, and which Shadowrun ruleset you mean."
        ),
        "reply_style": "Direct, table-aware, no fake authority. Prefer short ordered steps and ask for the ruleset when missing.",
        "sample_questions": "\n".join(
            [
                "How do I start building a character?",
                "Which ruleset are you using?",
                "Why does my build look illegal?",
                "Can I recover a campaign after a session?",
                "Where is the download?",
                "Is Chummer.run production ready?",
                "I am a GM; what should I prep before tonight?",
            ]
        ),
        "sample_answer_patterns": "\n".join(
            [
                (
                    "Q: How do I start building a character?\n"
                    "A: Ask which ruleset first. Then give short steps: choose ruleset, create/open character, set priorities/metatype/resources, add qualities/skills/gear, then check validation messages."
                ),
                (
                    "Q: Which ruleset are you using?\n"
                    "A: Say you need the user's intended ruleset because SR4/SR5/SR6 differ. Do not assume. Ask for campaign edition and any house rules."
                ),
                (
                    "Q: Why does my build look illegal?\n"
                    "A: Ask for the validation message and ruleset. Explain likely categories: limits, priorities, availability, karma/nuyen, sourcebook toggles, or missing house-rule setting."
                ),
                (
                    "Q: Can I recover a campaign after a session?\n"
                    "A: Explain the campaign/workspace return loop: recap, aftermath, next-session carry-forward, and proof/status surfaces. Ask if they are player, GM, or organizer."
                ),
                (
                    "Q: Where is the download?\n"
                    "A: Point to the downloads route/status shelf if known; avoid claiming a platform build is ready unless the current status/proof says so."
                ),
                (
                    "Q: Is Chummer.run production ready?\n"
                    "A: Be explicit about current status and proof. Say what is verified, what is preview/experimental, and where to inspect release evidence."
                ),
                (
                    "Q: I am a GM; what should I prep before tonight?\n"
                    "A: Ask campaign/ruleset/time budget. Suggest practical prep: player roster, scene objectives, NPC/contact notes, handouts, house rules, and a next-session carry-forward list."
                ),
            ]
        ),
        "safety_notes": "Do not invent game rules, account status, release status, or support closure. Point to source/proof when needed.",
        "enabled": True,
        "notes": "User-facing Chummer.run chat persona. Map an inbound number to this ai_key when the channel is assigned.",
    },
    {
        "persona_key": EXECUTIVE_ASSISTANT_KEY,
        "heyy_ai_key": EXECUTIVE_ASSISTANT_KEY,
        "heyy_ai_name": EXECUTIVE_ASSISTANT_NAME,
        "product_key": "executive_assistant",
        "product_name": "Executive Assistant",
        "channel": "whatsapp_web_session",
        "behavior_prompt": EXECUTIVE_ASSISTANT_BEHAVIOR_PROMPT,
        "memory_notes": EXECUTIVE_ASSISTANT_MEMORY_NOTES,
        "pacing_hint": EXECUTIVE_ASSISTANT_PACING_HINT,
        "typing_delay_ms": EXECUTIVE_ASSISTANT_TYPING_DELAY_MS,
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "quiet_hours_start_hour": 0,
        "quiet_hours_end_hour": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": True,
        "auto_reply_enabled": False,
        "greeting_text": EXECUTIVE_ASSISTANT_REPLY_TEXT,
        "reply_style": (
            "Concise, operator-focused, action-first. State what is known, what changed, and what remains. "
            "Mask private identifiers in summaries and never ask for secrets in chat."
        ),
        "sample_questions": "\n".join(
            [
                "What is the WhatsApp session status?",
                "Map my number to the Executive Assistant AI.",
                "Send the QR to Telegram.",
                "Why did I get logged out?",
                "Store the latest conversations in Teable.",
                "Route PropertyQuarry users to Mira.",
                "What still needs wiring for premium support?",
            ]
        ),
        "sample_answer_patterns": "\n".join(
            [
                "Q: What is the WhatsApp session status?\nA: Report readiness, account presence, route count, and last activity without exposing raw account digits.",
                "Q: Map my number to the Executive Assistant AI.\nA: Confirm the masked number suffix, Teable persistence, sidecar route application, and any verification performed.",
                "Q: Send the QR to Telegram.\nA: Check whether the sidecar needs pairing, generate/send the QR when available, and state if the session is already ready.",
                "Q: Why did I get logged out?\nA: Explain likely WhatsApp Web causes: old linked device replacement, session volume reset, browser auth invalidation, or account-side logout; then suggest the next check.",
                "Q: Store the latest conversations in Teable.\nA: Run the sync, report created/updated counts, and note whether message body text storage is enabled.",
                "Q: Route PropertyQuarry users to Mira.\nA: Confirm the route source, ai_key/name, Teable row, and live sidecar route count.",
                "Q: What still needs wiring for premium support?\nA: List remaining integration gaps by channel, persistence, notification consent, inbound actions, and verification.",
            ]
        ),
        "safety_notes": "Private operator assistant. Never expose secrets, raw private phone numbers, credentials, payment data, or private identity data.",
        "enabled": True,
        "notes": "Owner-facing Executive Assistant persona for the WhatsApp Web session.",
    },
]


def _load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _parse_env_value(raw_value)


def _parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                loaded = json.loads(value)
                if isinstance(loaded, str):
                    return loaded
            except Exception:
                return value[1:-1]
        return value[1:-1]
    return value


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _teable_request_timeout_seconds() -> float:
    raw = _env("EA_WHATSAPP_WEB_TEABLE_REQUEST_TIMEOUT_SECONDS", str(DEFAULT_TEABLE_REQUEST_TIMEOUT_SECONDS))
    try:
        value = float(raw)
    except Exception:
        value = float(DEFAULT_TEABLE_REQUEST_TIMEOUT_SECONDS)
    return max(1.0, min(value, 120.0))


def _teable_request_attempts() -> int:
    raw = _env("EA_WHATSAPP_WEB_TEABLE_REQUEST_ATTEMPTS", str(DEFAULT_TEABLE_REQUEST_ATTEMPTS))
    try:
        value = int(raw)
    except Exception:
        value = int(DEFAULT_TEABLE_REQUEST_ATTEMPTS)
    return max(1, min(value, 5))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _stale_zero_to_default(value: object, default: int) -> int:
    parsed = _int_value(value, default)
    if int(default) > 0 and parsed <= 0:
        return int(default)
    return parsed


def _bool_value(value: object, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _digits_value(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits if len(digits) >= 7 else ""


def _optional_int_env(name: str) -> int | None:
    raw = _env(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _nonnegative_int(value: object, default: int = 0) -> int:
    parsed = _int_value(value, default)
    return max(0, parsed)


def _load_sync_state(path_value: object) -> dict[str, Any]:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _save_sync_state(path_value: object, state: dict[str, Any]) -> None:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return
    path = Path(raw_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _conversation_skip_from_args(args: argparse.Namespace) -> int:
    explicit = getattr(args, "conversation_skip", None)
    if explicit is not None:
        return _nonnegative_int(explicit)
    if bool(getattr(args, "disable_conversation_page_state", False)):
        return 0
    state_file = str(getattr(args, "conversation_page_state_file", "") or "").strip()
    if not state_file:
        return 0
    state = _load_sync_state(state_file)
    return _nonnegative_int(state.get("next_conversation_skip"), 0)


def _conversation_start_skip_from_args(args: argparse.Namespace) -> int:
    explicit = getattr(args, "conversation_skip", None)
    if explicit is not None:
        return _nonnegative_int(explicit)
    return _conversation_skip_from_args(args)


def _conversation_state_completed(args: argparse.Namespace) -> bool:
    if bool(getattr(args, "disable_conversation_page_state", False)):
        return False
    state_file = str(getattr(args, "conversation_page_state_file", "") or "").strip()
    if not state_file:
        return False
    state = _load_sync_state(state_file)
    return bool(state.get("conversation_scan_completed"))


def _completed_refresh_conversation_take(args: argparse.Namespace) -> int:
    configured = _env("EA_WHATSAPP_WEB_TEABLE_COMPLETED_REFRESH_CONVERSATION_TAKE", "")
    default_take = min(max(1, _int_value(getattr(args, "conversation_take", 25), 25)), 5)
    return max(1, _int_value(configured, default_take))


def _effective_conversation_take(args: argparse.Namespace, *, completed_refresh: bool) -> int:
    configured_take = (
        _completed_refresh_conversation_take(args)
        if completed_refresh
        else max(1, _int_value(getattr(args, "conversation_take", 25), 25))
    )
    message_limit = max(1, _int_value(getattr(args, "message_limit", 100), 100))
    max_message_rows = _nonnegative_int(getattr(args, "max_message_rows_per_run", 0), 0)
    if max_message_rows <= 0:
        return configured_take
    budgeted_take = max(1, max_message_rows // message_limit)
    return max(1, min(configured_take, budgeted_take))


def _update_conversation_page_state(
    *,
    args: argparse.Namespace,
    payload: dict[str, Any],
    message_upsert: dict[str, int],
) -> dict[str, object]:
    if bool(getattr(args, "disable_conversation_page_state", False)):
        return {}
    state_file = str(getattr(args, "conversation_page_state_file", "") or "").strip()
    if not state_file:
        return {}
    state = _load_sync_state(state_file)
    completed_refresh = bool(payload.get("completed_refresh"))
    current_skip = _nonnegative_int(payload.get("conversation_skip"), 0)
    next_skip = _nonnegative_int(payload.get("next_conversation_skip"), 0)
    page_complete = bool(payload.get("conversation_page_complete"))
    updated_at = _now_iso()
    completed_scan_count = _nonnegative_int(state.get("conversation_scan_completed_count"), 0)
    previous_session_ref = str(state.get("session_ref") or "").strip()
    previous_next_skip = _nonnegative_int(state.get("next_conversation_skip"), 0)
    previous_page_complete = bool(state.get("conversation_page_complete"))
    previous_completed_refresh = bool(state.get("completed_refresh"))
    continuing_cycle = (
        previous_session_ref == str(args.session_ref)
        and current_skip > 0
        and previous_next_skip == current_skip
        and not previous_page_complete
        and not previous_completed_refresh
    )
    previous_cycle_total = _nonnegative_int(state.get("message_upsert_cycle_total"), 0) if continuing_cycle else 0
    cycle_total = previous_cycle_total + _nonnegative_int(message_upsert.get("total"), 0)
    if page_complete and not completed_refresh:
        completed_scan_count += 1
    page_state = {
        "conversation_count": _nonnegative_int(payload.get("conversation_count"), 0),
        "conversation_page_complete": page_complete,
        "conversation_pages": _nonnegative_int(payload.get("conversation_pages"), 1),
        "conversation_skip": _nonnegative_int(payload.get("conversation_skip"), 0),
        "conversation_scan_completed": bool(state.get("conversation_scan_completed")) or page_complete,
        "conversation_scan_completed_at": (
            updated_at
            if page_complete and not completed_refresh
            else str(state.get("conversation_scan_completed_at") or "").strip()
        ),
        "conversation_scan_completed_count": completed_scan_count,
        "conversation_scan_completed_total": _nonnegative_int(payload.get("conversation_total"), 0)
        if page_complete
        else _nonnegative_int(state.get("conversation_scan_completed_total"), 0),
        "conversation_total": _nonnegative_int(payload.get("conversation_total"), 0),
        "message_upsert": dict(message_upsert),
        "message_upsert_cycle_total": cycle_total,
        "next_conversation_skip": next_skip,
        "completed_refresh": completed_refresh,
        "session_ref": str(args.session_ref),
        "sync_all_conversations": bool(getattr(args, "sync_all_conversations", False)),
        "updated_at": updated_at,
    }
    state.update(page_state)
    _save_sync_state(state_file, state)
    return page_state


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 30,
    attempts: int = 3,
) -> Any:
    data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **dict(headers or {})},
    )
    bounded_attempts = max(1, min(int(attempts or 1), 5))
    for attempt in range(1, bounded_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:800]
            if exc.code in TRANSIENT_HTTP_STATUS_CODES and attempt < bounded_attempts:
                time.sleep(min(8.0, 1.5 * attempt))
                continue
            raise SystemExit(f"http_error:{exc.code}:{detail}") from exc
        except Exception as exc:
            if attempt < bounded_attempts:
                time.sleep(min(8.0, 1.5 * attempt))
                continue
            raise SystemExit(f"http_request_failed:{type(exc).__name__}:{exc}") from exc
    if not raw.strip():
        return {}
    return json.loads(raw)


def _teable_request(*, method: str, base_url: str, api_key: str, path: str, body: dict[str, object] | None = None) -> Any:
    origin = "https://app.teable.ai"
    return _request_json(
        method=method,
        url=f"{base_url.rstrip('/')}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": origin,
            "Referer": f"{origin}/",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        },
        body=body,
        timeout=_teable_request_timeout_seconds(),
        attempts=_teable_request_attempts(),
    )


def _session_headers(token: str, header_name: str, header_prefix: str) -> dict[str, str]:
    if not token:
        return {}
    return {header_name or "Authorization": f"{header_prefix}{token}".strip()}


def _session_api_unavailable_from_exit(exc: BaseException) -> SessionApiUnavailable | None:
    if not isinstance(exc, SystemExit):
        return None
    detail = str(exc)
    lowered = detail.lower()
    if detail.startswith("http_error:409:"):
        return SessionApiUnavailable(operation="session_api_request", detail=detail)
    if detail.startswith("http_error:502:") and "conversations_failed" in lowered:
        return SessionApiUnavailable(operation="session_api_request", detail=detail)
    if detail.startswith("http_error:503:") or detail.startswith("http_error:504:"):
        return SessionApiUnavailable(operation="session_api_request", detail=detail)
    if not detail.startswith("http_request_failed:"):
        return None
    if "connection refused" in lowered or "[errno 111]" in lowered:
        return SessionApiUnavailable(operation="session_api_request", detail=detail)
    if "timeout" in lowered or "timed out" in lowered:
        return SessionApiUnavailable(operation="session_api_request", detail=detail)
    return None


def _teable_api_unavailable_from_exit(exc: BaseException) -> SessionApiUnavailable | None:
    if not isinstance(exc, SystemExit):
        return None
    detail = str(exc)
    lowered = detail.lower()
    if detail.startswith("http_error:"):
        code_part = detail.split(":", 2)[1]
        if code_part.isdigit():
            code = int(code_part)
            if code in TRANSIENT_HTTP_STATUS_CODES:
                return SessionApiUnavailable(operation="teable_api_request", detail=detail)
        return None
    if not detail.startswith("http_request_failed:"):
        return None
    if "connection refused" in lowered or "[errno 111]" in lowered:
        return SessionApiUnavailable(operation="teable_api_request", detail=detail)
    if "name or service not known" in lowered or "[errno -2]" in lowered or "temporary failure in name resolution" in lowered:
        return SessionApiUnavailable(operation="teable_api_request", detail=detail)
    if "timed out" in lowered or "timeout" in lowered:
        return SessionApiUnavailable(operation="teable_api_request", detail=detail)
    if "network is unreachable" in lowered or "host is unreachable" in lowered or "failed to resolve" in lowered:
        return SessionApiUnavailable(operation="teable_api_request", detail=detail)
    return None


def _session_get(args: argparse.Namespace, suffix: str) -> dict[str, Any]:
    session_ref = urllib.parse.quote(str(args.session_ref).strip(), safe="")
    try:
        return _request_json(
            method="GET",
            url=f"{str(args.session_api_base_url).rstrip('/')}/sessions/{session_ref}/{suffix.lstrip('/')}",
            headers=_session_headers(str(args.session_api_token), str(args.auth_header_name), str(args.auth_header_prefix)),
            timeout=float(args.timeout_seconds),
        )
    except SystemExit as exc:
        unavailable = _session_api_unavailable_from_exit(exc)
        if unavailable is not None:
            raise unavailable from exc
        raise


def _session_put(args: argparse.Namespace, suffix: str, body: dict[str, object]) -> dict[str, Any]:
    session_ref = urllib.parse.quote(str(args.session_ref).strip(), safe="")
    try:
        return _request_json(
            method="PUT",
            url=f"{str(args.session_api_base_url).rstrip('/')}/sessions/{session_ref}/{suffix.lstrip('/')}",
            headers=_session_headers(str(args.session_api_token), str(args.auth_header_name), str(args.auth_header_prefix)),
            body=body,
            timeout=float(args.timeout_seconds),
        )
    except SystemExit as exc:
        unavailable = _session_api_unavailable_from_exit(exc)
        if unavailable is not None:
            raise unavailable from exc
        raise


def _table_id_from_base(*, base_url: str, api_key: str, base_id: str, table_name: str) -> str:
    if not base_id:
        return ""
    tables_payload = _teable_request(
        method="GET",
        base_url=base_url,
        api_key=api_key,
        path=f"/api/base/{urllib.parse.quote(base_id)}/table",
    )
    tables = tables_payload if isinstance(tables_payload, list) else tables_payload.get("tables") or []
    for raw_table in tables:
        if isinstance(raw_table, dict) and str(raw_table.get("name") or "").strip() == table_name:
            return str(raw_table.get("id") or "").strip()
    return ""


def _discover_table_id(*, base_url: str, api_key: str, table_name: str, base_id: str = "") -> str:
    direct = _table_id_from_base(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name)
    if direct:
        return direct
    spaces_payload = _teable_request(method="GET", base_url=base_url, api_key=api_key, path="/api/space")
    spaces = spaces_payload if isinstance(spaces_payload, list) else spaces_payload.get("spaces") or []
    for raw_space in spaces:
        if not isinstance(raw_space, dict):
            continue
        space_id = str(raw_space.get("id") or "").strip()
        if not space_id:
            continue
        bases_payload = _teable_request(method="GET", base_url=base_url, api_key=api_key, path=f"/api/space/{urllib.parse.quote(space_id)}/base")
        bases = bases_payload if isinstance(bases_payload, list) else bases_payload.get("bases") or []
        for raw_base in bases:
            if not isinstance(raw_base, dict):
                continue
            base_id = str(raw_base.get("id") or "").strip()
            if not base_id:
                continue
            found = _table_id_from_base(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name)
            if found:
                return found
    return ""


def _create_table(*, base_url: str, api_key: str, base_id: str, table_name: str, fields: list[dict[str, object]]) -> str:
    created = _teable_request(
        method="POST",
        base_url=base_url,
        api_key=api_key,
        path=f"/api/base/{urllib.parse.quote(base_id)}/table/",
        body={"name": table_name, "fields": fields, "fieldKeyType": "name"},
    )
    table_id = str(created.get("id") or "").strip()
    if not table_id:
        raise SystemExit(f"teable_create_table_missing_id:{table_name}")
    return table_id


def _table_fields(*, base_url: str, api_key: str, table_id: str) -> list[dict[str, Any]]:
    payload = _teable_request(
        method="GET",
        base_url=base_url,
        api_key=api_key,
        path=f"/api/table/{urllib.parse.quote(table_id)}/field",
    )
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [dict(item) for item in payload.get("fields") or [] if isinstance(item, dict)]
    return []


def _ensure_fields(*, base_url: str, api_key: str, table_id: str, fields: list[dict[str, object]]) -> int:
    existing = {str(field.get("name") or "").strip() for field in _table_fields(base_url=base_url, api_key=api_key, table_id=table_id)}
    created = 0
    for field in fields:
        name = str(field.get("name") or "").strip()
        if not name or name in existing:
            continue
        _teable_request(
            method="POST",
            base_url=base_url,
            api_key=api_key,
            path=f"/api/table/{urllib.parse.quote(table_id)}/field",
            body=dict(field),
        )
        existing.add(name)
        created += 1
    return created


def _ensure_table(
    *,
    base_url: str,
    api_key: str,
    base_id: str,
    table_id: str,
    table_name: str,
    fields: list[dict[str, object]],
    create_missing: bool,
) -> tuple[str, bool]:
    if table_id:
        return table_id, False
    discovered = _discover_table_id(base_url=base_url, api_key=api_key, table_name=table_name, base_id=base_id)
    if discovered:
        return discovered, False
    if not create_missing:
        raise SystemExit(f"teable_table_id_missing:{table_name}")
    if not base_id:
        raise SystemExit(f"teable_base_id_required:{table_name}")
    return _create_table(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name, fields=fields), True


def _list_records(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    take: int = 1000,
    projection: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        query_items: list[tuple[str, object]] = [
            ("fieldKeyType", "name"),
            ("cellFormat", "json"),
            ("take", take),
            ("skip", skip),
        ]
        for field_name in projection or []:
            normalized = str(field_name or "").strip()
            if normalized:
                query_items.append(("projection", normalized))
        query = urllib.parse.urlencode(query_items, doseq=True)
        payload = _teable_request(method="GET", base_url=base_url, api_key=api_key, path=f"/api/table/{urllib.parse.quote(table_id)}/record?{query}")
        records = [dict(item) for item in payload.get("records") or [] if isinstance(item, dict)]
        rows.extend(records)
        if len(records) < take:
            break
        skip += take
    return rows


def _existing_record_ids(*, base_url: str, api_key: str, table_id: str, key_field: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for record in _list_records(base_url=base_url, api_key=api_key, table_id=table_id, projection=[key_field]):
        fields = dict(record.get("fields") or {})
        key_value = str(fields.get(key_field) or "").strip()
        record_id = str(record.get("id") or "").strip()
        if key_value and record_id:
            found[key_value] = record_id
    return found


def _normalize_teable_value(value: object) -> object:
    if isinstance(value, bool):
        return value
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    if isinstance(value, list):
        return [_normalize_teable_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_teable_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    return str(value)


def _tql_field_ref(field_name: str) -> str:
    return "{" + str(field_name or "").replace("}", "").strip() + "}"


def _tql_string(value: str) -> str:
    escaped = str(value or "").replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _existing_record_ids_for_keys(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    key_field: str,
    key_values: list[str],
) -> dict[str, str]:
    found: dict[str, str] = {}
    normalized_keys = [str(value or "").strip() for value in key_values if str(value or "").strip()]
    field_ref = _tql_field_ref(key_field)
    for start in range(0, len(normalized_keys), KEY_LOOKUP_BATCH_SIZE):
        chunk = normalized_keys[start : start + KEY_LOOKUP_BATCH_SIZE]
        if not chunk:
            continue
        comparisons = [f"{field_ref} = {_tql_string(value)}" for value in chunk]
        filter_by_tql = comparisons[0] if len(comparisons) == 1 else "(" + " OR ".join(comparisons) + ")"
        query_items: list[tuple[str, object]] = [
            ("fieldKeyType", "name"),
            ("cellFormat", "json"),
            ("take", max(100, len(chunk))),
            ("skip", 0),
            ("ignoreViewQuery", "true"),
            ("projection", key_field),
            ("filterByTql", filter_by_tql),
        ]
        query = urllib.parse.urlencode(query_items, doseq=True)
        payload = _teable_request(method="GET", base_url=base_url, api_key=api_key, path=f"/api/table/{urllib.parse.quote(table_id)}/record?{query}")
        for record in payload.get("records") or []:
            if not isinstance(record, dict):
                continue
            fields = dict(record.get("fields") or {})
            key_value = str(fields.get(key_field) or "").strip()
            record_id = str(record.get("id") or "").strip()
            if key_value and record_id:
                found[key_value] = record_id
    return found


def _existing_records_for_keys(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    key_field: str,
    key_values: list[str],
    projection: list[str] | None = None,
) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    normalized_keys = [str(value or "").strip() for value in key_values if str(value or "").strip()]
    field_ref = _tql_field_ref(key_field)
    projections = [str(item or "").strip() for item in (projection or []) if str(item or "").strip()]
    if key_field not in projections:
        projections.insert(0, key_field)
    for start in range(0, len(normalized_keys), KEY_LOOKUP_BATCH_SIZE):
        chunk = normalized_keys[start : start + KEY_LOOKUP_BATCH_SIZE]
        if not chunk:
            continue
        comparisons = [f"{field_ref} = {_tql_string(value)}" for value in chunk]
        filter_by_tql = comparisons[0] if len(comparisons) == 1 else "(" + " OR ".join(comparisons) + ")"
        query_items: list[tuple[str, object]] = [
            ("fieldKeyType", "name"),
            ("cellFormat", "json"),
            ("take", max(100, len(chunk))),
            ("skip", 0),
            ("ignoreViewQuery", "true"),
            ("filterByTql", filter_by_tql),
        ]
        for field_name in projections:
            query_items.append(("projection", field_name))
        query = urllib.parse.urlencode(query_items, doseq=True)
        payload = _teable_request(method="GET", base_url=base_url, api_key=api_key, path=f"/api/table/{urllib.parse.quote(table_id)}/record?{query}")
        for record in payload.get("records") or []:
            if not isinstance(record, dict):
                continue
            fields = dict(record.get("fields") or {})
            key_value = str(fields.get(key_field) or "").strip()
            record_id = str(record.get("id") or "").strip()
            if key_value and record_id:
                found[key_value] = {"id": record_id, "fields": fields}
    return found


def _row_matches_existing_fields(row: dict[str, object], existing_fields: dict[str, object]) -> bool:
    for key, expected in row.items():
        if key in VOLATILE_NOOP_FIELDS:
            continue
        if _normalize_teable_value(existing_fields.get(key)) != _normalize_teable_value(expected):
            return False
    return True


def _upsert_rows(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    key_field: str,
    rows: list[dict[str, object]],
    lookup_existing_by_keys: bool = False,
) -> dict[str, int]:
    if not rows:
        return {"created": 0, "updated": 0, "total": 0}
    key_values = [str(row.get(key_field) or "").strip() for row in rows if str(row.get(key_field) or "").strip()]
    if lookup_existing_by_keys:
        existing_records = _existing_records_for_keys(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            key_field=key_field,
            key_values=key_values,
            projection=sorted({field for row in rows for field in row.keys()}),
        )
        existing = {key: str(dict(record).get("id") or "").strip() for key, record in existing_records.items()}
    else:
        existing = _existing_record_ids(base_url=base_url, api_key=api_key, table_id=table_id, key_field=key_field)
        existing_records = {}
    created = 0
    updated = 0
    pending: list[dict[str, object]] = []
    for row in rows:
        key_value = str(row.get(key_field) or "").strip()
        if not key_value:
            continue
        record_id = existing.get(key_value)
        if record_id:
            existing_record = dict(existing_records.get(key_value) or {})
            existing_fields = dict(existing_record.get("fields") or {})
            if existing_fields and _row_matches_existing_fields(row, existing_fields):
                continue
            _teable_request(
                method="PATCH",
                base_url=base_url,
                api_key=api_key,
                path=f"/api/table/{urllib.parse.quote(table_id)}/record/{urllib.parse.quote(record_id)}",
                body={"fieldKeyType": "name", "typecast": True, "record": {"fields": row}},
            )
            updated += 1
        else:
            pending.append({"fields": row})
    for start in range(0, len(pending), CREATE_RECORD_BATCH_SIZE):
        chunk = pending[start : start + CREATE_RECORD_BATCH_SIZE]
        if not chunk:
            continue
        result = _teable_request(
            method="POST",
            base_url=base_url,
            api_key=api_key,
            path=f"/api/table/{urllib.parse.quote(table_id)}/record",
            body={"fieldKeyType": "name", "typecast": True, "records": chunk},
        )
        created += len(result.get("records") or chunk)
    return {"created": created, "updated": updated, "total": len(rows)}


def _delete_record(*, base_url: str, api_key: str, table_id: str, record_id: str) -> bool:
    try:
        _teable_request(
            method="DELETE",
            base_url=base_url,
            api_key=api_key,
            path=f"/api/table/{urllib.parse.quote(table_id)}/record/{urllib.parse.quote(record_id)}",
        )
        return True
    except SystemExit as exc:
        detail = str(exc)
        if detail.startswith("http_error:501:") or "Unsupported method ('DELETE')" in detail:
            return False
        raise


def _cleanup_rows_missing_key(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    key_field: str,
    projection: list[str] | None = None,
) -> dict[str, int]:
    records = _list_records(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        projection=projection or [key_field],
    )
    deleted = 0
    failed = 0
    for record in records:
        fields = dict(record.get("fields") or {})
        key_value = str(fields.get(key_field) or "").strip()
        if key_value:
            continue
        if any(str(value or "").strip() for value in fields.values()):
            continue
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            failed += 1
            continue
        try:
            if _delete_record(base_url=base_url, api_key=api_key, table_id=table_id, record_id=record_id):
                deleted += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return {"deleted": deleted, "failed": failed, "total": deleted + failed}


def _cleanup_projectionless_rows(*, base_url: str, api_key: str, table_id: str) -> dict[str, int]:
    return _cleanup_rows_missing_key(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        key_field="projection_id",
        projection=["projection_id"],
    )


def _cleanup_persona_rows(*, base_url: str, api_key: str, persona_table_id: str) -> dict[str, int]:
    return _cleanup_rows_missing_key(
        base_url=base_url,
        api_key=api_key,
        table_id=persona_table_id,
        key_field="persona_key",
        projection=["persona_key"],
    )


def _cleanup_route_rows(*, base_url: str, api_key: str, route_table_id: str) -> dict[str, int]:
    return _cleanup_rows_missing_key(
        base_url=base_url,
        api_key=api_key,
        table_id=route_table_id,
        key_field="route_key",
        projection=["route_key"],
    )


def _cleanup_stale_route_rows(
    *,
    base_url: str,
    api_key: str,
    route_table_id: str,
    session_ref: str,
) -> dict[str, int]:
    records = _list_records(
        base_url=base_url,
        api_key=api_key,
        table_id=route_table_id,
        projection=["route_key", "session_ref"],
    )
    deleted = 0
    failed = 0
    normalized_session_ref = str(session_ref or "").strip()
    for record in records:
        fields = dict(record.get("fields") or {})
        route_key = str(fields.get("route_key") or "").strip()
        row_session_ref = str(fields.get("session_ref") or "").strip()
        should_delete = False
        if route_key.startswith("disabled_reachability_"):
            should_delete = True
        elif row_session_ref and normalized_session_ref and row_session_ref != normalized_session_ref:
            should_delete = True
        if not should_delete:
            continue
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            failed += 1
            continue
        try:
            if _delete_record(base_url=base_url, api_key=api_key, table_id=route_table_id, record_id=record_id):
                deleted += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return {"deleted": deleted, "failed": failed, "total": deleted + failed}


def _cleanup_projectionless_audiobook_rows(*, base_url: str, api_key: str, audiobook_table_id: str) -> dict[str, int]:
    return _cleanup_rows_missing_key(
        base_url=base_url,
        api_key=api_key,
        table_id=audiobook_table_id,
        key_field="projection_id",
        projection=["projection_id", "job_id"],
    )


def _cleanup_stale_audiobook_rows(
    *,
    base_url: str,
    api_key: str,
    audiobook_table_id: str,
    current_projection_ids: set[str],
) -> dict[str, int]:
    records = _list_records(
        base_url=base_url,
        api_key=api_key,
        table_id=audiobook_table_id,
        projection=["projection_id", "job_id"],
    )
    deleted = 0
    failed = 0
    for record in records:
        fields = dict(record.get("fields") or {})
        projection_id = str(fields.get("projection_id") or fields.get("job_id") or "").strip()
        if not projection_id or projection_id in current_projection_ids:
            continue
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            failed += 1
            continue
        try:
            if _delete_record(base_url=base_url, api_key=api_key, table_id=audiobook_table_id, record_id=record_id):
                deleted += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return {"deleted": deleted, "failed": failed, "total": deleted + failed}


def _disable_route_record(*, base_url: str, api_key: str, table_id: str, record_id: str) -> None:
    disabled_route_key = f"disabled_reachability_{hashlib.sha256(str(record_id).encode('utf-8')).hexdigest()[:12]}"
    _teable_request(
        method="PATCH",
        base_url=base_url,
        api_key=api_key,
        path=f"/api/table/{urllib.parse.quote(table_id)}/record/{urllib.parse.quote(record_id)}",
        body={
            "fieldKeyType": "name",
            "typecast": True,
            "record": {
                "fields": {
                    "route_key": disabled_route_key,
                    "enabled": False,
                    "notes": "Disabled stale reachability-only row created without a hashed route key.",
                }
            },
        },
    )


def _is_reachability_only_raw_digit_route_row(fields: dict[str, object]) -> bool:
    route_key = str(fields.get("route_key") or "").strip()
    inbound = str(fields.get("inbound_number_digits") or "").strip()
    if not route_key or _digits_value(route_key) != route_key or inbound:
        return False
    if str(fields.get("heyy_ai_key") or "").strip() or str(fields.get("heyy_ai_name") or "").strip():
        return False
    return any(
        key in fields
        for key in (
            "recipient_registered",
            "recipient_resolution_method",
            "recipient_chat_id_kind",
            "recipient_lid_chat_id_present",
            "recipient_phone_chat_id_present",
            "recipient_reachability_checked_at",
            "recipient_reachability_reason",
        )
    )


def _cleanup_reachability_only_route_rows(
    *,
    base_url: str,
    api_key: str,
    route_table_id: str,
    session_ref: str,
) -> dict[str, int]:
    records = _list_records(
        base_url=base_url,
        api_key=api_key,
        table_id=route_table_id,
        projection=[
            "route_key",
            "inbound_number_digits",
            "heyy_ai_key",
            "heyy_ai_name",
            "enabled",
            "recipient_registered",
            "recipient_resolution_method",
            "recipient_chat_id_kind",
            "recipient_lid_chat_id_present",
            "recipient_phone_chat_id_present",
            "recipient_reachability_checked_at",
            "recipient_reachability_reason",
            "session_ref",
        ],
    )
    disabled = 0
    failed = 0
    for record in records:
        fields = dict(record.get("fields") or {})
        if fields.get("enabled") is False:
            continue
        row_session = str(fields.get("session_ref") or "").strip()
        if row_session and row_session != session_ref:
            continue
        if not _is_reachability_only_raw_digit_route_row(fields):
            continue
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            failed += 1
            continue
        try:
            _disable_route_record(base_url=base_url, api_key=api_key, table_id=route_table_id, record_id=record_id)
            disabled += 1
        except Exception:
            failed += 1
    return {"disabled": disabled, "failed": failed, "total": disabled + failed}


def _persona_for_ai_key(ai_key: str) -> dict[str, object]:
    normalized = str(ai_key or "").strip()
    for persona in HEYY_AI_PERSONAS:
        if str(persona.get("heyy_ai_key") or "").strip() == normalized:
            return dict(persona)
    return {
        "heyy_ai_key": normalized or DEFAULT_HEYY_AI_KEY,
        "heyy_ai_name": normalized or DEFAULT_HEYY_AI_NAME,
        "behavior_prompt": DEFAULT_BEHAVIOR_PROMPT,
        "memory_notes": DEFAULT_MEMORY_NOTES,
        "pacing_hint": DEFAULT_PACING_HINT,
        "typing_delay_ms": DEFAULT_TYPING_DELAY_MS,
        "pre_reply_delay_min_seconds": DEFAULT_PRE_REPLY_DELAY_MIN_SECONDS if normalized == DEFAULT_HEYY_AI_KEY else 0,
        "pre_reply_delay_max_seconds": DEFAULT_PRE_REPLY_DELAY_MAX_SECONDS if normalized == DEFAULT_HEYY_AI_KEY else 0,
        "quiet_hours_start_hour": DEFAULT_QUIET_HOURS_START_HOUR if normalized == DEFAULT_HEYY_AI_KEY else 0,
        "quiet_hours_end_hour": DEFAULT_QUIET_HOURS_END_HOUR if normalized == DEFAULT_HEYY_AI_KEY else 0,
        "typing_delay_ms_per_character": DEFAULT_TYPING_DELAY_MS_PER_CHARACTER if normalized == DEFAULT_HEYY_AI_KEY else 0,
        "typing_status_enabled": True,
        "auto_reply_enabled": normalized == DEFAULT_HEYY_AI_KEY,
        "greeting_text": DEFAULT_REPLY_TEXT,
    }


def _route_key_for_inbound(*, session_ref: str, inbound_number_digits: str) -> str:
    material = f"{str(session_ref).strip()}:{str(inbound_number_digits).strip()}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"inbound_{digest}"


def _explicit_route_row(
    *,
    session_ref: str,
    inbound_number_digits: str,
    heyy_ai_key: str,
    heyy_ai_name: str = "",
) -> dict[str, object]:
    inbound = _digits_value(inbound_number_digits)
    if not inbound:
        return {}
    ai_key = str(heyy_ai_key or EXECUTIVE_ASSISTANT_KEY).strip() or EXECUTIVE_ASSISTANT_KEY
    persona = _persona_for_ai_key(ai_key)
    ai_name = str(heyy_ai_name or persona.get("heyy_ai_name") or ai_key).strip() or ai_key
    return {
        "route_key": _route_key_for_inbound(session_ref=session_ref, inbound_number_digits=inbound),
        "inbound_number_digits": inbound,
        "heyy_ai_key": ai_key,
        "heyy_ai_name": ai_name,
        "behavior_prompt": str(persona.get("behavior_prompt") or DEFAULT_BEHAVIOR_PROMPT).strip(),
        "memory_notes": str(persona.get("memory_notes") or DEFAULT_MEMORY_NOTES).strip(),
        "pacing_hint": str(persona.get("pacing_hint") or DEFAULT_PACING_HINT).strip(),
        "minimum_delay_seconds": 0,
        "pre_reply_delay_min_seconds": _int_value(persona.get("pre_reply_delay_min_seconds"), 0),
        "pre_reply_delay_max_seconds": _int_value(persona.get("pre_reply_delay_max_seconds"), 0),
        "quiet_hours_start_hour": _int_value(persona.get("quiet_hours_start_hour"), 0),
        "quiet_hours_end_hour": _int_value(persona.get("quiet_hours_end_hour"), 0),
        "typing_delay_ms": _int_value(persona.get("typing_delay_ms"), EXECUTIVE_ASSISTANT_TYPING_DELAY_MS),
        "typing_delay_ms_per_character": _int_value(persona.get("typing_delay_ms_per_character"), 0),
        "typing_status_enabled": _bool_value(persona.get("typing_status_enabled"), True),
        "auto_reply_enabled": _bool_value(persona.get("auto_reply_enabled"), ai_key == DEFAULT_HEYY_AI_KEY),
        "reply_text": str(persona.get("greeting_text") or DEFAULT_REPLY_TEXT).strip(),
        "enabled": True,
        "session_ref": session_ref,
        "updated_at": _now_iso(),
        "notes": "Explicit private inbound route. Number is stored only in Teable/session config; route_key is hashed.",
    }


def _load_route_seed_payload(*, raw_json: str = "", seed_file: str = "") -> object:
    raw = str(raw_json or "").strip()
    path_text = str(seed_file or "").strip()
    if not raw and path_text:
        try:
            raw = Path(path_text).read_text(encoding="utf-8")
        except OSError:
            raw = ""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _iter_route_seed_items(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        rows: list[dict[str, object]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(dict(item))
        return rows
    if isinstance(payload, dict):
        items: list[dict[str, object]] = []
        for raw_number, raw_rule in payload.items():
            if isinstance(raw_rule, dict):
                row = dict(raw_rule)
            else:
                row = {"heyy_ai_key": raw_rule}
            row.setdefault("inbound_number_digits", raw_number)
            items.append(row)
        return items
    return []


def _route_seed_rows(
    *,
    session_ref: str,
    raw_json: str = "",
    seed_file: str = "",
) -> list[dict[str, object]]:
    payload = _load_route_seed_payload(raw_json=raw_json, seed_file=seed_file)
    rows: list[dict[str, object]] = []
    seen_route_keys: set[str] = set()
    for item in _iter_route_seed_items(payload):
        inbound_number_digits = (
            item.get("inbound_number_digits")
            or item.get("inbound_number")
            or item.get("sender_digits")
            or item.get("phone")
            or item.get("number")
            or ""
        )
        ai_key = str(
            item.get("heyy_ai_key")
            or item.get("ai_key")
            or item.get("persona")
            or item.get("persona_key")
            or EXECUTIVE_ASSISTANT_KEY
        ).strip()
        ai_name = str(item.get("heyy_ai_name") or item.get("ai_name") or item.get("display_name") or "").strip()
        row = _explicit_route_row(
            session_ref=session_ref,
            inbound_number_digits=str(inbound_number_digits or ""),
            heyy_ai_key=ai_key,
            heyy_ai_name=ai_name,
        )
        route_key = str(row.get("route_key") or "").strip()
        if not row or not route_key or route_key in seen_route_keys:
            continue
        source = str(item.get("source") or item.get("product_key") or "").strip()
        if source:
            row["notes"] = f"{row['notes']} Seed source: {source}."
        rows.append(row)
        seen_route_keys.add(route_key)
    return rows


def _dedupe_route_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen_route_keys: set[str] = set()
    for row in rows:
        route_key = str(row.get("route_key") or "").strip()
        if not route_key or route_key in seen_route_keys:
            continue
        seen_route_keys.add(route_key)
        deduped.append(row)
    return deduped


def _sidecar_live_route_to_teable_row(route: dict[str, object]) -> dict[str, object]:
    row = dict(route)
    ai_key = str(row.pop("ai_key", "") or row.get("heyy_ai_key") or DEFAULT_HEYY_AI_KEY).strip()
    ai_name = str(row.pop("ai_name", "") or row.get("heyy_ai_name") or ai_key or DEFAULT_HEYY_AI_NAME).strip()
    row["heyy_ai_key"] = ai_key
    row["heyy_ai_name"] = ai_name
    return row


def _route_rows_with_sidecar_live_projection(
    route_rows: list[dict[str, object]],
    sidecar_live_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not sidecar_live_rows:
        return _dedupe_route_rows(route_rows)
    default_rows = [row for row in route_rows if str(row.get("route_key") or "").strip() == "default"]
    non_default_rows = [row for row in route_rows if str(row.get("route_key") or "").strip() != "default"]
    live_teable_rows = [_sidecar_live_route_to_teable_row(row) for row in sidecar_live_rows]
    return _dedupe_route_rows([*default_rows, *live_teable_rows, *non_default_rows])


def _route_row_for_sidecar_public_route(
    *,
    session_ref: str,
    route: dict[str, object],
) -> dict[str, object]:
    route_key = str(route.get("route_key") or "").strip()
    if not route_key or route_key == "default":
        return {}
    inbound = _digits_value(route_key)
    if not inbound:
        return {}
    ai_key = str(route.get("ai_key") or route.get("heyy_ai_key") or "").strip()
    if ai_key != DEFAULT_HEYY_AI_KEY:
        return {}
    ai_name = str(route.get("ai_name") or route.get("heyy_ai_name") or DEFAULT_HEYY_AI_NAME).strip() or DEFAULT_HEYY_AI_NAME
    persona = _persona_for_ai_key(ai_key)
    pre_reply_delay_min_seconds = _int_value(
        route.get("pre_reply_delay_min_seconds"),
        _int_value(persona.get("pre_reply_delay_min_seconds"), DEFAULT_PRE_REPLY_DELAY_MIN_SECONDS),
    )
    pre_reply_delay_max_seconds = _int_value(
        route.get("pre_reply_delay_max_seconds"),
        _int_value(persona.get("pre_reply_delay_max_seconds"), DEFAULT_PRE_REPLY_DELAY_MAX_SECONDS),
    )
    quiet_hours_start_hour = _int_value(
        route.get("quiet_hours_start_hour"),
        _int_value(persona.get("quiet_hours_start_hour"), DEFAULT_QUIET_HOURS_START_HOUR),
    )
    quiet_hours_end_hour = _int_value(
        route.get("quiet_hours_end_hour"),
        _int_value(persona.get("quiet_hours_end_hour"), DEFAULT_QUIET_HOURS_END_HOUR),
    )
    typing_delay_ms_per_character = _int_value(
        route.get("typing_delay_ms_per_character"),
        _int_value(persona.get("typing_delay_ms_per_character"), DEFAULT_TYPING_DELAY_MS_PER_CHARACTER),
    )
    live_test_route = (
        quiet_hours_start_hour == 0
        and quiet_hours_end_hour == 0
        and pre_reply_delay_min_seconds <= 30
        and pre_reply_delay_max_seconds <= 30
    )
    if live_test_route:
        typing_delay_ms_per_character = 0
    return {
        "route_key": _route_key_for_inbound(session_ref=session_ref, inbound_number_digits=inbound),
        "inbound_number_digits": inbound,
        "ai_key": ai_key,
        "ai_name": ai_name,
        "behavior_prompt": str(persona.get("behavior_prompt") or DEFAULT_BEHAVIOR_PROMPT).strip(),
        "memory_notes": str(persona.get("memory_notes") or DEFAULT_MEMORY_NOTES).strip(),
        "pacing_hint": str(route.get("pacing_hint") or persona.get("pacing_hint") or DEFAULT_PACING_HINT).strip(),
        "minimum_delay_seconds": 0,
        "pre_reply_delay_min_seconds": pre_reply_delay_min_seconds,
        "pre_reply_delay_max_seconds": pre_reply_delay_max_seconds,
        "quiet_hours_start_hour": quiet_hours_start_hour,
        "quiet_hours_end_hour": quiet_hours_end_hour,
        "typing_delay_ms": _int_value(route.get("typing_delay_ms"), DEFAULT_TYPING_DELAY_MS),
        "typing_delay_ms_per_character": typing_delay_ms_per_character,
        "typing_status_enabled": _bool_value(route.get("typing_status_enabled"), True),
        "auto_reply_enabled": _bool_value(route.get("auto_reply_enabled"), ai_key == DEFAULT_HEYY_AI_KEY),
        "reply_text": str(persona.get("greeting_text") or DEFAULT_REPLY_TEXT).strip(),
        "enabled": True,
        "session_ref": session_ref,
        "updated_at": _now_iso(),
        "notes": "Preserved live sidecar route. This keeps WhatsApp LID sender routes from reverting to a different assistant during Teable sync.",
    }


def _sidecar_live_route_rows(args: argparse.Namespace) -> list[dict[str, object]]:
    try:
        payload = _session_get(args, "heyy-ai-routes")
    except Exception:
        return []
    return _sidecar_live_route_rows_from_payload(args, payload)


def _sidecar_live_route_rows_from_payload(args: argparse.Namespace, payload: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_inbound: set[str] = set()
    for item in payload.get("routes") or []:
        if not isinstance(item, dict):
            continue
        row = _route_row_for_sidecar_public_route(session_ref=str(args.session_ref), route=dict(item))
        inbound = str(row.get("inbound_number_digits") or "").strip()
        if not row or not inbound or inbound in seen_inbound:
            continue
        rows.append(row)
        seen_inbound.add(inbound)
    return rows


def _merge_sidecar_live_route_overrides(
    routes: list[dict[str, object]],
    overrides: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not overrides:
        return routes
    override_inbounds = {str(row.get("inbound_number_digits") or "").strip() for row in overrides}
    merged = [
        row
        for row in routes
        if str(row.get("inbound_number_digits") or "").strip() not in override_inbounds
    ]
    merged.extend(overrides)
    return merged


def _route_compare_payload(route: dict[str, object]) -> dict[str, object]:
    return {
        "route_key": str(route.get("route_key") or "").strip(),
        "inbound_number_digits": str(route.get("inbound_number_digits") or "").strip(),
        "ai_key": str(route.get("ai_key") or route.get("heyy_ai_key") or "").strip(),
        "ai_name": str(route.get("ai_name") or route.get("heyy_ai_name") or "").strip(),
        "behavior_prompt": str(route.get("behavior_prompt") or "").strip(),
        "memory_notes": str(route.get("memory_notes") or "").strip(),
        "pacing_hint": str(route.get("pacing_hint") or "").strip(),
        "minimum_delay_seconds": _int_value(route.get("minimum_delay_seconds"), 0),
        "pre_reply_delay_min_seconds": _int_value(route.get("pre_reply_delay_min_seconds"), 0),
        "pre_reply_delay_max_seconds": _int_value(route.get("pre_reply_delay_max_seconds"), 0),
        "quiet_hours_start_hour": _int_value(route.get("quiet_hours_start_hour"), 0),
        "quiet_hours_end_hour": _int_value(route.get("quiet_hours_end_hour"), 0),
        "typing_delay_ms": _int_value(route.get("typing_delay_ms"), 0),
        "typing_delay_ms_per_character": _int_value(route.get("typing_delay_ms_per_character"), 0),
        "typing_status_enabled": _bool_value(route.get("typing_status_enabled"), True),
        "auto_reply_enabled": _bool_value(route.get("auto_reply_enabled"), False),
        "reply_text": str(route.get("reply_text") or "").strip(),
        "enabled": _bool_value(route.get("enabled"), True),
        "session_ref": str(route.get("session_ref") or "").strip(),
    }


def _normalized_sidecar_routes_for_compare(routes: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized = [_route_compare_payload(dict(route)) for route in routes if isinstance(route, dict)]
    return sorted(normalized, key=lambda row: (str(row.get("route_key") or ""), str(row.get("inbound_number_digits") or "")))


def _route_compare_hash(routes: list[dict[str, object]]) -> str:
    normalized = _normalized_sidecar_routes_for_compare(routes)
    payload = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preserve_sidecar_live_routes_enabled(args: argparse.Namespace) -> bool:
    if hasattr(args, "preserve_sidecar_live_routes"):
        return bool(getattr(args, "preserve_sidecar_live_routes"))
    # Keep the legacy attribute name readable for older callers until they migrate.
    return bool(getattr(args, "preserve_sidecar_herta_routes", True))


def _route_sync_state_file(args: argparse.Namespace) -> str:
    return str(getattr(args, "conversation_page_state_file", "") or "").strip()


def _stored_route_compare_hash(args: argparse.Namespace) -> str:
    state_file = _route_sync_state_file(args)
    if not state_file:
        return ""
    return str(_load_sync_state(state_file).get("route_compare_hash") or "").strip()


def _store_route_compare_hash(args: argparse.Namespace, route_hash: str, route_count: int) -> None:
    state_file = _route_sync_state_file(args)
    if not state_file:
        return
    state = _load_sync_state(state_file)
    state["route_compare_hash"] = str(route_hash or "").strip()
    state["route_compare_count"] = _nonnegative_int(route_count, 0)
    state["route_compare_updated_at"] = _now_iso()
    _save_sync_state(state_file, state)


def _load_route_import_sources_payload(*, raw_json: str = "", source_file: str = "") -> object:
    raw = str(raw_json or "").strip()
    path_text = str(source_file or "").strip()
    if not raw and path_text:
        try:
            raw = Path(path_text).read_text(encoding="utf-8")
        except OSError:
            raw = ""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _iter_route_import_sources(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        payload = payload.get("sources")
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        sources: list[dict[str, object]] = []
        for source_key, raw_source in payload.items():
            if isinstance(raw_source, dict):
                source = dict(raw_source)
            else:
                source = {"table_name": raw_source}
            source.setdefault("source", source_key)
            if not any(str(source.get(key) or "").strip() for key in ("table_id", "tableId", "id", "table_name", "name")):
                if str(source_key).startswith("tbl"):
                    source["table_id"] = source_key
                else:
                    source["table_name"] = source_key
            sources.append(source)
        return sources
    return []


def _source_field_value(fields: dict[str, object], configured_names: object, fallback_names: list[str]) -> object:
    names: list[str] = []
    if isinstance(configured_names, list):
        names.extend(str(name or "").strip() for name in configured_names)
    elif str(configured_names or "").strip():
        names.append(str(configured_names or "").strip())
    names.extend(fallback_names)
    for name in names:
        if name and name in fields:
            return fields.get(name)
    return ""


def _route_import_source_table_id(
    *,
    base_url: str,
    api_key: str,
    base_id: str,
    source: dict[str, object],
) -> str:
    explicit = str(source.get("table_id") or source.get("tableId") or source.get("id") or "").strip()
    if explicit:
        return explicit
    table_name = str(source.get("table_name") or source.get("name") or "").strip()
    if not table_name:
        return ""
    source_base_id = str(source.get("base_id") or source.get("baseId") or base_id or "").strip()
    return _discover_table_id(base_url=base_url, api_key=api_key, table_name=table_name, base_id=source_base_id)


def _source_required_purposes(source: dict[str, object]) -> set[str]:
    raw = source.get("required_purposes")
    if raw is None:
        raw = source.get("required_purpose")
    if raw is None:
        return set()
    if isinstance(raw, list):
        values = raw
    else:
        values = str(raw or "").replace(";", ",").split(",")
    return {str(value or "").strip().lower() for value in values if str(value or "").strip()}


def _route_import_source_rows(
    *,
    base_url: str,
    api_key: str,
    base_id: str,
    session_ref: str,
    raw_json: str = "",
    source_file: str = "",
) -> list[dict[str, object]]:
    payload = _load_route_import_sources_payload(raw_json=raw_json, source_file=source_file)
    rows: list[dict[str, object]] = []
    seen_route_keys: set[str] = set()
    for source in _iter_route_import_sources(payload):
        table_id = _route_import_source_table_id(base_url=base_url, api_key=api_key, base_id=base_id, source=source)
        if not table_id:
            continue
        required_purposes = _source_required_purposes(source)
        for record in _list_records(base_url=base_url, api_key=api_key, table_id=table_id):
            fields = dict(record.get("fields") or {})
            enabled = _source_field_value(
                fields,
                source.get("enabled_field") or source.get("enabled_fields"),
                ["whatsapp_ai_support_enabled", "WhatsApp AI Support Enabled", "enabled", "Enabled"],
            )
            if not _bool_value(enabled, _bool_value(source.get("default_enabled"), False)):
                continue
            if required_purposes:
                purpose = str(
                    _source_field_value(
                        fields,
                        source.get("purpose_field") or source.get("purpose_fields"),
                        ["whatsapp_ai_support_purpose", "WhatsApp AI Support Purpose", "purpose", "Purpose"],
                    )
                    or ""
                ).strip().lower()
                if purpose not in required_purposes:
                    continue
            inbound_number_digits = _source_field_value(
                fields,
                source.get("phone_field") or source.get("phone_fields"),
                ["whatsapp_ai_support_phone", "WhatsApp AI Support Phone", "phone", "Phone", "number", "Number"],
            )
            ai_key = str(
                source.get("heyy_ai_key")
                or source.get("ai_key")
                or source.get("persona_key")
                or _source_field_value(
                    fields,
                    source.get("ai_key_field") or source.get("heyy_ai_key_field"),
                    ["heyy_ai_key", "Heyy AI Key", "ai_key", "AI Key", "persona_key", "Persona Key"],
                )
                or EXECUTIVE_ASSISTANT_KEY
            ).strip()
            ai_name = str(
                source.get("heyy_ai_name")
                or source.get("ai_name")
                or _source_field_value(
                    fields,
                    source.get("ai_name_field") or source.get("heyy_ai_name_field"),
                    ["heyy_ai_name", "Heyy AI Name", "ai_name", "AI Name"],
                )
                or ""
            ).strip()
            row = _explicit_route_row(
                session_ref=session_ref,
                inbound_number_digits=str(inbound_number_digits or ""),
                heyy_ai_key=ai_key,
                heyy_ai_name=ai_name,
            )
            route_key = str(row.get("route_key") or "").strip()
            if not row or not route_key or route_key in seen_route_keys:
                continue
            source_name = str(source.get("source") or source.get("product_key") or source.get("table_name") or table_id).strip()
            if source_name:
                row["notes"] = f"{row['notes']} Imported Teable route source: {source_name}."
            rows.append(row)
            seen_route_keys.add(route_key)
    return rows


def _default_route_row(session_ref: str) -> dict[str, object]:
    return {
        "route_key": "default",
        "inbound_number_digits": "*",
        "heyy_ai_key": _env("EA_WHATSAPP_WEB_DEFAULT_HEYY_AI_KEY", DEFAULT_HEYY_AI_KEY),
        "heyy_ai_name": _env("EA_WHATSAPP_WEB_DEFAULT_HEYY_AI_NAME", DEFAULT_HEYY_AI_NAME),
        "behavior_prompt": _env("EA_WHATSAPP_WEB_HEYY_AI_BEHAVIOR_PROMPT", DEFAULT_BEHAVIOR_PROMPT),
        "memory_notes": _env("EA_WHATSAPP_WEB_HEYY_AI_MEMORY_NOTES", DEFAULT_MEMORY_NOTES),
        "pacing_hint": _env("EA_WHATSAPP_WEB_HEYY_AI_PACING_HINT", DEFAULT_PACING_HINT),
        "minimum_delay_seconds": _int_value(
            _env("EA_WHATSAPP_WEB_HEYY_AI_MINIMUM_DELAY_SECONDS", str(DEFAULT_MINIMUM_DELAY_SECONDS)),
            DEFAULT_MINIMUM_DELAY_SECONDS,
        ),
        "pre_reply_delay_min_seconds": _int_value(
            _env("EA_WHATSAPP_WEB_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS", str(DEFAULT_PRE_REPLY_DELAY_MIN_SECONDS)),
            DEFAULT_PRE_REPLY_DELAY_MIN_SECONDS,
        ),
        "pre_reply_delay_max_seconds": _int_value(
            _env("EA_WHATSAPP_WEB_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS", str(DEFAULT_PRE_REPLY_DELAY_MAX_SECONDS)),
            DEFAULT_PRE_REPLY_DELAY_MAX_SECONDS,
        ),
        "quiet_hours_start_hour": _int_value(
            _env("EA_WHATSAPP_WEB_HEYY_AI_QUIET_HOURS_START_HOUR", str(DEFAULT_QUIET_HOURS_START_HOUR)),
            DEFAULT_QUIET_HOURS_START_HOUR,
        ),
        "quiet_hours_end_hour": _int_value(
            _env("EA_WHATSAPP_WEB_HEYY_AI_QUIET_HOURS_END_HOUR", str(DEFAULT_QUIET_HOURS_END_HOUR)),
            DEFAULT_QUIET_HOURS_END_HOUR,
        ),
        "typing_delay_ms": _int_value(
            _env("EA_WHATSAPP_WEB_HEYY_AI_TYPING_DELAY_MS", str(DEFAULT_TYPING_DELAY_MS)),
            DEFAULT_TYPING_DELAY_MS,
        ),
        "typing_delay_ms_per_character": _int_value(
            _env("EA_WHATSAPP_WEB_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER", str(DEFAULT_TYPING_DELAY_MS_PER_CHARACTER)),
            DEFAULT_TYPING_DELAY_MS_PER_CHARACTER,
        ),
        "typing_status_enabled": _bool_value(_env("EA_WHATSAPP_WEB_HEYY_AI_TYPING_STATUS_ENABLED", "1"), True),
        "auto_reply_enabled": _bool_value(_env("EA_WHATSAPP_WEB_AUTOREPLY_ENABLED", "1"), True),
        "reply_text": _env("EA_WHATSAPP_WEB_AUTOREPLY_TEXT", DEFAULT_REPLY_TEXT),
        "enabled": True,
        "session_ref": session_ref,
        "updated_at": _now_iso(),
        "notes": "Default route. Replace inbound_number_digits with a private number to make this explicit.",
    }


def _persona_rows(session_ref: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    updated_at = _now_iso()
    for raw in HEYY_AI_PERSONAS:
        row = dict(raw)
        row["session_ref"] = session_ref
        row["updated_at"] = updated_at
        rows.append(row)
    return rows


def _audiobook_job_dirs(root: str) -> list[Path]:
    base = Path(str(root or "").strip())
    if not str(base):
        return []
    try:
        return sorted([path for path in base.iterdir() if path.is_dir()])
    except OSError:
        return []


def _load_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _receipt_is_whatsapp_audiobook(receipt: dict[str, object]) -> bool:
    whatsapp = dict(receipt.get("whatsapp") or {})
    if whatsapp:
        if _bool_value(whatsapp.get("sender_bound"), False) or _bool_value(whatsapp.get("session_bound"), False):
            return True
        if str(whatsapp.get("source") or "").strip() == "whatsapp_web_session":
            return True
    if str(receipt.get("public_share_whatsapp_delivery_status") or "").strip():
        return True
    if str(dict(receipt.get("playback_acceptance") or {}).get("source") or "").strip().startswith("whatsapp"):
        return True
    return False


def _audiobook_job_row_from_receipt(receipt: dict[str, object]) -> dict[str, object]:
    if not _receipt_is_whatsapp_audiobook(receipt):
        return {}
    metadata = dict(receipt.get("metadata") or {})
    source = dict(receipt.get("source") or {})
    playback = dict(receipt.get("playback_acceptance") or {})
    import_root = dict(receipt.get("audiobookshelf_import") or {})
    selection_root = dict(dict(receipt.get("render") or {}).get("voice_selection") or {})
    selected_voice = dict(selection_root.get("selected") or {})
    whatsapp = dict(receipt.get("whatsapp") or {})
    scheduler = dict(receipt.get("scheduler_resume") or {})
    job_id = str(receipt.get("job_id") or "").strip()
    if not job_id:
        return {}
    next_action = str(receipt.get("next_action") or "").strip()
    return {
        "projection_id": job_id,
        "job_id": job_id,
        "job_dir_name": str(receipt.get("job_dir_name") or "").strip(),
        "job_status": str(receipt.get("status") or "").strip(),
        "next_action": next_action,
        "updated_at": str(receipt.get("updated_at") or "").strip(),
        "observed_at": str(receipt.get("observed_at") or "").strip(),
        "title": str(metadata.get("title") or "").strip(),
        "author": str(metadata.get("author") or "").strip(),
        "source_kind": str(source.get("kind") or "").strip(),
        "source_filename": str(source.get("source_filename") or "").strip(),
        "public_share_status": str(receipt.get("public_share_status") or import_root.get("public_share_status") or "").strip(),
        "public_share_whatsapp_delivery_status": str(
            receipt.get("public_share_whatsapp_delivery_status")
            or import_root.get("public_share_whatsapp_delivery_status")
            or ""
        ).strip(),
        "public_share_whatsapp_followup_pending": _bool_value(
            receipt.get("public_share_whatsapp_followup_pending"),
            _bool_value(import_root.get("public_share_whatsapp_followup_pending"), False),
        ),
        "playback_status": str(playback.get("status") or "").strip(),
        "playback_source": str(playback.get("source") or "").strip(),
        "selected_voice_label": str(selected_voice.get("label") or "").strip(),
        "selected_voice_language": str(selected_voice.get("language") or "").strip(),
        "voice_selection_status": str(selection_root.get("status") or "").strip(),
        "voice_selected_at": str(selection_root.get("selected_at") or "").strip(),
        "sender_bound": _bool_value(whatsapp.get("sender_bound"), False),
        "session_bound": _bool_value(whatsapp.get("session_bound"), False),
        "operator_review_pending": next_action == "review_audiobook_playback_problem",
        "scheduler_next_action": str(scheduler.get("next_action") or "").strip(),
        "whatsapp_source": str(whatsapp.get("source") or "").strip(),
        "synced_at": _now_iso(),
    }


def _audiobook_job_rows_from_receipts(audiobook_jobs_root: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_projection_ids: set[str] = set()
    for job_dir in _audiobook_job_dirs(audiobook_jobs_root):
        receipt = _load_json_file(job_dir / "job_receipt.json")
        row = _audiobook_job_row_from_receipt(receipt)
        projection_id = str(row.get("projection_id") or "").strip()
        if not projection_id or projection_id in seen_projection_ids:
            continue
        rows.append(row)
        seen_projection_ids.add(projection_id)
    return rows


def _audiobook_jobs_root_accessible(audiobook_jobs_root: str) -> bool:
    raw_root = str(audiobook_jobs_root or "").strip()
    if not raw_root:
        return False
    base = Path(raw_root)
    try:
        return base.is_dir()
    except OSError:
        return False


def _route_rows_from_teable(*, base_url: str, api_key: str, route_table_id: str, session_ref: str) -> list[dict[str, object]]:
    records = _list_records(base_url=base_url, api_key=api_key, table_id=route_table_id)
    rows: list[dict[str, object]] = []
    for record in records:
        fields = dict(record.get("fields") or {})
        row_session = str(fields.get("session_ref") or "").strip()
        if row_session and row_session != session_ref:
            continue
        if fields.get("enabled") is False:
            continue
        route_key = str(fields.get("route_key") or "").strip()
        if route_key.startswith("disabled_reachability_"):
            continue
        inbound_field = str(fields.get("inbound_number_digits") or "").strip()
        if not inbound_field and route_key not in {"", "default"} and _digits_value(route_key) == route_key:
            continue
        inbound = str(inbound_field or route_key).strip()
        ai_key = str(fields.get("heyy_ai_key") or DEFAULT_HEYY_AI_KEY).strip()
        ai_name = str(fields.get("heyy_ai_name") or ai_key or DEFAULT_HEYY_AI_NAME).strip()
        behavior_prompt = str(fields.get("behavior_prompt") or DEFAULT_BEHAVIOR_PROMPT).strip()
        memory_notes = str(fields.get("memory_notes") or DEFAULT_MEMORY_NOTES).strip()
        pacing_hint = str(fields.get("pacing_hint") or DEFAULT_PACING_HINT).strip()
        reply_text = str(fields.get("reply_text") or DEFAULT_REPLY_TEXT).strip()
        if not inbound or not ai_key:
            continue
        old_lady_defaults = ai_key == DEFAULT_HEYY_AI_KEY
        rows.append(
            {
                "route_key": route_key,
                "inbound_number_digits": inbound,
                "ai_key": ai_key,
                "ai_name": ai_name,
                "behavior_prompt": behavior_prompt,
                "memory_notes": memory_notes,
                "pacing_hint": pacing_hint,
                "minimum_delay_seconds": (
                    _stale_zero_to_default(fields.get("minimum_delay_seconds"), DEFAULT_MINIMUM_DELAY_SECONDS)
                    if old_lady_defaults
                    else _int_value(fields.get("minimum_delay_seconds"), 0)
                ),
                "pre_reply_delay_min_seconds": (
                    _stale_zero_to_default(fields.get("pre_reply_delay_min_seconds"), DEFAULT_PRE_REPLY_DELAY_MIN_SECONDS)
                    if old_lady_defaults
                    else _int_value(fields.get("pre_reply_delay_min_seconds"), 0)
                ),
                "pre_reply_delay_max_seconds": (
                    _stale_zero_to_default(fields.get("pre_reply_delay_max_seconds"), DEFAULT_PRE_REPLY_DELAY_MAX_SECONDS)
                    if old_lady_defaults
                    else _int_value(fields.get("pre_reply_delay_max_seconds"), 0)
                ),
                "quiet_hours_start_hour": (
                    _stale_zero_to_default(fields.get("quiet_hours_start_hour"), DEFAULT_QUIET_HOURS_START_HOUR)
                    if old_lady_defaults
                    else _int_value(fields.get("quiet_hours_start_hour"), 0)
                ),
                "quiet_hours_end_hour": (
                    _stale_zero_to_default(fields.get("quiet_hours_end_hour"), DEFAULT_QUIET_HOURS_END_HOUR)
                    if old_lady_defaults
                    else _int_value(fields.get("quiet_hours_end_hour"), 0)
                ),
                "typing_delay_ms": _int_value(fields.get("typing_delay_ms"), DEFAULT_TYPING_DELAY_MS),
                "typing_delay_ms_per_character": (
                    _stale_zero_to_default(fields.get("typing_delay_ms_per_character"), DEFAULT_TYPING_DELAY_MS_PER_CHARACTER)
                    if old_lady_defaults
                    else _int_value(fields.get("typing_delay_ms_per_character"), 0)
                ),
                "typing_status_enabled": _bool_value(fields.get("typing_status_enabled"), True),
                "auto_reply_enabled": _bool_value(fields.get("auto_reply_enabled"), old_lady_defaults),
                "reply_text": reply_text,
            }
        )
    return rows


def _apply_routes_to_sidecar(
    args: argparse.Namespace,
    routes: list[dict[str, object]],
    sidecar_live_rows: list[dict[str, object]] | None = None,
    current_session_routes: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    compare_routes = current_session_routes
    if _preserve_sidecar_live_routes_enabled(args):
        if compare_routes is None:
            current_payload = _session_get(args, "heyy-ai-routes")
            compare_routes = list(current_payload.get("routes") or []) if isinstance(current_payload, dict) else []
            sidecar_live_rows = _sidecar_live_route_rows_from_payload(args, current_payload) if isinstance(current_payload, dict) else []
        routes = _merge_sidecar_live_route_overrides(
            routes,
            sidecar_live_rows or [],
        )
    target_hash = _route_compare_hash(routes)
    if compare_routes is None:
        current_payload = _session_get(args, "heyy-ai-routes")
        compare_routes = list(current_payload.get("routes") or []) if isinstance(current_payload, dict) else []
    if _normalized_sidecar_routes_for_compare(compare_routes) == _normalized_sidecar_routes_for_compare(routes):
        _store_route_compare_hash(args, target_hash, len(routes))
        return {
            "ok": True,
            "route_count": len(routes),
            "skipped_noop": True,
        }
    if _stored_route_compare_hash(args) == target_hash:
        return {
            "ok": True,
            "route_count": len(routes),
            "skipped_noop": True,
            "skipped_reason": "stored_route_compare_hash_match",
        }
    result = _session_put(args, "heyy-ai-routes", {"routes": routes})
    if bool(result.get("ok")):
        _store_route_compare_hash(args, target_hash, len(routes))
    return result


def _route_reachability_rows_from_sidecar(args: argparse.Namespace, routes: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    checked_at = _now_iso()
    for route in routes:
        inbound = str(route.get("inbound_number_digits") or "").strip()
        if not inbound or inbound == "*":
            continue
        route_key = str(route.get("route_key") or "").strip() or _route_key_for_inbound(
            session_ref=str(args.session_ref),
            inbound_number_digits=inbound,
        )
        try:
            payload = _session_get(args, f"recipients/{urllib.parse.quote(inbound, safe='')}")
        except Exception as exc:
            rows.append(
                {
                    "route_key": route_key,
                    "recipient_registered": False,
                    "recipient_resolution_method": "",
                    "recipient_chat_id_kind": "",
                    "recipient_lid_chat_id_present": False,
                    "recipient_phone_chat_id_present": False,
                    "recipient_reachability_checked_at": checked_at,
                    "recipient_reachability_reason": type(exc).__name__,
                }
            )
            continue
        registered = bool(payload.get("registered"))
        rows.append(
            {
                "route_key": route_key,
                "recipient_registered": registered,
                "recipient_resolution_method": str(payload.get("resolution_method") or "").strip(),
                "recipient_chat_id_kind": str(payload.get("chat_id_kind") or "").strip(),
                "recipient_lid_chat_id_present": bool(payload.get("lid_chat_id_present")),
                "recipient_phone_chat_id_present": bool(payload.get("phone_chat_id_present")),
                "recipient_reachability_checked_at": checked_at,
                "recipient_reachability_reason": "registered" if registered else "recipient_not_registered",
            }
        )
    return rows


def _message_projection_id(*, session_ref: str, message: dict[str, Any]) -> str:
    message_id = str(message.get("id") or "").strip()
    if message_id:
        return f"{session_ref}:wa-message:{hashlib.sha256(message_id.encode('utf-8')).hexdigest()[:24]}"
    material = json.dumps(message, sort_keys=True, ensure_ascii=True)
    return f"{session_ref}:wa-message:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _message_selected_button_hash(message: dict[str, Any]) -> str:
    selected_button_id = str(message.get("selected_button_id") or "").strip()
    if not selected_button_id:
        return ""
    return hashlib.sha256(selected_button_id.encode("utf-8")).hexdigest()[:24]


def _message_heyy_ai_projection(message: dict[str, Any]) -> tuple[str, str, bool]:
    matched = _bool_value(message.get("heyy_ai_route_matched"), False)
    if not matched:
        return "", "", False
    return (
        str(message.get("heyy_ai_key") or "").strip(),
        str(message.get("heyy_ai_name") or "").strip(),
        True,
    )


def _message_has_persistable_content(message: dict[str, Any]) -> bool:
    body_text = str(message.get("body_text") or "").strip()
    if body_text:
        if SYNTHETIC_NOTIFICATION_BODY_RE.fullmatch(body_text):
            return False
        return True
    if bool(message.get("body_present")):
        return True
    if bool(message.get("media_present")):
        return True
    if str(message.get("media_filename") or "").strip():
        return True
    if bool(message.get("selected_button_id_present")):
        return True
    if str(message.get("selected_button_id") or "").strip():
        return True
    return False


def _message_is_synthetic_notification(message: dict[str, Any]) -> bool:
    message_type = str(message.get("type") or "").strip()
    if message_type not in NON_CONVERSATION_MESSAGE_TYPES:
        return False
    return not _message_has_persistable_content(message)


def _conversation_query_suffix(
    args: argparse.Namespace,
    *,
    conversation_skip: int,
    conversation_take: int | None = None,
) -> str:
    query = urllib.parse.urlencode(
        {
            "take": int(conversation_take if conversation_take is not None else args.conversation_take),
            "skip": conversation_skip,
            "messages": int(args.message_limit),
            "fetch_timeout_ms": int(args.conversation_fetch_timeout_ms),
            "fetch_concurrency": int(args.conversation_fetch_concurrency),
        }
    )
    return f"conversations?{query}"


def _message_rows_from_conversation_payload(
    *,
    args: argparse.Namespace,
    payload: dict[str, Any],
    synced_at: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    scanned_message_count = 0
    skipped_synthetic_notification_count = 0
    for conversation in payload.get("conversations") or []:
        if not isinstance(conversation, dict):
            continue
        chat_ref = str(conversation.get("chat_ref") or "").strip()
        chat_id_kind = str(conversation.get("chat_id_kind") or "").strip()
        for message in conversation.get("messages") or []:
            if not isinstance(message, dict):
                continue
            scanned_message_count += 1
            message_type = str(message.get("type") or "").strip()
            if _message_is_synthetic_notification(message):
                skipped_synthetic_notification_count += 1
                continue
            body_text = str(message.get("body_text") or "").strip()
            heyy_ai_key, heyy_ai_name, heyy_ai_route_matched = _message_heyy_ai_projection(message)
            row = {
                "projection_id": _message_projection_id(session_ref=str(args.session_ref), message=message),
                "session_ref": str(args.session_ref),
                "chat_ref": chat_ref or str(message.get("chat_ref") or "").strip(),
                "message_id": str(message.get("id") or "").strip(),
                "direction": str(message.get("direction") or "").strip(),
                "sender_digits": str(message.get("sender_digits") or "").strip(),
                "heyy_ai_key": heyy_ai_key,
                "heyy_ai_name": heyy_ai_name,
                "heyy_ai_route_matched": heyy_ai_route_matched,
                "body_text": body_text,
                "body_present": bool(message.get("body_present") or body_text),
                "message_type": message_type,
                "message_timestamp": str(message.get("message_timestamp") or "").strip(),
                "selected_button_kind": str(message.get("selected_button_kind") or "").strip(),
                "selected_button_id_present": bool(message.get("selected_button_id_present")),
                "selected_button_hash": _message_selected_button_hash(message),
                "synced_at": synced_at,
                "chat_id_kind": str(message.get("chat_id_kind") or chat_id_kind).strip(),
                "from_me": bool(message.get("from_me")),
                "ack_label": str(message.get("ack_label") or "").strip(),
            }
            rows.append(row)
    payload["message_filter_summary"] = {
        "scanned_message_count": scanned_message_count,
        "persisted_message_count": len(rows),
        "skipped_synthetic_notification_count": skipped_synthetic_notification_count,
    }
    return rows


def _message_batch_from_sidecar(args: argparse.Namespace) -> tuple[list[dict[str, object]], dict[str, Any]]:
    conversation_skip = _conversation_start_skip_from_args(args)
    payload = _session_get(args, _conversation_query_suffix(args, conversation_skip=conversation_skip))
    rows = _message_rows_from_conversation_payload(args=args, payload=payload, synced_at=_now_iso())
    return rows, payload


def _aggregate_conversation_payloads(payloads: list[dict[str, Any]], *, start_skip: int, final_next_skip: int) -> dict[str, Any]:
    if not payloads:
        return {
            "conversation_count": 0,
            "conversation_page_complete": True,
            "conversation_pages": 0,
            "conversation_skip": start_skip,
            "conversation_total": 0,
            "message_filter_summary": {
                "scanned_message_count": 0,
                "persisted_message_count": 0,
                "skipped_synthetic_notification_count": 0,
            },
            "next_conversation_skip": 0,
            "ok": True,
        }
    final_payload = payloads[-1]
    return {
        "completed_refresh": any(bool(payload.get("completed_refresh")) for payload in payloads),
        "conversation_count": sum(_nonnegative_int(payload.get("conversation_count"), 0) for payload in payloads),
        "conversation_page_complete": bool(final_payload.get("conversation_page_complete")) or final_next_skip <= 0,
        "conversation_pages": len(payloads),
        "conversation_skip": start_skip,
        "conversation_total": max(_nonnegative_int(payload.get("conversation_total"), 0) for payload in payloads),
        "effective_conversation_take": _nonnegative_int(final_payload.get("effective_conversation_take"), 0),
        "fetch_concurrency": final_payload.get("fetch_concurrency"),
        "fetch_timeout_ms": final_payload.get("fetch_timeout_ms"),
        "max_message_rows_per_run": _nonnegative_int(final_payload.get("max_message_rows_per_run"), 0),
        "message_limit": final_payload.get("message_limit"),
        "message_filter_summary": {
            "scanned_message_count": sum(
                _nonnegative_int(dict(payload.get("message_filter_summary") or {}).get("scanned_message_count"), 0)
                for payload in payloads
            ),
            "persisted_message_count": sum(
                _nonnegative_int(dict(payload.get("message_filter_summary") or {}).get("persisted_message_count"), 0)
                for payload in payloads
            ),
            "skipped_synthetic_notification_count": sum(
                _nonnegative_int(
                    dict(payload.get("message_filter_summary") or {}).get("skipped_synthetic_notification_count"),
                    0,
                )
                for payload in payloads
            ),
        },
        "next_conversation_skip": final_next_skip,
        "ok": all(bool(payload.get("ok", True)) for payload in payloads),
        "ready": final_payload.get("ready"),
        "session_ref": final_payload.get("session_ref"),
        "status": final_payload.get("status"),
        "store_message_text": final_payload.get("store_message_text"),
    }


def _message_batches_from_sidecar(args: argparse.Namespace) -> tuple[list[dict[str, object]], dict[str, Any]]:
    if not bool(getattr(args, "sync_all_conversations", False)):
        return _message_batch_from_sidecar(args)

    start_skip = _conversation_start_skip_from_args(args)
    conversation_skip = start_skip
    completed_refresh = (
        getattr(args, "conversation_skip", None) is None
        and start_skip == 0
        and _conversation_state_completed(args)
    )
    conversation_take = _effective_conversation_take(args, completed_refresh=completed_refresh)
    max_pages = max(1, min(_int_value(getattr(args, "conversation_max_pages", 50), 50), 1000))
    if completed_refresh:
        max_pages = 1
    payloads: list[dict[str, Any]] = []
    rows: list[dict[str, object]] = []
    seen_projection_ids: set[str] = set()
    synced_at = _now_iso()
    final_next_skip = 0

    for _page in range(max_pages):
        payload = _session_get(
            args,
            _conversation_query_suffix(
                args,
                conversation_skip=conversation_skip,
                conversation_take=conversation_take,
            ),
        )
        payload = dict(payload)
        payload["effective_conversation_take"] = conversation_take
        payload["max_message_rows_per_run"] = _nonnegative_int(getattr(args, "max_message_rows_per_run", 0), 0)
        if completed_refresh:
            payload["completed_refresh"] = True
        payloads.append(payload)
        for row in _message_rows_from_conversation_payload(args=args, payload=payload, synced_at=synced_at):
            projection_id = str(row.get("projection_id") or "").strip()
            if projection_id and projection_id in seen_projection_ids:
                continue
            if projection_id:
                seen_projection_ids.add(projection_id)
            rows.append(row)

        next_skip = _nonnegative_int(payload.get("next_conversation_skip"), 0)
        final_next_skip = next_skip
        if bool(payload.get("conversation_page_complete")) or next_skip <= 0 or next_skip == conversation_skip:
            final_next_skip = 0 if bool(payload.get("conversation_page_complete")) else next_skip
            break
        conversation_skip = next_skip

    return rows, _aggregate_conversation_payloads(payloads, start_skip=start_skip, final_next_skip=final_next_skip)


def _message_rows_from_sidecar(args: argparse.Namespace) -> list[dict[str, object]]:
    rows, _payload = _message_batches_from_sidecar(args)
    return rows


def parse_args() -> argparse.Namespace:
    _load_env_file()
    parser = argparse.ArgumentParser(description="Sync WhatsApp Web session conversations and Heyy AI routes to Teable.")
    parser.add_argument("--base-url", default=_env("TEABLE_BASE_URL", DEFAULT_TEABLE_BASE_URL))
    parser.add_argument("--api-key", default=_env("TEABLE_API_KEY"))
    parser.add_argument("--base-id", default=_env("EA_WHATSAPP_WEB_TEABLE_BASE_ID") or _env("EA_ENV_TEABLE_BASE_ID"))
    parser.add_argument("--message-table-id", default=_env("EA_WHATSAPP_WEB_MESSAGES_TEABLE_TABLE_ID"))
    parser.add_argument("--persona-table-id", default=_env("EA_HEYY_AI_PERSONAS_TEABLE_TABLE_ID"))
    parser.add_argument("--route-table-id", default=_env("EA_WHATSAPP_WEB_ROUTES_TEABLE_TABLE_ID"))
    parser.add_argument("--audiobook-table-id", default=_env("EA_WHATSAPP_WEB_AUDIOBOOK_JOBS_TEABLE_TABLE_ID"))
    parser.add_argument("--message-table-name", default=_env("EA_WHATSAPP_WEB_MESSAGES_TEABLE_TABLE_NAME", DEFAULT_MESSAGE_TABLE_NAME))
    parser.add_argument("--persona-table-name", default=_env("EA_HEYY_AI_PERSONAS_TEABLE_TABLE_NAME", DEFAULT_PERSONA_TABLE_NAME))
    parser.add_argument("--route-table-name", default=_env("EA_WHATSAPP_WEB_ROUTES_TEABLE_TABLE_NAME", DEFAULT_ROUTE_TABLE_NAME))
    parser.add_argument("--audiobook-table-name", default=_env("EA_WHATSAPP_WEB_AUDIOBOOK_JOBS_TEABLE_TABLE_NAME", DEFAULT_AUDIOBOOK_TABLE_NAME))
    parser.add_argument("--audiobook-jobs-root", default=_env("EA_AUDIOBOOK_JOBS_ROOT", DEFAULT_AUDIOBOOK_JOBS_ROOT))
    parser.add_argument("--create-missing-tables", action="store_true", default=True)
    parser.add_argument("--no-create-missing-tables", action="store_false", dest="create_missing_tables")
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", DEFAULT_SESSION_REF))
    parser.add_argument("--session-api-token", default=_env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"))
    parser.add_argument("--auth-header-name", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"))
    parser.add_argument("--auth-header-prefix", default=os.environ.get("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "))
    parser.add_argument("--conversation-take", type=int, default=int(_env("EA_WHATSAPP_WEB_TEABLE_CONVERSATION_TAKE", "100") or "100"))
    parser.add_argument("--conversation-skip", type=int, default=_optional_int_env("EA_WHATSAPP_WEB_TEABLE_CONVERSATION_SKIP"))
    parser.add_argument("--message-limit", type=int, default=int(_env("EA_WHATSAPP_WEB_TEABLE_MESSAGE_LIMIT", "100") or "100"))
    parser.add_argument(
        "--max-message-rows-per-run",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_TEABLE_MAX_MESSAGE_ROWS_PER_RUN", "0") or "0"),
    )
    parser.add_argument(
        "--sync-all-conversations",
        action=argparse.BooleanOptionalAction,
        default=_bool_value(_env("EA_WHATSAPP_WEB_TEABLE_SYNC_ALL_CONVERSATIONS", "0"), False),
    )
    parser.add_argument(
        "--conversation-max-pages",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_TEABLE_CONVERSATION_MAX_PAGES", "50") or "50"),
    )
    parser.add_argument(
        "--conversation-fetch-timeout-ms",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_TIMEOUT_MS", "15000") or "15000"),
    )
    parser.add_argument(
        "--conversation-fetch-concurrency",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_CONCURRENCY", "6") or "6"),
    )
    parser.add_argument(
        "--conversation-page-state-file",
        default=_env("EA_WHATSAPP_WEB_TEABLE_SYNC_STATE_FILE", DEFAULT_SYNC_STATE_FILE),
    )
    parser.add_argument("--disable-conversation-page-state", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "30") or "30"))
    parser.add_argument(
        "--skip-messages",
        action="store_true",
        default=_bool_value(_env("EA_WHATSAPP_WEB_TEABLE_SKIP_MESSAGES", "0"), False),
    )
    parser.add_argument(
        "--skip-personas",
        action="store_true",
        default=_bool_value(_env("EA_WHATSAPP_WEB_TEABLE_SKIP_PERSONAS", "0"), False),
    )
    parser.add_argument(
        "--skip-routes",
        action="store_true",
        default=_bool_value(_env("EA_WHATSAPP_WEB_TEABLE_SKIP_ROUTES", "0"), False),
    )
    parser.add_argument(
        "--skip-audiobook-jobs",
        action="store_true",
        default=_bool_value(_env("EA_WHATSAPP_WEB_TEABLE_SKIP_AUDIOBOOK_JOBS", "0"), False),
    )
    parser.add_argument("--refresh-default-route", action="store_true", default=True)
    parser.add_argument("--no-refresh-default-route", action="store_false", dest="refresh_default_route")
    parser.add_argument("--map-inbound-number-digits", default=_env("EA_WHATSAPP_WEB_MAP_INBOUND_NUMBER_DIGITS"))
    parser.add_argument("--map-heyy-ai-key", default=_env("EA_WHATSAPP_WEB_MAP_HEYY_AI_KEY", EXECUTIVE_ASSISTANT_KEY))
    parser.add_argument("--map-heyy-ai-name", default=_env("EA_WHATSAPP_WEB_MAP_HEYY_AI_NAME"))
    parser.add_argument("--route-seeds-json", default=_env("EA_WHATSAPP_WEB_HEYY_AI_ROUTE_SEEDS_JSON"))
    parser.add_argument("--route-seeds-file", default=_env("EA_WHATSAPP_WEB_HEYY_AI_ROUTE_SEEDS_FILE"))
    preserve_sidecar_live_routes_default = _bool_value(
        _env(
            "EA_WHATSAPP_WEB_PRESERVE_SIDECAR_LIVE_ROUTES",
            _env("EA_WHATSAPP_WEB_PRESERVE_SIDECAR_HERTA_ROUTES", "1"),
        ),
        True,
    )
    parser.add_argument(
        "--preserve-sidecar-live-routes",
        action="store_true",
        dest="preserve_sidecar_live_routes",
        default=preserve_sidecar_live_routes_default,
    )
    parser.add_argument(
        "--no-preserve-sidecar-live-routes",
        action="store_false",
        dest="preserve_sidecar_live_routes",
    )
    parser.add_argument(
        "--preserve-sidecar-herta-routes",
        action="store_true",
        dest="preserve_sidecar_live_routes",
    )
    parser.add_argument(
        "--no-preserve-sidecar-herta-routes",
        action="store_false",
        dest="preserve_sidecar_live_routes",
    )
    parser.add_argument("--route-import-sources-json", default=_env("EA_WHATSAPP_WEB_ROUTE_IMPORT_SOURCES_JSON"))
    parser.add_argument("--route-import-sources-file", default=_env("EA_WHATSAPP_WEB_ROUTE_IMPORT_SOURCES_FILE"))
    parser.add_argument(
        "--tolerate-session-api-unavailable",
        action=argparse.BooleanOptionalAction,
        default=_bool_value(_env("EA_WHATSAPP_WEB_TEABLE_TOLERATE_SESSION_API_UNAVAILABLE", "1"), True),
    )
    return parser.parse_args()


def _session_api_waiting_receipt(
    *,
    args: argparse.Namespace,
    exc: SessionApiUnavailable,
    route_table_id: str = "",
    persona_table_id: str = "",
    message_table_id: str = "",
    audiobook_table_id: str = "",
) -> dict[str, object]:
    reason = f"{exc.operation.replace('_request', '')}_unavailable"
    waiting_at = _now_iso()
    return {
        "status": "waiting",
        "ok": True,
        "ready": False,
        "reason": reason,
        "session_api_operation": exc.operation,
        "detail": exc.detail,
        "session_ref": str(args.session_ref),
        "route_table_id": route_table_id,
        "persona_table_id": persona_table_id,
        "message_table_id": message_table_id,
        "audiobook_table_id": audiobook_table_id,
        "waiting_at": waiting_at,
        "updated_at": waiting_at,
    }


def _record_waiting_sync_state(args: argparse.Namespace, receipt: dict[str, object]) -> None:
    if bool(getattr(args, "disable_conversation_page_state", False)):
        return
    state_file = str(getattr(args, "conversation_page_state_file", "") or "").strip()
    if not state_file:
        return
    state = _load_sync_state(state_file)
    state.update(receipt)
    state["session_ref"] = str(getattr(args, "session_ref", "") or receipt.get("session_ref") or "").strip()
    state.setdefault("conversation_count", _nonnegative_int(state.get("conversation_count"), 0))
    state.setdefault("conversation_total", _nonnegative_int(state.get("conversation_total"), 0))
    state.setdefault("next_conversation_skip", _nonnegative_int(state.get("next_conversation_skip"), 0))
    _save_sync_state(state_file, state)


def main() -> int:
    args = parse_args()
    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise SystemExit("teable_api_key_missing")
    base_url = str(args.base_url or DEFAULT_TEABLE_BASE_URL).strip().rstrip("/")
    base_id = str(args.base_id or "").strip()

    route_table_id = ""
    persona_table_id = ""
    message_table_id = ""
    audiobook_table_id = ""
    created_route_table = False
    created_persona_table = False
    created_message_table = False
    created_audiobook_table = False
    route_fields_created = 0
    persona_fields_created = 0
    message_fields_created = 0
    audiobook_fields_created = 0
    message_page_state: dict[str, object] = {}
    message_payload: dict[str, object] = {}
    persona_count = 0
    persona_upsert = {"created": 0, "updated": 0, "total": 0}
    persona_cleanup = {"deleted": 0, "failed": 0, "total": 0}
    route_count = 0
    route_cleanup = {"disabled": 0, "failed": 0, "total": 0}
    route_projection_cleanup = {"deleted": 0, "failed": 0, "total": 0}
    route_stale_cleanup = {"deleted": 0, "failed": 0, "total": 0}
    route_import_count = 0
    route_upsert = {"created": 0, "updated": 0, "total": 0}
    route_reachability_upsert = {"created": 0, "updated": 0, "total": 0}
    route_apply = {"ok": False, "route_count": 0}
    message_upsert = {"created": 0, "updated": 0, "total": 0}
    message_cleanup = {"deleted": 0, "failed": 0, "total": 0}
    audiobook_upsert = {"created": 0, "updated": 0, "total": 0}
    audiobook_job_count = 0
    audiobook_cleanup = {"deleted": 0, "failed": 0, "total": 0}
    current_sidecar_route_count = 0
    sidecar_live_route_count = 0
    route_rows_to_upsert_count = 0
    preserved_live_route_count = 0

    if not args.skip_personas:
        persona_table_id, created_persona_table = _ensure_table(
            base_url=base_url,
            api_key=api_key,
            base_id=base_id,
            table_id=str(args.persona_table_id or "").strip(),
            table_name=str(args.persona_table_name),
            fields=PERSONA_FIELDS,
            create_missing=bool(args.create_missing_tables),
        )
        persona_fields_created = _ensure_fields(base_url=base_url, api_key=api_key, table_id=persona_table_id, fields=PERSONA_FIELDS)
        persona_cleanup = _cleanup_persona_rows(base_url=base_url, api_key=api_key, persona_table_id=persona_table_id)
        persona_rows = _persona_rows(str(args.session_ref))
        persona_count = len(persona_rows)
        persona_upsert = _upsert_rows(
            base_url=base_url,
            api_key=api_key,
            table_id=persona_table_id,
            key_field="persona_key",
            rows=persona_rows,
        )

    try:
        if not args.skip_routes:
            route_table_id, created_route_table = _ensure_table(
                base_url=base_url,
                api_key=api_key,
                base_id=base_id,
                table_id=str(args.route_table_id or "").strip(),
                table_name=str(args.route_table_name),
                fields=ROUTE_FIELDS,
                create_missing=bool(args.create_missing_tables),
            )
            route_fields_created = _ensure_fields(base_url=base_url, api_key=api_key, table_id=route_table_id, fields=ROUTE_FIELDS)
            route_projection_cleanup = _cleanup_route_rows(base_url=base_url, api_key=api_key, route_table_id=route_table_id)
            route_stale_cleanup = _cleanup_stale_route_rows(
                base_url=base_url,
                api_key=api_key,
                route_table_id=route_table_id,
                session_ref=str(args.session_ref),
            )
            route_cleanup = _cleanup_reachability_only_route_rows(
                base_url=base_url,
                api_key=api_key,
                route_table_id=route_table_id,
                session_ref=str(args.session_ref),
            )
            current_sidecar_payload = _session_get(args, "heyy-ai-routes")
            current_session_routes = list(current_sidecar_payload.get("routes") or []) if isinstance(current_sidecar_payload, dict) else []
            current_sidecar_route_count = len(current_session_routes)
            sidecar_live_rows = (
                _sidecar_live_route_rows_from_payload(args, current_sidecar_payload)
                if _preserve_sidecar_live_routes_enabled(args) and isinstance(current_sidecar_payload, dict)
                else []
            )
            sidecar_live_route_count = len(sidecar_live_rows)
            route_rows_to_upsert: list[dict[str, object]] = []
            if args.refresh_default_route:
                route_rows_to_upsert.append(_default_route_row(str(args.session_ref)))
            explicit_route = _explicit_route_row(
                session_ref=str(args.session_ref),
                inbound_number_digits=str(args.map_inbound_number_digits or ""),
                heyy_ai_key=str(args.map_heyy_ai_key or EXECUTIVE_ASSISTANT_KEY),
                heyy_ai_name=str(args.map_heyy_ai_name or ""),
            )
            if explicit_route:
                route_rows_to_upsert.append(explicit_route)
            route_rows_to_upsert.extend(
                _route_seed_rows(
                    session_ref=str(args.session_ref),
                    raw_json=str(args.route_seeds_json or ""),
                    seed_file=str(args.route_seeds_file or ""),
                )
            )
            imported_route_rows = _route_import_source_rows(
                base_url=base_url,
                api_key=api_key,
                base_id=base_id,
                session_ref=str(args.session_ref),
                raw_json=str(args.route_import_sources_json or ""),
                source_file=str(args.route_import_sources_file or ""),
            )
            route_import_count = len(imported_route_rows)
            route_rows_to_upsert.extend(imported_route_rows)
            route_rows_to_upsert = _route_rows_with_sidecar_live_projection(route_rows_to_upsert, sidecar_live_rows)
            route_rows_to_upsert_count = len(route_rows_to_upsert)
            if sidecar_live_rows:
                live_route_keys = {
                    str(row.get("route_key") or "").strip()
                    for row in sidecar_live_rows
                    if str(row.get("route_key") or "").strip()
                }
                preserved_live_route_count = sum(
                    1
                    for row in route_rows_to_upsert
                    if str(row.get("route_key") or "").strip() in live_route_keys
                )
            if route_rows_to_upsert:
                route_upsert = _upsert_rows(
                    base_url=base_url,
                    api_key=api_key,
                    table_id=route_table_id,
                    key_field="route_key",
                    rows=route_rows_to_upsert,
                )
            routes = _route_rows_from_teable(base_url=base_url, api_key=api_key, route_table_id=route_table_id, session_ref=str(args.session_ref))
            if not routes:
                default_row = _default_route_row(str(args.session_ref))
                route_upsert = _upsert_rows(base_url=base_url, api_key=api_key, table_id=route_table_id, key_field="route_key", rows=[default_row])
                routes = _route_rows_from_teable(base_url=base_url, api_key=api_key, route_table_id=route_table_id, session_ref=str(args.session_ref))
            route_count = len(routes)
            route_apply = _apply_routes_to_sidecar(
                args,
                routes,
                sidecar_live_rows=sidecar_live_rows,
                current_session_routes=current_session_routes,
            )
            reachability_rows = _route_reachability_rows_from_sidecar(args, routes)
            if reachability_rows:
                route_reachability_upsert = _upsert_rows(
                    base_url=base_url,
                    api_key=api_key,
                    table_id=route_table_id,
                    key_field="route_key",
                    rows=reachability_rows,
                )

        if not args.skip_messages:
            message_table_id, created_message_table = _ensure_table(
                base_url=base_url,
                api_key=api_key,
                base_id=base_id,
                table_id=str(args.message_table_id or "").strip(),
                table_name=str(args.message_table_name),
                fields=MESSAGE_FIELDS,
                create_missing=bool(args.create_missing_tables),
            )
            message_fields_created = _ensure_fields(base_url=base_url, api_key=api_key, table_id=message_table_id, fields=MESSAGE_FIELDS)
            message_cleanup = _cleanup_projectionless_rows(base_url=base_url, api_key=api_key, table_id=message_table_id)
            rows, message_payload = _message_batches_from_sidecar(args)
            message_upsert = _upsert_rows(
                base_url=base_url,
                api_key=api_key,
                table_id=message_table_id,
                key_field="projection_id",
                rows=rows,
                lookup_existing_by_keys=True,
            )
            message_page_state = _update_conversation_page_state(args=args, payload=message_payload, message_upsert=message_upsert)

        if not bool(getattr(args, "skip_audiobook_jobs", False)):
            audiobook_jobs_root = str(getattr(args, "audiobook_jobs_root", DEFAULT_AUDIOBOOK_JOBS_ROOT) or "")
            audiobook_table_id, created_audiobook_table = _ensure_table(
                base_url=base_url,
                api_key=api_key,
                base_id=base_id,
                table_id=str(getattr(args, "audiobook_table_id", "") or "").strip(),
                table_name=str(getattr(args, "audiobook_table_name", DEFAULT_AUDIOBOOK_TABLE_NAME)),
                fields=AUDIOBOOK_FIELDS,
                create_missing=bool(args.create_missing_tables),
            )
            audiobook_fields_created = _ensure_fields(
                base_url=base_url,
                api_key=api_key,
                table_id=audiobook_table_id,
                fields=AUDIOBOOK_FIELDS,
            )
            audiobook_cleanup = _cleanup_projectionless_audiobook_rows(
                base_url=base_url,
                api_key=api_key,
                audiobook_table_id=audiobook_table_id,
            )
            audiobook_rows = _audiobook_job_rows_from_receipts(audiobook_jobs_root)
            if _audiobook_jobs_root_accessible(audiobook_jobs_root):
                stale_audiobook_cleanup = _cleanup_stale_audiobook_rows(
                    base_url=base_url,
                    api_key=api_key,
                    audiobook_table_id=audiobook_table_id,
                    current_projection_ids={
                        str(row.get("projection_id") or "").strip()
                        for row in audiobook_rows
                        if str(row.get("projection_id") or "").strip()
                    },
                )
                audiobook_cleanup = {
                    "deleted": int(audiobook_cleanup.get("deleted") or 0) + int(stale_audiobook_cleanup.get("deleted") or 0),
                    "failed": int(audiobook_cleanup.get("failed") or 0) + int(stale_audiobook_cleanup.get("failed") or 0),
                    "total": int(audiobook_cleanup.get("total") or 0) + int(stale_audiobook_cleanup.get("total") or 0),
                }
            audiobook_job_count = len(audiobook_rows)
            audiobook_upsert = _upsert_rows(
                base_url=base_url,
                api_key=api_key,
                table_id=audiobook_table_id,
                key_field="projection_id",
                rows=audiobook_rows,
                lookup_existing_by_keys=True,
            )
    except SessionApiUnavailable as exc:
        if not bool(getattr(args, "tolerate_session_api_unavailable", True)):
            raise
        receipt = _session_api_waiting_receipt(
            args=args,
            exc=exc,
            route_table_id=route_table_id,
            persona_table_id=persona_table_id,
            message_table_id=message_table_id,
            audiobook_table_id=audiobook_table_id,
        )
        _record_waiting_sync_state(args, receipt)
        print(
            json.dumps(
                receipt
            )
        )
        return 0
    except SystemExit as exc:
        unavailable = _session_api_unavailable_from_exit(exc)
        if unavailable is None:
            unavailable = _teable_api_unavailable_from_exit(exc)
        if unavailable is None or not bool(getattr(args, "tolerate_session_api_unavailable", True)):
            raise
        receipt = _session_api_waiting_receipt(
            args=args,
            exc=unavailable,
            route_table_id=route_table_id,
            persona_table_id=persona_table_id,
            message_table_id=message_table_id,
            audiobook_table_id=audiobook_table_id,
        )
        _record_waiting_sync_state(args, receipt)
        print(
            json.dumps(
                receipt
            )
        )
        return 0

    print(
        json.dumps(
            {
                "status": "pass",
                "session_ref": str(args.session_ref),
                "route_table_id": route_table_id,
                "persona_table_id": persona_table_id,
                "message_table_id": message_table_id,
                "audiobook_table_id": audiobook_table_id,
                "created_route_table": created_route_table,
                "created_persona_table": created_persona_table,
                "created_message_table": created_message_table,
                "created_audiobook_table": created_audiobook_table,
                "route_fields_created": route_fields_created,
                "persona_fields_created": persona_fields_created,
                "message_fields_created": message_fields_created,
                "audiobook_fields_created": audiobook_fields_created,
                "persona_count": persona_count,
                "persona_cleanup": persona_cleanup,
                "route_count": route_count,
                "audiobook_job_count": audiobook_job_count,
                "message_cleanup": message_cleanup,
                "route_projection_cleanup": route_projection_cleanup,
                "audiobook_cleanup": audiobook_cleanup,
                "route_cleanup": route_cleanup,
                "route_import_count": route_import_count,
                "current_sidecar_route_count": current_sidecar_route_count,
                "sidecar_live_route_count": sidecar_live_route_count,
                "route_rows_to_upsert_count": route_rows_to_upsert_count,
                "preserved_live_route_count": preserved_live_route_count,
                "route_stale_cleanup": route_stale_cleanup,
                "route_apply_ok": bool(route_apply.get("ok")),
                "route_apply_count": _int_value(route_apply.get("route_count"), route_count),
                "persona_upsert": persona_upsert,
                "route_upsert": route_upsert,
                "route_reachability_upsert": route_reachability_upsert,
                "message_upsert": message_upsert,
                "audiobook_upsert": audiobook_upsert,
                "message_filter_summary": dict(message_payload.get("message_filter_summary") or {}),
                "message_page_state": message_page_state,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
