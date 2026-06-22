"use strict";

const crypto = require("crypto");
const express = require("express");
const fs = require("fs");
const path = require("path");
const qrImage = require("qrcode");
const qrcode = require("qrcode-terminal");
const { Buttons, Client, LocalAuth, MessageMedia, Poll } = require("whatsapp-web.js");

const SESSION_REF = (process.env.WA_WEB_SESSION_REF || "default-wa-web").trim();
const SESSION_LABEL = (process.env.WA_WEB_SESSION_LABEL || SESSION_REF).trim();
const PORT = Number.parseInt(process.env.WA_WEB_SESSION_PORT || "8098", 10);
const DATA_DIR = (process.env.WA_WEB_SESSION_DATA_DIR || "/data/session").trim();
const HEYY_AI_ROUTE_MAP_STATE_FILE = (
  process.env.WA_WEB_HEYY_AI_ROUTE_MAP_STATE_FILE ||
  path.join(DATA_DIR, `${SESSION_REF}.heyy-ai-routes.json`)
).trim();
const API_TOKEN = (process.env.WA_WEB_SESSION_API_TOKEN || "").trim();
const CHROMIUM_PATH = (process.env.CHROMIUM_PATH || "/usr/bin/chromium").trim();
const AUTO_REPLY_ENABLED = ["1", "true", "yes", "on"].includes(
  String(process.env.WA_WEB_AUTOREPLY_ENABLED || "").trim().toLowerCase()
);
const AUTO_REPLY_TEXT = (
  process.env.WA_WEB_AUTOREPLY_TEXT ||
  "Na geh... ich bin die Herta. Ich tipp langsam, die Brille ist wieder weg. Schreib mir bitte noch einmal langsam, ich scroll gleich zurück."
).trim();
const DEFAULT_HEYY_AI_KEY = (process.env.WA_WEB_DEFAULT_HEYY_AI_KEY || "empathetic_slow_typing_old_lady").trim() || "empathetic_slow_typing_old_lady";
const DEFAULT_HEYY_AI_NAME = (process.env.WA_WEB_DEFAULT_HEYY_AI_NAME || "Herta (Heyy Lady)").trim() || DEFAULT_HEYY_AI_KEY;
const DEFAULT_HEYY_AI_BEHAVIOR_PROMPT = (
  process.env.WA_WEB_HEYY_AI_BEHAVIOR_PROMPT ||
  "Warm elderly Viennese lady. Empathetic, confused by apps and banking, types slowly, mixes up harmless memories, asks verification questions, never shares real payment, identity, password, PIN, TAN, OTP, or address data. In German replies, use real umlauts and older pre-reform spelling such as daß, muß, and bißchen; avoid ae/oe/ue substitutions."
).trim();
const DEFAULT_HEYY_AI_MEMORY_NOTES = (
  process.env.WA_WEB_HEYY_AI_MEMORY_NOTES ||
  "Fictional memory card: Herta from Vienna; daughter Sabine/Sabi/Bine; tram 62 red school bag; yellow raincoat; budgie Peppi; neighbor cat Mitzi; Marillenknödel confusion; glasses often missing."
).trim();
const DEFAULT_HEYY_AI_PACING_HINT = (
  process.env.WA_WEB_HEYY_AI_PACING_HINT ||
  "Wait a random 1-15 minutes before typing, never answer between 21:00 and 06:00 local time, then type slowly at four seconds per character before sending one hesitant message."
).trim();
const DEFAULT_HEYY_AI_TYPING_DELAY_MS = Number.parseInt(process.env.WA_WEB_HEYY_AI_TYPING_DELAY_MS || "6500", 10);
const DEFAULT_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS = Number.parseInt(process.env.WA_WEB_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS || "60", 10);
const DEFAULT_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS = Number.parseInt(process.env.WA_WEB_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS || "900", 10);
const DEFAULT_HEYY_AI_QUIET_HOURS_START_HOUR = Number.parseInt(process.env.WA_WEB_HEYY_AI_QUIET_HOURS_START_HOUR || "21", 10);
const DEFAULT_HEYY_AI_QUIET_HOURS_END_HOUR = Number.parseInt(process.env.WA_WEB_HEYY_AI_QUIET_HOURS_END_HOUR || "6", 10);
const DEFAULT_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER = Number.parseInt(process.env.WA_WEB_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER || "4000", 10);
const MAX_HEYY_AI_TYPING_DELAY_MS = Number.parseInt(process.env.WA_WEB_HEYY_AI_MAX_TYPING_DELAY_MS || "3600000", 10);
const DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED = parseBoolean(process.env.WA_WEB_HEYY_AI_TYPING_STATUS_ENABLED, true);
const INITIAL_HEYY_AI_ROUTE_MAP = loadInitialHeyyAiRouteMap(
  process.env.WA_WEB_HEYY_AI_ROUTE_MAP_JSON || "",
  HEYY_AI_ROUTE_MAP_STATE_FILE
);
const AUTO_REPLY_ALLOWED_RECIPIENTS = new Set(
  String(process.env.WA_WEB_AUTOREPLY_ALLOWED_RECIPIENTS || "")
    .split(",")
    .map((value) => normalizeRecipient(value))
    .filter(Boolean)
);
const INBOX_LIMIT = Number.parseInt(process.env.WA_WEB_INBOX_LIMIT || "100", 10);
const JSON_LIMIT = (process.env.WA_WEB_JSON_LIMIT || "48mb").trim() || "48mb";
const BUTTON_LABEL_MAX_CHARS = 48;
const BUTTON_CALLBACK_MAX_CHARS = 256;
const CONVERSATION_FETCH_TIMEOUT_MS = Number.parseInt(process.env.WA_WEB_CONVERSATION_FETCH_TIMEOUT_MS || "15000", 10);
const CONVERSATION_FETCH_CONCURRENCY = Number.parseInt(process.env.WA_WEB_CONVERSATION_FETCH_CONCURRENCY || "6", 10);
const SEND_TIMEOUT_MS = Number.parseInt(process.env.WA_WEB_SEND_TIMEOUT_MS || "30000", 10);
const STORE_MESSAGE_TEXT = ["1", "true", "yes", "on"].includes(
  String(process.env.WA_WEB_STORE_MESSAGE_TEXT || "").trim().toLowerCase()
);
const NATIVE_BUTTONS_ENABLED = parseBoolean(process.env.WA_WEB_NATIVE_BUTTONS_ENABLED, false);
const POLL_BUTTONS_ENABLED = parseBoolean(process.env.WA_WEB_POLL_BUTTONS_ENABLED, true);
const BUTTON_MAP_STATE_FILE = (
  process.env.WA_WEB_BUTTON_MAP_STATE_FILE ||
  path.join(DATA_DIR, `${SESSION_REF}.button-maps.json`)
).trim();
const INITIAL_BUTTON_MAP_STATE = loadPersistedButtonMapState(BUTTON_MAP_STATE_FILE);

const state = {
  authenticated: false,
  buttonMapPersistQueued: false,
  chatRefMap: {},
  inbox: [],
  heyyAiRouteMap: INITIAL_HEYY_AI_ROUTE_MAP,
  lastError: "",
  lastAckAt: "",
  lastInboundAt: "",
  lastQrAt: "",
  lastReadyAt: "",
  lastRouteMapPersistAt: "",
  lastSendAt: "",
  lastButtonMapPersistAt: INITIAL_BUTTON_MAP_STATE.persisted_at || "",
  latestQr: "",
  outbox: [],
  recentHertaAutoReplies: {},
  recentPollMaps: INITIAL_BUTTON_MAP_STATE.recent_poll_maps,
  recentButtonMaps: INITIAL_BUTTON_MAP_STATE.recent_button_maps,
  ready: false,
  startedAt: new Date().toISOString(),
  status: "starting"
};

