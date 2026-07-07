# Environment Matrix

## Core Variables

- `EA_RUNTIME_MODE`:
  - `dev` -> local-default ergonomics; memory fallback allowed
  - `test` -> CI/test ergonomics; memory fallback allowed
  - `prod` -> fail fast if durable Postgres boot is not available
- `EA_STORAGE_BACKEND`:
  - `memory` -> in-process repositories only
  - `postgres` -> force Postgres repositories
  - `auto` -> try Postgres, fallback to memory outside `prod`
- `EA_LEDGER_BACKEND`: deprecated compatibility alias for `EA_STORAGE_BACKEND`
- `DATABASE_URL`: required for reliable Postgres-backed operation
- `EA_DEFAULT_PRINCIPAL_ID`: fallback request principal for principal-scoped connector/memory routes when `X-EA-Principal-ID` is omitted
- `EA_BOOTSTRAP_DB=1`: optional deploy-time migration bootstrap
- `EA_SIGNING_SECRET`: required in `prod`; keeps workspace links, browser sessions, and signed action tokens stable across restarts
- `EA_WORKSPACE_ACCESS_TOKEN_ISSUER`: in `prod`, set explicitly or let it derive from `EA_PUBLIC_APP_BASE_URL`; do not rely on the generic `ea://workspace-access` fallback
- `EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE`: workspace-access session audience label; keep explicit in `prod`
- `EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION`: workspace-access signing key version label; keep explicit in `prod`
- `EA_CF_TUNNEL_TOKEN`: optional Cloudflare Tunnel token used only when `docker-compose.cloudflared.yml` is layered onto the base compose stack

## Responses Provider Variables

- `ONEMIN_AI_API_KEY` plus sequential `ONEMIN_AI_API_KEY_FALLBACK_N` slots: ordered 1min.AI account slots used by the Responses facade and surfaced back as account names in provider-health payloads. The shipped env templates currently include placeholders through `ONEMIN_AI_API_KEY_FALLBACK_33`.
- `EA_RESPONSES_DEFAULT_PROFILE`: explicit default public lane profile for generic `/v1/responses` traffic; use `easy` to keep unattended callers out of the hard lane by default.
- `EA_RESPONSES_PROVIDER_ORDER`, `EA_RESPONSES_FAST_PROVIDER_ORDER`, `EA_RESPONSES_CHEAP_PROVIDER_ORDER`, `EA_RESPONSES_GROUNDWORK_PROVIDER_ORDER`, and `EA_RESPONSES_HARD_PROVIDER_ORDER`: provider preference orders for normal, fast, cheap/background, groundwork, and hard lanes; default to `onemin,magixai,gemini_vortex` so the 1minAI manager stays primary whenever usable and Gemini/Vertex remains a fallback path across every lane.
- `EA_RESPONSES_MAGICX_HEALTH_CHECK`, `EA_RESPONSES_MAGICX_HEALTH_INTERVAL_SECONDS`, `EA_RESPONSES_MAGICX_HEALTH_TIMEOUT_SECONDS`: enable and tune live Magicx readiness probes so fallback state is based on a real upstream check.
- `EA_RESPONSES_ONEMIN_INCLUDED_CREDITS_PER_KEY` and `EA_RESPONSES_ONEMIN_BONUS_CREDITS_PER_KEY`: baseline credits per 1min.AI slot used to estimate `estimated_remaining_credits_total` and `remaining_percent_of_max` before a depletion error is observed.
- `EA_RESPONSES_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS`: long quarantine applied when 1min.AI reports a deleted or inactive key so the slot remains visibly `deleted`.
- `EA_RESPONSES_ONEMIN_OWNER_LEDGER_PATH`: JSON file that maps each 1min slot to a human owner label/email via SHA-256 hashes and/or stable slot/account identifiers without storing raw API keys in repo config.
- `EA_RESPONSES_ONEMIN_PROBE_MODEL` and `EA_RESPONSES_ONEMIN_PROBE_TIMEOUT_SECONDS`: tune the explicit `POST /v1/providers/onemin/probe-all` sweep so operators can validate every configured slot on demand.
- `EA_RESPONSES_ONEMIN_ACTIVE_SLOTS` and `EA_RESPONSES_ONEMIN_RESERVE_SLOTS`: split the live 1min pool into a small hot set and a colder reserve set so generic background work does not immediately walk the whole key inventory.
- `EA_RESPONSES_ONEMIN_MAX_REQUESTS_PER_HOUR`, `EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_HOUR`, and `EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_DAY`: hard budget gates for the 1min lane; when exceeded, the Responses facade downgrades or refuses additional 1min-heavy work.
- `EA_RESPONSES_HARD_MAX_ACTIVE_REQUESTS`, `EA_RESPONSES_HARD_QUEUE_TIMEOUT_SECONDS`, `EA_RESPONSES_MAX_OUTPUT_TOKENS_FAST`, `EA_RESPONSES_MAX_OUTPUT_TOKENS_REVIEW`, `EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD`, and `EA_RESPONSES_MAX_OUTPUT_TOKENS_OVERFLOW`: lane-level concurrency and output caps for keeping unattended work in a bounded budget envelope.
- `EA_RESPONSES_MAGICX_API_KEY`: primary MagicX account name surfaced in `/v1/codex/profiles` and `/v1/responses/_provider_health`.
- `BROWSERACT_API_KEY` plus `BROWSERACT_API_KEY_FALLBACK_1` through `BROWSERACT_API_KEY_FALLBACK_3`: audit-lane ChatPlayground slots surfaced as `chatplayground_accounts` in provider-health payloads.
- `EA_SURVIVAL_ENABLED`, `EA_SURVIVAL_ROUTE_ORDER`, `EA_SURVIVAL_QUEUE_TIMEOUT_SECONDS`, `EA_SURVIVAL_MAX_OUTPUT_TOKENS`, and `EA_SURVIVAL_CACHE_TTL_SECONDS`: control the explicit survival lane used by `POST /v1/codex/survival` and the `ea-coder-survival` alias. The shipped default route is `onemin,chatplayground,gemini_vortex,gemini_web` so survival starts with the direct 1min backend, keeps a non-Gemini UI fallback ahead of Gemini, and only reaches Gemini when the earlier lanes do not hold.
- `EA_SURVIVAL_GEMINI_WEB_MODE`, `EA_SURVIVAL_GEMINI_WEB_ALLOW_DEEP_THINK`, `EA_SURVIVAL_GEMINI_WEB_TIMEOUT_SECONDS`, and `BROWSERACT_GEMINI_WEB_URL`: govern the BrowserAct-backed Gemini web fallback after the local Gemini Vortex attempt.
- `EA_SURVIVAL_CHATPLAYGROUND_SINGLE_ROLE`: limits the last-resort ChatPlayground tie-break to a single role instead of the normal multi-role jury lane.
- `EA_UI_CHALLENGE_COOLDOWN_SECONDS` and `EA_UI_CHALLENGE_MAX_CONSECUTIVE`: control how long survival skips a UI-backed backend after a Cloudflare/Turnstile/human-verification or session-expiry failure before retrying it.

