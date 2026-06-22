from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def test_compose_override_declares_whatsapp_web_session_sidecar() -> None:
    compose = (ROOT / "docker-compose.whatsapp-web-session.yml").read_text(encoding="utf-8")
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    assert "ea-whatsapp-web-session:" in compose
    assert "container_name: ea-whatsapp-web-session" in compose
    assert "WA_WEB_SESSION_REF=${EA_WHATSAPP_WEB_DEFAULT_SESSION_REF:-default-wa-web}" in compose
    assert 'process.env.WA_WEB_SESSION_REF || "default-wa-web"' in server
    assert "WA_WEB_SESSION_API_TOKEN=${EA_WHATSAPP_WEB_SESSION_API_TOKEN:-}" in compose
    assert "127.0.0.1:${EA_WHATSAPP_WEB_SESSION_HOST_PORT:-8098}:8098" in compose
    assert "ea_whatsapp_web_session:/data/session" in compose
    assert "name: ea_whatsapp_web_session" in compose
    assert "ea-whatsapp-web-activator:" in compose
    assert "container_name: ea-whatsapp-web-activator" in compose
    assert "ea-whatsapp-web-action-processor:" in compose
    assert "container_name: ea-whatsapp-web-action-processor" in compose
    assert "ea-whatsapp-web-teable-sync:" in compose
    assert "container_name: ea-whatsapp-web-teable-sync" in compose
    assert "EA_WHATSAPP_WEB_ACTIVATOR_ENABLED=${EA_WHATSAPP_WEB_ACTIVATOR_ENABLED:-0}" in compose
    assert "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=${EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED:-1}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_SYNC_ENABLED=${EA_WHATSAPP_WEB_TEABLE_SYNC_ENABLED:-0}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_SYNC_INTERVAL_SECONDS=${EA_WHATSAPP_WEB_TEABLE_SYNC_INTERVAL_SECONDS:-30}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_CONVERSATION_TAKE=${EA_WHATSAPP_WEB_TEABLE_CONVERSATION_TAKE:-25}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_MESSAGE_LIMIT=${EA_WHATSAPP_WEB_TEABLE_MESSAGE_LIMIT:-50}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_SYNC_ALL_CONVERSATIONS=${EA_WHATSAPP_WEB_TEABLE_SYNC_ALL_CONVERSATIONS:-1}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_CONVERSATION_MAX_PAGES=${EA_WHATSAPP_WEB_TEABLE_CONVERSATION_MAX_PAGES:-1}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_TIMEOUT_MS=${EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_TIMEOUT_MS:-15000}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_CONCURRENCY=${EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_CONCURRENCY:-6}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_COMPLETED_REFRESH_CONVERSATION_TAKE=${EA_WHATSAPP_WEB_TEABLE_COMPLETED_REFRESH_CONVERSATION_TAKE:-5}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_SYNC_STATE_FILE=${EA_WHATSAPP_WEB_TEABLE_SYNC_STATE_FILE:-/data/whatsapp-teable-sync/state.json}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_SYNC_RUN_TIMEOUT_SECONDS=${EA_WHATSAPP_WEB_TEABLE_SYNC_RUN_TIMEOUT_SECONDS:-300}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_SYNC_STALE_SECONDS=${EA_WHATSAPP_WEB_TEABLE_SYNC_STALE_SECONDS:-600}" in compose
    assert "EA_RESPONSES_PROVIDER_LEDGER_DIR=/data/whatsapp-teable-sync" in compose
    assert "EA_RESPONSES_PROVIDER_LEDGER_DIR=/data/whatsapp-actions" in compose
    assert "EA_WHATSAPP_WEB_MESSAGES_TEABLE_TABLE_ID=${EA_WHATSAPP_WEB_MESSAGES_TEABLE_TABLE_ID:-}" in compose
    assert "EA_WHATSAPP_WEB_ROUTES_TEABLE_TABLE_ID=${EA_WHATSAPP_WEB_ROUTES_TEABLE_TABLE_ID:-}" in compose
    assert "EA_HEYY_AI_PERSONAS_TEABLE_TABLE_ID=${EA_HEYY_AI_PERSONAS_TEABLE_TABLE_ID:-}" in compose
    assert "EA_WHATSAPP_WEB_HEYY_AI_ROUTE_SEEDS_JSON=${EA_WHATSAPP_WEB_HEYY_AI_ROUTE_SEEDS_JSON:-}" in compose
    assert "EA_WHATSAPP_WEB_HEYY_AI_ROUTE_SEEDS_FILE=${EA_WHATSAPP_WEB_HEYY_AI_ROUTE_SEEDS_FILE:-}" in compose
    assert "EA_WHATSAPP_WEB_ROUTE_IMPORT_SOURCES_JSON=${EA_WHATSAPP_WEB_ROUTE_IMPORT_SOURCES_JSON:-}" in compose
    assert "EA_WHATSAPP_WEB_ROUTE_IMPORT_SOURCES_FILE=${EA_WHATSAPP_WEB_ROUTE_IMPORT_SOURCES_FILE:-}" in compose
    assert "TEABLE_BASE_URL=${TEABLE_RUNTIME_BASE_URL:-https://app.teable.ai}" in compose
    assert '"host.docker.internal:host-gateway"' in compose
    assert "EA_WHATSAPP_WEB_ACTION_STATE_FILE=${EA_WHATSAPP_WEB_ACTION_STATE_FILE:-/data/whatsapp-actions/processed.json}" in compose
    assert "EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_STATUS_ENABLED=${EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_STATUS_ENABLED:-1}" in compose
    assert (
        "EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS="
        "${EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS:-60}"
    ) in compose
    assert (
        "EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS="
        "${EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS:-300}"
    ) in compose
    assert "EA_WHATSAPP_AUDIOBOOK_RESUME_DUE=${EA_WHATSAPP_AUDIOBOOK_RESUME_DUE:-1}" in compose
    assert "EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED=${EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED:-1}" in compose
    assert "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED=${EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED:-1}" in compose
    assert "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER=${EA_AUDIOBOOK_UNMIXR_AUTO_RENDER:-1}" in compose
    assert "EA_AUDIOBOOK_EBOOK_CONVERT_BIN=${EA_AUDIOBOOK_EBOOK_CONVERT_BIN:-ebook-convert}" in compose
    assert "EA_AUDIOBOOK_KINDLE_CONVERT_TIMEOUT_SECONDS=${EA_AUDIOBOOK_KINDLE_CONVERT_TIMEOUT_SECONDS:-900}" in compose
    assert "EA_AUDIOBOOKSHELF_AUTO_IMPORT=${EA_AUDIOBOOKSHELF_AUTO_IMPORT:-1}" in compose
    assert "EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED=${EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED:-1}" in compose
    assert "EA_AUDIOBOOKSHELF_API_BASE_URL=${EA_AUDIOBOOKSHELF_API_BASE_URL:-}" in compose
    assert "EA_AUDIOBOOKSHELF_API_TOKEN=${EA_AUDIOBOOKSHELF_API_TOKEN:-}" in compose
    assert "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID=${EA_WHATSAPP_WEB_DEFAULT_BINDING_ID:-ea-whatsapp-web-session}" in compose
    assert "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID=${EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID:-principal-default}" in compose
    assert "EA_WHATSAPP_WEB_DEFAULT_SESSION_REF=${EA_WHATSAPP_WEB_DEFAULT_SESSION_REF:-default-wa-web}" in compose
    assert "EA_WHATSAPP_WEB_DEFAULT_BROWSER_PROFILE_REF=${EA_WHATSAPP_WEB_DEFAULT_BROWSER_PROFILE_REF:-docker-volume://ea_whatsapp_web_session}" in compose
    assert "EA_WHATSAPP_WEB_SESSION_API_BASE_URL=${EA_WHATSAPP_WEB_SESSION_API_BASE_URL:-http://ea-whatsapp-web-session:8098}" in compose
    assert "EA_WHATSAPP_WEB_ACTIVATION_WATCH_INTERVAL_SECONDS=${EA_WHATSAPP_WEB_ACTIVATION_WATCH_INTERVAL_SECONDS:-5}" in compose
    assert "EA_WHATSAPP_WEB_ACTIVATION_WATCH_MAX_SECONDS=${EA_WHATSAPP_WEB_ACTIVATION_WATCH_MAX_SECONDS:-0}" in compose
    assert "EA_WHATSAPP_WEB_ACTIVATION_SEND_TEST=${EA_WHATSAPP_WEB_ACTIVATION_SEND_TEST:-0}" in compose
    assert "EA_WHATSAPP_WEB_ACTION_STATE_STALE_SECONDS=${EA_WHATSAPP_WEB_ACTION_STATE_STALE_SECONDS:-600}" in compose
    assert "WA_WEB_AUTOREPLY_ENABLED=${EA_WHATSAPP_WEB_AUTOREPLY_ENABLED:-0}" in compose
    assert "WA_WEB_AUTOREPLY_TEXT=${EA_WHATSAPP_WEB_AUTOREPLY_TEXT:-Na geh... ich bin die Herta." in compose
    assert "zurück" in compose
    assert "WA_WEB_AUTOREPLY_ALLOWED_RECIPIENTS=${EA_WHATSAPP_WEB_AUTOREPLY_ALLOWED_RECIPIENTS:-}" in compose
    assert "WA_WEB_DEFAULT_HEYY_AI_KEY=${EA_WHATSAPP_WEB_DEFAULT_HEYY_AI_KEY:-empathetic_slow_typing_old_lady}" in compose
    assert "WA_WEB_DEFAULT_HEYY_AI_NAME=${EA_WHATSAPP_WEB_DEFAULT_HEYY_AI_NAME:-Herta (Heyy Lady)}" in compose
    assert "WA_WEB_HEYY_AI_TYPING_DELAY_MS=${EA_WHATSAPP_WEB_HEYY_AI_TYPING_DELAY_MS:-6500}" in compose
    assert "WA_WEB_HEYY_AI_MAX_TYPING_DELAY_MS=${EA_WHATSAPP_WEB_HEYY_AI_MAX_TYPING_DELAY_MS:-3600000}" in compose
    assert "WA_WEB_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS=${EA_WHATSAPP_WEB_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS:-60}" in compose
    assert "WA_WEB_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS=${EA_WHATSAPP_WEB_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS:-900}" in compose
    assert "WA_WEB_HEYY_AI_QUIET_HOURS_START_HOUR=${EA_WHATSAPP_WEB_HEYY_AI_QUIET_HOURS_START_HOUR:-21}" in compose
    assert "WA_WEB_HEYY_AI_QUIET_HOURS_END_HOUR=${EA_WHATSAPP_WEB_HEYY_AI_QUIET_HOURS_END_HOUR:-6}" in compose
    assert "WA_WEB_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER=${EA_WHATSAPP_WEB_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER:-4000}" in compose
    assert "WA_WEB_HEYY_AI_TYPING_STATUS_ENABLED=${EA_WHATSAPP_WEB_HEYY_AI_TYPING_STATUS_ENABLED:-1}" in compose
    assert "WA_WEB_CONVERSATION_FETCH_TIMEOUT_MS=${EA_WHATSAPP_WEB_CONVERSATION_FETCH_TIMEOUT_MS:-15000}" in compose
    assert "WA_WEB_CONVERSATION_FETCH_CONCURRENCY=${EA_WHATSAPP_WEB_CONVERSATION_FETCH_CONCURRENCY:-6}" in compose
    assert "WA_WEB_POLL_BUTTONS_ENABLED=${EA_WHATSAPP_WEB_POLL_BUTTONS_ENABLED:-1}" in compose
    assert "WA_WEB_NATIVE_BUTTONS_ENABLED=${EA_WHATSAPP_WEB_NATIVE_BUTTONS_ENABLED:-0}" in compose
    assert "WA_WEB_JSON_LIMIT=${EA_WHATSAPP_WEB_JSON_LIMIT:-48mb}" in compose
    assert "EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED=${EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED:-0}" in compose
    assert "EA_WHATSAPP_WEB_TG_SUMMARY_EVERY=${EA_WHATSAPP_WEB_TG_SUMMARY_EVERY:-5}" in compose
    assert "EA_WHATSAPP_WEB_TG_SUMMARY_CHAT_ID=${EA_WHATSAPP_WEB_TG_SUMMARY_CHAT_ID:-}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_SYNC_ALL_CONVERSATIONS=${EA_WHATSAPP_WEB_TEABLE_SYNC_ALL_CONVERSATIONS:-1}" in compose
    assert "EA_WHATSAPP_WEB_TEABLE_CONVERSATION_MAX_PAGES=${EA_WHATSAPP_WEB_TEABLE_CONVERSATION_MAX_PAGES:-1}" in compose
    assert "timeout \"$${EA_WHATSAPP_WEB_TEABLE_SYNC_RUN_TIMEOUT_SECONDS:-300}s\" python /app/scripts/sync_whatsapp_web_session_to_teable.py" in compose
    assert '|| code="$$?"' in compose
    assert "whatsapp_web_teable_sync_run_failed" in compose
    assert "PYTHONUNBUFFERED=1" in compose
    assert "python /app/scripts/watch_whatsapp_web_session_activation.py" in compose
    assert "python /app/scripts/process_whatsapp_web_session_actions.py" in compose
    assert "python /app/scripts/sync_whatsapp_web_session_to_teable.py" in compose
    assert "python /app/scripts/check_whatsapp_web_teable_sync_readiness.py" in compose
    assert "whatsapp_web_session_activator_complete" in compose
    assert "pathlib.Path('/app/scripts/watch_whatsapp_web_session_activation.py')" in compose
    assert "python /app/scripts/check_whatsapp_web_action_processor_readiness.py --probe-sidecar" in compose
    assert "ea_whatsapp_web_actions:/data/whatsapp-actions" in compose
    assert "ea_whatsapp_web_teable_sync:/data/whatsapp-teable-sync" in compose
    assert "EA_AUDIOBOOK_JOBS_HOST_ROOT" not in compose
    assert "EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT" not in compose
    assert "/mnt/pcloud/EA:/mnt/pcloud/EA" not in compose
    assert "/mnt/pcloud/media:/mnt/pcloud/media" not in compose
    assert "name: ea_whatsapp_web_actions" in compose
    assert "name: ea_whatsapp_web_teable_sync" in compose