function nowIso() {
  return new Date().toISOString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseBoolean(value, fallback = false) {
  const raw = String(value === undefined || value === null || value === "" ? "" : value).trim().toLowerCase();
  if (!raw) {
    return Boolean(fallback);
  }
  if (["1", "true", "yes", "on"].includes(raw)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(raw)) {
    return false;
  }
  return Boolean(fallback);
}

function boundedTypingDelayMs(value) {
  const parsed = Number.parseInt(String(value === undefined || value === null ? "" : value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  const maxDelay = Number.isFinite(MAX_HEYY_AI_TYPING_DELAY_MS) && MAX_HEYY_AI_TYPING_DELAY_MS > 0
    ? MAX_HEYY_AI_TYPING_DELAY_MS
    : 3600000;
  return Math.max(0, Math.min(parsed, maxDelay));
}

function boundedDelaySeconds(value, fallback = 0) {
  const parsed = Number.parseInt(String(value === undefined || value === null ? "" : value), 10);
  const fallbackValue = Number.isFinite(fallback) ? Math.max(0, Math.min(fallback, 86400)) : 0;
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallbackValue;
  }
  return Math.max(0, Math.min(parsed, 86400));
}

function boundedHour(value, fallback = -1) {
  const parsed = Number.parseInt(String(value === undefined || value === null ? "" : value), 10);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 23) {
    return fallback;
  }
  return parsed;
}

function defaultPacingForAiKey(aiKey) {
  const normalized = String(aiKey || "").trim();
  if (normalized !== DEFAULT_HEYY_AI_KEY) {
    return {
      pre_reply_delay_min_seconds: 0,
      pre_reply_delay_max_seconds: 0,
      quiet_hours_start_hour: 0,
      quiet_hours_end_hour: 0,
      typing_delay_ms_per_character: 0
    };
  }
  return {
    pre_reply_delay_min_seconds: boundedDelaySeconds(DEFAULT_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS, 60),
    pre_reply_delay_max_seconds: boundedDelaySeconds(DEFAULT_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS, 900),
    quiet_hours_start_hour: boundedHour(DEFAULT_HEYY_AI_QUIET_HOURS_START_HOUR, 21),
    quiet_hours_end_hour: boundedHour(DEFAULT_HEYY_AI_QUIET_HOURS_END_HOUR, 6),
    typing_delay_ms_per_character: boundedTypingDelayMs(DEFAULT_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER)
  };
}

function delaySecondsForAiKey(aiKey, value, fallback = 0, options = {}) {
  const normalized = String(aiKey || "").trim();
  const parsed = boundedDelaySeconds(value, fallback);
  const fallbackValue = boundedDelaySeconds(fallback, 0);
  const allowZero = Boolean(options && options.allow_zero);
  if (!allowZero && normalized === DEFAULT_HEYY_AI_KEY && parsed <= 0 && fallbackValue > 0) {
    return fallbackValue;
  }
  return parsed;
}

function hourForAiKey(aiKey, value, fallback = 0, options = {}) {
  const normalized = String(aiKey || "").trim();
  const parsed = boundedHour(value, fallback);
  const fallbackValue = boundedHour(fallback, 0);
  const allowZero = Boolean(options && options.allow_zero);
  if (!allowZero && normalized === DEFAULT_HEYY_AI_KEY && parsed === 0 && fallbackValue > 0) {
    return fallbackValue;
  }
  return parsed;
}

function typingDelayMsPerCharacterForAiKey(aiKey, value, fallback = 0, options = {}) {
  const normalized = String(aiKey || "").trim();
  const parsed = boundedTypingDelayMs(value ?? fallback);
  const fallbackValue = boundedTypingDelayMs(fallback);
  const allowZero = Boolean(options && options.allow_zero);
  if (!allowZero && normalized === DEFAULT_HEYY_AI_KEY && parsed <= 0 && fallbackValue > 0) {
    return fallbackValue;
  }
  return parsed;
}

function sameToken(left, right) {
  const leftBuffer = Buffer.from(String(left || ""));
  const rightBuffer = Buffer.from(String(right || ""));
  if (leftBuffer.length !== rightBuffer.length) {
    return false;
  }
  return crypto.timingSafeEqual(leftBuffer, rightBuffer);
}

function requireAuth(req, res, next) {
  if (!API_TOKEN) {
    next();
    return;
  }
  const raw = String(req.get("authorization") || "");
  const token = raw.toLowerCase().startsWith("bearer ") ? raw.slice(7).trim() : raw.trim();
  if (!token || !sameToken(token, API_TOKEN)) {
    res.status(401).json({ ok: false, reason: "unauthorized" });
    return;
  }
  next();
}

function normalizeRecipient(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (digits.length < 7) {
    return "";
  }
  return digits;
}

function boundedInboxLimit() {
  return Math.max(1, Math.min(1000, INBOX_LIMIT || 100));
}

function boundedConversationFetchTimeoutMs(value) {
  const parsed = Number.parseInt(String(value === undefined || value === null ? "" : value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return Math.max(1000, Math.min(60000, CONVERSATION_FETCH_TIMEOUT_MS || 15000));
  }
  return Math.max(1000, Math.min(60000, parsed));
}

function boundedConversationFetchConcurrency(value) {
  const parsed = Number.parseInt(String(value === undefined || value === null ? "" : value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return Math.max(1, Math.min(16, CONVERSATION_FETCH_CONCURRENCY || 6));
  }
  return Math.max(1, Math.min(16, parsed));
}

function boundedSendTimeoutMs(value) {
  const parsed = Number.parseInt(String(value === undefined || value === null ? "" : value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return Math.max(1000, Math.min(300000, SEND_TIMEOUT_MS || 30000));
  }
  return Math.max(1000, Math.min(300000, parsed));
}

function withTimeout(promise, timeoutMs, label) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(label || "operation_timeout")), timeoutMs);
    Promise.resolve(promise).then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

async function mapWithConcurrency(items, concurrency, mapper) {
  const values = Array.isArray(items) ? items : [];
  const results = new Array(values.length);
  let nextIndex = 0;
  const workerCount = Math.min(values.length, boundedConversationFetchConcurrency(concurrency));
  const workers = Array.from({ length: workerCount }, async () => {
    while (nextIndex < values.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await mapper(values[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}

function conversationFetchErrorSummary(error) {
  return error && error.message ? String(error.message) : String(error || "conversation_fetch_failed");
}

function parseHeyyAiRouteMap(raw) {
  const value = String(raw || "").trim();
  if (!value) {
    return {};
  }
  try {
    const loaded = JSON.parse(value);
    return normalizeHeyyAiRouteMap(loaded);
  } catch (_error) {
    return {};
  }
}

function loadPersistedHeyyAiRouteMap(filePath) {
  const normalizedPath = String(filePath || "").trim();
  if (!normalizedPath) {
    return {};
  }
  try {
    if (!fs.existsSync(normalizedPath)) {
      return {};
    }
    const loaded = JSON.parse(fs.readFileSync(normalizedPath, "utf8"));
    return normalizeHeyyAiRouteMap(loaded && (loaded.routes || loaded.route_map || loaded));
  } catch (error) {
    console.warn(`[wa-web-session] persisted Heyy AI route map load failed for ${SESSION_REF}: ${error.message || error}`);
    return {};
  }
}

function loadInitialHeyyAiRouteMap(rawEnvRouteMap, filePath) {
  const configured = parseHeyyAiRouteMap(rawEnvRouteMap);
  if (Object.keys(configured).length > 0) {
    return configured;
  }
  return loadPersistedHeyyAiRouteMap(filePath);
}

function persistHeyyAiRouteMap(routeMap) {
  const normalizedPath = String(HEYY_AI_ROUTE_MAP_STATE_FILE || "").trim();
  if (!normalizedPath) {
    return false;
  }
  try {
    fs.mkdirSync(path.dirname(normalizedPath), { recursive: true });
    const payload = {
      persisted_at: nowIso(),
      route_count: Object.keys(routeMap || {}).length,
      routes: routeMap || {},
      session_ref: SESSION_REF
    };
    const tempPath = `${normalizedPath}.tmp`;
    fs.writeFileSync(tempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    fs.renameSync(tempPath, normalizedPath);
    state.lastRouteMapPersistAt = payload.persisted_at;
    return true;
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "route_map_persist_failed");
    console.warn(`[wa-web-session] persisted Heyy AI route map save failed for ${SESSION_REF}: ${state.lastError}`);
    return false;
  }
}

function loadPersistedButtonMapState(filePath) {
  const normalizedPath = String(filePath || "").trim();
  if (!normalizedPath) {
    return { persisted_at: "", recent_button_maps: {}, recent_poll_maps: {} };
  }
  try {
    if (!fs.existsSync(normalizedPath)) {
      return { persisted_at: "", recent_button_maps: {}, recent_poll_maps: {} };
    }
    const loaded = JSON.parse(fs.readFileSync(normalizedPath, "utf8"));
    const buttonMaps = loaded && typeof loaded.recent_button_maps === "object" && !Array.isArray(loaded.recent_button_maps)
      ? loaded.recent_button_maps
      : {};
    const pollMaps = loaded && typeof loaded.recent_poll_maps === "object" && !Array.isArray(loaded.recent_poll_maps)
      ? loaded.recent_poll_maps
      : {};
    return {
      persisted_at: String(loaded && loaded.persisted_at ? loaded.persisted_at : "").trim(),
      recent_button_maps: buttonMaps,
      recent_poll_maps: pollMaps
    };
  } catch (error) {
    console.warn(`[wa-web-session] persisted button map load failed for ${SESSION_REF}: ${error.message || error}`);
    return { persisted_at: "", recent_button_maps: {}, recent_poll_maps: {} };
  }
}

function persistButtonMapState() {
  const normalizedPath = String(BUTTON_MAP_STATE_FILE || "").trim();
  if (!normalizedPath) {
    return false;
  }
  try {
    fs.mkdirSync(path.dirname(normalizedPath), { recursive: true });
    const payload = {
      persisted_at: nowIso(),
      recent_button_maps: state.recentButtonMaps || {},
      recent_poll_maps: state.recentPollMaps || {},
      session_ref: SESSION_REF
    };
    const tempPath = `${normalizedPath}.tmp`;
    fs.writeFileSync(tempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    fs.renameSync(tempPath, normalizedPath);
    state.lastButtonMapPersistAt = payload.persisted_at;
    return true;
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "button_map_persist_failed");
    console.warn(`[wa-web-session] persisted button map save failed for ${SESSION_REF}: ${state.lastError}`);
    return false;
  }
}

function scheduleButtonMapStatePersist() {
  if (state.buttonMapPersistQueued) {
    return false;
  }
  state.buttonMapPersistQueued = true;
  setTimeout(() => {
    state.buttonMapPersistQueued = false;
    persistButtonMapState();
  }, 0);
  return true;
}

function normalizeHeyyAiRouteMap(loaded) {
  const parsed = {};
  if (!loaded || typeof loaded !== "object") {
    return parsed;
  }
  const entries = Array.isArray(loaded)
    ? loaded.map((item) => [item && (item.inbound_number_digits || item.inbound_number || item.sender_digits || item.route_key), item])
    : Object.entries(loaded);
  for (const [rawKey, rawRule] of entries) {
    const key = rawKey === "*" || rawKey === "default" ? "*" : normalizeRecipient(rawKey);
    if (!key) {
      continue;
    }
    if (typeof rawRule === "string") {
      const aiKey = rawRule.trim() || DEFAULT_HEYY_AI_KEY;
      const pacingDefaults = defaultPacingForAiKey(aiKey);
      parsed[key] = {
        ai_key: aiKey,
        auto_reply_enabled: aiKey === DEFAULT_HEYY_AI_KEY,
        ai_name: aiKey || DEFAULT_HEYY_AI_NAME,
        behavior_prompt: DEFAULT_HEYY_AI_BEHAVIOR_PROMPT,
        memory_notes: DEFAULT_HEYY_AI_MEMORY_NOTES,
        pacing_hint: DEFAULT_HEYY_AI_PACING_HINT,
        pre_reply_delay_max_seconds: pacingDefaults.pre_reply_delay_max_seconds,
        pre_reply_delay_min_seconds: pacingDefaults.pre_reply_delay_min_seconds,
        quiet_hours_end_hour: pacingDefaults.quiet_hours_end_hour,
        quiet_hours_start_hour: pacingDefaults.quiet_hours_start_hour,
        reply_text: AUTO_REPLY_TEXT,
        typing_delay_ms: boundedTypingDelayMs(DEFAULT_HEYY_AI_TYPING_DELAY_MS),
        typing_delay_ms_per_character: pacingDefaults.typing_delay_ms_per_character,
        typing_status_enabled: DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED
      };
      continue;
    }
    if (!rawRule || typeof rawRule !== "object" || Array.isArray(rawRule)) {
      continue;
    }
    const aiKey = String(rawRule.ai_key || rawRule.persona || rawRule.name || DEFAULT_HEYY_AI_KEY).trim() || DEFAULT_HEYY_AI_KEY;
    const pacingDefaults = defaultPacingForAiKey(aiKey);
    const allowZeroPacing = key !== "*";
    parsed[key] = {
      ai_key: aiKey,
      auto_reply_enabled: parseBoolean(rawRule.auto_reply_enabled, aiKey === DEFAULT_HEYY_AI_KEY),
      ai_name: String(rawRule.ai_name || rawRule.display_name || rawRule.label || rawRule.name || rawRule.ai_key || DEFAULT_HEYY_AI_NAME).trim() || DEFAULT_HEYY_AI_NAME,
      behavior_prompt: String(rawRule.behavior_prompt || rawRule.prompt || rawRule.system_prompt || DEFAULT_HEYY_AI_BEHAVIOR_PROMPT).trim(),
      memory_notes: String(rawRule.memory_notes || rawRule.memories || rawRule.memory || DEFAULT_HEYY_AI_MEMORY_NOTES).trim(),
      pacing_hint: String(rawRule.pacing_hint || rawRule.pacing || DEFAULT_HEYY_AI_PACING_HINT).trim(),
      pre_reply_delay_max_seconds: delaySecondsForAiKey(aiKey, rawRule.pre_reply_delay_max_seconds ?? rawRule.preReplyDelayMaxSeconds, pacingDefaults.pre_reply_delay_max_seconds, { allow_zero: allowZeroPacing }),
      pre_reply_delay_min_seconds: delaySecondsForAiKey(aiKey, rawRule.pre_reply_delay_min_seconds ?? rawRule.preReplyDelayMinSeconds, pacingDefaults.pre_reply_delay_min_seconds, { allow_zero: allowZeroPacing }),
      quiet_hours_end_hour: hourForAiKey(aiKey, rawRule.quiet_hours_end_hour ?? rawRule.quietHoursEndHour, pacingDefaults.quiet_hours_end_hour, { allow_zero: allowZeroPacing }),
      quiet_hours_start_hour: hourForAiKey(aiKey, rawRule.quiet_hours_start_hour ?? rawRule.quietHoursStartHour, pacingDefaults.quiet_hours_start_hour, { allow_zero: allowZeroPacing }),
      reply_text: String(rawRule.reply_text || rawRule.text || AUTO_REPLY_TEXT).trim(),
      typing_delay_ms: boundedTypingDelayMs(rawRule.typing_delay_ms ?? rawRule.typingDelayMs ?? DEFAULT_HEYY_AI_TYPING_DELAY_MS),
      typing_delay_ms_per_character: typingDelayMsPerCharacterForAiKey(aiKey, rawRule.typing_delay_ms_per_character ?? rawRule.typingDelayMsPerCharacter, pacingDefaults.typing_delay_ms_per_character, { allow_zero: allowZeroPacing }),
      typing_status_enabled: parseBoolean(rawRule.typing_status_enabled, DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED)
    };
  }
  return parsed;
}

function sessionStatus() {
  return {
    ...currentAccountInfo(),
    authenticated: state.authenticated,
    auto_reply_enabled: AUTO_REPLY_ENABLED,
    auto_reply_target_count: AUTO_REPLY_ALLOWED_RECIPIENTS.size,
    default_heyy_ai_key: DEFAULT_HEYY_AI_KEY,
    default_heyy_ai_name: DEFAULT_HEYY_AI_NAME,
    default_heyy_ai_pre_reply_delay_max_seconds: boundedDelaySeconds(DEFAULT_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS, 900),
    default_heyy_ai_pre_reply_delay_min_seconds: boundedDelaySeconds(DEFAULT_HEYY_AI_PRE_REPLY_DELAY_MIN_SECONDS, 60),
    default_heyy_ai_quiet_hours_end_hour: boundedHour(DEFAULT_HEYY_AI_QUIET_HOURS_END_HOUR, 6),
    default_heyy_ai_quiet_hours_start_hour: boundedHour(DEFAULT_HEYY_AI_QUIET_HOURS_START_HOUR, 21),
    default_heyy_ai_typing_delay_ms: boundedTypingDelayMs(DEFAULT_HEYY_AI_TYPING_DELAY_MS),
    default_heyy_ai_typing_delay_ms_per_character: boundedTypingDelayMs(DEFAULT_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER),
    default_heyy_ai_typing_status_enabled: DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED,
    heyy_ai_route_count: Object.keys(state.heyyAiRouteMap).length,
    inbox_count: state.inbox.length,
    label: SESSION_LABEL,
    last_ack_at: state.lastAckAt,
    last_button_map_persist_at: state.lastButtonMapPersistAt,
    last_error_present: Boolean(state.lastError),
    last_inbound_at: state.lastInboundAt,
    last_qr_at: state.lastQrAt,
    last_ready_at: state.lastReadyAt,
    last_route_map_persist_at: state.lastRouteMapPersistAt,
    last_send_at: state.lastSendAt,
    outbox_count: state.outbox.length,
    qr_required: state.status === "qr_required",
    ready: state.ready,
    session_ref: SESSION_REF,
    heyy_ai_route_map_state_file_present: fs.existsSync(HEYY_AI_ROUTE_MAP_STATE_FILE),
    store_message_text: STORE_MESSAGE_TEXT,
    started_at: state.startedAt,
    status: state.status
  };
}

function messageIdFrom(result) {
  const id = result && result.id ? result.id : {};
  return String(id._serialized || id.id || "").trim();
}

function messageDataFrom(message) {
  return message && message._data && typeof message._data === "object" ? message._data : {};
}

function firstNonEmptyString(...values) {
  for (const value of values) {
    const normalized = String(value || "").trim();
    if (normalized) {
      return normalized;
    }
  }
  return "";
}

function messageBodyFrom(message) {
  const data = messageDataFrom(message);
  return firstNonEmptyString(
    message && message.body,
    data.caption,
    data.body,
    data.pollName,
    data.eventName,
    data.title,
    data.description,
    data.content
  );
}

function messageTypeFrom(message) {
  const data = messageDataFrom(message);
  return firstNonEmptyString(message && message.type, data.type, data.subtype);
}

function messageHasDownloadableMedia(message) {
  const data = messageDataFrom(message);
  return Boolean(
    (message && message.hasMedia) ||
    data.directPath ||
    data.deprecatedMms3Url ||
    data.mediaKey ||
    data.filehash ||
    data.encFilehash
  );
}

function normalizedHertaInboundText(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function hertaReplyChoiceKey(message, inboundText) {
  return String((message && (message.from || message.author || message.id && message.id.remote)) || "default").trim() +
    ":" + normalizedHertaInboundText(inboundText);
}

function pickHertaReplyVariant(message, inboundText, variants) {
  const choices = Array.isArray(variants) ? variants.filter((value) => String(value || "").trim()) : [];
  if (choices.length === 0) {
    return "";
  }
  const choiceKey = hertaReplyChoiceKey(message, inboundText);
  const digest = crypto.createHash("sha256").update(choiceKey).digest("hex");
  let index = Number.parseInt(digest.slice(0, 8), 16) % choices.length;
  const chatKey = String((message && (message.from || message.author)) || "default").trim() || "default";
  const lastReply = state.recentHertaAutoReplies[chatKey] || "";
  if (choices.length > 1 && choices[index] === lastReply) {
    index = (index + 1) % choices.length;
  }
  const selected = choices[index];
  state.recentHertaAutoReplies[chatKey] = selected;
  return selected;
}

function hertaReplyTextForMessage(message, fallbackText = "") {
  const inboundText = messageBodyFrom(message);
  const normalized = normalizedHertaInboundText(inboundText);
  if (!normalized) {
    return String(fallbackText || AUTO_REPLY_TEXT).trim();
  }
  if (/(bank|geld|konto|überweis|uberweis|ueberweis|tan|pin|passwort|password|code|paypal|karte|zahlen|bezahl)/.test(normalized)) {
    return pickHertaReplyVariant(message, inboundText, [
      "Na, Bank mach ich hier nicht. Da ruf ich lieber die alte Nummer an, sonst wird mir ganz schwindlig.",
      "Geld und Codes schreib ich da nicht rein. Ich such lieber die Nummer von früher und frag dort nach."
    ]);
  }
  if (/(danke|schön|schoen|schon|passt|ok|okay|gut|super|lieb)/.test(normalized) || normalized.length <= 4) {
    return pickHertaReplyVariant(message, inboundText, [
      "Gern, mein Lieber. Ich hab es gesehen. Ich brauch nur einen Moment, ja?",
      "Schön. Ich bin da, ich tipp nur langsam. Nicht wundern, wenn ich ein bißchen brauch.",
      "Ja, passt. Ich leg mir die Brille gleich wieder her, sonst les ich alles zweimal."
    ]);
  }
  if (/(hallo|servus|morgen|abend|gruß|gruss|grüß|gruess|hi|hey)/.test(normalized)) {
    return pickHertaReplyVariant(message, inboundText, [
      "Servus, ich bin da. Schreib nur langsam, die Buchstaben sind wieder so klein.",
      "Hallo. Ich les mit, aber ich tipp halt wie eine alte Frau.",
      "Ja, ich bin da. Einen Moment, ich hab die Brille grad nicht ordentlich sitzen."
    ]);
  }
  if (/(schnell|langsam|warum|wieso|antwort|tippt|typing|nochmal|noch mal)/.test(normalized)) {
    return pickHertaReplyVariant(message, inboundText, [
      "Ja ja, langsam. Ich seh es eh, ich brauch nur ein bißchen, bis die Finger nachkommen.",
      "Nicht hudeln bitte. Schreib mir das noch einmal kurz, dann komm ich schon mit.",
      "Ich bin nicht weg. Ich tipp nur langsam und les lieber zweimal, bevor ich Unsinn schick."
    ]);
  }
  if (/(wer bist|bist du|herta|mama|omi|oma|mutter|sabine|sabi)/.test(normalized)) {
    return pickHertaReplyVariant(message, inboundText, [
      "Ich bin die Herta. Aber bei neuen Nummern frag ich lieber erst nach. Was soll denn Sabi wissen?",
      "Na, Herta bin ich. Wenn du wirklich von der Familie bist, sag mir bitte etwas Harmloses von früher.",
      "Ich glaub schon, daß ich die Herta bin. Aber bei so Nachrichten bin ich vorsichtig, gell."
    ]);
  }
  return pickHertaReplyVariant(message, inboundText, [
    "Ich hab es gelesen. Schreib mir bitte in einem ruhigen Satz, dann komm ich besser mit.",
    "Moment, ich bin da. Ich muß nur schauen, was du genau meinst.",
    "Na geh, die App macht wieder klein. Ich les es noch einmal und meld mich gleich.",
    "Ich hör dich schon. Also... ich les dich. Einen Moment bitte."
  ]);
}

function autoReplyTextForMessage(message, route) {
  const fallbackText = String((route && route.reply_text) || AUTO_REPLY_TEXT).trim();
  const aiKey = String(route && route.ai_key || "").trim();
  if (aiKey !== DEFAULT_HEYY_AI_KEY) {
    return fallbackText;
  }
  return hertaReplyTextForMessage(message, fallbackText);
}

function messageMediaFilenameFrom(message) {
  const data = messageDataFrom(message);
  return firstNonEmptyString(
    message && message.filename,
    data.filename,
    data.fileName,
    data.title,
    data.caption
  );
}

function messageMediaMimeTypeFrom(message) {
  const data = messageDataFrom(message);
  return firstNonEmptyString(
    message && message.mimetype,
    data.mimetype,
    data.mimeType
  );
}

function messageMediaSizeFrom(message) {
  const data = messageDataFrom(message);
  const parsed = Number.parseInt(String(data.size || data.fileSize || data.mediaSize || "0"), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function safeHeaderValue(value, fallback = "") {
  const normalized = String(value || fallback || "").replace(/[\r\n]/g, " ").trim();
  return normalized || fallback;
}

function selectedButtonIdFrom(message) {
  const data = message && message._data && typeof message._data === "object" ? message._data : {};
  return String(
    (message && message.selectedButtonId) ||
    data.selectedButtonId ||
    data.selectedButtonIdSerialized ||
    data.buttonId ||
    ""
  ).trim();
}

function selectedButtonKindFrom(value) {
  const normalized = String(value || "").trim();
  if (normalized.startsWith("ab|")) {
    return "audiobook_voice";
  }
  if (normalized.startsWith("am|")) {
    return "audiobook_voice_management";
  }
  if (normalized.startsWith("ap|")) {
    return "audiobook_playback";
  }
  if (normalized.startsWith("fb|")) {
    return "feedback";
  }
  if (normalized.startsWith("ea|")) {
    return "assistant_action";
  }
  return normalized ? "unknown" : "";
}

function timestampIsoFrom(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "";
  }
  return new Date(numeric * 1000).toISOString();
}

function ackValueFrom(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return numeric;
}

function ackLabelFrom(value) {
  const ack = ackValueFrom(value);
  if (ack === -1) {
    return "error";
  }
  if (ack === 0) {
    return "pending";
  }
  if (ack === 1) {
    return "server";
  }
  if (ack === 2) {
    return "device";
  }
  if (ack === 3) {
    return "read";
  }
  if (ack === 4) {
    return "played";
  }
  return ack === null ? "unknown" : "unknown";
}

function chatIdFromWid(wid) {
  if (typeof wid === "string") {
    return chatIdFromSerialized(wid);
  }
  const serialized = String(wid && wid._serialized ? wid._serialized : "").trim();
  if (serialized) {
    return serialized;
  }
  const user = String(wid && wid.user ? wid.user : "").trim();
  const server = String(wid && wid.server ? wid.server : "").trim();
  if (user && server) {
    return `${user}@${server}`;
  }
  return "";
}

function chatIdFromSerialized(value) {
  const serialized = String(value || "").trim();
  return serialized.includes("@") ? serialized : "";
}

function chatIdKindFrom(chatId) {
  const value = String(chatId || "").trim();
  if (value.endsWith("@c.us")) {
    return "c.us";
  }
  if (value.endsWith("@lid")) {
    return "lid";
  }
  if (value.endsWith("@g.us")) {
    return "g.us";
  }
  return value ? "unknown" : "";
}

function currentAccountChatId() {
  return chatIdFromWid(client && client.info ? client.info.wid : null);
}

function currentAccountDigits() {
  const wid = client && client.info ? client.info.wid : null;
  return normalizeRecipient(wid && wid.user ? wid.user : "");
}

function currentAccountInfo() {
  const accountChatId = currentAccountChatId();
  const digits = currentAccountDigits();
  return {
    account_digits_present: Boolean(digits),
    account_id_kind: chatIdKindFrom(accountChatId),
    account_id_present: Boolean(accountChatId),
    platform_present: Boolean(client && client.info && client.info.platform),
    pushname_present: Boolean(client && client.info && client.info.pushname)
  };
}

async function resolveRecipientChat(recipient) {
  const wid = await withTimeout(
    client.getNumberId(recipient),
    boundedConversationFetchTimeoutMs(),
    "recipient_number_id_timeout"
  );
  let chatId = chatIdFromWid(wid);
  let phoneChatId = chatId;
  let lidChatId = "";
  let resolutionMethod = chatId ? "number_id" : "";
  let lid_lookup_failed = false;
  if (!chatId && typeof client.getContactLidAndPhone === "function") {
    try {
      const mappings = await withTimeout(
        client.getContactLidAndPhone([`${recipient}@c.us`]),
        boundedConversationFetchTimeoutMs(),
        "recipient_lid_lookup_timeout"
      );
      const mapping = Array.isArray(mappings) ? mappings[0] : mappings;
      phoneChatId = chatIdFromSerialized(mapping && mapping.pn);
      lidChatId = chatIdFromSerialized(mapping && mapping.lid);
      const phoneDigits = normalizeRecipient(String(phoneChatId || "").split("@", 1)[0]);
      if (phoneChatId && phoneDigits === recipient) {
        chatId = phoneChatId;
        resolutionMethod = "lid_phone_number";
      } else if (lidChatId) {
        chatId = lidChatId;
        resolutionMethod = "lid_phone_lid";
      }
    } catch (_error) {
      lid_lookup_failed = true;
    }
  }
  const accountChatId = currentAccountChatId();
  const accountDigits = currentAccountDigits();
  return {
    chatId,
    chat_id_kind: chatIdKindFrom(chatId),
    chat_id_present: Boolean(chatId),
    lid_chat_id_present: Boolean(lidChatId),
    lid_lookup_failed,
    matches_current_account:
      Boolean(chatId && accountChatId && chatId === accountChatId) ||
      Boolean(recipient && accountDigits && recipient === accountDigits),
    phone_chat_id_present: Boolean(phoneChatId),
    registered: Boolean(chatId),
    resolution_method: resolutionMethod
  };
}

function chatRefFromChatId(chatId) {
  const value = String(chatId || "").trim();
  if (!value) {
    return "";
  }
  const chatRef = crypto.createHash("sha256").update(`${SESSION_REF}:${value}`).digest("hex").slice(0, 24);
  state.chatRefMap[chatRef] = {
    chat_id: value,
    chat_id_kind: chatIdKindFrom(value),
    recorded_at: nowIso()
  };
  return chatRef;
}

function chatIdFromChatRef(chatRef) {
  const value = String(chatRef || "").trim();
  if (!value) {
    return "";
  }
  const mapped = state.chatRefMap[value] || {};
  return String(mapped.chat_id || "").trim();
}

function resolvedChatFromChatRef(chatRef) {
  const chatId = chatIdFromChatRef(chatRef);
  const accountChatId = currentAccountChatId();
  return {
    chatId,
    chat_id_kind: chatIdKindFrom(chatId),
    chat_id_present: Boolean(chatId),
    lid_chat_id_present: chatIdKindFrom(chatId) === "lid",
    lid_lookup_failed: false,
    matches_current_account: Boolean(chatId && accountChatId && chatId === accountChatId),
    phone_chat_id_present: chatIdKindFrom(chatId) === "phone",
    registered: Boolean(chatId),
    resolution_method: chatId ? "chat_ref" : "chat_ref_not_found"
  };
}

function messageDirectionFrom(message) {
  return message && message.fromMe ? "outbound" : "inbound";
}

function heyyAiRouteForSenderDigits(senderDigits) {
  const normalized = normalizeRecipient(senderDigits);
  const mapped = (normalized && state.heyyAiRouteMap[normalized]) || state.heyyAiRouteMap["*"] || {};
  const aiKey = String(mapped.ai_key || DEFAULT_HEYY_AI_KEY).trim() || DEFAULT_HEYY_AI_KEY;
  const pacingDefaults = defaultPacingForAiKey(aiKey);
  const matched = Boolean(normalized && state.heyyAiRouteMap[normalized]);
  return {
    ai_key: aiKey,
    auto_reply_enabled: parseBoolean(mapped.auto_reply_enabled, aiKey === DEFAULT_HEYY_AI_KEY),
    ai_name: String(mapped.ai_name || mapped.ai_key || DEFAULT_HEYY_AI_NAME).trim() || DEFAULT_HEYY_AI_NAME,
    behavior_prompt: String(mapped.behavior_prompt || DEFAULT_HEYY_AI_BEHAVIOR_PROMPT).trim(),
    memory_notes: String(mapped.memory_notes || DEFAULT_HEYY_AI_MEMORY_NOTES).trim(),
    matched,
    pacing_hint: String(mapped.pacing_hint || DEFAULT_HEYY_AI_PACING_HINT).trim(),
    pre_reply_delay_max_seconds: delaySecondsForAiKey(aiKey, mapped.pre_reply_delay_max_seconds, pacingDefaults.pre_reply_delay_max_seconds, { allow_zero: matched }),
    pre_reply_delay_min_seconds: delaySecondsForAiKey(aiKey, mapped.pre_reply_delay_min_seconds, pacingDefaults.pre_reply_delay_min_seconds, { allow_zero: matched }),
    quiet_hours_end_hour: hourForAiKey(aiKey, mapped.quiet_hours_end_hour, pacingDefaults.quiet_hours_end_hour, { allow_zero: matched }),
    quiet_hours_start_hour: hourForAiKey(aiKey, mapped.quiet_hours_start_hour, pacingDefaults.quiet_hours_start_hour, { allow_zero: matched }),
    reply_text: String(mapped.reply_text || AUTO_REPLY_TEXT).trim(),
    typing_delay_ms: boundedTypingDelayMs(mapped.typing_delay_ms ?? DEFAULT_HEYY_AI_TYPING_DELAY_MS),
    typing_delay_ms_per_character: typingDelayMsPerCharacterForAiKey(aiKey, mapped.typing_delay_ms_per_character, pacingDefaults.typing_delay_ms_per_character, { allow_zero: matched }),
    typing_status_enabled: parseBoolean(mapped.typing_status_enabled, DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED)
  };
}

function requestValue(body, keys) {
  const payload = body && typeof body === "object" ? body : {};
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(payload, key)) {
      return payload[key];
    }
  }
  return undefined;
}

function requestTextValue(body, keys, fallback = "") {
  const value = requestValue(body, keys);
  const normalized = String(value === undefined || value === null ? "" : value).trim();
  return normalized || String(fallback || "").trim();
}

function routeWithOutboundPersonaOverride(route, body = {}) {
  const payload = body && typeof body === "object" ? body : {};
  const hasRequestOverride = (keys) => keys.some((key) => Object.prototype.hasOwnProperty.call(payload, key));
  const overrideKey = requestTextValue(body, ["heyy_ai_key", "ai_key", "persona_key"]);
  const base = route && typeof route === "object" ? route : {};
  const effectiveKey = overrideKey || (String(base.ai_key || "").trim() || DEFAULT_HEYY_AI_KEY);
  const pacingDefaults = defaultPacingForAiKey(effectiveKey);
  const baseMatchesOverride = String(base.ai_key || "").trim() === effectiveKey;
  const oldLadyOverride = effectiveKey === DEFAULT_HEYY_AI_KEY;
  return {
    ...base,
    ai_key: effectiveKey,
    ai_name: requestTextValue(
      body,
      ["heyy_ai_name", "ai_name", "persona_name"],
      oldLadyOverride ? DEFAULT_HEYY_AI_NAME : (baseMatchesOverride ? base.ai_name : effectiveKey)
    ) || effectiveKey,
    behavior_prompt: requestTextValue(
      body,
      ["behavior_prompt", "prompt", "system_prompt"],
      oldLadyOverride ? DEFAULT_HEYY_AI_BEHAVIOR_PROMPT : (baseMatchesOverride ? base.behavior_prompt : "")
    ),
    memory_notes: requestTextValue(
      body,
      ["memory_notes", "memories", "memory"],
      oldLadyOverride ? DEFAULT_HEYY_AI_MEMORY_NOTES : (baseMatchesOverride ? base.memory_notes : "")
    ),
    pacing_hint: requestTextValue(
      body,
      ["pacing_hint", "pacing"],
      oldLadyOverride ? DEFAULT_HEYY_AI_PACING_HINT : (baseMatchesOverride ? base.pacing_hint : "")
    ),
    pre_reply_delay_max_seconds: delaySecondsForAiKey(
      effectiveKey,
      requestValue(body, ["pre_reply_delay_max_seconds", "preReplyDelayMaxSeconds"]),
      baseMatchesOverride ? base.pre_reply_delay_max_seconds : pacingDefaults.pre_reply_delay_max_seconds,
      { allow_zero: hasRequestOverride(["pre_reply_delay_max_seconds", "preReplyDelayMaxSeconds"]) }
    ),
    pre_reply_delay_min_seconds: delaySecondsForAiKey(
      effectiveKey,
      requestValue(body, ["pre_reply_delay_min_seconds", "preReplyDelayMinSeconds"]),
      baseMatchesOverride ? base.pre_reply_delay_min_seconds : pacingDefaults.pre_reply_delay_min_seconds,
      { allow_zero: hasRequestOverride(["pre_reply_delay_min_seconds", "preReplyDelayMinSeconds"]) }
    ),
    quiet_hours_end_hour: boundedHour(
      requestValue(body, ["quiet_hours_end_hour", "quietHoursEndHour"]),
      baseMatchesOverride ? base.quiet_hours_end_hour : pacingDefaults.quiet_hours_end_hour
    ),
    quiet_hours_start_hour: boundedHour(
      requestValue(body, ["quiet_hours_start_hour", "quietHoursStartHour"]),
      baseMatchesOverride ? base.quiet_hours_start_hour : pacingDefaults.quiet_hours_start_hour
    ),
    typing_delay_ms_per_character: boundedTypingDelayMs(
      requestValue(body, ["typing_delay_ms_per_character", "typingDelayMsPerCharacter"]) ??
      (baseMatchesOverride ? base.typing_delay_ms_per_character : pacingDefaults.typing_delay_ms_per_character)
    ),
    typing_delay_ms: boundedTypingDelayMs(
      requestValue(body, ["typing_delay_ms", "typingDelayMs"]) ??
      (baseMatchesOverride ? base.typing_delay_ms : DEFAULT_HEYY_AI_TYPING_DELAY_MS)
    ),
    typing_status_enabled: parseBoolean(
      requestValue(body, ["typing_status_enabled", "typing_status"]),
      baseMatchesOverride ? base.typing_status_enabled : DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED
    )
  };
}

function heyyAiRouteForMessage(message) {
  return heyyAiRouteForSenderDigits(senderDigitsFrom(message));
}

function publicHeyyAiRoutes() {
  return Object.entries(state.heyyAiRouteMap).map(([routeKey, route]) => {
    const aiKey = String(route.ai_key || DEFAULT_HEYY_AI_KEY).trim() || DEFAULT_HEYY_AI_KEY;
    const pacingDefaults = defaultPacingForAiKey(aiKey);
    const allowZeroPacing = routeKey !== "*";
    return {
      ai_key: aiKey,
      auto_reply_enabled: parseBoolean(route.auto_reply_enabled, aiKey === DEFAULT_HEYY_AI_KEY),
      ai_name: String(route.ai_name || route.ai_key || DEFAULT_HEYY_AI_NAME).trim() || DEFAULT_HEYY_AI_NAME,
      behavior_prompt_present: Boolean(String(route.behavior_prompt || "").trim()),
      inbound_number_present: routeKey !== "*",
      memory_notes_present: Boolean(String(route.memory_notes || "").trim()),
      pacing_hint_present: Boolean(String(route.pacing_hint || "").trim()),
      pre_reply_delay_max_seconds: delaySecondsForAiKey(aiKey, route.pre_reply_delay_max_seconds, pacingDefaults.pre_reply_delay_max_seconds, { allow_zero: allowZeroPacing }),
      pre_reply_delay_min_seconds: delaySecondsForAiKey(aiKey, route.pre_reply_delay_min_seconds, pacingDefaults.pre_reply_delay_min_seconds, { allow_zero: allowZeroPacing }),
      quiet_hours_end_hour: hourForAiKey(aiKey, route.quiet_hours_end_hour, pacingDefaults.quiet_hours_end_hour, { allow_zero: allowZeroPacing }),
      quiet_hours_start_hour: hourForAiKey(aiKey, route.quiet_hours_start_hour, pacingDefaults.quiet_hours_start_hour, { allow_zero: allowZeroPacing }),
      reply_text_present: Boolean(String(route.reply_text || "").trim()),
      route_key: routeKey === "*" ? "default" : routeKey,
      typing_delay_ms: boundedTypingDelayMs(route.typing_delay_ms ?? DEFAULT_HEYY_AI_TYPING_DELAY_MS),
      typing_delay_ms_per_character: typingDelayMsPerCharacterForAiKey(aiKey, route.typing_delay_ms_per_character, pacingDefaults.typing_delay_ms_per_character, { allow_zero: allowZeroPacing }),
      typing_status_enabled: parseBoolean(route.typing_status_enabled, DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED)
    };
  });
}

function sanitizedMessageFrom(message, fallbackChatRef = "") {
  const body = messageBodyFrom(message);
  const selectedButtonId = actionButtonIdFrom(message);
  const chatId = chatIdFromWid(message && message.id && message.id.remote ? message.id.remote : null);
  const chatRef = chatRefFromChatId(chatId) || String(fallbackChatRef || "").trim();
  const senderDigits = senderDigitsFrom(message);
  const route = message && message.fromMe ? { ai_key: "", ai_name: "", matched: false } : heyyAiRouteForSenderDigits(senderDigits);
  const item = {
    ack: ackValueFrom(message && message.ack),
    ack_label: ackLabelFrom(message && message.ack),
    body_present: Boolean(body),
    chat_id_kind: chatIdKindFrom(chatId),
    chat_ref: chatRef,
    direction: messageDirectionFrom(message),
    from_me: Boolean(message && message.fromMe),
    heyy_ai_key: route.ai_key,
    heyy_ai_name: route.ai_name,
    heyy_ai_route_matched: route.matched,
    id: messageIdFrom(message),
    media_filename: messageMediaFilenameFrom(message),
    media_mime_type: messageMediaMimeTypeFrom(message),
    media_present: messageHasDownloadableMedia(message),
    media_size: messageMediaSizeFrom(message),
    message_timestamp: timestampIsoFrom(message && message.timestamp),
    selected_button_kind: selectedButtonKindFrom(selectedButtonId),
    selected_button_id_present: Boolean(selectedButtonId),
    sender_digits: senderDigits,
    type: messageTypeFrom(message)
  };
  if (selectedButtonId) {
    item.selected_button_id = selectedButtonId;
  }
  if (STORE_MESSAGE_TEXT) {
    item.body_text = body;
  }
  return item;
}

function sanitizedChatFrom(chat) {
  const chatId = chatIdFromWid(chat && chat.id ? chat.id : null);
  const chatRef = chatRefFromChatId(chatId);
  const lastMessage = chat && chat.lastMessage ? chat.lastMessage : null;
  return {
    chat_id_kind: chatIdKindFrom(chatId),
    chat_id_present: Boolean(chatId),
    chat_ref: chatRef,
    is_group: Boolean(chat && chat.isGroup),
    last_message_body_present: Boolean(messageBodyFrom(lastMessage)),
    last_message_direction: lastMessage ? messageDirectionFrom(lastMessage) : "",
    last_message_timestamp: timestampIsoFrom(lastMessage && lastMessage.timestamp),
    last_message_type: String(lastMessage && lastMessage.type ? lastMessage.type : "").trim(),
    name_present: Boolean(String(chat && chat.name ? chat.name : "").trim()),
    timestamp: timestampIsoFrom(chat && chat.timestamp),
    unread_count: Number(chat && chat.unreadCount ? chat.unreadCount : 0) || 0
  };
}

function senderDigitsFrom(message) {
  const raw = String(message && (message.author || message.from) ? (message.author || message.from) : "");
  return normalizeRecipient(raw.split("@", 1)[0]);
}

function normalizeButtonRows(rawButtons) {
  const rows = [];
  const sourceRows = Array.isArray(rawButtons) ? rawButtons : [];
  for (const rawRow of sourceRows) {
    const rawItems = Array.isArray(rawRow) ? rawRow : [rawRow];
    const row = [];
    for (const rawItem of rawItems) {
      let text = "";
      let callbackData = "";
      if (rawItem && typeof rawItem === "object" && !Array.isArray(rawItem)) {
        text = String(rawItem.text || rawItem.label || rawItem.title || rawItem.body || "").trim();
        callbackData = String(
          rawItem.callback_data ||
          rawItem.callback ||
          rawItem.id ||
          rawItem.button_id ||
          rawItem.value ||
          ""
        ).trim();
      } else if (Array.isArray(rawItem) && rawItem.length >= 2) {
        text = String(rawItem[0] || "").trim();
        callbackData = String(rawItem[1] || "").trim();
      }
      if (text && callbackData) {
        if (callbackData.length > BUTTON_CALLBACK_MAX_CHARS) {
          throw new Error("button_callback_too_long");
        }
        row.push({ text: text.slice(0, BUTTON_LABEL_MAX_CHARS), callback_data: callbackData });
      }
    }
    if (row.length > 0) {
      rows.push(row.slice(0, 3));
    }
  }
  return rows.slice(0, 8);
}

function flattenedButtons(buttonRows) {
  return []
    .concat(...buttonRows)
    .filter((button) => button && button.text && button.callback_data)
    .slice(0, 3);
}

function pollMessageSecretForButtons(text, buttons) {
  const seed = `${SESSION_REF}|${String(text || "").trim()}|${buttons.map((button) => `${button.text}:${button.callback_data}`).join("|")}|${Date.now()}`;
  return Array.from(crypto.createHash("sha256").update(seed).digest()).slice(0, 32);
}

function pollTitleForButtons(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  return (normalized || "Choose one").slice(0, 255);
}

function storeRecentButtonMap(chatId, buttonRows) {
  const normalizedChatId = String(chatId || "").trim();
  const buttons = []
    .concat(...buttonRows)
    .filter((button) => button && button.text && button.callback_data);
  if (!normalizedChatId || buttons.length === 0) {
    return;
  }
  const existing = state.recentButtonMaps[normalizedChatId] && typeof state.recentButtonMaps[normalizedChatId] === "object"
    ? state.recentButtonMaps[normalizedChatId]
    : {};
  const byOrdinal = {};
  const byLabel = existing.by_label && typeof existing.by_label === "object" ? { ...existing.by_label } : {};
  buttons.forEach((button, index) => {
    const callbackData = String(button.callback_data || "").trim();
    const label = String(button.text || "").trim();
    if (!callbackData || !label) {
      return;
    }
    byOrdinal[String(index + 1)] = callbackData;
    const normalizedLabel = normalizeCommandLabel(label);
    if (normalizedLabel) {
      byLabel[normalizedLabel] = callbackData;
    }
  });
  state.recentButtonMaps[normalizedChatId] = {
    by_label: byLabel,
    by_ordinal: byOrdinal,
    recorded_at: nowIso()
  };
  scheduleButtonMapStatePersist();
}

function pollMapFromButtonRows(chatId, buttonRows) {
  const normalizedChatId = String(chatId || "").trim();
  const buttons = []
    .concat(...buttonRows)
    .filter((button) => button && button.text && button.callback_data);
  const byLabel = {};
  buttons.forEach((button, index) => {
    const callbackData = String(button.callback_data || "").trim();
    const label = String(button.text || "").trim();
    const normalizedLabel = normalizeCommandLabel(label);
    if (!callbackData || !normalizedLabel) {
      return;
    }
    byLabel[normalizedLabel] = callbackData;
    byLabel[String(index)] = callbackData;
    byLabel[String(index + 1)] = callbackData;
  });
  return {
    by_label: byLabel,
    chat_id: normalizedChatId,
    recorded_at: nowIso()
  };
}

function storeRecentPollMap(message, chatId, buttonRows) {
  const messageId = messageIdFrom(message);
  const pollMap = pollMapFromButtonRows(chatId, buttonRows);
  if (!messageId || !pollMap || !pollMap.by_label || Object.keys(pollMap.by_label).length === 0) {
    return null;
  }
  state.recentPollMaps[messageId] = pollMap;
  const entries = Object.entries(state.recentPollMaps);
  if (entries.length > boundedInboxLimit()) {
    state.recentPollMaps = Object.fromEntries(entries.slice(-boundedInboxLimit()));
  }
  scheduleButtonMapStatePersist();
  return pollMap;
}

function pollParentMessageIdFromVote(vote) {
  const parentMessage = vote && vote.parentMessage ? vote.parentMessage : null;
  const fromParent = messageIdFrom(parentMessage);
  if (fromParent) {
    return fromParent;
  }
  const candidates = [
    vote && vote.parentMessageId,
    vote && vote.pollMessageId,
    vote && vote.pollCreationMessageKey && vote.pollCreationMessageKey._serialized,
    vote && vote.parentMsgKey && vote.parentMsgKey._serialized,
    vote && vote.msgKey && vote.msgKey._serialized
  ];
  for (const candidate of candidates) {
    const normalized = String(candidate || "").trim();
    if (normalized) {
      return normalized;
    }
  }
  return "";
}

function pollOptionLabelFromValue(option) {
  if (typeof option === "string") {
    return option.trim();
  }
  if (!option || typeof option !== "object") {
    return "";
  }
  return String(
    option.name ||
    option.optionName ||
    option.value ||
    option.text ||
    option.title ||
    option.label ||
    ""
  ).trim();
}

function selectedPollOptionLabelsFromVote(vote) {
  const sources = [
    vote && vote.selectedOptions,
    vote && vote.selected_options,
    vote && vote.options,
    vote && vote.votes
  ];
  const labels = [];
  for (const source of sources) {
    if (!Array.isArray(source)) {
      continue;
    }
    for (const option of source) {
      const label = pollOptionLabelFromValue(option);
      if (label) {
        labels.push(label);
      }
    }
  }
  for (const scalar of [
    vote && vote.selectedOption,
    vote && vote.selectedOptionName,
    vote && vote.optionName,
    vote && vote.vote
  ]) {
    const label = pollOptionLabelFromValue(scalar);
    if (label) {
      labels.push(label);
    }
  }
  return labels;
}

function selectedPollCallbackFromVote(vote) {
  const parentMessageId = pollParentMessageIdFromVote(vote);
  const pollMap = parentMessageId ? state.recentPollMaps[parentMessageId] : null;
  const selectedLabels = selectedPollOptionLabelsFromVote(vote);
  if (!pollMap || !pollMap.by_label || selectedLabels.length === 0) {
    return "";
  }
  const optionLabel = selectedLabels[selectedLabels.length - 1] || "";
  const normalizedLabel = normalizeCommandLabel(optionLabel);
  return String(pollMap.by_label[normalizedLabel] || "").trim();
}

function recordPollVoteAsInbound(vote) {
  const parentMessage = vote && vote.parentMessage ? vote.parentMessage : null;
  const parentMessageId = pollParentMessageIdFromVote(vote);
  const selectedButtonId = selectedPollCallbackFromVote(vote);
  const voter = String(vote && vote.voter ? vote.voter : "").trim();
  const parentChatId = chatIdFromWid(parentMessage && parentMessage.id && parentMessage.id.remote ? parentMessage.id.remote : null);
  const chatRef = chatRefFromChatId(parentChatId);
  const selectedLabels = selectedPollOptionLabelsFromVote(vote);
  const selectedOptionLabel = selectedLabels[selectedLabels.length - 1] || "";
  if (!selectedButtonId && !selectedOptionLabel) {
    return null;
  }
  const senderDigits = senderDigitsFrom({ author: voter, from: voter });
  const route = heyyAiRouteForSenderDigits(senderDigits);
  const recorded = {
    body_present: Boolean(selectedOptionLabel),
    chat_id_kind: chatIdKindFrom(parentChatId),
    chat_ref: chatRef,
    direction: "inbound",
    from_me: false,
    from_present: Boolean(voter),
    heyy_ai_key: route.ai_key,
    heyy_ai_name: route.ai_name,
    heyy_ai_route_matched: route.matched,
    id: `pollvote:${parentMessageId}:${vote && (vote.interractedAtTs || vote.interactedAtTs) ? (vote.interractedAtTs || vote.interactedAtTs) : Date.now()}`,
    media_filename: "",
    media_mime_type: "",
    media_present: false,
    media_size: 0,
    poll_parent_message_id_present: Boolean(parentMessageId),
    received_at: nowIso(),
    selected_button_label_present: Boolean(selectedOptionLabel),
    selected_button_kind: selectedButtonKindFrom(selectedButtonId),
    selected_button_id_present: Boolean(selectedButtonId),
    sender_digits: senderDigits,
    type: "poll_vote"
  };
  if (selectedButtonId) {
    recorded.selected_button_id = selectedButtonId;
  }
  if (selectedOptionLabel) {
    recorded.selected_button_label = selectedOptionLabel;
  }
  if (STORE_MESSAGE_TEXT) {
    recorded.body_text = selectedOptionLabel;
  }
  state.lastInboundAt = recorded.received_at;
  state.inbox.push(recorded);
  if (state.inbox.length > boundedInboxLimit()) {
    state.inbox = state.inbox.slice(-boundedInboxLimit());
  }
  return recorded;
}

function inferButtonIdFromText(message) {
  const chatId = String(message && message.from ? message.from : "").trim();
  const body = messageBodyFrom(message).trim();
  if (!chatId || !body) {
    return "";
  }
  const map = state.recentButtonMaps[chatId];
  if (!map || typeof map !== "object") {
    return "";
  }
  const ordinal = body.match(/^\s*(\d{1,2})(?:[\).\s]|$)/);
  if (ordinal && map.by_ordinal && map.by_ordinal[ordinal[1]]) {
    return String(map.by_ordinal[ordinal[1]] || "").trim();
  }
  const normalizedLabel = normalizeCommandLabel(body);
  if (map.by_label && map.by_label[normalizedLabel]) {
    return String(map.by_label[normalizedLabel] || "").trim();
  }
  return "";
}

function normalizeCommandLabel(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9\u00c0-\u024f]+/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function actionButtonIdFrom(message) {
  return selectedButtonIdFrom(message) || inferButtonIdFromText(message);
}

function fallbackTextWithButtons(text, buttonRows) {
  const buttons = []
    .concat(...buttonRows)
    .filter((button) => button && button.text && button.callback_data);
  if (buttons.length === 0) {
    return String(text || "");
  }
  const choiceLines = buttons.map((button) => `- ${button.text}`);
  return `${String(text || "").trim()}\n\nReply with:\n${choiceLines.join("\n")}`.trim();
}

function buildSendMessageContent(text, buttonRows) {
  const normalizedText = String(text || "").trim();
  const buttons = flattenedButtons(buttonRows);
  if (buttons.length === 0) {
    return {
      button_count: 0,
      buttons_fallback: false,
      control_kind: "text",
      content: normalizedText,
      rendered_text: normalizedText
    };
  }
  if (POLL_BUTTONS_ENABLED && typeof Poll === "function") {
    try {
      return {
        button_count: buttons.length,
        buttons_fallback: false,
        control_kind: "poll",
        content: new Poll(
          pollTitleForButtons(normalizedText),
          buttons.map((button) => button.text),
          {
            allowMultipleAnswers: false,
            messageSecret: pollMessageSecretForButtons(normalizedText, buttons)
          }
        ),
        rendered_text: normalizedText
      };
    } catch (error) {
      console.warn(`[wa-web-session] poll controls unavailable for ${SESSION_REF}: ${error.message || error}`);
    }
  }
  if (NATIVE_BUTTONS_ENABLED && typeof Buttons === "function") {
    try {
      return {
        button_count: buttons.length,
        buttons_fallback: false,
        control_kind: "native_buttons",
        content: new Buttons(
          normalizedText,
          buttons.map((button) => ({ body: button.text, id: button.callback_data })),
          "Executive Assistant",
          "Choose one"
        ),
        rendered_text: normalizedText
      };
    } catch (error) {
      console.warn(`[wa-web-session] native buttons unavailable for ${SESSION_REF}: ${error.message || error}`);
    }
  }
  const renderedText = fallbackTextWithButtons(normalizedText, buttonRows);
  return {
    button_count: buttons.length,
    buttons_fallback: true,
    control_kind: "text_fallback",
    content: renderedText,
    rendered_text: renderedText
  };
}

function outboundMediaFromRequest(body) {
  const payload = body && typeof body === "object" ? body : {};
  const data = String(payload.media_base64 || payload.data_base64 || "").trim();
  const mimetype = String(payload.media_mimetype || payload.mimetype || payload.content_type || "").trim();
  const filename = String(payload.media_filename || payload.filename || "ea-whatsapp-media").trim();
  if (!data && !mimetype) {
    return null;
  }
  if (!data || !mimetype) {
    throw new Error("media_base64_and_mimetype_required");
  }
  return new MessageMedia(mimetype, data, filename || "ea-whatsapp-media");
}

function autoReplySkipReason(message) {
  if (!AUTO_REPLY_ENABLED) {
    return "auto_reply_disabled";
  }
  if (!AUTO_REPLY_TEXT) {
    return "auto_reply_text_empty";
  }
  if (!state.ready) {
    return "session_not_ready";
  }
  if (message && message.fromMe) {
    return "from_me";
  }
  if (!messageBodyFrom(message)) {
    return "body_empty";
  }
  const senderDigits = senderDigitsFrom(message);
  if (!senderDigits) {
    return "sender_digits_missing";
  }
  const route = heyyAiRouteForMessage(message);
  if (!parseBoolean(route && route.auto_reply_enabled, String(route && route.ai_key || "").trim() === DEFAULT_HEYY_AI_KEY)) {
    return "route_auto_reply_disabled";
  }
  if (AUTO_REPLY_ALLOWED_RECIPIENTS.size === 0) {
    return "";
  }
  return AUTO_REPLY_ALLOWED_RECIPIENTS.has(senderDigits) ? "" : "recipient_not_allowed";
}

function shouldAutoReply(message) {
  return !autoReplySkipReason(message);
}

function routeQuietHoursActive(route, date = new Date()) {
  const startHour = boundedHour(route && route.quiet_hours_start_hour, -1);
  const endHour = boundedHour(route && route.quiet_hours_end_hour, -1);
  if (startHour < 0 || endHour < 0 || startHour === endHour) {
    return false;
  }
  const currentHour = date.getHours();
  if (startHour < endHour) {
    return currentHour >= startHour && currentHour < endHour;
  }
  return currentHour >= startHour || currentHour < endHour;
}

function randomPreReplyDelayMs(route) {
  const minSeconds = boundedDelaySeconds(route && route.pre_reply_delay_min_seconds, 0);
  const maxSeconds = boundedDelaySeconds(route && route.pre_reply_delay_max_seconds, minSeconds);
  const upperSeconds = Math.max(minSeconds, maxSeconds);
  if (upperSeconds <= 0) {
    return 0;
  }
  const selectedSeconds = minSeconds === upperSeconds
    ? minSeconds
    : minSeconds + Math.floor(Math.random() * (upperSeconds - minSeconds + 1));
  return selectedSeconds * 1000;
}

function typingDelayMsForText(route, text = "") {
  const perCharacterMs = boundedTypingDelayMs(route && route.typing_delay_ms_per_character);
  if (perCharacterMs > 0) {
    return boundedTypingDelayMs(Array.from(String(text || "")).length * perCharacterMs);
  }
  return boundedTypingDelayMs(route && route.typing_delay_ms);
}

async function showTypingStatusForChat(chat, route, text = "", options = {}) {
  const preReplyDelayMs = options && options.include_pre_reply_delay ? randomPreReplyDelayMs(route) : 0;
  if (preReplyDelayMs > 0) {
    await sleep(preReplyDelayMs);
  }
  const delayMs = typingDelayMsForText(route, text);
  const typingStatusEnabled = parseBoolean(
    route && route.typing_status_enabled,
    DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED
  );
  let statusSent = false;
  if (typingStatusEnabled && chat && typeof chat.sendStateTyping === "function") {
    try {
      await withTimeout(
        chat.sendStateTyping(),
        boundedConversationFetchTimeoutMs(),
        "typing_status_timeout"
      );
      statusSent = true;
    } catch (error) {
      console.warn(`[wa-web-session] typing status failed for ${SESSION_REF}: ${error.message || error}`);
    }
  }
  if (delayMs > 0) {
    await sleep(delayMs);
  }
  return { delay_ms: delayMs, pre_reply_delay_ms: preReplyDelayMs, status_sent: statusSent };
}

async function showTypingStatusForMessage(message, route, text = "") {
  let chat = null;
  try {
    chat = message && typeof message.getChat === "function"
      ? await withTimeout(message.getChat(), boundedConversationFetchTimeoutMs(), "inbound_chat_lookup_timeout")
      : null;
  } catch (error) {
    console.warn(`[wa-web-session] inbound chat lookup for typing failed for ${SESSION_REF}: ${error.message || error}`);
  }
  return showTypingStatusForChat(chat, route, text, { include_pre_reply_delay: true });
}

async function showTypingStatusForChatId(chatId, route, text = "", options = {}) {
  const preReplyDelayMs = options && options.include_pre_reply_delay ? randomPreReplyDelayMs(route) : 0;
  const delayMs = typingDelayMsForText(route, text);
  const typingStatusEnabled = parseBoolean(
    route && route.typing_status_enabled,
    DEFAULT_HEYY_AI_TYPING_STATUS_ENABLED
  );
  if (preReplyDelayMs <= 0 && delayMs <= 0 && !typingStatusEnabled) {
    return { delay_ms: 0, pre_reply_delay_ms: 0, status_sent: false };
  }
  let chat = null;
  try {
    chat = chatId && typeof client.getChatById === "function"
      ? await withTimeout(client.getChatById(chatId), boundedConversationFetchTimeoutMs(), "outbound_chat_lookup_timeout")
      : null;
  } catch (error) {
    console.warn(`[wa-web-session] outbound chat lookup for typing failed for ${SESSION_REF}: ${error.message || error}`);
  }
  return showTypingStatusForChat(chat, route, text, options);
}

async function downloadMediaViaStore(messageId) {
  return client.pupPage.evaluate(async (msgId) => {
    const collections = window.require("WAWebCollections");
    const msg = collections.Msg.get(msgId) || (await collections.Msg.getMessagesById([msgId]))?.messages?.[0];
    if (!msg) {
      return { ok: false, reason: "message_not_found" };
    }

    const directPath = msg.directPath || msg.mediaData?.directPath || "";
    const mediaKey = msg.mediaKey || msg.mediaData?.mediaKey || "";
    const mimetype = msg.mimetype || msg.mediaData?.mimetype || "";
    const filename = msg.filename || msg.caption || msg.title || "whatsapp-media";

    if (!directPath || !mediaKey) {
      return {
        ok: false,
        reason: "store_message_has_no_media",
        diagnostics: {
          body_present: Boolean((msg.body || msg.caption || "").trim()),
          direct_path_present: Boolean(directPath),
          media_key_present: Boolean(mediaKey),
          mimetype_present: Boolean(mimetype),
          size: Number(msg.size || msg.fileSize || 0) || 0,
          type: String(msg.type || "").trim()
        }
      };
    }

    if (msg.mediaData && msg.mediaData.mediaStage === "REUPLOADING") {
      return { ok: false, reason: "media_reuploading" };
    }
    if (msg.mediaData && msg.mediaData.mediaStage !== "RESOLVED") {
      await msg.downloadMedia({
        downloadEvenIfExpensive: true,
        rmrReason: 1
      });
    }
    if (msg.mediaData && (String(msg.mediaData.mediaStage || "").includes("ERROR") || msg.mediaData.mediaStage === "FETCHING")) {
      return { ok: false, reason: "media_not_available" };
    }

    try {
      const mockQpl = {
        addAnnotations() {
          return this;
        },
        addPoint() {
          return this;
        }
      };
      const decryptedMedia = await window.require("WAWebDownloadManager").downloadManager.downloadAndMaybeDecrypt({
        directPath,
        encFilehash: msg.encFilehash,
        filehash: msg.filehash,
        mediaKey,
        mediaKeyTimestamp: msg.mediaKeyTimestamp,
        type: msg.type,
        signal: new AbortController().signal,
        downloadQpl: mockQpl
      });
      const data = await window.WWebJS.arrayBufferToBase64Async(decryptedMedia);
      return {
        ok: true,
        media: {
          data,
          filename,
          filesize: Number(msg.size || msg.fileSize || 0) || 0,
          mimetype
        }
      };
    } catch (error) {
      if (error && error.status === 404) {
        return { ok: false, reason: "media_not_available" };
      }
      throw error;
    }
  }, messageId);
}

async function messageDiagnosticsViaStore(messageId) {
  return client.pupPage.evaluate(async (msgId) => {
    const collections = window.require("WAWebCollections");
    const msg = collections.Msg.get(msgId) || (await collections.Msg.getMessagesById([msgId]))?.messages?.[0];
    if (!msg) {
      return { found: false };
    }
    return {
      body: String(msg.body || "").trim(),
      body_present: Boolean(String(msg.body || "").trim()),
      caption: String(msg.caption || "").trim(),
      caption_present: Boolean(String(msg.caption || "").trim()),
      deprecated_mms3_url_present: Boolean(msg.deprecatedMms3Url),
      direct_path_present: Boolean(msg.directPath || msg.mediaData?.directPath),
      filehash_present: Boolean(msg.filehash),
      filename: String(msg.filename || "").trim(),
      found: true,
      media_key_present: Boolean(msg.mediaKey || msg.mediaData?.mediaKey),
      media_stage: String(msg.mediaData?.mediaStage || "").trim(),
      mimetype: String(msg.mimetype || msg.mediaData?.mimetype || "").trim(),
      mimetype_present: Boolean(msg.mimetype || msg.mediaData?.mimetype),
      size: Number(msg.size || msg.fileSize || 0) || 0,
      title: String(msg.title || "").trim(),
      type: String(msg.type || "").trim()
    };
  }, messageId);
}

function recordOutboundMessage(
  result,
  resolved,
  origin,
  text = "",
  heyyAiKey = "",
  heyyAiName = "",
  typingDelayMs = 0,
  typingStatusSent = false,
  buttonCount = 0,
  buttonsFallback = false,
  preReplyDelayMs = 0
) {
  const ack = ackValueFrom(result && result.ack);
  const messageId = messageIdFrom(result);
  const body = String(text || "").trim();
  const recorded = {
    ack,
    ack_at: "",
    ack_label: ackLabelFrom(ack),
    body_present: Boolean(body),
    button_count: Math.max(0, Number(buttonCount) || 0),
    buttons_fallback: Boolean(buttonsFallback),
    chat_id_kind: String(resolved && resolved.chat_id_kind ? resolved.chat_id_kind : "").trim(),
    chat_id_present: Boolean(resolved && resolved.chat_id_present),
    direction: "outbound",
    heyy_ai_key: String(heyyAiKey || "").trim(),
    heyy_ai_name: String(heyyAiName || "").trim(),
    id: messageId,
    origin: String(origin || "send").trim() || "send",
    sent_at: nowIso()
  };
  recorded.pre_reply_delay_ms = boundedTypingDelayMs(preReplyDelayMs);
  recorded.typing_delay_ms = boundedTypingDelayMs(typingDelayMs);
  recorded.typing_status_sent = Boolean(typingStatusSent);
  if (STORE_MESSAGE_TEXT) {
    recorded.body_text = body;
  }
  state.outbox.push(recorded);
  if (state.outbox.length > boundedInboxLimit()) {
    state.outbox = state.outbox.slice(-boundedInboxLimit());
  }
  state.lastSendAt = recorded.sent_at;
  return recorded;
}

function updateOutboundAck(message, ack) {
  const messageId = messageIdFrom(message);
  if (!messageId) {
    return null;
  }
  const ackValue = ackValueFrom(ack);
  const ackAt = nowIso();
  let recorded = null;
  for (let index = state.outbox.length - 1; index >= 0; index -= 1) {
    if (state.outbox[index].id === messageId) {
      recorded = state.outbox[index];
      break;
    }
  }
  if (!recorded) {
    recorded = {
      ack: null,
      ack_at: "",
      ack_label: "unknown",
      body_present: false,
      chat_id_kind: "",
      chat_id_present: false,
      direction: "outbound",
      heyy_ai_key: "",
      heyy_ai_name: "",
      id: messageId,
      origin: "external",
      sent_at: ""
    };
    state.outbox.push(recorded);
  }
  recorded.ack = ackValue;
  recorded.ack_at = ackAt;
  recorded.ack_label = ackLabelFrom(ackValue);
  state.lastAckAt = ackAt;
  if (state.outbox.length > boundedInboxLimit()) {
    state.outbox = state.outbox.slice(-boundedInboxLimit());
  }
  return recorded;
}

function recordInboundMessage(message) {
  const senderDigits = senderDigitsFrom(message);
  const body = messageBodyFrom(message);
  const selectedButtonId = actionButtonIdFrom(message);
  const chatId = chatIdFromWid(message && message.id && message.id.remote ? message.id.remote : null);
  const chatRef = chatRefFromChatId(chatId);
  const route = heyyAiRouteForSenderDigits(senderDigits);
  const recorded = {
    body_present: Boolean(body),
    chat_id_kind: chatIdKindFrom(chatId),
    chat_ref: chatRef,
    direction: "inbound",
    from_me: Boolean(message && message.fromMe),
    from_present: Boolean(senderDigits),
    heyy_ai_key: route.ai_key,
    heyy_ai_name: route.ai_name,
    heyy_ai_route_matched: route.matched,
    id: messageIdFrom(message),
    media_filename: messageMediaFilenameFrom(message),
    media_mime_type: messageMediaMimeTypeFrom(message),
    media_present: messageHasDownloadableMedia(message),
    media_size: messageMediaSizeFrom(message),
    received_at: nowIso(),
    selected_button_kind: selectedButtonKindFrom(selectedButtonId),
    selected_button_id_present: Boolean(selectedButtonId),
    sender_digits: senderDigits,
    type: messageTypeFrom(message)
  };
  if (selectedButtonId) {
    recorded.selected_button_id = selectedButtonId;
  }
  if (STORE_MESSAGE_TEXT) {
    recorded.body_text = body;
  }
  state.lastInboundAt = recorded.received_at;
  state.inbox.push(recorded);
  if (state.inbox.length > boundedInboxLimit()) {
    state.inbox = state.inbox.slice(-boundedInboxLimit());
  }
  return recorded;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function removeStaleChromiumLocks(rootDir) {
  const lockNames = new Set(["SingletonCookie", "SingletonLock", "SingletonSocket"]);
  const stack = [rootDir];
  while (stack.length > 0) {
    const current = stack.pop();
    let entries = [];
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch (_error) {
      continue;
    }
    for (const entry of entries) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(fullPath);
        continue;
      }
      if (!lockNames.has(entry.name)) {
        continue;
      }
      try {
        fs.rmSync(fullPath, { force: true });
        console.log(`[wa-web-session] removed stale Chromium lock ${fullPath}`);
      } catch (error) {
        console.warn(`[wa-web-session] could not remove stale Chromium lock ${fullPath}: ${error.message || error}`);
      }
    }
  }
}

removeStaleChromiumLocks(DATA_DIR);

const client = new Client({
  authStrategy: new LocalAuth({
    clientId: SESSION_REF,
    dataPath: DATA_DIR
  }),
  puppeteer: {
    executablePath: CHROMIUM_PATH,
    args: [
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--no-sandbox"
    ]
  }
});

client.on("qr", (qr) => {
  state.latestQr = qr;
  state.lastQrAt = nowIso();
  state.ready = false;
  state.status = "qr_required";
  console.log(`[wa-web-session] QR required for ${SESSION_REF}; scan the QR below.`);
  qrcode.generate(qr, { small: true });
});

client.on("authenticated", () => {
  state.authenticated = true;
  state.status = "authenticated";
  console.log(`[wa-web-session] authenticated ${SESSION_REF}`);
});

client.on("auth_failure", (message) => {
  state.authenticated = false;
  state.lastError = String(message || "auth_failure");
  state.ready = false;
  state.status = "auth_failure";
  console.error(`[wa-web-session] auth failure for ${SESSION_REF}: ${state.lastError}`);
});

client.on("ready", () => {
  state.authenticated = true;
  state.lastReadyAt = nowIso();
  state.latestQr = "";
  state.ready = true;
  state.status = "ready";
  console.log(`[wa-web-session] ready ${SESSION_REF}`);
});

client.on("disconnected", (reason) => {
  state.authenticated = false;
  state.lastError = String(reason || "disconnected");
  state.ready = false;
  state.status = "disconnected";
  console.warn(`[wa-web-session] disconnected ${SESSION_REF}: ${state.lastError}`);
});

client.on("message", async (message) => {
  const recorded = recordInboundMessage(message);
  console.log(`[wa-web-session] inbound message for ${SESSION_REF}; sender_present=${recorded.from_present}`);
  const skipReason = autoReplySkipReason(message);
  if (skipReason) {
    console.log(`[wa-web-session] auto-reply skipped for ${SESSION_REF}; reason=${skipReason}`);
    return;
  }
  try {
    const route = heyyAiRouteForMessage(message);
    const replyText = autoReplyTextForMessage(message, route);
    if (!replyText) {
      console.log(`[wa-web-session] auto-reply skipped for ${SESSION_REF}; reason=reply_text_empty`);
      return;
    }
    if (routeQuietHoursActive(route)) {
      console.log(`[wa-web-session] auto-reply skipped for ${SESSION_REF}; route_quiet_hours_active=true`);
      return;
    }
    const typing = await showTypingStatusForMessage(message, route, replyText);
    const sendTimeoutMs = boundedSendTimeoutMs();
    console.log(
      `[wa-web-session] sending auto-reply for ${SESSION_REF}; ` +
      `chat_id_present=${Boolean(message.from)} timeout_ms=${sendTimeoutMs}`
    );
    const result = await withTimeout(
      client.sendMessage(message.from, replyText),
      sendTimeoutMs,
      "auto_reply_send_timeout"
    );
    const recordedReply = recordOutboundMessage(
      result,
      {
        chat_id_kind: chatIdKindFrom(message.from),
        chat_id_present: Boolean(message.from)
      },
      "auto_reply",
      replyText,
      route.ai_key,
      route.ai_name,
      typing.delay_ms,
      typing.status_sent,
      0,
      false,
      typing.pre_reply_delay_ms
    );
    console.log(
      `[wa-web-session] auto-replied for ${SESSION_REF}; message_id_present=${Boolean(recordedReply.id)} ` +
      `pre_reply_delay_ms=${recordedReply.pre_reply_delay_ms} typing_status_sent=${recordedReply.typing_status_sent}`
    );
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "auto_reply_failed");
    console.error(`[wa-web-session] auto-reply failed for ${SESSION_REF}: ${state.lastError}`);
  }
});

client.on("vote_update", (vote) => {
  const recorded = recordPollVoteAsInbound(vote);
  if (!recorded) {
    return;
  }
  console.log(
    `[wa-web-session] inbound poll vote for ${SESSION_REF}; ` +
    `selected_button_present=${recorded.selected_button_id_present} sender_present=${recorded.from_present}`
  );
});

client.on("message_ack", (message, ack) => {
  const recorded = updateOutboundAck(message, ack);
  if (!recorded) {
    return;
  }
  console.log(
    `[wa-web-session] message ack for ${SESSION_REF}; message_id_present=${Boolean(recorded.id)} ` +
    `ack=${recorded.ack_label}`
  );
});

const app = express();
app.use((req, res, next) => {
  const startedAt = Date.now();
  console.log(
    `[wa-web-session] request start for ${SESSION_REF}; ` +
    `method=${req.method} path=${req.originalUrl || req.url} content_length=${req.get("content-length") || ""} content_type=${req.get("content-type") || ""}`
  );
  req.on("aborted", () => {
    console.warn(
      `[wa-web-session] request aborted for ${SESSION_REF}; ` +
      `method=${req.method} path=${req.originalUrl || req.url}`
    );
  });
  res.on("finish", () => {
    console.log(
      `[wa-web-session] request finish for ${SESSION_REF}; ` +
      `method=${req.method} path=${req.originalUrl || req.url} status=${res.statusCode} duration_ms=${Date.now() - startedAt}`
    );
  });
  next();
});
app.use(express.json({ limit: JSON_LIMIT }));
app.use((error, req, res, next) => {
  if (!error) {
    next();
    return;
  }
  const message = error && error.message ? String(error.message) : String(error || "json_parse_failed");
  console.error(
    `[wa-web-session] request middleware error for ${SESSION_REF}; ` +
    `method=${req.method} path=${req.originalUrl || req.url} error=${message}`
  );
  res.status(400).json({ ok: false, reason: "request_middleware_error", error: message });
});

app.get("/healthz", (_req, res) => {
  const ok = state.status !== "initialize_failed";
  res.status(ok ? 200 : 503).json({ ok, session_ref: SESSION_REF, status: state.status });
});

app.get("/sessions/:sessionRef/status", requireAuth, (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  res.json(sessionStatus());
});

app.get("/sessions/:sessionRef/qr", requireAuth, (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  const includeQr = String(req.query.include || req.query.raw || "").trim() === "1";
  const payload = {
    last_qr_at: state.lastQrAt,
    ok: true,
    qr_present: Boolean(state.latestQr),
    qr_required: state.status === "qr_required",
    ready: state.ready,
    session_ref: SESSION_REF,
    status: state.status
  };
  if (includeQr) {
    payload.qr = state.latestQr;
  }
  res.json(payload);
});

app.get("/sessions/:sessionRef/messages", requireAuth, (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  const take = Math.max(1, Math.min(Number.parseInt(String(req.query.take || "25"), 10) || 25, 100));
  const messages = state.inbox.slice(-take);
  res.json({
    auto_reply_enabled: AUTO_REPLY_ENABLED,
    inbox_count: state.inbox.length,
    last_inbound_at: state.lastInboundAt,
    messages,
    ok: true,
    ready: state.ready,
    session_ref: SESSION_REF,
    status: state.status
  });
});

app.get("/sessions/:sessionRef/messages/:messageId/media", requireAuth, async (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  if (!state.ready) {
    res.status(409).json({ ok: false, reason: "session_not_ready", status: state.status });
    return;
  }
  const messageId = String(req.params.messageId || "").trim();
  if (!messageId) {
    res.status(400).json({ ok: false, reason: "message_id_required" });
    return;
  }
  try {
    const message = await client.getMessageById(messageId);
    if (!message) {
      res.status(404).json({ ok: false, reason: "message_not_found" });
      return;
    }
    let media = null;
    if (message.hasMedia && typeof message.downloadMedia === "function") {
      media = await message.downloadMedia();
    }
    if (!media || !media.data) {
      const fallback = await downloadMediaViaStore(messageId);
      if (fallback && fallback.ok && fallback.media && fallback.media.data) {
        media = fallback.media;
      } else if (!media || !media.data) {
        const reason = fallback && fallback.reason ? String(fallback.reason) : "media_not_available";
        res.status(reason === "store_message_has_no_media" ? 404 : 502).json({ ok: false, reason });
        return;
      }
    }
    if (!media || !media.data) {
      res.status(404).json({ ok: false, reason: "message_has_no_media" });
      return;
    }
    const buffer = Buffer.from(String(media.data || ""), "base64");
    const mimetype = safeHeaderValue(media.mimetype || messageMediaMimeTypeFrom(message), "application/octet-stream");
    const filename = safeHeaderValue(media.filename || messageMediaFilenameFrom(message), "whatsapp-media");
    res.setHeader("Content-Type", mimetype);
    res.setHeader("Content-Length", String(buffer.length));
    res.setHeader("X-WA-Media-Filename", filename);
    res.setHeader("X-WA-Media-Mimetype", mimetype);
    res.send(buffer);
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "media_download_failed");
    res.status(500).json({ ok: false, reason: "media_download_failed" });
  }
});

app.get("/sessions/:sessionRef/messages/:messageId/diagnostics", requireAuth, async (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  if (!state.ready) {
    res.status(409).json({ ok: false, reason: "session_not_ready", status: state.status });
    return;
  }
  const messageId = String(req.params.messageId || "").trim();
  if (!messageId) {
    res.status(400).json({ ok: false, reason: "message_id_required" });
    return;
  }
  try {
    const message = await client.getMessageById(messageId);
    const store = await messageDiagnosticsViaStore(messageId);
    const payload = {
      message_id: messageId,
      ok: true,
      ready: state.ready,
      session_ref: SESSION_REF,
      state_message_found: Boolean(message),
      status: state.status,
      store
    };
    if (message) {
      payload.state_message = {
        body_present: Boolean(messageBodyFrom(message)),
        body_text: messageBodyFrom(message),
        has_media: Boolean(message.hasMedia),
        media_filename: messageMediaFilenameFrom(message),
        media_mime_type: messageMediaMimeTypeFrom(message),
        media_present: messageHasDownloadableMedia(message),
        media_size: messageMediaSizeFrom(message),
        type: messageTypeFrom(message)
      };
    }
    res.json(payload);
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "message_diagnostics_failed");
    res.status(500).json({ ok: false, reason: "message_diagnostics_failed" });
  }
});

app.get("/sessions/:sessionRef/outbox", requireAuth, (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  const take = Math.max(1, Math.min(Number.parseInt(String(req.query.take || "25"), 10) || 25, 100));
  const messages = state.outbox.slice(-take);
  res.json({
    last_ack_at: state.lastAckAt,
    last_send_at: state.lastSendAt,
    messages,
    ok: true,
    outbox_count: state.outbox.length,
    ready: state.ready,
    session_ref: SESSION_REF,
    status: state.status
  });
});

app.get("/sessions/:sessionRef/heyy-ai-routes", requireAuth, (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  res.json({
    default_heyy_ai_key: DEFAULT_HEYY_AI_KEY,
    default_heyy_ai_name: DEFAULT_HEYY_AI_NAME,
    ok: true,
    route_count: Object.keys(state.heyyAiRouteMap).length,
    routes: publicHeyyAiRoutes(),
    session_ref: SESSION_REF,
    status: state.status
  });
});

app.put("/sessions/:sessionRef/heyy-ai-routes", requireAuth, (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  const routes = req.body && (req.body.routes || req.body.route_map || req.body);
  const normalized = normalizeHeyyAiRouteMap(routes);
  state.heyyAiRouteMap = normalized;
  const persisted = persistHeyyAiRouteMap(normalized);
  res.json({
    last_route_map_persist_at: state.lastRouteMapPersistAt,
    ok: true,
    route_count: Object.keys(state.heyyAiRouteMap).length,
    route_map_persisted: persisted,
    routes: publicHeyyAiRoutes(),
    session_ref: SESSION_REF,
    status: state.status
  });
});

app.get("/sessions/:sessionRef/conversations", requireAuth, async (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  if (!state.ready) {
    res.status(409).json({ ok: false, reason: "session_not_ready", status: state.status });
    return;
  }

  const take = Math.max(1, Math.min(Number.parseInt(String(req.query.take || "25"), 10) || 25, 100));
  const skip = Math.max(0, Math.min(Number.parseInt(String(req.query.skip || "0"), 10) || 0, 100000));
  const messageLimit = Math.max(1, Math.min(Number.parseInt(String(req.query.messages || "25"), 10) || 25, 100));
  const fetchTimeoutMs = boundedConversationFetchTimeoutMs(req.query.fetch_timeout_ms || req.query.timeout_ms);
  const fetchConcurrency = boundedConversationFetchConcurrency(req.query.fetch_concurrency || req.query.concurrency);
  try {
    const chats = await withTimeout(client.getChats(), fetchTimeoutMs, "chats_fetch_timeout");
    const sortedChats = chats
      .slice()
      .sort((left, right) => Number(right.timestamp || 0) - Number(left.timestamp || 0));
    const selectedChats = sortedChats.slice(skip, skip + take);
    const conversations = await mapWithConcurrency(selectedChats, fetchConcurrency, async (chat) => {
      const chatSummary = sanitizedChatFrom(chat);
      let messages = [];
      let fetchError = "";
      try {
        const fetched = await withTimeout(
          chat.fetchMessages({ limit: messageLimit }),
          fetchTimeoutMs,
          "conversation_fetch_timeout"
        );
        messages = fetched.map((message) => sanitizedMessageFrom(message, chatSummary.chat_ref));
      } catch (error) {
        state.lastError = conversationFetchErrorSummary(error);
        fetchError = state.lastError;
      }
      return {
        ...chatSummary,
        fetch_error_present: Boolean(fetchError),
        messages,
        message_count: messages.length
      };
    });
    const nextConversationSkip = skip + selectedChats.length < sortedChats.length ? skip + selectedChats.length : 0;
    res.json({
      conversation_count: conversations.length,
      conversation_page_complete: skip + selectedChats.length >= sortedChats.length,
      conversation_skip: skip,
      conversation_total: sortedChats.length,
      conversations,
      fetch_concurrency: fetchConcurrency,
      fetch_timeout_ms: fetchTimeoutMs,
      message_limit: messageLimit,
      next_conversation_skip: nextConversationSkip,
      ok: true,
      ready: state.ready,
      session_ref: SESSION_REF,
      status: state.status,
      store_message_text: STORE_MESSAGE_TEXT
    });
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "conversations_failed");
    res.status(502).json({ ok: false, reason: "conversations_failed" });
  }
});

app.get("/sessions/:sessionRef/recipients/:recipient", requireAuth, async (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  if (!state.ready) {
    res.status(409).json({ ok: false, reason: "session_not_ready", status: state.status });
    return;
  }

  const recipient = normalizeRecipient(req.params.recipient);
  if (!recipient) {
    res.status(400).json({ ok: false, reason: "recipient_required" });
    return;
  }

  try {
    const resolved = await resolveRecipientChat(recipient);
    res.json({
      chat_id_kind: resolved.chat_id_kind,
      chat_id_present: resolved.chat_id_present,
      lid_chat_id_present: resolved.lid_chat_id_present,
      lid_lookup_failed: resolved.lid_lookup_failed,
      matches_current_account: resolved.matches_current_account,
      ok: true,
      phone_chat_id_present: resolved.phone_chat_id_present,
      ready: state.ready,
      registered: resolved.registered,
      resolution_method: resolved.resolution_method,
      session_ref: SESSION_REF,
      status: state.status
    });
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "recipient_resolve_failed");
    res.status(502).json({ ok: false, reason: "recipient_resolve_failed" });
  }
});