## Memorial Voice Variables

- `EA_MEMORIAL_SHADOW_STT_PROVIDER`: shadow speech-to-text provider for memorial user-question audio. Current allowed value is `blipai`.
- `EA_MEMORIAL_SHADOW_STT_URL`: optional explicit shadow STT endpoint. If unset and a BlipAI token is available, the memorial route falls back to BlipAI's official STT endpoint.
- `EA_MEMORIAL_SHADOW_STT_API_KEY`: explicit shadow STT bearer token. If unset for `blipai`, runtime lookup falls back to the persisted BlipAI token state and then `BLIPAI_APP_API_TOKEN`.
- `EA_MEMORIAL_SHADOW_STT_REFRESH_TOKEN`: preferred refresh token used to recover an expired BlipAI access token before the lane enters cooldown.
- `BLIPAI_APP_API_TOKEN`: fallback BlipAI access token used when no explicit memorial shadow token is configured.
- `BLIPAI_APP_REFRESH_TOKEN`: fallback BlipAI refresh token used when no explicit memorial refresh token is configured.
- `EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH`: optional override for the persisted refreshed-token state file. Default is `state/memorial_blipai_shadow_stt_tokens.json` under the configured memorial state directory.
- `EA_MEMORIAL_SHADOW_STT_TIMEOUT_SECONDS`: per-request timeout for the shadow STT provider call.
- `EA_MEMORIAL_SHADOW_STT_MAX_BYTES`: upper bound for user-question audio sent to the shadow STT lane.
- `EA_MEMORIAL_SHADOW_STT_ERROR_COOLDOWN_SECONDS`: cooldown after BlipAI auth/rate-limit errors (`401`, `403`, `429`) so one bad token does not slow every memorial turn.

Memorial shadow STT lookup order:

1. `EA_MEMORIAL_SHADOW_STT_API_KEY`
2. persisted refreshed token state at `EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH`
3. `BLIPAI_APP_API_TOKEN`

Memorial shadow STT refresh-token lookup order:

1. `EA_MEMORIAL_SHADOW_STT_REFRESH_TOKEN`
2. persisted refreshed token state at `EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH`
3. `BLIPAI_APP_REFRESH_TOKEN`

## Recommended Profiles

| Environment | EA_STORAGE_BACKEND | DATABASE_URL | EA_BOOTSTRAP_DB | Rationale |
|---|---|---|---|---|
| Local quick dev | `memory` | optional | `0` | Fast startup, no DB dependency |
| Local integration | `postgres` | required | `1` | Validate DB-backed runtime behavior |
| CI smoke | `memory` | unset | `0` | Deterministic and lightweight |
| CI integration | `postgres` | required | `1` | Exercises migrations and DB backends |
| Staging | `postgres` | required | `1` (initial), `0` (steady state) | Closest to production |
| Production | `postgres` | required | controlled rollout only | Avoid silent fallback and enforce durability (`EA_RUNTIME_MODE=prod`) |

## Guardrails

- Prefer `EA_STORAGE_BACKEND`; use `EA_LEDGER_BACKEND` only for temporary compatibility with older env files.
- Set `EA_RUNTIME_MODE=prod` for production-like boots so missing/unavailable Postgres fails fast instead of degrading to memory.
- For production/staging, use `EA_STORAGE_BACKEND=postgres` instead of `auto`.
- Use `auto` only where memory fallback is acceptable.
- Run `scripts/db_status.sh` after bootstrap to verify kernel table presence.
- `EA_RUNTIME_MODE=prod` requires `EA_SIGNING_SECRET`; outside prod, omitting it falls back to a process-local ephemeral secret.
- `EA_RUNTIME_MODE=prod` also requires a real workspace-access token binding source (`EA_PUBLIC_APP_BASE_URL`, `EA_GOOGLE_OAUTH_REDIRECT_URI`, or `EA_WORKSPACE_ACCESS_TOKEN_ISSUER`) plus non-placeholder `EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE` and `EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION`.
- The base `docker-compose.yml` intentionally omits `/docker` and `/var/run/docker.sock`; add `docker-compose.host-tools.yml` only for workflows that truly need host repo access or Docker control.
- The Cloudflare tunnel is opt-in; add `docker-compose.cloudflared.yml` only when you explicitly want to expose EA through Cloudflare Tunnel.