def test_main_compose_mounts_whatsapp_web_runtime_code_into_ea_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "./ea/app/api/routes/channels.py:/app/app/api/routes/channels.py:ro" in compose
    assert "./ea/app/services/whatsapp_delivery_router.py:/app/app/services/whatsapp_delivery_router.py:ro" in compose
    assert "./ea/app/services/whatsapp_web_session_delivery.py:/app/app/services/whatsapp_web_session_delivery.py:ro" in compose
    assert "./ea/app/services/whatsapp_delivery_outbox.py:/app/app/services/whatsapp_delivery_outbox.py:ro" in compose
    assert "./ea/app/services/whatsapp_web_session_readiness.py:/app/app/services/whatsapp_web_session_readiness.py:ro" in compose
    assert compose.count("./ea/app/services/whatsapp_delivery_outbox.py:/app/app/services/whatsapp_delivery_outbox.py:ro") >= 2
    assert compose.count("./ea/app/services/whatsapp_delivery_router.py:/app/app/services/whatsapp_delivery_router.py:ro") >= 3
    assert "ea-telegram-teable-sync:" in compose
    assert "container_name: ea-telegram-teable-sync" in compose
    assert "python /app/scripts/sync_telegram_conversations_to_teable.py || true" in compose


def test_sidecar_package_uses_whatsapp_web_js_local_auth_stack() -> None:
    package = json.loads((ROOT / "whatsapp-web-session" / "package.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["scripts"]["start"] == "node server.js"
    assert package["dependencies"]["whatsapp-web.js"] == "1.34.7"
    assert package["dependencies"]["qrcode"] == "1.5.4"
    assert package["dependencies"]["qrcode-terminal"] == "0.12.0"
    assert package["dependencies"]["express"] == "4.19.2"


def test_sidecar_http_contract_matches_ea_delivery_adapter() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    assert 'new LocalAuth({' in server
    assert "clientId: SESSION_REF" in server
    assert "dataPath: DATA_DIR" in server
    assert "HEYY_AI_ROUTE_MAP_STATE_FILE" in server
    assert "loadPersistedHeyyAiRouteMap" in server
    assert "loadInitialHeyyAiRouteMap" in server
    assert "persistHeyyAiRouteMap" in server
    assert "fs.renameSync(tempPath, normalizedPath)" in server
    assert "removeStaleChromiumLocks(DATA_DIR)" in server
    assert '"SingletonLock"' in server
    assert "BUTTON_MAP_STATE_FILE" in server
    assert "loadPersistedButtonMapState(BUTTON_MAP_STATE_FILE)" in server
    assert "persistButtonMapState()" in server
    assert "last_button_map_persist_at" in server
    assert 'app.get("/sessions/:sessionRef/status"' in server
    assert 'app.get("/sessions/:sessionRef/qr"' in server
    assert 'app.get("/sessions/:sessionRef/qr.svg"' in server
    assert 'app.get("/sessions/:sessionRef/pair"' in server
    assert 'app.get("/sessions/:sessionRef/messages"' in server
    assert 'app.get("/sessions/:sessionRef/messages/:messageId/diagnostics"' in server
    assert 'app.get("/sessions/:sessionRef/outbox"' in server
    assert 'app.get("/sessions/:sessionRef/recipients/:recipient"' in server
    assert 'app.post("/sessions/:sessionRef/messages"' in server
    assert 'client.on("message"' in server
    assert 'client.on("message_ack"' in server
    assert "recordInboundMessage(message)" in server
    assert "autoReplyTextForMessage(message, route)" in server
    assert "showTypingStatusForMessage(message, route, replyText)" in server
    assert "showTypingStatusForChatId(" in server
    assert "chat.sendStateTyping()" in server
    assert "typing_status_sent" in server
    assert "typing_status_enabled" in server
    assert "pre_reply_delay_min_seconds" in server
    assert "pre_reply_delay_max_seconds" in server
    assert "quiet_hours_start_hour" in server
    assert "quiet_hours_end_hour" in server
    assert "typing_delay_ms_per_character" in server
    assert "routeQuietHoursActive(route)" in server
    assert "randomPreReplyDelayMs(route)" in server
    assert "typingDelayMsForText(route, text)" in server
    assert "Array.from(String(text || \"\")).length * perCharacterMs" in server
    assert "behavior_prompt" in server
    assert "memory_notes" in server
    assert "pacing_hint" in server
    assert "recordOutboundMessage(" in server
    assert "updateOutboundAck(message, ack)" in server
    assert "message && message.body" in server
    assert "client.getNumberId(recipient)" in server
    assert "client.getContactLidAndPhone" in server
    assert "lid_phone_lid" in server
    assert "lid_phone_number" in server
    assert "resolveRecipientChat(recipient)" in server
    assert "chatRefMap" in server
    assert 'typeof wid === "string"' in server
    assert "chatIdFromSerialized(wid)" in server
    assert "chatIdFromChatRef(chatRef)" in server
    assert "resolvedChatFromChatRef(chatRef)" in server
    assert "req.body.chat_ref || req.body.chatRef" in server
    assert "chat_ref_not_found" in server
    assert "currentAccountInfo()" in server
    assert "matches_current_account" in server
    assert "lid_chat_id_present" in server
    assert "phone_chat_id_present" in server
    assert "resolution_method" in server
    assert 'app.get("/sessions/:sessionRef/heyy-ai-routes"' in server
    assert 'app.put("/sessions/:sessionRef/heyy-ai-routes"' in server
    assert "route_map_persisted" in server
    assert "last_route_map_persist_at" in server
    assert "heyy_ai_route_map_state_file_present" in server
    assert 'app.get("/sessions/:sessionRef/conversations"' in server
    assert "heyy_ai_name" in server
    assert "routeWithOutboundPersonaOverride(route, body = {})" in server
    assert 'requestTextValue(body, ["heyy_ai_key", "ai_key", "persona_key"])' in server
    assert "const outboundRouteBase = routeWithOutboundPersonaOverride(route, req.body || {})" in server
    assert "WA_WEB_STORE_MESSAGE_TEXT" in server
    assert "recipient_not_registered" in server
    assert "ack_label" in server
    assert "chat_id_present" in server
    assert "WA_WEB_AUTOREPLY_ENABLED" in server
    assert "WA_WEB_AUTOREPLY_ALLOWED_RECIPIENTS" in server
    assert 'res.status(ok ? 200 : 503).json({ ok, session_ref: SESSION_REF, status: state.status })' in server
    assert "includeQr" in server
    assert "payload.qr = state.latestQr" in server
    assert 'qrImage.toString(state.latestQr' in server
    assert 'alt="WhatsApp Web pairing QR code"' in server
    assert "boundedSendTimeoutMs" in server
    assert '"outbound_send_timeout"' in server
    assert "client.sendMessage(resolved.chatId, sendContent.content, sendContent.options || undefined)" in server
    assert "const { Buttons, Client, LocalAuth, MessageMedia, Poll }" in server
    assert "WA_WEB_JSON_LIMIT" in server
    assert "WA_WEB_CONVERSATION_FETCH_TIMEOUT_MS" in server
    assert "WA_WEB_CONVERSATION_FETCH_CONCURRENCY" in server
    assert "boundedConversationFetchTimeoutMs" in server
    assert "boundedConversationFetchConcurrency" in server
    assert "withTimeout(client.getChats()" in server
    assert "mapWithConcurrency(selectedChats, fetchConcurrency" in server
    assert "withTimeout(" in server
    assert "fetch_error_present" in server
    assert "fetch_concurrency" in server
    assert "fetch_timeout_ms" in server
    assert "conversation_skip" in server
    assert "conversation_total" in server
    assert "next_conversation_skip" in server
    assert "conversation_page_complete" in server
    assert ".slice(skip, skip + take)" in server
    assert 'app.get("/sessions/:sessionRef/messages/:messageId/media"' in server
    assert "client.getMessageById(messageId)" in server
    assert "message.downloadMedia()" in server
    assert "function messageDataFrom(message)" in server
    assert "function firstNonEmptyString(...values)" in server
    assert "function messageHasDownloadableMedia(message)" in server
    assert "function downloadMediaViaStore(messageId)" in server
    assert "function messageDiagnosticsViaStore(messageId)" in server
    assert 'window.require("WAWebCollections")' in server
    assert 'window.require("WAWebDownloadManager").downloadManager.downloadAndMaybeDecrypt' in server
    assert "data.caption" in server
    assert "data.pollName" in server
    assert "data.eventName" in server
    assert "data.description" in server
    assert "data.directPath" in server
    assert "data.deprecatedMms3Url" in server
    assert "data.mediaKey" in server
    assert "messageHasDownloadableMedia(message)" in server
    assert "outboundMediaFromRequest(req.body)" in server
    assert "new MessageMedia(mimetype, data, filename" in server
    assert "media_filename" in server
    assert "media_mime_type" in server
    assert "media_present" in server
    assert "normalizeButtonRows(req.body && (req.body.buttons || req.body.inline_buttons))" in server
    assert "BUTTON_CALLBACK_MAX_CHARS" in server
    assert "button_callback_too_long" in server
    assert "callbackData.slice(0, 256)" not in server
    assert "buildSendMessageContent(text, buttonRows)" in server
    assert "POLL_BUTTONS_ENABLED" in server
    assert "process.env.WA_WEB_POLL_BUTTONS_ENABLED" in server
    assert "POLL_BUTTONS_ENABLED && typeof Poll === \"function\"" in server
    assert "new Poll(" in server
    assert "allowMultipleAnswers: false" in server
    assert "pollMessageSecretForButtons(normalizedText, buttons)" in server
    assert "pollTitleForButtons(normalizedText)" in server
    assert "recentPollMaps" in server
    assert "recent_poll_maps" in server
    assert "storeRecentPollMap(result, resolved.chatId, buttonRows)" in server
    assert 'client.on("vote_update"' in server
    assert "recordPollVoteAsInbound(vote)" in server
    assert "if (!selectedButtonId && !selectedOptionLabel)" in server
    assert "if (!recorded) {" in server
    assert "selectedPollCallbackFromVote(vote)" in server
    assert "selectedPollOptionLabelsFromVote(vote)" in server
    assert "selected_button_label" in server
    assert 'type: "poll_vote"' in server
    assert "NATIVE_BUTTONS_ENABLED" in server
    assert "process.env.WA_WEB_NATIVE_BUTTONS_ENABLED" in server
    assert "NATIVE_BUTTONS_ENABLED && typeof Buttons === \"function\"" in server
    assert "new Buttons(" in server
    assert "fallbackTextWithButtons" in server
    assert "Reply with:" in server
    assert "[${button.callback_data}]" not in server
    assert "button_count" in server
    assert "buttons_fallback" in server
    assert "control_kind: sendContent.control_kind || \"\"" in server
    assert "selected_button_id = selectedButtonId" in server
    assert "selectedButtonIdFrom(message)" in server
    assert "recentButtonMaps" in server
    assert "storeRecentButtonMap(resolved.chatId, buttonRows)" in server
    assert "inferButtonIdFromText(message)" in server
    assert "normalizeCommandLabel(label)" in server
    assert "normalizeCommandLabel(body)" in server
    assert "actionButtonIdFrom(message)" in server
    assert "selected_button_kind" in server
    assert "session_not_ready" in server
    assert "qrcode.generate(qr" in server


def test_old_lady_auto_reply_waits_before_typing_and_respects_quiet_hours() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    assert 'WA_WEB_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS || "60"' in server
    assert 'WA_WEB_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS || "900"' in server
    assert 'WA_WEB_HEYY_AI_QUIET_HOURS_START_HOUR || "21"' in server
    assert 'WA_WEB_HEYY_AI_QUIET_HOURS_END_HOUR || "6"' in server
    assert 'WA_WEB_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER || "4000"' in server
    assert "Math.random() * (upperSeconds - minSeconds + 1)" in server

    quiet_check = server.index("if (routeQuietHoursActive(route))")
    reply_text = server.index("const replyText = autoReplyTextForMessage(message, route)")
    typing_call = server.index("const typing = await showTypingStatusForMessage(message, route, replyText)")
    send_timeout = server.index("const sendTimeoutMs = boundedSendTimeoutMs()", typing_call)
    send_call = server.index("const result = await withTimeout(", send_timeout)
    assert quiet_check > -1
    assert reply_text < quiet_check < typing_call < send_timeout < send_call

    pre_delay = server.index("const preReplyDelayMs = options && options.include_pre_reply_delay ? randomPreReplyDelayMs(route) : 0")
    sleep_before_typing = server.index("await sleep(preReplyDelayMs)", pre_delay)
    typing_status = server.index('chat.sendStateTyping(),', sleep_before_typing)
    typing_delay = server.index("await sleep(delayMs)", typing_status)
    assert pre_delay > -1
    assert pre_delay < sleep_before_typing < typing_status < typing_delay


def test_inbound_auto_reply_logs_skip_reasons_and_bounds_typing_operations() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    skip_helper = server.index("function autoReplySkipReason(message)")
    should_helper = server.index("function shouldAutoReply(message)", skip_helper)
    handler = server.index('client.on("message"', should_helper)
    skip_reason = server.index("const skipReason = autoReplySkipReason(message)", handler)
    skip_log = server.index("reason=${skipReason}", skip_reason)
    typing_status = server.index('chat.sendStateTyping(),')
    typing_timeout = server.index('"typing_status_timeout"', typing_status)
    inbound_lookup = server.index('withTimeout(message.getChat(), boundedConversationFetchTimeoutMs(), "inbound_chat_lookup_timeout")')
    outbound_lookup = server.index('withTimeout(client.getChatById(chatId), boundedConversationFetchTimeoutMs(), "outbound_chat_lookup_timeout")')

    assert skip_helper < should_helper < handler < skip_reason < skip_log
    assert typing_status < typing_timeout < inbound_lookup < outbound_lookup
    assert "recipient_not_allowed" in server
    assert "reason=reply_text_empty" in server


def test_outbound_typing_fast_path_skips_chat_lookup_when_pacing_is_disabled() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    helper = server.index("async function showTypingStatusForChatId(chatId, route, text = \"\", options = {})")
    pre_reply = server.index("const preReplyDelayMs = options && options.include_pre_reply_delay ? randomPreReplyDelayMs(route) : 0;", helper)
    delay_ms = server.index("const delayMs = typingDelayMsForText(route, text);", pre_reply)
    typing_enabled = server.index("const typingStatusEnabled = parseBoolean(", delay_ms)
    fast_path = server.index("if (preReplyDelayMs <= 0 && delayMs <= 0 && !typingStatusEnabled)", typing_enabled)
    lookup = server.index('withTimeout(client.getChatById(chatId), boundedConversationFetchTimeoutMs(), "outbound_chat_lookup_timeout")', fast_path)

    assert helper < pre_reply < delay_ms < typing_enabled < fast_path < lookup


def test_recipient_resolution_bounds_number_and_lid_lookups() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    resolver = server.index("async function resolveRecipientChat(recipient)")
    number_id = server.index("client.getNumberId(recipient)", resolver)
    number_timeout = server.index('"recipient_number_id_timeout"', number_id)
    lid_lookup = server.index("client.getContactLidAndPhone([`${recipient}@c.us`])", number_timeout)
    lid_timeout = server.index('"recipient_lid_lookup_timeout"', lid_lookup)

    assert resolver < number_id < number_timeout < lid_lookup < lid_timeout


def test_old_lady_auto_reply_builds_contextual_herta_text_instead_of_repeating_reset_line() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    builder = server.index("function hertaReplyTextForMessage(message, fallbackText = \"\")")
    auto_reply = server.index("function autoReplyTextForMessage(message, route)", builder)
    message_handler = server.index('client.on("message"', auto_reply)
    reply_text = server.index("const replyText = autoReplyTextForMessage(message, route)", message_handler)
    typing_call = server.index("showTypingStatusForMessage(message, route, replyText)", reply_text)
    send_timeout = server.index("const sendTimeoutMs = boundedSendTimeoutMs()", typing_call)
    send_call = server.index("client.sendMessage(message.from, replyText)", send_timeout)

    assert builder < auto_reply < message_handler < reply_text < typing_call < send_timeout < send_call
    assert "recentHertaAutoReplies" in server
    assert "danke|schön|schoen|schon|passt|ok|okay|gut|super|lieb" in server
    assert "bank|geld|konto|überweis|uberweis|ueberweis|tan|pin|passwort|password|code|paypal|karte|zahlen|bezahl" in server
    assert "wer bist|bist du|herta|mama|omi|oma|mutter|sabine|sabi" in server
    assert "Gern, mein Lieber. Ich hab es gesehen. Ich brauch nur einen Moment, ja?" in server
    assert "Na, Bank mach ich hier nicht." in server
    assert "daß" in server
    assert "muß" in server
    assert "bißchen" in server


def test_old_lady_outbound_send_uses_same_wait_and_quiet_hours_before_typing() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    outbound_route = server.index("const outboundRoute = {")
    quiet_check = server.index("if (routeQuietHoursActive(outboundRoute))", outbound_route)
    quiet_reason = server.index('reason: "route_quiet_hours_active"', quiet_check)
    typing_call = server.index("const typing = await showTypingStatusForChatId(", quiet_reason)
    pre_reply_option = server.index("include_pre_reply_delay: true", typing_call)
    send_timeout = server.index("const sendTimeoutMs = boundedSendTimeoutMs()", pre_reply_option)
    send_call = server.index("const result = await withTimeout(", send_timeout)
    record_call = server.index("recordOutboundMessage(", send_call)
    pre_reply_record = server.index("typing.pre_reply_delay_ms", record_call)
    response_field = server.index("pre_reply_delay_ms: recorded.pre_reply_delay_ms", pre_reply_record)

    assert outbound_route > -1
    assert outbound_route < quiet_check < quiet_reason < typing_call < pre_reply_option < send_timeout < send_call
    assert send_call < record_call < pre_reply_record < response_field


def test_outbound_heyy_ai_override_uses_old_lady_defaults_without_persisting_route_map() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    delay_helper = server.index("function delaySecondsForAiKey(aiKey, value, fallback = 0, options = {})")
    old_lady_zero_guard = server.index("normalized === DEFAULT_HEYY_AI_KEY && parsed <= 0 && fallbackValue > 0", delay_helper)
    hour_helper = server.index("function hourForAiKey(aiKey, value, fallback = 0, options = {})", old_lady_zero_guard)
    typing_per_char_helper = server.index("function typingDelayMsPerCharacterForAiKey(aiKey, value, fallback = 0, options = {})", hour_helper)
    helper = server.index("function routeWithOutboundPersonaOverride(route, body = {})")
    override_key = server.index('requestTextValue(body, ["heyy_ai_key", "ai_key", "persona_key"])', helper)
    pacing_defaults = server.index("const pacingDefaults = defaultPacingForAiKey(effectiveKey)", override_key)
    old_lady_default = server.index("const oldLadyOverride = effectiveKey === DEFAULT_HEYY_AI_KEY", pacing_defaults)
    old_lady_name = server.index("oldLadyOverride ? DEFAULT_HEYY_AI_NAME", old_lady_default)
    old_lady_delay = server.index("delaySecondsForAiKey(", old_lady_name)
    max_delay = server.index('requestValue(body, ["pre_reply_delay_max_seconds", "preReplyDelayMaxSeconds"])', old_lady_name)
    min_delay = server.index('requestValue(body, ["pre_reply_delay_min_seconds", "preReplyDelayMinSeconds"])', max_delay)
    quiet_start = server.index('requestValue(body, ["quiet_hours_start_hour", "quietHoursStartHour"])', min_delay)
    per_char_delay = server.index('requestValue(body, ["typing_delay_ms_per_character", "typingDelayMsPerCharacter"])', quiet_start)

    endpoint = server.index('app.post("/sessions/:sessionRef/messages"')
    route_lookup = server.index("const route = heyyAiRouteForSenderDigits(recipient)", endpoint)
    route_override = server.index("const outboundRouteBase = routeWithOutboundPersonaOverride(route, req.body || {})", route_lookup)
    outbound_route = server.index("const outboundRoute = {", route_override)
    quiet_check = server.index("if (routeQuietHoursActive(outboundRoute))", outbound_route)
    listen = server.index('app.listen(PORT, "0.0.0.0"', endpoint)
    endpoint_body = server[endpoint:listen]

    assert delay_helper < old_lady_zero_guard < hour_helper < typing_per_char_helper < helper
    assert helper < override_key < pacing_defaults < old_lady_default < old_lady_name < old_lady_delay < max_delay < min_delay < quiet_start < per_char_delay
    assert endpoint < route_lookup < route_override < outbound_route < quiet_check
    assert "persistHeyyAiRouteMap" not in endpoint_body


def test_outbound_request_can_override_pacing_without_persona_override() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    helper = server.index("function routeWithOutboundPersonaOverride(route, body = {})")
    override_key = server.index('const overrideKey = requestTextValue(body, ["heyy_ai_key", "ai_key", "persona_key"])', helper)
    effective_key = server.index("const effectiveKey = overrideKey ||", override_key)
    max_delay = server.index('requestValue(body, ["pre_reply_delay_max_seconds", "preReplyDelayMaxSeconds"])', effective_key)
    min_delay = server.index('requestValue(body, ["pre_reply_delay_min_seconds", "preReplyDelayMinSeconds"])', max_delay)
    quiet_end = server.index('requestValue(body, ["quiet_hours_end_hour", "quietHoursEndHour"])', max_delay)
    quiet_start = server.index('requestValue(body, ["quiet_hours_start_hour", "quietHoursStartHour"])', quiet_end)
    typing_per_char = server.index('requestValue(body, ["typing_delay_ms_per_character", "typingDelayMsPerCharacter"])', quiet_start)
    typing_delay = server.index('requestValue(body, ["typing_delay_ms", "typingDelayMs"])', typing_per_char)
    typing_status = server.index('requestValue(body, ["typing_status_enabled", "typing_status"])', typing_delay)

    assert helper < override_key < effective_key < max_delay < min_delay < quiet_end < quiet_start < typing_per_char < typing_delay < typing_status
    assert "if (!overrideKey) {\n    return route;\n  }" not in server


def test_explicit_old_lady_route_can_keep_fast_zero_pacing() -> None:
    server = (ROOT / "whatsapp-web-session" / "server.js").read_text(encoding="utf-8")

    normalize = server.index("function normalizeHeyyAiRouteMap(loaded)")
    allow_zero_route = server.index('const allowZeroPacing = key !== "*"', normalize)
    normalized_per_char = server.index("typingDelayMsPerCharacterForAiKey(aiKey", allow_zero_route)
    normalized_allow_zero = server.index("{ allow_zero: allowZeroPacing }", normalized_per_char)
    route_lookup = server.index("function heyyAiRouteForSenderDigits(senderDigits)", normalized_allow_zero)
    matched = server.index("const matched = Boolean(normalized && state.heyyAiRouteMap[normalized])", route_lookup)
    route_allow_zero = server.index("{ allow_zero: matched }", matched)
    public_routes = server.index("function publicHeyyAiRoutes()", route_allow_zero)
    public_allow_zero = server.index('const allowZeroPacing = routeKey !== "*"', public_routes)
    public_route_allow_zero = server.index("{ allow_zero: allowZeroPacing }", public_allow_zero)

    assert normalize < allow_zero_route < normalized_per_char < normalized_allow_zero
    assert route_lookup < matched < route_allow_zero < public_routes
    assert public_routes < public_allow_zero < public_route_allow_zero
    assert "const allowZero = Boolean(options && options.allow_zero)" in server


def test_channels_wire_audiobook_voice_buttons_to_whatsapp_router() -> None:
    channels_source = (ROOT / "ea" / "app" / "api" / "routes" / "channels.py").read_text(encoding="utf-8")

    assert "from app.services import whatsapp_delivery_router" in channels_source
    assert "def _whatsapp_send_audiobook_voice_samples(" in channels_source
    assert "audiobook_voice_audition_sample_messages(job)" in channels_source
    assert "_telegram_encode_audiobook_voice_callback(" in channels_source
    assert "whatsapp_delivery_router.send_whatsapp_delivery_text(" in channels_source
    assert 'buttons=[[("Use this", use_callback), ("Dismiss", dismiss_callback)]]' in channels_source
    assert "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET" in channels_source
    assert "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE" in channels_source
    assert "/config/whatsapp_audiobook_callback_secret" in channels_source


def test_env_example_points_binding_at_optional_sidecar_but_keeps_it_staged() -> None:
    env = _env_example()

    assert env["EA_WHATSAPP_WEB_DEFAULT_BINDING_ID"] == "ea-whatsapp-web-session"
    assert env["EA_WHATSAPP_WEB_DEFAULT_SESSION_REF"] == "default-wa-web"
    assert env["EA_WHATSAPP_WEB_DEFAULT_BROWSER_PROFILE_REF"] == "docker-volume://ea_whatsapp_web_session"
    assert env["EA_WHATSAPP_WEB_DEFAULT_CONNECTOR_STATUS"] == "staged"
    assert env["EA_WHATSAPP_WEB_SESSION_API_BASE_URL"] == "http://ea-whatsapp-web-session:8098"
    assert env["EA_WHATSAPP_WEB_SESSION_HOST_PORT"] == "8098"
    assert env["EA_WHATSAPP_WEB_ACTIVATE_WAIT_SECONDS"] == "0"
    assert env["EA_WHATSAPP_WEB_ACTIVATE_POLL_INTERVAL_SECONDS"] == "2"
    assert env["EA_WHATSAPP_WEB_ACTIVATOR_ENABLED"] == "0"
    assert env["EA_WHATSAPP_WEB_ACTIVATION_WATCH_INTERVAL_SECONDS"] == "5"
    assert env["EA_WHATSAPP_WEB_ACTIVATION_WATCH_MAX_SECONDS"] == "0"
    assert env["EA_WHATSAPP_WEB_ACTIVATION_SEND_TEST"] == "0"
    assert env["EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED"] == "1"
    assert env["EA_WHATSAPP_WEB_ACTION_POLL_INTERVAL_SECONDS"] == "5"
    assert env["EA_WHATSAPP_WEB_ACTION_STATE_FILE"] == "/data/whatsapp-actions/processed.json"
    assert env["EA_WHATSAPP_WEB_ACTION_MESSAGE_TAKE"] == "100"
    assert env["EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS"] == "60"
    assert env["EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS"] == "300"
    assert env["EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED"] == "0"
    assert env["EA_WHATSAPP_WEB_TG_SUMMARY_EVERY"] == "5"
    assert env["EA_WHATSAPP_WEB_TG_SUMMARY_CHAT_ID"] == ""
    assert env["EA_WHATSAPP_WEB_TG_SUMMARY_BOT_TOKEN"] == ""
    assert env["EA_WHATSAPP_WEB_TG_SUMMARY_TIMEOUT_SECONDS"] == "15"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_KEY"] == "empathetic_slow_typing_old_lady"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_NAME"] == "Herta (Heyy Lady)"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS"] == "60"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS"] == "900"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_START_HOUR"] == "21"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_END_HOUR"] == "6"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS"] == "6500"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER"] == "4000"
    assert env["EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_STATUS_ENABLED"] == "1"
    assert env["EA_WHATSAPP_WEB_JSON_LIMIT"] == "48mb"
    assert env["EA_WHATSAPP_AUDIOBOOK_RESUME_DUE"] == "1"
    assert env["EA_WHATSAPP_AUDIOBOOK_RESUME_DUE_LIMIT"] == "1"
    assert env["EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED"] == "1"
    assert env["EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_LIMIT"] == "3"
    assert env["EA_AUDIOBOOK_EBOOK_CONVERT_BIN"] == "ebook-convert"
    assert env["EA_AUDIOBOOK_KINDLE_CONVERT_TIMEOUT_SECONDS"] == "900"
    assert env["EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET"] == ""
    assert env["EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE"] == "config/whatsapp_audiobook_callback_secret"
    assert env["EA_WHATSAPP_WEB_TEABLE_SYNC_ENABLED"] == "0"
    assert env["EA_WHATSAPP_WEB_TEABLE_SYNC_INTERVAL_SECONDS"] == "30"
    assert env["EA_WHATSAPP_WEB_TEABLE_CONVERSATION_TAKE"] == "25"
    assert env["EA_WHATSAPP_WEB_TEABLE_MESSAGE_LIMIT"] == "50"
    assert env["EA_WHATSAPP_WEB_TEABLE_SYNC_ALL_CONVERSATIONS"] == "1"
    assert env["EA_WHATSAPP_WEB_TEABLE_CONVERSATION_MAX_PAGES"] == "1"
    assert env["EA_WHATSAPP_WEB_CONVERSATION_FETCH_TIMEOUT_MS"] == "15000"
    assert env["EA_WHATSAPP_WEB_CONVERSATION_FETCH_CONCURRENCY"] == "6"
    assert env["EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_TIMEOUT_MS"] == "15000"
    assert env["EA_WHATSAPP_WEB_TEABLE_CONVERSATION_FETCH_CONCURRENCY"] == "6"
    assert env["EA_WHATSAPP_WEB_TEABLE_COMPLETED_REFRESH_CONVERSATION_TAKE"] == "5"
    assert env["EA_WHATSAPP_WEB_TEABLE_SYNC_STATE_FILE"] == "/data/whatsapp-teable-sync/state.json"
    assert env["EA_WHATSAPP_WEB_TEABLE_SYNC_RUN_TIMEOUT_SECONDS"] == "300"
    assert env["EA_WHATSAPP_WEB_TEABLE_SYNC_STALE_SECONDS"] == "600"
    assert env["EA_WHATSAPP_WEB_AUTOREPLY_ENABLED"] == "0"
    assert env["EA_WHATSAPP_WEB_AUTOREPLY_TEXT"].startswith("Na geh... ich bin die Herta.")
    assert "zurück" in env["EA_WHATSAPP_WEB_AUTOREPLY_TEXT"]
    assert env["EA_WHATSAPP_WEB_DEFAULT_HEYY_AI_KEY"] == "empathetic_slow_typing_old_lady"
    assert env["EA_WHATSAPP_WEB_DEFAULT_HEYY_AI_NAME"] == "Herta (Heyy Lady)"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_TYPING_DELAY_MS"] == "6500"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_MAX_TYPING_DELAY_MS"] == "3600000"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS"] == "60"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS"] == "900"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_QUIET_HOURS_START_HOUR"] == "21"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_QUIET_HOURS_END_HOUR"] == "6"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER"] == "4000"
    assert env["EA_WHATSAPP_WEB_HEYY_AI_TYPING_STATUS_ENABLED"] == "1"
    assert env["EA_WHATSAPP_WEB_INBOX_LIMIT"] == "100"
    assert env["EA_WHATSAPP_WEB_STORE_MESSAGE_TEXT"] == "1"