app.get("/sessions/:sessionRef/qr.svg", requireAuth, async (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).type("text/plain").send("session_not_found");
    return;
  }
  if (!state.latestQr) {
    res.status(404).type("text/plain").send("qr_not_available");
    return;
  }
  try {
    const svg = await qrImage.toString(state.latestQr, {
      errorCorrectionLevel: "M",
      margin: 2,
      type: "svg",
      width: 360
    });
    res.set("Cache-Control", "no-store");
    res.type("image/svg+xml").send(svg);
  } catch (_error) {
    res.status(500).type("text/plain").send("qr_render_failed");
  }
});

app.get("/sessions/:sessionRef/pair", requireAuth, (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).type("text/plain").send("session_not_found");
    return;
  }
  const qrUrl = `/sessions/${encodeURIComponent(SESSION_REF)}/qr.svg?ts=${encodeURIComponent(state.lastQrAt || nowIso())}`;
  const status = escapeHtml(state.status);
  const label = escapeHtml(SESSION_LABEL);
  const sessionRef = escapeHtml(SESSION_REF);
  const lastQrAt = escapeHtml(state.lastQrAt || "");
  const body = state.ready
    ? `<p class="state ready">Session is ready.</p>`
    : state.latestQr
      ? `<img src="${qrUrl}" alt="WhatsApp Web pairing QR code" width="360" height="360">`
      : `<p class="state waiting">QR code is not available yet. Refresh in a few seconds.</p>`;
  res.set("Cache-Control", "no-store");
  res.type("html").send(`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EA WhatsApp Web Pairing</title>
  <style>
    body { background: #f7f7f4; color: #1f2933; font: 16px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; }
    main { margin: 40px auto; max-width: 520px; padding: 0 24px; }
    h1 { font-size: 24px; margin: 0 0 12px; }
    img { background: white; border: 1px solid #d6d3cc; display: block; margin: 24px 0; padding: 16px; }
    dl { display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; margin-top: 20px; }
    dt { color: #59636e; }
    dd { margin: 0; overflow-wrap: anywhere; }
    .ready { color: #116329; }
    .waiting { color: #7a4b00; }
  </style>
</head>
<body>
  <main>
    <h1>${label}</h1>
    ${body}
    <dl>
      <dt>Session</dt><dd>${sessionRef}</dd>
      <dt>Status</dt><dd>${status}</dd>
      <dt>Last QR</dt><dd>${lastQrAt || "not available"}</dd>
    </dl>
  </main>
</body>
</html>`);
});

app.post("/sessions/:sessionRef/messages", requireAuth, async (req, res) => {
  if (String(req.params.sessionRef || "") !== SESSION_REF) {
    res.status(404).json({ ok: false, reason: "session_not_found" });
    return;
  }
  if (!state.ready) {
    res.status(409).json({ ok: false, reason: "session_not_ready", status: state.status });
    return;
  }

  const recipient = normalizeRecipient(req.body && req.body.to);
  const chatRef = String(req.body && (req.body.chat_ref || req.body.chatRef) || "").trim();
  const text = String(req.body && req.body.text ? req.body.text : "").trim();
  let buttonRows = [];
  try {
    buttonRows = normalizeButtonRows(req.body && (req.body.buttons || req.body.inline_buttons));
  } catch (error) {
    res.status(400).json({ ok: false, reason: error && error.message ? String(error.message) : "buttons_invalid" });
    return;
  }
  let outboundMedia = null;
  try {
    outboundMedia = outboundMediaFromRequest(req.body);
  } catch (error) {
    res.status(400).json({ ok: false, reason: error && error.message ? String(error.message) : "media_invalid" });
    return;
  }
  if (!recipient && !chatRef) {
    res.status(400).json({ ok: false, reason: "recipient_required" });
    return;
  }
  if (!text && !outboundMedia) {
    res.status(400).json({ ok: false, reason: "text_required" });
    return;
  }

  try {
    console.log(
      `[wa-web-session] outbound request for ${SESSION_REF}; ` +
      `recipient_present=${Boolean(recipient)} chat_ref_present=${Boolean(chatRef)} text_present=${Boolean(text)} media_present=${Boolean(outboundMedia)}`
    );
    let resolved = chatRef ? resolvedChatFromChatRef(chatRef) : { chatId: "" };
    if (!resolved.chatId && recipient) {
      console.log(
        `[wa-web-session] resolving outbound recipient for ${SESSION_REF}; ` +
        `recipient=${recipient}`
      );
      resolved = await resolveRecipientChat(recipient);
    }
    if (!resolved.chatId) {
      res.status(404).json({
        chat_id_kind: resolved.chat_id_kind,
        chat_id_present: false,
        chat_ref_present: Boolean(chatRef),
        matches_current_account: resolved.matches_current_account,
        ok: false,
        lid_chat_id_present: resolved.lid_chat_id_present,
        lid_lookup_failed: resolved.lid_lookup_failed,
        phone_chat_id_present: resolved.phone_chat_id_present,
        reason: chatRef ? "chat_ref_not_found" : "recipient_not_registered",
        registered: false,
        resolution_method: resolved.resolution_method,
        session_ref: SESSION_REF
      });
      return;
    }
    const route = heyyAiRouteForSenderDigits(recipient);
    const outboundRouteBase = routeWithOutboundPersonaOverride(route, req.body || {});
    const hasTypingDelayOverride = Object.prototype.hasOwnProperty.call(req.body || {}, "typing_delay_ms");
    const hasTypingDelayPerCharacterOverride = Object.prototype.hasOwnProperty.call(req.body || {}, "typing_delay_ms_per_character")
      || Object.prototype.hasOwnProperty.call(req.body || {}, "typingDelayMsPerCharacter");
    const hasTypingStatusOverride = Object.prototype.hasOwnProperty.call(req.body || {}, "typing_status_enabled")
      || Object.prototype.hasOwnProperty.call(req.body || {}, "typing_status");
    const outboundRoute = {
      ...outboundRouteBase,
      typing_delay_ms_per_character: hasTypingDelayPerCharacterOverride
        ? boundedTypingDelayMs(req.body.typing_delay_ms_per_character ?? req.body.typingDelayMsPerCharacter)
        : (hasTypingDelayOverride ? 0 : outboundRouteBase.typing_delay_ms_per_character),
      typing_delay_ms: hasTypingDelayOverride
        ? boundedTypingDelayMs(req.body.typing_delay_ms)
        : outboundRouteBase.typing_delay_ms,
      typing_status_enabled: hasTypingStatusOverride
        ? parseBoolean(req.body.typing_status_enabled ?? req.body.typing_status, outboundRouteBase.typing_status_enabled)
        : outboundRouteBase.typing_status_enabled
    };
    const sendContent = outboundMedia
      ? {
        button_count: 0,
        buttons_fallback: false,
        control_kind: "media",
        content: outboundMedia,
        options: text ? { caption: text } : {},
        rendered_text: text
      }
      : buildSendMessageContent(text, buttonRows);
    if (routeQuietHoursActive(outboundRoute)) {
      res.status(409).json({
        chat_id_kind: resolved.chat_id_kind,
        chat_id_present: resolved.chat_id_present,
        heyy_ai_key: outboundRoute.ai_key,
        heyy_ai_name: outboundRoute.ai_name,
        matches_current_account: resolved.matches_current_account,
        ok: false,
        reason: "route_quiet_hours_active",
        registered: resolved.registered,
        session_ref: SESSION_REF,
        status: state.status
      });
      return;
    }
    const typing = await showTypingStatusForChatId(
      resolved.chatId,
      outboundRoute,
      sendContent.rendered_text,
      { include_pre_reply_delay: true }
    );
    if (!outboundMedia && sendContent.control_kind !== "poll") {
      storeRecentButtonMap(resolved.chatId, buttonRows);
    }
    const sendTimeoutMs = boundedSendTimeoutMs();
    console.log(
      `[wa-web-session] outbound message prepared for ${SESSION_REF}; ` +
      `chat_id_kind=${resolved.chat_id_kind} control_kind=${sendContent.control_kind || "chat"}`
    );
    console.log(
      `[wa-web-session] sending outbound message for ${SESSION_REF}; ` +
      `chat_id_kind=${resolved.chat_id_kind} control_kind=${sendContent.control_kind || "chat"} timeout_ms=${sendTimeoutMs}`
    );
    const result = await withTimeout(
      client.sendMessage(resolved.chatId, sendContent.content, sendContent.options || undefined),
      sendTimeoutMs,
      "outbound_send_timeout"
    );
    if (!outboundMedia && sendContent.control_kind === "poll") {
      storeRecentPollMap(result, resolved.chatId, buttonRows);
    }
    const recorded = recordOutboundMessage(
      result,
      resolved,
      "send",
      sendContent.rendered_text,
      outboundRoute.ai_key,
      outboundRoute.ai_name,
      typing.delay_ms,
      typing.status_sent,
      sendContent.button_count,
      sendContent.buttons_fallback,
      typing.pre_reply_delay_ms
    );
    console.log(
      `[wa-web-session] sent message for ${SESSION_REF}; message_id_present=${Boolean(recorded.id)} ` +
      `chat_id_kind=${resolved.chat_id_kind} ack=${recorded.ack_label} typing_status_sent=${recorded.typing_status_sent}`
    );
    res.json({
      ack: recorded.ack,
      ack_label: recorded.ack_label,
      button_count: recorded.button_count,
      buttons_fallback: recorded.buttons_fallback,
      chat_id_kind: resolved.chat_id_kind,
      chat_id_present: resolved.chat_id_present,
      control_kind: sendContent.control_kind || "",
      heyy_ai_key: outboundRoute.ai_key,
      heyy_ai_name: outboundRoute.ai_name,
      id: recorded.id,
      matches_current_account: resolved.matches_current_account,
      message_id: recorded.id,
      messages: recorded.id ? [{ id: recorded.id }] : [],
      ok: true,
      registered: resolved.registered,
      session_ref: SESSION_REF,
      status: "sent",
      pre_reply_delay_ms: recorded.pre_reply_delay_ms,
      typing_delay_ms: recorded.typing_delay_ms,
      typing_status_sent: recorded.typing_status_sent
    });
  } catch (error) {
    state.lastError = error && error.message ? String(error.message) : String(error || "send_failed");
    res.status(502).json({ ok: false, reason: "send_failed" });
  }
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[wa-web-session] listening on 0.0.0.0:${PORT} for ${SESSION_REF}`);
});

client.initialize().catch((error) => {
  state.lastError = error && error.message ? String(error.message) : String(error || "initialize_failed");
  state.status = "initialize_failed";
  console.error(`[wa-web-session] initialize failed for ${SESSION_REF}: ${state.lastError}`);
});
